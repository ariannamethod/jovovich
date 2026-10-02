"""Focused no-model checks for the newly introduced execution boundary."""
import importlib.util
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('controller', HERE / 'run_alignment.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def main():
    root = HERE / 'execution-boundary-fixtures'
    root.mkdir(exist_ok=False)
    checks = []
    dummy = root / 'bound.txt'
    dummy.write_text('original source bytes\n')

    def plan(name):
        folder = root / name
        p = dict(status='ready_requires_root_execution_decision', output_directory=str(folder),
                 bindings=[c.record(dummy), c.record(HERE / 'run_alignment.py')],
                 controller=c.record(HERE / 'run_alignment.py'), phases=[],
                 converted_model_path=str(folder / 'model-not-created.gguf'),
                 working_directory=str(root), environment={})
        path = root / (name + '-plan.json')
        return path, folder, p

    path, out, p = plan('wrong-plan-hash')
    c.save(path, p)
    c.require(c.execute(path, '0' * 64, out) == 1, 'wrong plan hash unexpectedly ran')
    r = json.loads((out / 'receipt.json').read_text())
    c.require(r['status'] == 'failed' and r['phases'] == [] and r['plan_before'] == c.record(path),
              'early plan hash failure not retained')
    checks.append(dict(name='early_plan_hash_failure', receipt=c.record(out / 'receipt.json')))

    path, out, p = plan('missing-bound-source')
    p['bindings'].append(dict(path=str(root / 'absent.txt'), bytes=1, sha256='0' * 64))
    c.save(path, p)
    c.require(c.execute(path, c.record(path)['sha256'], out) == 1, 'missing source unexpectedly ran')
    r = json.loads((out / 'receipt.json').read_text())
    c.require(r['phases'] == [] and 'hash_error' in r['input_bindings_before'][-1]
              and 'hash_error' in r['input_bindings_after'][-1], 'missing source evidence lost')
    checks.append(dict(name='early_missing_source', receipt=c.record(out / 'receipt.json')))

    for name, command, expected in (
            ('launch-failure', [str(root / 'missing-executable')], None),
            ('child-nonzero', [sys.executable, '-E', '-c',
             "from pathlib import Path; print('partial stream',flush=True); Path('partial.txt').write_text('retained'); raise SystemExit(7)"], 7)):
        folder = root / name
        folder.mkdir()
        result = c.run_phase(command, str(folder), dict(os.environ), folder / 'stdout',
                             folder / 'stderr', [folder / 'partial.txt'])
        c.require(result['status'] == 'failed' and result['exit_code'] == expected, 'child failure classification wrong')
        c.require((folder / 'stdout').is_file() and (folder / 'stderr').is_file(), 'child failure logs missing')
        if expected == 7:
            c.require((folder / 'partial.txt').read_text() == 'retained'
                      and result['peak_rss_kib'] is not None, 'partial output/resources not retained')
        c.save(folder / 'receipt.json', result)
        checks.append(dict(name=name, receipt=c.record(folder / 'receipt.json')))

    path, out, p = plan('source-changed-after-child')
    p['phases'] = [dict(name='mutate-synthetic-source', kind='synthetic_fixture',
        command=[sys.executable, '-E', '-c', 'from pathlib import Path; Path('+repr(str(dummy))+').write_text("changed source bytes\\n")'],
        stdout=str(out / 'child.stdout'), stderr=str(out / 'child.stderr'), outputs=[])]
    c.save(path, p)
    before = c.record(dummy)
    c.require(c.execute(path, c.record(path)['sha256'], out) == 1, 'changed source accepted')
    r = json.loads((out / 'receipt.json').read_text())
    phase = r['phases'][0]
    c.require(phase['exit_code'] == 0 and phase['status'] == 'failed' and phase['sources_unchanged'] is False
              and phase['input_bindings_before'][0] == before and phase['input_bindings_after'][0] == c.record(dummy)
              and phase['input_bindings_after'][0] != before, 'actual changed posthash was not retained')
    checks.append(dict(name='actual_changed_posthash', receipt=c.record(out / 'receipt.json')))
    c.save(HERE / 'execution-boundary-check.json', dict(status='passed', model_forwards=0, model_conversions=0,
        controller=c.record(HERE / 'run_alignment.py'), checker=c.record(__file__), checks=checks))
    print(json.dumps(dict(status='passed', checks=len(checks), model_forwards=0, model_conversions=0)))


if __name__ == '__main__':
    main()
