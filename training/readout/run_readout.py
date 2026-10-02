#!/usr/bin/env python3
"""Execute a frozen native readout protocol with byte-bound inputs and receipts.

The plan supplies literal argv arrays, never shell command text. Model arithmetic
and fitting belong to the native executables; this helper only orchestrates them.
All phase outputs must be new files inside the explicitly supplied run directory.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from datetime import datetime, timezone


def require(value, message):
    if not value:
        raise ValueError(message)


def file_record(path):
    h = hashlib.sha256()
    size = 0
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
            size += len(chunk)
    return {'path': str(path), 'sha256': h.hexdigest(), 'bytes': size}


def resolve(path, cwd):
    require(isinstance(path, str) and path, 'empty or invalid path')
    return (cwd / path).resolve()


def save_new(path, value):
    with path.open('x') as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
        f.write('\n')


def verify(bindings, cwd):
    checked = {}
    for name, item in bindings.items():
        require(isinstance(item, dict), 'invalid binding: ' + name)
        path = resolve(item['path'], cwd)
        actual = file_record(path)
        require(actual['sha256'] == item['sha256'], 'frozen SHA256 changed: ' + name)
        require(actual['bytes'] == item['bytes'], 'frozen byte count changed: ' + name)
        checked[name] = actual
    return checked


def verify_outputs(phases):
    for phase in phases:
        for record in [phase['stdout'], phase['stderr'], *phase['created_files']]:
            require(file_record(Path(record['path'])) == record, 'generated output changed: ' + record['path'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    plan_path = args.plan.resolve()
    initial_plan = file_record(plan_path)
    plan = json.loads(plan_path.read_bytes())
    require(plan.get('protocol_frozen') is True, 'protocol must be frozen before execution')
    execution = plan['execution']
    cwd = Path(execution['cwd']).resolve()
    require(cwd.is_dir(), 'execution cwd missing')
    out = args.output_dir.resolve()
    require(out.is_dir(), 'prepared output directory missing')
    receipt_path = out / 'readout-run.json'
    require(not receipt_path.exists(), 'run receipt already exists')
    bindings = plan['frozen_inputs']
    require(isinstance(bindings, dict) and bindings, 'no frozen inputs')
    self_sha = file_record(Path(__file__).resolve())['sha256']
    require(any(item['sha256'] == self_sha for item in bindings.values()), 'runner source is not frozen')
    phases = execution['phases']
    require(isinstance(phases, list) and phases, 'no phases')
    names = set()
    paths = set()
    for phase in phases:
        require(isinstance(phase['name'], str) and phase['name'] not in names, 'duplicate/invalid phase name')
        names.add(phase['name'])
        argv = phase['argv']
        require(isinstance(argv, list) and argv and all(isinstance(x, str) and x for x in argv), 'argv must be nonempty literal strings')
        for value in [phase['stdout'], phase['stderr'], *phase.get('creates', [])]:
            path = resolve(value, cwd)
            require(path.is_relative_to(out), 'phase output outside run directory: ' + str(path))
            require(path != receipt_path and path not in paths, 'phase output reused: ' + str(path))
            require(not path.exists(), 'phase output already exists: ' + str(path))
            require(path.parent.is_dir(), 'phase output parent missing: ' + str(path))
            paths.add(path)
    environment = execution.get('environment', {})
    require(isinstance(environment, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in environment.items()), 'invalid execution environment')
    started = time.monotonic()
    receipt = {'schema_version': 1, 'status': 'running', 'started_at_utc': datetime.now(timezone.utc).isoformat(),
               'plan': initial_plan, 'cwd': str(cwd), 'environment_overrides': environment,
               'phases': [], 'model_training': False, 'model_weights_changed': False,
               'all_frozen_inputs_unchanged': False,
               'peak_rss_units': 'KiB on this Linux host',
               'peak_rss_note': 'Exact child rusage from Linux wait4 for each phase.'}
    try:
        verify(bindings, cwd)
        for phase in phases:
            require(file_record(plan_path) == initial_plan, 'plan changed during execution')
            verify(bindings, cwd)
            verify_outputs(receipt['phases'])
            stdout_path = resolve(phase['stdout'], cwd)
            stderr_path = resolve(phase['stderr'], cwd)
            phase_start = time.monotonic()
            row = {'name': phase['name'], 'argv': phase['argv'], 'elapsed_seconds': None,
                   'returncode': None, 'peak_rss_kib': None,
                   'user_cpu_seconds': None, 'system_cpu_seconds': None,
                   'stdout': None, 'stderr': None, 'missing_log_files': [],
                   'created_files': [], 'missing_created_files': []}
            receipt['phases'].append(row)
            try:
                # Linux wait4 obtains this exact child's rusage, rather than the
                # process-global RUSAGE_CHILDREN peak inherited from earlier phases.
                with stdout_path.open('xb') as stdout, stderr_path.open('xb') as stderr:
                    child = subprocess.Popen(phase['argv'], cwd=cwd, env={**os.environ, **environment}, stdout=stdout, stderr=stderr)
                    _, status, usage = os.wait4(child.pid, 0)
                    code = os.waitstatus_to_exitcode(status)
                    child.returncode = code
                    row.update(returncode=code, peak_rss_kib=usage.ru_maxrss,
                               user_cpu_seconds=usage.ru_utime, system_cpu_seconds=usage.ru_stime)
            except BaseException as exc:
                row['failure_type'] = type(exc).__name__
                row['failure'] = str(exc)
                raise
            finally:
                row['elapsed_seconds'] = time.monotonic() - phase_start
                # A launch failure can still create logs. Preserve those and
                # every declared artifact before propagating any phase failure.
                for field, path in [('stdout', stdout_path), ('stderr', stderr_path)]:
                    if path.is_file():
                        row[field] = file_record(path)
                    else:
                        row['missing_log_files'].append(str(path))
                for value in phase.get('creates', []):
                    path = resolve(value, cwd)
                    if path.is_file():
                        row['created_files'].append(file_record(path))
                    else:
                        row['missing_created_files'].append(str(path))
            require(row['returncode'] == 0, 'native/procedure phase failed: ' + phase['name'])
            require(not row['missing_created_files'],
                    'phase did not create declared files: ' + ', '.join(row['missing_created_files']))
            verify(bindings, cwd)
            verify_outputs(receipt['phases'])
        verify_outputs(receipt['phases'])
        require(file_record(plan_path) == initial_plan, 'plan changed during execution')
        receipt['verified_frozen_inputs'] = verify(bindings, cwd)
        receipt['all_frozen_inputs_unchanged'] = True
        receipt['status'] = 'completed'
    except BaseException as exc:
        receipt['status'] = 'failed'
        receipt['failure_type'] = type(exc).__name__
        receipt['failure'] = str(exc)
        raise
    finally:
        receipt['elapsed_seconds'] = time.monotonic() - started
        receipt['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        save_new(receipt_path, receipt)
    print(json.dumps({'status': receipt['status'], 'receipt': file_record(receipt_path), 'phases': len(receipt['phases'])}))


if __name__ == '__main__':
    main()
