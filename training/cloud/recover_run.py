#!/usr/bin/env python3
"""Copy only incident evidence from a stopped attempt, with per-file archive ACKs."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys

STATE_FILES = ('state.json', 'exit.json', 'child.log')
JOB_FILES = ('after.stderr', 'after.stdout', 'exit-status.txt', 'host-manifest.json')
AFTER_FILES = ('failure.json', 'stderr.log', 'stdout.jsonl', 'metrics.jsonl', 'plan.json')
MAX_BYTES = 16 * 1024 * 1024
SAFE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z')
ACK = re.compile(r'(?:intent|completion|update-[0-9]{3})\.ack\.json\Z')


def need(value, message):
    if not value:
        raise RuntimeError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def safe_path(path):
    """Reject links in every component, including a missing leaf's parents."""
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        need(not part.is_symlink(), 'incident source/destination must not traverse symlinks')
    return path


def regular_snapshot(path):
    path = safe_path(path)
    before = path.stat()
    need(stat.S_ISREG(before.st_mode), 'incident source must be a regular file')
    need(before.st_size <= MAX_BYTES, 'incident source exceeds size limit')
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    after = path.stat()
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    need(len(raw) == before.st_size and all(getattr(before, k) == getattr(after, k) for k in fields),
         'incident source changed during snapshot')
    return raw, {'bytes': len(raw), 'sha256': sha(raw), 'mtime_ns': before.st_mtime_ns}


def sanitize(raw, secrets):
    for secret in secrets:
        if secret:
            raw = raw.replace(secret.encode(), b'[REDACTED]')
    return re.sub(rb'\b(?:hf_|rpa_)[A-Za-z0-9_-]{8,}\b', b'[REDACTED]', raw)


def layout(repo, state_dir, run_prefix, output, run_id):
    need(SAFE.fullmatch(run_prefix) and SAFE.fullmatch(run_id), 'invalid incident identifier')
    need(run_id != run_prefix and run_id.startswith(run_prefix + '-incident'), 'incident run ID must be unique to this incident')
    repo, state_dir, output = map(safe_path, (repo, state_dir, output))
    need(repo.is_dir(), 'original repository is missing')
    need(state_dir == repo.parent / (run_prefix + '-host'), 'unexpected original watchdog directory')
    roots = {'state': state_dir, 'job': repo / 'models' / (run_prefix + '-job'),
             'after': repo / 'models' / (run_prefix + '-after'),
             'before': repo / 'models' / (run_prefix + '-before')}
    need(not output.exists() and all(not output.is_relative_to(root) for root in roots.values()),
         'incident output must be new and outside original evidence directories')
    for root in roots.values():
        safe_path(root)
    return repo, roots, output


