#!/usr/bin/env python3
"""One native optimizer trajectory, gated by verified remote evidence units."""
from __future__ import annotations

import argparse
import itertools
import json
import os
from pathlib import Path
import re
import select
import shutil
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'training'))
from durable_archive import DurableArchive, HFTransport
from layers.run_layers import check_binding, digest, identity, now, relative, save

ARCHIVE_CAPABILITY = {'schema': 'jovovich.archive-ack.v1', 'startup_ack': True,
                      'initial_snapshot': True, 'per_update_ack': True}
ARCHIVE_HELLO = {'stage': 'archive_hello', 'schema': ARCHIVE_CAPABILITY['schema']}


class TrainingError(RuntimeError):
    """A sanitized launch failure; transport exception text is never propagated."""


def need(condition, message):
    if not condition:
        raise TrainingError(message)


def native_environment(plan):
    env = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL', 'TMPDIR') if k in os.environ}
    env.update(plan.get('environment', {}))
    return env


def check_archive_capability(plan, repo=REPO):
    """Ask the exact bound executable without passing any model/data paths."""
    binding = next(b for b in plan['bindings'] if b['path'] == plan['argv'][0])
    binary = Path(repo) / binding['path']
    before = check_binding(binary, binding)
    try:
        result = subprocess.run([str(binary), '--archive-protocol'], cwd=repo,
                                env=native_environment(plan), stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=5)
        capability = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError, UnicodeError):
        raise TrainingError('bound trainer does not support the required archive protocol') from None
    need(result.returncode == 0 and capability == ARCHIVE_CAPABILITY and not result.stderr,
         'bound trainer does not support the required archive protocol')
    need(all(type(capability.get(k)) is bool for k in ('startup_ack', 'initial_snapshot', 'per_update_ack')),
         'invalid native archive capability types')
    need(check_binding(binary, binding) == before, 'trainer changed during capability check')
    return {'binary_sha256': binding['sha256'], 'capability': capability}


def startup_line(child):
    """Read the first small control line with a deadline, before model work."""
    deadline, raw = time.monotonic() + 5, bytearray()
    while len(raw) < 4096:
        remaining = deadline - time.monotonic()
        need(remaining > 0 and select.select([child.stdout], [], [], remaining)[0],
             'native archive startup timed out')
        byte = os.read(child.stdout.fileno(), 1)
        need(bool(byte), 'native trainer ended before archive startup')
        raw.extend(byte)
        if byte == b'\n':
            return bytes(raw)
    raise TrainingError('oversized native archive startup record')


