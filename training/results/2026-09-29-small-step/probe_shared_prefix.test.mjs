import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { PREFIX, PREFIX_IDS, verifyBoundary, assess, casesFor, matchingNatural, shardIndices } from './probe_shared_prefix.mjs';

test('common prefix ends before both native verdict targets and refuses boundary changes', () => {
  assert.equal(PREFIX, '{"findings');
  const original = [151644, 123, 10], supplied = [...original, ...PREFIX_IDS];
  for (const next of [66582, 788]) verifyBoundary(original, supplied, [...supplied, next, 151645], next);
  assert.throws(() => verifyBoundary(original, [...supplied, 788], null), /exactly the three/);
  assert.throws(() => verifyBoundary(original, [...original, 4913, 819], null), /exactly the three/);
  assert.throws(() => verifyBoundary(original, supplied, [...supplied.slice(0, -1), 111, 788], 788), /gold answer/);
  assert.throws(() => verifyBoundary(original, supplied, [...supplied, 66582], 788), /first divergent/);
});

test('assembled common prefix permits clean and concern; invalid citations retain their JSON choice', () => {
  const chunk = { path: 'src/a.c', lines: [{ side: 'RIGHT', line: 2, quote: 'x();' }] };
  const clean = assess(PREFIX + '":[]}', chunk);
  assert.equal(clean.concern, false); assert.equal(clean.citation_error, null);
  const concern = assess(PREFIX + '":[{"line_id":1,"reason":"A concrete conflict."}]}', chunk);
  assert.equal(concern.concern, true); assert.equal(concern.citation_error, null);
  const bad = assess(PREFIX + '":[{"line_id":2,"reason":"Unavailable line."}]}', chunk);
  assert.equal(bad.concern, true); assert.match(bad.citation_error, /citation/);
  assert.equal(assess('```json\n[]\n```', chunk).concern, false);
  assert.equal(assess(PREFIX + 'broken', chunk).concern, null);
});

test('all 20 training pairs exactly match prior natural prompt hashes and both outcomes', async () => {
  const { cases } = await casesFor('train');
  const rows = (await readFile('training/results/2026-09-29-decision-only/train-generation.jsonl', 'utf8')).trim().split('\n').map(JSON.parse);
  const natural = matchingNatural(cases, rows, rows[0].model_sha256);
  assert.equal(cases.length, 40); assert.equal(natural.length, 40);
  assert.equal(cases.filter(c => c.expected_concern).length, 20);
  assert.ok(natural.every(r => r.response === '```json\n[]\n```'));
  const changed = structuredClone(rows); changed[0].prompt_sha256 = 'wrong';
  assert.throws(() => matchingNatural(cases, changed, rows[0].model_sha256), /prompt mismatch/);
  assert.throws(() => matchingNatural(cases, rows, 'wrong-model'), /model mismatch/);
  assert.throws(() => matchingNatural(cases, rows.slice(1), rows[0].model_sha256), /exact cohort/);
  assert.throws(() => matchingNatural(cases, [...rows.slice(1), rows[1]], rows[0].model_sha256), /duplicate/);
  const first = cases[0];
  assert.equal(createHash('sha256').update(first.prompt).digest('hex'), rows[0].prompt_sha256);
});

test('all six runtime pairs exactly match prior natural host prompts', async () => {
  const { cases } = await casesFor('runtime');
  const rows = (await readFile('training/results/2026-09-29-decision-only/review.jsonl', 'utf8')).trim().split('\n').map(JSON.parse);
  assert.equal(matchingNatural(cases, rows, rows[0].model_sha256).length, 12);
  assert.equal(cases.filter(c => c.expected_concern).length, 6);
});

test('two worker shards cover all 40 original review indices exactly once', () => {
  const even = shardIndices(40, 0), odd = shardIndices(40, 1);
  assert.equal(even.length, 20); assert.equal(odd.length, 20);
  assert.deepEqual([...even, ...odd].sort((a, b) => a - b), shardIndices(40, null));
  assert.equal(new Set([...even, ...odd]).size, 40);
  assert.throws(() => shardIndices(40, 2), /shard/);
});
