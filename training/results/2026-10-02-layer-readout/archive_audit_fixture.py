"""Independent offline fault injection for the layer evidence packer."""
from pathlib import Path
import tempfile, json, hashlib, importlib.util, sys, contextlib, io, tarfile, struct
SOURCE = Path(__file__).resolve().with_name('archive_run.py')

def fp(path):
    b = path.read_bytes()
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()}

def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, sort_keys=True) + '\n')

def setup(base):
    run = base / 'run'
    out = base / 'public'
    run.mkdir()
    out.mkdir()
    (out / 'prepared').mkdir()
    source = run / 'input.bin'
    source.write_bytes(b'input fixture')
    (out / 'prepared/input.bin').write_bytes(source.read_bytes())
    plan = {'run_id': 'synthetic-layer-audit', 'remote': {'prefix': 'experiments/layers', 'repo_id': 'ataeff/jovovich', 'private': True}, 'bindings': [], 'bootstrap': [{'path': 'input.bin', **fp(source)}], 'phases': []}
    for i in range(104):
        stem = f'_units/row{i:03d}'
        outputs = [f'row{i:03d}.bin']
        if i == 103:
            outputs += ['layers-summary.json', 'layers-table.tsv']
        unit = {'id': f'row{i:03d}', 'outputs': outputs, 'argv': ['fixture', str(i)], 'check_argv': ['verify', str(i)]}
        plan['phases'].append(unit)
        for p in outputs:
            (run / p).write_bytes(struct.pack('<4f', i, 0.5, -0.5, 1.0) if p.endswith('.bin') else b'{}\n')
        intent = {'unit': unit, 'sequence': 1 + 2 * i}
        write(run / (stem + '.intent.json'), intent)
        names = set(outputs + [stem + x for x in ['.intent.json', '.stdout', '.stderr', '.check.stdout', '.check.stderr']])
        for p in names:
            if not (run / p).exists():
                (run / p).write_bytes(b'fixture log\n')
        result = {'unit': unit, 'sequence': 2 + 2 * i, 'status': 'completed', 'return_code': 0, 'commands': [{'argv': unit['argv'], 'return_code': 0}, {'argv': unit['check_argv'], 'return_code': 0}], 'artifacts': [{'path': p, **fp(run / p)} for p in sorted(names)], 'started_utc': '2026-10-02T00:00:00+00:00', 'finished_utc': '2026-10-02T00:00:01+00:00'}
        write(run / (stem + '.result.json'), result)
    write(run / 'plan.json', plan)
    (out / 'launch-plan.json').write_bytes((run / 'plan.json').read_bytes())
    completion = {'status': 'completed', 'failed_bindings': [], 'run_id': plan['run_id'], 'sequence': 209}
    write(run / 'completion.json', completion)
    remote = {'schema': 'jovovich.durable-receipt.v1', 'verified_remote_bytes': True, 'run_id': plan['run_id'], 'unit_id': 'completion', 'sequence': 209, 'prefix': plan['remote']['prefix'] + '/' + plan['run_id'], 'revision': 'a' * 40, 'manifest_sha256': 'b' * 64, 'files': [{'name': 'completion.json', 'size': fp(run / 'completion.json')['bytes'], 'sha256': fp(run / 'completion.json')['sha256']}]}
    receipt = base / 'remote.json'
    write(receipt, {**completion, 'remote_verification': remote})
    return (run, out, receipt)

def run_case(name):
    with tempfile.TemporaryDirectory(prefix='jovovich-packer-audit-') as tmp:
        base = Path(tmp)
        root, out, receipt = setup(base)
        spec = importlib.util.spec_from_file_location('archive_builder', SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.HERE = out
        if name == 'bound-snapshot':
            (root / 'snapshot').mkdir()
            snap = root / 'snapshot/collector'
            snap.write_bytes(b'\x7fELFfixture-not-a-real-binary')
            plan = json.loads((root / 'plan.json').read_text())
            plan['bindings'] = [{'path': 'build/collector', 'snapshot': 'snapshot/collector', **fp(snap)}]
            write(root / 'plan.json', plan)
            (out / 'launch-plan.json').write_bytes((root / 'plan.json').read_bytes())
        if name == 'model-as-data':
            payload = root / 'row050.bin'
            payload.write_bytes(b'GGUFfixture-not-a-real-model')
            result_path = root / '_units/row050.result.json'
            result = json.loads(result_path.read_text())
            for item in result['artifacts']:
                if item['path'] == 'row050.bin':
                    item.update(fp(payload))
            write(result_path, result)
        if name == 'corrupt-artifact':
            (root / 'row050.bin').write_bytes(b'CORRUPT')
        if name == 'corrupt-remote':
            r = json.loads(receipt.read_text())
            r['remote_verification']['files'][0]['sha256'] = '0' * 64
            write(receipt, r)
        if name == 'remote-sequence':
            r = json.loads(receipt.read_text())
            r['remote_verification']['sequence'] = 208
            write(receipt, r)
        if name == 'unplanned-data':
            (root / 'extra-layer.f32').write_bytes(b'important numeric data')
        if name == 'snapshot-extra':
            (root / 'snapshot').mkdir()
            (root / 'snapshot/unplanned-layer.f32').write_bytes(b'important numeric data')
        if name == 'late-summary-mutation':
            verify = module.verify

            def changed(path, expected):
                verify(path, expected)
                if path == receipt:
                    (root / 'layers-summary.json').write_bytes(b'{"silently_changed":true}\n')
            module.verify = changed
        sys.argv = [str(SOURCE), '--run-dir', str(root), '--remote-receipt', str(receipt)]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                module.main()
            passed = True
            error = None
        except Exception as exc:
            passed = False
            error = type(exc).__name__ + ': ' + str(exc)
        result = {'case': name, 'accepted': passed, 'error': error}
        if passed:
            with tarfile.open(out / 'raw-evidence.tar.gz') as tar:
                manifest = json.loads((out / 'raw-evidence-manifest.json').read_text())
                result['members'] = len(tar.getmembers())
                result['numeric_preserved'] = tar.extractfile('row050.bin').read() == (root / 'row050.bin').read_bytes()
                result['summary_copy_matches_archive'] = tar.extractfile('layers-summary.json').read() == (out / 'layers-summary.json').read_bytes()
        return result
before = fp(SOURCE)
cases = [run_case(name) for name in ['normal', 'bound-snapshot', 'model-as-data', 'corrupt-artifact', 'corrupt-remote', 'remote-sequence', 'unplanned-data', 'snapshot-extra', 'late-summary-mutation']]
accepted = {'normal', 'bound-snapshot', 'late-summary-mutation'}
for case in cases:
    if case['accepted'] != (case['case'] in accepted):
        raise RuntimeError('unexpected archive gate result: ' + case['case'])
    if case['accepted'] and (not (case['numeric_preserved'] and case['summary_copy_matches_archive'])):
        raise RuntimeError('archive payload or direct copy differs: ' + case['case'])
if fp(SOURCE) != before:
    raise RuntimeError('builder source changed during audit')
print(json.dumps({'schema_version': 1, 'status': 'passed', 'scope': 'Isolated synthetic 104-phase archive preservation audit. No model run files or remote repositories accessed.', 'builder': before, 'fixture': fp(Path(__file__)), 'cases': cases}, indent=2))
