import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync, rmSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const row = (kind, pair, findings) => ({
  kind, pair,
  messages: [
    { role: 'system', content: 'Review the supplied change.' },
    { role: 'user', content: 'A changed line.' },
    { role: 'assistant', content: JSON.stringify({ findings }) },
  ],
});
const concern = [{ line_id: 1, reason: 'The owner is overwritten on failure.' }];

function pack(rows, extra = [], existing = null) {
  const dir = mkdtempSync(path.join(tmpdir(), 'jovovich-pairs-'));
  const input = path.join(dir, 'sft.jsonl');
  const output = path.join(dir, 'sft.bin');
  const pairs = path.join(dir, 'pairs.bin');
  writeFileSync(input, rows.map(r => JSON.stringify(r)).join('\n') + '\n');
  if (existing !== null) {
    writeFileSync(output, existing);
    writeFileSync(pairs, existing);
  }
  const result = spawnSync('python3', ['training/prepare.py', output, '--sft', input,
    '--sft-only', '--review-pairs', pairs, ...extra.map(x => x === '$output' ? output : x)], { encoding: 'utf8' });
  return { dir, output, pairs, result };
}

test('review pair maps retain original row indices and concern/clean direction', () => {
  const p = pack([row('review', 'owner', []), row('code', null, []),
    row('review', 'owner', concern), row('review', 'scope', concern), row('review', 'scope', [])]);
  try {
    assert.equal(p.result.status, 0, p.result.stderr);
    const bytes = readFileSync(p.pairs);
    assert.equal(bytes.length, 32);
    assert.deepEqual([...bytes.subarray(0, 8)], [74, 86, 80, 82, 1, 0, 0, 0]);
    assert.deepEqual([8, 12, 16, 20, 24, 28].map(i => bytes.readUInt32LE(i)), [5, 2, 2, 0, 3, 4]);
    assert.equal(readFileSync(p.output).readUInt32LE(8), 5);
  } finally { rmSync(p.dir, { recursive: true, force: true }); }
});

const withAnswer = (pair, answer) => {
  const result = row('review', pair, []);
  result.messages[2].content = answer;
  return result;
};

function decodeV2(bytes) {
  assert.deepEqual([...bytes.subarray(0, 8)], [74, 86, 80, 82, 2, 0, 0, 0]);
  const rows = bytes.readUInt32LE(8);
  const count = bytes.readUInt32LE(12);
  let offset = 16;
  const pairs = [];
  for (let i = 0; i < count; i++) {
    const concern = bytes.readUInt32LE(offset);
    const clean = bytes.readUInt32LE(offset + 4);
    offset += 8;
    const prefixes = [];
    for (let side = 0; side < 2; side++) {
      const size = bytes.readUInt32LE(offset);
      offset += 4;
      prefixes.push(bytes.subarray(offset, offset + size).toString('utf8'));
      assert.equal(Buffer.byteLength(prefixes.at(-1)), size);
      offset += size;
    }
    pairs.push({ concern, clean, prefixes });
  }
  assert.equal(offset, bytes.length, 'no trailing bytes in the pair map');
  return { rows, pairs };
}

