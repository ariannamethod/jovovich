#!/usr/bin/env python3
"""Evaluate authenticated saved endpoints under an explicit evaluation-only repair."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'training'))
from explanations import execute_evaluation as original
from after_recovery.bind import (checked_recovery, committed_binding, git,
                                 recovered_receipt)
from after_recovery.preflight import regular
from after_recovery.evaluate import execute as execute_evaluation
from durable_archive import ArchiveError, DurableArchive, HFTransport

REPAIRS = frozenset(('training/explanations/execute_evaluation.py',
                     'training/explanations/collect_generation.py', 'training/layers/run_layers.py'))
ADDITIONS = ('training/file_integrity.py', 'training/after_recovery/evaluate_saved.py',
             'training/explanations/prepare_semantic_packet.py', 'src/infer.c', 'Makefile')
HISTORICAL_ADDITIONS = frozenset(('src/infer.c', 'Makefile'))
SCHEMA = 'jovovich.saved-evaluation-admission.v1'


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def item(path, name):
    return {'path': name, 'bytes': path.stat().st_size, 'sha256': digest(path)}


def checked(path, expected):
    need(path.is_file() and not path.is_symlink() and
         path.stat().st_size == expected['bytes'] and digest(path) == expected['sha256'],
         'saved evaluation bound bytes differ: ' + expected['path'])


def relative(root, path):
    path = Path(path).absolute()
    need(path.is_relative_to(root) and '..' not in path.parts and not any(p.is_symlink() for p in (path, *path.parents)),
         'saved evaluation path escapes checkout or uses symlink')
    return str(path.relative_to(root))


def prepare(recovered, record_path, output, source_sha, *, repo=ROOT):
    """Restore only authenticated bootstrap inputs; preserve historical source bindings."""
    need(not sys.flags.optimize and not os.environ.get('PYTHONOPTIMIZE'), 'optimized Python is unsupported')
    repo = Path(repo).absolute()
    record_name = relative(repo, record_path)
    record_binding = committed_binding(repo, record_name, source_sha)
    need(git(repo, 'rev-parse', 'HEAD').decode().strip() == source_sha,
         'evaluation checkout HEAD differs from source pin')
    record = read(record_path)
    need(set(record) == {'schema', 'parent_run_id', 'parent_archive_revision', 'parent_plan_sha256',
                         'training_source_commit', 'evaluation_run_id', 'source_changes'} and
         record['schema'] == SCHEMA, 'invalid saved evaluation admission record')
    for name in ('parent_archive_revision', 'training_source_commit'):
        need(re.fullmatch(r'[0-9a-f]{40}', record[name]) is not None, 'invalid saved evaluation source pin')
    need(re.fullmatch(r'[0-9a-f]{64}', record['parent_plan_sha256']) is not None,
         'invalid parent plan checksum')
    for name in ('parent_run_id', 'evaluation_run_id'):
        need(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,49}', record[name]) is not None,
             'invalid saved evaluation run ID')
    need(record['parent_run_id'] != record['evaluation_run_id'], 'evaluation needs a fresh run ID')
    recovered = repo / relative(repo, recovered)
    output = repo / relative(repo, output)
    need(not output.exists() and output != recovered and not output.is_relative_to(recovered) and
         not recovered.is_relative_to(output), 'evaluation output must be new and separate')
    ledger = checked_recovery(recovered)
    need(ledger.get('verified_remote_bytes') is True and
         ledger['revision'] == record['parent_archive_revision'] and
         ledger['run_id'] == record['parent_run_id'] and
         ledger['prefix'] == 'experiments/explanation-order/' + record['parent_run_id'],
         'saved evaluation recovery identity differs')
    parent_path = regular(recovered, 'plan.json')
    need(digest(parent_path) == record['parent_plan_sha256'], 'saved evaluation parent plan changed')
    parent = read(parent_path)
    need(parent['run_id'] == record['parent_run_id'] and
         parent['continuation']['source_commit'] == record['training_source_commit'],
         'historical evaluation/training source identity differs')
    bootstrap = recovered_receipt(ledger, 'bootstrap')
    need(bootstrap['sequence'] == 0, 'parent bootstrap must be first')
    archived = {entry['name']: entry for entry in bootstrap['files']}
    need(len(archived) == len(bootstrap['files']) and
         archived.get('plan.json', {}).get('sha256') == record['parent_plan_sha256'],
         'parent plan was not authenticated at bootstrap')
    bound = {value['path']: value for value in parent['bindings']}
    need(len(bound) == len(parent['bindings']), 'duplicate historical evaluation binding')
    changes = {value['path']: value for value in record['source_changes']}
    need(len(changes) == len(record['source_changes']) and set(changes) <= REPAIRS,
         'evaluation source repair exceeds allowed helpers')
    need('training/explanations/execute_evaluation.py' in changes,
         'saved evaluation requires the explicit evaluator repair')
    replacements, restore, new_bindings = {}, [], {}
    for name, expected in bound.items():
        # Validate path grammar even for the separately supplied large public base.
        target = repo / name
        need(relative(repo, target) == name, 'noncanonical historical binding path')
        if name == 'models/base-qwen.gguf':
            checked(regular(repo, name), expected)
        else:
            source = regular(recovered, 'inputs/' + name)
            remote = archived.get('inputs/' + name, {})
            need((remote.get('size'), remote.get('sha256')) == (expected['bytes'], expected['sha256']),
                 'historical input was not bound in evaluation bootstrap')
            checked(source, expected)
            if name in changes:
                change = changes[name]
                need(set(change) == {'path', 'original', 'candidate'} and change['original'] == expected and
                     change['candidate'] != expected, 'invalid evaluation source hash pair')
                raw = git(repo, 'cat-file', 'blob', record['training_source_commit'] + ':' + name)
                need(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'],
                     'historical evaluator source differs from deployed training commit')
                candidate = committed_binding(repo, name, source_sha)
                need(change['candidate'] == candidate, 'evaluation repair differs from committed source')
                replacements[name] = candidate
                old_name = relative(repo, source)
                new_bindings[old_name] = item(source, old_name)
            elif target.exists():
                checked(regular(repo, name), expected)
            else:
                need(Path(name).parts[0] in ('models', 'build'),
                     'committed evaluation input is absent from checkout')
                restore.append((source, target, expected))
        new_bindings[name] = replacements.get(name, expected)
    need(set(replacements) == set(changes), 'repair helper is absent from historical bindings')
    for name in ADDITIONS:
        need(name not in bound, 'new evaluator dependency collides with historical binding')
        new_bindings[name] = committed_binding(repo, name, source_sha)
        if name in HISTORICAL_ADDITIONS:
            raw = git(repo, 'cat-file', 'blob', record['training_source_commit'] + ':' + name)
            need(len(raw) == new_bindings[name]['bytes'] and
                 hashlib.sha256(raw).hexdigest() == new_bindings[name]['sha256'],
                 'newly bound numerical/build source differs from historical training commit')
    new_bindings[record_name] = record_binding
    for path in (parent_path, recovered / '_durable-recovery.json'):
        name = relative(repo, path)
        need(name not in new_bindings, 'saved evidence binding collision')
        new_bindings[name] = item(path, name)

    old_before = Path(parent['training']['before']['directory'])
    before_name = parent['continuation']['before_recovered']
    old_root = old_before
    for unused in Path(before_name).parts:
        old_root = old_root.parent
    need(old_root.is_absolute() and old_root / before_name == old_before,
         'cannot resolve historical checkout root')
    training = copy.deepcopy(parent['training'])
    for arm in ('before', 'after'):
        old_dir = Path(training[arm]['directory'])
        need(old_dir.is_relative_to(old_root), 'historical training directory escapes checkout')
        name = str(old_dir.relative_to(old_root))
        need(name + '/plan.json' in bound and name + '/completion.json' in bound and
             name + '/_units/update-100.ack.json' in bound and
             name + '/_units/completion.ack.json' in bound, 'saved training endpoint is incomplete')
        completion = read(regular(recovered, 'inputs/' + name + '/completion.json'))
        launch = read(regular(recovered, 'inputs/' + name + '/plan.json'))
        need(completion['return_code'] == 0 and completion['acknowledged_updates'] == 100 and
             completion['plan_sha256'] == bound[name + '/plan.json']['sha256'] and
             completion['bindings'] == launch['bindings'] and
             launch['run_id'] == training[arm]['run_id'], 'saved training completion differs')
        training[arm]['directory'] = str(repo / name)
    contract = parent['contract']
    need(contract.get('schema') == 'jovovich.explanation-order.evaluation.v1' and
         len(parent['training_receipts']) == 4 and
         len(contract['collector_jobs']) == 6 and sum(job['rows'] for job in contract['collector_jobs']) == 228 and
         [row['index'] for row in contract['parity']['rows']] == [0, 1, 2, 3, 51],
         'historical evaluation contract differs')
    for arm in ('before', 'after'):
        receipts = [r for r in parent['training_receipts'] if r['run_id'] == training[arm]['run_id']]
        need(len(receipts) == 2 and {r['unit_id'] for r in receipts} == {'completion', 'update-100'},
             'saved training endpoint receipts differ')
    parameters = dict(parent['parameters'], BEFORE_RUN=training['before']['directory'],
                      AFTER_RUN=training['after']['directory'], EVALUATION_RUN=str(output),
                      EVALUATION_RUN_ID=record['evaluation_run_id'])
    exports = [original.export_unit(step, parameters, output)
               for arm in contract['exports'] for step in arm['steps']]
    need(len(exports) == 8, 'saved endpoint export count differs')
    # All admission checks precede materialization; no native process is launched.
    for source, target, expected in restore:
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open('rb') as src, target.open('xb') as dst:
            shutil.copyfileobj(src, dst)
            dst.flush(); os.fsync(dst.fileno())
        checked(target, expected)
        if Path(expected['path']).parts[0] == 'build':
            target.chmod(0o755)
    return dict(parent, run_id=record['evaluation_run_id'], training=training, parameters=parameters,
                export_phases=exports, bindings=list(new_bindings.values()),
                saved_evaluation={'schema': SCHEMA, 'training_source_commit': record['training_source_commit'],
                    'evaluation_source_commit': source_sha, 'parent_plan': item(parent_path, relative(repo, parent_path)),
                    'parent_bootstrap_receipt': bootstrap, 'admission_record': record_binding,
                    'source_changes': record['source_changes']})


def execute(archive, prepared, output):
    # This fresh remote read authenticates the parent admission and all bootstrap
    # payloads before the new run archives intent or invokes any native command.
    with tempfile.TemporaryDirectory(prefix='saved-evaluation-parent-') as tmp:
        original.verify_training_receipts(archive,
            [prepared['saved_evaluation']['parent_bootstrap_receipt']], Path(tmp))
    return execute_evaluation(archive, prepared, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('preflight', 'run'))
    for name in ('recovered', 'record', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--token-file', type=Path)
    args = parser.parse_args()
    try:
        prepared = prepare(args.recovered, args.record, args.output, args.source_sha)
        if args.mode == 'preflight':
            print(json.dumps({'status': 'preflight_passed', 'run_id': prepared['run_id'],
                              'training_updates': 0, 'generation_calls': 228}))
            return
        need(args.token_file is not None, 'archive token file is required')
        transport = HFTransport('ataeff/jovovich', args.token_file.read_text().strip())
        archive = DurableArchive(transport, prepared['run_id'], 'experiments/explanation-order')
        need(not transport.inventory(transport.head(), archive.prefix), 'evaluation remote run already exists')
        print(json.dumps(execute(archive, prepared, args.output)))
    except Exception as error:
        diagnostic = {'status': 'stopped', 'error_type': type(error).__name__}
        if isinstance(error, ArchiveError):
            diagnostic['archive_error'] = error.diagnostic
        print(json.dumps(diagnostic), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
