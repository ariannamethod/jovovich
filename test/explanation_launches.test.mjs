import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

const setup = `
import copy,hashlib,json,sys,tempfile
from pathlib import Path
sys.path.insert(0,'training/explanations')
import prepare_launches as h
work=tempfile.TemporaryDirectory();repo=Path(work.name);before=repo/'before';(before/'_units').mkdir(parents=True)
def dump(p,v):p.write_text(json.dumps(v))
def bind(p):return {'path':str(p.relative_to(repo)),'bytes':p.stat().st_size,'sha256':h.sha(p)}
for name in ('trainer','model','before-data','before-pairs','after-data','after-pairs','source'):(repo/name).write_text(name)
(repo/'trainer').write_text('#!/usr/bin/env python3\\nimport json\\nprint(json.dumps({\"schema\":\"jovovich.archive-ack.v1\",\"startup_ack\":True,\"initial_snapshot\":True,\"per_update_ack\":True}))\\n');(repo/'trainer').chmod(0o755)
common=[bind(repo/name) for name in ('trainer','model','source')]
p={'schema_version':1,'arm':'before','run_id':'fixture-before','argv':['trainer','model','before-data','@RUN@/adapter','100','0.0001','40','25','joint','before-pairs'],'environment':{'NT_NO_I8':'1'},'bindings':common+[bind(repo/'before-data'),bind(repo/'before-pairs')],'scientific_plan_sha256':'f'*64}
a=copy.deepcopy(p);a.update(schema_version='awaiting-before-initialization',arm='after',run_id='fixture-after');a['argv'][2]='after-data';a['argv'][9]='after-pairs';a['bindings']=common+[bind(repo/'after-data'),bind(repo/'after-pairs')]
template=repo/'template.json';dump(template,a)
def receipts(plan=p,initial=None):
 dump(before/'plan.json',plan)
 complete={'status':'native_completed','return_code':0,'acknowledged_updates':100,'initial_lora_sha256':initial or {k:'a'*64 for k in ('gate','up','down')},'bindings':plan['bindings'],'plan_sha256':h.sha(before/'plan.json')}
 dump(before/'completion.json',complete)
 receipt={'verified_remote_bytes':True,'unit_id':'completion','revision':'b'*40,'manifest_sha256':'c'*64,'files':[{'name':'completion.json','size':(before/'completion.json').stat().st_size,'sha256':h.sha(before/'completion.json')}]}
 dump(before/'_units/completion.ack.json',{'status':'completed','archive_status':'verified','remote_verification':receipt})
receipts()
validate=h.validate_plan;h.validate_plan=lambda plan:validate(plan,repo)
def run(name='resolved.json'):h.bind_after(template,before,repo/name)
def rejected(fragment):
 try:run()
 except (ValueError,RuntimeError) as error:assert fragment in str(error),str(error)
 else:raise AssertionError('accepted invalid handoff')
`;

function python(code) {
  const r = spawnSync('python3', ['-c', setup + code], { encoding: 'utf8', timeout: 15000 });
  assert.equal(r.status, 0, r.stderr || r.stdout || String(r.error));
}

test('after launch binds nested verified completion and initialization hashes', () => {
  python(`
run();result=json.loads((repo/'resolved.json').read_text())
assert result['schema_version']==1 and result['expected_initial_lora_sha256']=={k:'a'*64 for k in ('gate','up','down')}
assert result['before_completion']['revision']=='b'*40
try:validate(a,repo)
except RuntimeError:pass
else:raise AssertionError('unresolved after template runnable')
`);
});

test('after launch rejects changed receipts, local plans and invalid adapter hashes', () => {
  python(`
(before/'completion.json').write_text('{}');rejected('receipt mismatch')
receipts();changed=copy.deepcopy(p);changed['argv'][5]='0.001';dump(before/'plan.json',changed);rejected('archived evidence')
receipts(initial={'gate':'bad','up':'a'*64,'down':'a'*64});rejected('initial adapter')
`);
});

test('after launch rejects differing training settings and missing shared bindings', () => {
  python(`
changed=copy.deepcopy(p);changed['argv'][5]='0.001';receipts(changed);rejected('training settings')
changed=copy.deepcopy(p);changed['environment']['NT_QMV_THREADS']='8';receipts(changed);rejected('training settings')
changed=copy.deepcopy(p);changed['bindings']=[b for b in changed['bindings'] if b['path']!='source'];receipts(changed);rejected('shared arm bindings')
`);
});

