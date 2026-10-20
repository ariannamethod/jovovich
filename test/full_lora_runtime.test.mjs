import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdtemp, mkdir, rm } from 'node:fs/promises';
import { execFileSync, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { chunksFor, promptFor, review, fetchModel } from '../bin/jovovich.mjs';

const root = path.resolve(import.meta.dirname, '..');
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const suffix = ' Include a concise analysis string connecting the relevant rule, changed line and consequence.';
function environment(t, values) {
  const old = Object.fromEntries(Object.keys(values).map(k => [k, process.env[k]]));
  for (const [k, v] of Object.entries(values)) v === undefined ? delete process.env[k] : process.env[k] = v;
  t.after(() => { for (const [k, v] of Object.entries(old)) v === undefined ? delete process.env[k] : process.env[k] = v; });
}

test('trained profile matches all 24 delivery prompts byte-for-byte without changing collector defaults', async t => {
  environment(t, { JOVOVICH_PROFILE: 'full-lora' });
  const rows = (await readFile(path.join(root, 'training/review_holdout_v5.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse);
  const identity = await readFile(path.join(root, 'prompts/identity.txt'), 'utf8');
  const code = 'import json,sys;from pathlib import Path;sys.path.insert(0,"training/explanations");from collect_generation import review_cases;print(json.dumps([c["prompt"].decode() for c in review_cases(Path("training/review_holdout_v5.jsonl").read_bytes(),split="holdout")]))';
  const delivery = JSON.parse(execFileSync('python3', ['-c', code], { cwd: root, encoding: 'utf8' }));
  assert.equal(delivery.length, 24);
  for (const [i, row] of rows.entries()) {
    const [chunk] = chunksFor(row.files);
    const legacy = await promptFor(chunk, row.context, identity, 'chatml');
    const trained = await promptFor(chunk, row.context, identity, 'chatml', 'full-lora');
    assert.equal(trained, delivery[i], row.id);
    assert.equal(trained.split(suffix).length - 1, 1);
    assert.equal(legacy.includes(suffix), false, 'four-argument collector renderer must remain base');
  }
});

test('review forwards explicit trained profile; incompatible templates and misspelled profiles fail', async () => {
  const input = { context: {}, files: [{ path: 'x.c', patch: '@@ -0,0 +1 @@\n+return 0;' }] };
  const calls = [];
  const result = await review(input, async (...args) => { calls.push(args); return '{"analysis":"Clean.","findings":[]}'; }, 'full-lora');
  assert.equal(result.prompt_profile, 'full-lora');
  assert.equal(calls.length, 1);
  assert.ok(calls[0][0].endsWith(suffix + '<|im_end|>\n<|im_start|>assistant\n'));
  assert.deepEqual(calls[0].slice(1), [512, 'full-lora']);
  await assert.rejects(promptFor(chunksFor(input.files)[0], {}, 'identity', 'qwen3-no-think', 'full-lora'), /requires.*ChatML/);
  await assert.rejects(review(input, async () => { throw new Error('must not run'); }, 'typo'), /Unknown model prompt profile/);
});

test('separate lock fetches its exact pinned artifact without promoting model.json', async t => {
  const directory = await mkdtemp(path.join(tmpdir(), 'jovovich-lock-'));t.after(() => rm(directory, { recursive: true, force: true }));
  const bytes = Buffer.from('independent trained GGUF fixture');
  const lock = { name: 'fixture', stage: 'trained-fixture', repo: 'ataeff/jovovich', revision: 'a'.repeat(40), file: 'release/jovovich.gguf', sha256: sha(bytes), bytes: bytes.length, prompt_profile: 'full-lora' };
  const lockFile = path.join(directory, 'trained.json');await writeFile(lockFile, JSON.stringify(lock));
  const dest = path.join(directory, 'trained.gguf');environment(t, { JOVOVICH_MODEL: dest, JOVOVICH_MODEL_LOCK: lockFile });
  const oldFetch = globalThis.fetch;t.after(() => { globalThis.fetch = oldFetch; });let count = 0;
  globalThis.fetch = async url => { count++;assert.equal(url, `https://huggingface.co/ataeff/jovovich/resolve/${lock.revision}/release/jovovich.gguf`);return new Response(bytes); };
  const originalLock = await readFile(path.join(root, 'model.json'));
  await fetchModel();await fetchModel();assert.equal(count, 1);
  assert.deepEqual(await readFile(dest), bytes);assert.deepEqual(await readFile(path.join(root, 'model.json')), originalLock);
});

test('CLI explicit lock binds custom model, selects trained prompt and F32 inference; mismatch fails before execution', async t => {
  const directory = await mkdtemp(path.join(tmpdir(), 'jovovich-profile-'));t.after(() => rm(directory, { recursive: true, force: true }));
  const repo = path.join(directory, 'repo');await mkdir(repo);
  const git = (...args) => execFileSync('git', ['-C', repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', ...args], { stdio: 'pipe' });
  git('init');await writeFile(path.join(repo, 'a.c'), 'return 0;\n');git('add', '.');git('commit', '-m', 'base');await writeFile(path.join(repo, 'a.c'), 'return 1;\n');git('commit', '-am', 'change');
  const model = path.join(directory, 'model.gguf'), exe = path.join(directory, 'native.mjs'), capture = path.join(directory, 'capture.json'), lockFile = path.join(directory, 'trained.json');
  const bytes = Buffer.from('trained fixture body');await writeFile(model, bytes);
  await writeFile(lockFile, JSON.stringify({ stage: 'trained-fixture', bytes: bytes.length, sha256: sha(bytes), prompt_profile: 'full-lora' }));
  await writeFile(exe, `#!${process.execPath}\nimport{writeFileSync}from'node:fs';let prompt='';for await(const b of process.stdin)prompt+=b;writeFileSync(process.env.PROFILE_CAPTURE,JSON.stringify({prompt,argv:process.argv.slice(2),precision:process.env.NT_NO_I8,threads:process.env.OPENBLAS_NUM_THREADS}));console.log('{"analysis":"Clean.","findings":[]}');\n`, { mode: 0o755 });
  const env = { ...process.env, JOVOVICH_MODEL: model, JOVOVICH_INFER: exe, PROFILE_CAPTURE: capture, NT_NO_I8: '0' };delete env.JOVOVICH_PROFILE;delete env.JOVOVICH_MODEL_LOCK;delete env.JOVOVICH_CHAT_TEMPLATE;
  const args = [path.join(root, 'bin/jovovich.mjs'), 'review', '--repo', repo, '--model-lock', lockFile];
  let run = spawnSync(process.execPath, args, { env, encoding: 'utf8' });assert.equal(run.status, 0, run.stderr);assert.match(run.stdout, /trained-fixture weights · full-lora prompt/);
  const observed = JSON.parse(await readFile(capture, 'utf8'));assert.equal(observed.precision, '1');assert.equal(observed.threads, '4');assert.ok(observed.prompt.endsWith(suffix + '<|im_end|>\n<|im_start|>assistant\n'));assert.deepEqual(observed.argv, ['--model', model, '--tokens', '512', '--context', '8192', '--temperature', '0']);
  await rm(capture);await writeFile(model, 'wrong');run = spawnSync(process.execPath, args, { env, encoding: 'utf8' });assert.equal(run.status, 1);assert.match(run.stderr, /does not match.*checksum/);await assert.rejects(readFile(capture), { code: 'ENOENT' });
});
