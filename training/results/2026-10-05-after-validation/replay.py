#!/usr/bin/env python3
"""Replay an archived failed boundary locally; no model calls or remote writes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import types


def need(value, message):
    if not value:
        raise ValueError(message)


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def regular(path):
    need(not any(p.is_symlink() for p in (path, *path.parents)) and path.is_file(), 'nonregular input')
    return path


def fingerprint(raw):
    return {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob_sha1': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def no_network(event, args):
    if event in ('socket.connect', 'socket.connect_ex', 'socket.getaddrinfo', 'socket.bind'):
        raise RuntimeError('network is disabled for the local replay')


class ImmutableTransport:
    """Versioned local snapshots. commit appends a new revision without rewriting old bytes."""
    def __init__(self, seed, root, revision, *, fingerprint_mode='dual', fault=None):
        self.root, self.current = root, revision
        self.root.mkdir()
        self.views = {revision: dict(seed)}
        self.fingerprint_mode, self.fault = fingerprint_mode, fault
        self.counts = {'head': 0, 'inventory': 0, 'download': 0, 'commit': 0}
        self.commits = 0
        self.injected = False
        self.metadata = {name: fingerprint(path.read_bytes()) for name, path in seed.items()}

    def head(self):
        self.counts['head'] += 1
        return self.current

    def inventory(self, revision, prefix):
        self.counts['inventory'] += 1
        view = self.views[revision]
        result = {}
        for name in view:
            if not name.startswith(prefix + '/'):
                continue
            info = dict(self.metadata[name])
            if self.fingerprint_mode == 'git-only':
                info.pop('sha256')
            elif self.fingerprint_mode == 'sha256-only':
                info.pop('git_blob_sha1')
            if self.fault == 'bad-object-inventory-size' and '/objects/' in name and not self.injected:
                info['size'] += 1
                self.injected = True
            result[name] = info
        return result

    def download(self, name, revision, destination):
        self.counts['download'] += 1
        source = self.views[revision][name]
        shutil.copyfile(source, destination)
        if self.fault == 'corrupt-object-download' and '/objects/' in name and not self.injected:
            with destination.open('ab') as stream:
                stream.write(b'corruption-control')
            self.injected = True

    def commit(self, files, parent, message):
        self.counts['commit'] += 1
        need(parent == self.current, 'local CAS parent mismatch')
        view = dict(self.views[parent])
        target = self.root / ('commit-%03d' % self.counts['commit'])
        target.mkdir()
        for index, (name, path) in enumerate(sorted(files.items())):
            need(name not in view, 'replay attempted to overwrite an immutable remote object')
            copied = target / str(index)
            shutil.copyfile(path, copied)
            view[name] = copied
            self.metadata[name] = fingerprint(copied.read_bytes())
        revision = hashlib.sha1((parent + '\n' + '\n'.join(
            name + ':' + self.metadata[name]['sha256'] for name in sorted(view))).encode()).hexdigest()
        need(revision not in self.views, 'duplicate synthetic revision')
        self.views[revision] = view
        self.current = revision
        self.commits += 1
        if self.fault == 'accepted-commit-lost-response' and not self.injected:
            self.injected = True
            raise TimeoutError('local accepted-commit response loss control')
        return revision


def check_recovery(module, directory):
    ledger = json.loads(regular(directory / '_durable-recovery.json').read_text())
    objects, payloads = {}, {}
    for unit in ledger['units']:
        for entry in unit['files']:
            module._name(entry['name'])
            path = regular(directory / entry['name'])
            actual = module._digest(path)
            need(actual == {key: entry[key] for key in ('size', 'sha256', 'git_blob_sha1')},
                 'recovered payload differs from ledger')
            need(entry['object'] == ledger['prefix'] + '/objects/' + actual['sha256'],
                 'recovery object path differs')
            if entry['object'] in objects:
                need(module._digest(objects[entry['object']]) == actual, 'object alias differs')
            objects[entry['object']] = path
            if entry['name'] in payloads:
                need(payloads[entry['name']] == entry, 'logical payload changed')
            payloads[entry['name']] = entry
    return ledger, objects, payloads


def replay(args):
    sys.addaudithook(no_network)
    need(not args.out.exists(), 'output already exists')
    args.out.mkdir(parents=True)
    env = {'PATH': os.environ.get('PATH', os.defpath), 'LANG': 'C', 'GIT_NO_LAZY_FETCH': '1',
           'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull}
    raw_source = subprocess.check_output(['git', '--no-replace-objects', '-c', 'core.fsmonitor=false',
        '-C', str(args.repo), 'show', args.source_sha + ':training/durable_archive.py'], env=env,
        stderr=subprocess.DEVNULL, timeout=30)
    source_path = args.out / 'deployed-durable-archive.py'
    source_path.write_bytes(raw_source)
    module = types.ModuleType('deployed_archive')
    module.__file__ = str(source_path)
    exec(compile(raw_source, str(source_path), 'exec'), module.__dict__)
    after, seed, after_payloads = check_recovery(module, args.after)
    failed, _, failure_payloads = check_recovery(module, args.failure)
    failure = json.loads((args.failure / 'failure.json').read_text())
    need(failed['run_id'] == after['run_id'] and after['next_sequence'] == 25 and
         [(u['sequence'], u['unit_id']) for u in after['units']] ==
         [(0, 'intent')] + [(i + 1, 'update-%03d' % i) for i in range(24)], 'unexpected incident sequence')
    need(failure['unit_id'] == 'update-024' and failure['sequence'] == 25 and
         failure['last_acknowledged_update'] == 23, 'incident boundary differs')
    need(failure['last_acknowledged_unit']['manifest_sha256'] == after['units'][-1]['manifest_sha256'],
         'last ACK manifest differs from recovered history')
    archived_source = after_payloads['inputs/training/durable_archive.py']
    need(fingerprint(raw_source) == {key: archived_source[key] for key in ('size', 'sha256', 'git_blob_sha1')},
         'Git source differs from archived deployed implementation')
    manifests = []
    previous = None
    for unit in after['units']:
        filename = '%06d-%s.json' % (unit['sequence'], unit['unit_id'])
        path = regular(args.manifests / filename)
        raw = path.read_bytes()
        manifest = json.loads(raw)
        need(raw == module._canonical(manifest) and hashlib.sha256(raw).hexdigest() == unit['manifest_sha256'],
             'exact remote manifest differs from recovery hash')
        need(manifest['schema'] == module.SCHEMA and manifest['run_id'] == after['run_id'] and
             {key: manifest[key] for key in ('sequence', 'unit_id', 'files')} ==
             {key: unit[key] for key in ('sequence', 'unit_id', 'files')} and
             manifest['previous_manifest'] == previous, 'exact remote manifest chain differs')
        module._revision(manifest['parent_revision'])
        previous = unit['manifest_sha256']
        seed[after['prefix'] + '/units/' + filename] = path
        manifests.append({'name': filename, **fingerprint(raw)})
    boundary = args.out / 'closed-update024'
    boundary.mkdir()
    files, derivation = {}, []
    for suffix, failed_log in (('raw.jsonl', 'stdout.jsonl'), ('metrics.jsonl', 'metrics.jsonl'),
                               ('stderr', 'stderr.log')):
        prior = b''.join((args.after / ('_units/update-%03d.%s' % (index, suffix))).read_bytes()
                         for index in range(24))
        whole = (args.failure / failed_log).read_bytes()
        need(whole.startswith(prior), 'failure log is not the exact archived prefix plus boundary24')
        tail = whole[len(prior):]
        name = '_units/update-024.' + suffix
        target = boundary / Path(name).name
        target.write_bytes(tail)
        files[name] = target
        derivation.append({'name': name, **fingerprint(tail), 'failure_log': failed_log,
                           'verified_prefix_bytes': len(prior), 'source_log': failure_payloads[failed_log]})
    raw_rows = [json.loads(line) for line in files['_units/update-024.raw.jsonl'].read_bytes().splitlines()]
    metric_rows = [json.loads(line) for line in files['_units/update-024.metrics.jsonl'].read_bytes().splitlines()]
    need(len(raw_rows) == 2 and len(metric_rows) == 1 and raw_rows[0] == metric_rows[0] and
         metric_rows[0]['stage'] == 'decision_train' and metric_rows[0]['update'] == 24 and
         raw_rows[1] == {'stage': 'archive_ready', 'update': 24, 'snapshot_saved': False},
         'boundary records differ from step24')
    need(files['_units/update-024.stderr'].stat().st_size == 0, 'unexpected boundary stderr')

    cases = [('cold-direct-dual', False, False, 'dual', None),
             ('warm-direct-dual', True, False, 'dual', None),
             ('cold-retry-dual', False, True, 'dual', None),
             ('warm-retry-dual', True, True, 'dual', None),
             ('warm-retry-git-only', True, True, 'git-only', None),
             ('warm-retry-sha256-only', True, True, 'sha256-only', None),
             ('accepted-commit-response-loss', True, True, 'dual', 'accepted-commit-lost-response'),
             ('inventory-integrity-control', False, True, 'dual', 'bad-object-inventory-size'),
             ('download-integrity-control', False, True, 'dual', 'corrupt-object-download')]
    results = []
    last_revision = failure['last_acknowledged_unit']['revision']
    for name, warm, retry, mode, fault in cases:
        transport = ImmutableTransport(seed, args.out / name, last_revision, fingerprint_mode=mode, fault=fault)
        archive = module.DurableArchive(transport, after['run_id'], after['prefix'].rsplit('/', 1)[0])
        if warm:
            with tempfile.TemporaryDirectory(prefix='archive-replay-prime-') as temp:
                history, _ = archive._history(last_revision, Path(temp))
                archive._known = {i: item[1] for i, item in enumerate(history)}
            need(len(archive._known) == 25, 'warm cache priming incomplete')
        baseline_counts = dict(transport.counts)
        initial_source = {key: module._digest(path) for key, path in files.items()}
        retry_events = []
        started = time.monotonic()
        row = {'case': name, 'warm_cache': warm, 'retry_wrapper': retry,
               'inventory_fingerprints': mode, 'injected_fault': fault}
        try:
            if retry:
                receipt = module.sync_unit_with_retry(archive, 'update-024', files, sequence=25,
                    deadline=time.monotonic() + 120, max_attempts=4, on_retry=retry_events.append,
                    sleep=lambda _: None)
            else:
                receipt = archive.sync_unit('update-024', files, sequence=25)
            need(receipt['sequence'] == 25 and receipt['unit_id'] == 'update-024' and
                 receipt['verified_remote_bytes'] is True, 'wrong replay receipt')
            expected_files = [dict(name=key, **module._digest(path),
                                  object=after['prefix'] + '/objects/' + module._digest(path)['sha256'])
                              for key, path in sorted(files.items())]
            need(receipt['files'] == expected_files, 'replay altered the closed unit bytes')
            row.update(status='passed', reused=receipt['reused'],
                       manifest_sha256=receipt['manifest_sha256'], receipt=receipt)
        except module.ArchiveError as error:
            row.update(status='failed', exception_type=type(error).__name__,
                       message=str(error), diagnostic=error.diagnostic)
        row.update(elapsed_seconds=round(time.monotonic() - started, 6), retry_events=retry_events,
                   local_commits=transport.commits,
                   transport_calls={key: transport.counts[key] - baseline_counts[key] for key in baseline_counts},
                   source_bytes_unchanged=initial_source == {key: module._digest(path) for key, path in files.items()})
        results.append(row)
        save(args.out / (name + '.json'), row)
    positive = [row for row in results if row['injected_fault'] in (None, 'accepted-commit-lost-response')]
    negative = [row for row in results if row not in positive]
    record = {'schema': 'jovovich.archive-local-replay.v1',
              'source_commit': args.source_sha, 'source': fingerprint(raw_source),
              'source_matches_archived_intent': True,
              'original_remote_chain': 'exact downloaded manifest bytes; no synthetic historical manifests',
              'replay_commits': 'synthetic local revisions only', 'network_requests': 0,
              'remote_writes': 0, 'training_calls': 0,
              'recovery_revision': after['revision'], 'seed_head_revision': last_revision,
              'recovered_units': len(after['units']), 'recovered_payloads': len(after_payloads),
              'failure_payloads': len(failure_payloads), 'unit24_files': derivation,
              'verified_manifests': manifests, 'incident_failure': failure,
              'cases': results,
              'summary': {'positive_cases': len(positive),
                          'positive_passes': sum(row['status'] == 'passed' for row in positive),
                          'integrity_controls': len(negative),
                          'integrity_controls_rejected': sum(row['status'] == 'failed' for row in negative),
                          'all_source_bytes_preserved': all(row['source_bytes_unchanged'] for row in results),
                          'validation_failure_reproduced_without_injected_fault':
                              any(row['status'] == 'failed' for row in positive if row['injected_fault'] is None)},
              'observed_scope': ['Historical manifests and payloads are exact recovered bytes.',
                                 'Boundary24 files are exact suffixes of verified failure logs.',
                                 'Filesystem inode/mtime and private-service responses from the incident are unavailable.',
                                 'Inventory fingerprints are computed from recovered bytes in dual, Git-only and SHA256-only modes.']}
    save(args.out / 'report.json', record)
    concise = {'schema': 'jovovich.archive-local-replay-summary.v1',
               'source_commit': args.source_sha, 'deployed_archive_sha256': record['source']['sha256'],
               'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'training_run_id': after['run_id'], 'recovery_revision': after['revision'],
               'seed_head_revision': last_revision, 'historical_manifests': 'exact remote bytes',
               'recovered_units': 25, 'recovered_payloads': len(after_payloads),
               'unit_id': 'update-024', 'sequence': 25,
               'closed_unit_derivation': 'Exact suffixes after byte-matched archived update000..023 log prefixes.',
               'closed_unit_files': [{key: item[key] for key in ('name', 'size', 'sha256')}
                                     for item in derivation],
               'result': record['summary'],
               'cases': [{key: row[key] for key in ('case', 'status', 'local_commits', 'injected_fault')}
                         for row in results],
               'network_requests': 0, 'remote_writes': 0, 'training_calls': 0,
               'unrecorded_incident_state': ['Filesystem inode/mtime and local file mutations during the failed call.',
                                           'Private-service responses and metadata returned during the failed call.'],
               'complete_report': 'report.json'}
    save(args.out / 'summary.json', concise)
    print(json.dumps(record['summary'], sort_keys=True))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', type=Path, required=True)
    p.add_argument('--after', type=Path, required=True)
    p.add_argument('--failure', type=Path, required=True)
    p.add_argument('--manifests', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--source-sha', default='970163b792d24dba1b5d2d3077177baf9cd1e28b')
    replay(p.parse_args())


if __name__ == '__main__':
    main()
