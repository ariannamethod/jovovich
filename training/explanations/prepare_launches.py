#!/usr/bin/env python3
"""Bind the prepared order experiment and its second arm's initialization."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_training import validate_plan


def need(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def binding(path):
    path = path.resolve()
    need(path.is_relative_to(ROOT), 'bound files must be inside the repository')
    return {'path': str(path.relative_to(ROOT)), 'bytes': path.stat().st_size, 'sha256': sha(path)}


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def prepare(base, preflight, output, run_prefix):
    need(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', run_prefix), 'invalid run prefix')
    base, preflight, output = base.resolve(), preflight.resolve(), output.resolve()
    need(not output.exists(), 'launch directory must be new')
    report = json.loads((preflight / 'verification.json').read_text())
    need(report['status'] == 'pass' and report['native_chatml_comparisons'] == 304 and
         report['identical_prompt_and_content_rows'] == 52, 'complete native preflight required')
    recorded = json.loads((preflight / 'bindings.json').read_text())['files']
    verifiers = [Path(item['path']) for item in recorded
                 if item['path'].endswith('/training/explanations/verify_native.py')]
    need(len(verifiers) == 1, 'preflight verifier binding missing or ambiguous')
    recorded_root = verifiers[0].parents[2]
    for index, item in enumerate(recorded):
        original_path = Path(item['path'])
        need(original_path.is_relative_to(recorded_root), 'preflight binding escapes recorded repository')
        path = base if index == 0 else ROOT / original_path.relative_to(recorded_root)
        need(path.stat().st_size == item['bytes'] and sha(path) == item['sha256'],
             'preflight source binding changed: ' + str(path))
    spec_path = ROOT / 'training/explanations/plan.json'
    spec = json.loads(spec_path.read_text())
    need(sha(base) == spec['training']['base_expected_sha256'], 'wrong base model')
    evaluation_template = ROOT / 'training/explanations/evaluation_plan.json'
    evaluation = json.loads(evaluation_template.read_text())
    need(evaluation['schema'] == 'jovovich.explanation-order.evaluation.v1',
         'unsupported evaluation contract')
    packed = set()
    # Freeze the selected preflight paths before either arm starts. The source
    # contract's archived example paths are not the paths of a fresh repeat.
    for arm in ('before', 'after'):
        export = next(item for item in evaluation['exports'] if item['arm'] == arm)
        parity = next(step for step in export['steps'] if step['id'] == arm + '-native-export-parity')
        previous = parity['argv'][3]
        previous_pair = previous[:-4] + '.pairs.bin'
        dataset = str((preflight / (arm + '.bin')).relative_to(ROOT))
        pair_map = str((preflight / (arm + '.pairs.bin')).relative_to(ROOT))
        need(previous in evaluation['required_pretraining_launch_bindings'] and
             previous_pair in evaluation['required_pretraining_launch_bindings'],
             'evaluation packed-input requirements are incomplete')
        parity['argv'][3] = dataset
        replacements = {previous: dataset, previous_pair: pair_map}
        evaluation['required_pretraining_launch_bindings'] = [
            replacements.get(path, path) for path in evaluation['required_pretraining_launch_bindings']]
        packed.update((dataset, pair_map))
    evaluation_path = output / 'evaluation-plan.json'
    evaluation['required_pretraining_launch_bindings'].append(str(evaluation_path.relative_to(ROOT)))
    common = [base, ROOT / 'build/jovovich-train-mlp', spec_path,
              ROOT / 'training/durable_archive.py', ROOT / 'training/layers/run_layers.py',
              ROOT / 'training/train_mlp.c', ROOT / 'training/prepare.py',
              ROOT / 'training/score_decisions.py', ROOT / 'training/score_training.py',
              ROOT / 'training/explanations/reasons.json',
              ROOT / 'training/sft_review_v5.jsonl', ROOT / 'training/review_holdout_v5.jsonl',
              ROOT / 'training/sft_review_v6_before.jsonl', ROOT / 'training/sft_review_v6_after.jsonl',
              preflight / 'verification.json', preflight / 'bindings.json', evaluation_path]
    common += [ROOT / path for path in evaluation['required_pretraining_launch_bindings'] if path not in packed]
    common += sorted((ROOT / 'training/explanations').glob('*.py'))
    common += [ROOT / 'deps/notorch' / name for name in (
        'notorch.c', 'notorch.h', 'notorch_simd.h', 'gguf.c', 'gguf.h',
        'harness/runtime.c', 'harness/runtime.h', 'harness/arch_llama.c',
        'harness/arch.h', 'harness/arch_models.h', 'examples/bpe.c', 'examples/bpe.h')]
    output.mkdir(parents=True)
    save(evaluation_path, evaluation)
    for arm in ('before', 'after'):
        paths = common + [preflight / (arm + '.bin'), preflight / (arm + '.pairs.bin')]
        bound = [binding(p) for p in dict.fromkeys(paths)]
        plan = {'schema_version': 1, 'run_id': run_prefix + '-' + arm,
                'argv': ['build/jovovich-train-mlp', str(base.relative_to(ROOT)),
                         str((preflight / (arm + '.bin')).relative_to(ROOT)), '@RUN@/adapter',
                         '100', '0.0001', '40', '25', 'joint',
                         str((preflight / (arm + '.pairs.bin')).relative_to(ROOT))],
                'environment': spec['training']['native_environment'], 'bindings': bound,
                'remote': {'private': True, 'repo': 'ataeff/jovovich',
                           'prefix': 'experiments/explanation-order'}, 'ack_timeout_ms': 300000,
                'arm': arm, 'scientific_plan_sha256': sha(spec_path),
                'evaluation_plan': str(evaluation_path.relative_to(ROOT))}
        validate_plan(plan)
        if arm == 'after':
            plan['schema_version'] = 'awaiting-before-initialization'
            save(output / 'after.template.json', plan)
        else:
            save(output / 'before.launch.json', plan)
    print(json.dumps({'status': 'prepared', 'directory': str(output),
                      'evaluation_plan': str(evaluation_path),
                      'after_requires': 'bind-after with the completed, remotely verified before run'}))


def bind_after(template, before_run, output):
    plan = json.loads(template.read_text())
    need(plan['schema_version'] == 'awaiting-before-initialization' and plan['arm'] == 'after',
         'expected unresolved after template')
    verified = json.loads((before_run / '_units/completion.ack.json').read_text())
    need(verified.get('status') == 'completed' and verified.get('archive_status') == 'verified',
         'verified before completion required')
    ack = verified.get('remote_verification', {})
    need(ack.get('verified_remote_bytes') is True and ack.get('unit_id') == 'completion' and
         re.fullmatch(r'[0-9a-f]{40}', ack.get('revision', '')), 'verified before completion required')
    completion_path = before_run / 'completion.json'
    bound = [item for item in ack['files'] if item['name'] == 'completion.json']
    need(len(bound) == 1 and bound[0]['sha256'] == sha(completion_path) and
         bound[0]['size'] == completion_path.stat().st_size, 'before completion receipt mismatch')
    completed = json.loads(completion_path.read_text())
    need(completed.get('acknowledged_updates') == 100 and completed.get('return_code') == 0,
         'before must complete its fixed 100 updates')
    before_plan = json.loads((before_run / 'plan.json').read_text())
    need(sha(before_run / 'plan.json') == completed.get('plan_sha256') and
         before_plan['bindings'] == completed['bindings'], 'before plan differs from archived evidence')
    need(before_plan.get('arm') == 'before' and before_plan['scientific_plan_sha256'] == plan['scientific_plan_sha256'],
         'before belongs to another experiment')
    need(all(before_plan['argv'][i] == plan['argv'][i] for i in (0, 1, 4, 5, 6, 7, 8)) and
         before_plan['environment'] == plan['environment'], 'arm training settings differ')
    # Only the packed dataset and pair map may have different source bindings.
    first = {b['path']: b for b in before_plan['bindings']}
    second = {b['path']: b for b in plan['bindings']}
    first = {p: b for p, b in first.items() if p not in (before_plan['argv'][2], before_plan['argv'][9])}
    second = {p: b for p, b in second.items() if p not in (plan['argv'][2], plan['argv'][9])}
    need(first == second, 'shared arm bindings differ')
    plan['schema_version'] = 1
    plan['expected_initial_lora_sha256'] = completed['initial_lora_sha256']
    plan['before_completion'] = {'revision': ack['revision'], 'manifest_sha256': ack['manifest_sha256'],
                                 'completion_sha256': sha(completion_path)}
    validate_plan(plan)
    save(output, plan)
    print(json.dumps({'status': 'after-bound', 'output': str(output)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--base', type=Path, required=True)
    prep.add_argument('--preflight', type=Path, required=True)
    prep.add_argument('--out', type=Path, required=True)
    prep.add_argument('--run-prefix', required=True)
    after = sub.add_parser('bind-after')
    after.add_argument('--template', type=Path, required=True)
    after.add_argument('--before-run', type=Path, required=True)
    after.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.mode == 'prepare':
        prepare(args.base, args.preflight, args.out, args.run_prefix)
    else:
        bind_after(args.template, args.before_run, args.output)


if __name__ == '__main__':
    main()
