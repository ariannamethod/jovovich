import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

const fixture = readFileSync('test/after_recovery_fixture.py', 'utf8');

function python(code) {
  const result = spawnSync('python3', ['-c', fixture + code], { encoding: 'utf8', timeout: 60000 });
  assert.equal(result.status, 0, result.stderr || result.stdout || String(result.error));
}

test('binder restores exact numerical artifacts and reconstructs receipts from checked durable units', () => {
  python(String.raw`
plan=run();contract=json.loads((output/'binding.json').read_text())
assert plan['argv']==plans['after']['argv'] and plan['environment']==plans['after']['environment']
assert plan['run_id']=='fresh-after' and plan['expected_initial_lora_sha256']==initial
assert plan['infrastructure_changes']==changes
assert plan['continuation']==dict(contract,binding_report=h.binding(output/'binding.json','models/launch/binding.json'))
original={f['path']:f for f in plans['after']['bindings']}
for item in plan['bindings']:
 assert h.binding(repo/item['path'],item['path'])==item
 if item['path'] in original and item['path'] not in h.INFRASTRUCTURE:assert item==original[item['path']]
assert os.access(repo/'build/jovovich-train-mlp',os.X_OK)
assert json.loads((repo/plan['evaluation_plan']).read_text())['generation_calls']==228
for name in ('training/after_recovery/evaluate.py','training/cloud/prepare_after_host.sh','test/after_host_launch.test.mjs'):
 assert any(f['path']==name for f in contract['added_bindings'])
from explanations.execute_evaluation import verify_training_receipts
checkdir=root/'verified';checkdir.mkdir()
remote=verify_training_receipts(DurableArchive(transport,'fresh-eval',inputs['archive']['prefix']),contract['before_receipts'],checkdir)
assert remote['status']=='verified' and remote['unique_payloads']>0
ack=json.loads((recovered/'before/_units/completion.ack.json').read_text())
assert ack['archive_status']=='verified' and ack['remote_verification']==contract['before_receipts'][0]
assert transport.commits==commits
`);
});

test('binder refuses changed numerical sources and original packed bytes', () => {
  python(String.raw`write(repo/'training/train_mlp.c','drift');reject('non-infrastructure source changed')`);
  python(String.raw`write(recovered/'failed-after/inputs/models/original/after.bin','drift');reject('bound bytes changed')`);
});

test('binder requires the infrastructure record in the pinned Git commit', () => {
  python(String.raw`
record_path=write(repo/'ignored-record.json',json.loads(record_path.read_text()));reject('Git object')
`);
  python(String.raw`
record=json.loads(record_path.read_text());record['infrastructure_changes'][0]['candidate']['sha256']='f'*64
write(record_path,record);reject('checkout differs from committed source')
`);
});

test('committed but incorrect infrastructure pairs reject original, candidate, and unused entries', () => {
  for (const mutate of [
    "record['infrastructure_changes'][0]['original']['sha256']='f'*64",
    "record['infrastructure_changes'][0]['candidate']['sha256']='f'*64",
    "record['infrastructure_changes'].append(copy.deepcopy(record['infrastructure_changes'][0]))",
  ]) {
    python(String.raw`
record=json.loads(record_path.read_text())
` + mutate + String.raw`
write(record_path,record);git('add',str(record_path));git('commit','-qm','wrong committed record');source_sha=git('rev-parse','HEAD')
try:run()
except ValueError as error:assert 'infrastructure' in str(error),str(error)
else:raise AssertionError('wrong committed hash pair accepted')
assert not (output/'after.launch.json').exists()
`);
  }
});

test('binder rejects source pin, executing implementation, and committed inputs drift', () => {
  python(String.raw`source_sha='b'*40;reject('checkout HEAD')`);
  python(String.raw`
write(repo/'training/after_recovery/bind.py','changed binder');git('add','training/after_recovery/bind.py')
git('commit','-qm','different binder');source_sha=git('rev-parse','HEAD');reject('executing binder')
`);
  python(String.raw`
inputs['new_after_run_id']='another-run';write(inputs_path,inputs);reject('checkout differs from committed source')
`);
});

test('binder rejects reused output, artifact, receipt, and symlink destinations', () => {
  python(String.raw`output.mkdir();reject('launch output must be new')`);
  python(String.raw`write(repo/'build/jovovich-train-mlp','preexisting binary');reject('artifact destination already exists')`);
  python(String.raw`write(recovered/'before/_units/completion.ack.json',{});reject('reconstructed receipt already exists')`);
  python(String.raw`
(repo/'build').rmdir();external=root/'external';external.mkdir();(repo/'build').symlink_to(external,target_is_directory=True)
reject('symlink')
`);
});

test('binder verifies all endpoint payload bytes and their ledger entries before making receipts', () => {
  python(String.raw`write(recovered/'before/adapter.epoch100.gate.f32','corrupt');reject('bound bytes changed')`);
  python(String.raw`
ledger_path=recovered/'before/_durable-recovery.json';ledger=json.loads(ledger_path.read_text())
ledger['units'][101]['files']=[f for f in ledger['units'][101]['files'] if f['name']!='adapter.epoch100.gate.f32']
write(ledger_path,ledger);reject('endpoint artifacts are incomplete')
`);
  python(String.raw`
ledger_path=recovered/'before/_durable-recovery.json';ledger=json.loads(ledger_path.read_text())
ledger['units'][101]['files'][0]['object']='elsewhere/object';write(ledger_path,ledger);reject('object binding')
`);
});

test('binder checks preflight provenance and base identity', () => {
  python(String.raw`write(repo/'models/base-qwen.gguf','wrong GGUF');reject('bound bytes changed')`);
  python(String.raw`
p=recovered/'preflight.json';value=json.loads(p.read_text());value['inputs']['new_after_run_id']='forged';write(p,value)
reject('preflight report differs')
`);
});

test('binder binds the host manifest and exact committed launcher copy', () => {
  python(String.raw`
host=write(repo/'models/job/host-manifest.json',{'source_commit':source_sha})
write(host.parent/'launcher.sh',(repo/'training/after_recovery/host_launch.sh').read_text())
plan=run(host_manifest=host)
assert any(item['path']=='models/job/host-manifest.json' for item in plan['bindings'])
assert any(item['path']=='models/job/launcher.sh' for item in plan['bindings'])
`);
  python(String.raw`
host=write(repo/'models/job/host-manifest.json',{'source_commit':source_sha})
write(host.parent/'launcher.sh','wrong shell');reject('launcher copy differs',host_manifest=host)
`);
});

test('Git provenance ignores inherited overrides and rejects a symlink Git object', () => {
  python(String.raw`
os.environ.update(GIT_DIR=str(root/'wrong-git'),GIT_WORK_TREE=str(root/'wrong-tree'),
                  GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='alias.cat-file',GIT_CONFIG_VALUE_0='!exit 99')
plan=run()
assert plan['run_id']=='fresh-after'
`);
  python(String.raw`
raw=record_path.read_text();record_path.unlink();record_path.symlink_to(raw)
git('add',str(record_path));git('commit','-qm','symlink record');source_sha=git('rev-parse','HEAD')
record_path.unlink();record_path.write_text(raw);reject('not a regular file')
`);
});
