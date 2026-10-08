#!/usr/bin/env python3
"""Sequential native work with a verified remote intent/result journal."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from file_integrity import IntegrityError

REPO = Path(__file__).resolve().parents[2]


def now():
    return datetime.now(timezone.utc).isoformat()


def relative(value):
    path = Path(value)
    if not value or not path.parts or path.is_absolute() or '..' in path.parts or str(path) != value:
        raise RuntimeError('unsafe relative path: ' + str(value))
    return path


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def identity(path):
    s = Path(path).stat()
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def check_binding(path, expected):
    before = identity(path)
    if before[2] != expected['bytes'] or digest(path) != expected['sha256']:
        raise RuntimeError('binding mismatch: ' + str(path))
    if before != identity(path):
        raise RuntimeError('binding changed while hashing: ' + str(path))
    return before


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def unit_paths(unit, run_dir):
    name = unit['id']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
        raise RuntimeError('invalid unit ID')
    return tuple(run_dir / '_units' / (name + suffix)
                 for suffix in ('.intent.json', '.result.json', '.stdout', '.stderr'))


def artifact_files(unit, run_dir, *, allow_invalid=False):
    files = {}
    for value in unit.get('outputs', []):
        rel = relative(value)
        if rel.parts[0] == '_units':
            raise RuntimeError('output uses reserved journal directory')
        path = run_dir / rel
        if path.is_symlink():
            if allow_invalid:
                continue
            raise RuntimeError('declared output is a symlink')
        if path.is_dir():
            children = sorted(p for p in path.rglob('*') if p.is_file())
        else:
            children = [path] if path.exists() else []
        for child in children:
            if child.is_symlink() or not child.resolve().is_relative_to(run_dir.resolve()):
                if allow_invalid:
                    continue
                raise RuntimeError('output escapes run directory')
            files[str(child.relative_to(run_dir))] = child
    logs = [run_dir / relative(unit[key]) for key in ('stdout', 'stderr') if key in unit]
    logs += [run_dir / '_units' / (unit['id'] + '.check.' + channel) for channel in ('stdout', 'stderr')]
    for path in [*unit_paths(unit, run_dir), *logs]:
        if path.exists():
            files[str(path.relative_to(run_dir))] = path
    return files


def sync_result(archive, unit, run_dir, receipt):
    archive.sync_unit(unit['id'] + '.result', artifact_files(unit, run_dir, allow_invalid=receipt['status'] != 'completed'),
                      sequence=receipt['sequence'])
    if receipt['status'] != 'completed':
        raise RuntimeError('unit ' + unit['id'] + ' ended ' + receipt['status'])
    return receipt['sequence'] + 1


def run_work_units(archive, units, execute_callback, *, run_dir, next_sequence=0):
    """Publish each intent before execution; publish each result before advancing.

    The callback receives (unit, Path(run_dir)) and returns an exit code or None.
    Recovered completed units are reverified, never executed again. An intent
    without a result is recorded as interrupted and requires a separate attempt.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    if len({u['id'] for u in units}) != len(units):
        raise RuntimeError('duplicate unit IDs')
    for unit in units:
        intent, result, _, _ = unit_paths(unit, run_dir)
        if result.exists():
            receipt = json.loads(result.read_text())
            if receipt['unit'] != unit:
                raise RuntimeError('recovered unit differs from frozen plan')
            next_sequence = max(next_sequence, sync_result(archive, unit, run_dir, receipt))
            continue
        interrupted = intent.exists()
        if interrupted:
            record = json.loads(intent.read_text())
            if record['unit'] != unit:
                raise RuntimeError('recovered intent differs from frozen plan')
            result_sequence = record['sequence'] + 1
        else:
            record = {'unit': unit, 'sequence': next_sequence, 'started_utc': now()}
            save(intent, record)
            archive.sync_unit(unit['id'] + '.intent',
                              {str(intent.relative_to(run_dir)): intent}, sequence=next_sequence)
            result_sequence = next_sequence + 1
        receipt = {'unit': unit, 'sequence': result_sequence,
                   'started_utc': record['started_utc'], 'status': 'interrupted', 'return_code': None}
        failure = None
        if not interrupted:
            try:
                if any((run_dir / relative(p)).exists() for p in unit.get('outputs', [])):
                    raise RuntimeError('declared output already exists before execution')
                code = execute_callback(unit, run_dir)
                if isinstance(code, dict):
                    receipt['commands'] = code['commands']
                    code = code['return_code']
                receipt['return_code'] = 0 if code is None else int(code)
                missing = [p for p in unit.get('outputs', []) if not (run_dir / relative(p)).exists()]
                if missing:
                    raise RuntimeError('declared outputs missing: ' + ', '.join(missing))
                receipt['status'] = 'completed' if receipt['return_code'] == 0 else 'failed'
            except BaseException as exc:
                failure = exc
                receipt['status'] = 'interrupted' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'failed'
                receipt['error_type'] = type(exc).__name__
                if isinstance(exc, IntegrityError):
                    receipt['integrity_error'] = exc.diagnostic
        receipt['finished_utc'] = now()
        receipt['artifacts'] = []
        try:
            files = artifact_files(unit, run_dir)
        except RuntimeError:
            receipt.update(status='failed', error_type='InvalidArtifactPath')
            files = artifact_files(unit, run_dir, allow_invalid=True)
        for name, path in files.items():
            with path.open('rb') as stream:
                os.fsync(stream.fileno())
            receipt['artifacts'].append({'path': name, 'bytes': path.stat().st_size, 'sha256': digest(path)})
        save(result, receipt)
        next_sequence = sync_result(archive, unit, run_dir, receipt)
        if failure:
            raise failure
    return next_sequence


