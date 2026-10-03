import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, realpathSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const source = resolve('training/quote/host_launch.sh');
const INPUTS = { schema: 'jovovich.quote-launch-inputs.v1', archive_revision: 'd'.repeat(40),
  before_run_id: 'fixture-before', before_eval_run_id: 'fixture-eval',
  expected_initial_lora_sha256: { gate: 'a'.repeat(64), up: 'b'.repeat(64), down: 'c'.repeat(64) } };
const ORDER = ['install', 'node training/quote/build.mjs', 'derive-check', 'node bin/jovovich.mjs', 'build',
  'recover fixture-before', 'recover fixture-eval-before_update100-train', 'recover fixture-eval-before_update100-holdout',
  'native', 'bind', 'preflight-quote', 'run-quote', 'evaluate'];

function write(path, text, mode) {
  mkdirSync(resolve(path, '..'), { recursive: true });
  writeFileSync(path, text, { mode });
}
function command(cmd, args, cwd) {
  const r = spawnSync(cmd, args, { cwd, encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr || String(r.error));
  return r.stdout.trim();
}
function fixture(t, inputs = INPUTS) {
  const temp = mkdtempSync(join(realpathSync(tmpdir()), 'jovovich-quote-host-'));
  t.after(() => rmSync(temp, { recursive: true, force: true }));
  const repo = join(temp, 'repo'); mkdirSync(repo);
  const launcher = join(repo, 'training/quote/host_launch.sh');
  write(launcher, readFileSync(source));
  write(join(repo, '.gitignore'), 'models/\n');
  write(join(repo, 'training/quote/manipulation.mjs'), 'fixture\n');
  if (inputs !== null) write(join(repo, 'training/quote/launch_inputs.json'), JSON.stringify(inputs, null, 2) + '\n');
  const native = join(repo, 'deps/notorch'); mkdirSync(native, { recursive: true });
  for (const dir of [native, repo]) {
    command('git', ['init', '-q'], dir);
    command('git', ['config', 'user.email', 'fixture@example.invalid'], dir);
    command('git', ['config', 'user.name', 'Fixture'], dir);
  }
  write(join(native, 'source.c'), 'fixture\n');
  command('git', ['add', '.'], native); command('git', ['commit', '-qm', 'fixture'], native);
  const notorch = command('git', ['rev-parse', 'HEAD'], native);
  write(join(repo, '.gitmodules'), '[submodule "deps/notorch"]\n\tpath = deps/notorch\n\turl = ' + native + '\n');
  command('git', ['add', '.'], repo); command('git', ['commit', '-qm', 'fixture'], repo);
  const sha = command('git', ['rev-parse', 'HEAD'], repo);
  const tools = join(temp, 'tools'); mkdirSync(tools);
  const trace = join(temp, 'trace');
  write(join(tools, 'node'), `#!/bin/sh\n[ "$1" = '-e' ] && exit 0\nprintf 'node %s\\n' "$1" >> "$HOST_TEST_TRACE"\n`, 0o755);
  write(join(tools, 'make'), '#!/bin/sh\nprintf "build\\n" >> "$HOST_TEST_TRACE"\n', 0o755);
  // The launcher targets Linux hosts; these stubs make the fixture host one.
  write(join(tools, 'uname'), '#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo fixture-machine;; *) exit 1;; esac\n', 0o755);
  write(join(tools, 'flock'), '#!/bin/sh\nexit 0\n', 0o755);
  write(join(tools, 'lscpu'), '#!/bin/sh\nprintf "Architecture: fixture\\nModel name:          Fixture CPU\\n"\n', 0o755);
  const mock = join(temp, 'mock.py');
  write(mock, String.raw`
import json,os,sys,types
from pathlib import Path
assert not any(k in os.environ for k in ('HF_TOKEN','HUGGING_FACE_HUB_TOKEN','HUGGINGFACE_HUB_TOKEN','RUNPOD_API_KEY','RUNPOD_API_TOKEN'))
a=sys.argv[1:]
def log(s):
 with open(os.environ['HOST_TEST_TRACE'],'a') as f:f.write(s+'\n')
def arg(flag):return a[a.index(flag)+1]
def save(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v))
inputs=lambda:json.loads(Path('training/quote/launch_inputs.json').read_text())
sys.modules['huggingface_hub']=types.SimpleNamespace(__version__='0.35.3')
if a[:2]==['-m','pip']:log('install')
elif a[0]=='-c':exec(a[1])
elif a[0]=='-':sys.argv=a;exec(sys.stdin.read())
elif a==['training/quote/evaluate_quote.py','derive','--check']:log('derive-check')
elif a[:2]==['training/quote/bind_quote.py','recover']:
 run=arg('--run-id');log('recover '+run);assert arg('--revision')==inputs()['archive_revision']
 out=Path(arg('--out'));out.mkdir(parents=True)
 if run==inputs()['before_run_id']:
  initial=dict(inputs()['expected_initial_lora_sha256'])
  if os.environ.get('HOST_TEST_INITIAL')=='mismatch':initial['up']='e'*64
  save(out/'completion.json',{'initial_lora_sha256':initial});save(out/'plan.json',{'arm':'before'})
 else:save(out/'manifest.json',{'run_id':run})
 print(json.dumps({'status':'recovered','run_id':run}))
elif a[:2]==['training/quote/bind_quote.py','native']:log('native');Path(arg('--out')).mkdir()
elif a[:2]==['training/quote/bind_quote.py','bind']:
 log('bind');assert json.loads((Path(arg('--before-recovered'))/'plan.json').read_text())['arm']=='before'
 assert arg('--evaluation-contract')=='training/quote/evaluation_contract.json' and Path(arg('--native')).is_dir()
 save(arg('--out'),{'arm':'quote','run_id':arg('--run-prefix')+'-quote'})
elif a[0]=='training/explanations/run_training.py':
 p=json.loads(Path(arg('--plan')).read_text());log(a[1]+'-'+p['arm'])
 if a[1]=='run':
  if os.environ.get('HOST_TEST_FAIL')=='quote':sys.exit(7)
  save(Path(arg('--run-dir'))/'verified.json',{'verified':True})
  if os.environ.get('HOST_TEST_MUTATE')=='quote':Path('training/quote/manipulation.mjs').write_text('changed')
elif a[:2]==['training/quote/evaluate_quote.py','run']:
 log('evaluate');assert json.loads((Path(arg('--quote-run'))/'verified.json').read_text())['verified']
 i=a.index('--before-collectors')
 for d,split in zip(a[i+1:i+3],('train','holdout')):
  assert json.loads((Path(d)/'manifest.json').read_text())['run_id']==inputs()['before_eval_run_id']+'-before_update100-'+split
 assert arg('--run-id')=='fixture-quote-eval' and arg('--contract')=='training/quote/evaluation_contract.json'
 save(Path(arg('--output'))/'fixture-completed.json',{})
else:raise AssertionError(a)
`);
  const python = command('which', ['python3'], repo);
  write(join(repo, 'models/archive-client-0.35.3/bin/python'), `#!/bin/sh\nexec '${python}' '${mock}' "$@"\n`, 0o755);
  const token = join(temp, 'credential'); write(token, 'synthetic-test-credential\n', 0o600);
  const env = { ...process.env, PATH: tools + ':' + process.env.PATH, HOST_TEST_TRACE: trace,
    HF_TOKEN: 'must-be-unset', RUNPOD_API_KEY: 'must-be-unset' };
  const run = (extra = {}, pin = sha) => spawnSync('bash', [launcher, token, 'fixture', pin],
    { cwd: repo, env: { ...env, ...extra }, encoding: 'utf8', timeout: 20000 });
  const events = () => existsSync(trace) ? readFileSync(trace, 'utf8').trim().split('\n') : [];
  const job = name => join(repo, 'models/fixture-quote-job', name);
  return { repo, sha, notorch, run, events, job };
}

test('quote launcher recovers the before arm, trains quote once and evaluates it', t => {
  const f = fixture(t); const r = f.run(); assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(f.events(), ORDER);
  const manifest = JSON.parse(readFileSync(f.job('host-manifest.json'), 'utf8'));
  assert.equal(manifest.source_commit, f.sha); assert.equal(manifest.notorch_commit, f.notorch);
  assert.equal(manifest.checkout, f.repo); assert.equal(manifest.machine, 'fixture-machine');
  assert.equal(manifest.cpu_model, 'Fixture CPU'); assert.match(manifest.cc_version, /\S/);
  assert.deepEqual(manifest.launch_inputs, INPUTS);
  const done = JSON.parse(readFileSync(f.job('completed.json'), 'utf8'));
  assert.deepEqual(done, { status: 'quote_evaluation_archived', semantic_audit: 'pending', evaluation: 'models/fixture-quote-eval' });
  assert.equal(readFileSync(f.job('exit-status.txt'), 'utf8'), 'launcher_exit_code=0\n');
  assert.match(r.stdout, /semantic audit pending/);
  assert.doesNotMatch(r.stdout + r.stderr, /synthetic-test-credential|must-be-unset/);
});

test('wrong source SHA is rejected before installation or model work', t => {
  const f = fixture(t); const r = f.run({}, 'a'.repeat(40));
  assert.notEqual(r.status, 0); assert.match(r.stderr, /checkout must be pinned/);
  assert.deepEqual(f.events(), []); assert.equal(existsSync(f.job('')), false);
});

test('missing committed launch inputs are refused before any work', t => {
  const f = fixture(t, null); const r = f.run();
  assert.notEqual(r.status, 0); assert.match(r.stderr, /missing committed training\/quote\/launch_inputs\.json/);
  assert.deepEqual(f.events(), []); assert.equal(existsSync(f.job('')), false);
});

test('malformed launch inputs are refused before any work', t => {
  const f = fixture(t, { ...INPUTS, archive_revision: 'main' }); const r = f.run();
  assert.notEqual(r.status, 0); assert.match(r.stderr, /invalid training\/quote\/launch_inputs\.json/);
  assert.deepEqual(f.events(), []); assert.equal(existsSync(f.job('')), false);
});

test('recovered initialization that differs from launch inputs stops before bind', t => {
  const f = fixture(t); const r = f.run({ HOST_TEST_INITIAL: 'mismatch' });
  assert.notEqual(r.status, 0); assert.match(r.stderr, /recovered before initialization differs from launch inputs/);
  assert.deepEqual(f.events(), ORDER.slice(0, ORDER.indexOf('native')));
});

test('failed quote training stops without evaluation or restart', t => {
  const f = fixture(t); const r = f.run({ HOST_TEST_FAIL: 'quote' });
  assert.equal(r.status, 7); assert.equal(f.events().at(-1), 'run-quote');
  assert.equal(readFileSync(f.job('exit-status.txt'), 'utf8'), 'launcher_exit_code=7\n');
  assert.equal(existsSync(f.job('completed.json')), false);
  const retry = f.run(); assert.notEqual(retry.status, 0); assert.match(retry.stderr, /fresh output already exists/);
  assert.equal(f.events().filter(v => v === 'run-quote').length, 1);
});

test('tracked source mutation after training stops before evaluation', t => {
  const f = fixture(t); const r = f.run({ HOST_TEST_MUTATE: 'quote' });
  assert.notEqual(r.status, 0); assert.match(r.stderr, /tracked checkout files have local changes/);
  assert.equal(f.events().at(-1), 'run-quote');
});
