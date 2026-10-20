"""Mailbox rate limiting and live-child policy: fake HF, clock and process."""
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
import hashlib
import io
import sys
import tarfile
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'training/full_lora/host_mailbox.py'
spec = importlib.util.spec_from_file_location('host_mailbox', SOURCE)
mailbox = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mailbox)  # No HF package, environment or token required.


class HTTPError(Exception):
    def __init__(self, status, retry_after=None):
        self.response = types.SimpleNamespace(status_code=status,
            headers={} if retry_after is None else {'Retry-After': retry_after})


class Clock:
    def __init__(self):
        self.now, self.sleeps, self.on_sleep = 0.0, [], None
    def __call__(self):
        return self.now
    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds
        if self.on_sleep:
            self.on_sleep(self.now)


class API:
    def __init__(self, errors=()):
        self.errors, self.calls, self.successes = list(errors), [], []
    def upload_file(self, **kwargs):
        self.calls.append(kwargs)
        if self.errors:
            error = self.errors.pop(0)
            if error:
                raise error
        self.successes.append(kwargs)
        return 'ack'


class Process:
    def __init__(self, clock, until=390, result=0):
        self.clock, self.until, self.result = clock, until, result
    def poll(self):
        return self.result if self.clock() >= self.until else None
    def wait(self):
        assert self.poll() is not None
        return self.result
    def terminate(self):
        raise AssertionError('mailbox must not terminate the live child')
    kill = terminate


def publisher(api, clock, budget=60):
    return mailbox.Mailbox(api, 'fixture', 'pod', clock=clock, sleep=clock.sleep,
                           wall_clock=lambda: 0, retry_seconds=budget)