def validate_plan(plan, repo=REPO):
    need(plan.get('schema_version') == 1 and
         isinstance(plan.get('run_id'), str) and
         re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', plan['run_id']), 'invalid training plan')
    argv = plan.get('argv')
    need(isinstance(argv, list) and len(argv) == 10 and
         all(isinstance(a, str) and a for a in argv), 'expected complete native trainer argv')
    need(argv[3].startswith('@RUN@/'), 'output prefix must be inside the new run directory')
    output = relative(argv[3][6:])
    need(output.parts[0] not in ('_units', 'inputs', 'plan.json', 'completion.json',
                                 'failure.json', 'stdout.jsonl', 'metrics.jsonl', 'stderr.log'), 'reserved output prefix')
    for i in (0, 1, 2, 9):
        relative(argv[i])
    try:
        epochs, batch, every = (int(argv[i]) for i in (4, 6, 7))
        rate = float(argv[5])
    except ValueError:
        raise TrainingError('invalid native numeric arguments') from None
    need(0 <= epochs <= 100 and 1 <= batch <= 128 and 1 <= every <= 100 and
         0 < rate < float('inf') and argv[8] in ('joint', 'decisions'), 'invalid native training configuration')
    bindings = plan.get('bindings', [])
    paths = [b['path'] for b in bindings]
    need(len(paths) == len(set(paths)) and all(argv[i] in paths for i in (0, 1, 2, 9)),
         'binary, base, dataset and pairs must have unique bindings')
    for b in bindings:
        path = Path(repo) / relative(b['path'])
        need(not path.is_symlink() and path.is_file() and path.resolve().is_relative_to(Path(repo).resolve()),
             'bound input must be a regular file inside the repository')
        check_binding(path, b)
    environment = plan.get('environment', {})
    allowed = {'NT_NO_I8', 'NT_QMV_THREADS', 'NT_ATTN_THREADS', 'NT_SIMD_THREADS'}
    need(isinstance(environment, dict) and set(environment) <= allowed and
         all(isinstance(v, str) and re.fullmatch(r'[0-9]+', v) for v in environment.values()),
         'invalid native environment')
    need(environment.get('NT_NO_I8', '1') == '1', 'native trainer requires NT_NO_I8=1')
    timeout = plan.get('ack_timeout_ms', 300000)
    need(type(timeout) is int and 1 <= timeout <= 3600000, 'invalid archive acknowledgement timeout')
    initial = plan.get('expected_initial_lora_sha256')
    need(initial is None or (isinstance(initial, dict) and set(initial) == {'gate', 'up', 'down'} and
         all(isinstance(v, str) and re.fullmatch(r'[0-9a-f]{64}', v) for v in initial.values())),
         'invalid expected initial adapter hashes')
    check_archive_capability(plan, repo)
    return plan


def _closed_copy(source, destination, start=0):
    with source.open('rb') as src, destination.open('xb') as dst:
        src.seek(start)
        shutil.copyfileobj(src, dst)
        end = src.tell()
        dst.flush()
        os.fsync(dst.fileno())
    return end


def _stop(child):
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
    for stream in (child.stdin, child.stdout):
        if stream:
            try:
                stream.close()
            except OSError:
                pass


def run_training(archive, plan, run_dir, *, repo=REPO):
    """Archive intent, then each closed boundary, before allowing another update.

    A failed native process is never restarted here. LoRA snapshots omit Chuck's
    controller/moments, so a new process needs a new attempt directory/run ID.
    """
    repo, run_dir = Path(repo).resolve(), Path(run_dir).resolve()
    validate_plan(plan, repo)
    need(not run_dir.exists(), 'run destination must be new; use a new attempt')
    run_dir.mkdir(parents=True)
    units = run_dir / '_units'
    units.mkdir()
    save(run_dir / 'plan.json', plan)
    plan_sha256 = digest(run_dir / 'plan.json')
    bound = {repo / b['path']: b for b in plan['bindings']}
    signatures = {p: check_binding(p, b) for p, b in bound.items()}
    intent = {'status': 'intent', 'started_utc': now(), 'argv': plan['argv'],
              'environment': plan.get('environment', {}), 'bindings': plan['bindings'],
              'archive_capability': ARCHIVE_CAPABILITY}
    save(units / 'intent.json', intent)
    files = {'plan.json': run_dir / 'plan.json', '_units/intent.json': units / 'intent.json'}
    # Snapshot every bound input except the large base: its exact public/pinned
    # identity remains in the plan. Binary, data, pair map and source bytes travel.
    for path, b in bound.items():
        if b['path'] == plan['argv'][1]:
            continue
        target = run_dir / 'inputs' / b['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        _closed_copy(path, target)
        check_binding(target, b)
        files[str(target.relative_to(run_dir))] = target
    child = None
    try:
        archive.sync_unit('intent', files, sequence=0)
        need(digest(run_dir / 'plan.json') == plan_sha256, 'launch plan changed during intent verification')
        for p, b in bound.items():
            check_binding(p, b)
        check_archive_capability(plan, repo)
        argv = [str(repo / a) if i in (0, 1, 2, 9) else a.replace('@RUN@', str(run_dir))
                for i, a in enumerate(plan['argv'])]
        Path(argv[3]).parent.mkdir(parents=True, exist_ok=True)
        # Native work receives no credentials or inherited NT_* tuning.
        env = native_environment(plan)
        env.update(JOVOVICH_ARCHIVE_ACK='1',
                   JOVOVICH_ARCHIVE_ACK_TIMEOUT_MS=str(plan.get('ack_timeout_ms', 300000)))
        expected, sequence, error_offset, segment, metric_segment = 0, 1, 0, [], []
        initial_lora_sha256 = {}
        startup_verified = False
        epochs, every = int(argv[4]), int(argv[7])
        with (run_dir / 'stderr.log').open('xb') as err, (run_dir / 'stdout.jsonl').open('xb') as out, (run_dir / 'metrics.jsonl').open('xb') as metric_out:
            child = subprocess.Popen(argv, cwd=repo, env=env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=err)
            for raw in itertools.chain([startup_line(child)], child.stdout):
                out.write(raw)
                segment.append(raw)
                need(len(raw) <= 16 * 1024 * 1024, 'oversized trainer record')
                try:
                    event = json.loads(raw)
                except (ValueError, UnicodeError):
                    raise TrainingError('invalid trainer JSON record') from None
                need(isinstance(event, dict), 'invalid trainer record')
                if not startup_verified:
                    need(event == ARCHIVE_HELLO, 'native trainer did not open the archive startup handshake')
                    need(digest(run_dir / 'plan.json') == plan_sha256, 'launch plan changed before startup')
                    for p, before in signatures.items():
                        need(identity(p) == before, 'bound file changed before native startup')
                    child.stdin.write(b'START\n')
                    child.stdin.flush()
                    startup_verified = True
                    continue
                if event.get('stage') != 'archive_ready':
                    need(event.get('stage') in ('sft_initial', 'sft', 'decision_train'), 'unknown trainer metric stage')
                    metric_out.write(raw)
                    metric_segment.append(raw)
                    continue
                saved = expected == 0 or expected % every == 0 or expected == epochs
                need(type(event.get('update')) is int and event['update'] == expected and
                     type(event.get('snapshot_saved')) is bool and event['snapshot_saved'] == saved and
                     expected <= epochs, 'unexpected trainer acknowledgement boundary')
                for p, before in signatures.items():
                    need(identity(p) == before, 'bound file changed during native training')
                out.flush()
                os.fsync(out.fileno())
                metric_out.flush()
                os.fsync(metric_out.fileno())
                err.flush()
                os.fsync(err.fileno())
                name = 'update-%03d' % expected
                raw_log, metrics = units / (name + '.raw.jsonl'), units / (name + '.metrics.jsonl')
                for path, records in ((raw_log, segment), (metrics, metric_segment)):
                    with path.open('xb') as stream:
                        stream.write(b''.join(records))
                        stream.flush()
                        os.fsync(stream.fileno())
                log = units / (name + '.stderr')
                error_offset = _closed_copy(run_dir / 'stderr.log', log, error_offset)
                files = {str(p.relative_to(run_dir)): p for p in (raw_log, metrics, log)}
                if saved:
                    for suffix in ('gate', 'up', 'down'):
                        for extension in ('f32', 'lora'):
                            path = Path('%s.epoch%02d.%s.%s' % (argv[3], expected, suffix, extension))
                            need(path.is_file() and not path.is_symlink(), 'checkpoint file missing')
                            files[str(path.relative_to(run_dir))] = path
                            if expected == 0 and extension == 'lora':
                                initial_lora_sha256[suffix] = digest(path)
                if expected == 0:
                    wanted = plan.get('expected_initial_lora_sha256')
                    need(wanted is None or initial_lora_sha256 == wanted,
                         'initial adapters differ from the required paired initialization')
                    initialization = units / 'initialization.json'
                    save(initialization, {'initial_lora_sha256': initial_lora_sha256,
                                          'expected_initial_lora_sha256': wanted})
                    files['_units/initialization.json'] = initialization
                receipt = archive.sync_unit(name, files, sequence=sequence)
                save(units / (name + '.ack.json'), receipt)
                for p, before in signatures.items():
                    need(identity(p) == before, 'bound file changed during archive verification')
                need(digest(run_dir / 'plan.json') == plan_sha256, 'launch plan changed during archive verification')
                child.stdin.write(('ACK %d\n' % expected).encode())
                child.stdin.flush()
                expected += 1
                sequence += 1
                segment = []
                metric_segment = []
            code = child.wait()
            out.flush()
            err.flush()
            metric_out.flush()
            os.fsync(out.fileno())
            os.fsync(err.fileno())
            os.fsync(metric_out.fileno())
        need(code == 0 and startup_verified and expected == epochs + 1,
             'native training ended before complete acknowledged trajectory')
        for p, b in bound.items():
            check_binding(p, b)
        need(digest(run_dir / 'plan.json') == plan_sha256, 'launch plan changed during native training')
        files = {n: run_dir / n for n in ('stdout.jsonl', 'metrics.jsonl', 'stderr.log')}
        for suffix in ('gate', 'up', 'down'):
            for extension in ('f32', 'lora'):
                path = Path('%s.%s.%s' % (argv[3], suffix, extension))
                need(path.is_file() and not path.is_symlink(), 'final weight file missing')
                files[str(path.relative_to(run_dir))] = path
        completion = {'status': 'native_completed', 'archive_status': 'requires_verified_receipt',
                      'finished_utc': now(), 'return_code': code,
                      'acknowledged_updates': epochs, 'initial_readout_acknowledged': True,
                      'initial_lora_sha256': initial_lora_sha256,
                      'plan_sha256': plan_sha256,
                      'bindings': plan['bindings'], 'sequence': sequence}
        save(run_dir / 'completion.json', completion)
        files['completion.json'] = run_dir / 'completion.json'
        receipt = archive.sync_unit('completion', files, sequence=sequence)
        verified = {**completion, 'status': 'completed', 'archive_status': 'verified',
                    'remote_verification': receipt}
        save(units / 'completion.ack.json', verified)
        return verified
    except BaseException as exc:
        if child is not None:
            _stop(child)
        if not (run_dir / 'failure.json').exists():
            save(run_dir / 'failure.json', {'status': 'interrupted' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'failed',
                  'finished_utc': now(), 'error_type': type(exc).__name__,
                  'return_code': child.returncode if child is not None else None})
        raise TrainingError('training attempt stopped; inspect its closed journal and start a new attempt') from None
    finally:
        if child is not None:
            _stop(child)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('preflight', 'run'))
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--token-file', type=Path)
    args = parser.parse_args()
    plan = validate_plan(json.loads(args.plan.read_text()))
    if args.mode == 'preflight':
        print(json.dumps({'status': 'preflight-passed'}))
        return
    need(args.run_dir is not None, '--run-dir is required')
    remote = plan.get('remote', {})
    need(remote.get('private') is True and remote.get('repo') and remote.get('prefix'),
         'a frozen private remote destination is required')
    token = args.token_file.read_text().strip() if args.token_file else os.environ.get('HF_TOKEN', '')
    archive = DurableArchive(HFTransport(remote['repo'], token), plan['run_id'], prefix=remote['prefix'])
    print(json.dumps(run_training(archive, plan, args.run_dir)))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('training launch failed; inspect local preflight or attempt journal', file=sys.stderr)
        raise SystemExit(1)
