import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

const setup = `
import copy,hashlib,json,sys,tempfile
from pathlib import Path
sys.path[:0]=['training/explanations','test']
import continue_experiment as c
from durable_archive_fixture import FakeTransport
from durable_archive import DurableArchive
work=tempfile.TemporaryDirectory();root=Path(work.name);c.ROOT=root
before=root/'before';before.mkdir();state=root/'state';state.mkdir()
def dump(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
def completion(directory,evaluation=False):
 dump(directory/'plan.json',{'arm':'fixture','run_id':'fixture'})
 body={'plan_sha256':c.digest(directory/'plan.json'),'return_code':0,'acknowledged_updates':100,'semantic_audit':'pending','generation_calls':228}
 dump(directory/'completion.json',body)
 ack={**body,'status':'native_evaluation_completed' if evaluation else 'completed','archive_status':'verified','remote_verification':{'verified_remote_bytes':True,'unit_id':'completion','run_id':'fixture','revision':'a'*40,'files':[{'name':'completion.json','sha256':c.digest(directory/'completion.json'),'size':(directory/'completion.json').stat().st_size}]}}
 dump(directory/('_receipts/completion.json' if evaluation else '_units/completion.ack.json'),ack)
 return ack
expected={'pid':17,'start_ticks':42,'cmdline_sha256':'a'*64}
def rejected(fn):
 try:fn()
 except RuntimeError:return
 raise AssertionError('accepted invalid continuation')
`;

function python(code) {
  const r = spawnSync('python3', ['-c', setup + code], { encoding: 'utf8', timeout: 15000 });
  assert.equal(r.status, 0, r.stderr || r.stdout || String(r.error));
}

test('continuation waits for verified completion and the exact original parent exit', () => {
  python(`
ack=completion(before);identities=iter([expected,expected,None]);slept=[]
result=c.wait_before(before,expected,identity_fn=lambda _:next(identities),sleep=lambda seconds:slept.append(seconds))
assert result==ack and slept==[5,5]
# Same PID with another kernel start time means original parent has exited.
assert c.wait_before(before,expected,identity_fn=lambda _:{**expected,'start_ticks':99},sleep=lambda _:None)==ack
`);
});

test('continuation handles partial JSON while parent lives and fails without a completed receipt', () => {
  python(`
(before/'_units').mkdir();(before/'_units/completion.ack.json').write_text('{')
states=iter([expected,None])
def finish(_):completion(before)
assert c.wait_before(before,expected,identity_fn=lambda _:next(states),sleep=finish)['status']=='completed'
(before/'_units/completion.ack.json').write_text('{')
rejected(lambda:c.wait_before(before,expected,identity_fn=lambda _:None,sleep=lambda _:None))
completion(before);(before/'failure.json').write_text('{}')
rejected(lambda:c.wait_before(before,expected,identity_fn=lambda _:expected,sleep=lambda _:None))
`);
});

test('continuation times out and rejects corrupt verified receipt bytes', () => {
  python(`
clock=iter([0,2]);rejected(lambda:c.wait_before(before,expected,identity_fn=lambda _:expected,clock=lambda:next(clock),timeout_seconds=1))
completion(before);(before/'completion.json').write_text('{}');rejected(lambda:c.verified_completion(before))
`);
});

test('continuation runs one writer at a time with bound after launch and pending semantic audit', () => {
  python(`
source=root/'source.py';source.write_text('frozen')
plan={'before_run':'before','after_run':'after','evaluation_run':'evaluation','evaluation_plan':'evaluation.json','after_template':'after.template.json','evaluation_run_id':'eval','python':sys.executable,'before_process':expected,'poll_seconds':5,'wait_timeout_seconds':60,'run_id':'supervisor','remote':{'repo':'private','prefix':'experiments/test'},'bindings':[{'path':'source.py','bytes':source.stat().st_size,'sha256':c.digest(source)}]}
dump(state/'plan.json',plan)
steps=[];transport=FakeTransport();archive=DurableArchive(transport,'supervisor')
def wait(*a,**kw):steps.append('wait');assert transport.commits==0;return {}
def factory():assert steps==['wait'];return archive
def run(argv,output,name):
 steps.append(name)
 for suffix in ('stdout','stderr'):(output/(name+'.'+suffix)).write_text('closed')
 if name=='bind-after':dump(output/'after.launch.json',{'expected_initial_lora_sha256':{'gate':'a'*64}})
 if name=='after-training':
  assert argv[argv.index('--plan')+1]==str(state/'after.launch.json')
  assert argv[argv.index('--run-dir')+1]==str(root/'after')
  completion(root/'after')
 if name=='native-evaluation':
  assert (root/'after/_units/completion.ack.json').exists()
  completion(root/'evaluation',True)
result=c.execute(plan,state,root/'unused-secret-file',wait=wait,archive_factory=factory,run=run)
assert steps==['wait','bind-after','after-training','native-evaluation']
assert result['status']=='native_evaluation_done' and result['semantic_audit']=='pending'
assert transport.commits==8
assert 'unused-secret-file' not in (state/'plan.json').read_text()
`);
});

