import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const source = resolve('training/explanations/persistent_host_launch.sh');
const provenance = ['training/quote/PREREGISTRATION.md', 'training/quote/build.mjs',
  'training/quote/manipulation.mjs', 'training/quote/preflight.json',
  'test/quote_manipulation.test.mjs', 'training/sft_review_v7_quote.jsonl',
  'training/explanations/reasons.json', 'test/persistent_host_launch.test.mjs',
  'training/cloud/prepare_host.sh', 'training/cloud/runpod_bootstrap.py'];
function write(path, text, mode) {
  mkdirSync(resolve(path, '..'), { recursive: true });
  writeFileSync(path, text, { mode });
}
function command(cmd, args, cwd) {
  const r = spawnSync(cmd, args, { cwd, encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr || String(r.error));
  return r.stdout.trim();
}
function fixture(t) {
  const temp = mkdtempSync(join(tmpdir(), 'jovovich-host-'));
  t.after(() => rmSync(temp, { recursive: true, force: true }));
  const repo = join(temp, 'repo'); mkdirSync(repo);
  const launcher = join(repo, 'training/explanations/persistent_host_launch.sh');
  write(launcher, readFileSync(source));
  write(join(repo, '.gitignore'), 'models/\n');
  for (const path of provenance) write(join(repo, path), path + '\n');
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
  const mock = join(temp, 'mock.py');
  write(mock, String.raw`
import hashlib,json,os,sys,types
from pathlib import Path
assert not any(k in os.environ for k in ('HF_TOKEN','HUGGING_FACE_HUB_TOKEN','HUGGINGFACE_HUB_TOKEN','RUNPOD_API_KEY','RUNPOD_API_TOKEN'))
a=sys.argv[1:]
def log(s):
 with open(os.environ['HOST_TEST_TRACE'],'a') as f:f.write(s+'\n')
def arg(flag):return a[a.index(flag)+1]
def save(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
sys.modules['huggingface_hub']=types.SimpleNamespace(__version__='0.35.3')
if a[:2]==['-m','pip']:log('install')
elif a[0]=='-c':exec(a[1])
elif a[0]=='-':sys.argv=a;exec(sys.stdin.read())
elif a[0].endswith('verify_native.py'):log('native-preflight')
elif a[0].endswith('prepare_launches.py') and a[1]=='prepare':
 log('prepare');out=Path(arg('--out'));out.mkdir()
 env={'NT_NO_I8':'1','NT_QMV_THREADS':'2','NT_ATTN_THREADS':'2','NT_SIMD_THREADS':'2'}
 for arm in ('before','after'):
  p={'arm':arm,'argv':['trainer','model',arm,'@RUN@/adapter','100','0.0001','40','25','joint','pairs'], 'environment':env,'bindings':[], 'ack_timeout_ms':300000}
  if os.environ.get('HOST_TEST_DRIFT')=='1':p['argv'][4]='99'
  save(out/('before.launch.json' if arm=='before' else 'after.template.json'),p)
 save(out/'evaluation-plan.json',{'generated':True})
elif a[0].endswith('run_training.py'):
 p=json.loads(Path(arg('--plan')).read_text());arm=p['arm'];log(a[1]+'-'+arm)
 assert p['ack_timeout_ms']==900000 and p['argv'][4]=='100'
 for b in p['bindings']:
  assert Path(b['path']).stat().st_size==b['bytes'] and sha(b['path'])==b['sha256']
 if a[1]=='run':
  if os.environ.get('HOST_TEST_FAIL')==arm:sys.exit(7)
  save(Path(arg('--run-dir'))/'verified.json',{'verified':True})
  if os.environ.get('HOST_TEST_MUTATE')==arm:Path('training/quote/manipulation.mjs').write_text('changed')
elif a[0].endswith('prepare_launches.py') and a[1]=='bind-after':
 log('bind-after');assert json.loads((Path(arg('--before-run'))/'verified.json').read_text())['verified']
 p=json.loads(Path(arg('--template')).read_text());p['expected_initial_lora_sha256']={k:'a'*64 for k in ('gate','up','down')};save(arg('--output'),p)
elif a[0].endswith('execute_evaluation.py'):
 log('evaluate');assert json.loads(Path(arg('--plan')).read_text())['generated']
 for arm in ('before','after'):assert json.loads((Path(arg('--'+arm))/'verified.json').read_text())['verified']
 save(Path(arg('--output'))/'fixture-completed.json',{})
else:raise AssertionError(a)
`);
  const python = command('which', ['python3'], repo);
  write(join(repo, 'models/archive-client-0.35.3/bin/python'), `#!/bin/sh\nexec '${python}' '${mock}' "$@"\n`, 0o755);
  const token = join(temp, 'credential'); write(token, 'synthetic-test-credential\n', 0o600);
  const env = { ...process.env, PATH: tools + ':' + process.env.PATH, HOST_TEST_TRACE: trace,
    HF_TOKEN: 'must-be-unset', RUNPOD_API_KEY: 'must-be-unset' };
  const run = (extra = {}, pin = sha, prefix = 'fixture') => spawnSync('bash', [launcher, token, prefix, pin],
    { cwd: repo, env: { ...env, ...extra }, encoding: 'utf8', timeout: 20000 });
  const events = () => existsSync(trace) ? readFileSync(trace, 'utf8').trim().split('\n') : [];
  return { repo, sha, notorch, run, events };
}

test('portable launcher archives matched arms sequentially with frozen host and quote provenance', t => {
  const f = fixture(t); const r = f.run(); assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(f.events(), ['install', 'node training/quote/build.mjs', 'node bin/jovovich.mjs',
    'build', 'native-preflight', 'prepare', 'preflight-before', 'run-before', 'bind-after',
    'preflight-after', 'run-after', 'evaluate']);
  const load = p => JSON.parse(readFileSync(join(f.repo, p), 'utf8'));
  const manifest = load('models/fixture-job/host-manifest.json');
  assert.equal(manifest.source_commit, f.sha); assert.equal(manifest.notorch_commit, f.notorch);
  assert.equal(manifest.quote_training, 'separate subsequent launch');
  const before = load('models/fixture-launch/before.launch.json');
  const after = load('models/fixture-launch/after.launch.json');
  assert.deepEqual(before.bindings, after.bindings);
  for (const path of provenance) assert.ok(before.bindings.some(b => b.path === path));
  assert.ok(before.bindings.some(b => b.path === 'models/fixture-job/host-manifest.json'));
  assert.equal(new Set(before.bindings.map(b => b.path)).size, before.bindings.length);
  assert.match(r.stdout, /semantic audit pending/);
  assert.doesNotMatch(r.stdout + r.stderr, /synthetic-test-credential|must-be-unset/);
});

test('wrong source SHA is rejected before installation or model work', t => {
  const f = fixture(t); const r = f.run({}, 'a'.repeat(40));
  assert.notEqual(r.status, 0); assert.match(r.stderr, /checkout must be pinned/);
  assert.deepEqual(f.events(), []); assert.equal(existsSync(join(f.repo, 'models/fixture-job')), false);
});

test('fixed training settings cannot drift during preparation', t => {
  const f = fixture(t); const r = f.run({ HOST_TEST_DRIFT: '1' });
  assert.notEqual(r.status, 0); assert.match(r.stderr, /fixed training settings differ/);
  assert.ok(!f.events().some(v => v.startsWith('run-')));
});

test('failed before stops without after binding, evaluation, or restart', t => {
  const f = fixture(t); const r = f.run({ HOST_TEST_FAIL: 'before' });
  assert.equal(r.status, 7); assert.equal(f.events().at(-1), 'run-before');
  assert.equal(readFileSync(join(f.repo, 'models/fixture-job/exit-status.txt'), 'utf8'), 'launcher_exit_code=7\n');
  const retry = f.run(); assert.notEqual(retry.status, 0); assert.match(retry.stderr, /fresh output already exists/);
  assert.equal(f.events().filter(v => v === 'run-before').length, 1);
});

test('tracked source mutation between arms stops the handoff', t => {
  const f = fixture(t); const r = f.run({ HOST_TEST_MUTATE: 'before' });
  assert.notEqual(r.status, 0); assert.match(r.stderr, /tracked checkout files have local changes/);
  assert.equal(f.events().at(-1), 'run-before');
});

test('after failure prevents evaluation', t => {
  const f = fixture(t); const r = f.run({ HOST_TEST_FAIL: 'after' });
  assert.equal(r.status, 7); assert.equal(f.events().at(-1), 'run-after');
});

test('untracked launch helpers cannot borrow an older reviewed source pin', t => {
  const f = fixture(t);
  write(join(f.repo, 'training/explanations/injected.py'), 'unreviewed');
  const r = f.run(); assert.notEqual(r.status, 0); assert.match(r.stderr, /untracked source files/);
  assert.deepEqual(f.events(), []);
});
