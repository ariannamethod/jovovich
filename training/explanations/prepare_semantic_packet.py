#!/usr/bin/env python3
"""Prepare two blinded review packets from completed, recovered evaluation journals.

No model calls, semantic judgments, remote writes or source changes. Publish the
packets and separate operator mapping through DurableArchive before distribution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'training'), str(Path(__file__).resolve().parent)]
from after_recovery.bind import checked_recovery, clean_path
from after_recovery.preflight import regular, check
from explanations import collect_generation as collect
from explanations import execute_evaluation as evaluation
from explanations import score_generation as score

PREFIX = 'experiments/explanation-order'
SOURCES = ('training/explanations/collect_generation.py',
           'training/explanations/score_generation.py',
           'training/explanations/execute_evaluation.py',
           'training/explanations/build_corpora.py', 'bin/jovovich.mjs',
           'prompts/identity.txt', 'training/explanations/plan.json',
           'training/after_recovery/bind.py', 'training/after_recovery/preflight.py')


def need(value, message):
    if not value:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return score.strict_json(Path(path).read_text())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n')


class Recovery:
    """Only ledger-bound files may enter a packet or its provenance."""
    def __init__(self, directory):
        self.root = clean_path(directory)
        self.ledger = checked_recovery(self.root)
        value = self.ledger
        need(value.get('verified_remote_bytes') is True and
             value.get('next_sequence') == len(value['units']), 'unverified recovery')
        self.files = {f['name']: f for unit in value['units'] for f in unit['files']}

    def path(self, name):
        need(name in self.files, 'required artifact is not in the recovery ledger: ' + name)
        return regular(self.root, name)

    def read(self, name):
        return read(self.path(name))

    def units(self, expected, run_id):
        need(self.ledger['run_id'] == run_id and self.ledger['prefix'] == PREFIX + '/' + run_id and
             [u['unit_id'] for u in self.ledger['units']] == expected,
             'recovery identity or complete unit sequence differs')

    def receipt(self, receipt, unit_id):
        units = [u for u in self.ledger['units'] if u['unit_id'] == unit_id]
        need(len(units) == 1 and receipt.get('schema') == 'jovovich.durable-receipt.v1' and
             receipt.get('verified_remote_bytes') is True and
             receipt.get('run_id') == self.ledger['run_id'] and
             receipt.get('prefix') == self.ledger['prefix'] and
             isinstance(receipt.get('revision'), str) and re.fullmatch(r'[0-9a-f]{40}', receipt['revision']) and
             all(receipt.get(k) == units[0][k] for k in ('sequence', 'unit_id', 'manifest_sha256', 'files')),
             'collector receipt differs from recovered closed unit')


def changed_lines(prompt):
    marker = '\nChanged lines to review:\n'
    need(prompt.count(marker) == 1, 'prompt changed-line section differs')
    table = []
    for line in prompt.split(marker, 1)[1].split('\n\n', 1)[0].splitlines():
        match = re.fullmatch(r'\[([1-9][0-9]*)\] (ADDED|REMOVED) (.+):([0-9]+): (.*)', line)
        need(match is not None, 'invalid changed-line table')
        number, action, path, physical, quote = match.groups()
        table.append(dict(line_id=int(number), path=path, line=int(physical),
                          side='LEFT' if action == 'REMOVED' else 'RIGHT', quote=quote))
    need(table and [r['line_id'] for r in table] == list(range(1, len(table) + 1)) and
         len({r['path'] for r in table}) == 1, 'changed-line table is not one complete chunk')
    return table


def production_parse(rows):
    # argv[1] is the data file, so importing the CLI module does not invoke main().
    bridge = r'''
import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
const {parseReview} = await import(pathToFileURL(process.argv[2]).href);
const rows = JSON.parse(readFileSync(process.argv[1], 'utf8'));
process.stdout.write(JSON.stringify(rows.map(({raw, chunk}) => {
  try { return {accepted: true, result: parseReview(raw, chunk), error: null}; }
  catch (error) { return {accepted: false, result: null, error: error.message}; }
})));
'''
    inputs = [dict(raw=r['raw_response'], chunk=dict(path=r['changed_line_table'][0]['path'],
        lines=[{k: v for k, v in line.items() if k not in ('line_id', 'path')}
               for line in r['changed_line_table']])) for r in rows]
    with tempfile.TemporaryDirectory(prefix='jovovich-semantic-parse-') as directory:
        source = Path(directory) / 'responses.json'
        save(source, inputs)
        result = subprocess.run(['node', '--input-type=module', '-e', bridge,
            str(source), str(ROOT / 'bin/jovovich.mjs')], cwd=ROOT,
            env=collect.native_environment(), capture_output=True, check=True, timeout=60)
    parsed = score.strict_json(result.stdout.decode())
    need(isinstance(parsed, list) and len(parsed) == len(rows), 'production parser coverage differs')
    return parsed


def verify_parent(parent, run_id, revision):
    need(parent.ledger['revision'] == revision, 'parent recovery revision differs from requested pin')
    prepared, completed = parent.read('plan.json'), parent.read('completion.json')
    need(prepared['run_id'] == run_id and completed.get('run_id') == run_id and
         completed.get('status') == 'native_evaluation_completed' and
         completed.get('semantic_audit') == 'pending' and completed.get('generation_calls') == 228 and
         completed.get('parity_rows_per_arm') == 5 and completed.get('structural_reports') == 6 and
         completed.get('teacher_forced_reports') == 2 and
         completed.get('plan_sha256') == sha(parent.path('plan.json').read_bytes()) and
         completed.get('bindings') == prepared['bindings'], 'parent evaluation is incomplete or unbound')
    bindings = {b['path']: b for b in prepared['bindings']}
    need(len(bindings) == len(prepared['bindings']), 'duplicate parent binding')
    for name, item in bindings.items():
        if name != 'models/base-qwen.gguf':
            check(parent.path('inputs/' + name), item)
    for name in SOURCES:
        need(name in bindings, 'required packet source was not bound in evaluation: ' + name)
        check(regular(ROOT, name), bindings[name])
    contract = prepared['contract']
    need(contract == parent.read('inputs/' + prepared['contract_source']) and
         contract['schema'] == 'jovovich.explanation-order.evaluation.v1', 'evaluation contract binding differs')
    scientific = parent.read('inputs/' + contract['scientific_plan'])
    need(set(contract['required_pretraining_launch_bindings']) <= set(bindings), 'missing frozen evaluation sources')
    generation = parent.read('generation-plan.json')
    parameters = generation['parameters']
    need(set(parameters) == set(prepared['parameters']) | {'BEFORE_UPDATE100_SHA256', 'AFTER_UPDATE100_SHA256'} and
         all(parameters[k] == v for k, v in prepared['parameters'].items()) and
         parameters['EVALUATION_RUN_ID'] == run_id and
         parameters['SHARED_BASE_UPDATE0_SHA256'] == contract['resolution']['SHARED_BASE_UPDATE0_SHA256'] ==
         bindings['models/base-qwen.gguf']['sha256'], 'resolved evaluation parameters differ')
    jobs = generation['jobs']
    need(jobs == evaluation.resolve(contract['collector_jobs'], parameters) and
         [(j['model'], j['split'], j['rows']) for j in jobs] == [
             (model, split, count) for model in ('shared_base_update0', 'before_update100', 'after_update100')
             for split, count in (('train', 52), ('holdout', 24))], 'six fixed collector jobs differ')
    phases = ['training-remote-check', 'before-teacher-forced-diagnostics', 'after-teacher-forced-diagnostics']
    phases += [step['id'] for arm in contract['exports'] for step in arm['steps']]
    phases += ['resolve-generation'] + [j['id'] + suffix for j in jobs for suffix in ('-collect', '-score')]
    phases += ['cross-model-prompts']
    parent.units(['bootstrap'] + [p + suffix for p in phases for suffix in ('.intent', '.result')] + ['completion'], run_id)
    for phase in phases:
        result = parent.read('_units/' + phase + '.result.json')
        need(result['unit']['id'] == phase and result['status'] == 'completed' and result['return_code'] == 0,
             'parent phase did not complete: ' + phase)
    for arm in ('before', 'after'):
        audit = parent.read('exports/' + arm + '/export-audit.json')
        model_sha = collect.digest(parent.path('exports/' + arm + '/jovovich.gguf'))
        need(audit.get('valid') is True and audit.get('adapted') == 3 and audit.get('metadata_equal') is True and
             audit['model']['sha256'] == model_sha == parameters[arm.upper() + '_UPDATE100_SHA256'], 'export identity differs')
        parity = [score.strict_json(line) for line in parent.path('exports/' + arm + '/parity.jsonl').read_text().splitlines()]
        need([r['row'] for r in parity] == [0, 1, 2, 3, 51] and all(
            r['pass'] is True and r['argmax_agree'] == r['completion_tokens'] and
            r['logits_relative_l2'] <= 1e-5 and r['residual_relative_l2'] <= 1e-5 and
            r['max_batch_ce_diff'] <= 1e-4 for r in parity), 'export parity differs')
    remote = parent.read('training-remote-verification.json')
    need(remote['status'] == 'verified' and remote['receipts'] == prepared['training_receipts'] and
         len(remote['receipts']) == 4, 'training receipt verification differs')
    prompts = parent.read('prompt-comparison.json')
    need(prompts == dict(status='pass', generation_calls=228, jobs={j['id']: j['rows'] for j in jobs},
                         unique_prompts={'train': 52, 'holdout': 24}), 'parent prompt comparison differs')
    return prepared, scientific, jobs, bindings


def artifact_list(journal, items, original_output, expected):
    need(len(items) == len(expected), 'native artifact receipt coverage differs')
    found = set()
    for item in items:
        name = str(Path(item['path']).relative_to(original_output))
        need(name in expected and name not in found, 'native artifact receipt path differs')
        check(journal.path(name), item)
        found.add(name)
    need(found == set(expected), 'native artifact receipt differs')


def verify_collector(parent, journal, job, bindings):
    args = evaluation.argument_map(job['argv'])
    run_id, count, split = args['--run-id'], job['rows'], job['split']
    journal.units(['inputs'] + [f'case-{i:03d}-{stage}' for i in range(count)
                  for stage in ('intent', 'tokenizer', 'result')] + ['completion'], run_id)
    outer = parent.read('_receipts/' + job['id'] + '.json')
    result, completed = outer['result'], journal.read('completion.json')
    need(outer['argv'] == job['argv'] and result.get('status') == 'completed' and
         result.get('archive_status') == 'verified' and result.get('cases') == count and
         result.get('run_id') == run_id and completed.get('status') == 'native_completed' and
         completed.get('archive_status') == 'requires_verified_receipt' and completed.get('inputs_unchanged') is True and
         all(result.get(k) == v for k, v in completed.items() if k not in ('status', 'archive_status')),
         'collector completion differs')
    journal.receipt(result['remote_verification'], 'completion')
    manifest = journal.read('manifest.json')
    corpus_path = journal.path('inputs/corpus.jsonl')
    corpus, corpus_binding = score.read_jsonl(corpus_path)
    check(corpus_path, bindings[job['source']])
    model_bytes = (bindings['models/base-qwen.gguf']['bytes'] if job['model'] == 'shared_base_update0' else
                   parent.path('exports/' + job['model'].split('_', 1)[0] + '/jovovich.gguf').stat().st_size)
    def same_path(recorded, argument):
        return (recorded == argument if Path(argument).is_absolute() else
                Path(recorded).is_absolute() and recorded.endswith('/' + argument))
    need(manifest['run_id'] == run_id and manifest['split'] == split and
         manifest['corpus']['sha256'] == corpus_binding['sha256'] and manifest['corpus']['bytes'] == corpus_binding['bytes'] and
         same_path(manifest['corpus']['path'], args['--sft']) and
         manifest['model']['sha256'] == args['--model-sha256'] and manifest['model']['bytes'] == model_bytes and
         same_path(manifest['model']['path'], args['--model']) and
         manifest['infer']['sha256'] == args['--infer-sha256'] == bindings['build/jovovich-infer']['sha256'] and
         manifest['infer']['bytes'] == bindings['build/jovovich-infer']['bytes'] and
         same_path(manifest['infer']['path'], args['--infer']) and
         manifest['temperature'] == 0 and manifest['token_budget'] == collect.LIMIT and
         manifest['context'] == collect.CONTEXT and manifest['environment'] == collect.ENVIRONMENT and
         manifest['assistant_prefix'] == '<|im_start|>assistant\n', 'collector source/model contract differs')
    sources = ['training/explanations/collect_generation.py', 'training/durable_archive.py', 'src/infer.c', 'Makefile']
    if split == 'holdout':
        sources += ['bin/jovovich.mjs', 'prompts/identity.txt', 'training/explanations/build_corpora.py']
    need(len(manifest['sources']) == len(sources), 'collector source list differs')
    for i, (name, item) in enumerate(zip(sources, manifest['sources'])):
        need(item['path'].endswith('/' + name) and
             (item['bytes'], item['sha256']) == (bindings[name]['bytes'], bindings[name]['sha256']),
             'collector source binding differs')
        check(journal.path('inputs/sources/' + str(i) + '-' + Path(name).name), item)
    rendered = collect.review_cases(corpus_path.read_bytes(), split=split)
    cases, pairs = (score.corpus_cases(corpus, job['expected_order']) if split == 'train' else
                    score.holdout_cases(corpus, corpus_path.read_bytes()))
    need(len(rendered) == count and len(pairs) == count // 2, 'source case coverage differs')
    generations = journal.path('generations.jsonl')
    records, file_binding = score.read_jsonl(generations)
    need(completed['generations_sha256'] == file_binding['sha256'] and len(records) == count and
         len(manifest['cases']) == count and len({r['case_id'] for r, _ in records}) == count,
         'missing or duplicate generation row')
    structural = parent.read('generation/' + job['id'] + '/structural-score.json')
    need(structural['status'] == 'complete' and structural['summary']['received_reviews'] == count and
         structural['generations']['sha256'] == file_binding['sha256'] and
         structural['corpus']['sha256'] == corpus_binding['sha256'], 'structural score binding differs')
    rows, prompt_ids = [], []
    for i, ((record, line_binding), intended, recorded) in enumerate(zip(records, rendered, manifest['cases'])):
        case_id, base = intended['case_id'], f'cases/{i:03d}/'
        need(recorded == {k: v for k, v in intended.items() if k != 'prompt'} | {'prompt_path': base + 'prompt.txt'} and
             record['case_id'] == case_id, 'collector case identity/order differs')
        prompt = journal.path(base + 'prompt.txt').read_bytes()
        need(prompt == intended['prompt'], 'archived prompt bytes differ from frozen source')
        score.validate_record(record, corpus_binding['sha256'])
        need(record == journal.read(base + 'record.json') and record['finish_reason'] in ('eos', 'length') and
             record['raw_response'] == journal.path(base + 'stdout.bin').read_bytes().decode(),
             'raw response differs from archived native result')
        trace, tokenizer = journal.read(base + 'tokens.json'), journal.read(base + 'tokenizer-result.json')
        ids = collect.parse_prompt_ids(journal.path(base + 'prompt-token-ids.txt').read_bytes())
        need(collect.validate_trace(trace) == record['finish_reason'] and trace['prompt_token_ids'] == ids and
             tokenizer['case_id'] == case_id and tokenizer['status'] == 'completed' and
             tokenizer['return_code'] == 0 and tokenizer['error_type'] is None and tokenizer['prompt_token_ids'] == ids,
             'native/tokenizer correspondence differs')
        metadata = record['metadata']
        need(metadata['prompt_sha256'] == intended['prompt_sha256'] and
             metadata['model_sha256'] == args['--model-sha256'] and metadata['model_path'] == manifest['model']['path'] and
             metadata['requested_limit'] == collect.LIMIT and metadata['prompt_token_ids'] == ids and
             metadata['generated_token_ids'] == trace['generated_token_ids'], 'generation metadata differs')
        intent, native = journal.read(base + 'intent.json'), journal.read(base + 'result.json')
        need(intent['case_id'] == case_id and intent['prompt_sha256'] == intended['prompt_sha256'] and
             intent['environment'] == collect.ENVIRONMENT and
             intent['argv'] == collect.native_command(manifest['infer']['path'], manifest['model']['path'],
                                                      Path(args['--output']) / base / 'tokens.json') and
             intent['tokenizer_argv'] == collect.token_command(manifest['infer']['path'], manifest['model']['path']) and
             native['case_id'] == case_id and native['return_code'] == native['tokenizer_return_code'] == 0 and
             native['finish_reason'] == record['finish_reason'], 'native invocation/result differs')
        artifact_list(journal, tokenizer['artifacts'], Path(args['--output']),
                      [base + n for n in ('prompt-token-ids.txt', 'tokenizer.stderr.bin')])
        artifact_list(journal, native['artifacts'], Path(args['--output']),
                      [base + n for n in ('stdout.bin', 'stderr.bin', 'tokens.json', 'record.json')])
        case = cases[case_id]
        source_row = corpus[case['row']][0]
        gold = source_row['gold'] if split == 'holdout' else score.strict_json(source_row['messages'][2]['content'])
        rows.append(dict(split=split, case_id=case_id, pair=case['pair'], exact_prompt=prompt.decode(),
            prompt_sha256=intended['prompt_sha256'], raw_response=record['raw_response'],
            raw_response_sha256=record['raw_response_sha256'], raw_record_file_sha256=file_binding['sha256'],
            raw_record_line_sha256=line_binding['sha256'], finish_reason=record['finish_reason'],
            changed_line_table=changed_lines(prompt.decode()), expected_concern=case['expected_concern'],
            canonical_gold_findings=gold['findings'],
            candidate_line_ids=case.get('supplied_candidate_line_ids', case['expected_ids'])))
        prompt_ids.append((case_id, prompt, ids))
    return rows, prompt_ids


def prepare(parent_directory, collector_directories, output, *, run_id, revision):
    output = clean_path(output)
    need(not output.exists(), 'packet output must be new')
    parent = Recovery(parent_directory)
    prepared, scientific, jobs, bindings = verify_parent(parent, run_id, revision)
    journals = [Recovery(p) for p in collector_directories]
    indexed = {j.ledger['run_id']: j for j in journals}
    need(len(indexed) == len(journals) == 6 and set(indexed) == {
        evaluation.argument_map(j['argv'])['--run-id'] for j in jobs}, 'six distinct collector recoveries are required')
    notorch = {j.read('manifest.json')['notorch_commit'] for j in journals}
    need(len(notorch) == 1 and isinstance(next(iter(notorch)), str) and
         re.fullmatch(r'[0-9a-f]{40}', next(iter(notorch))), 'collector NoTorch identities differ')
    if 'continuation' in prepared:
        host = parent.read('inputs/' + prepared['continuation']['host_manifest']['path'])
        need(notorch == {host['notorch_commit']}, 'collector NoTorch differs from the training host')
    model_slots = {model: 'model-' + secrets.token_hex(8) for model in
                   ('shared_base_update0', 'before_update100', 'after_update100')}
    need(len(set(model_slots.values())) == 3, 'opaque model slot collision')
    rows, references = [], {}
    for job in jobs:
        journal = indexed[evaluation.argument_map(job['argv'])['--run-id']]
        batch, prompts = verify_collector(parent, journal, job, bindings)
        need(job['split'] not in references or references[job['split']] == prompts,
             'cross-model prompt bytes/token IDs differ')
        references[job['split']] = prompts
        for row in batch:
            row['opaque_model_slot'] = model_slots[job['model']]
        rows.extend(batch)
    need(len(rows) == 228, 'semantic packet coverage differs')
    for row, result in zip(rows, production_parse(rows)):
        row['actual_production_parse_result'] = result
    fields = prepared['contract']['semantic_audit']['packet_fields']
    need(all(set(row) == set(fields) for row in rows), 'frozen semantic packet fields differ')
    # Random slots are sorted, breaking the known base/before/after collector order.
    rows.sort(key=lambda r: (r['opaque_model_slot'], r['split'], r['case_id']))
    judgments = [{**{k: row[k] for k in ('opaque_model_slot', 'split', 'case_id', 'pair')},
                  **{key: None for key in prepared['contract']['semantic_audit']['judgment_fields']}} for row in rows]
    rubric = dict(schema='jovovich.blinded-semantic-rubric.v1', archive_status='pending_archive',
        full_review_rubric=scientific['primary_evaluation']['full_review_rubric'],
        instructions='Read each exact prompt and complete actual response. Fill every judgment field independently. '
        'Keep the opaque model slots. The operator publishes the packet before review and adjudicates differences '
        'before revealing the mapping. Structural parser results are supplied evidence; semantic judgments remain yours.',
        judgment_fields=prepared['contract']['semantic_audit']['judgment_fields'])
    output.mkdir(parents=True, mode=0o700)
    for reviewer in ('reviewer-1', 'reviewer-2'):
        directory = output / reviewer
        save(directory / 'rubric.json', rubric)
        for name, records in (('packet.jsonl', rows), ('judgments.jsonl', judgments)):
            with (directory / name).open('x') as stream:
                for record in records:
                    stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
    save(output / 'operator/model-mapping.json', dict(schema='jovovich.semantic-mapping.v1',
        disclosure='Withhold from both reviewers until their judgments and adjudication are archived.', model_slots=model_slots))
    save(output / 'operator/provenance.json', dict(schema='jovovich.semantic-packet-provenance.v1',
        run_id=run_id, parent_recovery=parent.ledger, collector_recoveries=[j.ledger for j in journals],
        input_directories=[str(parent.root), *[str(j.root) for j in journals]], source_bindings=prepared['bindings'],
        implementation_sha256=sha(Path(__file__).read_bytes()), semantic_contract=prepared['contract']['semantic_audit'],
        training_calls=0, semantic_judgments=0))
    artifacts = [dict(path=str(p.relative_to(output)), bytes=p.stat().st_size, sha256=sha(p.read_bytes()))
                 for p in sorted(output.rglob('*')) if p.is_file()]
    result = dict(schema='jovovich.semantic-packet-preparation.v1', status='prepared',
                  archive_status='pending_archive', ready_for_review=False, rows=228,
                  reviewers=2, semantic_judgments=0, artifacts=artifacts)
    save(output / 'preparation.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evaluation', required=True, type=Path)
    parser.add_argument('--collector', action='append', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--evaluation-revision', required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.evaluation, args.collector, args.output,
                         run_id=args.run_id, revision=args.evaluation_revision)
        print(json.dumps({k: result[k] for k in ('status', 'archive_status', 'rows', 'reviewers', 'semantic_judgments')}))
    except (ValueError, RuntimeError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        reason = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
        print('prepare_semantic_packet: stopped: ' + reason + '; inputs retained', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
