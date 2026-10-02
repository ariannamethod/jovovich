#!/usr/bin/env python3
"""Actual private-HF durability smoke with a deliberately lost commit ACK."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / 'training'))
from durable_archive import ArchiveError, DurableArchive, HFTransport, HUB_VERSION

RUN_ID = 'durability-smoke-20261002-v1'
PREFIX = 'experiments/durable-layer-readout'
REMOTE = 'ataeff/jovovich'
HELPER = REPO / 'training/durable_archive.py'
PROTOCOL = HERE / 'live-smoke-protocol.json'
RECEIPT = HERE / 'live-smoke-receipt.json'
FROZEN_HELPER = '5e163cfe174bcd20b5f4c815027e1e8ce0e18c1659606048acee8928523b5a2a'
PAYLOAD = b'JOVOVICH durability smoke: closed synthetic bytes.\n' + bytes(range(256)) * 4


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def binding(path):
    data = path.read_bytes()
    return {'bytes': len(data), 'sha256': sha(data)}


def write(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temp.replace(path)


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def prepare():
    require(binding(HELPER)['sha256'] == FROZEN_HELPER, 'helper differs from frozen revision')
    value = {'schema': 'jovovich.live-durability-smoke.v1', 'created_at': now(),
             'repo_id': REMOTE, 'prefix': PREFIX, 'run_id': RUN_ID,
             'hub_client_version': HUB_VERSION,
             'sources': {'training/durable_archive.py': binding(HELPER),
                         'live_smoke.py': binding(Path(__file__))},
             'payload': {'bytes': len(PAYLOAD), 'sha256': sha(PAYLOAD)},
             'sequence': ['bootstrap source and protocol',
                          'closed synthetic payload; suppress successful commit ACK',
                          'identical retry, no second commit',
                          'delete owned local directory and recover remote-only',
                          'verified completion marker'],
             'gates': ['private repository on every transport operation',
                       'fresh downloaded bytes at pinned revisions',
                       'same retry returns reused=true with unchanged commit count',
                       'every recovered logical file matches original SHA256 and size',
                       'source/protocol hashes unchanged across run'],
             'scope': 'Synthetic archive/transport smoke. No model calls or weights.'}
    require(not PROTOCOL.exists(), 'protocol already exists; do not rewrite a frozen smoke')
    write(PROTOCOL, value)
    print(json.dumps({'prepared': True, 'protocol': binding(PROTOCOL)}))


def run(token_file):
    import huggingface_hub
    protocol = json.loads(PROTOCOL.read_text())
    before = {'training/durable_archive.py': binding(HELPER),
              'live_smoke.py': binding(Path(__file__)),
              'live-smoke-protocol.json': binding(PROTOCOL)}
    require(before['training/durable_archive.py']['sha256'] == FROZEN_HELPER,
            'helper differs from frozen revision')
    require(protocol['sources'] == {k: before[k] for k in protocol['sources']},
            'frozen source binding changed')
    require(huggingface_hub.__version__ == HUB_VERSION, 'hub client version changed')
    require(not RECEIPT.exists(), 'smoke already has a receipt; inspect before retrying')
    receipt = {'schema': 'jovovich.live-durability-smoke-result.v1',
               'started_at': now(), 'repo_id': REMOTE, 'prefix': PREFIX,
               'run_id': RUN_ID, 'hub_client_version': huggingface_hub.__version__,
               'source_bindings_before': before, 'events': [], 'status': 'running'}

    def event(kind, **fields):
        receipt['events'].append({'at': now(), 'kind': kind, **fields})
        write(RECEIPT, receipt)
        print(json.dumps({'event': kind, **fields}), flush=True)

    class ObservedTransport:
        def __init__(self, real):
            self.real, self.lose_ack, self.commits = real, False, []
        def head(self):
            return self.real.head()
        def inventory(self, revision, prefix):
            return self.real.inventory(revision, prefix)
        def download(self, path, revision, destination):
            return self.real.download(path, revision, destination)
        def commit(self, files, parent, message):
            revision = self.real.commit(files, parent, message)
            self.commits.append(revision)
            event('actual_commit_accepted', parent=parent, revision=revision,
                  operations=len(files))
            if self.lose_ack:
                self.lose_ack = False
                event('injected_ack_loss', revision=revision)
                raise ConnectionError('deliberate smoke acknowledgement loss')
            return revision

    try:
        token = Path(token_file).read_text().strip()
        transport = ObservedTransport(HFTransport(REMOTE, token))
        del token
        initial = transport.head()
        require(not transport.inventory(initial, PREFIX + '/' + RUN_ID),
                'fresh smoke run ID already has remote files')
        event('private_remote_checked', revision=initial)
        archive = DurableArchive(transport, RUN_ID, PREFIX)
        with tempfile.TemporaryDirectory(prefix='jovovich-live-smoke-') as temporary:
            owned = Path(temporary) / 'original'
            owned.mkdir()
            bootstrap = {
                'source/durable_archive.py': HELPER,
                'source/live_smoke.py': Path(__file__),
                'inputs/live-smoke-protocol.json': PROTOCOL,
            }
            local = {}
            expected = {}
            for logical, source in bootstrap.items():
                target = owned / logical
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                local[logical] = target
                expected[logical] = binding(target)
            first = archive.sync_unit('bootstrap', local, sequence=0)
            receipt['bootstrap'] = first
            event('bootstrap_verified', revision=first['revision'])
            payload_path = owned / 'data/closed-payload.bin'
            payload_path.parent.mkdir(parents=True)
            payload_path.write_bytes(PAYLOAD)
            expected['data/closed-payload.bin'] = binding(payload_path)
            transport.lose_ack = True
            count_before = len(transport.commits)
            interrupted = False
            try:
                archive.sync_unit('closed-payload', {'data/closed-payload.bin': payload_path},
                                  sequence=1)
            except ArchiveError:
                interrupted = True
                event('caller_observed_lost_ack')
            require(interrupted and len(transport.commits) == count_before + 1,
                    'expected exactly one accepted but unacknowledged commit')
            accepted = transport.commits[-1]
            retry = archive.sync_unit('closed-payload', {'data/closed-payload.bin': payload_path},
                                      sequence=1)
            require(retry['reused'] is True and len(transport.commits) == count_before + 1,
                    'retry duplicated an accepted unit')
            receipt['lost_ack_retry'] = retry
            event('identical_retry_verified', accepted_revision=accepted,
                  verified_revision=retry['revision'], additional_commits=0)
            del archive
            shutil.rmtree(owned)
            require(not owned.exists(), 'owned source directory survived deletion')
            event('owned_local_directory_deleted', logical_files=len(expected))
            resumed = DurableArchive(transport, RUN_ID, PREFIX)
            restored = Path(temporary) / 'recovered'
            recovery = resumed.recover(restored)
            require(recovery['next_sequence'] == 2, 'recovered wrong sequence')
            recovered = {name: binding(restored / name) for name in expected}
            require(recovered == expected, 'remote-only recovery bytes differ')
            receipt['recovery'] = recovery
            receipt['recovered_file_bindings'] = recovered
            event('remote_only_recovery_verified', revision=recovery['revision'],
                  logical_files=len(recovered))
            completion = {'schema': 'jovovich.live-durability-completion.v1',
                          'completed_at': now(), 'run_id': RUN_ID,
                          'lost_ack_commit': accepted,
                          'verified_recovery_revision': recovery['revision'],
                          'recovered_files': recovered,
                          'outcome': 'all smoke gates passed'}
            marker = restored / 'completion.json'
            write(marker, completion)
            last = resumed.sync_unit('completion', {'completion.json': marker}, sequence=2)
            receipt['completion'] = last
            event('completion_marker_verified', revision=last['revision'])
        after = {'training/durable_archive.py': binding(HELPER),
                 'live_smoke.py': binding(Path(__file__)),
                 'live-smoke-protocol.json': binding(PROTOCOL)}
        require(after == before, 'bound source or protocol changed during smoke')
        receipt['source_bindings_after'] = after
        receipt['remote_commits'] = transport.commits
        receipt['status'] = 'passed'
        receipt['finished_at'] = now()
        write(RECEIPT, receipt)
        print(json.dumps({'status': 'passed', 'commits': transport.commits,
                          'receipt': binding(RECEIPT)}), flush=True)
        return 0
    except Exception as error:
        # Never serialize SDK exception text, HTTP bodies, credentials or URLs.
        receipt['status'] = 'failed'
        receipt['finished_at'] = now()
        receipt['failure'] = {'exception_type': type(error).__name__,
                              'message': 'smoke stopped; inspect last completed event'}
        write(RECEIPT, receipt)
        print(json.dumps({'status': 'failed', 'exception_type': type(error).__name__}), flush=True)
        return 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['prepare', 'run'])
    parser.add_argument('--token-file')
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare()
        return 0
    require(args.token_file is not None, 'token file is required')
    return run(args.token_file)


if __name__ == '__main__':
    raise SystemExit(main())
