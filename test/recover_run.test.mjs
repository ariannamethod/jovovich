import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

const fixture = String.raw`
import hashlib,importlib.util,json,sys,tempfile,subprocess,os
from pathlib import Path
spec=importlib.util.spec_from_file_location('recover_run','training/cloud/recover_run.py')
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
scenario=sys.argv[1]
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp);repo=root/'jovovich';state=root/'order-test-host';out=root/'output'
    def write(p,raw):p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);return p
    source=root/'source'
    for name in ('recover_run.py','recover_host.sh'):
        write(source/('training/cloud/'+name),Path('training/cloud/'+name).read_bytes())
    write(repo/'training/durable_archive.py',b'# fixture archive source\n')
    def git(directory,*args):
        return subprocess.check_output(['git','-C',str(directory),*args],stderr=subprocess.DEVNULL).decode().strip()
    def commit(directory):
        git(directory,'init');git(directory,'add','.')
        git(directory,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture')
        return git(directory,'rev-parse','HEAD')
    retained=commit(repo);revision=commit(source)
    host_source=source/'training/cloud/recover_host.sh'
    plan={'schema_version':1,'run_id':'order-test-after','arm':'after','argv':['a','b','c','d','100'],
          'remote':{'repo':'ataeff/jovovich','private':True,'prefix':'experiments/explanation-order'}}
    plan_raw=json.dumps(plan).encode()
    prefix='experiments/explanation-order/order-test-after'
    remote={};previous=None
    def entry(name,raw):
        digest=hashlib.sha256(raw).hexdigest()
        path=prefix+'/objects/'+digest;remote[path]=raw
        return dict(name=name,size=len(raw),sha256=digest,
                    git_blob_sha1=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),object=path)
    for sequence in range(11):
        unit='intent' if sequence==0 else 'update-%03d'%(sequence-1)
        entries=[entry('plan.json',plan_raw)] if sequence==0 else [entry('_units/'+unit+'.metrics.jsonl',b'metric')]
        manifest=dict(schema='jovovich.durable-unit.v1',run_id='order-test-after',sequence=sequence,unit_id=unit,
                      previous_manifest=previous,parent_revision='a'*40,files=entries)
        raw=(json.dumps(manifest,sort_keys=True,separators=(',',':'),ensure_ascii=True)+'\n').encode()
        remote[prefix+'/units/%06d-%s.json'%(sequence,unit)]=raw
        previous=hashlib.sha256(raw).hexdigest()
    receipt=dict(schema='jovovich.durable-receipt.v1',run_id='order-test-after',prefix=prefix,revision='a'*40,
                 sequence=10,unit_id='update-009',manifest_sha256=previous,files=entries,verified_remote_bytes=True,reused=False)
    downloads=[]
    class Transport:
        def inventory(self,rev,pref):
            assert rev=='a'*40 and pref==prefix
            result={name:{'size':len(raw)} for name,raw in remote.items()}
            if scenario=='remote_oversized':result[prefix+'/units/000000-intent.json']['size']=1000001
            return result
        def download(self,name,rev,destination):
            assert rev=='a'*40
            downloads.append(name)
            # No weight or metric payload is needed for manifest/plan validation.
            assert '/units/' in name or name==prefix+'/objects/'+hashlib.sha256(plan_raw).hexdigest()
            if scenario=='remote_unavailable':raise RuntimeError('fixture-known-secret')
            Path(destination).write_bytes(remote[name])
    write(state/'state.json',b'{"phase":"child-failed","child_exit_code":1}')
    write(state/'child.log',b'closed log hf_THISISAPRIVATECREDENTIAL fixture-known-secret\n')
    write(state/'hf-token',b'NEVER_READ_OLD_TOKEN')
    write(state/'env',b'NEVER_READ_ENV')
    job=repo/'models/order-test-job';after=repo/'models/order-test-after'
    write(job/'after.stderr',b'training launch failed\n')
    write(after/'stderr.log',b'native log\n')
    write(after/'metrics.jsonl',b'{"update":9}\n')
    write(after/'failure.json',b'{"error_type":"TrainingError","return_code":-9}')
    write(after/'plan.json',plan_raw)
    if scenario=='receipt_wrong_run':receipt['run_id']='different-after'
    if scenario=='receipt_wrong_unit':receipt['unit_id']='update-008'
    if scenario=='receipt_wrong_sequence':receipt['sequence']=9
    if scenario=='receipt_wrong_schema':receipt['schema']='unknown'
    if scenario=='receipt_wrong_revision':receipt['revision']='main'
    if scenario=='receipt_wrong_manifest':receipt['manifest_sha256']='f'*64
    if scenario=='receipt_wrong_files':receipt['files'][0]['size']=999
    if scenario=='receipt_wrong_plan':
        different=dict(plan,arm='before')
        write(after/'plan.json',json.dumps(different).encode())
    if scenario=='remote_plan_mismatch':
        different=dict(plan,argv=['a','b','c','d','99'])
        write(after/'plan.json',json.dumps(different).encode())
    if scenario=='remote_chain_mismatch':
        name=prefix+'/units/000010-update-009.json'
        broken=json.loads(remote[name]);broken['previous_manifest']='f'*64
        remote[name]=(json.dumps(broken,sort_keys=True,separators=(',',':'))+'\n').encode()
    write(after/'_units/update-009.ack.json',json.dumps(receipt).encode())
    if scenario=='receipt_renamed':
        (after/'_units/update-009.ack.json').rename(after/'_units/update-999.ack.json')
    if scenario=='source_wrong_revision':revision='b'*40
    if scenario=='source_helper_changed':
        write(source/'training/cloud/recover_run.py',b'# changed helper\n')
        h.__file__=str(source/'training/cloud/recover_run.py')
    if scenario=='source_host_changed':write(host_source,b'# changed host\n')
    if scenario=='source_archive_changed':write(repo/'training/durable_archive.py',b'# changed module\n')
    write(after/'adapter.epoch0.gate.lora',b'NEVER_READ_WEIGHTS')
    write(after/'_units/hf-token.ack.json',b'NEVER_READ_CREDENTIAL')
    files={p:p.read_bytes() for p in root.rglob('*') if p.is_file() and '.git' not in p.parts}
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
        h.MAX_BYTES=32768
        write(after/'stdout.jsonl',b'x'*32769);files[after/'stdout.jsonl']=(after/'stdout.jsonl').read_bytes()
    if scenario=='git_env_isolation':
        os.environ.update(GIT_DIR=str(source/'.git'),GIT_WORK_TREE=str(source),GIT_OBJECT_DIRECTORY=str(source/'.git/objects'),
                          GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='core.bare',GIT_CONFIG_VALUE_0='true')
    try:
        result=h.recover(archive,repo=repo,state_dir=state,run_prefix='order-test',
                         output=out,run_id='order-test-incident01',secrets=('fixture-known-secret',),
                         source_repo=source,source_revision=revision,host_source=host_source,receipt_transport=None if scenario=='verification_not_requested' else Transport())
    except RuntimeError:
        assert scenario in ('archive_failure','unsafe_output','existing_output','root_symlink') or scenario.startswith('source_')
        assert not (out/'completion.ack.json').exists()
        if scenario=='archive_failure':assert [name for name,_ in archive.calls]==['intent','evidence-000']
        else:assert archive.calls==[]
    else:
        assert scenario not in ('archive_failure','unsafe_output','existing_output','root_symlink') and not scenario.startswith('source_')
        assert result['archive_status']=='verified' and archive.calls[-1][0]=='completion'
        rejected=scenario in ('receipt_wrong_run','receipt_wrong_unit','receipt_wrong_sequence','receipt_wrong_schema',
                              'receipt_wrong_revision','receipt_wrong_plan','receipt_renamed')
        failed=scenario in ('receipt_wrong_manifest','receipt_wrong_files','remote_plan_mismatch','remote_chain_mismatch','remote_unavailable','remote_oversized')
        assert 'latest_local_verified_update_ack' not in result
        assert result['latest_manifest_bound_local_update_ack']==(None if rejected or failed or scenario=='verification_not_requested' else 9),result
        assert result['local_update_receipts_rejected']==int(rejected)
        assert result['receipt_verification']['status']==('no_valid_local_receipt' if rejected else 'failed' if failed else 'not_requested' if scenario=='verification_not_requested' else 'manifest_and_plan_verified')
        if rejected:assert not downloads
        intent=json.loads((out/'intent.json').read_text())
        bindings=intent['source_bindings']
        assert bindings['recover_run.py']['revision']==revision
        assert bindings['recover_host.sh']['revision']==revision
        assert bindings['durable_archive.py']['revision']==retained
        for name,binding in bindings.items():
            assert hashlib.sha256((out/name).read_bytes()).hexdigest()==binding['sha256']
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
for (const scenario of ['success', 'partial', 'symlink', 'large', 'archive_failure', 'unsafe_output', 'existing_output', 'root_symlink',
  'receipt_wrong_run', 'receipt_wrong_unit', 'receipt_wrong_sequence', 'receipt_wrong_schema',
  'receipt_wrong_revision', 'receipt_wrong_manifest', 'receipt_wrong_files', 'receipt_wrong_plan',
  'receipt_renamed', 'remote_plan_mismatch', 'remote_chain_mismatch', 'remote_unavailable', 'remote_oversized', 'verification_not_requested',
  'source_wrong_revision', 'source_helper_changed', 'source_host_changed', 'source_archive_changed', 'git_env_isolation']) {
  test(`incident recovery: ${scenario}`, () => {
    const r = spawnSync('python3', ['-c', fixture, scenario], { encoding: 'utf8', timeout: 15000 });
    assert.equal(r.status, 0, r.stderr || r.stdout || String(r.error));
  });
}


test('incident recovery: missing promisor source object never triggers a fetch', () => {
  const script = String.raw`
