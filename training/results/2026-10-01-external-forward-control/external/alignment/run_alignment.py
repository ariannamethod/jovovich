"""Run the separately frozen exact-weight alignment; retain every owned attempt."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import struct
import subprocess
import time


def require(condition, message):
    if not condition:
        raise ValueError(message)


def record(path):
    path = Path(path).resolve()
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            'file changed during hashing: ' + str(path))
    return dict(path=str(path), bytes=after.st_size, sha256=digest.hexdigest())


def safe_record(path):
    try:
        return record(path)
    except BaseException as error:
        return dict(path=str(Path(path).absolute()), hash_error_type=type(error).__name__, hash_error=str(error))


def snapshot(bindings):
    return [safe_record(item['path']) for item in bindings]


def save(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')


def artifacts(paths):
    """Include actual hash failures and missing outputs, not just successful files."""
    return [safe_record(path) for path in paths]


def run_phase(command, cwd, environment, stdout_path, stderr_path, outputs):
    started = time.monotonic()
    result = dict(command=command, started_utc=datetime.now(timezone.utc).isoformat(),
                  status='failed', exit_code=None, peak_rss_kib=None,
                  user_seconds=None, system_seconds=None)
    child = None
    usage = None

    def collect(blocking=True):
        nonlocal usage
        pid, status, measured = os.wait4(child.pid, 0 if blocking else os.WNOHANG)
        if pid:
            usage = measured
            child.returncode = os.waitstatus_to_exitcode(status)
        return bool(pid)

    try:
        with Path(stdout_path).open('x') as out, Path(stderr_path).open('x') as err:
            child = subprocess.Popen(command, cwd=cwd, env=environment, stdout=out, stderr=err,
                                     start_new_session=True)
            result['pid'] = child.pid
            collect()
            result['exit_code'] = child.returncode
            require(child.returncode == 0, 'child exited unsuccessfully')
        result['status'] = 'completed'
    except BaseException as error:
        result.update(failure_type=type(error).__name__, failure=str(error))
        if child is not None and child.returncode is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 10
            while not collect(False):
                if time.monotonic() >= deadline:
                    os.killpg(child.pid, signal.SIGKILL)
                    collect()
                    break
                time.sleep(0.05)
        if child is not None:
            result['exit_code'] = child.returncode
    finally:
        result['elapsed_seconds'] = time.monotonic() - started
        if usage is not None:
            result.update(peak_rss_kib=usage.ru_maxrss, user_seconds=usage.ru_utime,
                          system_seconds=usage.ru_stime)
        result['artifacts'] = artifacts([stdout_path, stderr_path, *outputs])
        result['missing_or_unhashable_outputs'] = [item for item in result['artifacts'] if 'sha256' not in item]
        if result['status'] == 'completed' and result['missing_or_unhashable_outputs']:
            result.update(status='failed', failure_type='ValueError',
                          failure='successful child omitted or corrupted required output')
    return result


def verify_dump(path, ids_path):
    expected_ids = [int(token) for token in Path(ids_path).read_text().split()]
    require(len(expected_ids) == 447, 'fixed case ID count changed')
    require(Path(path).stat().st_size == 1217308, 'unexpected full-logit dump size')
    with Path(path).open('rb') as stream:
        require(struct.unpack('<6I', stream.read(24)) == (0x324c564a, 2, 1, 151936, 2, 447),
                'unexpected dump header')
        require(list(struct.unpack('<447I', stream.read(447 * 4))) == expected_ids,
                'dump IDs differ from fixed case')
        for position in (444, 447):
            require(struct.unpack('<I', stream.read(4))[0] == position, 'dump capture index changed')
            stream.seek(151936 * 4, 1)
        require(not stream.read(1), 'trailing dump bytes')
    return dict(expected_ids=record(ids_path), captured_prefix_lengths=[444, 447],
                embedded_ids_match_fixed_case=True)


def validate_conversion_receipt(plan, converted):
    validation = json.loads(Path(plan['validation_receipt']).read_text())
    require(validation.get('status') == 'completed' and validation.get('native_exit_code') == 0,
            'independent validation did not complete')
    require(validation.get('every_tensor_exact') is True and validation.get('all_finite') is True
            and validation.get('semantic_metadata_exact') is True,
            'tensor/metadata equality gate did not pass')
    require(validation.get('base') == plan['original_model'] and validation.get('converted') == converted,
            'validation covers different model bytes')
    for key, expected in plan['validation_bindings'].items():
        require(validation.get(key) == expected, 'validation implementation binding mismatch: ' + key)
    require(validation.get('metadata_keys_checked') == 26
            and validation.get('expected_byte_extent') == 2526617472,
            'validation scope changed')
    require(validation.get('metadata_changes') == [dict(key='general.file_type',
            original_hex='0400000007000000', converted_hex='0400000000000000')],
            'unexpected metadata bookkeeping difference')
    tensors = validation.get('tensors', [])
    require(len(tensors) == 291 and len({item['name'] for item in tensors}) == 291,
            'validation tensor inventory incomplete')
    rows = [json.loads(line) for line in Path(plan['native_validation_rows']).read_text().splitlines()]
    require(len(rows) == 291 and {item['name'] for item in rows} == {item['name'] for item in tensors}
            and all(item.get('exact_float32_bytes') is True and item.get('all_finite') is True for item in rows)
            and sum(item['elements'] for item in rows) == 630167424,
            'native every-element verification incomplete')
    expected_artifacts = [record(plan['native_validation_rows']), record(plan['native_validation_stderr'])]
    require(validation.get('artifacts') == expected_artifacts, 'native validation artifact hashes differ')
    return record(plan['validation_receipt'])


def validate_metrics(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    require(len(rows) == 2 and [row['prefix_tokens'] for row in rows] == [444, 447]
            and all(row['vocabulary'] == 151936 and row['decision_ids'] == [66582, 788] for row in rows),
            'incomplete metric captures')
    for row in rows:
        for key in ('max_abs', 'relative_l2', 'rmse', 'mean_abs', 'first_top_margin',
                    'second_top_margin', 'first_concern_minus_clean', 'second_concern_minus_clean'):
            require(math.isfinite(row[key]), 'nonfinite comparison metric')
    return len(rows)


def execute(plan_path, expected_sha256, output):
    # Reserve before reading/hashing the plan so an early binding failure has a receipt.
    # Existing output directories are never touched; the caller's stderr records collisions.
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    receipt = dict(schema_version=1, status='running', requested_plan=str(Path(plan_path).resolve()),
                   expected_plan_sha256=expected_sha256, output_directory=str(output), phases=[],
                   model_forward_processes_started=0, conversion_processes_started=0,
                   started_utc=datetime.now(timezone.utc).isoformat(), sources_unchanged=False)
    bindings, dynamic = [], []
    plan_binding = None
    plan = None
    try:
        save(output / 'started.json', dict(pid=os.getpid(), explicit_execute=True,
             requested_plan=receipt['requested_plan'], expected_plan_sha256=expected_sha256,
             started_utc=receipt['started_utc']))
        plan_binding = safe_record(plan_path)
        receipt['plan_before'] = plan_binding
        require(plan_binding.get('sha256') == expected_sha256, 'execution plan hash mismatch or unreadable plan')
        plan = json.loads(Path(plan_path).read_text())
        require(plan.get('status') == 'ready_requires_root_execution_decision', 'plan is not prepared')
        require(str(output) == plan['output_directory'], 'output path differs from frozen plan')
        bindings = plan['bindings']
        receipt['input_bindings_before'] = snapshot(bindings)
        require(receipt['input_bindings_before'] == bindings, 'bound input changed before execution')
        require(record(__file__) == plan['controller'], 'controller differs from frozen execution plan')
        require(not Path(plan['converted_model_path']).exists(), 'converted model path already exists')
        environment = {key: value for key, value in os.environ.items() if not key.startswith('NT_')}
        environment.update(plan['environment'])
        receipt['environment_overrides'] = plan['environment']
        converted = None
        validation_binding = None
        for index, phase in enumerate(plan['phases']):
            result = dict(name=phase['name'], kind=phase['kind'], command=phase['command'],
                          status='failed', exit_code=None)
            receipt['phases'].append(result)
            expected = [*bindings, *dynamic]
            try:
                result['input_bindings_before'] = snapshot(expected)
                require(result['input_bindings_before'] == expected, 'bound input changed before phase')
                if phase['kind'] in ('model_forward', 'metric_comparison'):
                    require(converted is not None and validation_binding is not None,
                            'validated exact F32 weights required before forwards/comparisons')
                    require(record(plan['validation_receipt']) == validation_binding,
                            'conversion validation changed')
                if phase['kind'] == 'metric_comparison':
                    result['comparison_dump_checks'] = [verify_dump(path, phase['ids']['path'])
                                                        for path in phase['comparison_dumps']]
                print(json.dumps(dict(phase='starting', name=phase['name'])), flush=True)
                result.update(run_phase(phase['command'], plan['working_directory'], environment,
                                        phase['stdout'], phase['stderr'], phase['outputs']))
                if result.get('pid') is not None:
                    if phase['kind'] == 'model_forward':
                        receipt['model_forward_processes_started'] += 1
                    if phase['kind'] == 'conversion':
                        receipt['conversion_processes_started'] += 1
                require(result['status'] == 'completed', 'phase failed; partial evidence retained')
                if phase['kind'] == 'conversion':
                    converted = record(plan['converted_model_path'])
                    require(converted['bytes'] == 2526617472, 'converted model byte extent differs')
                    dynamic.append(converted)
                    receipt['converted_model'] = converted
                    result['converted_model'] = converted
                elif phase['kind'] == 'independent_validation':
                    validation_binding = validate_conversion_receipt(plan, converted)
                    dynamic.extend([validation_binding, record(plan['native_validation_rows']),
                                    record(plan['native_validation_stderr'])])
                    receipt['validation_receipt'] = validation_binding
                    result['validation_receipt'] = validation_binding
                elif phase['kind'] == 'model_forward':
                    result['dump_validation'] = verify_dump(phase['outputs'][0], phase['ids']['path'])
                    dynamic.append(record(phase['outputs'][0]))
                    result['model'] = converted
                elif phase['kind'] == 'metric_comparison':
                    result['metric_captures'] = validate_metrics(phase['stdout'])
            except BaseException as error:
                result.update(status='failed', controller_failure_type=type(error).__name__,
                              controller_failure=str(error))
            finally:
                result['input_bindings_after'] = snapshot(expected)
                result['sources_unchanged'] = result['input_bindings_after'] == expected
                result['dynamic_bindings_after'] = snapshot(dynamic)
                result['dynamic_unchanged'] = result['dynamic_bindings_after'] == dynamic
                if not result['sources_unchanged'] or not result['dynamic_unchanged']:
                    result.update(status='failed', postcheck_failure='bound inputs changed after phase')
                if 'artifacts' not in result:
                    result['artifacts'] = artifacts([phase['stdout'], phase['stderr'], *phase['outputs']])
                save(output / (str(index).zfill(2) + '-' + phase['name'] + '-receipt.json'), result)
            require(result['status'] == 'completed', 'alignment phase failed; partial evidence retained')
            print(json.dumps(dict(phase='completed', name=phase['name'])), flush=True)
        require(receipt['model_forward_processes_started'] == 4
                and receipt['conversion_processes_started'] == 1, 'unexpected execution count')
        receipt['status'] = 'completed'
    except BaseException as error:
        receipt.update(status='failed', failure_type=type(error).__name__, failure=str(error))
    finally:
        receipt['plan_after'] = safe_record(plan_path)
        receipt['input_bindings_after'] = snapshot(bindings)
        receipt['dynamic_bindings_after'] = snapshot(dynamic)
        receipt['sources_unchanged'] = bool(bindings) and receipt['input_bindings_after'] == bindings
        receipt['dynamic_unchanged'] = receipt['dynamic_bindings_after'] == dynamic
        receipt['plan_unchanged'] = plan_binding is not None and receipt['plan_after'] == plan_binding
        if not receipt['sources_unchanged'] or not receipt['dynamic_unchanged'] or not receipt['plan_unchanged']:
            receipt.update(status='failed', final_binding_failure='actual before/after bindings retained')
        receipt['completed_utc'] = datetime.now(timezone.utc).isoformat()
        receipt['artifacts'] = [safe_record(path) for path in sorted(output.rglob('*')) if path.is_file()]
        save(output / 'receipt.json', receipt)
    print(json.dumps(dict(status=receipt['status'], receipt=str(output / 'receipt.json'))), flush=True)
    return 0 if receipt['status'] == 'completed' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    require(args.execute, 'no conversion or forwards without explicit --execute')
    return execute(args.plan, args.plan_sha256, args.output_dir)


if __name__ == '__main__':
    raise SystemExit(main())