test('fresh launches freeze evaluation inputs and detect imported diagnostic scorer mutation', () => {
  python(`
import shutil
original_root=h.ROOT
contract=json.loads((original_root/'training/explanations/evaluation_plan.json').read_text())
scientific=json.loads((original_root/'training/explanations/plan.json').read_text())
common=['build/jovovich-train-mlp','models/base-qwen.gguf','training/explanations/plan.json',
 'training/explanations/reasons.json','training/sft_review_v5.jsonl']
common+=['training/explanations/'+name+'.py' for name in (
 'prepare_launches','run_training','execute_evaluation','verify_native','build_corpora',
 'collect_generation','score_generation','continue_experiment')]
common+=['deps/notorch/'+name for name in (
 'notorch.c','notorch.h','notorch_simd.h','gguf.c','gguf.h','harness/runtime.c','harness/runtime.h',
 'harness/arch_llama.c','harness/arch.h','harness/arch_models.h','examples/bpe.c','examples/bpe.h')]
for name in set(common+contract['required_pretraining_launch_bindings']):
 path=repo/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture '+name)
trainer=repo/'build/jovovich-train-mlp';shutil.copyfile(repo/'trainer',trainer);trainer.chmod(0o755)
base=repo/'models/base-qwen.gguf';scientific['training']['base_expected_sha256']=h.sha(base)
contract['resolution']['SHARED_BASE_UPDATE0_SHA256']=h.sha(base)
dump(repo/'training/explanations/plan.json',scientific)
dump(repo/'training/explanations/evaluation_plan.json',contract)
preflight=repo/'models/custom-native-repeat';preflight.mkdir()
dump(preflight/'verification.json',dict(status='pass',native_chatml_comparisons=304,identical_prompt_and_content_rows=52))
recorded=[]
for path in (base,repo/'training/explanations/verify_native.py'):
 recorded.append(dict(path=str(path),bytes=path.stat().st_size,sha256=h.sha(path)))
dump(preflight/'bindings.json',dict(files=recorded))
for arm in ('before','after'):
 for ext in ('.bin','.pairs.bin'):(preflight/(arm+ext)).write_text(arm+ext)
h.ROOT=repo
launches=repo/'models/repeat-launches';h.prepare(base,preflight,launches,'fresh-repeat')
resolved_path=launches/'evaluation-plan.json';resolved=json.loads(resolved_path.read_text())
resolved_name=str(resolved_path.relative_to(repo))
assert resolved_name in resolved['required_pretraining_launch_bindings']
plans={arm:json.loads((launches/('before.launch.json' if arm=='before' else 'after.template.json')).read_text()) for arm in ('before','after')}
for arm,plan in plans.items():
 bound={item['path']:item for item in plan['bindings']}
 assert plan['evaluation_plan']==resolved_name and bound[resolved_name]['sha256']==h.sha(resolved_path)
 for dependency in ('training/score_decisions.py','training/score_training.py','training/prepare.py'):
  assert bound[dependency]['sha256']==h.sha(repo/dependency)
 for item in resolved['required_pretraining_launch_bindings']:
  if item.endswith(('/before.bin','/before.pairs.bin','/after.bin','/after.pairs.bin')):continue
  assert item in bound,item
 assert not any('2026-10-03-explanation-order-run/native/' in name for name in bound)
 parity=next(x for x in resolved['exports'] if x['arm']==arm)['steps'][-1]
 assert parity['argv'][3]==str((preflight/(arm+'.bin')).relative_to(repo))==plan['argv'][2]
def complete(plan,directory):
 (directory/'_units').mkdir(parents=True,exist_ok=True)
 dump(directory/'plan.json',plan)
 final=[];saved=[]
 for part in ('gate','up','down'):
  for ext in ('f32','lora'):
   for epoch,entries in (('',final),('.epoch100',saved)):
    name='adapter'+epoch+'.'+part+'.'+ext;path=directory/name;path.write_text(part+ext)
    entries.append(dict(name=name,size=path.stat().st_size,sha256=h.sha(path)))
 core=dict(status='native_completed',archive_status='requires_verified_receipt',return_code=0,
  acknowledged_updates=100,initial_lora_sha256={part:'a'*64 for part in ('gate','up','down')},
  bindings=plan['bindings'],plan_sha256=h.sha(directory/'plan.json'))
 for name,data in (('completion.json',core),('metrics.jsonl',{})):
  dump(directory/name,data);final.append(dict(name=name,size=(directory/name).stat().st_size,sha256=h.sha(directory/name)))
 receipt=dict(run_id=plan['run_id'],prefix='experiments/explanation-order/'+plan['run_id'],
  verified_remote_bytes=True,unit_id='completion',revision='b'*40,manifest_sha256='c'*64,sequence=103,files=final)
 dump(directory/'_units/completion.ack.json',dict(core,status='completed',archive_status='verified',remote_verification=receipt))
 dump(directory/'_units/update-100.ack.json',dict(receipt,unit_id='update-100',sequence=102,files=saved))
before_run=repo/'models/before-completed';after_run=repo/'models/after-completed'
complete(plans['before'],before_run)
h.bind_after(launches/'after.template.json',before_run,launches/'after.launch.json')
complete(json.loads((launches/'after.launch.json').read_text()),after_run)
import execute_evaluation as evaluator
evaluator.ROOT=repo;evaluator.__file__=str(repo/'training/explanations/execute_evaluation.py')
args=(resolved_path,before_run,after_run,repo/'models/evaluation','fresh-evaluation')
prepared=evaluator.prepare(*args)
assert any(item['path']=='training/score_training.py' for item in prepared['bindings'])
# A same-length import edit must fail before either diagnostic command runs.
dependency=repo/'training/score_training.py';original=dependency.read_bytes()
dependency.write_bytes(bytes([original[0]^1])+original[1:])
try:evaluator.prepare(*args)
except RuntimeError as error:assert 'binding mismatch' in str(error),str(error)
else:raise AssertionError('modified imported scorer accepted')
assert dependency.stat().st_size==len(original)
sys.path.insert(0,'test')
from durable_archive_fixture import FakeTransport
from durable_archive import DurableArchive
transport=FakeTransport();archive=DurableArchive(transport,'fresh-evaluation')
calls=[];evaluator.run_command=lambda *a,**kw:calls.append(a) or 0
try:evaluator.execute(archive,prepared,args[3])
except RuntimeError as error:assert 'binding mismatch' in str(error),str(error)
else:raise AssertionError('changed imported scorer reached diagnostics')
assert not calls and transport.commits==0
dependency.write_bytes(original)
shutil.rmtree(args[3])
# Internally consistent historical receipts still lack the newly required import.
for directory in (before_run,after_run):
 old=json.loads((directory/'plan.json').read_text())
 old['bindings']=[item for item in old['bindings'] if item['path']!='training/score_training.py']
 complete(old,directory)
try:evaluator.prepare(*args)
except RuntimeError as error:assert 'diagnostic scorer and its imports' in str(error),str(error)
else:raise AssertionError('unbound historical scorer accepted')
`);
});