import importlib.util,subprocess,tempfile
from pathlib import Path
spec=importlib.util.spec_from_file_location('recover_run','training/cloud/recover_run.py')
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);repo=root/'repo';repo.mkdir();marker=root/'fetch-attempted';helper=root/'fetch-marker'
    helper.write_text('#!/bin/sh\ntouch '+str(marker)+'\nexit 1\n');helper.chmod(0o700)
    def git(*args):return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.DEVNULL).decode().strip()
    git('init');(repo/'source').write_text('source bytes');git('add','source')
    git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture')
    blob=git('rev-parse','HEAD:source');(repo/'.git/objects'/blob[:2]/blob[2:]).unlink()
    git('config','remote.origin.url','ext::'+str(helper));git('config','remote.origin.promisor','true')
    git('config','protocol.ext.allow','always')
    try:h.git_bytes(repo,'show','HEAD:source')
    except RuntimeError:pass
    else:raise AssertionError('missing source object was accepted')
    assert not marker.exists(),'verification triggered lazy fetch'
    # Establish that the fixture really would lazy-fetch under ordinary Git.
    subprocess.run(['git','-C',str(repo),'show','HEAD:source'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    assert marker.exists(),'promisor fixture did not exercise lazy fetch'
`;
  const r = spawnSync('python3', ['-c', script], { encoding: 'utf8', timeout: 15000 });
  assert.equal(r.status, 0, r.stderr || r.stdout || String(r.error));
});

test('incident recovery: main archives the exact source bundle it executed', () => {
  const script = String.raw`
import importlib.util,json,sys,tempfile
from pathlib import Path
spec=importlib.util.spec_from_file_location('recover_run','training/cloud/recover_run.py')
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);repo=root/'repo';repo.mkdir();token=root/'credential';token.write_text('fixture token')
    module=b'class HFTransport:\n def __init__(self,*a): pass\nclass DurableArchive:\n def __init__(self,*a,**k): pass\n'
    bundle=({'durable_archive.py':{'revision':'a'*40}}, {'durable_archive.py':module})
    calls=[]
    def bind(*args):
        calls.append(args)
        if len(calls)>1:raise AssertionError('source rebound after execution')
        return bundle
    def recover(archive,**kwargs):
        assert kwargs['_source_bundle'] is bundle
        assert archive.__class__.__init__.__code__.co_filename==str(repo/'training/durable_archive.py')
        assert kwargs['_source_bundle'][1]['durable_archive.py']==module
        return {'status':'fixture-complete'}
    h.bind_sources=bind;h.recover=recover
    h.layout=lambda *a:(repo,{'state':root/'state'},root/'output')
    sys.argv=['recover_run.py','--repo',str(repo),'--state-dir',str(root/'state'),'--run-prefix','order-test',
              '--run-id','order-test-incident01','--output',str(root/'output'),'--token-file',str(token),
              '--source-repo',str(root/'source'),'--source-revision','a'*40,'--host-source',str(root/'host.sh')]
    assert h.main()==0
    assert len(calls)==1
`;
  const r = spawnSync('python3', ['-c', script], { encoding: 'utf8', timeout: 15000 });
  assert.equal(r.status, 0, r.stderr || r.stdout || String(r.error));
});
