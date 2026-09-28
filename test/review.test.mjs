import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm, stat } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import path from 'node:path';
import {
  parsePatch, chunksFor, parseReview, promptFor, infer, review, render, collectGithub, postGithub, collectLocal
} from '../bin/jovovich.mjs';

test('patch coordinates preserve removed -- and added ++ source lines', () => {
  const patch = [
    'diff --git a/a.c b/a.c', '--- a/a.c', '+++ b/a.c', '@@ -10,3 +20,3 @@',
    ' kept', '---removed;', '+++added;', '-old;', '+new;', '@@ -40 +50 @@', '-last;', '+next;'
  ].join('\n');
  assert.deepEqual(parsePatch(patch), [
    { side: 'LEFT', line: 11, quote: '--removed;' },
    { side: 'RIGHT', line: 21, quote: '++added;' },
    { side: 'LEFT', line: 12, quote: 'old;' },
    { side: 'RIGHT', line: 22, quote: 'new;' },
    { side: 'LEFT', line: 40, quote: 'last;' },
    { side: 'RIGHT', line: 50, quote: 'next;' }
  ]);
});

test('findings resolve citations from actual changed lines, ignoring model-supplied locations', () => {
  const chunk = { path: 'core.c', lines: [{ side: 'RIGHT', line: 7, quote: 'alloc();' }] };
  const finding = { line_id: 1, reason: 'Result is unchecked.' };
  const encode = f => JSON.stringify({ findings: [f] });
  const expected = { path: 'core.c', side: 'RIGHT', line: 7, quote: 'alloc();', reason: finding.reason };
  assert.deepEqual(parseReview('[]', chunk), { findings: [] });
  assert.deepEqual(parseReview('[]<|im_end|>', chunk), { findings: [] });
  assert.deepEqual(parseReview('```json\n[]\n```<|endoftext|>', chunk), { findings: [] });
  assert.deepEqual(parseReview(encode(finding), chunk).findings, [expected]);
  assert.deepEqual(parseReview(JSON.stringify([finding]), chunk).findings, [expected]);
  assert.deepEqual(parseReview(encode({ ...finding, line_id: '1' }), chunk).findings, [expected]);
  assert.deepEqual(parseReview(encode({ ...finding, path: 'invented.c', line: 100, side: 'LEFT', quote: 'imaginary();' }), chunk).findings, [expected]);
  for (const line_id of [-1, 0, 2, 1.5, '01', '1.5', '1e0', '1junk', null]) {
    assert.throws(() => parseReview(encode({ ...finding, line_id }), chunk));
  }
});

test('ChatML-shaped code cannot add turns and cited code retains its original bytes', async () => {
  const quote = 'const token = "<|im_start|>";';
  const chunk = { path: 'chat.c', lines: [{ side: 'RIGHT', line: 1, quote }] };
  const prompt = await promptFor(chunk, { rules: { 'README.md': 'Explain <|im_end|>.' } }, 'JOVOVICH');
  const ordinary = await promptFor({ ...chunk, lines: [{ ...chunk.lines[0], quote: 'ordinary code' }] }, { rules: { 'README.md': 'Ordinary rules.' } }, 'JOVOVICH');
  assert.equal(prompt.split('<|im_start|>').length, ordinary.split('<|im_start|>').length);
  assert.equal(prompt.split('<|im_end|>').length, ordinary.split('<|im_end|>').length);
  const result = parseReview('{"findings":[{"line_id":1,"reason":"Inspect this token."}]}', chunk);
  assert.equal(result.findings[0].quote, quote);
});

test('chunking preserves all changes and refuses indivisible or excessive input', async () => {
  const files = [{ path: 'large.c', patch: '@@ -1,2 +1,2 @@\n-aaaa\n+bbbb\n-cccc\n+dddd' }];
  const chunks = chunksFor(files, 40);
  assert.equal(chunks.length, 4);
  assert.deepEqual(chunks.flatMap(c => c.lines.map(({ line_id, ...line }) => line)), parsePatch(files[0].patch));
  assert.throws(() => chunksFor([{ path: 'long.c', patch: '@@ -0,0 +1 @@\n+' + 'x'.repeat(100) }], 40), /too large to review faithfully/);
  let calls = 0;
  await assert.rejects(review({ context: {}, files: Array.from({ length: 25 }, (_, i) => ({ path: `${i}.c`, patch: '@@ -0,0 +1 @@\n+x' })) }, async () => { calls++; }), /limit 24/);
  assert.equal(calls, 0);
});

