import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

const fixture = String.raw`
import hashlib, json, sys, tempfile, time
from pathlib import Path
from unittest.mock import patch
sys.path[:0] = ['training', 'test']
from after_recovery import evaluate as runner
from durable_archive import ArchiveError, DurableArchive
from durable_archive_fixture import FakeTransport, HTTPError

scenario = sys.argv[1]
def need(value, message):
    if not value:
        raise AssertionError(message)

class ObservedArchive(DurableArchive):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.attempts = []
    def sync_unit(self, unit_id, files, *, sequence):
        self.attempts.append((sequence, unit_id, {name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                                                for name, path in files.items()}))
        return super().sync_unit(unit_id, files, sequence=sequence)

class ObservedTransport(FakeTransport):
    def __init__(self):
        super().__init__()
        self.head_calls = 0
    def head(self):
        self.head_calls += 1
        return super().head()

budgets = []
real_sync = runner.sync_unit_with_retry
def observed_sync(*args, **kwargs):
    remaining = kwargs['deadline'] - time.monotonic()
    need(899 <= remaining <= 900, 'evaluation unit must use the 900-second acknowledgement budget')
    need(kwargs['max_attempts'] == 4, 'evaluation retry count differs from the reviewed four attempts')
    budgets.append((remaining, kwargs['max_attempts']))
    return real_sync(*args, **kwargs)

def transient(_):
    raise HTTPError(503)
def lost_reply(_):
    raise ConnectionResetError(104, 'hf_SYNTHETIC_AFTER_RETRY_SECRET lost response')

def verify(archive, remote, local, receipt, directory, *, unit='generation-000', sequence=0):
    need(receipt['verified_remote_bytes'] and receipt['unit_id'] == unit and receipt['sequence'] == sequence,
         'receipt does not identify the closed unit')
    need(receipt['files'][0]['sha256'] == hashlib.sha256(local.read_bytes()).hexdigest(), 'receipt bytes differ')
    ledger = DurableArchive(remote, archive.run_id, 'experiments/test-evaluation').recover(directory / 'recovered')
    need(ledger['next_sequence'] == 1 and ledger['units'][0]['unit_id'] == unit, 'retry duplicated an archived unit')
    need((directory / 'recovered' / 'response.jsonl').read_bytes() == local.read_bytes(), 'remote recovery differs')
    need(archive._pending is None and archive._operation_deadline is None, 'retry left a pending gate or deadline')

with tempfile.TemporaryDirectory(prefix='jovovich-after-retry-') as temporary:
    directory = Path(temporary)
    local = directory / 'response.jsonl'; local.write_bytes(b'{"review":"closed response"}\n')
    remote = ObservedTransport()
    archive = ObservedArchive(remote, 'retry-evaluation', 'experiments/test-evaluation')
    wrapped = runner.RetryingArchive(archive)
    need(wrapped.transport is remote and wrapped.run_id == archive.run_id and wrapped.prefix == archive.prefix,
         'retry wrapper did not preserve archive identity')
    with patch.object(runner, 'sync_unit_with_retry', observed_sync):
        if scenario in ('transient-upload', 'accepted-lost-ack', 'transient-readback'):
            if scenario == 'transient-upload':
                remote.before_commit = transient
            elif scenario == 'accepted-lost-ack':
                remote.after_commit = lost_reply
            else:
                def once(path, data):
                    remote.download_fault = None
                    raise TimeoutError('hf_SYNTHETIC_AFTER_RETRY_SECRET readback')
                remote.download_fault = once
            receipt = wrapped.sync_unit('generation-000', {'response.jsonl': local}, sequence=0)
            need(len(archive.attempts) == 2 and archive.attempts[0] == archive.attempts[1],
                 'whole-unit retry changed unit ID, sequence, logical paths or payload bytes')
            need(remote.commits == 1, 'transient retry duplicated an accepted commit')
            need(receipt['reused'] is (scenario != 'transient-upload'), 'accepted remote unit was not reused')
            verify(archive, remote, local, receipt, directory)
        elif scenario in ('permanent-http', 'corrupt-readback', 'four-attempts', 'changed-closed-input'):
            if scenario == 'permanent-http':
                remote.head_fault = HTTPError(401)
            elif scenario == 'corrupt-readback':
                remote.download_fault = lambda path, data: data + b'corrupt'
            elif scenario == 'four-attempts':
                remote.head_fault = HTTPError(503)
            else:
                def changed(files):
                    local.write_bytes(b'different response after failed upload')
                    raise HTTPError(503)
                remote.before_commit = changed
            try:
                wrapped.sync_unit('generation-000', {'response.jsonl': local}, sequence=0)
            except ArchiveError as error:
                diagnostic = error.diagnostic
                need('SYNTHETIC' not in str(error) + json.dumps(diagnostic), 'error leaked transport contents')
                if scenario == 'four-attempts':
                    need(diagnostic['attempts'] == 4 and len(archive.attempts) == 4 and remote.head_calls == 4,
                         'retry wrapper did not stop at four attempts')
                    need(all(item == archive.attempts[0] for item in archive.attempts), 'exhausted retry changed closed unit')
                else:
                    need(not diagnostic['retryable'] and len(archive.attempts) == 1,
                         'permanent failure or changed closed input reached another archive attempt')
                    need(diagnostic['attempts'] == (2 if scenario == 'changed-closed-input' else 1),
                         'failure reported the wrong retry boundary')
                    if scenario == 'permanent-http':
                        need(remote.head_calls == 1 and diagnostic['http_status'] == 401, 'permanent HTTP error was retried')
                    else:
                        need(diagnostic['operation'] == 'validation', 'byte mismatch lost its integrity classification')
            else:
                raise AssertionError('archive failure was accepted')
            need(remote.commits == (1 if scenario == 'corrupt-readback' else 0), 'failure added unexpected commits')
            need(archive._operation_deadline is None, 'failed retry leaked its deadline into later calls')
        elif scenario in ('execute-collector', 'execute-collector-permanent'):
            prepared = {'fixture': 'forwarded unchanged'}
            output = directory / 'evaluation'
            collector_calls = []
            children = []
            def collector(journal, **kwargs):
                # This is the generation/archive boundary. One closed response is
                # produced once; the real archive retries its synchronization.
                need(isinstance(journal, runner.RetryingArchive), 'collector child lacks the retry wrapper')
                need(kwargs == {'output': output, 'marker': 'unchanged'}, 'collector arguments changed')
                collector_calls.append(journal)
                return journal.sync_unit('generation-000', {'response.jsonl': local}, sequence=0)
            def delegate(parent, supplied, target, *, collector):
                # Replace only the existing orchestration boundary: its contract,
                # native commands and coverage are tested by explanation_execution.
                # The archives, byte verification and retries remain real here.
                need(isinstance(parent, runner.RetryingArchive) and parent.archive is archive,
                     'outer evaluation archive lacks the retry wrapper')
                need(supplied is prepared and target is output, 'execute wrapper changed invocation arguments')
                remote.before_commit = transient
                parent.sync_unit('bootstrap', {'response.jsonl': local}, sequence=0)
                child = ObservedArchive(parent.transport, 'child-generation', 'experiments/test-evaluation')
                children.append(child)
                if scenario == 'execute-collector-permanent':
                    remote.head_fault = HTTPError(403)
                else:
                    remote.after_commit = lost_reply
                receipt = collector(child, output=output, marker='unchanged')
                complete = directory / 'completion.json'; complete.write_text('{"status":"complete"}\n')
                parent.sync_unit('completion', {'completion.json': complete}, sequence=1)
                return receipt
            with patch.object(runner.original, 'execute', delegate):
                try:
                    receipt = runner.execute(archive, prepared, output, collector=collector)
                except ArchiveError as error:
                    need(scenario == 'execute-collector-permanent' and error.diagnostic['http_status'] == 403 and
                         error.diagnostic['attempts'] == 1, 'collector failure did not propagate intact')
                    need(remote.commits == 1 and len(children[0].attempts) == 1,
                         'permanent collector failure retried or allowed parent completion')
                else:
                    need(scenario == 'execute-collector' and receipt['verified_remote_bytes'] and receipt['reused'],
                         'collector accepted commit was not recovered')
                    need(remote.commits == 3, 'outer or collector retry duplicated a committed unit')
                    need(len(children[0].attempts) == 2 and children[0].attempts[0] == children[0].attempts[1],
                         'collector retry changed its closed response')
                    ledger = DurableArchive(remote, archive.run_id, 'experiments/test-evaluation').recover(directory / 'outer-recovery')
                    need([(unit['sequence'], unit['unit_id']) for unit in ledger['units']] == [(0, 'bootstrap'), (1, 'completion')],
                         'outer archive history differs after retries')
                    verify(children[0], remote, local, receipt, directory)
                need(len(collector_calls) == 1, 'retry regenerated the collector response')
                need(archive.attempts[0] == archive.attempts[1], 'outer retry changed its bootstrap unit')
        else:
            raise AssertionError(scenario)
    need(budgets, 'retry helper was not called')
print(json.dumps({'passed': True, 'scenario': scenario, 'network_calls': 0}))
`;

for (const scenario of ['transient-upload', 'accepted-lost-ack', 'transient-readback', 'permanent-http',
  'corrupt-readback', 'four-attempts', 'changed-closed-input', 'execute-collector', 'execute-collector-permanent']) {
  test(`after evaluation retry: ${scenario}`, { timeout: 20000 }, () => {
    const result = spawnSync('python3', ['-c', fixture, scenario], {
      cwd: process.cwd(), encoding: 'utf8', timeout: 18000,
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
    });
    assert.equal(result.status, 0, result.stderr || result.error?.message);
    assert.deepEqual(JSON.parse(result.stdout.trim()), { passed: true, scenario, network_calls: 0 });
  });
}
