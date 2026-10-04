import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

const fixture = String.raw`
import hashlib,importlib.util,json,sys,tempfile
from pathlib import Path
spec=importlib.util.spec_from_file_location('recover_run','training/cloud/recover_run.py')
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
scenario=sys.argv[1]
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp);repo=root/'jovovich';state=root/'order-test-host';out=root/'output'
    def write(p,raw):p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);return p
    write(repo/'training/durable_archive.py',b'# fixture archive source\n')
    write(state/'state.json',b'{"phase":"child-failed","child_exit_code":1}')
    write(state/'child.log',b'closed log hf_THISISAPRIVATECREDENTIAL fixture-known-secret\n')
    write(state/'hf-token',b'NEVER_READ_OLD_TOKEN')
    write(state/'env',b'NEVER_READ_ENV')
    job=repo/'models/order-test-job';after=repo/'models/order-test-after'
    write(job/'after.stderr',b'training launch failed\n')
    write(after/'stderr.log',b'native log\n')
    write(after/'metrics.jsonl',b'{"update":9}\n')
    write(after/'failure.json',b'{"error_type":"TrainingError","return_code":-9}')
    write(after/'_units/update-009.ack.json',b'{"unit_id":"update-009","verified_remote_bytes":true}')
    write(after/'adapter.epoch0.gate.lora',b'NEVER_READ_WEIGHTS')
    write(after/'_units/hf-token.ack.json',b'NEVER_READ_CREDENTIAL')
    files={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    class Archive:
        def __init__(self):self.calls=[]
        def sync_unit(self,name,files,sequence):
            assert sequence==len(self.calls)
            self.calls.append((name,{k:Path(p).read_bytes() for k,p in files.items()}))
            if scenario=='archive_failure' and name=='evidence-000':raise RuntimeError('injected failure')
            return dict(verified_remote_bytes=True,unit_id=name,run_id='order-test-incident01',revision='a'*40)
    archive=Archive()
    original_snapshot=h.regular_snapshot
    def snapshot(path):
        assert not any(x in str(path) for x in ('hf-token','/env','adapter.'))
        return original_snapshot(path)
    h.regular_snapshot=snapshot
    if scenario=='partial':
        (after/'failure.json').unlink();files.pop(after/'failure.json')
        write(state/'exit.json',b'{"phase":')
        files[state/'exit.json']=(state/'exit.json').read_bytes()
    if scenario=='symlink':
        (job/'after.stderr').unlink();files.pop(job/'after.stderr')
        (job/'after.stderr').symlink_to(state/'hf-token')
    if scenario=='unsafe_output':out=after/'new'
    if scenario=='existing_output':out.mkdir()
    if scenario=='root_symlink':
        alias=root/'alias';alias.symlink_to(repo,target_is_directory=True);repo=alias
    if scenario=='large':
        h.MAX_BYTES=16384
        write(after/'stdout.jsonl',b'x'*16385);files[after/'stdout.jsonl']=(after/'stdout.jsonl').read_bytes()
    try:
        result=h.recover(archive,repo=repo,state_dir=state,run_prefix='order-test',
                         output=out,run_id='order-test-incident01',secrets=('fixture-known-secret',))
    except RuntimeError:
        assert scenario in ('archive_failure','unsafe_output','existing_output','root_symlink')
        assert not (out/'completion.ack.json').exists()
        if scenario=='archive_failure':assert [name for name,_ in archive.calls]==['intent','evidence-000']
        else:assert archive.calls==[]
    else:
        assert scenario not in ('archive_failure','unsafe_output','existing_output','root_symlink')
        assert result['archive_status']=='verified' and archive.calls[-1][0]=='completion'
        assert result['latest_local_verified_update_ack']==9
        assert result['after_failure_record_present']==(scenario!='partial')
        if scenario!='partial':assert result['trainer_return_code']==-9
        raw=b'\n'.join(data for _,fileset in archive.calls for data in fileset.values())
        for forbidden in (b'NEVER_READ_',b'hf_THISISAPRIVATECREDENTIAL',b'fixture-known-secret'):
            assert forbidden not in raw
        assert b'[REDACTED]' in raw
        assert (out/'recover_run.py').read_bytes()==Path('training/cloud/recover_run.py').read_bytes()
        assert not (out/'after/adapter.epoch0.gate.lora').exists()
        if scenario=='symlink':assert not (out/'job/after.stderr').exists()
        if scenario=='large':assert not (out/'after/stdout.jsonl').exists()
    for path,raw in files.items():assert path.read_bytes()==raw,'original evidence changed'
`;
for (const scenario of ['success', 'partial', 'symlink', 'large', 'archive_failure', 'unsafe_output', 'existing_output', 'root_symlink']) {
  test(`incident recovery: ${scenario}`, () => {
    const r = spawnSync('python3', ['-c', fixture, scenario], { encoding: 'utf8', timeout: 15000 });
    assert.equal(r.status, 0, r.stderr || r.stdout || String(r.error));
  });
}
