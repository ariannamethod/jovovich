// Freeze every supplied production ChatML prompt before model generation.
import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { chunksFor, promptFor } from '../../../bin/jovovich.mjs';
const root = process.cwd();
const raw = await readFile('training/review_holdout_v5.jsonl');
assert.equal(createHash('sha256').update(raw).digest('hex'), 'e066e033cd339243b0eb099291c69540cb183e725d1643f5c4e04af9e6c22451');
const rows = raw.toString().trim().split('\n').map(JSON.parse);
assert.equal(rows.length, 24);
const identity = await readFile('prompts/identity.txt', 'utf8');
const cases = [];
for (const [index, row] of rows.entries()) {
  const chunks = chunksFor(row.files); assert.equal(chunks.length, 1);
  const prompt = await promptFor(chunks[0], row.context, identity, 'chatml');
  assert.ok(prompt.endsWith('<|im_start|>assistant\n'));
  cases.push({index, name: row.id, pair: row.pair, prompt,
    prompt_sha256: createHash('sha256').update(prompt).digest('hex'), chunk: chunks[0],
    expected_concern: row.expected_concern, expected_line_ids: row.expected_line_ids,
    expected_reason_concept: row.expected_reason_concept, audit_metadata: row.audit_metadata});
}
assert.equal(new Set(cases.map(c => c.name)).size, 24);
const pairs = new Map();
for (const c of cases) pairs.set(c.pair, [...(pairs.get(c.pair) ?? []), c.expected_concern]);
assert.equal(pairs.size, 12);
for (const pair of pairs.values()) assert.deepEqual(pair.sort(), [false, true]);
await writeFile('training/results/2026-10-02-checkpoint-control/cases.jsonl', cases.map(c => JSON.stringify(c)+'\n').join(''), {flag:'wx'});
console.log(JSON.stringify({cases: cases.length, pairs: pairs.size, repository_root: root, model_forward_calls: 0}));