def resume_work_units(archive, units, execute_callback, *, run_dir):
    sequence = archive.recover(Path(run_dir))['next_sequence']
    return run_work_units(archive, units, execute_callback, run_dir=run_dir, next_sequence=sequence)


def validate_plan(plan):
    if plan.get('schema_version') != 1 or not plan.get('run_id'):
        raise RuntimeError('unsupported launch plan')
    paths = set()
    def reserve(value):
        name = str(relative(value))
        if (Path(name).parts[0] in ('plan.json', 'completion.json', '_units', '_durable-recovery.json')
                or any(name == p or name.startswith(p + '/') or p.startswith(name + '/') for p in paths)):
            raise RuntimeError('duplicate, overlapping or reserved artifact destination')
        paths.add(name)
    for item in plan['bindings']:
        relative(item['path'])
        check_binding(REPO / item['path'], item)
        if item.get('snapshot'):
            reserve(item['snapshot'])
    for item in plan.get('bootstrap', []):
        relative(item['source'])
        reserve(item['path'])
        check_binding(REPO / item['source'], item)
    if len({p['id'] for p in plan['phases']}) != len(plan['phases']):
        raise RuntimeError('duplicate phase IDs')
    for phase in plan['phases']:
        unit_paths(phase, Path('.'))
        for key in ('argv', 'check_argv'):
            if key == 'check_argv' and key not in phase:
                continue
            if not phase.get(key) or not all(isinstance(v, str) and v for v in phase[key]):
                raise RuntimeError('invalid argv')
        for value in phase.get('outputs', []) + [phase[k] for k in ('stdout', 'stderr') if k in phase]:
            reserve(value)
        for key in {**plan.get('environment', {}), **phase.get('environment', {})}:
            if 'TOKEN' in key.upper() or 'SECRET' in key.upper():
                raise RuntimeError('credentials cannot appear in a frozen plan')
    return plan


def validate_remote(plan, repo, prefix):
    remote = plan.get('remote')
    if remote is not None and (remote.get('repo') != repo or remote.get('prefix') != prefix
                               or remote.get('private') is not True):
        raise RuntimeError('archive destination differs from the frozen private destination')


