"""Synthetic completed journals for packet validation; zero model/network calls."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'training/explanations'))
import prepare_semantic_packet as packet

REVISION = 'a' * 40
RUN = 'synthetic-evaluation'
POD = Path('/synthetic/pod/repository')


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False) + '\n').encode()


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw if isinstance(raw, bytes) else encoded(raw))


def item(path, name):
    raw = path.read_bytes()
    return dict(path=str(name), bytes=len(raw), sha256=packet.sha(raw))


def refresh(directory):
    """Reseal an explicitly synthetic journal after a deliberately injected fault."""
    ledger_path = directory / '_durable-recovery.json'
    ledger = json.loads(ledger_path.read_text())
    previous = None
    for unit in ledger['units']:
        for entry in unit['files']:
            raw = (directory / entry['name']).read_bytes()
            entry.update(size=len(raw), sha256=packet.sha(raw),
                git_blob_sha1=hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest())
            entry['object'] = ledger['prefix'] + '/objects/' + entry['sha256']
        manifest = dict(schema='jovovich.durable-unit.v1', run_id=ledger['run_id'],
            sequence=unit['sequence'], unit_id=unit['unit_id'], parent_revision=REVISION,
            previous_manifest=previous, files=unit['files'])
        previous = packet.sha((json.dumps(manifest, sort_keys=True, separators=(',', ':')) + '\n').encode())
        unit['manifest_sha256'] = previous
    write(ledger_path, ledger)
    return ledger


def receipt(ledger):
    return dict(schema='jovovich.durable-receipt.v1', run_id=ledger['run_id'], prefix=ledger['prefix'],
        revision=REVISION, verified_remote_bytes=True, reused=False, **ledger['units'][-1])


class Journal:
    def __init__(self, root, run_id):
        self.root = root
        self.ledger = dict(schema='jovovich.durable-recovery.v1', run_id=run_id,
            prefix=packet.PREFIX + '/' + run_id, revision=REVISION, verified_remote_bytes=True,
            next_sequence=0, units=[], fixture='SYNTHETIC: no model calls or remote archive')

    def add(self, name, files):
        for path, raw in files.items():
            write(self.root / path, raw)
        self.ledger['units'].append(dict(sequence=len(self.ledger['units']), unit_id=name,
            manifest_sha256='0' * 64, files=[dict(name=p) for p in sorted(files)]))

    def finish(self):
        self.ledger['next_sequence'] = len(self.ledger['units'])
        write(self.root / '_durable-recovery.json', self.ledger)
        self.ledger = refresh(self.root)
        return receipt(self.ledger)


def make_fixture(root):
    contract = json.loads((ROOT / 'training/explanations/evaluation_plan.json').read_text())
    output = POD / 'models' / RUN
    parameters = dict(BEFORE_RUN=str(POD / 'models/before'), AFTER_RUN=str(POD / 'models/after'),
        EVALUATION_RUN=str(output), EVALUATION_RUN_ID=RUN,
        SHARED_BASE_UPDATE0_SHA256=contract['resolution']['SHARED_BASE_UPDATE0_SHA256'])
    source_names = set(contract['required_pretraining_launch_bindings']) | set(packet.SOURCES) | {'training/file_integrity.py',
        'src/infer.c', 'Makefile'}
    bindings, sources = [], {}
    for name in sorted(source_names):
        original = ROOT / name
        raw = original.read_bytes() if original.is_file() else ('SYNTHETIC artifact ' + name).encode()
        sources[name] = raw
        bindings.append(dict(path=name, bytes=len(raw), sha256=packet.sha(raw)))
    bound = {b['path']: b for b in bindings}
    parameters['INFER_SHA256'] = bound['build/jovovich-infer']['sha256']
    bindings.append(dict(path='models/base-qwen.gguf', bytes=675710848,
        sha256=parameters['SHARED_BASE_UPDATE0_SHA256']))
    prepared = dict(schema_version=1, run_id=RUN, parameters=copy.deepcopy(parameters),
        contract=contract, contract_source='training/explanations/evaluation_plan.json',
        bindings=bindings, training_receipts=[{'synthetic_training_receipt': i} for i in range(4)])
    artifacts = {}
    for arm in ('before', 'after'):
        model = ('SYNTHETIC exported model ' + arm).encode()
        parameters[arm.upper() + '_UPDATE100_SHA256'] = packet.sha(model)
        artifacts[arm + '-merge'] = {'exports/' + arm + '/jovovich.gguf': model}
        artifacts[arm + '-byte-export-audit'] = {'exports/' + arm + '/export-audit.json': encoded(dict(
            valid=True, adapted=3, metadata_equal=True, model=dict(sha256=packet.sha(model)), synthetic=True))}
        parity = b''.join(encoded(dict(row=i, **{'pass': True}, completion_tokens=7, argmax_agree=7,
            logits_relative_l2=0, residual_relative_l2=0, max_batch_ce_diff=0, synthetic=True)) for i in (0, 1, 2, 3, 51))
        artifacts[arm + '-native-export-parity'] = {'exports/' + arm + '/parity.jsonl': parity}
    jobs = packet.evaluation.resolve(contract['collector_jobs'], parameters)
    artifacts['resolve-generation'] = {'generation-plan.json': encoded(dict(jobs=jobs, parameters=parameters))}
    artifacts['training-remote-check'] = {'training-remote-verification.json': encoded(dict(
        status='verified', receipts=prepared['training_receipts'], unique_payloads=0, synthetic=True))}
    for job in jobs:
        args = packet.evaluation.argument_map(job['argv'])
        journal = Journal(root / job['id'], args['--run-id'])
        corpus = sources[job['source']]
        source_rows = [json.loads(line) for line in corpus.splitlines()]
        rendered = packet.collect.review_cases(corpus, split=job['split'])
        rows_by_id = {r['id']: r for r in source_rows}
        source_list = ['training/explanations/collect_generation.py', 'training/durable_archive.py', 'src/infer.c', 'Makefile', 'training/file_integrity.py']
        if job['split'] == 'holdout':
            source_list += ['bin/jovovich.mjs', 'prompts/identity.txt', 'training/explanations/build_corpora.py']
        infer = dict(bound['build/jovovich-infer'], path=str(POD / 'build/jovovich-infer'))
        model_bytes = (675710848 if job['model'] == 'shared_base_update0' else
                       len(('SYNTHETIC exported model ' + job['model'].split('_', 1)[0]).encode()))
        model = dict(path=str(POD / args['--model']), sha256=args['--model-sha256'], bytes=model_bytes)
        manifest = dict(run_id=args['--run-id'], split=job['split'], corpus=dict(bound[job['source']], path=str(POD / job['source'])),
            model=model, infer=infer, sources=[dict(bound[n], path=str(POD / n)) for n in source_list],
            notorch_commit='b' * 40, temperature=0, token_budget=512, context=8192,
            environment=packet.collect.ENVIRONMENT, assistant_prefix='<|im_start|>assistant\n',
            cases=[{k: v for k, v in case.items() if k != 'prompt'} | {'prompt_path': f'cases/{i:03d}/prompt.txt'}
                   for i, case in enumerate(rendered)], synthetic=True)
        bootstrap = {'inputs/corpus.jsonl': corpus, 'manifest.json': encoded(manifest)}
        bootstrap.update({'inputs/sources/' + str(i) + '-' + Path(n).name: sources[n] for i, n in enumerate(source_list)})
        bootstrap.update({f'cases/{i:03d}/prompt.txt': case['prompt'] for i, case in enumerate(rendered)})
        journal.add('inputs', bootstrap)
        records = []
        for i, case in enumerate(rendered):
            base = f'cases/{i:03d}/'
            source_row = rows_by_id[case['case_id']]
            gold = source_row['gold'] if job['split'] == 'holdout' else json.loads(source_row['messages'][2]['content'])
            response = json.dumps(dict(findings=gold['findings']))
            if i == 0:
                response = '```json\n' + response + '\n```'
            elif i == 1:
                response = 'SYNTHETIC invalid JSON'
            elif i == 2:
                response = json.dumps(gold['findings'])
            elif i == 3:
                response = json.dumps(dict(findings=gold['findings'], extra='Synthetic ignored top-level field'))
            elif i == 4 and gold['findings']:
                response = json.dumps(dict(findings=[gold['findings'][0]] * 8))
            candidates = source_row.get('expected_line_ids', [])
            if job['split'] == 'holdout' and gold['findings'] and len(candidates) > 1:
                alternative = next(n for n in candidates if n != gold['findings'][0]['line_id'])
                response = json.dumps(dict(findings=[dict(gold['findings'][0], line_id=alternative)]))
            ids = [151644, 11, 12]
            trace = dict(schema_version=1, prompt_token_ids=ids, generated_token_ids=[17, 151645],
                requested_limit=512, emitted_tokens=1, stop_reason='eos')
            intent = dict(case_id=case['case_id'], prompt_sha256=case['prompt_sha256'], environment=packet.collect.ENVIRONMENT,
                argv=packet.collect.native_command(infer['path'], model['path'], Path(args['--output']) / base / 'tokens.json'),
                tokenizer_argv=packet.collect.token_command(infer['path'], model['path']))
            journal.add(f'case-{i:03d}-intent', {base + 'intent.json': encoded(intent)})
            token_files = {base + 'prompt-token-ids.txt': b'151644,11,12\n', base + 'tokenizer.stderr.bin': b''}
            token_artifacts = [dict(path=str(Path(args['--output']) / n), bytes=len(raw), sha256=packet.sha(raw))
                               for n, raw in token_files.items()]
            token_files[base + 'tokenizer-result.json'] = encoded(dict(case_id=case['case_id'], status='completed',
                return_code=0, error_type=None, prompt_token_ids=ids, artifacts=token_artifacts))
            journal.add(f'case-{i:03d}-tokenizer', token_files)
            record = dict(case_id=case['case_id'], corpus_sha256=packet.sha(corpus), raw_response=response,
                raw_response_sha256=packet.sha(response.encode()), finish_reason='eos', metadata=dict(
                model_path=model['path'], model_sha256=model['sha256'], prompt_sha256=case['prompt_sha256'],
                requested_limit=512, prompt_token_ids=ids, generated_token_ids=trace['generated_token_ids']))
            records.append(record)
            native_files = {base + 'stdout.bin': response.encode(), base + 'stderr.bin': b'',
                            base + 'tokens.json': encoded(trace), base + 'record.json': encoded(record)}
            native_artifacts = [dict(path=str(Path(args['--output']) / n), bytes=len(raw), sha256=packet.sha(raw))
                                for n, raw in native_files.items()]
            native_files[base + 'result.json'] = encoded(dict(case_id=case['case_id'], return_code=0,
                tokenizer_return_code=0, finish_reason='eos', artifacts=native_artifacts))
            journal.add(f'case-{i:03d}-result', native_files)
        generated = b''.join(encoded(r) for r in records)
        completion = dict(schema_version=1, run_id=args['--run-id'], cases=len(records),
            status='native_completed', archive_status='requires_verified_receipt',
            generations_sha256=packet.sha(generated), inputs_unchanged=True)
        journal.add('completion', {'completion.json': encoded(completion), 'generations.jsonl': generated})
        remote = journal.finish()
        result = dict(completion, status='completed', archive_status='verified', remote_verification=remote)
        artifacts[job['id'] + '-collect'] = {'_receipts/' + job['id'] + '.json': encoded(dict(argv=job['argv'], result=result))}
        artifacts[job['id'] + '-score'] = {'generation/' + job['id'] + '/structural-score.json': encoded(dict(
            status='complete', summary=dict(received_reviews=len(records)),
            generations=dict(sha256=packet.sha(generated)), corpus=dict(sha256=packet.sha(corpus)), synthetic=True))}
    artifacts['cross-model-prompts'] = {'prompt-comparison.json': encoded(dict(status='pass', generation_calls=228,
        jobs={j['id']: j['rows'] for j in jobs}, unique_prompts={'train': 52, 'holdout': 24}))}
    parent = Journal(root / 'parent', RUN)
    parent.add('bootstrap', {'plan.json': encoded(prepared), **{'inputs/' + n: raw for n, raw in sources.items()}})
    phases = ['training-remote-check', 'before-teacher-forced-diagnostics', 'after-teacher-forced-diagnostics']
    phases += [s['id'] for arm in contract['exports'] for s in arm['steps']]
    phases += ['resolve-generation'] + [j['id'] + suffix for j in jobs for suffix in ('-collect', '-score')]
    phases += ['cross-model-prompts']
    for phase in phases:
        parent.add(phase + '.intent', {'_units/' + phase + '.intent.json': encoded(dict(unit={'id': phase}, synthetic=True))})
        parent.add(phase + '.result', {**artifacts.get(phase, {}), '_units/' + phase + '.result.json': encoded(dict(
            unit={'id': phase}, status='completed', return_code=0, synthetic=True))})
    parent.add('completion', {'completion.json': encoded(dict(status='native_evaluation_completed', semantic_audit='pending',
        run_id=RUN, generation_calls=228, parity_rows_per_arm=5, structural_reports=6, teacher_forced_reports=2,
        plan_sha256=packet.sha(encoded(prepared)), bindings=bindings, synthetic=True))})
    parent.finish()


class PacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='synthetic-semantic-packet-')
        cls.template = Path(cls.temporary.name) / 'template'
        make_fixture(cls.template)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix='synthetic-semantic-case-')
        self.root = Path(self.work.name)
        shutil.copytree(self.template, self.root / 'input')
        self.parent = self.root / 'input/parent'
        self.children = sorted(p for p in (self.root / 'input').iterdir() if p.name != 'parent')
        self.child = self.root / 'input/shared_base_update0-train'

    def tearDown(self):
        self.work.cleanup()

    def prepare(self):
        return packet.prepare(self.parent, self.children, self.root / 'packet', run_id=RUN, revision=REVISION)

    def update_child(self):
        ledger = refresh(self.child)
        name = self.child.name
        path = self.parent / ('_receipts/' + name + '.json')
        outer = json.loads(path.read_text())
        completion = json.loads((self.child / 'completion.json').read_text())
        outer['result'].update(completion, status='completed', archive_status='verified', remote_verification=receipt(ledger))
        write(path, outer)
        structural = self.parent / ('generation/' + name + '/structural-score.json')
        value = json.loads(structural.read_text()); value['generations']['sha256'] = completion['generations_sha256']
        write(structural, value)
        refresh(self.parent)

    def change_generations(self, mutate):
        path = self.child / 'generations.jsonl'
        records = [json.loads(line) for line in path.read_text().splitlines()]
        mutate(records)
        path.write_bytes(b''.join(encoded(r) for r in records))
        completion = json.loads((self.child / 'completion.json').read_text())
        completion['generations_sha256'] = packet.sha(path.read_bytes())
        write(self.child / 'completion.json', completion)
        self.update_child()

    def reject(self, text):
        with self.assertRaisesRegex(ValueError, text):
            self.prepare()
        self.assertFalse((self.root / 'packet').exists())

    def test_production_results_blinding_and_blank_judgments(self):
        result = self.prepare()
        self.assertEqual((result['rows'], result['archive_status'], result['ready_for_review']), (228, 'pending_archive', False))
        reviewer = self.root / 'packet/reviewer-1'
        raw = (reviewer / 'packet.jsonl').read_text()
        rows = [json.loads(line) for line in raw.splitlines()]
        for hidden in ('/synthetic/pod/', 'model_path', 'shared_base_update0', 'before_update100', 'after_update100'):
            self.assertNotIn(hidden, raw)
        self.assertEqual(len({r['opaque_model_slot'] for r in rows}), 3)
        self.assertEqual((reviewer / 'packet.jsonl').read_bytes(), (self.root / 'packet/reviewer-2/packet.jsonl').read_bytes())
        self.assertTrue(all(r['actual_production_parse_result']['accepted'] for r in rows if r['raw_response'].startswith('```')))
        self.assertTrue(all(not r['actual_production_parse_result']['accepted'] for r in rows if r['raw_response'] == 'SYNTHETIC invalid JSON'))
        self.assertTrue(any(r['actual_production_parse_result']['accepted'] and len(r['actual_production_parse_result']['result']['findings']) == 8 for r in rows))
        self.assertTrue(any(r['actual_production_parse_result']['accepted'] and r['raw_response'].startswith('[') for r in rows))
        alternatives = [r for r in rows if r['split'] == 'holdout' and len(r['candidate_line_ids']) > 1]
        self.assertTrue(alternatives)
        for row in alternatives:
            self.assertTrue(row['actual_production_parse_result']['accepted'])
            self.assertNotEqual(json.loads(row['raw_response'])['findings'][0]['line_id'], row['canonical_gold_findings'][0]['line_id'])
        judgments = [json.loads(line) for line in (reviewer / 'judgments.jsonl').read_text().splitlines()]
        self.assertEqual(len(judgments), 228)
        self.assertTrue(all(all(v is None for k, v in r.items() if k not in ('opaque_model_slot', 'case_id', 'pair', 'split')) for r in judgments))

    def test_missing_generation_row(self):
        self.change_generations(lambda rows: rows.pop())
        self.reject('missing or duplicate')

    def test_duplicate_generation_row(self):
        self.change_generations(lambda rows: rows.__setitem__(-1, copy.deepcopy(rows[0])))
        self.reject('missing or duplicate')

    def test_tampered_raw_hash(self):
        self.change_generations(lambda rows: rows[0].update(raw_response_sha256='f' * 64))
        self.reject('raw response hash mismatch')

    def test_tampered_native_output(self):
        (self.child / 'cases/000/stdout.bin').write_text('different literal bytes')
        self.update_child()
        self.reject('raw response differs')

    def test_tampered_prompt(self):
        (self.child / 'cases/000/prompt.txt').write_text('different source context')
        self.update_child()
        self.reject('prompt bytes differ')

    def test_tokenizer_trace_mismatch(self):
        path = self.child / 'cases/000/tokens.json'
        value = json.loads(path.read_text()); value['prompt_token_ids'] = [151644, 99, 12]
        write(path, value); self.update_child()
        self.reject('native/tokenizer correspondence')

    def test_mismatched_collector_receipt(self):
        path = self.parent / '_receipts/shared_base_update0-train.json'
        value = json.loads(path.read_text()); value['result']['remote_verification']['manifest_sha256'] = 'f' * 64
        write(path, value); refresh(self.parent)
        self.reject('collector receipt differs')

    def test_mismatched_frozen_source(self):
        name = 'bin/jovovich.mjs'
        path = self.parent / ('inputs/' + name)
        path.write_text('SYNTHETIC different parser implementation')
        plan_path = self.parent / 'plan.json'
        plan = json.loads(plan_path.read_text())
        plan['bindings'] = [item(path, name) if b['path'] == name else b for b in plan['bindings']]
        write(plan_path, plan)
        completion_path = self.parent / 'completion.json'
        completion = json.loads(completion_path.read_text())
        completion.update(bindings=plan['bindings'], plan_sha256=packet.sha(plan_path.read_bytes()))
        write(completion_path, completion); refresh(self.parent)
        self.reject('bound bytes changed')

    def test_wrong_parent_pin(self):
        with self.assertRaisesRegex(ValueError, 'parent recovery revision'):
            packet.prepare(self.parent, self.children, self.root / 'packet', run_id=RUN, revision='b' * 40)


if __name__ == '__main__':
    unittest.main(verbosity=2)
