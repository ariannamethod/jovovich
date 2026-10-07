#!/usr/bin/env python3
"""Replay closed archived bytes against private HF, without any model work."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'training'))
from durable_archive import (ArchiveError, DurableArchive, HFTransport,
                             _digest, sync_unit_with_retry)


def need(value, message):
    if not value:
        raise ValueError(message)


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def read(path):
    return json.loads(path.read_text())


def checked_recovery(directory):
    ledger = read(directory / '_durable-recovery.json')
    need(ledger['verified_remote_bytes'] is True and
         ledger['revision'] == '11f6c33b277f24459147bf6a9314205be1c334de' and
         ledger['run_id'] == 'order-rp-20261004-02-after', 'unexpected recovery')
    for unit in ledger['units']:
        for entry in unit['files']:
            path = directory / entry['name']
            need(path.is_file() and not path.is_symlink() and
                 _digest(path) == {k: entry[k] for k in ('size', 'sha256', 'git_blob_sha1')},
                 'recovered payload changed')
    return ledger


class TracedTransport:
    """Record bounded operation metadata; never record exceptions or credentials."""
    def __init__(self, actual):
        self.actual, self.events, self.last_inventory = actual, [], None

    def call(self, operation, *args):
        row = {'operation': operation}
        if operation in ('inventory', 'download'):
            row['revision'] = args[0] if operation == 'inventory' else args[1]
        if operation == 'commit':
            row.update(parent=args[1], files=len(args[0]))
        start = time.monotonic()
        try:
            result = getattr(self.actual, operation)(*args)
            if operation in ('head', 'commit'):
                row['revision'] = result
            if operation == 'inventory':
                self.last_inventory = {'revision': args[0], 'prefix': args[1], 'files': result}
                row.update(files=len(result), inventory_sha256=hashlib.sha256(
                    json.dumps(result, sort_keys=True).encode()).hexdigest())
            row['status'] = 'returned'
            return result
        except ArchiveError as error:
            row.update(status='failed', diagnostic=error.diagnostic)
            raise
        finally:
            row['seconds'] = round(time.monotonic() - start, 6)
            self.events.append(row)

    def head(self): return self.call('head')
    def inventory(self, *args): return self.call('inventory', *args)
    def download(self, *args): return self.call('download', *args)
    def commit(self, *args): return self.call('commit', *args)


def run(args):
    need(not args.out.exists(), 'use a fresh output directory')
    after = checked_recovery(args.after)
    failure = checked_recovery(args.failure)
    need(after['next_sequence'] == 25 and failure['next_sequence'] == 1,
         'unexpected incident boundary')
    need(after['prefix'] == 'experiments/explanation-order/order-rp-20261004-02-after' and
         failure['prefix'] == 'experiments/explanation-order/failures/order-rp-20261004-02-after',
         'unexpected recovery prefixes')
    need([(u['sequence'], u['unit_id']) for u in after['units']] ==
         [(0, 'intent')] + [(i + 1, 'update-%03d' % i) for i in range(24)],
         'unexpected source sequence')
    args.out.mkdir(parents=True)
    boundary = {}
    expected = {f['name']: f for f in read(Path(__file__).parent.parent /
        '2026-10-05-after-validation/replay-summary.json')['closed_unit_files']}
    for suffix, failed_name in (('raw.jsonl', 'stdout.jsonl'),
                                ('metrics.jsonl', 'metrics.jsonl'), ('stderr', 'stderr.log')):
        prior = b''.join((args.after / ('_units/update-%03d.%s' % (i, suffix))).read_bytes()
                         for i in range(24))
        whole = (args.failure / failed_name).read_bytes()
        need(whole.startswith(prior), 'failure log differs from archived prefix')
        target = args.out / ('update-024.' + suffix)
        target.write_bytes(whole[len(prior):])
        name = '_units/' + target.name
        need({k: _digest(target)[k] for k in ('size', 'sha256')} ==
             {k: expected[name][k] for k in ('size', 'sha256')}, 'boundary24 bytes differ')
        boundary[name] = target
    protocol = {
        'schema': 'jovovich.live-archive-rehearsal.v1', 'training_calls': 0,
        'utc': datetime.now(timezone.utc).isoformat(),
        'run_id': args.run_id, 'repo': 'ataeff/jovovich', 'private': True,
        'prefix': 'experiments/archive-rehearsal',
        'source_recovery_revision': after['revision'],
        'archive_source': _digest(ROOT / 'training/durable_archive.py'),
        'script': _digest(Path(__file__)),
        'units': 103, 'per_unit_budget_seconds': 120, 'max_attempts': 4,
        'schedule': 'intent and exact update000..024 payloads; then 77 repetitions of the closed update024 bytes under unique rehearsal names',
        'scope': 'Live transport and closed-unit validation. Repeated payloads are archive load, never optimizer updates.',
        'evidence': 'Each unit carries the previous receipt and bounded transport trace. Final report and remote recovery follow.'}
    save(args.out / 'protocol.json', protocol)
    transport = TracedTransport(HFTransport(protocol['repo'], args.token_file.read_text().strip()))
    head = transport.head()
    need(not transport.inventory(head, protocol['prefix'] + '/' + args.run_id), 'remote attempt already exists')
    archive = DurableArchive(transport, args.run_id, protocol['prefix'])
    receipts, failure_record = [], None
    for sequence in range(protocol['units']):
        if sequence < 25:
            unit = after['units'][sequence]
            files = {entry['name']: args.after / entry['name'] for entry in unit['files']}
            unit_id = unit['unit_id']
        elif sequence == 25:
            files, unit_id = dict(boundary), 'update-024'
        else:
            files = {'_rehearsal/repetition-%03d/%s' % (sequence, Path(name).name): path
                     for name, path in boundary.items()}
            unit_id = 'repetition-%03d' % sequence
        if sequence == 0:
            files.update({'_rehearsal/protocol.json': args.out / 'protocol.json',
                          '_rehearsal/rehearse.py': Path(__file__),
                          '_rehearsal/durable_archive.py': ROOT / 'training/durable_archive.py'})
        else:
            trace = args.out / ('receipt-%03d.json' % (sequence - 1))
            files['_rehearsal/' + trace.name] = trace
        start, first_event, retries = time.monotonic(), len(transport.events), []
        try:
            receipt = sync_unit_with_retry(archive, unit_id, files, sequence=sequence,
                deadline=start + 120, max_attempts=4, on_retry=retries.append)
            row = {'receipt': receipt, 'seconds': round(time.monotonic() - start, 6),
                   'operations': transport.events[first_event:], 'retries': retries}
            save(args.out / ('receipt-%03d.json' % sequence), row)
            receipts.append(row)
            print(json.dumps({'ack': sequence, 'unit': unit_id, 'seconds': row['seconds'],
                              'revision': receipt['revision']}), flush=True)
        except ArchiveError as error:
            failure_record = {'sequence': sequence, 'unit_id': unit_id,
                'diagnostic': error.diagnostic, 'operations': transport.events[first_event:],
                'retries': retries, 'last_inventory': transport.last_inventory}
            break
    report = {'schema': 'jovovich.live-archive-rehearsal-result.v1', 'protocol': protocol,
              'acknowledged_units': len(receipts), 'failure': failure_record,
              'last_receipt': receipts[-1]['receipt'] if receipts else None,
              'unit_seconds': [r['seconds'] for r in receipts],
              'retry_events': sum(len(r['retries']) for r in receipts),
              'status': 'failed' if failure_record else 'passed'}
    save(args.out / 'report.json', report)
    evidence = {p.name: p for p in args.out.iterdir() if p.is_file()}
    report_archive = DurableArchive(transport, args.run_id, protocol['prefix'] + '/reports')
    receipt = sync_unit_with_retry(report_archive, 'report', evidence, sequence=0,
                                  deadline=time.monotonic() + 600, max_attempts=4)
    save(args.out / 'report-receipt.json', receipt)
    if not failure_record:
        recovered = DurableArchive(transport, args.run_id, protocol['prefix']).recover(
            args.out / 'remote-recovery', revision=report['last_receipt']['revision'])
        save(args.out / 'remote-recovery-summary.json', {k: recovered[k] for k in
            ('run_id', 'revision', 'next_sequence', 'verified_remote_bytes')})
    print(json.dumps({'status': report['status'], 'acknowledged_units': len(receipts),
                      'failure_diagnostic': failure_record['diagnostic'] if failure_record else None,
                      'report_revision': receipt['revision']}), flush=True)
    return 1 if failure_record else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('after', 'failure', 'out', 'token-file'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--run-id', required=True)
    try:
        sys.exit(run(parser.parse_args()))
    except ArchiveError as error:
        print(json.dumps({'archive_failure': error.diagnostic}), flush=True)
        sys.exit(2)
