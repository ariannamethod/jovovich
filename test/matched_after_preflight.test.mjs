import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

const fixture = String.raw`
import copy,hashlib,json,sys,tempfile
from pathlib import Path
sys.path[:0]=['training/after_recovery','training','test']
import preflight as h
from durable_archive import DurableArchive, _name
from durable_archive_fixture import FakeTransport
class CanonicalTransport(FakeTransport):
 def inventory(self,revision,prefix):
  _name(prefix)  # The real HF transport rejects trailing-slash/noncanonical paths.
  return {name:item for name,item in super().inventory(revision,prefix).items()
          if name.startswith(prefix+'/')}
workspace=tempfile.TemporaryDirectory();root=Path(workspace.name);repo=root/'repo';repo.mkdir()
def write(path,value):
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(value if isinstance(value,str) else json.dumps(value,indent=2)+'\n')
 return path
def bind(name):return h.binding(repo/name,name)
for name in ('models/base-qwen.gguf','build/jovovich-train-mlp','build/jovovich-infer',
 'training/train_mlp.c','training/durable_archive.py','training/explanations/run_training.py',
 'deps/notorch/notorch.c','training/quote/PREREGISTRATION.md','models/original/evaluation-plan.json'):
 write(repo/name,'fixture '+name)
for arm in ('before','after'):
 for suffix in ('.bin','.pairs.bin'):write(repo/('models/original/'+arm+suffix),arm+suffix)
write(repo/'training/explanations/plan.json',{'training':{'base_expected_sha256':h.digest(repo/'models/base-qwen.gguf')}})
shared=[bind(n) for n in ('models/base-qwen.gguf','build/jovovich-train-mlp','build/jovovich-infer',
 'training/train_mlp.c','training/durable_archive.py','training/explanations/run_training.py',
 'deps/notorch/notorch.c','training/quote/PREREGISTRATION.md','models/original/evaluation-plan.json',
 'training/explanations/plan.json')]
initial={p:hashlib.sha256(('initial '+p).encode()).hexdigest() for p in ('gate','up','down')}
transport=CanonicalTransport();plans={};plan_hashes={};completed=None
for arm in ('before','after'):
 run=root/arm;run.mkdir()
 data='models/original/'+arm+'.bin';pairs='models/original/'+arm+'.pairs.bin'
 plan=dict(schema_version=1,run_id='original-'+arm,arm=arm,
  argv=['build/jovovich-train-mlp','models/base-qwen.gguf',data,'@RUN@/adapter','100','0.0001','40','25','joint',pairs],
  environment={'NT_NO_I8':'1','NT_QMV_THREADS':'2','NT_ATTN_THREADS':'2','NT_SIMD_THREADS':'2'},
  remote={'repo':'ataeff/jovovich','private':True,'prefix':'experiments/explanation-order'},ack_timeout_ms=900000,
  scientific_plan_sha256=h.digest(repo/'training/explanations/plan.json'),
  evaluation_plan='models/original/evaluation-plan.json',bindings=shared+[bind(data),bind(pairs)])
 if arm=='after':plan.update(expected_initial_lora_sha256=initial,before_completion={'completion_sha256':completed})
 write(run/'plan.json',plan);plans[arm]=plan;plan_hashes[arm]=h.digest(run/'plan.json')
 files={'plan.json':run/'plan.json'}
 for item in plan['bindings']:
  if item['path']!=plan['argv'][1]:files['inputs/'+item['path']]=repo/item['path']
 archive=DurableArchive(transport,plan['run_id'],plan['remote']['prefix'])
 archive.sync_unit('intent',files,sequence=0)
 for step in range(101 if arm=='before' else 10):
  metric=write(run/('_units/update-%03d.metrics.jsonl'%step),{'update':step})
  files={str(metric.relative_to(run)):metric}
  if step==0:
   init=write(run/'_units/initialization.json',{'initial_lora_sha256':initial})
   files['_units/initialization.json']=init
   for part in initial:
    name='adapter.epoch00.'+part+'.lora';files[name]=write(run/name,'initial '+part)
  archive.sync_unit('update-%03d'%step,files,sequence=step+1)
 if arm=='before':
  completion=write(run/'completion.json',dict(return_code=0,acknowledged_updates=100,
   plan_sha256=plan_hashes[arm],bindings=plan['bindings'],initial_lora_sha256=initial))
  completed=h.digest(completion);archive.sync_unit('completion',{'completion.json':completion},sequence=102)
inputs=dict(schema='jovovich.matched-after-inputs.v1',original_source_commit='a'*40,
 archive_revision=transport.current,archive=plans['before']['remote'],before_run_id='original-before',
 failed_after_run_id='original-after',before_plan_sha256=plan_hashes['before'],before_completion_sha256=completed,
 failed_after_plan_sha256=plan_hashes['after'],expected_initial_lora_sha256=initial,
 new_after_run_id='fresh-after',new_evaluation_run_id='fresh-eval')
inputs_path=write(repo/'training/after_recovery/inputs.json',inputs)
out=root/'preflight';commit_count=transport.commits
def run():return h.prepare(lambda:transport,out,repo=repo,inputs_path=inputs_path)
def reject(fragment):
 try:run()
 except (RuntimeError,ValueError) as error:
  assert fragment in str(error),str(error)
 else:raise AssertionError('unsafe preflight accepted')
 assert not (out/'preflight.json').exists()
 assert transport.commits==commit_count
`;

