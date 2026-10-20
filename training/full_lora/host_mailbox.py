#!/usr/bin/env python3
"""Execute owner-published jobs from this host's private Hugging Face mailbox."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import time
from email.utils import parsedate_to_datetime

ROOT = Path('/workspace/jovovich-full-lora')
REPO = 'ataeff/jovovich'
LOG_INTERVAL = 120
UPLOAD_RETRY_SECONDS = 1800


class UploadDeadline(TimeoutError):
    """An ancillary mailbox write exhausted its bounded retry window."""
    def __init__(self, message, retry_not_before=0.0):
        super().__init__(message)
        self.retry_not_before = retry_not_before


def transient(error):
    status = getattr(getattr(error, 'response', None), 'status_code', None)
    if type(status) is int:
        return status in (408, 429) or 500 <= status <= 599
    types = (TimeoutError, ConnectionError)
    try:
        from requests.exceptions import Timeout, ConnectionError as RequestsConnectionError
        types += (Timeout, RequestsConnectionError)
    except ImportError:
        pass
    return isinstance(error, types)


def retry_after(error, wall_clock=time.time):
    headers = getattr(getattr(error, 'response', None), 'headers', {}) or {}
    raw = headers.get('Retry-After', headers.get('retry-after'))
    if raw is None:
        return None
    try:
        seconds = int(raw)
        return float(max(0, seconds))
    except (TypeError, ValueError):
        try:
            return max(0.0, parsedate_to_datetime(raw).timestamp() - wall_clock())
        except (TypeError, ValueError, OverflowError):
            return None


def retry_write(call, *, deadline, clock=time.monotonic, sleep=time.sleep,
                wall_clock=time.time):
    """Retry one immutable payload; an expired window never authorizes a write."""
    attempts, retry_not_before = 0, 0.0
    while clock() < deadline:
        try:
            return call()
        except Exception as error:
            if not transient(error):
                raise
            attempts += 1
            delay = retry_after(error, wall_clock)
            if delay is None:
                delay = min(60.0, 2.0 ** min(attempts - 1, 6))
            retry_not_before = clock() + max(delay, 1.0)
            # Do not shorten Retry-After and send too early. If it exceeds this
            # attempt's budget, wait out the budget and leave the child alive.
            remaining = deadline - clock()
            if remaining <= 0:
                break
            print(json.dumps({'event': 'mailbox_write_retry', 'attempt': attempts,
                              'delay_seconds': min(delay, remaining),
                              'http_status': getattr(getattr(error, 'response', None), 'status_code', None),
                              'exception_type': type(error).__name__}), flush=True)
            sleep(min(max(delay, 1.0), remaining))
    raise UploadDeadline('mailbox write retry deadline exceeded', retry_not_before) from None


class Mailbox:
    def __init__(self, api, prefix, pod, *, clock=time.monotonic, sleep=time.sleep,
                 wall_clock=time.time, retry_seconds=UPLOAD_RETRY_SECONDS):
        self.api, self.prefix, self.pod = api, prefix, pod
        self.clock, self.sleep, self.wall_clock = clock, sleep, wall_clock
        self.retry_seconds = retry_seconds
        self.retry_not_before = 0.0

    def upload(self, name, data, message):
        # Snapshot paths before retry: every attempt sends the same closed bytes.
        if isinstance(data, Path):
            data = data.read_bytes()
        deadline = self.clock() + self.retry_seconds
        # Preserve a server Retry-After across exhausted windows and different
        # status/log payloads; a new upload must not reset the rate-limit clock.
        if self.clock() < self.retry_not_before:
            self.sleep(min(self.retry_not_before - self.clock(), self.retry_seconds))
        def attempt():
            try:
                return self.api.upload_file(repo_id=REPO,
                    path_in_repo=self.prefix + '/' + name,
                    path_or_fileobj=data, commit_message=message)
            except Exception as error:
                delay = retry_after(error, self.wall_clock) if transient(error) else None
                if delay is not None:
                    self.retry_not_before = max(self.retry_not_before, self.clock() + max(delay, 1.0))
                raise
        try:
            return retry_write(attempt, deadline=deadline, clock=self.clock,
                sleep=self.sleep, wall_clock=self.wall_clock)
        except UploadDeadline as error:
            self.retry_not_before = max(self.retry_not_before, error.retry_not_before)
            error.retry_not_before = self.retry_not_before
            raise

    def status(self, phase, **fields):
        payload = {'phase': phase, 'updated_at': self.wall_clock(), 'pod': self.pod, **fields}
        self.upload('status.json', json.dumps(payload, sort_keys=True).encode(),
                    'JOVOVICH host status')
        print(json.dumps(payload), flush=True)


def initial_status(mailbox, **fields):
    """A rate-limited ready notification must not restart the host process."""
    while True:
        try:
            mailbox.status('ready', **fields)
            return
        except UploadDeadline as error:
            print(json.dumps({'event': 'mailbox_ready_deferred',
                              'exception_type': type(error).__name__}), flush=True)
            mailbox.sleep(min(max(error.retry_not_before - mailbox.clock(), 30), 300))


def monitor_process(process, log, upload, *, clock=time.monotonic, sleep=time.sleep):
    """Ancillary logging cannot kill or restart an already running native job."""
    last_attempt, last_digest, chunk, retry_not_before = clock(), None, 0, 0.0
    while process.poll() is None:
        sleep(15)
        if process.poll() is not None or clock() - last_attempt < LOG_INTERVAL or clock() < retry_not_before:
            continue
        last_attempt = clock()
        try:
            snapshot = log.read_bytes()
            checksum = hashlib.sha256(snapshot).digest()
            if checksum == last_digest:
                continue
            upload(f'log-{chunk:06d}.txt', snapshot)
            last_digest = checksum
            chunk += 1
        except Exception as error:
            retry_not_before = max(retry_not_before, getattr(error, 'retry_not_before', 0.0))
            # Checkpoints/results have their own verified archive barrier. A
            # failed progress snapshot must not destroy the process doing work.
            print(json.dumps({'event': 'mailbox_log_deferred',
                              'exception_type': type(error).__name__}), flush=True)
    return process.wait()


def should_stop(job, result):
    return ((result != 0 and job.get('stop_on_failure', True)) or
            (result == 0 and job.get('stop_on_success', False)))


def close_job(mailbox, directory, job):
    """Retry final delivery after an outage without executing the job again."""
    result = json.loads((directory / 'closed.json').read_text())['returncode']
    if not (directory / 'delivered.json').exists():
        mailbox.upload(f'jobs/{job["id"]}/final.log', directory / 'job.log',
                       'JOVOVICH job closed log')
        mailbox.status('closed', job=job['id'], returncode=result)
        (directory / 'delivered.json').write_text(json.dumps({'returncode': result}))
    return should_stop(job, result)


def main():
    # Imports and private configuration are deliberately delayed until main so
    # retry/process policy can be checked without an HF installation or token.
    from huggingface_hub import HfApi, hf_hub_download
    from huggingface_hub.utils import EntryNotFoundError
    pod = os.environ['RUNPOD_POD_ID']
    prefix = 'control/full-lora-' + pod
    token = (ROOT / 'hf.key').read_text().strip()
    api = HfApi(token=token)
    if not api.repo_info(REPO).private:
        raise ValueError('control repository must be private')
    mailbox = Mailbox(api, prefix, pod)
    initial_status(mailbox, root=str(ROOT), gpu=subprocess.check_output(
        ['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader'], text=True).strip())
    (ROOT / 'jobs').mkdir(exist_ok=True)
    while not (ROOT / 'STOP').exists():
        try:
            path = hf_hub_download(REPO, prefix + '/next.json', token=token, force_download=True)
            job = json.loads(Path(path).read_text())
            ident = job['id']
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,80}', ident):
                raise ValueError('invalid job id')
            directory = ROOT / 'jobs' / ident
            if directory.exists():
                if (directory / 'closed.json').exists() and close_job(mailbox, directory, job):
                    (ROOT / 'STOP').touch()
                    continue
                time.sleep(10)
                continue
            bundle = Path(hf_hub_download(REPO, job['bundle'], token=token,
                                        revision=job['revision'], force_download=True))
            if hashlib.sha256(bundle.read_bytes()).hexdigest() != job['sha256']:
                raise ValueError('source bundle checksum mismatch')
            # A failed running-status write must leave no job directory that a
            # later poll could mistake for an already started child.
            mailbox.status('running', job=ident, bundle_sha256=job['sha256'])
            directory.mkdir()
            with tarfile.open(bundle) as tar:
                for member in tar.getmembers():
                    p = Path(member.name)
                    if p.is_absolute() or '..' in p.parts or not (member.isdir() or member.isfile()):
                        raise ValueError('unsafe bundle member')
                tar.extractall(directory)
            (directory / 'job.json').write_text(json.dumps(job, indent=2))
            script = directory / 'run.sh'
            if not script.is_file():
                raise ValueError('missing fixed job entrypoint')
            log = directory / 'job.log'
            env = {k: v for k, v in os.environ.items() if k not in
                   ('JOV_RUNPOD_KEY', 'JOV_HF_TOKEN', 'HF_TOKEN', 'RUNPOD_API_KEY')}
            with log.open('wb') as output:
                process = subprocess.Popen(['bash', str(script)], cwd=directory,
                    stdout=output, stderr=subprocess.STDOUT, env=env)
                result = monitor_process(process, log, lambda name, data: mailbox.upload(
                    f'jobs/{ident}/{name}', data, 'JOVOVICH job log'))
            # Preserve the exit result locally before any further remote write.
            (directory / 'closed.json').write_text(json.dumps({'returncode': result}))
            if close_job(mailbox, directory, job):
                (ROOT / 'STOP').touch()
        except EntryNotFoundError:
            time.sleep(10)
        except Exception as error:
            print(json.dumps({'event': 'mailbox_failure',
                              'exception_type': type(error).__name__}), flush=True)
            if transient(error) or isinstance(error, UploadDeadline):
                # No process is running here: live snapshots are handled above.
                # A temporary mailbox outage does not justify destroying a pod.
                delay = (max(0.0, error.retry_not_before - time.monotonic())
                         if isinstance(error, UploadDeadline) else retry_after(error))
                time.sleep(min(max(delay if delay is not None else 30, 1), 300))
                continue
            try:
                mailbox.status('error', exception_type=type(error).__name__)
            except Exception:
                pass
            (ROOT / 'STOP').touch()
            return 1
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'event': 'mailbox_failure',
                          'exception_type': type(error).__name__}), flush=True)
        raise SystemExit(1) from None