test('JVPR2 records independent exact Unicode prefixes and ignores structural decoys', () => {
  const cleanPrefix = ' \n{ "analysis" : "Чисто. 🪶", "findings';
  const concernPrefix = '{"analysis":{"findings":[],"note":"The string \\\"findings\\\" is a decoy; naïve search loses. \\u2603"},\n  "findings';
  const rows = [withAnswer('owner', cleanPrefix + '":[] }'), row('code', null, []),
    withAnswer('owner', concernPrefix + '":' + JSON.stringify(concern) + ',"after":true}')];
  const v2 = pack(rows, ['--pair-format', '2']);
  const v1 = pack(rows);
  try {
    assert.equal(v2.result.status, 0, v2.result.stderr);
    assert.equal(v1.result.status, 0, v1.result.stderr);
    assert.deepEqual(decodeV2(readFileSync(v2.pairs)), {
      rows: 3, pairs: [{ concern: 2, clean: 0, prefixes: [concernPrefix, cleanPrefix] }],
    });
    assert.deepEqual(readFileSync(v2.output), readFileSync(v1.output), 'JVDS is format-independent');
    const helper = spawnSync('python3', ['-c',
      'import json,sys; from pathlib import Path; from training.prepare import review_prefixes; print(json.dumps(review_prefixes([json.loads(s) for s in Path(sys.argv[1]).read_text().splitlines()]),ensure_ascii=False))',
      path.join(v2.dir, 'sft.jsonl')], { encoding: 'utf8' });
    assert.equal(helper.status, 0, helper.stderr);
    assert.deepEqual(JSON.parse(helper.stdout), { 0: cleanPrefix, 2: concernPrefix });
  } finally {
    rmSync(v2.dir, { recursive: true, force: true });
    rmSync(v1.dir, { recursive: true, force: true });
  }
});

test('JVPR2 rejects spacing at the verdict branch and nonobject concern findings; JVPR1 stays unchanged', () => {
  for (const [answer, side, error] of [
    ['{"analysis":"bad dependency","findings" : [{"message":"bad"}]}', 'concern', /compact findings boundary/],
    ['{"findings": [{"message":"bad"}]}', 'concern', /compact findings boundary/],
    ['{"findings":[ {"message":"bad"}]}', 'concern', /compact findings boundary/],
    ['{"findings" :[]}', 'clean', /compact findings boundary/],
    ['{"findings": []}', 'clean', /compact findings boundary/],
    ['{"findings":[ ]}', 'clean', /compact findings boundary/],
    ['{"findings":["bad"]}', 'concern', /arrays of objects/],
    ['{"findings":[1]}', 'concern', /arrays of objects/],
    ['{"findings":[null]}', 'concern', /arrays of objects/],
    ['{"findings":[{"message":"bad"},false]}', 'concern', /arrays of objects/],
  ]) {
    const rows = [withAnswer('owner', answer), row('review', 'owner', side === 'clean' ? concern : [])];
    const v2 = pack(rows, ['--pair-format', '2']);
    const v1 = pack(rows);
    try {
      assert.notEqual(v2.result.status, 0, answer);
      assert.match(v2.result.stderr, error, answer);
      assert.equal(existsSync(v2.output), false);
      assert.equal(existsSync(v2.pairs), false);
      assert.equal(v1.result.status, 0, v1.result.stderr);
    } finally {
      rmSync(v2.dir, { recursive: true, force: true });
      rmSync(v1.dir, { recursive: true, force: true });
    }
  }
});

test('JVPR2 rejects duplicate keys, escaped top-level keys and malformed JSON before writing', () => {
  for (const answer of [
    '{"findings":[],"findings":' + JSON.stringify(concern) + '}',
    '{"analysis":{"x":1,"x":2},"findings":' + JSON.stringify(concern) + '}',
    String.raw`{"find\u0069ngs":` + JSON.stringify(concern) + '}',
    String.raw`{"anal\u0079sis":"reason","findings":` + JSON.stringify(concern) + '}',
    '{"findings":' + JSON.stringify(concern) + ',"after":NaN}',
    '{"findings":' + JSON.stringify(concern) + '} trailing',
    '{"findings":' + JSON.stringify(concern),
    JSON.stringify({ findings: 'not an array' }),
  ]) {
    const p = pack([withAnswer('owner', answer), row('review', 'owner', [])], ['--pair-format', '2']);
    try {
      assert.notEqual(p.result.status, 0, answer);
      assert.equal(existsSync(p.output), false, 'invalid data must not create JVDS');
      assert.equal(existsSync(p.pairs), false, 'invalid data must not create JVPR');
    } finally { rmSync(p.dir, { recursive: true, force: true }); }
  }
});

