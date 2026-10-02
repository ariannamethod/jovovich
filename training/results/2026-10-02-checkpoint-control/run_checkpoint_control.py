"""Export/parity gates then exactly two natural-generation workers; no optimization."""
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import hashlib, json, os, subprocess, time

OUT=Path('training/results/2026-10-02-checkpoint-control')
BIN=Path('models/checkpoint-control')
PLAN_PATH=OUT/'protocol.json'
PLAN_RAW=PLAN_PATH.read_bytes()
PLAN=json.loads(PLAN_RAW)
PLAN_SHA=hashlib.sha256(PLAN_RAW).hexdigest()

def now(): return datetime.now(timezone.utc).isoformat()
def binding(path):
    path=Path(path);before=path.stat();h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    after=path.stat()
    assert (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),str(path)
    return dict(path=str(path),bytes=after.st_size,sha256=h.hexdigest())
def write(path,record):
    with Path(path).open('x') as stream:
        json.dump(record,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
def check_inputs():
    assert PLAN_PATH.read_bytes()==PLAN_RAW
    for b in PLAN['bindings']:assert binding(b['path'])==b,b['path']
def phase(name,argv):
    stem=OUT/name;env={k:v for k,v in os.environ.items() if not k.startswith('NT_')}
    env.update(PLAN['native_environment'])
    record=dict(name=name,argv=[str(x) for x in argv],started_at=now(),protocol_sha256=PLAN_SHA,
        native_environment=PLAN['native_environment'],stdout=str(stem)+'.stdout.txt',stderr=str(stem)+'.stderr.txt')
    write(str(stem)+'.intent.json',record)
    started=time.monotonic();process=None
    try:
        with open(record['stdout'],'xb') as out,open(record['stderr'],'xb') as err:
            process=subprocess.Popen(record['argv'],stdout=out,stderr=err,env=env)
            write(str(stem)+'.started.json',dict(pid=process.pid,started_at=now(),protocol_sha256=PLAN_SHA))
            print(json.dumps(dict(phase=name,pid=process.pid,status='started')),flush=True)
            record['exit_code']=process.wait()
        assert record['exit_code']==0,f'{name}: exit {record["exit_code"]}'
    except BaseException as error:
        if process is not None and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        record.update(error=dict(type=type(error).__name__,message=str(error)),exit_code=None if process is None else process.returncode)
        raise
    finally:
        record.update(finished_at=now(),elapsed_seconds=time.monotonic()-started)
        record['logs']=[binding(p) for p in [record['stdout'],record['stderr']] if Path(p).exists()]
        write(str(stem)+'.receipt.json',record)
    return record

write(OUT/'run.intent.json',dict(started_at=now(),pid=os.getpid(),protocol_sha256=PLAN_SHA))
try:
    check_inputs()
    base='models/base-qwen.gguf'
    recovered='models/recovered-matched/matched-review'
    merged25=recovered+'-selected.gguf'
    merged100=str(BIN/'update100.gguf')
    phases=[]
    for update in [25,100]:
        phases.append(phase(f'export-{update}',[BIN/'export-saved',base,f'{recovered}.epoch{update}',BIN/f'update{update}']))
        # Native snapshot must preserve the exact loaded adapter serialization.
        for part in ['gate','up','down']:
            assert binding(f'{recovered}.epoch{update}.{part}.lora')['sha256']==binding(BIN/f'update{update}.{part}.lora')['sha256']
    phases.append(phase('merge-100',[BIN/'merge-mlp',base,BIN/'update100',merged100]))
    for update,model in [(25,merged25),(100,merged100)]:
        phases.append(phase(f'audit-{update}',['python3','training/results/2026-09-29-verdict-balance/verify_verdict_export.py',
            base,model,BIN/f'update{update}',OUT/f'export-audit-{update}.json']))
        audit=json.loads((OUT/f'export-audit-{update}.json').read_text())
        assert audit['valid'] and audit['unchanged']==288 and audit['adapted']==3 and audit['metadata_equal']
        assert audit['model']['bytes']==714116992
        phases.append(phase(f'parity-{update}',[BIN/'probe-mlp',base,model,f'{recovered}.bin',f'{recovered}.epoch{update}','0','1','2']))
        rows=[json.loads(line) for line in (OUT/f'parity-{update}.stdout.txt').read_text().splitlines()]
        assert [r['row'] for r in rows]==[0,1,2] and all(r['pass'] for r in rows)
    check_inputs()
    models=dict(update25=binding(merged25),update100=binding(merged100))
    write(OUT/'verified-models.json',dict(status='export_and_parity_passed',created_at=now(),protocol_sha256=PLAN_SHA,
        models=models,checks=[binding(OUT/f'{kind}-{update}.{suffix}') for update in [25,100]
            for kind,suffix in [('export-audit','json'),('parity','stdout.txt'),('parity','receipt.json')]],
        generated_weights=[binding(p) for p in sorted(BIN.glob('update*'))]))
    # The two arms have the same case order and decoding. There is no output-based selection.
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures=[executor.submit(phase,f'generation-{arm}',['node',OUT/'evaluate_checkpoints.mjs',arm]) for arm in PLAN['arms']]
        results=[];errors=[]
        for future in futures:
            try:results.append(future.result())
            except Exception as error:errors.append(str(error))
        if errors:raise RuntimeError('; '.join(errors))
    check_inputs()
    assert all(binding(b['path'])==b for b in models.values())
    arms={}
    for arm in PLAN['arms']:
        rows=[json.loads(line) for line in (OUT/arm/'responses.jsonl').read_text().splitlines()]
        assert len(rows)==24 and [r['name'] for r in rows]==PLAN['case_order']
        arms[arm]=rows
    assert all(a['original_prompt_ids']==b['original_prompt_ids'] and a['prompt_sha256']==b['prompt_sha256']
        for a,b in zip(arms['update25'],arms['update100']))
    write(OUT/'complete.json',dict(status='complete',finished_at=now(),protocol_sha256=PLAN_SHA,
        models=models,cases_per_arm=24,total_responses=48,prompt_ids_identical_between_arms=True,
        frozen_inputs_unchanged=True,arm_receipts=[binding(OUT/arm/'complete.json') for arm in PLAN['arms']],
        semantic_judgments='pending independent review; generation controller makes no semantic judgments'))
    print(json.dumps(dict(status='complete',total_responses=48,protocol_sha256=PLAN_SHA)),flush=True)
except BaseException as error:
    write(OUT/'run.failure.json',dict(finished_at=now(),protocol_sha256=PLAN_SHA,error=dict(type=type(error).__name__,message=str(error))))
    raise
