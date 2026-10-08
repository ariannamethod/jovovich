#!/usr/bin/env python3
"""Independent archive condition reproductions. No credentials/network/model work."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    source = repo / 'training/durable_archive.py'
    fixture = repo / 'test/durable_archive_fixture.py'
    spec = importlib.util.spec_from_file_location('audit_fixture', fixture)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    archive_module = module.archive_module

    def forbid_network(event, unused):
        if event in ('socket.connect', 'socket.connect_ex', 'socket.getaddrinfo', 'socket.bind'):
            raise RuntimeError('This audit is offline')
    sys.addaudithook(forbid_network)

    with tempfile.TemporaryDirectory(prefix='jovovich-independent-audit-') as directory:
        payload = Path(directory) / 'closed.bin'
        payload.write_bytes(b'immutable bytes')
        remote = module.FakeTransport()
        archive = module.DurableArchive(remote, 'audit-stale-head')
        receipts = []
        for sequence in range(25):
            receipts.append(archive.sync_unit('unit-%03d' % sequence,
                {'units/%03d.bin' % sequence: payload}, sequence=sequence))
        current = remote.current
        previous = receipts[-2]['revision']
        remote.head = lambda: previous
        retries = []
        diagnostic = None
        try:
            archive_module.sync_unit_with_retry(archive, 'unit-025',
                {'units/025.bin': payload}, sequence=25,
                deadline=time.monotonic() + 120, on_retry=retries.append)
        except module.ArchiveError as error:
            diagnostic = error.diagnostic
        if diagnostic is None:
            raise RuntimeError('Expected shorter-history rejection did not happen')
        before_restore = remote.commits
        remote.head = lambda: current
        resumed = archive.sync_unit('unit-025', {'units/025.bin': payload}, sequence=25)
        first = {'case': 'head_returns_preceding_valid_commit',
                 'injected_condition': True, 'acknowledged_before': 25,
                 'diagnostic': diagnostic, 'retry_events': len(retries),
                 'commits_at_failure': before_restore,
                 'same_pending_unit_succeeds_after_head_restored': resumed['verified_remote_bytes'],
                 'commits_after_restore': remote.commits}

    import huggingface_hub as hub
    from huggingface_hub.hf_api import RepoFile
    from huggingface_hub.errors import EntryNotFoundError

    class PartialApi:
        def list_repo_tree(self, **unused):
            yield RepoFile(path='audit/prefix/objects/' + 'a' * 64, size=3, oid='b' * 40)
            raise EntryNotFoundError('synthetic later page unavailable')

    transport = object.__new__(archive_module.HFTransport)
    transport._hub, transport._api = hub, PartialApi()
    transport.repo_id, transport._private = 'audit/private', lambda revision: revision
    result = transport.inventory('a' * 40, 'audit/prefix')
    second = {'case': 'later_listing_entry_not_found', 'injected_condition': True,
              'yielded_files_before_failure': 1, 'returned_inventory': result,
              'error_propagated': False}
    print(json.dumps({'schema': 'jovovich.independent-archive-condition-audit.v1',
        'archive_source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'fixture_sha256': hashlib.sha256(fixture.read_bytes()).hexdigest(),
        'hub_version': hub.__version__, 'network_calls': 0, 'training_calls': 0,
        'repository_edits': 0, 'cases': [first, second],
        'incident_attribution': 'These are injected conditions. The original incident cause remains unestablished.'},
        sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
