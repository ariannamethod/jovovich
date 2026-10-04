#!/usr/bin/env python3
"""Copy only incident evidence from a stopped attempt, with per-file archive ACKs."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import subprocess
import types

STATE_FILES = ('state.json', 'exit.json', 'child.log')
JOB_FILES = ('after.stderr', 'after.stdout', 'exit-status.txt', 'host-manifest.json')
AFTER_FILES = ('failure.json', 'stderr.log', 'stdout.jsonl', 'metrics.jsonl', 'plan.json')
MAX_BYTES = 16 * 1024 * 1024
SAFE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z')
HEX40 = re.compile(r'[0-9a-f]{40}\Z')
HEX64 = re.compile(r'[0-9a-f]{64}\Z')
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


def git_bytes(repo, *args):
    result = subprocess.run(['git', '--no-replace-objects', '-C', str(safe_path(repo)), *args],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
                            env={'PATH': os.environ.get('PATH', os.defpath), 'LANG': 'C',
                                 'GIT_NO_LAZY_FETCH': '1', 'GIT_TERMINAL_PROMPT': '0',
                                 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull})
    need(result.returncode == 0, 'source revision is unavailable')
    return result.stdout


def bind_sources(repo, source_repo, source_revision, host_source):
    """Use Git objects offline; the recovery source and retained engine are distinct."""
    need(isinstance(source_revision, str) and HEX40.fullmatch(source_revision), 'invalid recovery revision')
    need(git_bytes(source_repo, 'rev-parse', source_revision + '^{commit}').decode().strip() == source_revision,
         'recovery source must name an exact commit')
    retained_revision = git_bytes(repo, 'rev-parse', 'HEAD^{commit}').decode().strip()
    need(HEX40.fullmatch(retained_revision), 'invalid retained source revision')
    bindings, sources = {}, {}
    for name, path, git_repo, revision, logical in [
            ('recover_run.py', Path(__file__), source_repo, source_revision, 'training/cloud/recover_run.py'),
            ('recover_host.sh', host_source, source_repo, source_revision, 'training/cloud/recover_host.sh'),
            ('durable_archive.py', repo / 'training/durable_archive.py', repo, retained_revision, 'training/durable_archive.py')]:
        raw, info = regular_snapshot(path)
        need(raw == git_bytes(git_repo, 'show', revision + ':' + logical), 'executed source differs from pinned Git object')
        sources[name] = raw
        bindings[name] = dict(revision=revision, path=logical, bytes=info['bytes'], sha256=info['sha256'])
    return bindings, sources


def valid_entries(entries, prefix):
    if not isinstance(entries, list) or not entries:
        return False
    names = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'name', 'size', 'sha256', 'git_blob_sha1', 'object'}:
            return False
        name = entry['name']
        if (not isinstance(name, str) or len(name) > 512 or
                not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', name) or
                any(part in ('.', '..') for part in name.split('/')) or
                type(entry['size']) is not int or entry['size'] < 0 or
                not isinstance(entry['sha256'], str) or not HEX64.fullmatch(entry['sha256']) or
                not isinstance(entry['git_blob_sha1'], str) or not HEX40.fullmatch(entry['git_blob_sha1']) or
                entry['object'] != prefix + '/objects/' + entry['sha256']):
            return False
        names.append(name)
    return names == sorted(set(names)) and not any(b.startswith(a + '/') for a, b in zip(names, names[1:]))


def receipt_candidate(name, receipt, plan, run_prefix):
    """Local validation only. A structurally valid receipt remains a local claim."""
    match = re.fullmatch(r'_units/update-([0-9]{3})\.ack\.json', name)
    if not match or not isinstance(receipt, dict) or not isinstance(plan, dict):
        return False
    update = int(match[1]); run_id = run_prefix + '-after'
    try:
        steps = plan['argv'][4]
        if not isinstance(steps, str) or not steps.isdecimal() or not 0 <= update <= int(steps) <= 999:
            return False
        remote = plan['remote']; prefix = remote['prefix'] + '/' + run_id
        return (plan.get('schema_version') == 1 and plan.get('run_id') == run_id and plan.get('arm') == 'after' and
                remote == {'private': True, 'repo': 'ataeff/jovovich', 'prefix': 'experiments/explanation-order'} and
                set(receipt) == {'schema', 'run_id', 'prefix', 'revision', 'sequence', 'unit_id', 'manifest_sha256',
                                 'files', 'verified_remote_bytes', 'reused'} and
                receipt['schema'] == 'jovovich.durable-receipt.v1' and receipt['run_id'] == run_id and
                receipt['prefix'] == prefix and receipt['unit_id'] == 'update-' + match[1] and
                type(receipt['sequence']) is int and receipt['sequence'] == update + 1 and
                isinstance(receipt['revision'], str) and bool(HEX40.fullmatch(receipt['revision'])) and
                isinstance(receipt['manifest_sha256'], str) and bool(HEX64.fullmatch(receipt['manifest_sha256'])) and
                receipt['verified_remote_bytes'] is True and type(receipt['reused']) is bool and
                valid_entries(receipt['files'], prefix))
    except (KeyError, TypeError, IndexError):
        return False


def verify_ack_manifest(transport, receipt, plan_raw, directory):
    """Fresh pinned manifest-chain and plan checks; never downloads weight objects."""
    directory.mkdir()
    revision, prefix = receipt['revision'], receipt['prefix']
    inventory = transport.inventory(revision, prefix)
    need(isinstance(inventory, dict), 'invalid remote inventory')
    total = 0

    def download(path, destination, limit):
        nonlocal total
        meta = inventory.get(path, {})
        need(type(meta.get('size')) is int and 0 <= meta['size'] <= limit, 'remote evidence exceeds bound')
        total += meta['size']
        need(total <= MAX_BYTES, 'remote receipt evidence exceeds total bound')
        transport.download(path, revision, destination)
        raw, _ = regular_snapshot(destination)
        need(len(raw) == meta['size'], 'remote evidence size mismatch')
        return raw

    previous = None
    for sequence in range(receipt['sequence'] + 1):
        unit_id = 'intent' if sequence == 0 else f'update-{sequence - 1:03d}'
        filename = f'{sequence:06d}-{unit_id}.json'
        raw = download(prefix + '/units/' + filename, directory / filename, 1000000)
        manifest = json.loads(raw)
        canonical = (json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False) + '\n').encode()
        need(raw == canonical and isinstance(manifest, dict) and set(manifest) ==
             {'schema', 'run_id', 'sequence', 'unit_id', 'previous_manifest', 'parent_revision', 'files'},
             'invalid remote manifest')
        need(manifest['schema'] == 'jovovich.durable-unit.v1' and manifest['run_id'] == receipt['run_id'] and
             type(manifest['sequence']) is int and manifest['sequence'] == sequence and manifest['unit_id'] == unit_id and
             manifest['previous_manifest'] == previous and isinstance(manifest['parent_revision'], str) and
             HEX40.fullmatch(manifest['parent_revision']) and valid_entries(manifest['files'], prefix),
             'remote manifest binding mismatch')
        previous = sha(raw)
        if sequence == 0:
            entries = [entry for entry in manifest['files'] if entry['name'] == 'plan.json']
            need(len(entries) == 1, 'remote intent has no unique plan')
            entry = entries[0]
            need(entry['size'] == len(plan_raw) and entry['sha256'] == sha(plan_raw) and
                 entry['git_blob_sha1'] == hashlib.sha1(b'blob ' + str(len(plan_raw)).encode() + b'\0' + plan_raw).hexdigest(),
                 'receipt archive belongs to a different training plan')
            need(download(entry['object'], directory / 'plan.json', len(plan_raw)) == plan_raw,
                 'remote training plan differs from local incident plan')
    need(previous == receipt['manifest_sha256'] and manifest['files'] == receipt['files'],
         'local receipt differs from remote manifest')
    return {'status': 'manifest_and_plan_verified', 'revision': revision,
            'manifest_sha256': previous, 'update': receipt['sequence'] - 1,
            'scope': 'Fresh manifest chain and exact plan bytes; payload verification is the original local receipt claim.'}


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


def recover(archive, *, repo, state_dir, run_prefix, output, run_id, source_repo, source_revision, host_source,
            secrets=(), receipt_transport=None, _source_bundle=None):
    repo, roots, output = layout(repo, state_dir, run_prefix, output, run_id)
    source_bindings, source_bytes = (_source_bundle if _source_bundle is not None else
                                     bind_sources(repo, source_repo, source_revision, host_source))
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
              'started_utc': now(), 'read_only_original': True, 'source_bindings': source_bindings,
              'host': {'uname': list(os.uname()), 'filesystem_bytes': dict(total=storage.total, used=storage.used, free=storage.free)},
              'roots': {k: {'path': str(v), 'exists': v.exists(),
                           'is_directory': v.is_dir(),
                           'mtime_ns': v.stat().st_mtime_ns if v.exists() else None}
                        for k, v in roots.items()},
              'policy': 'Allowlisted text evidence only; no old credential, environment or model-weight files.'}
    save(output / 'intent.json', intent)
    bootstrap = {'intent.json': output / 'intent.json'}
    for name, raw in source_bytes.items():
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
    plan = parsed.get(('after', 'plan.json'))
    receipts = [(name, value) for (group, name), value in parsed.items()
                if group == 'after' and re.fullmatch(r'_units/update-[0-9]{3}\.ack\.json', name)]
    candidates = [value for name, value in receipts if receipt_candidate(name, value, plan, run_prefix)]
    diagnostic['local_update_receipts_rejected'] = len(receipts) - len(candidates)
    diagnostic['latest_manifest_bound_local_update_ack'] = None
    verification = {'status': 'no_valid_local_receipt' if not candidates else 'not_requested'}
    if candidates and receipt_transport is not None:
        candidate = max(candidates, key=lambda value: value['sequence'])
        try:
            verification = verify_ack_manifest(receipt_transport, candidate, (output / 'after/plan.json').read_bytes(),
                                               output / 'receipt-verification')
            diagnostic['latest_manifest_bound_local_update_ack'] = verification['update']
        except Exception as error:
            verification = {'status': 'failed', 'error_type': type(error).__name__
                            if re.fullmatch(r'[A-Za-z0-9_]{1,80}', type(error).__name__) else 'Exception'}
    diagnostic['receipt_verification'] = verification
    save(output / 'diagnosis.json', diagnostic)
    closed = {'diagnosis.json': output / 'diagnosis.json'}
    if verification['status'] == 'manifest_and_plan_verified':
        for path in sorted((output / 'receipt-verification').iterdir()):
            closed[str(path.relative_to(output))] = path
    receipt = sync('completion', closed)
    result = dict(diagnostic, archive_status='verified', remote_verification=receipt)
    save(output / 'completion.ack.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('repo', 'state-dir', 'run-prefix', 'run-id', 'output', 'token-file', 'source-repo', 'source-revision', 'host-source'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try:
        repo, roots, _ = layout(args.repo, args.state_dir, args.run_prefix, args.output, args.run_id)
        source_bundle = bind_sources(repo, args.source_repo, args.source_revision, args.host_source)
        _, sources = source_bundle
        module = repo / 'training/durable_archive.py'
        archive_module = types.ModuleType('incident_durable_archive')
        archive_module.__file__ = str(module)
        exec(compile(sources['durable_archive.py'], str(module), 'exec'), archive_module.__dict__)
        # Only this newly supplied parent credential is read; original credentials are never consulted.
        credential = safe_path(args.token_file)
        need(not credential.is_relative_to(repo) and
             all(not credential.is_relative_to(root) for root in roots.values()),
             'supply a new parent credential outside the original evidence')
        token = credential.read_text().strip()
        transport = archive_module.HFTransport('ataeff/jovovich', token)
        archive = archive_module.DurableArchive(transport,
                                                args.run_id, prefix='experiments/explanation-order')
        result = recover(archive, repo=repo, state_dir=args.state_dir, run_prefix=args.run_prefix,
                         output=args.output, run_id=args.run_id, secrets=(token,), receipt_transport=transport,
                         source_repo=args.source_repo, source_revision=args.source_revision, host_source=args.host_source,
                         _source_bundle=source_bundle)
        print(json.dumps(result), flush=True)
        return 0
    except Exception as error:
        print('incident recovery stopped (' + type(error).__name__ + '); retain its new output directory', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
