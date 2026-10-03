#!/usr/bin/env python3
"""Continue one live before arm into its matched after arm and native evaluation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'training'))
from layers.run_layers import check_binding, digest, now, save


class ContinuationError(RuntimeError):
    pass


def need(condition, message):
    if not condition:
        raise ContinuationError(message)


def inside(path):
    path = Path(path).resolve()
    need(path.is_relative_to(ROOT), 'continuation paths must remain inside the repository')
    return path


def process_identity(pid, expected_run=None):
    """PID plus kernel start time protects against PID reuse; argv is hashed."""
    proc = Path('/proc') / str(pid)
    try:
        stat = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
        if stat[0] == 'Z':
            return None
        raw = (proc / 'cmdline').read_bytes()
        if expected_run is not None:
            argv = [x.decode() for x in raw.split(b'\0') if x]
            need(any(a.endswith('training/explanations/run_training.py') for a in argv),
                 'before PID is not the training archive parent')
            need(argv.count('--run-dir') == 1, 'before parent has no unique run directory')
            actual = Path(argv[argv.index('--run-dir') + 1])
            if not actual.is_absolute():
                actual = Path(os.readlink(proc / 'cwd')) / actual
            need(actual.resolve() == Path(expected_run).resolve(), 'before PID belongs to another run')
        return {'pid': pid, 'start_ticks': int(stat[19]),
                'cmdline_sha256': hashlib.sha256(raw).hexdigest()}
    except (FileNotFoundError, ProcessLookupError):
        return None


def verified_completion(directory, *, evaluation=False):
    directory = Path(directory)
    ack_path = directory / ('_receipts/completion.json' if evaluation else '_units/completion.ack.json')
    try:
        ack = json.loads(ack_path.read_text())
        completion_path = directory / 'completion.json'
        completed = json.loads(completion_path.read_text())
        remote = ack['remote_verification']
        launch = json.loads((directory / 'plan.json').read_text())
        entry = [f for f in remote['files'] if f['name'] == 'completion.json']
        need(ack['archive_status'] == 'verified' and remote['verified_remote_bytes'] is True and
             remote['unit_id'] == 'completion' and re.fullmatch(r'[0-9a-f]{40}', remote['revision']),
             'completion has no verified remote receipt')
        need(remote.get('run_id') == launch['run_id'] and all(ack.get(k) == v for k, v in completed.items()
             if k not in ('status', 'archive_status')), 'completion identity or acknowledged fields mismatch')
        need(len(entry) == 1 and entry[0]['sha256'] == digest(completion_path) and
             entry[0]['size'] == completion_path.stat().st_size, 'completion receipt bytes mismatch')
        need(completed['plan_sha256'] == digest(directory / 'plan.json'), 'completed plan changed')
        if evaluation:
            need(ack['status'] == 'native_evaluation_completed' and completed['semantic_audit'] == 'pending' and
                 completed['generation_calls'] == 228, 'native evaluation is incomplete')
        else:
            need(ack['status'] == 'completed' and completed['return_code'] == 0 and
                 completed['acknowledged_updates'] == 100, 'training trajectory is incomplete')
        return ack
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    except (KeyError, TypeError):
        raise ContinuationError('invalid completion receipt') from None


def wait_before(directory, expected, *, poll_seconds=5, timeout_seconds=86400,
                identity_fn=process_identity, completion_fn=verified_completion,
                sleep=time.sleep, clock=time.monotonic):
    deadline = clock() + timeout_seconds
    while True:
        need(not (Path(directory) / 'failure.json').exists(), 'before training recorded failure')
        current = identity_fn(expected['pid']) if expected else None
        # A completion file can still be being written while its owner is alive.
        completed = completion_fn(directory)
        if current != expected or current is None:
            need(completed is not None, 'before parent exited or changed identity without verified completion')
            return completed
        need(clock() < deadline, 'before completion wait timed out')
        sleep(poll_seconds)


def freeze(args):
    before, after, template = inside(args.before_run), inside(args.after_run), inside(args.after_template)
    output, evaluation, contract = inside(args.state_dir), inside(args.evaluation_run), inside(args.evaluation_plan)
    need(type(args.before_pid) is int and args.before_pid > 0, 'invalid before PID')
    need(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,49}', args.run_id), 'invalid continuation run ID')
    need(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,49}', args.evaluation_run_id), 'invalid evaluation run ID')
    need(0.1 <= args.poll_seconds <= 30 and 1 <= args.wait_timeout_seconds <= 172800, 'invalid wait bounds')
    paths = [before, after, output, evaluation]
    need(all(a != b and not a.is_relative_to(b) and not b.is_relative_to(a)
             for i, a in enumerate(paths) for b in paths[i + 1:]), 'run directories overlap')
    need(before.is_dir() and not any(p.exists() for p in (after, output, evaluation)), 'continuation output must be new')
    expected = process_identity(args.before_pid, before)
    need(expected is not None or verified_completion(before) is not None, 'before parent is absent and not complete')
    scripts = ['continue_experiment.py', 'prepare_launches.py', 'run_training.py',
               'execute_evaluation.py', 'collect_generation.py', 'score_generation.py']
    sources = [before / 'plan.json', template, contract,
               ROOT / 'training/durable_archive.py', ROOT / 'training/layers/run_layers.py']
    sources += [ROOT / 'training/explanations' / p for p in scripts]
    bound = [{'path': str(p.relative_to(ROOT)), 'bytes': p.stat().st_size, 'sha256': digest(p)}
             for p in dict.fromkeys(sources)]
    plan = {'schema': 'jovovich.explanation-order.continuation.v1', 'run_id': args.run_id,
            'created_utc': now(), 'before_run': str(before.relative_to(ROOT)),
            'after_run': str(after.relative_to(ROOT)), 'after_template': str(template.relative_to(ROOT)),
            'evaluation_run': str(evaluation.relative_to(ROOT)), 'evaluation_plan': str(contract.relative_to(ROOT)),
            'evaluation_run_id': args.evaluation_run_id, 'before_process': expected,
            'poll_seconds': args.poll_seconds, 'wait_timeout_seconds': args.wait_timeout_seconds,
            'bindings': bound, 'python': sys.executable,
            'remote': {'repo': 'ataeff/jovovich', 'prefix': 'experiments/explanation-order'},
            'credentials': 'Provided only to phase archive parents through an unrecorded token-file argument.'}
    output.mkdir(parents=True)
    save(output / 'plan.json', plan)
    return plan, output


def guard(plan, output, plan_sha256):
    need(digest(output / 'plan.json') == plan_sha256, 'continuation plan bytes changed')
    need(json.loads((output / 'plan.json').read_text()) == plan, 'continuation plan changed')
    for item in plan['bindings']:
        check_binding(ROOT / item['path'], item)


def command(argv, output, name):
    """Only one phase process exists; its own archive parent owns HF writes."""
    with (output / (name + '.stdout')).open('xb') as out, (output / (name + '.stderr')).open('xb') as err:
        env = {k: v for k, v in os.environ.items()
               if not any(w in k.upper() for w in ('TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL', 'API_KEY'))}
        child = subprocess.Popen(argv, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                 stdout=out, stderr=err, start_new_session=True)
        try:
            code = child.wait()
        except BaseException:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
            raise
        finally:
            out.flush(); err.flush()
            os.fsync(out.fileno()); os.fsync(err.fileno())
    need(code == 0, 'continuation phase failed: ' + name)


def execute(plan, output, token_file, *, wait=wait_before, archive_factory=None, run=command):
    """Wait for the existing writer to exit before this supervisor uploads."""
    output, token_file = Path(output), Path(token_file)
    archive, sequence = None, 0
    pending_archive, active_phase = False, None
    plan_sha256 = digest(output / 'plan.json')
    def check():
        guard(plan, output, plan_sha256)
    def sync(unit, files, sequence):
        nonlocal pending_archive
        pending_archive = True
        receipt = archive.sync_unit(unit, files, sequence=sequence)
        pending_archive = False
        return receipt
    before, after = ROOT / plan['before_run'], ROOT / plan['after_run']
    try:
        check()
        print(json.dumps({'phase': 'before', 'status': 'waiting_for_verified_parent_exit'}), file=sys.stderr, flush=True)
        wait(before, plan['before_process'], poll_seconds=plan['poll_seconds'], timeout_seconds=plan['wait_timeout_seconds'])
        check()
        if archive_factory is None:
            from durable_archive import DurableArchive, HFTransport
            archive = DurableArchive(HFTransport(plan['remote']['repo'], token_file.read_text().strip()),
                                     plan['run_id'], prefix=plan['remote']['prefix'])
        else:
            archive = archive_factory()
        files = {'plan.json': output / 'plan.json'}
        for item in plan['bindings']:
            files['inputs/' + item['path']] = ROOT / item['path']
        sync('continuation-intent', files, sequence=sequence)
        sequence += 1
        check()
        phases = [
            ('bind-after', [plan['python'], 'training/explanations/prepare_launches.py', 'bind-after',
                           '--template', str(ROOT / plan['after_template']), '--before-run', str(before),
                           '--output', str(output / 'after.launch.json')]),
            ('after-training', [plan['python'], 'training/explanations/run_training.py', 'run',
                                '--plan', str(output / 'after.launch.json'), '--run-dir', str(after),
                                '--token-file', str(token_file)]),
            ('native-evaluation', [plan['python'], 'training/explanations/execute_evaluation.py', 'run',
                                   '--plan', str(ROOT / plan['evaluation_plan']), '--before', str(before),
                                   '--after', str(after), '--output', str(ROOT / plan['evaluation_run']),
                                   '--run-id', plan['evaluation_run_id'], '--token-file', str(token_file)])]
        for name, argv in phases:
            active_phase = name
            check()
            if name != 'bind-after':
                check_binding(ROOT / after_binding['path'], after_binding)
            print(json.dumps({'phase': name, 'status': 'running'}), file=sys.stderr, flush=True)
            save(output / (name + '.intent.json'), {'phase': name, 'started_utc': now()})
            sync(name + '-intent', {name + '.intent.json': output / (name + '.intent.json')}, sequence=sequence)
            sequence += 1
            check()
            if name != 'bind-after':
                check_binding(ROOT / after_binding['path'], after_binding)
            run(argv, output, name)
            check()
            files = {name + '.' + stream: output / (name + '.' + stream) for stream in ('stdout', 'stderr')}
            if name == 'bind-after':
                launch = output / 'after.launch.json'
                need(launch.is_file(), 'after binding did not produce a launch plan')
                after_binding = {'path': str(launch.relative_to(ROOT)), 'bytes': launch.stat().st_size, 'sha256': digest(launch)}
                files['after.launch.json'] = launch
            else:
                check_binding(ROOT / after_binding['path'], after_binding)
                directory = after if name == 'after-training' else ROOT / plan['evaluation_run']
                need(verified_completion(directory, evaluation=name == 'native-evaluation') is not None,
                     'phase ended without verified completion')
            save(output / (name + '.result.json'), {'phase': name, 'status': 'completed', 'finished_utc': now()})
            files[name + '.result.json'] = output / (name + '.result.json')
            sync(name + '-result', files, sequence=sequence)
            sequence += 1
        check()
        check_binding(ROOT / after_binding['path'], after_binding)
        result = {'status': 'native_evaluation_done', 'semantic_audit': 'pending', 'finished_utc': now(),
                  'plan_sha256': plan_sha256}
        save(output / 'completion.json', result)
        receipt = sync('completion', {'completion.json': output / 'completion.json'}, sequence=sequence)
        result = {**result, 'archive_status': 'verified', 'remote_verification': receipt}
        save(output / 'completion.ack.json', result)
        return result
    except BaseException as exc:
        failure = {'status': 'failed', 'error_type': type(exc).__name__, 'finished_utc': now()}
        if not (output / 'failure.json').exists():
            save(output / 'failure.json', failure)
        # The phase child has exited before reaching this handler. Never open a
        # second writer while waiting for before, or replace a pending unit.
        if archive is not None and not pending_archive:
            files = {'failure.json': output / 'failure.json'}
            if active_phase:
                for suffix in ('intent.json', 'stdout', 'stderr', 'result.json'):
                    path = output / (active_phase + '.' + suffix)
                    if path.is_file():
                        files[path.name] = path
            try:
                receipt = sync('continuation-failure', files, sequence=sequence)
                save(output / 'failure.ack.json', receipt)
            except Exception:
                pass
        raise ContinuationError('continuation stopped; inspect its immutable phase journal') from None


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('before-run', 'after-template', 'after-run', 'evaluation-plan', 'evaluation-run', 'state-dir', 'token-file'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--before-pid', type=int, required=True)
    p.add_argument('--run-id', required=True)
    p.add_argument('--evaluation-run-id', required=True)
    p.add_argument('--poll-seconds', type=float, default=5)
    p.add_argument('--wait-timeout-seconds', type=float, default=86400)
    return p


def main():
    args = parser().parse_args()
    try:
        plan, output = freeze(args)
        print(json.dumps(execute(plan, output, args.token_file)))
    except (OSError, ValueError, RuntimeError) as error:
        print('continue_experiment: stopped (' + type(error).__name__ + '); inspect the phase journal', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
