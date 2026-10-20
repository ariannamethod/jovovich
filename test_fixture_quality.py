import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from fixture_quality import QUARANTINE, quarantined, require_usable, semantic_verdict
from verify_functions import check, safe
from review import SYSTEM

ROOT = Path(__file__).resolve().parent


class FixtureQualityTests(unittest.TestCase):
    def test_all_fixture_system_prompts_match_runtime(self):
        for name in ('train', 'validation', 'test', 'acceptance'):
            for row in map(json.loads, (ROOT / f'data/{name}.jsonl').read_text().splitlines()):
                chat = row.get('messages', row.get('prompt_messages'))
                if chat:
                    self.assertEqual(chat[0]['content'], SYSTEM, row['id'])

    def test_worker_model_config_has_no_ml_imports(self):
        result = subprocess.run([sys.executable, '-I', '-c',
            "import sys; sys.path.insert(0, " + repr(str(ROOT)) + "); "
            "from model_config import MODEL, REVISION; "
            "assert MODEL and len(REVISION) == 40; "
            "assert 'torch' not in sys.modules and 'transformers' not in sys.modules"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_contract_counterexamples(self):
        source = {r['task_id']: r for r in map(json.loads, (ROOT / 'data/verified_functions.jsonl').read_text().splitlines())}
        for issue in QUARANTINE:
            if 'task_id' not in issue:
                continue
            with self.subTest(task=issue['task_id']):
                row = source[issue['task_id']]
                code = row['imports'] + '\n' + row['original']
                self.assertTrue(safe(code + '\n' + issue['test']))
                self.assertIn(check(code, [issue['test']]).get('error'), ('AssertionError', 'IndexError'))
                for kind in ('original', 'changed'):
                    with self.assertRaises(ValueError):
                        require_usable([{'id': f"mbpp-{issue['task_id']}-{kind}"}])

    def test_rebuilt_splits(self):
        groups = []
        for name in ('train', 'validation', 'test'):
            rows = list(map(json.loads, (ROOT / f'data/{name}.jsonl').read_text().splitlines()))
            require_usable(rows)
            groups.append({r['group'] for r in rows})
        for i, group in enumerate(groups):
            for other in groups[:i]:
                self.assertFalse(group & other)

    def test_release_policy_requires_preapproval(self):
        policies = json.loads((ROOT / 'data/policies.json').read_text())
        merges = []
        class Github:
            def merge_pull_request(self, number):
                merges.append(number)
        exec(policies[4]['bad'], {'github': Github(), 'score': .99,
                                  'pr_number': 7, 'preapproved': False})
        self.assertEqual(merges, [7])
        self.assertTrue(quarantined({'id': 'policy-4-permitted'}))

    def test_verdict_is_outside_code_and_unambiguous(self):
        for text in ('Verdict: **CONCERN**', '**Verdict:** CONCERN', '## Verdict: CONCERN'):
            self.assertEqual(semantic_verdict(text), 'CONCERN')
        for text in ('```python\nVerdict: CLEAN', '~~~\nVerdict: CLEAN',
                     '```\nVerdict: CLEAN\n```',
                     'Verdict: CLEAN\nVerdict: CONCERN',
                     'The example says Verdict: CLEAN'):
            self.assertEqual(semantic_verdict(text), 'INVALID')
        self.assertEqual(semantic_verdict('```\nVerdict: CLEAN\n```\nVerdict: CONCERN'), 'CONCERN')

    def test_scoring_rejects_unknown_and_truncated_generations(self):
        cases = [{'id': 'policy-check-' + str(i), 'expected': 'CLEAN'} for i in range(3)]
        answers = [{**r, 'review': '**Verdict:** CLEAN'} for r in cases]
        answers[0]['complete'] = True
        answers[1]['complete'] = False
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            for name, rows in [('cases', cases), ('answers', answers)]:
                (directory / name).write_text(''.join(json.dumps(r) + '\n' for r in rows))
            result = subprocess.run([sys.executable, str(ROOT / 'evaluate.py'),
                                     str(directory / 'answers'), str(directory / 'cases')],
                                    check=True, capture_output=True, text=True)
            counts = json.loads(result.stdout)['counts']
            self.assertEqual(counts['correct_semantic_verdict'], 1)
            self.assertEqual(counts['completion_unknown'], 1)
            self.assertEqual(counts['complete'], 1)

    def test_distillation_rejects_defective_corpus_before_loading_models(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.jsonl'
            path.write_text(json.dumps({'id': 'mbpp-461-original', 'group': 'mbpp-461'}) + '\n')
            result = subprocess.run([sys.executable, str(ROOT / 'distill.py'), '--input', str(path)],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Quarantined source tasks', result.stderr)
            self.assertNotIn('ModuleNotFoundError', result.stderr)


if __name__ == '__main__':
    unittest.main()