test('continuation does not initialize archive on before failure or restart failed phases', () => {
  python(`
plan={'before_run':'before','after_run':'after','evaluation_run':'evaluation','evaluation_plan':'evaluation.json','after_template':'after.template.json','evaluation_run_id':'eval','python':sys.executable,'before_process':expected,'poll_seconds':5,'wait_timeout_seconds':60,'run_id':'supervisor','bindings':[]}
dump(state/'plan.json',plan)
def fail(*a,**kw):raise RuntimeError('stopped')
def forbidden():raise AssertionError('archive opened while before still active')
rejected(lambda:c.execute(plan,state,root/'unused',wait=fail,archive_factory=forbidden))
assert (state/'failure.json').exists()
`);
});

test('continuation CLI validates required named arguments without reading credentials', () => {
  python(`
args=c.parser().parse_args(['--before-run','before','--before-pid','17','--after-template','template','--after-run','after','--evaluation-plan','evaluation-plan','--evaluation-run','evaluation','--state-dir','state','--token-file','unread','--run-id','chain','--evaluation-run-id','eval'])
assert args.before_pid==17 and args.poll_seconds==5 and args.token_file==Path('unread')
`);
});

test('continuation stops between phases when the bound after plan or supervisor bytes change', () => {
  python(`
for scenario in ('after-plan','supervisor-bytes'):
 out=root/scenario;out.mkdir()
 plan={'before_run':'before','after_run':'after','evaluation_run':'evaluation','evaluation_plan':'evaluation.json','after_template':'after.template.json','evaluation_run_id':'eval','python':sys.executable,'before_process':expected,'poll_seconds':5,'wait_timeout_seconds':60,'run_id':scenario,'bindings':[]}
 dump(out/'plan.json',plan)
 transport=FakeTransport();archive=DurableArchive(transport,scenario);original=archive.sync_unit;calls=[]
 def sync(name,files,*,sequence):
  receipt=original(name,files,sequence=sequence)
  if scenario=='supervisor-bytes' and name=='continuation-intent':(out/'plan.json').write_text((out/'plan.json').read_text()+' ')
  if scenario=='after-plan' and name=='bind-after-result':dump(out/'after.launch.json',{'changed':'argv'})
  return receipt
 archive.sync_unit=sync
 def run(argv,dest,name):
  calls.append(name)
  for suffix in ('stdout','stderr'):(dest/(name+'.'+suffix)).write_text('closed')
  dump(dest/'after.launch.json',{'bound':'initialization'})
 rejected(lambda:c.execute(plan,out,root/'unused',wait=lambda *a,**kw:{},archive_factory=lambda:archive,run=run))
 assert calls==(['bind-after'] if scenario=='after-plan' else [])
 assert (out/'failure.ack.json').exists()
`);
});

test('continuation archives closed child failures and preserves pending archive units', () => {
  python(`
for scenario in ('child-failure','archive-failure'):
 out=root/scenario;out.mkdir()
 plan={'before_run':'before','after_run':'after','evaluation_run':'evaluation','evaluation_plan':'evaluation.json','after_template':'after.template.json','evaluation_run_id':'eval','python':sys.executable,'before_process':expected,'poll_seconds':5,'wait_timeout_seconds':60,'run_id':scenario,'bindings':[]}
 dump(out/'plan.json',plan)
 transport=FakeTransport();archive=DurableArchive(transport,scenario);calls=[]
 if scenario=='archive-failure':transport.head_fault=RuntimeError('remote unavailable')
 def run(argv,dest,name):
  calls.append(name)
  for suffix in ('stdout','stderr'):(dest/(name+'.'+suffix)).write_text('closed failure evidence')
  raise RuntimeError('child exit nonzero')
 rejected(lambda:c.execute(plan,out,root/'unused',wait=lambda *a,**kw:{},archive_factory=lambda:archive,run=run))
 assert calls==(['bind-after'] if scenario=='child-failure' else [])
 if scenario=='child-failure':
  receipt=json.loads((out/'failure.ack.json').read_text())
  assert receipt['verified_remote_bytes'] and {'bind-after.stdout','bind-after.stderr','failure.json'} <= {f['name'] for f in receipt['files']}
 else:
  assert archive._pending==(0,'continuation-intent') and not (out/'failure.ack.json').exists()
`);
});

test('continuation rejects completion identity and acknowledgement field substitution', () => {
  python(`
completion(before);p=before/'_units/completion.ack.json';ack=json.loads(p.read_text());ack['remote_verification']['run_id']='other';dump(p,ack);rejected(lambda:c.verified_completion(before))
completion(before);ack=json.loads(p.read_text());ack['acknowledged_updates']=99;dump(p,ack);rejected(lambda:c.verified_completion(before))
`);
});
