#!/usr/bin/env python3
"""Bind a fresh matched after trajectory to authenticated original evidence."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'training'), str(ROOT / 'training/explanations')]
from after_recovery.preflight import (INFRASTRUCTURE, binding, check, digest,
                                      inspect_evidence, need, read, regular,
                                      validate_inputs)
from run_training import validate_plan

SCHEMA = 'jovovich.matched-after-continuation.v1'
INPUTS = 'training/after_recovery/inputs.json'


def clean_path(path):
    need('..' not in Path(path).parts, 'parent traversal in continuation path')
    path = Path(path).absolute()
    need(not any(p.is_symlink() for p in (path, *path.parents)), 'symlink in continuation path')
    return path


def inside(repo, path):
    path = Path(path)
    path = clean_path(path if path.is_absolute() else repo / path)
    need(path.is_relative_to(repo), 'continuation path must remain inside the repository')
    return str(path.relative_to(repo))


def git(repo, *argv):
    # Inspect local immutable objects without inherited Git overrides or lazy
    # fetching; source inspection does not require credentials or a network.
    env = {'PATH': os.environ.get('PATH', os.defpath), 'LANG': 'C',
           'GIT_NO_LAZY_FETCH': '1', 'GIT_TERMINAL_PROMPT': '0',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull}
    try:
        return subprocess.check_output(['git', '--no-replace-objects', '-c', 'core.fsmonitor=false',
                                        '-C', str(repo), *argv], stderr=subprocess.DEVNULL,
                                       env=env, timeout=30)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise ValueError('required source Git object is unavailable') from None


def committed_binding(repo, name, source_sha):
    """Require both a regular checkout file and identical bytes in the pinned Git tree."""
    repo = clean_path(repo)
    need(isinstance(source_sha, str) and re.fullmatch(r'[0-9a-f]{40}', source_sha),
         'source must be a full commit SHA')
    path = regular(repo, name)
    entries = git(repo, 'ls-tree', '-z', source_sha, '--', name).split(b'\0')
    need(len(entries) == 2 and entries[-1] == b'' and b'\t' in entries[0],
         'required regular source Git object is unavailable')
    metadata, recorded_name = entries[0].split(b'\t', 1)
    fields = metadata.split()
    need(len(fields) == 3 and fields[0] in (b'100644', b'100755') and
         fields[1] == b'blob' and recorded_name.decode() == name,
         'source Git object is not a regular file')
    raw = git(repo, 'cat-file', 'blob', source_sha + ':' + name)
    current = binding(path, name)
    need(current['bytes'] == len(raw) and current['sha256'] == hashlib.sha256(raw).hexdigest(),
         'checkout differs from committed source: ' + name)
    return current


def verify_record(repo, name, source_sha, changes):
    """Admit exactly the observed archive repairs from a committed hash-pair record."""
    item = committed_binding(repo, name, source_sha)
    record = read(repo / name)
    entries = record.get('infrastructure_changes') if isinstance(record, dict) else None
    need(isinstance(entries, list), 'infrastructure record has no change list')
    indexed = {}
    for entry in entries:
        need(isinstance(entry, dict) and set(entry) == {'path', 'original', 'candidate'} and
             entry['path'] in INFRASTRUCTURE and entry['path'] not in indexed and
             all(isinstance(entry[k], dict) and set(entry[k]) == {'path', 'bytes', 'sha256'} and
                 entry[k]['path'] == entry['path'] and type(entry[k]['bytes']) is int and
                 entry[k]['bytes'] >= 0 and isinstance(entry[k]['sha256'], str) and
                 re.fullmatch(r'[0-9a-f]{64}', entry[k]['sha256']) for k in ('original', 'candidate')),
             'invalid infrastructure hash pair')
        need(entry['original'] != entry['candidate'], 'infrastructure pair records no change')
        indexed[entry['path']] = entry
    observed = {entry['path']: entry for entry in changes}
    need(len(observed) == len(changes) and indexed == observed,
         'infrastructure record differs from observed source changes')
    for name, entry in indexed.items():
        need(committed_binding(repo, name, source_sha) == entry['candidate'],
             'candidate infrastructure differs from committed source')
    return item


def source_bindings(repo, source_sha):
    names = git(repo, 'ls-tree', '-r', '--name-only', source_sha).decode().splitlines()
    selected = [name for name in names if (
        (name.startswith('training/after_recovery/') and Path(name).suffix in ('.py', '.sh', '.json')) or
        (name.startswith('test/after_recovery') and name.endswith('.test.mjs')) or
        name in ('test/matched_after_preflight.test.mjs', 'test/after_host_launch.test.mjs', 'test/after_recovery_fixture.py',
                 'training/cloud/runpod_bootstrap.py',
                 'training/cloud/prepare_after_host.sh'))]
    need({'training/after_recovery/bind.py', 'training/after_recovery/preflight.py', INPUTS} <= set(selected),
         'continuation implementation is absent from pinned source')
    return [committed_binding(repo, name, source_sha) for name in sorted(selected)]


def checked_recovery(directory):
    """Recheck every recovered payload, then derive receipt objects from the full unit ledger.

    The caller also checks committed plan/completion pins. Evaluation independently
    downloads these exact remote manifests and payloads before exports.
    """
    ledger = read(regular(directory, '_durable-recovery.json'))
    need(ledger.get('schema') == 'jovovich.durable-recovery.v1' and
         isinstance(ledger.get('units'), list) and ledger.get('units') and
         isinstance(ledger.get('revision'), str) and re.fullmatch(r'[0-9a-f]{40}', ledger['revision']),
         'invalid recovery ledger')
    seen = {}
    for sequence, unit in enumerate(ledger['units']):
        need(unit.get('sequence') == sequence and isinstance(unit.get('manifest_sha256'), str) and
             re.fullmatch(r'[0-9a-f]{64}', unit['manifest_sha256']) and
             isinstance(unit.get('files'), list) and unit['files'], 'invalid recovered unit')
        names = set()
        for entry in unit['files']:
            name = entry['name']
            need(name not in names, 'duplicate recovered payload')
            names.add(name)
            need(isinstance(entry.get('sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', entry['sha256']) and
                 type(entry.get('size')) is int and entry['size'] >= 0 and
                 entry.get('object') == ledger['prefix'] + '/objects/' + entry['sha256'],
                 'invalid recovered object binding')
            item = {'path': name, 'bytes': entry['size'], 'sha256': entry['sha256']}
            # Repeated logical names must carry identical bytes; recovery preserves
            # only the last materialization at that path.
            need(name not in seen or seen[name] == item, 'recovered logical file was overwritten')
            seen[name] = item
            check(regular(directory, name), item)
    return ledger


def recovered_receipt(ledger, unit_id):
    units = [unit for unit in ledger['units'] if unit['unit_id'] == unit_id]
    need(len(units) == 1, 'required recovery unit is missing or duplicated')
    return {'schema': 'jovovich.durable-receipt.v1', 'run_id': ledger['run_id'],
            'prefix': ledger['prefix'], 'revision': ledger['revision'], **units[0],
            'verified_remote_bytes': True, 'reused': True}


def save_new(path, value):
    clean_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def bind(recovered, output, source_sha, infrastructure_record, *, repo=ROOT, host_manifest=None):
    need(not sys.flags.optimize and not os.environ.get('PYTHONOPTIMIZE'), 'optimized Python is unsupported')
    repo = clean_path(repo)
    need(git(repo, 'rev-parse', 'HEAD').decode().strip() == source_sha,
         'checkout HEAD differs from requested source commit')
    recovered = repo / inside(repo, recovered)
    output = repo / inside(repo, output)
    need(recovered.is_dir() and not output.exists() and not output.is_symlink(), 'launch output must be new')
    need(not output.is_relative_to(recovered) and not recovered.is_relative_to(output),
         'launch and recovered evidence paths overlap')
    source = source_bindings(repo, source_sha)
    need(next(item for item in source if item['path'] == 'training/after_recovery/bind.py')['sha256'] ==
         digest(Path(__file__)), 'executing binder differs from pinned source')
    inputs_item = committed_binding(repo, INPUTS, source_sha)
    inputs = read(repo / INPUTS)
    validate_inputs(inputs)
    before_dir, failed_dir = recovered / 'before', recovered / 'failed-after'
    before_ledger, failed_ledger = (checked_recovery(path) for path in (before_dir, failed_dir))
    before, failed, changes = inspect_evidence(before_dir, failed_dir, inputs, repo)
    record_name = inside(repo, infrastructure_record)
    record_item = verify_record(repo, record_name, source_sha, changes)
    preflight_path = regular(recovered, 'preflight.json')
    preflight = read(preflight_path)
    need(preflight.get('schema') == 'jovovich.matched-after-preflight.v1' and
         preflight.get('status') == 'evidence-verified-admission-pending' and
         preflight.get('runnable') is False and preflight.get('inputs') == inputs and
         preflight.get('inputs_binding') == inputs_item and
         preflight.get('preflight_implementation_sha256') == digest(repo / 'training/after_recovery/preflight.py') and
         preflight.get('original_bindings') == failed['bindings'] and
         preflight.get('infrastructure_changes') == changes and
         preflight.get('frozen_evaluation_binding') == next(
             item for item in failed['bindings'] if item['path'] == failed['evaluation_plan']),
         'preflight report differs from recovered evidence or committed inputs')

    # Check every destination before creating anything. Numerical executables,
    # packed inputs and their frozen evaluation contract are copied, never rebuilt.
    restore = {}
    base_name = failed['argv'][1]
    for directory, plan in ((before_dir, before), (failed_dir, failed)):
        for item in plan['bindings']:
            name = item['path']
            if name == base_name:
                check(regular(repo, name), item)
            elif PurePosixPath(name).parts[0] in ('models', 'build'):
                if name in restore:
                    need(restore[name][1] == item, 'original artifact bindings disagree')
                else:
                    target = clean_path(repo / name)
                    need(not target.exists(), 'artifact destination already exists: ' + name)
                    restore[name] = (regular(directory, 'inputs/' + name), item)
            else:
                # All non-infrastructure source bytes were already compared to
                # original intent by inspect_evidence; commit-pin the repaired pair.
                check(regular(repo, name), next((c['candidate'] for c in changes if c['path'] == name), item))
    for name in ('_units/completion.ack.json', '_units/update-100.ack.json'):
        need(not clean_path(before_dir / name).exists(), 'reconstructed receipt already exists')
    completion = read(before_dir / 'completion.json')
    receipt_completion = recovered_receipt(before_ledger, 'completion')
    receipt_checkpoint = recovered_receipt(before_ledger, 'update-100')
    needed_snapshots = {'adapter.epoch100.' + part + '.' + ext for part in ('gate', 'up', 'down')
                        for ext in ('f32', 'lora')}
    needed_finals = {'adapter.' + part + '.' + ext for part in ('gate', 'up', 'down') for ext in ('f32', 'lora')}
    need(needed_snapshots <= {item['name'] for item in receipt_checkpoint['files']} and
         needed_finals | {'completion.json', 'stdout.jsonl', 'metrics.jsonl', 'stderr.log'} <=
         {item['name'] for item in receipt_completion['files']}, 'before endpoint artifacts are incomplete')
    extra = source + [record_item]
    for path in (preflight_path, before_dir / 'plan.json', failed_dir / 'plan.json',
                 before_dir / 'completion.json', before_dir / '_durable-recovery.json',
                 failed_dir / '_durable-recovery.json'):
        extra.append(binding(path, inside(repo, path)))
    host_item = None
    if host_manifest is not None:
        host_path = repo / inside(repo, host_manifest)
        host = read(regular(repo, inside(repo, host_path)))
        host_item = binding(host_path, inside(repo, host_path))
        need(host.get('source_commit') == source_sha, 'host manifest source pin differs')
        for path in (host_path, host_path.parent / 'launcher.sh'):
            extra.append(binding(regular(repo, inside(repo, path)), inside(repo, path)))
        launcher = next((item for item in source if item['path'] == 'training/after_recovery/host_launch.sh'), None)
        need(launcher is not None and digest(host_path.parent / 'launcher.sh') == launcher['sha256'],
             'host launcher copy differs from committed source')

    for name, (source_path, item) in restore.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with source_path.open('rb') as src, target.open('xb') as dst:
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        check(target, item)
        target.chmod(0o755 if PurePosixPath(name).parts[0] == 'build' else 0o644)
    save_new(before_dir / '_units/update-100.ack.json', receipt_checkpoint)
    save_new(before_dir / '_units/completion.ack.json', {
        **completion, 'status': 'completed', 'archive_status': 'verified',
        'remote_verification': receipt_completion})
    for name in ('_units/completion.ack.json', '_units/update-100.ack.json'):
        path = before_dir / name
        extra.append(binding(path, inside(repo, path)))
    # The record does not include its own hash. The launch binds its complete
    # bytes, and evaluation receives that exact file as --continuation-record.
    unique = {}
    originals = {item['path']: item for item in failed['bindings']}
    for item in extra:
        if item['path'] in originals:
            need(item == originals[item['path']], 'continuation addition changes original binding')
            continue
        need(item['path'] not in unique or unique[item['path']] == item, 'conflicting continuation binding')
        unique[item['path']] = item
    continuation = {
        'schema': SCHEMA, 'source_commit': source_sha,
        'original_source_commit': inputs['original_source_commit'], 'archive_revision': inputs['archive_revision'],
        'inputs': inputs_item, 'infrastructure_record': record_item, 'infrastructure_changes': changes,
        'host_manifest': host_item,
        'before_recovered': inside(repo, before_dir), 'failed_after_recovered': inside(repo, failed_dir),
        'preflight': binding(preflight_path, inside(repo, preflight_path)),
        'original_plans': {arm: binding(path / 'plan.json', inside(repo, path / 'plan.json'))
                           for arm, path in (('before', before_dir), ('failed_after', failed_dir))},
        'before_completion': binding(before_dir / 'completion.json', inside(repo, before_dir / 'completion.json')),
        'before_receipts': [receipt_completion, receipt_checkpoint],
        'new_after_run_id': inputs['new_after_run_id'], 'new_evaluation_run_id': inputs['new_evaluation_run_id'],
        'added_bindings': list(unique.values()), 'restored_artifacts': [item for _, item in restore.values()],
        'optimizer_initialization': 'fresh process at update zero; no checkpoint resume',
        'fixed_endpoint': 100, 'evaluation_plan': failed['evaluation_plan'],
    }
    output.mkdir(parents=True)
    save_new(output / 'binding.json', continuation)
    report_item = binding(output / 'binding.json', inside(repo, output / 'binding.json'))
    plan = copy.deepcopy(failed)
    candidate = {entry['path']: entry['candidate'] for entry in changes}
    plan.update(run_id=inputs['new_after_run_id'],
                bindings=[candidate.get(item['path'], item) for item in failed['bindings']] +
                         list(unique.values()) + [report_item],
                infrastructure_changes=changes,
                continuation={**continuation, 'binding_report': report_item},
                before_completion={
                    'run_id': inputs['before_run_id'], 'revision': inputs['archive_revision'],
                    'manifest_sha256': receipt_completion['manifest_sha256'],
                    'completion_sha256': inputs['before_completion_sha256']},
                expected_initial_lora_sha256=inputs['expected_initial_lora_sha256'])
    validate_plan(plan, repo)
    for item in extra:
        check(regular(repo, item['path']), item)
    verify_record(repo, record_name, source_sha, changes)
    save_new(output / 'after.launch.json', plan)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recovered', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--infrastructure-record', type=Path, required=True)
    parser.add_argument('--host-manifest', type=Path)
    args = parser.parse_args()
    try:
        plan = bind(args.recovered, args.out, args.source_sha, args.infrastructure_record,
                    host_manifest=args.host_manifest)
        print(json.dumps({'status': 'matched-after-bound', 'run_id': plan['run_id'],
                          'bindings': len(plan['bindings']), 'output': str(args.out / 'after.launch.json')}))
    except Exception as error:
        print('matched-after binding failed: ' + type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
