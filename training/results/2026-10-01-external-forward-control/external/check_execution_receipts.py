"""Focused no-model checks for launch/partial-file receipts and fixed input IDs."""
import importlib.util
import json
import os
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('external_controller',HERE/'run_external.py')
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def main():
    root=HERE/'controller-check'
    root.mkdir(exist_ok=False)
    results=[]
    for name in ('launch_failure','partial_failure','missing_output','stderr_open_failure'):
        case=root/name
        case.mkdir()
        artifact=case/'partial.dump'
        err=case/'stderr'
        if name=='launch_failure':
            command=[str(case/'nonexistent-command')]
        elif name=='partial_failure':
            command=[sys.executable,'-c',"from pathlib import Path; Path('partial.dump').write_bytes(b'partial'); raise SystemExit(7)"]
        elif name=='missing_output':
            command=[sys.executable,'-c','pass']
        else:
            command=[str(case/'nonexistent-command')]
            err=case/'missing-parent/stderr'
        result=runner.run_phase(command,case,os.environ.copy(),case/'stdout',err,[artifact])
        runner.require(result['status']=='failed',name+': failure accepted')
        runner.require(result['exit_code']==({'partial_failure':7,'missing_output':0}.get(name)),name+': incorrect child exit')
        expected_files=3 if name=='partial_failure' else 1 if name=='stderr_open_failure' else 2
        runner.require(len(result['artifacts'])==expected_files,name+': missing partial evidence')
        runner.require((result['peak_rss_kib'] is None)==(name in ('launch_failure','stderr_open_failure')),name+': incorrect resource presence')
        results.append(dict(name=name,receipt=result))
    good=runner.verify_dump(HERE/'synthetic-check/native.dump',HERE/'concern.ids.txt')
    rejected=False
    try:
        runner.verify_dump(HERE/'synthetic-check/native.dump',HERE/'clean.ids.txt')
    except ValueError as error:
        runner.require(str(error)=='dump IDs differ from fixed case','unexpected dump rejection')
        rejected=True
    runner.require(rejected,'same-engine ID agreement bypassed fixed-case check')
    receipt=dict(passed=True,model_forward_calls=0,controller=runner.record(HERE/'run_external.py'),helper=runner.record(__file__),
                 fixtures=results,dump_fixed_case_validation=good,wrong_case_rejected=True)
    runner.save(HERE/'controller-check.json',receipt)
    print(json.dumps(dict(passed=True,model_forward_calls=0,process_failure_cases=4,wrong_case_dump_rejected=True)))


if __name__=='__main__':
    main()
