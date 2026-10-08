"""Saved-evaluation admission must preserve history and reject source drift."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT / 'training'), str(PROJECT / 'test')]
from after_recovery import evaluate_saved as saved
from durable_archive import DurableArchive
from durable_archive_fixture import FakeTransport


class Transport(FakeTransport):
    def inventory(self, revision, prefix):
        return {k: v for k, v in super().inventory(revision, prefix).items() if k.startswith(prefix + '/')}


class SavedEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.write('models/base-qwen.gguf', 'base')
        for name in saved.REPAIRS:
            self.write(name, 'historical ' + name)
        self.write('training/train_mlp.c', 'immutable numerical source')
        for name in saved.HISTORICAL_ADDITIONS:
            self.write(name, 'unchanged collector source ' + name)
        self.write('build/jovovich-infer', 'immutable binary')
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        self.git('add', 'training', 'src/infer.c', 'Makefile')
        self.git('commit', '-qm', 'training source')
        self.training_sha = self.git('rev-parse', 'HEAD')
        names = list(saved.REPAIRS) + ['models/base-qwen.gguf', 'training/train_mlp.c', 'build/jovovich-infer']
        training = {}
        receipts = []
        for arm in ('before', 'after'):
            directory = 'models/old-' + arm
            run_id = arm + '-training'
            plan_name = directory + '/plan.json'
            self.write(plan_name, {'run_id': run_id, 'bindings': []})
            self.write(directory + '/completion.json', {'return_code': 0, 'acknowledged_updates': 100,
                'plan_sha256': saved.digest(self.repo / plan_name), 'bindings': []})
            for name in ('completion', 'update-100'):
                self.write(directory + '/_units/' + name + '.ack.json', {'unit_id': name})
                receipts.append({'run_id': run_id, 'unit_id': name})
            names += [plan_name, directory + '/completion.json', directory + '/_units/completion.ack.json',
                      directory + '/_units/update-100.ack.json']
            training[arm] = {'directory': '/historical/checkout/' + directory, 'run_id': run_id}
        contract = json.loads((PROJECT / 'training/explanations/evaluation_plan.json').read_text())
        self.parent = {'schema_version': 1, 'run_id': 'failed-eval', 'training': training,
            'bindings': [self.binding(name) for name in names], 'training_receipts': receipts,
            'continuation': {'source_commit': self.training_sha, 'before_recovered': 'models/old-before'},
            'contract': contract, 'parameters': {'BEFORE_RUN': training['before']['directory'],
                'AFTER_RUN': training['after']['directory'], 'EVALUATION_RUN': '/historical/checkout/models/eval',
                'EVALUATION_RUN_ID': 'failed-eval', 'INFER_SHA256': '1' * 64,
                'SHARED_BASE_UPDATE0_SHA256': '2' * 64}, 'export_phases': []}
        parent_path = self.root / 'plan.json'
        parent_path.write_text(json.dumps(self.parent))
        self.transport = Transport()
        archive = DurableArchive(self.transport, 'failed-eval', 'experiments/explanation-order')
        files = {'plan.json': parent_path}
        files.update({'inputs/' + name: self.repo / name for name in names if name != 'models/base-qwen.gguf'})
        archive.sync_unit('bootstrap', files, sequence=0)
        self.recovered = self.repo / 'models/recovered-parent'
        archive.recover(self.recovered, revision=self.transport.current)
        self.record = {'schema': saved.SCHEMA, 'parent_run_id': 'failed-eval',
            'parent_archive_revision': self.transport.current, 'parent_plan_sha256': saved.digest(parent_path),
            'training_source_commit': self.training_sha, 'evaluation_run_id': 'fresh-eval', 'source_changes': []}
        for name in saved.REPAIRS:
            old = self.binding(name)
            self.write(name, 'reviewed repair ' + name)
            self.record['source_changes'].append({'path': name, 'original': old, 'candidate': self.binding(name)})
        for name in saved.ADDITIONS:
            if name not in saved.HISTORICAL_ADDITIONS:
                self.write(name, 'new evaluation helper ' + name)
        self.record_path = self.repo / 'training/saved-record.json'
        self.output = self.repo / 'models/new-eval'
        self.commit_record()

    def write(self, name, value):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value))
        return path

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], stderr=subprocess.DEVNULL).decode().strip()

    def binding(self, name):
        return saved.item(self.repo / name, name)

    def commit_record(self):
        self.record_path.write_text(json.dumps(self.record))
        self.git('add', 'training', 'src/infer.c', 'Makefile')
        self.git('commit', '--allow-empty', '-qm', 'evaluation source')
        self.source_sha = self.git('rev-parse', 'HEAD')

    def prepare(self):
        return saved.prepare(self.recovered, self.record_path, self.output, self.source_sha, repo=self.repo)

    def test_saved_endpoint_plan_preserves_historical_identity_and_contract(self):
        prepared = self.prepare()
        self.assertEqual(prepared['continuation'], self.parent['continuation'])
        self.assertEqual(prepared['contract'], self.parent['contract'])
        self.assertEqual(prepared['training_receipts'], self.parent['training_receipts'])
        self.assertEqual(prepared['saved_evaluation']['training_source_commit'], self.training_sha)
        self.assertEqual(prepared['saved_evaluation']['evaluation_source_commit'], self.source_sha)
        self.assertEqual(prepared['parameters']['EVALUATION_RUN_ID'], 'fresh-eval')
        self.assertEqual(prepared['training']['before']['directory'], str(self.repo / 'models/old-before'))
        self.assertEqual(len(prepared['export_phases']), 8)
        bound = {x['path']: x for x in prepared['bindings']}
        for change in self.record['source_changes']:
            old_path = 'models/recovered-parent/inputs/' + change['path']
            self.assertEqual(bound[old_path]['sha256'], change['original']['sha256'])
            self.assertEqual(bound[change['path']], change['candidate'])
        self.assertFalse(self.output.exists())

    def test_missing_artifacts_restore_from_authenticated_bootstrap(self):
        for name in ('build/jovovich-infer', 'models/old-after/completion.json'):
            (self.repo / name).unlink()
        self.prepare()
        self.assertTrue((self.repo / 'build/jovovich-infer').stat().st_mode & 0o100)
        self.assertEqual(saved.read(self.repo / 'models/old-after/completion.json')['acknowledged_updates'], 100)

    def test_numerical_source_replacement_is_rejected(self):
        name = 'training/train_mlp.c'
        old = self.binding(name)
        self.write(name, 'changed numerics')
        self.record['source_changes'].append({'path': name, 'original': old, 'candidate': self.binding(name)})
        self.commit_record()
        with self.assertRaisesRegex(RuntimeError, 'exceeds allowed'):
            self.prepare()

    def test_omitted_repair_is_rejected(self):
        self.record['source_changes'] = [x for x in self.record['source_changes']
                                       if x['path'] != 'training/explanations/collect_generation.py']
        self.commit_record()
        with self.assertRaisesRegex(RuntimeError, 'bound bytes differ'):
            self.prepare()

    def test_uncommitted_candidate_is_rejected(self):
        self.write('training/explanations/execute_evaluation.py', 'uncommitted')
        with self.assertRaisesRegex(ValueError, 'checkout differs'):
            self.prepare()

    def test_historical_training_commit_cannot_be_relabelled(self):
        self.record['training_source_commit'] = self.source_sha
        self.commit_record()
        with self.assertRaisesRegex(RuntimeError, 'historical evaluation/training source'):
            self.prepare()

    def test_parent_plan_checksum_pin_is_required(self):
        self.record['parent_plan_sha256'] = 'f' * 64
        self.commit_record()
        with self.assertRaisesRegex(RuntimeError, 'parent plan changed'):
            self.prepare()

    def test_reused_evaluation_id_is_rejected(self):
        self.record['evaluation_run_id'] = self.record['parent_run_id']
        self.commit_record()
        with self.assertRaisesRegex(RuntimeError, 'fresh run ID'):
            self.prepare()

    def test_recovered_payload_tamper_is_rejected(self):
        path = self.recovered / 'inputs/models/old-after/completion.json'
        path.write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'bound bytes changed'):
            self.prepare()

    def test_existing_artifact_tamper_is_not_overwritten(self):
        self.write('build/jovovich-infer', 'wrong binary')
        with self.assertRaisesRegex(RuntimeError, 'bound bytes differ'):
            self.prepare()
        self.assertEqual((self.repo / 'build/jovovich-infer').read_text(), 'wrong binary')

    def test_output_traversal_is_rejected(self):
        self.output = self.repo / '..' / 'escape'
        with self.assertRaisesRegex(RuntimeError, 'escapes checkout'):
            self.prepare()

    def test_newly_bound_numerical_source_must_match_training_commit(self):
        self.write('src/infer.c', 'changed inference source')
        self.commit_record()
        with self.assertRaisesRegex(RuntimeError, 'numerical/build source differs'):
            self.prepare()

    def test_parent_remote_readback_precedes_executor(self):
        prepared = self.prepare()
        events = []
        with patch.object(saved.original, 'verify_training_receipts', side_effect=lambda *a: events.append('remote')):
            with patch.object(saved, 'execute_evaluation', side_effect=lambda *a: events.append('execute')):
                saved.execute(object(), prepared, self.output)
        self.assertEqual(events, ['remote', 'execute'])
        with patch.object(saved.original, 'verify_training_receipts', side_effect=RuntimeError('bad remote')):
            with patch.object(saved, 'execute_evaluation') as execute:
                with self.assertRaisesRegex(RuntimeError, 'bad remote'):
                    saved.execute(object(), prepared, self.output)
                execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