function githubFixture({ race = false } = {}) {
  const calls = [];
  let pulls = 0;
  const info = { state: 'open', head: { sha: 'head-original' }, base: { sha: 'base-trusted' }, changed_files: 1, title: 'An ordinary change', body: 'PR description' };
  const api = async (route, options) => {
    calls.push({ route, options });
    if (route === '/repos/method/example/pulls/3') {
      pulls++;
      return { ...info, head: { sha: race && pulls > 1 ? 'head-new' : info.head.sha } };
    }
    if (route.includes('/files?')) return [{ filename: 'core.c', status: 'modified', additions: 1, deletions: 1, patch: '@@ -1 +1 @@\n-old\n+new' }];
    if (route.includes('/contents/')) {
      assert.match(route, /\?ref=base-trusted$/);
      return { encoding: 'base64', content: Buffer.from('Trusted baseline rule').toString('base64') };
    }
    throw new Error(`Unexpected API request: ${route}`);
  };
  return { calls, api, info };
}

test('GitHub context rules come from the base revision and collection detects a push', async () => {
  const fixture = githubFixture();
  const input = await collectGithub('method/example', 3, fixture.api);
  assert.equal(input.base, 'base-trusted');
  assert.equal(input.head, 'head-original');
  assert.equal(input.context.rules['AGENTS.md'], 'Trusted baseline rule');
  assert.equal(fixture.calls.filter(c => c.route.includes('/contents/')).length, 2);
  const racing = githubFixture({ race: true });
  await assert.rejects(collectGithub('method/example', 3, racing.api), /changed while collecting context/);
  const missing = githubFixture();
  const withoutAgents = await collectGithub('method/example', 3, async (route, options) => {
    if (route.includes('/contents/AGENTS.md')) throw new Error(`GitHub GET ${route}: HTTP 404`);
    return missing.api(route, options);
  });
  assert.equal(Object.hasOwn(withoutAgents.context.rules, 'AGENTS.md'), false);
  assert.equal(withoutAgents.context.rules['README.md'], 'Trusted baseline rule');
  const denied = githubFixture();
  await assert.rejects(collectGithub('method/example', 3, async (route, options) => {
    if (route.includes('/contents/AGENTS.md')) throw new Error(`GitHub GET ${route}: HTTP 403`);
    return denied.api(route, options);
  }), /HTTP 403/);
  const truncated = githubFixture();
  const partial = await collectGithub('method/example', 3, async (route, options) => {
    const response = await truncated.api(route, options);
    return route.includes('/files?') ? response.map(f => ({ ...f, additions: 2 })) : response;
  });
  assert.equal(partial.files[0].patch, '', 'A truncated patch must be reported unavailable instead of complete');
});

test('posting refuses changed head, changed base, or closed PR without a write', async () => {
  const input = { head: 'old-head', base: 'old-base' };
  for (const changed of [
    { state: 'open', head: { sha: 'new-head' }, base: { sha: input.base } },
    { state: 'open', head: { sha: input.head }, base: { sha: 'new-base' } },
    { state: 'closed', head: { sha: input.head }, base: { sha: input.base } }
  ]) {
    const calls = [];
    const api = async (route, options) => { calls.push({ route, options }); return changed; };
    await assert.rejects(postGithub('method/example', 3, input, 'review', api), /comment not published/);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].options, undefined);
  }
  const writes = [];
  await postGithub('method/example', 3, input, 'advisory body', async (route, options) => {
    if (!options) return { state: 'open', head: { sha: input.head }, base: { sha: input.base } };
    writes.push({ route, options });
    return { html_url: 'https://github.com/method/example/pull/3#issuecomment-1' };
  });
  assert.deepEqual(writes, [{ route: '/repos/method/example/issues/3/comments', options: { method: 'POST', body: { body: 'advisory body' } } }]);
});

