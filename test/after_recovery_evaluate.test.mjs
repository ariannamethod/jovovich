import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

const configure = String.raw`
import json
from pathlib import Path
def configure_fixture(repo,write,bind,shared):
 contract=json.loads(Path('training/explanations/evaluation_plan.json').read_text().replace(
  'training/results/2026-10-03-explanation-order-run/native/','models/original/'))
 contract['resolution']['SHARED_BASE_UPDATE0_SHA256']=bind('models/base-qwen.gguf')['sha256']
 scientific=json.loads(Path('training/explanations/plan.json').read_text())
 scientific['training']['base_expected_sha256']=contract['resolution']['SHARED_BASE_UPDATE0_SHA256']
 write(repo/contract['scientific_plan'],scientific)
 names=set(contract['required_pretraining_launch_bindings'])|{'training/explanations/execute_evaluation.py'}
 for name in names:
  if not (repo/name).exists():write(repo/name,'fixture '+name)
 for name in ('training/explanations/evaluation_plan.json','models/original/evaluation-plan.json'):
  write(repo/name,contract)
 names|={item['path'] for item in shared}
 names-={'models/original/'+arm+suffix for arm in ('before','after') for suffix in ('.bin','.pairs.bin')}
 return [bind(name) for name in sorted(names)]
`;
const fixture = configure + readFileSync('test/after_recovery_fixture.py', 'utf8') + String.raw`
from after_recovery import evaluate as e
e.ROOT=repo;e.original.ROOT=repo;e.__file__=str(repo/'training/after_recovery/evaluate.py')
host=write(repo/'models/fresh-job/host-manifest.json',dict(source_commit=source_sha,launch_inputs=inputs,
 infrastructure_record=bind('training/results/verification.json')))
write(host.parent/'launcher.sh',(repo/'training/after_recovery/host_launch.sh').read_text())
plan=run(host_manifest=host);after=repo/'models/fresh-after';after.mkdir()
write(after/'plan.json',plan)
record_path=output/'binding.json'
before=recovered/'before'
def admit():return e.admission(before,after,record_path,source_sha,'fresh-eval')
def rewrite_record(change):
 record=e.read(record_path);change(record);write(record_path,record)
 updated=e.read(after/'plan.json')
 old={item['path']:item for item in plans['after']['bindings']}
 replacements={item['path']:item['candidate'] for item in changes}
 report=e.binding(record_path)
 updated['continuation']=dict(record,binding_report=report)
 updated['bindings']=[replacements.get(name,item) for name,item in old.items()]+record['added_bindings']+[report]
 write(after/'plan.json',updated)
def reject(call,fragment):
 try:call()
 except (RuntimeError,ValueError) as error:assert fragment in str(error),str(error)
 else:raise AssertionError('unsafe evaluation admission accepted')
def complete_after():
 archive=DurableArchive(transport,plan['run_id'],plan['remote']['prefix'])
 archive.sync_unit('intent',{'plan.json':after/'plan.json'},sequence=0)
 for update in range(101):
  metric=write(after/('_units/update-%03d.metrics.jsonl'%update),{'update':update})
  files={str(metric.relative_to(after)):metric}
  if update==100:
   for part in initial:
    for ext in ('f32','lora'):
     name=f'adapter.epoch100.{part}.{ext}'
     files[name]=write(after/name,'final '+part)
  receipt=archive.sync_unit('update-%03d'%update,files,sequence=update+1)
  if update==100:write(after/'_units/update-100.ack.json',receipt)
 completion=dict(status='native_completed',archive_status='requires_verified_receipt',return_code=0,
  acknowledged_updates=100,initial_readout_acknowledged=True,sequence=102,
  plan_sha256=e.digest(after/'plan.json'),bindings=plan['bindings'],initial_lora_sha256=initial)
 files={'completion.json':write(after/'completion.json',completion)}
 for name in ('stdout.jsonl','metrics.jsonl','stderr.log'):files[name]=write(after/name,'fixture log')
 for part in initial:
  for ext in ('f32','lora'):
   name=f'adapter.{part}.{ext}';files[name]=write(after/name,'final '+part)
 receipt=archive.sync_unit('completion',files,sequence=102)
 write(after/'_units/completion.ack.json',dict(completion,status='completed',archive_status='verified',remote_verification=receipt))
def prepare():return e.prepare(repo/plan['evaluation_plan'],before,after,repo/'models/eval',
                              'fresh-eval',record_path,source_sha)
`;

function python(code) {
  const result = spawnSync('python3', ['-c', fixture + code], { encoding: 'utf8', timeout: 60000 });
  assert.equal(result.status, 0, result.stderr || result.stdout || String(result.error));
}

