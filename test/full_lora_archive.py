#!/usr/bin/env python3
"""Exercise checkpoint ACK ordering and fail-closed child shutdown without HF."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ArchiveProtocol(unittest.TestCase):
    def run_scenario(self, fail):
        spec = importlib.util.spec_from_file_location('host_archive', ROOT/'training/full_lora/host_archive.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'key').write_text('test-placeholder')
            (root/'checkpoints').mkdir()
            script = root/'trainer.py'
            script.write_text('''import json,os,pathlib,sys
root=pathlib.Path(sys.argv[1]);(root/'pid').write_text(str(os.getpid()))
p=root/'checkpoints'/'step-000000';p.mkdir()
for n in ['q','k','v','o','gate','up','down']:(p/(n+'.lora')).write_bytes(b'adapter')
(p/'optimizer.bin').write_bytes(b'optimizer');(p/'state.json').write_text('{}')
print(json.dumps({'event':'checkpoint','step':0,'path':str(p)}),flush=True)
assert sys.stdin.readline()=='ACK 0\\n'
(root/'received-ack').write_text('yes')
print(json.dumps({'event':'completed'}),flush=True)
''')
            units = []
            module.HFTransport = lambda *args: None
            module.DurableArchive = lambda *args, **kwargs: None
            def sync(archive, unit, files, **kwargs):
                self.assertTrue(all(path.is_file() for path in files.values()))
                units.append(unit)
                if unit.startswith('checkpoint'):
                    self.assertFalse((root/'received-ack').exists())
                    if fail:
                        raise RuntimeError('simulated archive failure')
                return {'verified_remote_bytes': True, 'sequence': kwargs['sequence']}
            module.sync_unit_with_retry = sync
            original = sys.argv
            try:
                sys.argv = ['host', '--run-id', 'test', '--state-dir', str(root/'state'),
                    '--checkpoint-root', str(root/'checkpoints'), '--token-file', str(root/'key'),
                    '--stop-file', str(root/'STOP'), '--', sys.executable, str(script), str(root)]
                self.assertEqual(module.main(), 1 if fail else 0)
            finally:
                sys.argv = original
            self.assertEqual((root/'received-ack').exists(), not fail)
            self.assertTrue((root/'STOP').exists())
            self.assertEqual(units, ['bootstrap', 'checkpoint-000000'] + ([] if fail else ['closed']))
            with self.assertRaises(ProcessLookupError):
                os.kill(int((root/'pid').read_text()), 0)

    def test_verified_checkpoint_is_acknowledged(self):
        self.run_scenario(False)

    def test_archive_failure_kills_child_without_ack(self):
        self.run_scenario(True)

if __name__ == '__main__':
    unittest.main()
