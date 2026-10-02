#!/usr/bin/env python3
"""Continue intact, closed local units through the unchanged frozen launcher."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def fingerprint(path):
    require(path.is_file() and not path.is_symlink(), 'expected regular file: ' + str(path))
    before = path.stat()
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(data)
    after = path.stat()
    require((before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'file changed while hashing')
    return {'bytes': after.st_size, 'sha256': h.hexdigest()}


def verify(path, binding):
    actual = fingerprint(path)
    require(actual == {k: binding[k] for k in ('bytes', 'sha256')}, 'file identity differs: ' + str(path))
    return actual


def local(root, name):
    relative = Path(name)
    require(relative.parts and not relative.is_absolute() and '..' not in relative.parts
            and str(relative) == name, 'invalid run artifact path')
    path = root / relative
    require(path.resolve().is_relative_to(root), 'run artifact escapes destination')
    return path


def preflight(root, repo_id, remote_prefix, completed):
    require(not (root / 'completion.json').exists(), 'run already has a completion record')
    plan_path = local(root, 'plan.json')
    plan = json.loads(plan_path.read_text())
    plan_binding = fingerprint(plan_path)
    verify(HERE / 'launch-plan.json', plan_binding)
    require(len(plan['phases']) == 104 and 0 < completed < len(plan['phases']), 'unexpected survey extent')
    # Verify executable Python before importing it; the launcher then checks all
    # original source, binary, model and prepared-input bindings itself.
    for name in ('training/layers/run_layers.py', 'training/durable_archive.py'):
        items = [b for b in plan['bindings'] if b['path'] == name]
        require(len(items) == 1, 'missing frozen launcher binding')
        verify(REPO / name, items[0])
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(REPO / 'training/layers'))
    import run_layers
    run_layers.validate_plan(plan)
    run_layers.validate_remote(plan, repo_id, remote_prefix)
    host = {'platform': platform.platform(), 'python': platform.python_version(),
            'compiler': subprocess.check_output(['cc', '--version'], text=True).splitlines()[0]}
    require(host == plan['host'], 'continuation host differs from the frozen host')
    expected = {'plan.json'}
    for item in plan['bootstrap']:
        verify(local(root, item['path']), item)
        expected.add(item['path'])
    for item in plan['bindings']:
        if item.get('snapshot'):
            verify(local(root, item['snapshot']), item)
            expected.add(item['snapshot'])
    phases = []
    for index, unit in enumerate(plan['phases'][:completed]):
        stem = '_units/' + unit['id']
        intent_name, result_name = stem + '.intent.json', stem + '.result.json'
        intent_path, result_path = local(root, intent_name), local(root, result_name)
        intent = json.loads(intent_path.read_text())
        result = json.loads(result_path.read_text())
        require(intent['unit'] == unit and result['unit'] == unit
                and intent['sequence'] == 1 + 2 * index and result['sequence'] == 2 + 2 * index
                and result['status'] == 'completed' and result['return_code'] == 0
                and result['started_utc'] == intent['started_utc'], 'closed phase identity or status differs')
        commands = [unit['argv']] + ([unit['check_argv']] if unit.get('check_argv') else [])
        require([c['argv'] for c in result['commands']] == commands
                and all(c['return_code'] == 0 for c in result['commands']), 'closed command sequence differs')
        artifacts = set(unit['outputs']) | {intent_name, unit.get('stdout', stem + '.stdout'),
                                           unit.get('stderr', stem + '.stderr')}
        if unit.get('check_argv'):
            artifacts.update({stem + '.check.stdout', stem + '.check.stderr'})
        require({a['path'] for a in result['artifacts']} == artifacts
                and len(result['artifacts']) == len(artifacts), 'closed artifact inventory differs')
        for item in result['artifacts']:
            verify(local(root, item['path']), item)
        expected.update(artifacts | {result_name})
        phases.append({'id': unit['id'], 'intent_sequence': intent['sequence'],
                       'result_sequence': result['sequence'], 'result': fingerprint(result_path)})
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if not p.is_dir() or p.is_symlink()}
    require(actual == expected, 'open intent, partial output, or unexpected local artifact exists')
    receipt = {'schema_version': 1, 'status': 'intact-closed-local-prefix-verified',
               'checked_utc': datetime.now(timezone.utc).isoformat(), 'run_id': plan['run_id'],
               'controller': {'path': Path(__file__).name, **fingerprint(Path(__file__))},
               'plan': plan_binding, 'closed_phases': phases, 'closed_phase_count': completed,
               'local_files_verified': len(expected), 'open_intents': 0,
               'next_phase': plan['phases'][completed]['id'], 'next_intent_sequence': 1 + 2 * completed,
               'continuation': 'Process interruption with intact local files; this is not a restoration from remote storage.',
               'execution': 'Unmodified frozen execute_plan starting at sequence 1 re-verifies each closed result through DurableArchive before launching pending work.',
               'host': {'frozen': plan['host'], 'current': host, 'exact_match': True},
               'remote': {'repo': repo_id, 'prefix': remote_prefix,
                          'preflight_remote_calls': 0, 'remote_synchronization_starts_after_this_receipt': True}}
    return plan, receipt, run_layers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('preflight', 'continue'))
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--completed', type=int, default=28)
    parser.add_argument('--hf-repo', default='ataeff/jovovich')
    parser.add_argument('--remote-prefix', default='experiments/layer-readout')
    parser.add_argument('--token-file', type=Path)
    args = parser.parse_args()
    require(not sys.flags.optimize and not os.environ.get('PYTHONOPTIMIZE'), 'optimized Python is unsupported')
    root, audit = args.run_dir.resolve(), args.audit.resolve()
    require(not audit.is_relative_to(root) and not audit.exists(), 'audit destination must be new and outside run directory')
    plan, receipt, launcher = preflight(root, args.hf_repo, args.remote_prefix, args.completed)
    with audit.open('x') as stream:
        json.dump(receipt, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    if args.mode == 'preflight':
        print(json.dumps(receipt))
        return
    sys.path.insert(0, str(REPO / 'training'))
    from durable_archive import DurableArchive, HFTransport
    token = args.token_file.read_text().strip() if args.token_file else os.environ.get('HF_TOKEN', '')
    archive = DurableArchive(HFTransport(args.hf_repo, token), plan['run_id'], prefix=args.remote_prefix)
    print(json.dumps(launcher.execute_plan(archive, plan, root, sequence=1)), flush=True)


if __name__ == '__main__':
    main()
