import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));

// A fake repository, a before run archived through the real DurableArchive and recovered from it.
const FIXTURE = String.raw`
import hashlib,json,shutil,sys
from pathlib import Path
sys.path.insert(0,'training');sys.path.insert(0,'test')
from durable_archive import DurableArchive
from durable_archive_fixture import FakeTransport
root=Path(sys.argv[1]).resolve();variant=sys.argv[2];repo=root/'repo'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(name,text):
 p=repo/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);return p
def dump(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2)+'\n')
def bind(name,absolute=False):
 p=repo/name;return {'path':str(p) if absolute else name,'bytes':p.stat().st_size,'sha256':sha(p)}
trainer=write('build/jovovich-train-mlp','#!/usr/bin/env python3\nimport json\nprint(json.dumps({"schema":"jovovich.archive-ack.v1","startup_ack":True,"initial_snapshot":True,"per_update_ack":True}))\n')
trainer.chmod(0o755)
base=write('models/base-qwen.gguf','fixture base')
training={'argv_template':['build/jovovich-train-mlp','@BASE@','@ARM_DATASET@','@ARM_PREFIX@','100','0.0001','40','25','joint','@ARM_PAIR_MAP@'],
 'native_environment':{'NT_NO_I8':'1','NT_QMV_THREADS':'2','NT_ATTN_THREADS':'2','NT_SIMD_THREADS':'2'},'base_expected_sha256':sha(base)}
dump(repo/'training/explanations/plan.json',{'training':training})
for name in ('training/prepare.py','deps/notorch/notorch.c','models/before-native/before.bin','models/before-native/before.pairs.bin',
 'models/before-native/verification.json','training/quote/PREREGISTRATION.md','training/quote/bind_quote.py',
 'training/sft_review_v7_quote.jsonl','test/quote_bind.test.mjs','models/quote-native/quote.bin','models/quote-native/quote.pairs.bin',
 'models/before-launch/evaluation-plan.json'):
 write(name,'fixture '+name)
for name in ('training/explanations/evaluation_plan.json','training/quote/evaluation_contract.json'):
 shutil.copyfile(name,repo/name)
native=repo/'models/quote-native'
dump(native/'verification.json',{'status':'fail' if variant=='native_fail' else 'pass','identical_prompt_rows':52,'unchanged_nonreview_rows':24})
recorded=[bind(n,True) for n in ('models/base-qwen.gguf','training/quote/bind_quote.py','training/sft_review_v7_quote.jsonl')]
if variant=='native_base':recorded[0]['sha256']='e'*64
dump(native/'bindings.json',{'files':recorded})
argv=['build/jovovich-train-mlp','models/base-qwen.gguf','models/before-native/before.bin','@RUN@/adapter','100','0.0001','40','25','joint','models/before-native/before.pairs.bin']
plan={'schema_version':1,'run_id':'fixture-before','argv':argv,'environment':dict(training['native_environment']),
 'bindings':[bind(n) for n in ('models/base-qwen.gguf','build/jovovich-train-mlp','training/explanations/plan.json','training/prepare.py',
  'deps/notorch/notorch.c','models/before-native/verification.json','models/before-native/before.bin','models/before-native/before.pairs.bin',
  'models/before-launch/evaluation-plan.json')],
 'remote':{'private':True,'repo':'fixture/archive','prefix':'experiments/explanation-order'},'ack_timeout_ms':900000,'arm':'before',
 'scientific_plan_sha256':sha(repo/'training/explanations/plan.json'),'evaluation_plan':'models/before-launch/evaluation-plan.json'}
if variant=='scientific':plan['scientific_plan_sha256']='0'*64
if variant=='environment':plan['environment']['NT_QMV_THREADS']='8'
if variant=='lr':plan['argv'][5]='0.001'
if variant=='arm':plan['arm']='after'
run=root/'run'
dump(run/'plan.json',plan)
dump(run/'_units/intent.json',{'status':'intent','argv':plan['argv'],'environment':plan['environment'],'bindings':plan['bindings']})
initial={k:hashlib.sha256(('initial '+k).encode()).hexdigest() for k in ('gate','up','down')}
dump(run/'_units/initialization.json',{'initial_lora_sha256':initial,'expected_initial_lora_sha256':None})
completion={'status':'native_completed','archive_status':'requires_verified_receipt','return_code':0,'acknowledged_updates':100,
 'initial_readout_acknowledged':True,'initial_lora_sha256':initial,'plan_sha256':sha(run/'plan.json'),'bindings':plan['bindings'],'sequence':2}
if variant=='updates':completion['acknowledged_updates']=99
if variant=='return_code':completion['return_code']=1
if variant=='plan_sha':completion['plan_sha256']='f'*64
if variant=='bindings':completion['bindings']=plan['bindings'][:-1]
dump(run/'completion.json',completion)
archive=DurableArchive(FakeTransport(),'other-before' if variant=='run_id' else plan['run_id'],prefix=plan['remote']['prefix'])
archive.sync_unit('intent',{'plan.json':run/'plan.json','_units/intent.json':run/'_units/intent.json'},sequence=0)
archive.sync_unit('update-000',{'_units/initialization.json':run/'_units/initialization.json'},sequence=1)
if variant!='no_completion':archive.sync_unit('completion',{'completion.json':run/'completion.json'},sequence=2)
recovered=root/'recovered';archive.recover(recovered)
if variant=='unverified':
 r=json.loads((recovered/'_durable-recovery.json').read_text());r['verified_remote_bytes']=False
 (recovered/'_durable-recovery.json').write_text(json.dumps(r))
if variant=='receipt_bytes':(recovered/'completion.json').write_text((recovered/'completion.json').read_text()+' ')
shutil.rmtree(repo/'models/before-native')
if variant=='source':write('training/prepare.py','changed after the before run')
if variant=='trainer':trainer.write_text(trainer.read_text()+'# rebuilt\n')
if variant=='native_source':write('training/sft_review_v7_quote.jsonl','changed after native verification')
if variant=='contract_drift':
 c=json.loads((repo/'training/quote/evaluation_contract.json').read_text());s=c['collector_jobs'][0]['score_argv']
 s[s.index('--order')+1]='after';(repo/'training/quote/evaluation_contract.json').write_text(json.dumps(c,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({'repo':str(repo),'recovered':str(recovered),'native':str(native),'initial':initial,'before':plan}))
`;

