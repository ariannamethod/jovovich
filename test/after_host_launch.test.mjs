import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, realpathSync, rmSync, existsSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';

const source = resolve('training/after_recovery/host_launch.sh');
const prepareSource = resolve('training/cloud/prepare_after_host.sh');
const INPUT_PATH = 'training/after_recovery/inputs.json';
const RECORD_PATH = 'training/results/2026-10-08-archive-rehearsal/launch-bindings.json';
const INPUTS = { ...JSON.parse(readFileSync(INPUT_PATH, 'utf8')),
  new_after_run_id: 'fixture-after', new_evaluation_run_id: 'fixture-eval' };
const ORDER = ['install', 'fetch-model', 'recover', 'bind', 'preflight-after', 'run-after', 'evaluate'];

function write(path, text, mode) {
  mkdirSync(resolve(path, '..'), { recursive: true });
  writeFileSync(path, text, { mode });
}
function command(cmd, args, cwd) {
  const r = spawnSync(cmd, args, { cwd, encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr || String(r.error));
  return r.stdout.trim();
}
function fileBinding(repo, path) {
  const bytes = readFileSync(join(repo, path));
  return { path, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') };
}
function fixture(t, options = {}) {
  const temp = mkdtempSync(join(realpathSync(tmpdir()), 'jovovich-after-host-'));
  t.after(() => rmSync(temp, { recursive: true, force: true }));
  const repo = join(temp, 'repo'); mkdirSync(repo);
  const launcher = join(repo, 'training/after_recovery/host_launch.sh');
  write(launcher, readFileSync(source));
  write(join(repo, '.gitignore'), 'models/\nbuild/\n' + (options.ignoredRecord ? RECORD_PATH + '\n' : ''));
  write(join(repo, 'training/durable_archive.py'), '# fixture archive source\n');
  write(join(repo, 'training/explanations/run_training.py'), '# fixture archive-parent source\n');
  write(join(repo, 'training/after_recovery/bind.py'), '# fixture new binding source\n');
  const inputs = { ...INPUTS, ...options.inputs };
  if (!options.missingInputs) write(join(repo, INPUT_PATH), JSON.stringify(inputs, null, 2) + '\n');
  const infrastructure_changes = ['training/durable_archive.py', 'training/explanations/run_training.py'].map(path => ({
    path, original: { path, bytes: 1, sha256: 'a'.repeat(64) }, candidate: fileBinding(repo, path),
  }));
  if (options.badInfrastructure) infrastructure_changes[0].candidate.sha256 = 'b'.repeat(64);
  const record = { schema: 'jovovich.archive-retry-preflight-result.v1',
    new_after_run_id: INPUTS.new_after_run_id, original_archive_revision: INPUTS.archive_revision, infrastructure_changes };
  write(join(repo, RECORD_PATH), JSON.stringify(record, null, 2) + '\n');
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
  write(join(tools, 'node'), `#!/bin/sh\n[ "$1" = '-e' ] && exit 0\n[ "$1" = 'bin/jovovich.mjs' ] && [ "$2" = 'fetch-model' ] || exit 99\nprintf 'fetch-model\\n' >> "$HOST_TEST_TRACE"\nprintf 'fixture model' > "$JOVOVICH_MODEL"\n`, 0o755);
  write(join(tools, 'make'), '#!/bin/sh\nprintf "unexpected-build\\n" >> "$HOST_TEST_TRACE"\nexit 99\n', 0o755);
  write(join(tools, 'uname'), '#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo x86_64;; *) exit 1;; esac\n', 0o755);
  write(join(tools, 'flock'), '#!/bin/sh\nexit 0\n', 0o755);
  const mock = join(temp, 'mock.py');
  write(mock, String.raw`
import hashlib,json,os,sys,types
from pathlib import Path
for key in ('HF_TOKEN','RUNPOD_API_KEY','GITHUB_TOKEN','CUSTOM_CREDENTIAL','TEST_PASSWORD'):
 assert key not in os.environ, 'credential leaked to child'
a=sys.argv[1:]
def log(s):
 with open(os.environ['HOST_TEST_TRACE'],'a') as f:f.write(s+'\n')
def arg(flag):return a[a.index(flag)+1]
def save(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v))
def binding(name):
 p=Path(name);return {'path':name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
inputs=lambda:json.loads(Path('training/after_recovery/inputs.json').read_text())
sys.modules['huggingface_hub']=types.SimpleNamespace(__version__='0.35.3')
if a[:2]==['-m','pip']:log('install');assert a[-1]=='huggingface_hub==0.35.3'
elif a[0]=='-c':exec(a[1])
elif a[0]=='-':sys.argv=a;exec(sys.stdin.read())
elif a[0]=='training/after_recovery/preflight.py':
 log('recover')
 if os.environ.get('HOST_TEST_FAIL')=='recover':sys.exit(6)
 out=Path(arg('--output'));save(out/'preflight.json',{'fixture':True})
 save(out/'before'/'verified.json',{'run_id':inputs()['before_run_id']})
 save(out/'failed-after'/'verified.json',{'run_id':inputs()['failed_after_run_id']})
 assert Path(arg('--token-file')).is_file()
 print(json.dumps({'status':'recovered'}))
elif a[0]=='training/after_recovery/bind.py':
 log('bind')
 if os.environ.get('HOST_TEST_FAIL')=='bind':sys.exit(8)
 assert json.loads((Path(arg('--recovered'))/'preflight.json').read_text())['fixture']
 assert arg('--infrastructure-record')=='training/results/2026-10-08-archive-rehearsal/launch-bindings.json'
 host=Path(arg('--host-manifest'));assert json.loads(host.read_text())['source_commit']==arg('--source-sha')
 bindings=[binding(name) for name in ('training/after_recovery/inputs.json','training/after_recovery/host_launch.sh',
            'models/fixture-job/launcher.sh','models/fixture-job/host-manifest.json')]
 eval_path='models/original-launch/evaluation-plan.json';save(eval_path,{'frozen_original_contract':True})
 bindings.append(binding(eval_path))
 variant=os.environ.get('HOST_TEST_BINDINGS')
 if variant=='duplicate':bindings.append(dict(bindings[0]))
 if variant=='provenance':bindings[3]['sha256']='f'*64
 if variant=='evaluation':bindings[-1]['sha256']='f'*64
 out=Path(arg('--out'))
 save(out/'after.launch.json',{'arm':'after','run_id':inputs()['new_after_run_id'],'bindings':bindings,
      'evaluation_plan':eval_path,'expected_initial_lora_sha256':inputs()['expected_initial_lora_sha256']})
 save(out/'binding.json',{'source_commit':arg('--source-sha'),'fixture':True})
 print(json.dumps({'status':'bound'}))
elif a[0]=='training/explanations/run_training.py':
 p=json.loads(Path(arg('--plan')).read_text());log(a[1]+'-'+p['arm'])
 assert p['arm']=='after' and p['run_id']==inputs()['new_after_run_id']
 frozen={item['path']:item for item in p['bindings']}
 for name in ('training/after_recovery/inputs.json','training/after_recovery/host_launch.sh',
              'models/fixture-job/launcher.sh','models/fixture-job/host-manifest.json'):
  assert frozen[name]==binding(name),'provenance must be frozen before preflight or training'
 if a[1]=='preflight' and os.environ.get('HOST_TEST_FAIL')=='protocol':sys.exit(4)
 if a[1]=='run':
  if os.environ.get('HOST_TEST_FAIL')=='after':sys.exit(7)
  save(Path(arg('--run-dir'))/'verified.json',{'verified':True})
  if os.environ.get('HOST_TEST_MUTATE')=='after':Path('training/after_recovery/bind.py').write_text('changed')
elif a[:2]==['training/after_recovery/evaluate.py','run']:
 log('evaluate')
 assert json.loads((Path(arg('--before'))/'verified.json').read_text())['run_id']==inputs()['before_run_id']
 assert json.loads((Path(arg('--after'))/'verified.json').read_text())['verified']
 assert arg('--run-id')==inputs()['new_evaluation_run_id']
 assert arg('--plan')=='models/original-launch/evaluation-plan.json'
 assert json.loads(Path(arg('--plan')).read_text())['frozen_original_contract']
 assert json.loads(Path(arg('--continuation-record')).read_text())['source_commit']==arg('--source-sha')
 if os.environ.get('HOST_TEST_FAIL')=='evaluation':sys.exit(9)
 save(Path(arg('--output'))/'fixture-completed.json',{})
else:raise AssertionError(a)
`);
  const python = command('which', ['python3'], repo);
  write(join(repo, 'models/archive-client-0.35.3/bin/python'), `#!/bin/sh\nexec '${python}' '${mock}' "$@"\n`, 0o755);
  const token = join(temp, 'credential'); write(token, 'synthetic-test-credential\n', 0o600);
  const env = { ...process.env, PATH: tools + ':' + process.env.PATH, HOST_TEST_TRACE: trace,
    HF_TOKEN: 'must-be-unset', RUNPOD_API_KEY: 'must-be-unset', GITHUB_TOKEN: 'must-be-unset',
    CUSTOM_CREDENTIAL: 'must-be-unset', TEST_PASSWORD: 'must-be-unset' };
  const run = (extra = {}, pin = sha, prefix = 'fixture') => spawnSync('bash', [launcher, token, prefix, pin],
    { cwd: repo, env: { ...env, ...extra }, encoding: 'utf8', timeout: 20000 });
  const events = () => existsSync(trace) ? readFileSync(trace, 'utf8').trim().split('\n') : [];
  const job = name => join(repo, 'models/fixture-job', name);
  return { repo, sha, notorch, run, events, job };
}

test('after launcher recovers before, runs after once, and evaluates the fixed pair with bound host provenance', t => {
  const f = fixture(t); const r = f.run(); assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(f.events(), ORDER);
  const manifest = JSON.parse(readFileSync(f.job('host-manifest.json'), 'utf8'));
  assert.equal(manifest.source_commit, f.sha); assert.equal(manifest.notorch_commit, f.notorch);
  assert.equal(manifest.checkout, f.repo); assert.equal(manifest.machine, 'x86_64');
  assert.deepEqual(manifest.launch_inputs, INPUTS);
  assert.deepEqual(manifest.infrastructure_record, fileBinding(f.repo, RECORD_PATH));
  assert.match(manifest.numerical_binaries, /no rebuild/);
  const done = JSON.parse(readFileSync(f.job('completed.json'), 'utf8'));
  assert.deepEqual(done, { status: 'matched_after_evaluation_archived', semantic_audit: 'pending', evaluation: 'models/fixture-eval' });
  assert.equal(readFileSync(f.job('exit-status.txt'), 'utf8'), 'launcher_exit_code=0\n');
  assert.doesNotMatch(r.stdout + r.stderr, /synthetic-test-credential|must-be-unset/);
});

test('wrong source SHA is rejected before installation or model work', t => {
  const f = fixture(t); const r = f.run({}, 'a'.repeat(40));
  assert.notEqual(r.status, 0); assert.match(r.stderr, /checkout must be pinned/);
  assert.deepEqual(f.events(), []); assert.equal(existsSync(f.job('')), false);
});

test('a run prefix different from the committed fresh IDs is rejected before work', t => {
  const f = fixture(t); const r = f.run({}, f.sha, 'other');
  assert.notEqual(r.status, 0); assert.match(r.stderr, /committed continuation inputs do not match/);
  assert.deepEqual(f.events(), []);
});

for (const [name, options] of [
  ['missing inputs', { missingInputs: true }],
  ['malformed pinned inputs', { inputs: { archive_revision: 'main' } }],
  ['changed approved infrastructure bytes', { badInfrastructure: true }],
  ['an ignored uncommitted infrastructure record', { ignoredRecord: true }],
]) {
  test(`${name} stops before installation, model download or archive reads`, t => {
    const f = fixture(t, options); const r = f.run();
    assert.notEqual(r.status, 0); assert.match(r.stderr, /committed continuation inputs do not match/);
    assert.deepEqual(f.events(), []); assert.equal(existsSync(f.job('')), false);
  });
}

test('caller Git overrides cannot redirect validation to another repository or enable fsmonitor', t => {
  const f = fixture(t); const r = f.run({ GIT_DIR: '/missing/caller-repo', GIT_WORK_TREE: '/missing/caller-worktree',
    GIT_CONFIG_COUNT: '1', GIT_CONFIG_KEY_0: 'core.fsmonitor', GIT_CONFIG_VALUE_0: '/missing/caller-monitor' });
  assert.equal(r.status, 0, r.stderr); assert.deepEqual(f.events(), ORDER);
});

test('optimized Python is rejected before installation', t => {
  const f = fixture(t); const r = f.run({ PYTHONOPTIMIZE: '1' });
  assert.notEqual(r.status, 0); assert.match(r.stderr, /unoptimized Python/); assert.deepEqual(f.events(), []);
});

for (const [stage, code, last] of [
  ['recover', 6, 'recover'], ['bind', 8, 'bind'], ['protocol', 4, 'preflight-after'], ['after', 7, 'run-after'],
  ['evaluation', 9, 'evaluate'],
]) {
  test(`${stage} failure halts the pipeline without automatic training restart`, t => {
    const f = fixture(t); const r = f.run({ HOST_TEST_FAIL: stage });
    assert.equal(r.status, code); assert.equal(f.events().at(-1), last);
    assert.deepEqual(f.events(), ORDER.slice(0, ORDER.indexOf(last) + 1));
    assert.equal(readFileSync(f.job('exit-status.txt'), 'utf8'), `launcher_exit_code=${code}\n`);
    assert.equal(existsSync(f.job('completed.json')), false);
    const retry = f.run(); assert.notEqual(retry.status, 0); assert.match(retry.stderr, /fresh output already exists/);
    assert.equal(f.events().filter(v => v === 'run-after').length, ['after', 'evaluation'].includes(stage) ? 1 : 0);
  });
}

test('tracked source mutation after training stops before evaluation', t => {
  const f = fixture(t); const r = f.run({ HOST_TEST_MUTATE: 'after' });
  assert.notEqual(r.status, 0); assert.match(r.stderr, /tracked checkout files have local changes/);
  assert.equal(f.events().at(-1), 'run-after');
});

for (const variant of ['duplicate', 'provenance', 'evaluation']) {
  test(`invalid ${variant} binding stops before native protocol preflight`, t => {
    const f = fixture(t); const r = f.run({ HOST_TEST_BINDINGS: variant });
    assert.notEqual(r.status, 0); assert.match(r.stderr, /bound after plan or host provenance differs/);
    assert.deepEqual(f.events(), ORDER.slice(0, ORDER.indexOf('preflight-after')));
    assert.equal(existsSync(f.job('completed.json')), false);
  });
}

function cloudFixture(t, { occupied = false, brokenWatchdog = false } = {}) {
  const temp = mkdtempSync(join(realpathSync(tmpdir()), 'jovovich-prepare-after-'));
  t.after(() => rmSync(temp, { recursive: true, force: true }));
  const workspace = join(temp, 'workspace'); mkdirSync(workspace);
  const original = join(workspace, 'jovovich/evidence.json'); write(original, 'original evidence\n');
  const bootstrap = join(temp, 'jovovich-runpod-bootstrap.py'); write(bootstrap, '# pinned watchdog\n');
  // Relocate only the fixed mount and watchdog paths so this shell integration
  // test cannot touch the developer's /workspace or /tmp bootstrap.
  const script = readFileSync(prepareSource, 'utf8').replaceAll('/workspace', workspace)
    .replaceAll('/tmp/jovovich-runpod-bootstrap.py', bootstrap);
  const entrypoint = join(temp, 'prepare.sh'); write(entrypoint, script);
  const template = join(temp, 'template'); mkdirSync(template);
  write(join(template, 'training/cloud/prepare_after_host.sh'), script);
  write(join(template, 'training/cloud/runpod_bootstrap.py'), brokenWatchdog ? '# different watchdog\n' : '# pinned watchdog\n');
  write(join(template, 'training/after_recovery/host_launch.sh'), '#!/bin/sh\nprintf "after-child %s %s\\n" "$2" "$3" >> "$HOST_TEST_TRACE"\n');
  command('git', ['init', '-q'], template);
  command('git', ['config', 'user.email', 'fixture@example.invalid'], template);
  command('git', ['config', 'user.name', 'Fixture'], template);
  command('git', ['add', '.'], template); command('git', ['commit', '-qm', 'fixture'], template);
  const sha = command('git', ['rev-parse', 'HEAD'], template);
  const prefix = 'fixture'; const checkout = join(workspace, 'jovovich-after-' + prefix);
  if (occupied) symlinkSync(join(temp, 'missing'), checkout);
  const tools = join(temp, 'tools'); mkdirSync(tools);
  const realGit = command('which', ['git'], template);
  const trace = join(temp, 'trace');
  for (const tool of ['apt-get', 'curl', 'tar', 'sha256sum']) {
    write(join(tools, tool), `#!/bin/sh\nprintf '${tool}\\n' >> "$HOST_TEST_TRACE"\nexit 0\n`, 0o755);
  }
  write(join(tools, 'uname'), '#!/bin/sh\necho x86_64\n', 0o755);
  write(join(tools, 'mountpoint'), '#!/bin/sh\nexit 0\n', 0o755);
  write(join(tools, 'git'), `#!/bin/sh\n[ "$1" = '-c' ] && shift && shift\nif [ "$1" = clone ]; then\n  printf 'clone\\n' >> "$HOST_TEST_TRACE"\n  exec '${realGit}' clone --no-checkout '${template}' "$4"\nfi\nexec '${realGit}' "$@"\n`, 0o755);
  const token = join(temp, 'credential'); write(token, 'synthetic-test-credential\n', 0o600);
  const r = spawnSync('bash', [entrypoint, token, prefix, sha], { cwd: temp,
    env: { ...process.env, PATH: tools + ':' + process.env.PATH, HOST_TEST_TRACE: trace,
      GIT_DIR: '/missing/override', GIT_CONFIG_COUNT: '1', GIT_CONFIG_KEY_0: 'core.fsmonitor', GIT_CONFIG_VALUE_0: '/missing/monitor' },
    encoding: 'utf8', timeout: 20000 });
  const events = existsSync(trace) ? readFileSync(trace, 'utf8').trim().split('\n') : [];
  return { r, events, original, checkout, sha };
}

test('cloud bootstrap uses a new mounted checkout and verifies the pinned watchdog before the after child', t => {
  const f = cloudFixture(t); assert.equal(f.r.status, 0, f.r.stderr);
  assert.equal(readFileSync(f.original, 'utf8'), 'original evidence\n');
  assert.equal(command('git', ['rev-parse', 'HEAD'], f.checkout), f.sha);
  assert.deepEqual(f.events, ['apt-get', 'apt-get', 'curl', 'sha256sum', 'tar', 'clone', 'after-child fixture ' + f.sha]);
});

test('cloud bootstrap refuses an existing checkout symlink before installation', t => {
  const f = cloudFixture(t, { occupied: true }); assert.notEqual(f.r.status, 0);
  assert.match(f.r.stderr, /fresh after checkout required/); assert.deepEqual(f.events, []);
  assert.equal(readFileSync(f.original, 'utf8'), 'original evidence\n');
});

test('cloud bootstrap rejects a watchdog that differs from the pinned commit', t => {
  const f = cloudFixture(t, { brokenWatchdog: true }); assert.notEqual(f.r.status, 0);
  assert.equal(f.events.at(-1), 'clone'); assert.ok(!f.events.some(v => v.startsWith('after-child')));
  assert.equal(readFileSync(f.original, 'utf8'), 'original evidence\n');
});
