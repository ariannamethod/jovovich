"""Foreground watchdog for one paid CPU pod; standard library, no auto-resume.

The public module and the reviewed preparation shell script can be embedded in
the pod entrypoint. Setup, checkout and training all run inside the same deadline.
Only this parent retains the Runpod API credential. The child receives a private
HF token file and must pin the requested source before calling the native launcher.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request


API_ORIGIN = 'https://api.runpod.io'
MAX_SECONDS = 12 * 60 * 60
MAX_HOURLY_COST = Decimal('0.20')
STOP_RESERVE_SECONDS = 90
POD_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{2,63}\Z')
RUN_PREFIX = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,39}\Z')


class BootstrapError(RuntimeError):
    """Messages contain fixed labels only, never service bodies or credentials."""


def need(condition, message):
    if not condition:
        raise BootstrapError(message)


def utc():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        raise BootstrapError('Runpod API redirects are forbidden')


class RunpodAPI:
    def __init__(self, key, pod_id, opener=None):
        need(isinstance(key, str) and key and '\n' not in key and '\r' not in key,
             'missing or invalid Runpod control key')
        need(isinstance(pod_id, str) and POD_ID.fullmatch(pod_id), 'invalid own pod ID')
        self._key = key
        self.pod_id = pod_id
        self._opener = opener or urllib.request.build_opener(NoRedirect())

    def _request(self, action=None):
        url = API_ORIGIN + '/v2/pods/' + self.pod_id
        data = None
        if action is not None:
            need(action == 'stop', 'unsupported pod action')
            url += '/action'
            data = b'{"action":"stop"}'
        request = urllib.request.Request(url, data=data,
            headers={'Authorization': 'Bearer ' + self._key, 'Content-Type': 'application/json',
                     'User-Agent': 'jovovich-runpod-watchdog/1.0'},
            method='GET' if data is None else 'POST')
        try:
            with self._opener.open(request, timeout=10) as response:
                raw = response.read(1024 * 1024 + 1)
                need(len(raw) <= 1024 * 1024, 'Runpod API response exceeds limit')
                need(200 <= response.status < 300, 'Runpod API returned a non-success status')
                if action == 'stop':
                    return {'http_status': response.status}
                return json.loads(raw)
        except urllib.error.HTTPError as error:
            raise BootstrapError('Runpod API HTTP ' + str(error.code)) from None
        except BootstrapError:
            raise
        except Exception:
            raise BootstrapError('Runpod API request failed') from None

    def get_pod(self):
        return self._request()

    def stop(self):
        return self._request('stop')


class Redactor:
    """Keep enough trailing bytes to mask a secret split across pipe reads."""
    def __init__(self, secrets):
        self.secrets = sorted({s.encode() for s in secrets if s}, key=len, reverse=True)
        self.keep = max((len(s) for s in self.secrets), default=1) - 1
        self.pending = b''

    def feed(self, data, final=False):
        self.pending += data
        boundary = len(self.pending) if final else max(0, len(self.pending) - self.keep)
        out = bytearray()
        position = 0
        while position < boundary:
            secret = next((s for s in self.secrets if self.pending.startswith(s, position)), None)
            if secret:
                out.extend(b'[REDACTED]')
                position += len(secret)
            else:
                out.append(self.pending[position])
                position += 1
        self.pending = self.pending[position:]
        return bytes(out)


def child_environment(environment):
    allowed = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TZ', 'USER', 'LOGNAME', 'TMPDIR',
               'SSL_CERT_FILE', 'SSL_CERT_DIR')
    result = {key: environment[key] for key in allowed if key in environment}
    result.update(PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1', PIP_DISABLE_PIP_VERSION_CHECK='1')
    return result


def validate_config(config):
    need(isinstance(config.pod_id, str) and POD_ID.fullmatch(config.pod_id), 'invalid own pod ID')
    need(RUN_PREFIX.fullmatch(config.run_prefix), 'invalid fresh run prefix')
    need(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _.:-]{0,127}', config.expected_name), 'invalid expected pod name')
    need(re.fullmatch(r'[0-9a-f]{40}', config.source_sha), 'source must be a full Git SHA')
    need(re.fullmatch(r'[0-9a-f]{64}', config.command_sha256), 'preparation script SHA256 required')
    need(math.isfinite(config.max_seconds) and 0 < config.max_seconds <= MAX_SECONDS,
         'deadline must be positive and at most 12 hours')
    need(math.isfinite(config.heartbeat_seconds) and 0 < config.heartbeat_seconds <= 60,
         'heartbeat must be positive and at most 60 seconds')
    need(Path(config.repo).is_absolute() and Path(config.state_dir).is_absolute(),
         'checkout and watchdog state paths must be absolute')
    repo = Path(config.repo).resolve()
    state = Path(config.state_dir).resolve()
    need(state != repo and repo not in state.parents,
         'watchdog state must be outside the checkout')
    command = Path(config.command)
    need(command.is_absolute() and command.is_file() and not command.is_symlink(),
         'reviewed preparation script must be an absolute regular file')
    need(hashlib.sha256(command.read_bytes()).hexdigest() == config.command_sha256,
         'preparation script SHA256 mismatch')


def verify_pod(pod, config, *, allow_starting=False):
    need(isinstance(pod, dict), 'invalid own pod response')
    need(pod.get('id') == config.pod_id and pod.get('name') == config.expected_name,
         'own pod identity or expected name mismatch')
    # Exact documented fields are intentional: missing cost/status fails closed.
    statuses = ('RUNNING', 'STARTING', 'PROVISIONING') if allow_starting else ('RUNNING',)
    need(pod.get('status') in statuses, 'own pod is not running or starting')
    need(pod.get('locked') is False, 'own pod is locked or lock state is unavailable')
    need(isinstance(pod.get('cpu'), dict) and pod.get('gpu') is None, 'own pod must be a CPU pod')
    if pod.get('status') == 'RUNNING':
        need(isinstance(pod.get('actions'), list) and 'stop' in pod['actions'],
             'own pod does not permit a stop transition')
    try:
        price = Decimal(str(pod['cost']))
    except (KeyError, InvalidOperation, ValueError):
        raise BootstrapError('own pod hourly cost unavailable') from None
    need(price.is_finite() and 0 <= price <= MAX_HOURLY_COST, 'own pod hourly cost exceeds cap')
    return {'id': config.pod_id, 'name': config.expected_name, 'status': pod['status'],
            'hourly_cost_usd': str(price), 'hourly_cap_usd': str(MAX_HOURLY_COST)}


def supervise(config, api, hf_token, control_key, *, environment=None, output=None, extra_secrets=(),
              stop_delays=(1, 2, 4, 8), clock=time.monotonic, sleep=time.sleep):
    """Return only after a stop request succeeds or all bounded retries fail."""
    environment = os.environ if environment is None else environment
    output = sys.stdout.buffer if output is None else output
    state_dir = Path(config.state_dir).resolve()
    state = {'schema': 'jovovich.runpod-watchdog.v1', 'started_at': utc(),
             'pod_id': config.pod_id, 'expected_name': config.expected_name,
             'source_sha': config.source_sha, 'run_prefix': config.run_prefix,
             'repo': str(Path(config.repo).resolve()), 'max_seconds': config.max_seconds,
             'phase': 'preflight', 'child_exit_code': None, 'stop_attempts': []}
    start = clock()
    # Reserve 90 seconds of the 12-hour envelope for process shutdown and API retries.
    # A remote outage can still prevent a stop; that is reported, never called success.
    stop_reserve = min(STOP_RESERVE_SECONDS, config.max_seconds / 10)
    deadline = start + config.max_seconds - stop_reserve
    state['stop_reserve_seconds'] = stop_reserve
    state['work_budget_seconds'] = config.max_seconds - stop_reserve
    verified_identity = False
    owned_state = False
    token_path = None
    child = None
    caught_signal = []
    handlers = {}
    redactor = Redactor([hf_token, control_key, *extra_secrets])
    log = None
    stdout_open = True

    def write_output(raw, *, best_effort=False):
        nonlocal stdout_open
        if log is not None:
            try:
                log.write(raw)
                log.flush()
            except OSError:
                state['log_write_failed'] = True
                if not best_effort:
                    raise BootstrapError('watchdog log write failed') from None
        if stdout_open:
            try:
                output.write(raw)
                output.flush()
            except (BrokenPipeError, OSError):
                stdout_open = False

    def save(*, best_effort=False):
        state.update(updated_at=utc(), elapsed_seconds=round(clock() - start, 6))
        if owned_state:
            try:
                atomic_json(state_dir / 'state.json', state)
            except OSError:
                state['state_write_failed'] = True
                if not best_effort:
                    raise BootstrapError('watchdog state write failed') from None

    def notice(event, *, best_effort=False):
        write_output((json.dumps({'watchdog': event, 'phase': state['phase'],
                                 'elapsed_seconds': round(clock() - start, 3)}) + '\n').encode(),
                     best_effort=best_effort)

    def on_signal(number, frame):
        caught_signal.append(number)

    def terminate_child():
        if child is not None:
            # Also terminate descendants if the setup shell has already exited.
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait(timeout=5)
            state['child_exit_code'] = child.returncode

    try:
        for number in (signal.SIGTERM, signal.SIGINT):
            handlers[number] = signal.signal(number, on_signal)
        pod = api.get_pod()
        verified_identity = isinstance(pod, dict) and pod.get('id') == config.pod_id and pod.get('name') == config.expected_name
        validate_config(config)
        startup_deadline = min(deadline, start + 60)
        while True:
            state['pod'] = verify_pod(pod, config, allow_starting=True)
            if pod['status'] == 'RUNNING':
                break
            need(clock() < startup_deadline and not caught_signal, 'own pod did not become running before startup deadline')
            sleep(min(2, max(0, startup_deadline - clock())))
            pod = api.get_pod()
        state['pod'] = verify_pod(pod, config)
        state_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        owned_state = True
        os.chmod(state_dir, 0o700)
        log = (state_dir / 'child.log').open('xb')
        os.chmod(state_dir / 'child.log', 0o600)
        save()
        need(isinstance(hf_token, str) and hf_token.strip() and '\n' not in hf_token and '\r' not in hf_token,
             'missing or invalid HF archive credential')
        token_path = state_dir / 'hf-token'
        fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(hf_token)
            stream.flush()
            os.fsync(stream.fileno())
        # Bind the actual executable bytes, not a mutable /tmp pathname.
        prep_bytes = Path(config.command).read_bytes()
        need(hashlib.sha256(prep_bytes).hexdigest() == config.command_sha256,
             'preparation script changed after validation')
        prep_path = state_dir / 'prepare-host.sh'
        fd = os.open(prep_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(prep_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        need(clock() < deadline and not caught_signal, 'launch deadline or signal reached before child start')
        command = [str(prep_path), str(token_path), config.run_prefix, config.source_sha]
        state.update(phase='running', command_sha256=config.command_sha256,
                     child_argv=['bash', *command], deadline_seconds=config.max_seconds)
        save()
        child = subprocess.Popen(['bash', *command], cwd=str(state_dir),
            env=child_environment(environment), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        state['child_pid'] = child.pid
        save()
        notice('child-started')
        next_heartbeat = clock()
        selector = selectors.DefaultSelector()
        selector.register(child.stdout, selectors.EVENT_READ)
        try:
            while True:
                current = clock()
                if caught_signal:
                    state.update(phase='interrupted', signal=caught_signal[0])
                    break
                if current >= deadline:
                    state['phase'] = 'deadline'
                    break
                if current >= next_heartbeat:
                    save()
                    notice('heartbeat')
                    next_heartbeat = current + config.heartbeat_seconds
                for key, events in selector.select(min(0.25, max(0, deadline - current))):
                    raw = os.read(key.fd, 65536)
                    if raw:
                        write_output(redactor.feed(raw))
                    else:
                        selector.unregister(key.fileobj)
                code = child.poll()
                if code is not None and not selector.get_map():
                    state.update(child_exit_code=code, phase='child-succeeded' if code == 0 else 'child-failed')
                    break
        finally:
            selector.close()
        save()
    except Exception as error:
        state.update(phase='bootstrap-failed', error=error.args[0] if isinstance(error, BootstrapError) else type(error).__name__)
        save(best_effort=True)
        notice('failed', best_effort=True)
    finally:
        try:
            terminate_child()
        except OSError:
            state['child_termination_failed'] = True
        except subprocess.TimeoutExpired:
            state['child_termination_failed'] = True
        write_output(redactor.feed(b'', final=True), best_effort=True)
        if token_path is not None:
            try:
                token_path.unlink(missing_ok=True)
            except OSError:
                state['hf_token_cleanup_failed'] = True
        try:
            state['hf_token_removed'] = token_path is None or not token_path.exists()
        except OSError:
            state['hf_token_removed'] = False
            state['hf_token_cleanup_failed'] = True
        state['stop_requested'] = False
        if verified_identity:
            # Keep this evidence durable before the stop API can kill this parent.
            for attempt in range(len(stop_delays) + 1):
                state['stop_attempts'].append({'attempt': attempt + 1, 'started_at': utc(), 'status': 'requesting'})
                save(best_effort=True)
                notice('requesting-own-pod-stop', best_effort=True)
                try:
                    result = api.stop()
                    state['stop_attempts'][-1].update(status='accepted', **result)
                    state['stop_requested'] = True
                    break
                except Exception:
                    state['stop_attempts'][-1]['status'] = 'failed'
                    save(best_effort=True)
                    if attempt < len(stop_delays):
                        sleep(stop_delays[attempt])
        else:
            state['stop_skipped_reason'] = 'own pod identity was not verified'
        state['finished_at'] = utc()
        save(best_effort=True)
        if owned_state:
            try:
                atomic_json(state_dir / 'exit.json', state)
            except OSError:
                state['exit_write_failed'] = True
        notice('finished', best_effort=True)
        if child is not None and child.stdout is not None:
            child.stdout.close()
        if log is not None:
            try:
                os.fsync(log.fileno())
                log.close()
            except OSError:
                state['log_write_failed'] = True
        for number, handler in handlers.items():
            signal.signal(number, handler)
    if not state['stop_requested']:
        return 3
    return 0 if state['phase'] == 'child-succeeded' and not any(state.get(field) for field in
        ('child_termination_failed', 'hf_token_cleanup_failed', 'log_write_failed',
         'state_write_failed', 'exit_write_failed')) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pod-id', default=os.environ.get('RUNPOD_POD_ID'))
    parser.add_argument('--expected-name', required=True)
    parser.add_argument('--run-prefix', required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--repo', default='/workspace/jovovich')
    parser.add_argument('--state-dir', required=True)
    parser.add_argument('--command', required=True)
    parser.add_argument('--command-sha256', required=True)
    parser.add_argument('--max-seconds', type=float, default=MAX_SECONDS)
    parser.add_argument('--heartbeat-seconds', type=float, default=60)
    config = parser.parse_args()
    account_key = os.environ.pop('JOVOVICH_RUNPOD_CONTROL_KEY', '')
    scoped_key = os.environ.pop('RUNPOD_API_KEY', '')
    control_key = account_key or scoped_key
    hf_token = os.environ.pop('HF_TOKEN', '')
    try:
        need(config.pod_id is not None, 'missing own pod ID')
        advertised_id = os.environ.get('RUNPOD_POD_ID')
        need(not advertised_id or advertised_id == config.pod_id, 'own pod ID disagrees with platform environment')
        api = RunpodAPI(control_key, config.pod_id)
        return supervise(config, api, hf_token, control_key, extra_secrets=(account_key, scoped_key))
    except BootstrapError as error:
        print('jovovich watchdog: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
