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