class MailboxTests(unittest.TestCase):
    def test_initial_status_retries_429_5xx_timeout_same_payload(self):
        clock = Clock()
        api = API([HTTPError(429, '7'), HTTPError(503), TimeoutError()])
        publisher(api, clock).status('ready', root='fixture')
        self.assertEqual(len(api.calls), 4)
        self.assertEqual(clock.sleeps, [7.0, 2.0, 4.0])
        self.assertEqual(len({call['path_or_fileobj'] for call in api.calls}), 1)
        self.assertEqual(json.loads(api.successes[0]['path_or_fileobj'])['phase'], 'ready')

    def test_retry_after_date_and_finite_deadline(self):
        self.assertEqual(mailbox.retry_after(HTTPError(429, 'Thu, 01 Jan 1970 00:00:09 GMT'), lambda: 2), 7)
        clock = Clock();api = API([HTTPError(429, '100')])
        with self.assertRaises(mailbox.UploadDeadline):
            publisher(api, clock, 5).status('running')
        self.assertEqual(clock.sleeps, [5])
        self.assertEqual(len(api.calls), 1, 'must not retry before Retry-After')
        pub = publisher(API([HTTPError(429, '100')]), clock, 5)
        with self.assertRaises(mailbox.UploadDeadline):pub.status('running')
        with self.assertRaises(mailbox.UploadDeadline):pub.status('closed')
        self.assertEqual(len(pub.api.calls), 1, 'new payload must respect prior Retry-After')

    def test_initial_ready_survives_exhausted_window_and_respects_cooldown(self):
        clock = Clock();api = API([HTTPError(429, '100')]);pub = publisher(api, clock, 5)
        mailbox.initial_status(pub, root='fixture')
        self.assertEqual(clock(), 100)
        self.assertEqual(len(api.calls), 2)
        self.assertEqual(len(api.successes), 1)

    def test_main_running_status_outage_does_not_leave_unstarted_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);(root/'hf.key').write_text('fixture')
            bundle = root/'bundle.tar'
            with tarfile.open(bundle, 'w') as tar:
                info=tarfile.TarInfo('run.sh');info.size=5;tar.addfile(info, io.BytesIO(b'exit\n'))
            job={'id':'job', 'bundle':'bundle.tar', 'revision':'a'*40,
                 'sha256':hashlib.sha256(bundle.read_bytes()).hexdigest(), 'stop_on_success':True}
            command=root/'next.json';command.write_text(json.dumps(job))
            clock=Clock();api=API();starts=[];polls=[];original_upload=api.upload_file
            def upload(**kwargs):
                if kwargs['path_in_repo'].endswith('status.json'):
                    payload=json.loads(kwargs['path_or_fileobj'])
                    if payload['phase']=='running' and clock()<100:
                        self.assertFalse((root/'jobs/job').exists())
                        raise HTTPError(429, '100')
                return original_upload(**kwargs)
            api.upload_file=upload;api.repo_info=lambda repo:types.SimpleNamespace(private=True)
            def download(repo, name, **kwargs):
                if name.endswith('next.json'):
                    polls.append(clock());self.assertFalse((root/'jobs/job').exists());return str(command)
                return str(bundle)
            hub=types.ModuleType('huggingface_hub');hub.HfApi=lambda **kwargs:api;hub.hf_hub_download=download
            utils=types.ModuleType('huggingface_hub.utils');utils.EntryNotFoundError=type('EntryNotFoundError',(Exception,),{})
            real_class=mailbox.Mailbox
            def make(*args):return real_class(*args,clock=clock,sleep=clock.sleep,wall_clock=lambda:0,retry_seconds=5)
            def process(*args,**kwargs):starts.append(clock());return Process(clock,until=0)
            with patch.dict(sys.modules,{'huggingface_hub':hub,'huggingface_hub.utils':utils}), patch.dict('os.environ',{'RUNPOD_POD_ID':'fixture'}), patch.object(mailbox,'ROOT',root), patch.object(mailbox,'Mailbox',make), patch.object(mailbox.time,'monotonic',clock), patch.object(mailbox.time,'sleep',clock.sleep), patch.object(mailbox.subprocess,'check_output',return_value='fixture GPU'), patch.object(mailbox.subprocess,'Popen',process):
                self.assertEqual(mailbox.main(),0)
            self.assertEqual(polls,[0,100]);self.assertEqual(starts,[100])
            self.assertTrue((root/'STOP').exists())
            self.assertTrue((root/'jobs/job/delivered.json').exists())

    def test_live_child_survives_429_and_only_changed_snapshots_upload(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / 'job.log';log.write_bytes(b'first')
            clock = Clock();api = API([HTTPError(429, '7')]);pub = publisher(api, clock)
            clock.on_sleep = lambda now: log.write_bytes(b'second') if now >= 270 else None
            starts = []
            def upload(name, data):
                starts.append(clock());return pub.upload(name, data, 'fixture')
            result = mailbox.monitor_process(Process(clock), log, upload, clock=clock, sleep=clock.sleep)
            self.assertEqual(result, 0)
            self.assertEqual([x['path_or_fileobj'] for x in api.successes], [b'first', b'second'])
            self.assertEqual(len(api.calls), 3)
            self.assertGreaterEqual(starts[0], 120)
            self.assertTrue(all(b-a >= 120 for a, b in zip(starts, starts[1:])))

    def test_exhausted_log_upload_does_not_stop_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / 'job.log';log.write_bytes(b'progress')
            clock = Clock();api = API([HTTPError(429, '1000')] * 3);pub = publisher(api, clock, 5)
            result = mailbox.monitor_process(Process(clock, until=270, result=7), log,
                lambda name, data: pub.upload(name, data, 'fixture'), clock=clock, sleep=clock.sleep)
            self.assertEqual(result, 7)
            self.assertGreaterEqual(clock(), 270)
            self.assertFalse(api.successes)

    def test_closed_delivery_retries_without_reexecution_and_stop_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary);(directory/'job.log').write_bytes(b'final')
            (directory/'closed.json').write_text('{"returncode":0}')
            clock = Clock();api = API([HTTPError(429, '100')]);pub = publisher(api, clock, 5)
            job = {'id':'done', 'stop_on_success':True}
            with self.assertRaises(mailbox.UploadDeadline):mailbox.close_job(pub, directory, job)
            self.assertFalse((directory/'delivered.json').exists())
            clock.sleep(95)  # Server Retry-After remains binding across windows.
            self.assertTrue(mailbox.close_job(pub, directory, job))
            count = len(api.calls)
            self.assertTrue(mailbox.close_job(pub, directory, job))
            self.assertEqual(len(api.calls), count)
        self.assertTrue(mailbox.should_stop({}, 1))
        self.assertFalse(mailbox.should_stop({'stop_on_failure':False}, 1))
        self.assertFalse(mailbox.should_stop({}, 0))

    def test_terminal_auth_is_not_retried(self):
        clock = Clock();api = API([HTTPError(401)])
        with self.assertRaises(HTTPError):publisher(api, clock).status('ready')
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(clock.sleeps, [])


if __name__ == '__main__':
    unittest.main()