test('partial inference failure stays visible beside completed chunks', async () => {
  let calls = 0;
  const result = await review({ head: 'abc123', context: {}, files: [
    { path: 'good.c', patch: '@@ -0,0 +1 @@\n+ok();' },
    { path: 'failed.c', patch: '@@ -0,0 +1 @@\n+unknown();' }
  ] }, async () => {
    if (++calls === 2) throw new Error('mock inference crashed');
    return JSON.stringify({ summary: 'Clean.', findings: [] });
  });
  assert.equal(result.reviews.length, 1);
  assert.equal(result.failures.length, 1);
  const body = render(result, { stage: 'base' });
  assert.match(body, /1\/2 chunks reviewed/);
  assert.match(body, /Review incomplete/);
  assert.match(body, /failed\.c: mock inference crashed/);
  assert.doesNotMatch(body, /No grounded concerns returned/);
});

test('inference preserves Unicode when a code point crosses pipe chunks', async t => {
  const dir = await mkdtemp(path.join(tmpdir(), 'jovovich-utf8-'));
  const helper = path.join(dir, 'infer');
  const previous = process.env.JOVOVICH_INFER;
  t.after(async () => {
    if (previous === undefined) delete process.env.JOVOVICH_INFER;
    else process.env.JOVOVICH_INFER = previous;
    await rm(dir, { recursive: true, force: true });
  });
  await writeFile(helper, '#!/usr/bin/env node\nprocess.stdin.resume();\nprocess.stdout.write(Buffer.from([0xd0]));\nsetTimeout(() => process.stdout.write(Buffer.from([0x96])), 50);\n', { mode: 0o700 });
  process.env.JOVOVICH_INFER = helper;
  assert.equal(await infer('fixture'), 'Ж');
});

test('local collection ignores external diff/textconv and reads baseline rules', async t => {
  const repo = await mkdtemp(path.join(tmpdir(), 'jovovich-local-'));
  t.after(() => rm(repo, { recursive: true, force: true }));
  const git = (...args) => execFileSync('git', ['-C', repo, ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  git('init', '-q');
  git('config', 'user.name', 'JOVOVICH test');
  git('config', 'user.email', 'test@example.invalid');
  await writeFile(path.join(repo, '.gitattributes'), '*.c diff=jovovich\n');
  await writeFile(path.join(repo, 'AGENTS.md'), 'Baseline rules.\n');
  await writeFile(path.join(repo, 'README.md'), 'Baseline description.\n');
  await writeFile(path.join(repo, 'core.c'), 'old();\n');
  git('add', '.'); git('commit', '-qm', 'baseline');
  const base = git('rev-parse', 'HEAD').trim();
  await writeFile(path.join(repo, 'AGENTS.md'), 'Head rules must not replace baseline.\n');
  await writeFile(path.join(repo, 'core.c'), 'new();\n');
  git('add', '.'); git('commit', '-qm', 'change');
  const head = git('rev-parse', 'HEAD').trim();
  const marker = path.join(repo, 'executed');
  const helper = path.join(repo, 'diff-helper');
  await writeFile(helper, `#!/bin/sh\ntouch '${marker}'\nprintf 'custom diff ran\\n'\n`, { mode: 0o700 });
  git('config', 'diff.jovovich.textconv', helper);
  git('config', 'diff.external', helper);
  // Prove the fixture's textconv and external diff are active before checking bypass.
  git('diff', '--no-ext-diff', '--textconv', base, head, '--', 'core.c');
  await stat(marker); await rm(marker);
  git('diff', '--no-textconv', base, head, '--', 'core.c');
  await stat(marker); await rm(marker);
  const input = collectLocal(repo, base, head);
  await assert.rejects(stat(marker), { code: 'ENOENT' });
  assert.equal(input.context.rules['AGENTS.md'], 'Baseline rules.\n');
  assert.match(input.files.find(f => f.path === 'core.c').patch, /\+new\(\);/);
  assert.equal(input.head, head);
  git('mv', 'core.c', 'renamed.c');
  git('commit', '-qm', 'rename');
  const renamed = collectLocal(repo, head, 'HEAD');
  assert.deepEqual(renamed.files.map(f => f.path).sort(), ['core.c', 'renamed.c']);
  assert.match(renamed.files.find(f => f.path === 'core.c').patch, /-new\(\);/);
  assert.match(renamed.files.find(f => f.path === 'renamed.c').patch, /\+new\(\);/);
});