def recover(archive, *, repo, state_dir, run_prefix, output, run_id, source_file=None, secrets=()):
    repo, roots, output = layout(repo, state_dir, run_prefix, output, run_id)
    output.mkdir(parents=True, mode=0o700)
    sequence = 0

    def sync(unit, files):
        nonlocal sequence
        receipt = archive.sync_unit(unit, files, sequence=sequence)
        need(receipt.get('verified_remote_bytes') is True and receipt.get('run_id') == run_id and
             receipt.get('unit_id') == unit, 'incident archive did not acknowledge the closed unit')
        save(output / '_receipts' / (unit + '.json'), receipt)
        sequence += 1
        print(json.dumps({'incident_unit': unit, 'archive_status': 'verified'}), flush=True)
        return receipt

    storage = shutil.disk_usage(repo)
    intent = {'schema': 'jovovich.incident-recovery.v1', 'run_id': run_id, 'original_run_prefix': run_prefix,
              'started_utc': now(), 'read_only_original': True,
              'host': {'uname': list(os.uname()), 'filesystem_bytes': dict(total=storage.total, used=storage.used, free=storage.free)},
              'roots': {k: {'path': str(v), 'exists': v.exists(),
                           'is_directory': v.is_dir(),
                           'mtime_ns': v.stat().st_mtime_ns if v.exists() else None}
                        for k, v in roots.items()},
              'policy': 'Allowlisted text evidence only; no old credential, environment or model-weight files.'}
    save(output / 'intent.json', intent)
    bootstrap = {'intent.json': output / 'intent.json'}
    for name, path in [('recover_run.py', source_file or Path(__file__)), ('durable_archive.py', repo / 'training/durable_archive.py')]:
        raw, _ = regular_snapshot(path)
        dest = output / name; dest.write_bytes(raw); bootstrap[name] = dest
    sync('intent', bootstrap)
    requests = [(group, name) for group, names in [('state', STATE_FILES), ('job', JOB_FILES), ('after', AFTER_FILES),
                ('before', ('completion.json', '_units/completion.ack.json'))] for name in names]
    units_dir = safe_path(roots['after'] / '_units')
    if units_dir.exists():
        need(units_dir.is_dir(), 'after receipt directory is invalid')
        requests += [('after', '_units/' + name) for name in sorted(os.listdir(units_dir)) if ACK.fullmatch(name)]
    inventory, parsed = [], {}
    for index, (group, name) in enumerate(requests):
        source = roots[group] / name
        record = {'group': group, 'name': name, 'status': 'missing'}
        files = {}
        try:
            safe_path(source)
            if source.exists():
                raw, info = regular_snapshot(source)
                copied = sanitize(raw, secrets)
                dest = output / group / name; dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(copied)
                record.update(info, status='copied', redacted=copied != raw, copied_sha256=sha(copied))
                files[str(dest.relative_to(output))] = dest
                if name.endswith('.json'):
                    try:
                        parsed[(group, name)] = json.loads(copied)
                    except (ValueError, UnicodeError):
                        record['json_parse_status'] = 'invalid_or_partial'
        except (OSError, RuntimeError):
            # Missing/unsafe/partial evidence never causes a broader file search.
            record['status'] = 'unavailable_or_unsafe'
        record_path = output / 'inventory' / f'{index:03d}.json'
        save(record_path, record); files[str(record_path.relative_to(output))] = record_path
        sync(f'evidence-{index:03d}', files)
        inventory.append(record)
    watchdog = parsed.get(('state', 'exit.json'), parsed.get(('state', 'state.json'), {}))
    failure = parsed.get(('after', 'failure.json'), {})
    if not isinstance(watchdog, dict):
        watchdog = {}
    if not isinstance(failure, dict):
        failure = {}
    diagnostic = {'status': 'evidence_collected', 'run_id': run_id, 'finished_utc': now(),
                  'files_copied': sum(r['status'] == 'copied' for r in inventory),
                  'files_missing_or_unavailable': sum(r['status'] != 'copied' for r in inventory),
                  'after_failure_record_present': isinstance(parsed.get(('after', 'failure.json')), dict),
                  'watchdog_exit_record_present': isinstance(parsed.get(('state', 'exit.json')), dict),
                  'cause': 'Undetermined; inspect the archived evidence. No training resume was attempted.'}
    for source, key, target in [(watchdog, 'phase', 'watchdog_phase'), (failure, 'error_type', 'training_error_type')]:
        if isinstance(source.get(key), str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', source[key]):
            diagnostic[target] = source[key]
    for source, key, target in [(watchdog, 'child_exit_code', 'watchdog_child_exit_code'), (failure, 'return_code', 'trainer_return_code')]:
        if type(source.get(key)) is int:
            diagnostic[target] = source[key]
    acknowledged = [int(name[14:17]) for (group, name), value in parsed.items()
                    if group == 'after' and re.fullmatch(r'_units/update-[0-9]{3}\.ack\.json', name) and
                    isinstance(value, dict) and value.get('verified_remote_bytes') is True]
    diagnostic['latest_local_verified_update_ack'] = max(acknowledged, default=None)
    save(output / 'diagnosis.json', diagnostic)
    receipt = sync('completion', {'diagnosis.json': output / 'diagnosis.json'})
    result = dict(diagnostic, archive_status='verified', remote_verification=receipt)
    save(output / 'completion.ack.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('repo', 'state-dir', 'run-prefix', 'run-id', 'output', 'token-file'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try:
        repo, roots, _ = layout(args.repo, args.state_dir, args.run_prefix, args.output, args.run_id)
        module = safe_path(repo / 'training/durable_archive.py')
        spec = importlib.util.spec_from_file_location('incident_durable_archive', module)
        archive_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(archive_module)
        # Only this newly supplied parent credential is read; original credentials are never consulted.
        credential = safe_path(args.token_file)
        need(not credential.is_relative_to(repo) and
             all(not credential.is_relative_to(root) for root in roots.values()),
             'supply a new parent credential outside the original evidence')
        token = credential.read_text().strip()
        archive = archive_module.DurableArchive(archive_module.HFTransport('ataeff/jovovich', token),
                                                args.run_id, prefix='experiments/explanation-order')
        result = recover(archive, repo=repo, state_dir=args.state_dir, run_prefix=args.run_prefix,
                         output=args.output, run_id=args.run_id, secrets=(token,))
        print(json.dumps(result), flush=True)
        return 0
    except Exception as error:
        print('incident recovery stopped (' + type(error).__name__ + '); retain its new output directory', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
