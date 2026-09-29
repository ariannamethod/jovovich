import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
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

function pack(rows, extra = []) {
  const dir = mkdtempSync(path.join(tmpdir(), 'jovovich-pairs-'));
  const input = path.join(dir, 'sft.jsonl');
  const output = path.join(dir, 'sft.bin');
  const pairs = path.join(dir, 'pairs.bin');
  writeFileSync(input, rows.map(r => JSON.stringify(r)).join('\n') + '\n');
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