function python(code) {
  const result = spawnSync('python3', ['-c', fixture + code], { encoding: 'utf8', timeout: 30000 });
  assert.equal(result.status, 0, result.stderr || result.stdout || String(result.error));
}

test('matched-after preflight verifies both remote histories and freezes a non-runnable contract', () => {
  python(String.raw`
result=run()
assert result['runnable'] is False and result['recovered_units']=={'before':103,'failed-after':11}
assert result['native_calls']==result['training_updates']==result['remote_writes']==0
assert transport.commits==commit_count
assert result['after_argv']==plans['after']['argv'] and result['expected_initial_lora_sha256']==initial
assert result['original_bindings']==plans['after']['bindings'] and result['fixed_endpoint']==100
assert result['infrastructure_changes']==[] and result['remaining_blockers']
assert all(revision==inputs['archive_revision'] for revision,_ in transport.downloads[-20:])
sys.path.insert(0,'training/explanations');from run_training import validate_plan
try:validate_plan(result,repo)
except RuntimeError:pass
else:raise AssertionError('preflight report admitted as runnable training plan')
`);
});

test('only the two explicit infrastructure files may change, with old and candidate hashes recorded', () => {
  python(String.raw`
for path in h.INFRASTRUCTURE:write(repo/path,'reviewed infrastructure fix '+path)
result=run();changes=result['infrastructure_changes']
assert {c['path'] for c in changes}==h.INFRASTRUCTURE
assert all(c['original']['sha256']!=c['candidate']['sha256'] for c in changes)
assert result['frozen_evaluation_binding']==bind('models/original/evaluation-plan.json')
`);
});

test('trainer-source drift and parent-directory symlinks are rejected before an admission report', () => {
  python(String.raw`
write(repo/'training/train_mlp.c','changed numerical source');reject('non-infrastructure source changed')
`);
  python(String.raw`
external=root/'external';(repo/'deps/notorch').rename(external);(repo/'deps/notorch').symlink_to(external,target_is_directory=True)
reject('symlink')
`);
});

test('committed plan and initialization pins reject altered pair provenance', () => {
  python(String.raw`
inputs['failed_after_plan_sha256']='f'*64;write(inputs_path,inputs);reject('committed pin')
`);
  python(String.raw`
inputs['expected_initial_lora_sha256']['gate']='e'*64;write(inputs_path,inputs);reject('initial adapters')
`);
});

test('new attempt namespaces must be unused and old attempt identities cannot be reused', () => {
  python(String.raw`
transport.revisions[transport.current]['experiments/explanation-order/fresh-after/occupied']=b'previous evidence'
reject('already has evidence')
`);
  python(String.raw`
inputs['new_after_run_id']=inputs['failed_after_run_id'];write(inputs_path,inputs);reject('distinct safe')
`);
});

test('namespace inventory uses canonical paths and keeps sibling runs distinct', () => {
  python(String.raw`
transport.revisions[transport.current]['experiments/explanation-order/fresh-after-other/occupied']=b'sibling evidence'
result=run()
assert result['runnable'] is False and transport.commits==commit_count
`);
});

test('remote corruption and an incomplete pinned sequence fail closed', () => {
  python(String.raw`
target=next(name for name,data in transport.revisions[transport.current].items() if data==b'initial gate')
transport.download_fault=lambda name,data:b'corrupted' if name==target else data
reject('integrity mismatch')
`);
  python(String.raw`
inputs['archive_revision']=format(transport.commits-1,'040x');write(inputs_path,inputs)
reject('pinned attempt sequence')
`);
});

test('existing evidence output is never overwritten', () => {
  python(String.raw`
out.mkdir();write(out/'sentinel','preserve me');reject('must be new')
assert (out/'sentinel').read_text()=='preserve me'
`);
});