test('continuation evaluator admits authenticated before100 and fresh after100 to the original 228-response contract', () => {
  python(String.raw`
complete_after();prepared=prepare()
assert prepared['training']['before']['run_id']=='original-before'
assert prepared['training']['after']['run_id']=='fresh-after'
assert len(prepared['export_phases'])==8 and len(prepared['training_receipts'])==4
assert sum(job['rows'] for job in prepared['contract']['collector_jobs'])==228
assert [row['index'] for row in prepared['contract']['parity']['rows']]==[0,1,2,3,51]
bound={item['path']:item for item in prepared['bindings']}
for change in changes:
 assert bound[change['path']]==change['candidate']
 assert bound['models/recovered/before/inputs/'+change['path']]['sha256']==change['original']['sha256']
temporary=root/'receipt-readback';temporary.mkdir()
verified=e.original.verify_training_receipts(DurableArchive(transport,'fresh-eval',plan['remote']['prefix']),
 prepared['training_receipts'],temporary)
assert verified['status']=='verified' and verified['unique_payloads']>0
assert not (repo/'models/eval').exists()
`);
});

test('continuation admission rejects omitted helpers even when report and launch hashes are recomputed', () => {
  for (const name of ['training/after_recovery/bind.py', 'training/after_recovery/evaluate.py',
    'training/cloud/prepare_after_host.sh', 'models/recovered/before/_durable-recovery.json']) {
    python(String.raw`
rewrite_record(lambda record:record.update(added_bindings=[item for item in record['added_bindings'] if item['path']!=${JSON.stringify(name)}]))
reject(admit,'dependency set differs')
`);
  }
});

test('continuation admission rejects an extra arbitrary payload with self-consistent hashes', () => {
  python(String.raw`
payload=write(repo/'models/unreviewed.txt','arbitrary data')
rewrite_record(lambda record:record['added_bindings'].append(e.binding(payload)))
reject(admit,'dependency set differs')
`);
});

test('managed continuation cannot remove its host provenance by declaring it optional', () => {
  python(String.raw`
def remove_host(record):
 record['host_manifest']=None
 record['added_bindings']=[item for item in record['added_bindings'] if not item['path'].startswith('models/fresh-job/')]
rewrite_record(remove_host)
reject(admit,'requires its bound host manifest')
`);
});

test('continuation requires the full recovered ledgers even when a truncated ledger is rehashed', () => {
  python(String.raw`
path=before/'_durable-recovery.json';ledger=e.read(path)
ledger['units']=[unit for unit in ledger['units'] if unit['unit_id'] in ('update-100','completion')]
write(path,ledger)
def rebind_ledger(record):
 record['added_bindings']=[e.binding(path) if item['path']==str(path.relative_to(repo)) else item
                           for item in record['added_bindings']]
rewrite_record(rebind_ledger)
reject(admit,'invalid recovered unit')
`);
});

test('continuation admission rejects changed training parameters and attempt IDs', () => {
  for (const mutation of ["changed['argv'][5]='0.001'", "changed['environment']['NT_QMV_THREADS']='8'",
    "changed['expected_initial_lora_sha256']['gate']='f'*64", "changed['run_id']='another-after'"]) {
    python(String.raw`
changed=e.read(after/'plan.json')
${mutation}
write(after/'plan.json',changed)
try:admit()
except RuntimeError:pass
else:raise AssertionError('changed training contract accepted')
`);
  }
});

test('continuation evaluation requires both complete endpoints and original initialization', () => {
  for (const mutation of ["completion['acknowledged_updates']=99", "completion['initial_lora_sha256']['up']='e'*64"]) {
    python(String.raw`
complete_after();path=after/'_units/completion.ack.json';completion=e.read(path)
${mutation}
write(path,completion)
try:prepare()
except RuntimeError:pass
else:raise AssertionError('incomplete or changed endpoint accepted')
`);
  }
  python(String.raw`
complete_after();write(before/'adapter.epoch100.gate.f32','changed checkpoint')
reject(prepare,'bound bytes changed')
`);
});

test('continuation evaluation rejects remote checkpoint corruption before exports', () => {
  python(String.raw`
complete_after();prepared=prepare()
transport.download_fault=lambda name,data:b'corrupt' if '/objects/' in name else data
temporary=root/'receipt-readback';temporary.mkdir()
reject(lambda:e.original.verify_training_receipts(DurableArchive(transport,'fresh-eval',plan['remote']['prefix']),
 prepared['training_receipts'],temporary),'remote payload checksum mismatch')
assert not (repo/'models/eval').exists()
`);
});
