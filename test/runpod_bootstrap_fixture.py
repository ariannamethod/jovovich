"""No network: mocked own-pod API and real short-lived child processes."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import urllib.error


REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bootstrap', REPO / 'training/cloud/runpod_bootstrap.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)
HF_SECRET = 'hf_fake-archive-secret-xyz'
CONTROL_SECRET = 'fake-runpod-control-secret'
SCOPED_SECRET = 'fake-scoped-secret'
POD = {'id': 'pod_test123', 'name': 'jovovich-test', 'status': 'RUNNING',
       'cost': 0.184, 'actions': ['stop', 'restart'], 'locked': False,
       'cpu': {'id': 'cpu5g', 'vcpuCount': 4, 'memory': 16}}


class FakeAPI:
    def __init__(self, pod=None, failures=0):
        self.pod = copy.deepcopy(POD if pod is None else pod)
        self.failures = failures
        self.stops = 0

    def get_pod(self):
        return self.pod

    def stop(self):
        self.stops += 1
        if self.stops <= self.failures:
            raise bootstrap.BootstrapError('Runpod API HTTP 503')
        return {'http_status': 200}


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.script = self.root / 'setup.sh'
        self.script.write_text('#!/bin/bash\nexit 0\n')
        self.config = SimpleNamespace(pod_id=POD['id'], expected_name=POD['name'],
            run_prefix='run-test', source_sha='a' * 40, repo=str(self.root / 'checkout'),
            state_dir=str(self.root / 'run-test-host'), command=str(self.script),
            command_sha256=hashlib.sha256(self.script.read_bytes()).hexdigest(),
            max_seconds=3.0, heartbeat_seconds=0.1)
        self.output = io.BytesIO()

    def tearDown(self):
        self.directory.cleanup()

    def script_text(self, text):
        self.script.write_text(text)
        self.config.command_sha256 = hashlib.sha256(self.script.read_bytes()).hexdigest()

    def run_child(self, api=None, **kwargs):
        self.api = api or FakeAPI()
        environment = dict(os.environ, HF_TOKEN=HF_SECRET, RUNPOD_API_KEY=SCOPED_SECRET,
            JOVOVICH_RUNPOD_CONTROL_KEY=CONTROL_SECRET, SECRET_UNRELATED='never-child',
            NT_FAKE='never-child', PYTHONPATH='/should/not/inherit')
        return bootstrap.supervise(self.config, self.api, HF_SECRET, CONTROL_SECRET,
            environment=environment, output=self.output, extra_secrets=(SCOPED_SECRET,),
            stop_delays=(0, 0), **kwargs)

    def manifest(self):
        return json.loads((Path(self.config.state_dir) / 'exit.json').read_text())

    def test_success_credentials_logs_and_provenance(self):
        self.script_text('''#!/bin/bash
set -eu
python3 - "$1" "$2" "$3" <<'PY'
import json, os, pathlib, stat, sys
p = pathlib.Path(sys.argv[1])
secret = p.read_text()
assert stat.S_IMODE(p.stat().st_mode) == 0o600
assert stat.S_IMODE(p.parent.stat().st_mode) == 0o700
for key in ('HF_TOKEN', 'RUNPOD_API_KEY', 'JOVOVICH_RUNPOD_CONTROL_KEY',
            'SECRET_UNRELATED', 'NT_FAKE', 'PYTHONPATH'):
    assert key not in os.environ, key
assert sys.argv[2:] == ['run-test', 'a' * 40]
os.write(1, secret[:5].encode())
os.write(1, secret[5:].encode() + b'\\nchild-completed\\n')
pathlib.Path('child-proof.json').write_text(json.dumps({'token_mode': '0600', 'clean_env': True}))
PY
''')
        self.assertEqual(self.run_child(), 0)
        self.assertEqual(self.api.stops, 1)
        result = self.manifest()
        self.assertEqual(result['phase'], 'child-succeeded')
        self.assertTrue(result['stop_requested'])
        self.assertTrue(result['hf_token_removed'])
        self.assertEqual(result['command_sha256'], self.config.command_sha256)
        self.assertEqual(result['pod']['hourly_cost_usd'], '0.184')
        self.assertEqual((Path(self.config.state_dir) / 'prepare-host.sh').read_bytes(), self.script.read_bytes())
        for path in Path(self.config.state_dir).iterdir():
            content = path.read_bytes()
            for secret in (HF_SECRET, CONTROL_SECRET, SCOPED_SECRET):
                self.assertNotIn(secret.encode(), content)
        self.assertNotIn(HF_SECRET.encode(), self.output.getvalue())
        self.assertIn(b'[REDACTED]', self.output.getvalue())

    def test_failure_stops_and_records_exit(self):
        self.script_text('exit 7\n')
        self.assertEqual(self.run_child(), 1)
        self.assertEqual(self.api.stops, 1)
        self.assertEqual(self.manifest()['child_exit_code'], 7)

    def test_deadline_stops_and_kills_child(self):
        self.script_text('sleep 30\n')
        self.config.max_seconds = 0.2
        self.assertEqual(self.run_child(), 1)
        self.assertEqual(self.api.stops, 1)
        state = self.manifest()
        self.assertEqual(state['phase'], 'deadline')
        self.assertIsNotNone(state['child_exit_code'])
        self.assertTrue(state['hf_token_removed'])

    def test_signal_stops_and_kills_child(self):
        self.script_text('kill -TERM "$PPID"\nsleep 30\n')
        self.assertEqual(self.run_child(), 1)
        self.assertEqual(self.manifest()['phase'], 'interrupted')
        self.assertEqual(self.api.stops, 1)

    def test_retry_stop_and_exhaustion(self):
        self.assertEqual(self.run_child(FakeAPI(failures=2)), 0)
        self.assertEqual(self.api.stops, 3)
        self.assertEqual([x['status'] for x in self.manifest()['stop_attempts']], ['failed', 'failed', 'accepted'])
        self.config.state_dir = str(self.root / 'other-host')
        self.assertEqual(self.run_child(FakeAPI(failures=3)), 3)
        self.assertEqual(self.api.stops, 3)
        self.assertFalse(self.manifest()['stop_requested'])

    def test_preflight_rejects_cost_status_schema_and_no_resume(self):
        invalids = [{'cost': 0.201}, {'status': 'ERROR'}, {'cost': None},
                    {'actions': ['restart']}, {'locked': True}, {'gpu': {'id': 'gpu'}}]
        for number, change in enumerate(invalids):
            with self.subTest(change=change):
                self.config.state_dir = str(self.root / ('invalid-' + str(number)))
                api = FakeAPI(dict(POD, **change))
                self.assertEqual(self.run_child(api), 1)
                self.assertEqual(api.stops, 1)
                self.assertFalse(Path(self.config.state_dir).exists())
        self.config.state_dir = str(self.root / 'existing')
        Path(self.config.state_dir).mkdir()
        sentinel = Path(self.config.state_dir) / 'sentinel'
        sentinel.write_text('untouched')
        self.assertEqual(self.run_child(), 1)
        self.assertEqual(self.api.stops, 1)
        self.assertEqual(list(Path(self.config.state_dir).iterdir()), [sentinel])
        self.assertEqual(sentinel.read_text(), 'untouched')

    def test_identity_mismatch_never_stops_other_pod(self):
        self.assertEqual(self.run_child(FakeAPI(dict(POD, id='pod_other'))), 3)
        self.assertEqual(self.api.stops, 0)
        self.assertFalse(Path(self.config.state_dir).exists())

    def test_bad_command_hash_stops_without_child(self):
        self.config.command_sha256 = 'b' * 64
        self.assertEqual(self.run_child(), 1)
        self.assertEqual(self.api.stops, 1)
        self.assertFalse(Path(self.config.state_dir).exists())

    def test_state_io_failure_cannot_skip_stop(self):
        with mock.patch.object(bootstrap, 'atomic_json', side_effect=OSError(28, 'disk full')):
            self.assertEqual(self.run_child(), 1)
        self.assertEqual(self.api.stops, 1)
        self.assertNotIn(b'child-started', self.output.getvalue())

    def test_log_io_failure_cannot_skip_stop(self):
        original = Path.open
        def open_path(path, *args, **kwargs):
            if path.name == 'child.log':
                stream = mock.Mock(wraps=original(path, *args, **kwargs))
                stream.write.side_effect = OSError(28, 'disk full')
                return stream
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, 'open', open_path):
            self.assertEqual(self.run_child(), 1)
        self.assertEqual(self.api.stops, 1)
        self.assertTrue(self.manifest()['log_write_failed'])
        self.assertTrue(self.manifest()['hf_token_removed'])

    def test_starting_preflight_waits_then_launches(self):
        api = FakeAPI()
        api.get_pod = mock.Mock(side_effect=[dict(POD, status='STARTING'), POD])
        self.assertEqual(self.run_child(api, sleep=lambda delay: None), 0)
        self.assertEqual(api.get_pod.call_count, 2)
        self.assertEqual(api.stops, 1)

    def test_missing_hf_fails_closed_and_stops(self):
        api = FakeAPI()
        self.assertEqual(bootstrap.supervise(self.config, api, '', CONTROL_SECRET,
            output=self.output, stop_delays=()), 1)
        self.assertEqual(api.stops, 1)
        self.assertNotIn('child_pid', self.manifest())

    def test_main_explicit_key_precedes_scoped_and_removes_both(self):
        argv = ['watchdog', '--expected-name', POD['name'], '--run-prefix', 'run-test',
                '--source-sha', 'a' * 40, '--state-dir', self.config.state_dir,
                '--command', str(self.script), '--command-sha256', self.config.command_sha256]
        env = {'RUNPOD_POD_ID': POD['id'], 'RUNPOD_API_KEY': SCOPED_SECRET,
               'JOVOVICH_RUNPOD_CONTROL_KEY': CONTROL_SECRET, 'HF_TOKEN': HF_SECRET}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch('sys.argv', argv), \
                mock.patch.object(bootstrap, 'RunpodAPI') as api, \
                mock.patch.object(bootstrap, 'supervise', return_value=0) as supervisor:
            self.assertEqual(bootstrap.main(), 0)
            api.assert_called_once_with(CONTROL_SECRET, POD['id'])
            self.assertEqual(supervisor.call_args.args[2:4], (HF_SECRET, CONTROL_SECRET))
            for name in ('RUNPOD_API_KEY', 'JOVOVICH_RUNPOD_CONTROL_KEY', 'HF_TOKEN'):
                self.assertNotIn(name, os.environ)

    def test_redaction_every_split(self):
        expected = b'prefix [REDACTED] suffix [REDACTED]'
        raw = b'prefix ' + HF_SECRET.encode() + b' suffix ' + CONTROL_SECRET.encode()
        for split in range(len(raw) + 1):
            redactor = bootstrap.Redactor([HF_SECRET, CONTROL_SECRET])
            actual = redactor.feed(raw[:split]) + redactor.feed(raw[split:]) + redactor.feed(b'', final=True)
            self.assertEqual(actual, expected)

    def test_api_exact_own_urls_stop_only_ua_and_sanitized_error(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = json.dumps(POD).encode()
        opener = mock.Mock()
        opener.open.return_value = response
        api = bootstrap.RunpodAPI(CONTROL_SECRET, POD['id'], opener=opener)
        self.assertEqual(api.get_pod(), POD)
        self.assertEqual(api.stop(), {'http_status': 200})
        get_request, stop_request = [call.args[0] for call in opener.open.call_args_list]
        self.assertEqual(get_request.full_url, 'https://api.runpod.io/v2/pods/pod_test123')
        self.assertEqual(get_request.method, 'GET')
        self.assertEqual(stop_request.full_url, get_request.full_url + '/action')
        self.assertEqual(stop_request.method, 'POST')
        self.assertEqual(stop_request.data, b'{"action":"stop"}')
        self.assertEqual(stop_request.get_header('User-agent'), 'jovovich-runpod-watchdog/1.0')
        self.assertEqual(stop_request.get_header('Authorization'), 'Bearer ' + CONTROL_SECRET)
        opener.open.side_effect = urllib.error.HTTPError('secret-url', 403, CONTROL_SECRET, {}, None)
        with self.assertRaisesRegex(bootstrap.BootstrapError, '^Runpod API HTTP 403$'):
            api.stop()
        for value in ('', None, '../other', 'x\ny'):
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.RunpodAPI(CONTROL_SECRET, value)
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.RunpodAPI('', POD['id'])
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other')


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BootstrapTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print(json.dumps({'passed': True, 'tests': result.testsRun, 'network_calls': 0}))