function fixture(t, variant) {
  const dir = mkdtempSync(join(realpathSync(tmpdir()), 'quote-bind-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const r = spawnSync('python3', ['-c', FIXTURE, dir, variant], { cwd: ROOT, encoding: 'utf8', timeout: 30000 });
  assert.equal(r.status, 0, r.stderr || String(r.error));
  return { dir, out: join(dir, 'quote.launch.json'), ...JSON.parse(r.stdout) };
}

function bind(f) {
  return spawnSync('python3', ['training/quote/bind_quote.py', 'bind', '--before-recovered', f.recovered,
    '--native', f.native, '--run-prefix', 'fixture', '--out', f.out, '--repo', f.repo,
    '--evaluation-contract', join(f.repo, 'training/quote/evaluation_contract.json')],
  { cwd: ROOT, encoding: 'utf8', timeout: 30000 });
}

test('bind derives a runnable quote plan from the recovered before run', t => {
  const f = fixture(t, 'ok');
  const r = bind(f);
  assert.equal(r.status, 0, r.stderr);
  const plan = JSON.parse(readFileSync(f.out, 'utf8'));
  const receipt = JSON.parse(readFileSync(join(f.recovered, '_durable-recovery.json'), 'utf8'));
  const completion = receipt.units.find(u => u.unit_id === 'completion');
  assert.equal(plan.run_id, 'fixture-quote');
  assert.equal(plan.arm, 'quote');
  assert.deepEqual(plan.expected_initial_lora_sha256, f.initial);
  assert.deepEqual(plan.before_completion, {
    run_id: 'fixture-before', revision: receipt.revision, manifest_sha256: completion.manifest_sha256,
    completion_sha256: completion.files.find(x => x.name === 'completion.json').sha256 });
  assert.equal(plan.argv[2], 'models/quote-native/quote.bin');
  assert.equal(plan.argv[9], 'models/quote-native/quote.pairs.bin');
  for (const i of [0, 1, 3, 4, 5, 6, 7, 8]) assert.equal(plan.argv[i], f.before.argv[i]);
  for (const key of ['environment', 'remote', 'ack_timeout_ms', 'scientific_plan_sha256'])
    assert.deepEqual(plan[key], f.before[key]);
  const bound = Object.fromEntries(plan.bindings.map(b => [b.path, b]));
  for (const b of f.before.bindings) {
    if (b.path.startsWith('models/before-native/')) {
      assert.equal(bound[b.path], undefined);
      assert.ok(!existsSync(join(f.repo, b.path)));
    } else if (b.path === f.before.evaluation_plan) assert.equal(bound[b.path], undefined);
    else assert.deepEqual(bound[b.path], b);
  }
  assert.deepEqual(plan.before_artifacts.map(a => a.path).sort(),
    ['models/before-launch/evaluation-plan.json', 'models/before-native/before.bin', 'models/before-native/before.pairs.bin',
      'models/before-native/verification.json']);
  const contract = readFileSync(join(f.repo, 'training/quote/evaluation_contract.json'));
  assert.equal(plan.evaluation_plan, 'training/quote/evaluation_contract.json');
  assert.deepEqual(bound[plan.evaluation_plan], { path: plan.evaluation_plan, bytes: contract.length,
    sha256: createHash('sha256').update(contract).digest('hex') });
  assert.ok(bound['training/explanations/evaluation_plan.json']);
  for (const path of ['models/quote-native/quote.bin', 'models/quote-native/quote.pairs.bin',
    'models/quote-native/verification.json', 'models/quote-native/bindings.json', 'training/quote/PREREGISTRATION.md',
    'training/quote/bind_quote.py', 'training/sft_review_v7_quote.jsonl', 'test/quote_bind.test.mjs'])
    assert.ok(bound[path], path);
  const check = spawnSync('python3', ['-c', `import json,sys
sys.path.insert(0,'training/explanations')
from run_training import validate_plan
validate_plan(json.load(open(sys.argv[1])),sys.argv[2])`, f.out, f.repo], { cwd: ROOT, encoding: 'utf8' });
  assert.equal(check.status, 0, check.stderr);
  const again = bind(f);
  assert.equal(again.status, 1);
  assert.match(again.stderr, /bind_quote: output plan already exists/);
});

const rejected = [
  ['updates', 'before completion did not acknowledge 100 updates'],
  ['return_code', 'before completion return code is not 0'],
  ['unverified', 'recovery receipt does not verify remote bytes'],
  ['no_completion', 'recovered archive has no completion unit'],
  ['scientific', 'before scientific plan differs from this checkout'],
  ['environment', 'before environment differs from the frozen native environment'],
  ['lr', 'before argv differs from the frozen training argv'],
  ['source', 'before source differs in this checkout: training/prepare.py'],
  ['trainer', 'trainer binary differs from the before run: build/jovovich-train-mlp'],
  ['arm', 'recovered plan is not the before arm'],
  ['plan_sha', 'completion plan_sha256 differs from recovered plan.json'],
  ['bindings', 'completion bindings differ from recovered plan'],
  ['receipt_bytes', 'recovered file differs from its archive receipt: completion.json'],
  ['run_id', 'recovery receipt belongs to another run'],
  ['native_fail', 'quote native verification did not pass'],
  ['native_base', 'quote native base differs from the before base'],
  ['native_source', 'quote native source changed since verification: training/sft_review_v7_quote.jsonl'],
  ['contract_drift', 'quote evaluation contract differs from its derivation'],
];

test('every rejection has its own message', () => {
  assert.equal(new Set(rejected.map(([, message]) => message)).size, rejected.length);
});

for (const [variant, message] of rejected) {
  test(`bind rejects ${variant}`, t => {
    const f = fixture(t, variant);
    const r = bind(f);
    assert.equal(r.status, 1, r.stderr);
    assert.equal(r.stderr.trim(), 'bind_quote: ' + message);
    assert.ok(!existsSync(f.out));
  });
}
