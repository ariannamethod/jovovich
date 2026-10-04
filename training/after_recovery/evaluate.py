#!/usr/bin/env python3
"""Admit the pinned before and repaired after parents to the original evaluation."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'training'))
from explanations import execute_evaluation as original
from explanations.execute_evaluation import (need, local, read, binding, digest, check_binding,
    native_environment, export_unit)
from durable_archive import ArchiveError, DurableArchive, HFTransport, sync_unit_with_retry
from after_recovery.bind import (committed_binding, verify_record, source_bindings,
                                 recovered_receipt, checked_recovery)
from after_recovery.preflight import INFRASTRUCTURE, inspect_evidence


def admission(before, after, record_path, source_sha, run_id):
    before, after, record_path = (local(p, existing=False) for p in (before, after, record_path))
    launch = read(after / 'plan.json')
    metadata = launch.get('continuation', {})
    need(metadata.get('schema') == 'jovovich.matched-after-continuation.v1' and
         metadata.get('source_commit') == source_sha, 'continuation source identity mismatch')
    need(metadata.get('binding_report') == binding(record_path), 'continuation record bytes changed')
    record = read(record_path)
    need(record == {k: v for k, v in metadata.items() if k != 'binding_report'},
         'continuation record disagrees with the training plan')
    need(metadata['before_recovered'] == str(before.relative_to(ROOT)), 'wrong recovered before directory')
    pinned_inputs = committed_binding(ROOT, 'training/after_recovery/inputs.json', source_sha)
    need(metadata['inputs'] == pinned_inputs, 'continuation input pins differ')
    inputs = read(ROOT / pinned_inputs['path'])
    need(run_id == inputs['new_evaluation_run_id'] and launch['run_id'] == inputs['new_after_run_id'] and
         metadata['archive_revision'] == inputs['archive_revision'] and
         metadata['original_source_commit'] == inputs['original_source_commit'],
         'continuation attempt or archive pin differs')
    before_plan = read(before / 'plan.json')
    need(before_plan['run_id'] == inputs['before_run_id'] and
         digest(before / 'plan.json') == inputs['before_plan_sha256'] and
         digest(before / 'completion.json') == inputs['before_completion_sha256'],
         'surviving before identity changed')
    old_after = local(metadata['original_plans']['failed_after']['path'])
    check_binding(old_after, metadata['original_plans']['failed_after'])
    need(digest(old_after) == inputs['failed_after_plan_sha256'], 'original after plan changed')
    frozen = read(old_after)
    for key in ('arm', 'argv', 'environment', 'remote', 'ack_timeout_ms', 'scientific_plan_sha256',
                'evaluation_plan', 'expected_initial_lora_sha256'):
        need(launch.get(key) == frozen.get(key), 'after training configuration changed: ' + key)
    need(launch.get('before_completion') == {
        'run_id': inputs['before_run_id'], 'revision': inputs['archive_revision'],
        'manifest_sha256': metadata['before_receipts'][0]['manifest_sha256'],
        'completion_sha256': inputs['before_completion_sha256']}, 'before completion binding changed')
    changes = metadata['infrastructure_changes']
    record_name = metadata['infrastructure_record']['path']
    need(verify_record(ROOT, record_name, source_sha, changes) == metadata['infrastructure_record'],
         'infrastructure record binding differs')
    need(launch.get('infrastructure_changes') == changes, 'after infrastructure declaration differs')
    original_bindings = {b['path']: b for b in frozen['bindings']}
    replacements = {}
    for change in changes:
        name = change['path']
        need(name in INFRASTRUCTURE and name not in replacements and
             change['original'] == original_bindings.get(name) and
             change['candidate'] == binding(local(name)), 'infrastructure pair differs')
        replacements[name] = change
    # Recompute the closed set of continuation dependencies independently of the
    # submitted declaration. Rehashing an edited report cannot omit a helper or
    # authorize a new models/* payload.
    failed_dir = local(metadata['failed_after_recovered'], existing=False)
    need(failed_dir == before.parent / 'failed-after' and before.name == 'before',
         'recovered evidence directories disagree')
    expected_paths = [before.parent / 'preflight.json', before / 'plan.json',
                      failed_dir / 'plan.json', before / 'completion.json',
                      before / '_durable-recovery.json', failed_dir / '_durable-recovery.json',
                      before / '_units/completion.ack.json', before / '_units/update-100.ack.json']
    need(metadata['original_plans'] == {'before': binding(before / 'plan.json'),
                                       'failed_after': binding(failed_dir / 'plan.json')} and
         metadata['preflight'] == binding(expected_paths[0]) and
         metadata['before_completion'] == binding(before / 'completion.json'),
         'continuation recovery bindings differ')
    before_ledger = checked_recovery(before)
    checked_recovery(failed_dir)
    _, _, observed_changes = inspect_evidence(before, failed_dir, inputs, ROOT)
    need(observed_changes == changes, 'continuation source changes differ from recovered evidence')
    need(before_ledger['revision'] == inputs['archive_revision'] and
         before_ledger['run_id'] == inputs['before_run_id'] and
         metadata['before_receipts'] == [recovered_receipt(before_ledger, unit)
                                        for unit in ('completion', 'update-100')],
         'continuation before receipts differ from the recovery ledger')
    expected_extra = source_bindings(ROOT, source_sha) + [metadata['infrastructure_record']]
    expected_extra += [binding(path) for path in expected_paths]
    host_item = metadata['host_manifest']
    prefix = inputs['new_after_run_id'].removesuffix('-after')
    need(isinstance(host_item, dict) and
         host_item.get('path') == f'models/{prefix}-job/host-manifest.json',
         'managed continuation requires its bound host manifest')
    host_path = local(host_item['path'])
    launcher = host_path.parent / 'launcher.sh'
    host = read(host_path)
    need(binding(host_path) == host_item and host['source_commit'] == source_sha and
         host['launch_inputs'] == inputs and host['infrastructure_record'] == metadata['infrastructure_record'] and
         digest(launcher) == digest(local('training/after_recovery/host_launch.sh')),
         'continuation host provenance differs')
    expected_extra += [host_item, binding(launcher)]
    unique = {}
    for item in expected_extra:
        name = item['path']
        if name in original_bindings:
            need(item == original_bindings[name], 'continuation dependency changes original input')
            continue
        need(name not in unique or unique[name] == item, 'conflicting continuation dependencies')
        unique[name] = item
    declared = {item['path']: item for item in metadata['added_bindings']}
    need(len(declared) == len(metadata['added_bindings']) and declared == unique,
         'continuation dependency set differs from required sources and evidence')
    extra = [*metadata['added_bindings'], metadata['binding_report']]
    added = {b['path']: b for b in extra}
    need(len(added) == len(extra) and not (set(added) & set(original_bindings)),
         'continuation extra bindings collide with original inputs')
    for name, item in added.items():
        check_binding(local(name), item)
        if not name.startswith('models/'):
            need(committed_binding(ROOT, name, source_sha) == item, 'uncommitted continuation source')
    expected = dict(original_bindings)
    expected.update({name: c['candidate'] for name, c in replacements.items()})
    expected.update(added)
    actual = {b['path']: b for b in launch['bindings']}
    need(len(actual) == len(launch['bindings']) and actual == expected,
         'after bindings differ from the reviewed continuation')
    return {'changes': replacements, 'added': added, 'record': metadata}


def prepare(plan_path, before, after, output, run_id, continuation_record, source_sha):
    need(not sys.flags.optimize and not os.environ.get('PYTHONOPTIMIZE'),
         'optimized Python execution is unsupported')
    need(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,49}', run_id), 'invalid evaluation run ID')
    plan_path = local(plan_path)
    output = local(output, existing=False)
    need(not output.exists(), 'evaluation destination must be new')
    contract = read(plan_path)
    need(contract.get('schema') == 'jovovich.explanation-order.evaluation.v1', 'unsupported evaluation contract')
    admitted = admission(before, after, continuation_record, source_sha, run_id)
    bindings, training, receipts, frozen_arms = {}, {}, [], {}
    scientific = read(local(contract['scientific_plan']))
    for arm, directory in (('before', before), ('after', after)):
        directory = local(directory, existing=False)
        launch_path = local(directory / 'plan.json')
        completion_path = local(directory / '_units/completion.ack.json')
        checkpoint_path = local(directory / '_units/update-100.ack.json')
        launch, completed, checkpoint = read(launch_path), read(completion_path), read(checkpoint_path)
        need(launch.get('arm') == arm, 'supplied training directory has the wrong arm')
        export = next(item for item in contract['exports'] if item['arm'] == arm)
        dataset = export['steps'][-1]['argv'][3]
        pairs = dataset[:-4] + '.pairs.bin'
        training_parameters = {
            'BASE': 'models/base-qwen.gguf', 'ARM_DATASET': dataset,
            'ARM_PREFIX': '@RUN@/adapter', 'ARM_PAIR_MAP': pairs}
        expected_argv = list(scientific['training']['argv_template'])
        for name, value in training_parameters.items():
            expected_argv = [argument.replace('@' + name + '@', value) for argument in expected_argv]
        need(launch['argv'] == expected_argv and launch['environment'] == scientific['training']['native_environment'],
             'training arguments or environment differ from the scientific contract')
        need(completed.get('status') == 'completed' and completed.get('archive_status') == 'verified' and
             completed.get('acknowledged_updates') == 100 and completed.get('return_code') == 0 and
             completed.get('plan_sha256') == digest(launch_path) and
             completed.get('bindings') == launch.get('bindings'), 'training completion is incomplete or unbound')
        need(launch['argv'][3] == '@RUN@/adapter' and launch['argv'][4] == '100' and
             launch['remote'] == {'repo': 'ataeff/jovovich', 'prefix': 'experiments/explanation-order', 'private': True},
             'training endpoint or archive differs from frozen contract')
        for receipt, unit in ((completed['remote_verification'], 'completion'), (checkpoint, 'update-100')):
            need(receipt.get('verified_remote_bytes') is True and receipt.get('run_id') == launch['run_id'] and
                 receipt.get('unit_id') == unit, 'training archive receipt mismatch')
            receipts.append(receipt)
            for entry in receipt['files']:
                path = local(directory / entry['name'])
                need(path.is_relative_to(directory), 'training receipt path escapes its attempt')
                item = binding(path)
                need(item['bytes'] == entry['size'] and item['sha256'] == entry['sha256'],
                     'local training evidence differs from its remote receipt')
                bindings[item['path']] = item
        raw_completion = read(directory / 'completion.json')
        need(all(completed.get(key) == value for key, value in raw_completion.items()
                 if key not in ('status', 'archive_status')), 'training completion receipt fields changed')
        frozen = {item['path']: item for item in launch['bindings']}
        need(dataset in frozen and pairs in frozen, 'arm packed inputs were not frozen before training')
        frozen_arms[arm] = {name: item for name, item in frozen.items() if name not in (dataset, pairs)}
        need(frozen[str(plan_path.relative_to(ROOT))]['sha256'] == digest(plan_path),
             'evaluation contract changed after training launch')
        for name, item in frozen.items():
            if arm == 'before' and name in admitted['changes']:
                # Preserve the original executed source at its authenticated archive path.
                path = local(directory / 'inputs' / name)
                need(digest(path) == item['sha256'] and path.stat().st_size == item['bytes'],
                     'original infrastructure evidence changed')
                archived = binding(path); bindings[archived['path']] = archived
                continue
            path = local(name)
            check_binding(path, item)
            need(name not in bindings or bindings[name] == item, 'training arm source bindings disagree')
            bindings[name] = item
        for path in (launch_path, completion_path, checkpoint_path, directory / 'completion.json'):
            item = binding(path); bindings[item['path']] = item
        for suffix in ('gate', 'up', 'down'):
            for extension in ('f32', 'lora'):
                for epoch in ('', '.epoch100'):
                    item = binding(directory / f'adapter{epoch}.{suffix}.{extension}')
                    bindings[item['path']] = item
        training[arm] = dict(directory=str(directory), run_id=launch['run_id'],
                             initial_lora_sha256=completed['initial_lora_sha256'])
    need(training['before']['directory'] != training['after']['directory'] and
         training['before']['run_id'] != training['after']['run_id'], 'training attempts must be distinct')
    expected_after = dict(frozen_arms['before'])
    expected_after.update({name: change['candidate'] for name, change in admitted['changes'].items()})
    expected_after.update(admitted['added'])
    need(expected_after == frozen_arms['after'], 'shared training source bindings disagree')
    need({'training/score_decisions.py', 'training/score_training.py', 'training/prepare.py'} <= set(bindings),
         'diagnostic scorer and its imports must be frozen in the training launches')
    need(set(contract['required_pretraining_launch_bindings']) <= set(bindings),
         'evaluation source was not frozen across the paired training launches')
    need(training['before']['initial_lora_sha256'] == training['after']['initial_lora_sha256'],
         'paired initialization hashes differ')
    helper = binding(Path(__file__))
    need(admitted['added'].get(helper['path']) == helper,
         'continuation evaluator was not bound before training')
    bindings[helper['path']] = helper
    parameters = {'BEFORE_RUN': training['before']['directory'], 'AFTER_RUN': training['after']['directory'],
                  'EVALUATION_RUN': str(output), 'EVALUATION_RUN_ID': run_id,
                  'INFER_SHA256': bindings['build/jovovich-infer']['sha256'],
                  'SHARED_BASE_UPDATE0_SHA256': bindings['models/base-qwen.gguf']['sha256']}
    need(parameters['SHARED_BASE_UPDATE0_SHA256'] == contract['resolution']['SHARED_BASE_UPDATE0_SHA256'],
         'base model differs from frozen Qwen')
    exports = [export_unit(step, parameters, output) for arm in contract['exports'] for step in arm['steps']]
    need([arm['arm'] for arm in contract['exports']] == ['before', 'after'] and len(exports) == 8,
         'expected both endpoint export sequences')
    need([r['index'] for r in contract['parity']['rows']] == [0, 1, 2, 3, 51], 'parity rows changed')
    need(sum(job['rows'] for job in contract['collector_jobs']) == 228 and len(contract['collector_jobs']) == 6,
         'expected six fixed collector jobs')
    native_environment(contract['native_environment'])
    return dict(schema_version=1, run_id=run_id, parameters=parameters, training=training,
                contract=contract, contract_source=str(plan_path.relative_to(ROOT)),
                continuation=admitted['record'],
                bindings=list(bindings.values()), training_receipts=receipts, export_phases=exports)



class RetryingArchive:
    """Apply the training archive retry contract to closed evaluation units."""
    def __init__(self, archive):
        self.archive = archive

    def __getattr__(self, name):
        return getattr(self.archive, name)

    def sync_unit(self, unit_id, files, *, sequence):
        # Full exported GGUF units include upload and fresh readback. Evaluation
        # has no waiting native ACK; give these large closed units fifteen minutes.
        return sync_unit_with_retry(self.archive, unit_id, files, sequence=sequence,
                                    deadline=time.monotonic() + 900, max_attempts=4)


def execute(archive, prepared, output, *, collector=original.collect):
    def closed_collector(journal, **kwargs):
        return collector(RetryingArchive(journal), **kwargs)
    return original.execute(RetryingArchive(archive), prepared, output, collector=closed_collector)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('preflight', 'run'))
    for name in ('plan', 'before', 'after', 'continuation-record', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--token-file', type=Path)
    args = parser.parse_args()
    try:
        prepared = prepare(args.plan, args.before, args.after, args.output, args.run_id,
                           args.continuation_record, args.source_sha)
        if args.mode == 'preflight':
            print(json.dumps({'status': 'preflight_passed', 'generation_calls': 228,
                              'parity_rows': [0, 1, 2, 3, 51], 'bindings': len(prepared['bindings'])}))
            return
        need(args.token_file is not None, 'archive token file is required')
        transport = HFTransport('ataeff/jovovich', args.token_file.read_text().strip())
        archive = DurableArchive(transport, args.run_id, 'experiments/explanation-order')
        print(json.dumps(execute(archive, prepared, local(args.output, existing=False))))
    except Exception as error:
        diagnostic = {'status': 'stopped', 'error_type': type(error).__name__}
        if isinstance(error, ArchiveError):
            diagnostic['archive_error'] = error.diagnostic
        print(json.dumps(diagnostic), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
