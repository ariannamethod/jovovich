import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('full_delivery', ROOT / 'training/full_lora/deliver.py')
delivery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)


class ClosedCaseResume(unittest.TestCase):
    def test_reuses_closed_native_case_and_rejects_changed_inputs_or_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            prompt, raw = b'exact original prompt', b'{"analysis":"Already checked.","findings":[]}'
            sha = lambda value: hashlib.sha256(value).hexdigest()
            case = {'case_id': 'closed-case', 'prompt': prompt}
            record = {'case_id': 'closed-case', 'corpus_sha256': 'corpus',
                      'raw_response': raw.decode(), 'raw_response_sha256': sha(raw),
                      'finish_reason': 'eos', 'metadata': {'model_sha256': 'model',
                      'prompt_sha256': sha(prompt), 'requested_limit': 512}}
            (directory / 'prompt.txt').write_bytes(prompt)
            (directory / 'stdout.bin').write_bytes(raw)
            (directory / 'record.json').write_text(json.dumps(record))
            (directory / 'execution.json').write_text(json.dumps({'returncode': 0}))
            trace = {'schema_version': 1, 'prompt_token_ids': [1], 'generated_token_ids': [2, 3],
                     'requested_limit': 512, 'emitted_tokens': 1, 'stop_reason': 'eos'}
            (directory / 'trace.json').write_text(json.dumps(trace))
            self.assertEqual(delivery.recovered_record(directory, case, 'model', 'corpus'), record)
            for changed, model, corpus in [({**case, 'prompt': b'new prompt'}, 'model', 'corpus'),
                                            (case, 'new-model', 'corpus'), (case, 'model', 'new-corpus')]:
                with self.assertRaises(ValueError):
                    delivery.recovered_record(directory, changed, model, corpus)
            (directory / 'stdout.bin').write_bytes(b'{"findings":[{"line_id":1,"reason":"invented"}]}')
            with self.assertRaises(ValueError):
                delivery.recovered_record(directory, case, 'model', 'corpus')


if __name__ == '__main__':
    unittest.main()
