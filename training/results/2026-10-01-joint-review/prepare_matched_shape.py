#!/usr/bin/env python3
"""Rebind the frozen eight-case probe to a checkout and completed control receipts.

Run from the repository root. This helper never runs the tokenizer or model.
"""
import argparse
import copy
import hashlib
import json
import os
import shlex
from datetime import datetime, timezone
from pathlib import Path


PREFIX = '{"findings'
PREFIX_IDS = [4913, 3903, 819]
DECODING = dict(temperature=0, continuation_tokens=192, context=2048, threads=2, NT_NO_I8='1')
MODEL_SHA256 = 'a60b4009f22b036ccbd4982559332cd0f85439a74a5db721810efbb6ccd96e6c'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def text_sha(text):
    return sha(text.encode('utf-8'))


def read_jsonl(file):
    text = file.read_text(encoding='utf-8')
    require(text.endswith('\n'), f'JSONL is not newline-terminated: {file}')
    return [json.loads(line) for line in text.splitlines()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template', type=Path, required=True)
    parser.add_argument('--receipts', type=Path, default=Path('models/joint-review-control-train-shared.jsonl'))
    parser.add_argument('--output', type=Path, default=Path('models/matched-shape-plan.json'))
    parser.add_argument('--cases', type=Path)
    parser.add_argument('--wrapper', type=Path)
    args = parser.parse_args()
    root, template, output = Path.cwd().resolve(), args.template.resolve(), args.output.resolve()
    require(not os.path.lexists(args.output), f'Output already exists: {args.output}')
    require(output != template, 'The archived template must not be overwritten')
    template_bytes = template.read_bytes()
    plan = json.loads(template_bytes)
    require(plan['schema_version'] == 1 and plan['case_count'] == 8, 'Unsupported template')
    require(plan['decoding'] == DECODING, 'Template decoding changed')
    require(plan['supplied_prefix'] == PREFIX and plan['supplied_prefix_ids'] == PREFIX_IDS, 'Template prefix changed')
    require(plan['model']['path'] == 'models/decision-small-step-selected.gguf', 'Unsupported control model')
    require(plan['model']['sha256'] == MODEL_SHA256, 'Template control model identity changed')
    require(plan['model']['selected_update'] == 100, 'Control selection changed')
    require(plan['output'] == 'models/matched-shape-control.jsonl', 'Unsupported generation output')
    require(plan['trace_dir'] == 'models/matched-shape-control-traces', 'Unsupported trace directory')
    cases_path = (args.cases or template.parent / 'matched-shape-cases.jsonl').resolve()
    wrapper_path = (args.wrapper or template.parent / 'probe_matched_shape.mjs').resolve()
    require(cases_path == wrapper_path.parent / 'matched-shape-cases.jsonl',
            'The frozen wrapper requires matched-shape-cases.jsonl beside it')

    def relative(file):
        return os.path.relpath(file, root)

    def item(file):
        file = Path(file).resolve()
        digest = hashlib.sha256()
        with file.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        return dict(path=relative(file), sha256=digest.hexdigest(), bytes=file.stat().st_size)

    sources = plan['sources']
    paths = dict(cases=cases_path, wrapper=wrapper_path,
                 runner=root / 'build/jovovich-infer', infer=root / 'src/infer.c',
                 host=root / 'bin/jovovich.mjs', sft=root / 'training/sft_review_v2.jsonl',
                 baseline_receipts=args.receipts.resolve(),
                 basis_wrapper=template.parent / 'evaluate_joint_reviews.mjs',
                 scope_assessment=template.parent / 'shape-control-scope.json',
                 control_selection=root / 'training/results/2026-09-29-small-step/selected-model.json',
                 control_metrics=root / 'training/results/2026-09-29-small-step/metrics.jsonl')
    require(set(sources) == set(paths), 'Unsupported source keys in template')
    rebound_sources = {name: item(file) for name, file in paths.items()}
    for name in ('cases', 'wrapper', 'sft', 'basis_wrapper', 'scope_assessment', 'control_selection', 'control_metrics'):
        require(rebound_sources[name]['sha256'] == sources[name]['sha256'], f'Archived input changed: {name}')
    model = item(root / 'models/decision-small-step-selected.gguf')
    require(model['sha256'] == plan['model']['sha256'], 'Selected control model identity changed')
    require(model['bytes'] == plan['model']['bytes'], 'Selected control model size changed')

    cases = read_jsonl(cases_path)
    require(len(cases) == 8 and len({c['name'] for c in cases}) == 8, 'Expected eight unique cases')
    require([c['name'] for c in cases] == plan['case_ids'], 'Case IDs or order changed')
    for case in cases:
        require(case['id'] == case['name'], 'Case ID/name mismatch')
        require([m['role'] for m in case['messages']] == ['system', 'user'], 'Expected two stored prompt messages')
        prompt = ''.join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in case['messages'])
        prompt += '<|im_start|>assistant\n'
        require(prompt == case['prompt'] and text_sha(prompt) == case['prompt_sha256'], f"Prompt changed: {case['name']}")
    sft = {row['id']: row for row in read_jsonl(paths['sft']) if row['kind'] == 'review'}
    receipts = read_jsonl(paths['baseline_receipts'])
    by_name = {row['name']: row for row in receipts}
    require(len(receipts) == len(by_name) == 40 and set(by_name) == set(sft), 'Receipts must cover all 40 unique training reviews')
    for row in receipts:
        require(row['kind'] == 'train' and row['mode'] == 'shared' and row['returncode'] == 0, 'Incomplete or wrong-cohort receipt')
        require(row.get('signal') is None and not row.get('execution_error'), 'Failed control receipt')
        require(row['model_sha256'] == model['sha256'], 'Receipt model mismatch')
        require(row['source_sha256'] == rebound_sources['sft']['sha256'], 'Receipt SFT mismatch')
        require(row['decoding'] == DECODING, 'Receipt decoding mismatch')
        require(row['supplied_prefix'] == PREFIX and row['supplied_prefix_ids'] == PREFIX_IDS, 'Receipt prefix mismatch')
        require(row['assembled_response'] == PREFIX + row['continuation'], 'Incomplete assembled response')
        trace = row['trace']
        require(trace['schema_version'] == 1 and trace['requested_limit'] == 192, 'Wrong native trace schema or limit')
        require(trace['prompt_token_ids'] == row['original_prompt_ids'] + PREFIX_IDS, 'Receipt native prefix mismatch')
        generated, emitted, stop = trace['generated_token_ids'], trace['emitted_tokens'], trace['stop_reason']
        require(generated and all(type(token) is int and token >= 0 for token in generated), 'Invalid sampled IDs')
        require(type(emitted) is int and 0 <= emitted <= 192 and len(generated) <= 192, 'Invalid trace length')
        require(stop in ('eos', 'token-limit') and len(generated) == emitted + (stop == 'eos'), 'Incomplete native trace')
        require(stop != 'token-limit' or emitted == 192, 'Incomplete token-limit receipt')
        require(row['stop_reason'] == stop and row['actual_first_token_id'] == generated[0], 'Receipt trace summary differs')

    baseline_cases = [c for c in cases if c['metadata']['is_original_baseline']]
    old_baselines = {b['name']: b for b in plan['baselines']}
    require(len(baseline_cases) == len(old_baselines) == 2, 'Exactly two original baselines required')
    baselines = []
    for case in baseline_cases:
        name, original = case['name'], case['metadata']['original_training_id']
        row, old = by_name[original], old_baselines[case['name']]
        require(old['original_training_id'] == original, 'Baseline identity changed')
        require(row['prompt'] == case['prompt'] and row['prompt_sha256'] == case['prompt_sha256'], f'Baseline prompt mismatch: {name}')
        require(row['original_prompt_ids'] == case['original_prompt_expected_ids'], f'Baseline token IDs mismatch: {name}')
        require(row['supplied_prompt_sha256'] == text_sha(case['prompt'] + PREFIX), f'Supplied prompt mismatch: {name}')
        require(sft[original]['messages'][:2] == case['messages'], f'Original SFT messages changed: {name}')
        require(sft[original]['messages'][2]['content'] == case['expected_response'], f'Original gold response changed: {name}')
        require(row['actual_first_token_id'] == old['expected_first_token_id'] == 66582, 'Baseline first ID incompatible with frozen wrapper')
        baselines.append(dict(name=name, original_training_id=original,
                              previous_receipt_path=relative(paths['baseline_receipts']),
                              previous_prompt_sha256=row['prompt_sha256'], expected_first_token_id=row['actual_first_token_id'],
                              previous_assembled_response_sha256=text_sha(row['assembled_response']),
                              previous_continuation_sha256=text_sha(row['continuation']),
                              original_prompt_ids_sha256=text_sha(json.dumps(row['original_prompt_ids'], separators=(',', ':'))),
                              original_prompt_token_count=len(row['original_prompt_ids']), stop_reason=row['stop_reason']))

    fresh = copy.deepcopy(plan)
    fresh.update(status='Rebound from archived template before tokenizer or model execution.',
                 created_at_utc=datetime.now(timezone.utc).isoformat(), sources=rebound_sources, baselines=baselines)
    # The fixed model alias may be a symlink into a cache. Keep its logical path
    # because the native wrapper requires this repository-relative identity.
    fresh['model'].update(sha256=model['sha256'], bytes=model['bytes'])
    fresh['reproduction_template'] = dict(path=relative(template), sha256=sha(template_bytes))
    fresh['preparation_helper'] = item(Path(__file__).resolve())
    fresh['validation_before_freeze'] = dict(completed_control_receipts=40, stored_prompt_hashes_verified=8,
                                            baseline_original_ids_equal_existing_control_receipts=2,
                                            baseline_supplied_ids_equal_existing_traces=2,
                                            tokenizer_or_inference_runs_during_preparation=0)
    fresh['command'] = shlex.join(['node', relative(wrapper_path), '--output', fresh['output'],
                                   '--trace-dir', fresh['trace_dir'], '--plan', relative(output)])
    require(template.read_bytes() == template_bytes, 'Archived template changed during preparation')
    encoded = (json.dumps(fresh, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
    with args.output.open('xb') as stream:
        stream.write(encoded)
    print(json.dumps(dict(plan=relative(output), sha256=sha(encoded), bytes=len(encoded))))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        raise SystemExit(f'prepare-matched-shape: {error}')
