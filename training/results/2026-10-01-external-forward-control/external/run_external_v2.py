"""Execute only an explicitly invoked, separately frozen external diagnostic."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
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
        for block in iter(lambda: stream.read(8*1024*1024), b''):
            digest.update(block)
    after = path.stat()
    require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns) ==
            (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns), 'file changed during hashing')
    return dict(path=str(path),bytes=after.st_size,sha256=digest.hexdigest())


def save(path,value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value,indent=2)+'\n')


def verify(bindings):
    actual = [record(item['path']) for item in bindings]
    require(actual == bindings, 'bound external input changed')
    return actual


def verify_dump(path, ids_path):
    expected_ids=[int(token) for token in Path(ids_path).read_text().split()]
    require(len(expected_ids)==447,'fixed case ID count changed')
    require(Path(path).stat().st_size==1217308,'unexpected full-logit dump size')
    with Path(path).open('rb') as stream:
        require(struct.unpack('<6I',stream.read(24))==(0x324c564a,2,1,151936,2,447),'unexpected dump header')
        require(list(struct.unpack('<447I',stream.read(447*4)))==expected_ids,'dump IDs differ from fixed case')
        for position in (444,447):
            require(struct.unpack('<I',stream.read(4))[0]==position,'dump capture index changed')
            stream.seek(151936*4,1)
        require(not stream.read(1),'trailing dump bytes')
    return dict(expected_ids=record(ids_path),captured_prefix_lengths=[444,447],embedded_ids_match_fixed_case=True)


def run_phase(command, cwd, environment, stdout_path, stderr_path, outputs):
    """Always preserve logs and partial outputs, including failures before exec."""
    started = time.monotonic()
    result = dict(command=command, started_utc=datetime.now(timezone.utc).isoformat(),
                  status='failed',exit_code=None,peak_rss_kib=None,user_seconds=None,system_seconds=None)
    child = None
    usage = None
    def collect(blocking=True):
        nonlocal usage
        pid,status,measured = os.wait4(child.pid,0 if blocking else os.WNOHANG)
        if pid:
            usage=measured
            child.returncode=os.waitstatus_to_exitcode(status)
        return bool(pid)
    try:
        with Path(stdout_path).open('x') as out, Path(stderr_path).open('x') as err:
            child=subprocess.Popen(command,cwd=cwd,env=environment,stdout=out,stderr=err)
            result['pid']=child.pid
            collect()
            result['exit_code']=child.returncode
            require(child.returncode==0,'native child failed')
        result['status']='completed'
    except BaseException as error:
        result.update(failure_type=type(error).__name__,failure=str(error))
        if child is not None and child.returncode is None:
            try:
                os.kill(child.pid,signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline=time.monotonic()+10
            while not collect(False):
                if time.monotonic()>=deadline:
                    os.kill(child.pid,signal.SIGKILL)
                    collect()
                    break
                time.sleep(0.05)
        if child is not None:
            result['exit_code']=child.returncode
    finally:
        result['elapsed_seconds']=time.monotonic()-started
        if usage is not None:
            result.update(peak_rss_kib=usage.ru_maxrss,user_seconds=usage.ru_utime,system_seconds=usage.ru_stime)
        paths=[Path(stdout_path),Path(stderr_path),*map(Path,outputs)]
        result['artifacts']=[record(path) for path in paths if path.is_file()]
        result['missing_outputs']=[str(path) for path in paths if not path.is_file()]
        if result['status']=='completed' and result['missing_outputs']:
            result.update(status='failed',failure_type='ValueError',failure='successful child omitted required output')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--plan-sha256',required=True)
    parser.add_argument('--execute',action='store_true',help='root explicitly requested actual model execution')
    args=parser.parse_args()
    require(args.execute,'no forwards without explicit --execute')
    plan_binding=record(args.plan)
    require(plan_binding['sha256']==args.plan_sha256,'execution plan hash mismatch')
    plan=json.loads(args.plan.read_text())
    require(plan['status']=='ready_requires_root_execution_decision','execution plan is not prepared')
    require(record(__file__)==plan['controller'],'controller differs from frozen execution plan')
    verify(plan['bindings'])
    output=Path(plan['output_directory'])
    output.mkdir(parents=True,exist_ok=False)
    receipt=dict(schema_version=1,status='running',plan=plan_binding,phases=[],model_forward_processes_started=0,
                 started_utc=datetime.now(timezone.utc).isoformat(),sources_unchanged=False)
    save(output/'started.json',dict(plan=plan_binding,pid=os.getpid(),started_utc=receipt['started_utc'],explicit_execute=True))
    environment={key:value for key,value in os.environ.items() if not key.startswith('NT_')}
    environment.update(plan['environment'])
    receipt['environment_overrides']=plan['environment']
    try:
        for index,phase in enumerate(plan['phases']):
            before=verify(plan['bindings'])
            print(json.dumps(dict(phase='starting',name=phase['name'])),flush=True)
            result=run_phase(phase['command'],plan['working_directory'],environment,
                             phase['stdout'],phase['stderr'],phase['outputs'])
            result.update(name=phase['name'],kind=phase['kind'],input_bindings_before=before)
            receipt['phases'].append(result)
            if phase['kind']=='model_forward' and result.get('pid') is not None:
                receipt['model_forward_processes_started']+=1
            try:
                after=[]
                for item in plan['bindings']:
                    try:
                        after.append(record(item['path']))
                    except Exception as error:
                        after.append(dict(path=item['path'],hash_error_type=type(error).__name__,hash_error=str(error)))
                result['input_bindings_after']=after
                result['sources_unchanged']=after==plan['bindings']
                require(result['sources_unchanged'],'bound input changed after child execution')
                if result['status']=='completed' and phase['kind']=='model_forward':
                    result['dump_validation']=verify_dump(phase['outputs'][0],phase['ids']['path'])
                if result['status']=='completed' and phase['kind']=='metric_comparison':
                    lines=Path(phase['stdout']).read_text().splitlines()
                    metrics=[json.loads(line) for line in lines]
                    require(len(metrics)==2 and [row['prefix_tokens'] for row in metrics]==[444,447]
                            and all(row['vocabulary']==151936 for row in metrics),'incomplete metric captures')
                    result['metric_captures']=2
            except Exception as error:
                result.update(status='failed',postcheck_failure=str(error))
            save(output/(str(index).zfill(2)+'-'+phase['name']+'-receipt.json'),result)
            require(result['status']=='completed','external phase failed; partial evidence retained')
            print(json.dumps(dict(phase='completed',name=phase['name'])),flush=True)
        require(record(args.plan)==plan_binding,'execution plan changed')
        verify(plan['bindings'])
        receipt.update(status='completed',sources_unchanged=True)
    except BaseException as error:
        receipt.update(status='failed',failure_type=type(error).__name__,failure=str(error))
    finally:
        receipt['completed_utc']=datetime.now(timezone.utc).isoformat()
        receipt['artifacts']=[record(path) for path in sorted(output.iterdir()) if path.is_file()]
        save(output/'receipt.json',receipt)
    print(json.dumps(dict(status=receipt['status'],receipt=str(output/'receipt.json'))),flush=True)
    return 0 if receipt['status']=='completed' else 1


if __name__=='__main__':
    raise SystemExit(main())
