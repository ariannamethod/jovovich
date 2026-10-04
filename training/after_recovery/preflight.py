#!/usr/bin/env python3
"""Authenticate the surviving paired evidence and prepare a non-runnable after contract.

This command performs remote reads and writes a fresh local evidence directory.
It never launches native work, uploads evidence, or resumes optimizer state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'training'))
from durable_archive import DurableArchive, HFTransport

INPUTS = ROOT / 'training/after_recovery/inputs.json'
# Only the archive parent and archive implementation may change. Numerical
# sources, binaries, datasets, tokenization and the evaluation remain frozen.
INFRASTRUCTURE = frozenset(('training/durable_archive.py',
                            'training/explanations/run_training.py'))
BLOCKERS = [
    'Implement a fresh after-only host launcher with source and watchdog pins.',
    'Materialize authenticated binaries and packed inputs; verify the pinned base model.',
    'Admit old before and new after infrastructure bindings explicitly in evaluation.',
    'Reconstruct training receipts from verified recovery manifests for evaluation.',
    'Recheck unused remote run IDs and archive the final launch contract before native startup.',
]


def need(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def regular(root, name):
    parts = PurePosixPath(name)
    need(isinstance(name, str) and parts.parts and not parts.is_absolute() and
         str(parts) == name and all(re.fullmatch(r'[A-Za-z0-9_.-]+', p) and p not in ('.', '..')
                                    for p in parts.parts), 'invalid bound path')
    path = root
    for part in parts.parts:
        path /= part
        need(not path.is_symlink(), 'symlink in bound path')
    need(path.is_file(), 'required bound file missing: ' + name)
    return path


def binding(path, name):
    return {'path': name, 'bytes': path.stat().st_size, 'sha256': digest(path)}


def check(path, item):
    need(path.stat().st_size == item['bytes'] and digest(path) == item['sha256'],
         'bound bytes changed: ' + item['path'])


def read(path):
    return json.loads(path.read_text())


def validate_inputs(value):
    need(set(value) == {'schema', 'original_source_commit', 'archive_revision', 'archive',
         'before_run_id', 'failed_after_run_id', 'before_plan_sha256',
         'before_completion_sha256', 'failed_after_plan_sha256',
         'expected_initial_lora_sha256', 'new_after_run_id', 'new_evaluation_run_id'} and
         value['schema'] == 'jovovich.matched-after-inputs.v1', 'invalid continuation inputs')
    for name in ('original_source_commit', 'archive_revision'):
        need(re.fullmatch(r'[0-9a-f]{40}', value[name]), 'invalid source/archive pin')
    for name in ('before_plan_sha256', 'before_completion_sha256', 'failed_after_plan_sha256'):
        need(re.fullmatch(r'[0-9a-f]{64}', value[name]), 'invalid evidence pin')
    ids = [value[k] for k in ('before_run_id', 'failed_after_run_id', 'new_after_run_id', 'new_evaluation_run_id')]
    need(len(set(ids)) == 4 and all(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,49}', x) for x in ids),
         'attempts need distinct safe run IDs')
    need(value['archive'] == {'private': True, 'repo': 'ataeff/jovovich',
                              'prefix': 'experiments/explanation-order'}, 'archive destination changed')
    initial = value['expected_initial_lora_sha256']
    need(set(initial) == {'gate', 'up', 'down'} and
         all(re.fullmatch(r'[0-9a-f]{64}', x) for x in initial.values()), 'invalid initial adapter pins')


def inspect_evidence(before_dir, after_dir, inputs, repo):
    """Only called with fresh remote recoveries by prepare(); local receipts alone are insufficient."""
    before, after = (read(p / 'plan.json') for p in (before_dir, after_dir))
    complete = read(before_dir / 'completion.json')
    for directory, key in ((before_dir, 'before_plan_sha256'), (after_dir, 'failed_after_plan_sha256')):
        need(digest(directory / 'plan.json') == inputs[key], 'archived plan differs from committed pin')
    need(digest(before_dir / 'completion.json') == inputs['before_completion_sha256'],
         'before completion differs from committed pin')
    need(complete.get('return_code') == 0 and complete.get('acknowledged_updates') == 100 and
         complete.get('plan_sha256') == inputs['before_plan_sha256'] and
         complete.get('bindings') == before['bindings'], 'before completion is not the fixed endpoint')
    need(complete.get('initial_lora_sha256') == after.get('expected_initial_lora_sha256') ==
         inputs['expected_initial_lora_sha256'], 'paired initial adapters changed')
    need(after.get('before_completion', {}).get('completion_sha256') == inputs['before_completion_sha256'],
         'failed after was paired with another before completion')
    frozen = {}
    source_changes = []
    for arm, plan, directory, id_key in (
            ('before', before, before_dir, 'before_run_id'),
            ('after', after, after_dir, 'failed_after_run_id')):
        receipt = read(directory / '_durable-recovery.json')
        expected = ['intent', *('update-%03d' % i for i in range(101 if arm == 'before' else 10))]
        if arm == 'before':
            expected.append('completion')
        need(receipt.get('verified_remote_bytes') is True and receipt.get('revision') == inputs['archive_revision'] and
             receipt.get('run_id') == plan.get('run_id') == inputs[id_key] and
             receipt.get('prefix') == inputs['archive']['prefix'] + '/' + inputs[id_key] and
             receipt.get('next_sequence') == len(expected) and
             [(u['sequence'], u['unit_id']) for u in receipt['units']] == list(enumerate(expected)),
             'archive does not have the pinned attempt sequence')
        need(plan.get('arm') == arm and plan.get('schema_version') == 1 and
             plan.get('remote') == inputs['archive'], 'archived attempt identity differs')
        argv = plan['argv']
        need(len(argv) == 10 and argv[3:9] == ['@RUN@/adapter', '100', '0.0001', '40', '25', 'joint'] and
             plan['environment'] == {'NT_NO_I8': '1', 'NT_QMV_THREADS': '2',
                                     'NT_ATTN_THREADS': '2', 'NT_SIMD_THREADS': '2'},
             'fixed training settings changed')
        entries = {b['path']: b for b in plan['bindings']}
        need(len(entries) == len(plan['bindings']) and all(argv[i] in entries for i in (0, 1, 2, 9)),
             'missing or duplicate numerical input binding')
        # Each source snapshot must have appeared in the authenticated intent,
        # rather than merely somewhere in the later archive history.
        intent_files = {f['name']: f for f in receipt['units'][0]['files']}
        for name, item in entries.items():
            if name == argv[1]:
                continue  # The large public base is identified by its pinned hash.
            archived_name = 'inputs/' + name
            remote = intent_files.get(archived_name, {})
            need((remote.get('size'), remote.get('sha256')) == (item['bytes'], item['sha256']),
                 'input was not frozen in the original intent')
            check(regular(directory, archived_name), item)
            if arm == 'after' and PurePosixPath(name).parts[0] not in ('models', 'build'):
                current = binding(regular(repo, name), name)
                if current != item:
                    need(name in INFRASTRUCTURE, 'non-infrastructure source changed: ' + name)
                    source_changes.append({'path': name, 'original': item, 'candidate': current})
        frozen[arm] = {p: b for p, b in entries.items() if p not in (argv[2], argv[9])}
        initial = read(directory / '_units/initialization.json')['initial_lora_sha256']
        need(initial == inputs['expected_initial_lora_sha256'], 'archived initial adapter mismatch')
        for part in ('gate', 'up', 'down'):
            need(digest(regular(directory, 'adapter.epoch00.' + part + '.lora')) == initial[part],
                 'initial snapshot differs from the paired initialization')
    need(frozen['before'] == frozen['after'], 'original paired shared bindings disagree')
    need(all(before['argv'][i] == after['argv'][i] for i in (0, 1, 3, 4, 5, 6, 7, 8)) and
         before['evaluation_plan'] == after['evaluation_plan'] and
         before['scientific_plan_sha256'] == after['scientific_plan_sha256'], 'original paired settings disagree')
    scientific = read(after_dir / 'inputs/training/explanations/plan.json')
    need(scientific['training']['base_expected_sha256'] == frozen['after'][after['argv'][1]]['sha256'] and
         after['scientific_plan_sha256'] == digest(after_dir / 'inputs/training/explanations/plan.json'),
         'scientific/base identity changed')
    return before, after, source_changes


def prepare(connect, output, *, repo=ROOT, inputs_path=INPUTS):
    need(not sys.flags.optimize and not os.environ.get('PYTHONOPTIMIZE'), 'optimized Python is unsupported')
    repo = Path(repo).resolve()
    inputs_path = Path(inputs_path)
    need(inputs_path.resolve() == regular(repo, 'training/after_recovery/inputs.json').resolve(),
         'use the committed continuation inputs from this checkout')
    inputs_binding = binding(inputs_path, 'training/after_recovery/inputs.json')
    inputs = read(inputs_path)
    validate_inputs(inputs)
    output = Path(output).absolute()
    need(not output.exists() and not output.is_symlink(), 'preflight output must be new')
    need(not any(p.is_symlink() for p in output.parents), 'symlink in output path')
    transport = connect()
    archive = DurableArchive(transport, inputs['new_after_run_id'], inputs['archive']['prefix'])
    head = archive._remote('head')
    for key in ('new_after_run_id', 'new_evaluation_run_id'):
        prefix = inputs['archive']['prefix'] + '/' + inputs[key]
        need(not archive._remote('inventory', head, prefix), 'new remote run ID already has evidence')
    output.mkdir(parents=True)
    receipts = {}
    for arm, key in (('before', 'before_run_id'), ('failed-after', 'failed_after_run_id')):
        receipts[arm] = DurableArchive(transport, inputs[key], inputs['archive']['prefix']).recover(
            output / arm, inputs['archive_revision'])
    before, after, changes = inspect_evidence(output / 'before', output / 'failed-after', inputs, repo)
    check(inputs_path, inputs_binding)
    evaluation = next(b for b in after['bindings'] if b['path'] == after['evaluation_plan'])
    result = {
        'schema': 'jovovich.matched-after-preflight.v1', 'status': 'evidence-verified-admission-pending',
        'runnable': False, 'native_calls': 0, 'training_updates': 0, 'remote_writes': 0,
        'inputs': inputs, 'inputs_binding': inputs_binding,
        'preflight_implementation_sha256': digest(Path(__file__)),
        'remote_head_at_freshness_check': head,
        'recovered_units': {arm: len(receipt['units']) for arm, receipt in receipts.items()},
        'after_argv': after['argv'], 'training_environment': after['environment'],
        'ack_timeout_ms': after['ack_timeout_ms'], 'fixed_endpoint': 100,
        'optimizer_initialization': 'fresh process at update zero; no checkpoint resume',
        'expected_initial_lora_sha256': inputs['expected_initial_lora_sha256'],
        'original_bindings': after['bindings'], 'infrastructure_changes': changes,
        'allowed_infrastructure_paths': sorted(INFRASTRUCTURE),
        'frozen_evaluation_binding': evaluation,
        'evaluation_models': ['shared_base_update0', 'original_before_update100', 'fresh_after_update100'],
        'evaluation_policy': 'Keep original contract bytes, 228 responses, parity rows and preregistration.',
        'remaining_blockers': BLOCKERS,
    }
    with (output / 'preflight.json').open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--token-file', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(lambda: HFTransport('ataeff/jovovich', args.token_file.read_text().strip()), args.output)
        print(json.dumps({key: result[key] for key in ('status', 'runnable', 'recovered_units', 'remaining_blockers')}))
    except Exception as error:
        # No transport/credential exception text escapes through the CLI.
        print('matched-after preflight failed: ' + type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