def execute_plan(archive, plan, run_dir, sequence):
    if json.loads((run_dir / 'plan.json').read_text()) != plan:
        raise RuntimeError('copied launch plan differs from preflight plan')
    bindings = {REPO / b['path']: b for b in plan['bindings']}
    bindings.update({run_dir / b['path']: b for b in plan.get('bootstrap', [])})
    bindings.update({run_dir / b['snapshot']: b for b in plan['bindings'] if b.get('snapshot')})
    bindings[run_dir / 'plan.json'] = {'bytes': (run_dir / 'plan.json').stat().st_size,
                                      'sha256': digest(run_dir / 'plan.json')}
    identities = {path: check_binding(path, expected) for path, expected in bindings.items()}

    def execute(unit, destination):
        for path, before in identities.items():
            if identity(path) != before:
                raise RuntimeError('bound file changed before phase: ' + str(path))
        for value in unit.get('outputs', []):
            output = destination / relative(value)
            if not output.resolve().is_relative_to(destination.resolve()):
                raise RuntimeError('output parent escapes run directory')
            output.parent.mkdir(parents=True, exist_ok=True)
        print(json.dumps({'unit': unit['id'], 'status': 'intent-remotely-verified', 'started_utc': now()}),
              file=sys.stderr, flush=True)
        _, _, default_stdout, default_stderr = unit_paths(unit, destination)
        stdout = destination / relative(unit['stdout']) if 'stdout' in unit else default_stdout
        stderr = destination / relative(unit['stderr']) if 'stderr' in unit else default_stderr
        env = {k: v for k, v in os.environ.items() if 'TOKEN' not in k.upper() and 'SECRET' not in k.upper()}
        env.update(plan.get('environment', {}))
        env.update(unit.get('environment', {}))
        commands = []
        invocations = [(unit['argv'], stdout, stderr)]
        if unit.get('check_argv'):
            invocations.append((unit['check_argv'], destination / '_units' / (unit['id'] + '.check.stdout'),
                                destination / '_units' / (unit['id'] + '.check.stderr')))
        for frozen_argv, output, error in invocations:
            argv = [arg.replace('@RUN@', str(destination)) for arg in frozen_argv]
            output.parent.mkdir(parents=True, exist_ok=True)
            error.parent.mkdir(parents=True, exist_ok=True)
            record = {'argv': frozen_argv, 'started_utc': now()}
            with output.open('xb') as out, error.open('xb') as err:
                child = subprocess.Popen(argv, cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err)
                try:
                    code = child.wait()
                except BaseException:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
                    raise
                finally:
                    out.flush()
                    err.flush()
                    os.fsync(out.fileno())
                    os.fsync(err.fileno())
            record.update(return_code=code, finished_utc=now())
            commands.append(record)
            if code:
                break
        return {'return_code': code, 'commands': commands}

    sequence = run_work_units(archive, plan['phases'], execute, run_dir=run_dir, next_sequence=sequence)
    completion = run_dir / 'completion.json'
    if not completion.exists():
        verified, failed = [], []
        for path, expected in bindings.items():
            name = str(path.relative_to(run_dir)) if path.is_relative_to(run_dir) else str(path.relative_to(REPO))
            try:
                check_binding(path, expected)
                verified.append({'path': name, 'sha256': expected['sha256'], 'bytes': expected['bytes']})
            except (RuntimeError, OSError):
                failed.append(name)
        save(completion, {'status': 'failed' if failed else 'completed', 'finished_utc': now(),
                          'sequence': sequence, 'run_id': plan['run_id'],
                          'verified_bindings': verified, 'failed_bindings': failed})
    receipt = json.loads(completion.read_text())
    remote = archive.sync_unit('completion', {'completion.json': completion}, sequence=receipt['sequence'])
    if receipt['status'] != 'completed':
        raise RuntimeError('final binding verification failed; failure archived')
    return {**receipt, 'remote_verification': remote}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('preflight', 'run', 'resume'))
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--hf-repo')
    parser.add_argument('--remote-prefix', default='experiments/layer-readout')
    parser.add_argument('--run-id')
    parser.add_argument('--token-file', type=Path)
    args = parser.parse_args()
    if sys.flags.optimize or os.environ.get('PYTHONOPTIMIZE'):
        raise RuntimeError('optimized Python execution is unsupported')
    if args.mode == 'preflight':
        validate_plan(json.loads(args.plan.read_text()))
        print(json.dumps({'status': 'preflight-passed'}))
        return
    if not args.run_dir or not args.hf_repo:
        parser.error('--run-dir and --hf-repo are required')
    run_dir = args.run_dir.resolve()
    # The durable backend is imported only for commands that use remote storage.
    sys.path.insert(0, str(REPO / 'training'))
    from durable_archive import DurableArchive, HFTransport
    token = args.token_file.read_text().strip() if args.token_file else os.environ.get('HF_TOKEN', '')
    transport = HFTransport(args.hf_repo, token)
    if args.mode == 'resume':
        if not args.run_id:
            parser.error('--run-id is required for resume')
        archive = DurableArchive(transport, args.run_id, prefix=args.remote_prefix)
        sequence = archive.recover(run_dir)['next_sequence']
        plan = json.loads((run_dir / 'plan.json').read_text())
        if plan['run_id'] != args.run_id:
            raise RuntimeError('recovered run identity mismatch')
        validate_remote(plan, args.hf_repo, args.remote_prefix)
    else:
        plan = validate_plan(json.loads(args.plan.read_text()))
        validate_remote(plan, args.hf_repo, args.remote_prefix)
        archive = DurableArchive(transport, plan['run_id'], prefix=args.remote_prefix)
        if run_dir.exists():
            raise RuntimeError('run destination must be new')
        run_dir.mkdir(parents=True)
        shutil.copy2(args.plan, run_dir / 'plan.json')
        files = {'plan.json': run_dir / 'plan.json'}
        copies = [(b['path'], b['snapshot'], b) for b in plan['bindings'] if b.get('snapshot')]
        copies += [(b['source'], b['path'], b) for b in plan.get('bootstrap', [])]
        for source, target, expected in copies:
            destination = run_dir / relative(target)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / relative(source), destination)
            check_binding(destination, expected)
            files[target] = destination
        archive.sync_unit('bootstrap', files, sequence=0)
        sequence = 1
    print(json.dumps(execute_plan(archive, plan, run_dir, sequence)))


if __name__ == '__main__':
    main()
