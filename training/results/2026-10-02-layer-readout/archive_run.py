#!/usr/bin/env python3
"""Pack a completed, remotely acknowledged layer run without weights or binaries."""
import argparse
from datetime import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import tarfile

HERE = Path(__file__).resolve().parent


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def fingerprint(path):
    before = path.stat()
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(data)
    after = path.stat()
    require((before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            'file changed while hashing')
    return {'bytes': after.st_size, 'sha256': h.hexdigest()}


def checked_path(root, name):
    relative = Path(name)
    require(not relative.is_absolute() and relative.parts and '..' not in relative.parts
            and str(relative) == name, 'invalid artifact name')
    path = root / relative
    require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root),
            'missing, nonregular, or escaping artifact: ' + name)
    return path


def verify(path, expected):
    require(fingerprint(path) == {k: expected[k] for k in ('bytes', 'sha256')},
            'artifact identity differs: ' + path.name)


def save_json(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True, type=Path)
    parser.add_argument('--remote-receipt', required=True, type=Path)
    args = parser.parse_args()
    root = args.run_dir.resolve()
    completion_path = checked_path(root, 'completion.json')
    completion = json.loads(completion_path.read_text())
    require(completion.get('status') == 'completed' and completion.get('failed_bindings') == [],
            'run has no successful final binding verification')
    plan_path = checked_path(root, 'plan.json')
    plan = json.loads(plan_path.read_text())
    require(completion['run_id'] == plan['run_id'], 'completion identity differs')
    require(len(plan['phases']) == 104, 'expected the frozen 104-phase survey')
    verify(HERE / 'launch-plan.json', fingerprint(plan_path))
    remote_payload = json.loads(args.remote_receipt.read_text())
    require({k: v for k, v in remote_payload.items() if k != 'remote_verification'} == completion,
            'launcher final receipt differs from local completion')
    remote = remote_payload['remote_verification']
    require(remote['schema'] == 'jovovich.durable-receipt.v1'
            and remote['verified_remote_bytes'] is True and remote['run_id'] == plan['run_id']
            and remote['unit_id'] == 'completion' and remote['sequence'] == 1 + 2 * len(plan['phases'])
            and remote['prefix'] == plan['remote']['prefix'] + '/' + plan['run_id']
            and re.fullmatch('[0-9a-f]{40}', remote['revision'])
            and re.fullmatch('[0-9a-f]{64}', remote['manifest_sha256']),
            'missing or mismatched remote completion acknowledgement')
    require(len(remote['files']) == 1 and remote['files'][0]['name'] == 'completion.json',
            'remote completion inventory differs')
    verify(completion_path, {'bytes': remote['files'][0]['size'], 'sha256': remote['files'][0]['sha256']})
    remote_binding = fingerprint(args.remote_receipt)
    expected = {'plan.json', 'completion.json'}
    for item in plan['bootstrap']:
        name = item['path']
        verify(checked_path(root, name), item)
        expected.add(name)
        if '/' not in name:
            verify(HERE / 'prepared' / name, item)
    phases = []
    for index, unit in enumerate(plan['phases']):
        stem = '_units/' + unit['id']
        intent_name, result_name = stem + '.intent.json', stem + '.result.json'
        intent = json.loads(checked_path(root, intent_name).read_text())
        result = json.loads(checked_path(root, result_name).read_text())
        require(intent['unit'] == unit and result['unit'] == unit
                and intent['sequence'] == 1 + 2 * index and result['sequence'] == 2 + 2 * index
                and result['status'] == 'completed' and result['return_code'] == 0,
                'phase identity, sequence or status differs: ' + unit['id'])
        commands = [unit['argv']] + ([unit['check_argv']] if unit.get('check_argv') else [])
        require([c['argv'] for c in result['commands']] == commands
                and all(c['return_code'] == 0 for c in result['commands']),
                'native or validator command failed: ' + unit['id'])
        artifacts = set(unit['outputs']) | {intent_name, unit.get('stdout', stem + '.stdout'),
                                            unit.get('stderr', stem + '.stderr')}
        if unit.get('check_argv'):
            artifacts.update({stem + '.check.stdout', stem + '.check.stderr'})
        require({a['path'] for a in result['artifacts']} == artifacts
                and len(result['artifacts']) == len(artifacts), 'phase artifact inventory differs')
        for artifact in result['artifacts']:
            verify(checked_path(root, artifact['path']), artifact)
        expected.update(artifacts | {result_name})
        phases.append({'id': unit['id'], 'status': result['status'],
                       'intent_sequence': intent['sequence'], 'result_sequence': result['sequence'],
                       'return_codes': [c['return_code'] for c in result['commands']],
                       'started_utc': result['started_utc'], 'finished_utc': result['finished_utc'],
                       'elapsed_seconds': (datetime.fromisoformat(result['finished_utc']) -
                                           datetime.fromisoformat(result['started_utc'])).total_seconds(),
                       'artifact_count': len(artifacts) + 1,
                       'result': {'path': result_name, **fingerprint(root / result_name)}})
    snapshots = [b for b in plan['bindings'] if b.get('snapshot')]
    snapshot_names = {b['snapshot'] for b in snapshots}
    require(len(snapshot_names) == len(snapshots)
            and all(Path(name).parts[0] == 'snapshot' for name in snapshot_names),
            'invalid bound snapshot inventory')
    actual_snapshots = {str(p.relative_to(root)) for p in (root / 'snapshot').rglob('*')
                        if not p.is_dir() or p.is_symlink()}
    require(actual_snapshots == snapshot_names, 'unplanned or missing excluded snapshot artifact')
    excluded_entries = []
    for item in snapshots:
        verify(checked_path(root, item['snapshot']), item)
        excluded_entries.append({'path': item['snapshot'], 'bytes': item['bytes'], 'sha256': item['sha256']})
    recovery = root / '_durable-recovery.json'
    if recovery.exists() or recovery.is_symlink():
        checked_path(root, recovery.name)
        excluded_entries.append({'path': recovery.name, **fingerprint(recovery)})
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()
              and p.relative_to(root).parts[0] not in ('snapshot', '_durable-recovery.json')}
    require(actual == expected, 'unplanned or missing public artifact inventory')
    entries = []
    for name in sorted(expected):
        path = checked_path(root, name)
        require(not name.endswith(('.gguf', '.lora', '.safetensors')) and Path(name).parts[0] != 'snapshot',
                'weight or source snapshot in public evidence')
        with path.open('rb') as stream:
            require(stream.read(4) not in (b'\x7fELF', b'GGUF'), 'executable or model payload in public evidence')
        entries.append({'path': name, **fingerprint(path)})
    products = ['raw-evidence.tar.gz', 'raw-evidence-manifest.json', 'layers-summary.json',
                'layers-table.tsv', 'process-summary.json', 'archive-receipt.json']
    require(all(not (HERE / name).exists() for name in products), 'public archive output already exists')
    partial = HERE / 'raw-evidence.tar.gz.part'
    require(not partial.exists(), 'partial archive already exists; inspect it before retry')
    with partial.open('xb') as raw:
        with gzip.GzipFile(filename='', mode='wb', compresslevel=9, fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.USTAR_FORMAT) as archive:
                for entry in entries:
                    info = tarfile.TarInfo(entry['path'])
                    info.size, info.mode = entry['bytes'], 0o644
                    info.mtime = info.uid = info.gid = 0
                    info.uname = info.gname = ''
                    with (root / entry['path']).open('rb') as stream:
                        archive.addfile(info, stream)
        raw.flush()
        os.fsync(raw.fileno())
    require(partial.stat().st_size <= 45 * 1024 * 1024,
            'archive exceeds 45 MiB; complete partial preserved for an explicit size decision')
    # Independent archive readback verifies every packed byte before publication.
    direct_payloads = {}
    with tarfile.open(partial, 'r:gz') as archive:
        members = archive.getmembers()
        require([m.name for m in members] == [e['path'] for e in entries], 'packed inventory differs')
        for member, entry in zip(members, entries):
            require(member.isfile() and member.size == entry['bytes'], 'packed extent differs')
            stream = archive.extractfile(member)
            h = hashlib.sha256()
            direct = member.name in ('layers-summary.json', 'layers-table.tsv')
            pieces = []
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                h.update(chunk)
                if direct:
                    pieces.append(chunk)
            require(h.hexdigest() == entry['sha256'], 'packed payload digest differs')
            if direct:
                direct_payloads[member.name] = b''.join(pieces)
            verify(root / entry['path'], entry)
    verify(args.remote_receipt, remote_binding)
    partial.rename(HERE / products[0])
    archive_binding = fingerprint(HERE / products[0])
    manifest = {'schema_version': 1, 'run_id': plan['run_id'], 'entries': entries,
                'entry_count': len(entries), 'uncompressed_bytes': sum(e['bytes'] for e in entries),
                'archive': {'path': products[0], **archive_binding},
                'source_remote_receipt': {'path': args.remote_receipt.name, **remote_binding},
                'remote_revision': remote['revision'], 'remote_manifest_sha256': remote['manifest_sha256'],
                'excluded': ['snapshot/**: bound source and compiled binaries remain in the private archive',
                             '_durable-recovery.json: local recovery bookkeeping, when present'],
                'excluded_verified_entries': sorted(excluded_entries, key=lambda e: e['path']),
                'packing': 'USTAR sorted regular files, mode 0644, uid/gid/mtime 0, empty owner names; gzip level 9, mtime 0, empty filename.'}
    save_json(HERE / products[1], manifest)
    for name in ('layers-summary.json', 'layers-table.tsv'):
        with (HERE / name).open('xb') as stream:
            stream.write(direct_payloads[name])
        verify(HERE / name, next(entry for entry in entries if entry['path'] == name))
    save_json(HERE / 'process-summary.json', {'schema_version': 1, 'run_id': plan['run_id'],
              'phase_count': len(phases), 'native_or_validator_command_count': sum(len(p['return_codes']) for p in phases),
              'phases': phases, 'remote_completion': remote})
    receipt = {'schema_version': 1, 'status': 'packed-and-byte-verified', 'run_id': plan['run_id'],
               'builder': {'path': Path(__file__).name, **fingerprint(Path(__file__))},
               'source_remote_receipt': {'path': args.remote_receipt.name, **remote_binding},
               'remote_verification_source': 'Launcher completion acknowledgement; this offline packer performs no remote calls.',
               'archive': {'path': products[0], **archive_binding}, 'entries_verified': len(entries),
               'manifest': {'path': products[1], **fingerprint(HERE / products[1])},
               'direct_copies': [{'path': name, **fingerprint(HERE / name)} for name in products[2:5]],
               'weights_and_executables_included': False}
    save_json(HERE / 'archive-receipt.json', receipt)
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