test('JVPR2 retains pair-completeness checks and preserves existing outputs on validation failure', () => {
  for (const rows of [
    [row('review', 'owner', concern)],
    [row('review', 'owner', concern), row('review', 'owner', concern)],
    [withAnswer('owner', '{"findings":[],"findings":' + JSON.stringify(concern) + '}'), row('review', 'owner', [])],
    [row('review', 'owner', concern), row('review', 'owner', []),
      { ...row('code', null, []), messages: row('code', null, []).messages.map((m, i) => i === 2 ? { ...m, content: 17 } : m) }],
  ]) {
    const p = pack(rows, ['--pair-format', '2'], 'previous artifact');
    try {
      assert.notEqual(p.result.status, 0);
      assert.equal(readFileSync(p.output, 'utf8'), 'previous artifact');
      assert.equal(readFileSync(p.pairs, 'utf8'), 'previous artifact');
    } finally { rmSync(p.dir, { recursive: true, force: true }); }
  }
});

test('pair format 2 requires a map and unknown formats fail', () => {
  const missing = spawnSync('python3', ['training/prepare.py', 'unused.bin', '--sft-only', '--pair-format', '2'], { encoding: 'utf8' });
  assert.notEqual(missing.status, 0);
  assert.match(missing.stderr, /--pair-format 2 requires --review-pairs/);
  const p = pack([row('review', 'owner', concern), row('review', 'owner', [])], ['--pair-format', '3']);
  try {
    assert.notEqual(p.result.status, 0);
    assert.equal(existsSync(p.output), false);
    assert.equal(existsSync(p.pairs), false);
  } finally { rmSync(p.dir, { recursive: true, force: true }); }
});

test('the fixed 52-review v5 curriculum preserves JVDS and legacy JVPR1 bytes', () => {
  const rows = readFileSync('training/sft_review_v5.jsonl', 'utf8').trim().split('\n').map(s => JSON.parse(s));
  assert.equal(rows.filter(r => r.kind === 'review').length, 52);
  const v1 = pack(rows);
  const v2 = pack(rows, ['--pair-format', '2']);
  try {
    assert.equal(v1.result.status, 0, v1.result.stderr);
    assert.equal(v2.result.status, 0, v2.result.stderr);
    const digest = bytes => createHash('sha256').update(bytes).digest('hex');
    assert.equal(digest(readFileSync(v1.output)), '54636d0d1d2c95d1fce45243d8ae3a6d1268a560dcdb07e943cff4bd9d7eacce');
    assert.equal(digest(readFileSync(v1.pairs)), 'c9e42c3055f3c719531c5ec304ee8ab579a93a724d1a6e44ec814f10382cc472');
    assert.deepEqual(readFileSync(v1.output), readFileSync(v2.output));
    const parsed = decodeV2(readFileSync(v2.pairs));
    assert.equal(parsed.rows, 76);
    assert.equal(parsed.pairs.length, 26);
    for (const pair of parsed.pairs) assert.deepEqual(pair.prefixes, ['{"findings', '{"findings']);
  } finally {
    rmSync(v1.dir, { recursive: true, force: true });
    rmSync(v2.dir, { recursive: true, force: true });
  }
});

test('review pair preparation rejects incomplete, duplicate and malformed partners', () => {
  for (const rows of [
    [row('review', 'owner', concern)],
    [row('review', 'owner', concern), row('review', 'owner', concern)],
    [row('review', 'owner', 'not an array'), row('review', 'owner', [])],
  ]) {
    const p = pack(rows);
    try { assert.notEqual(p.result.status, 0); }
    finally { rmSync(p.dir, { recursive: true, force: true }); }
  }
});

test('pair maps require SFT-only packing and a distinct output', () => {
  const result = spawnSync('python3', ['training/prepare.py', 'unused.bin', '--review-pairs', 'unused-pairs.bin'], { encoding: 'utf8' });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /requires --sft-only/);
  const p = pack([row('review', 'owner', concern), row('review', 'owner', [])], ['--review-pairs', '$output']);
  try {
    assert.notEqual(p.result.status, 0);
    assert.match(p.result.stderr, /distinct output paths/);
  } finally { rmSync(p.dir, { recursive: true, force: true }); }
});
