import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdtemp, mkdir, rm } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { buildHoldoutV5, runHoldoutWitnesses, holdoutFeatures, HOLDOUT_OUTPUT, HOLDOUT_DESIGN } from '../training/build_holdout_v5.mjs';
import { chunksFor, parseReview } from '../bin/jovovich.mjs';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

test('fresh evaluation quartets reproduce production prompts with matched non-token cues', async () => {
  const built = await buildHoldoutV5(ROOT);
  assert.equal(await readFile(path.join(ROOT, HOLDOUT_OUTPUT), 'utf8'), built.data);
  assert.equal((await buildHoldoutV5(ROOT)).data, built.data);
  assert.equal(built.rows.length, 24);
  assert.equal(built.rows.filter(r => r.expected_concern).length, 12);
  assert.equal(new Set(built.rows.map(r => r.audit_metadata.family)).size, 6);
  const byId = new Map(built.rows.map(r => [r.id, r]));
  for (let i = 0; i < built.rows.length; i++) {
    const row = built.rows[i], mate = byId.get(row.audit_metadata.semantic_counterpart);
    assert.ok(mate && mate.expected_concern !== row.expected_concern);
    assert.deepEqual(holdoutFeatures(row.files[0].patch), holdoutFeatures(mate.files[0].patch));
    assert.deepEqual(chunksFor(row.files)[0].lines, chunksFor(mate.files)[0].lines);
    assert.deepEqual(row.context, mate.context);
    assert.ok(built.prompts[i].prompt.endsWith('<|im_start|>assistant\n'));
    assert.ok(!built.prompts[i].prompt.includes(row.id));
    assert.ok(!built.prompts[i].prompt.includes(row.audit_metadata.family));
    assert.equal(parseReview(JSON.stringify(row.gold), chunksFor(row.files)[0]).findings.length, row.expected_concern ? 1 : 0);
    assert.equal(row.audit_metadata.split, 'evaluation-only');
  }
});

test('fresh source semantics hold before edits and expose precise concern boundaries after edits', async () => {
  const { rows } = await buildHoldoutV5(ROOT);
  const audit = await runHoldoutWitnesses(rows);
  assert.equal(audit.status, 'pass');
  assert.equal(audit.source_states_checked, 48);
  assert.ok(audit.results.every(r => r.stages.before.failing_case_indices.length === 0));
  for (let i = 0; i < rows.length; i++) {
    assert.equal(audit.results[i].stages.after.failing_case_indices.length > 0, rows[i].expected_concern);
  }
  const flag = audit.results.find(r => r.id.includes('reserved-flag-bits-pure-deletion-concern'));
  assert.equal(flag.stages.after.cases.length, 256);
  assert.equal(flag.stages.after.failing_case_indices.length, 240);
});

test('fresh evaluation material does not reuse prior train or evaluation cases', async () => {
  const { rows, sftRows } = await buildHoldoutV5(ROOT);
  const sources = ['training/sft_review_v2.jsonl', 'training/sft_review_v3.jsonl', 'training/sft_review_v4.jsonl',
    'training/review_holdout_v2.jsonl', 'training/results/2026-10-01-counterbalanced-review/fresh-transfer.jsonl'];
  try { await readFile(path.join(ROOT, 'training/sft_review_v5.jsonl')); sources.push('training/sft_review_v5.jsonl'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  for (const source of sources) {
    const text = await readFile(path.join(ROOT, source), 'utf8');
    for (const row of rows) {
      assert.ok(!text.includes(row.context.repository), `${source}: repository reuse`);
      assert.ok(!text.includes(row.files[0].path), `${source}: source path reuse`);
      assert.ok(!text.includes(row.id), `${source}: evaluation ID reuse`);
    }
    for (const prior of text.trim().split('\n').map(JSON.parse)) {
      const user = prior.messages?.find(m => m.role === 'user')?.content;
      if (user) assert.ok(!sftRows.some(r => r.messages[1].content === user), `${source}: exact user prompt reuse`);
    }
  }
});

test('builder rejects malformed context mechanisms and CLI preserves existing outputs', async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'jovovich-holdout-cli-'));
  try {
    await mkdir(path.join(directory, 'training')); await mkdir(path.join(directory, 'prompts'));
    const design = JSON.parse(await readFile(path.join(ROOT, HOLDOUT_DESIGN), 'utf8'));
    // Deleting the sole contextual difference destroys the counterfactual pair.
    design.families[0].concern_context = design.families[0].clean_context;
    await writeFile(path.join(directory, HOLDOUT_DESIGN), JSON.stringify(design));
    await writeFile(path.join(directory, 'prompts/identity.txt'), await readFile(path.join(ROOT, 'prompts/identity.txt')));
    await assert.rejects(buildHoldoutV5(directory), /labels differ in one unchanged context line/);
    const output = path.join(directory, 'exists.jsonl'), audit = path.join(directory, 'absent.json');
    await writeFile(output, 'preserve these bytes\n');
    const child = spawnSync(process.execPath, ['training/build_holdout_v5.mjs', '--out', output, '--audit', audit], { cwd: ROOT, encoding: 'utf8' });
    assert.notEqual(child.status, 0); assert.match(child.stderr, /Refusing existing output/);
    assert.equal(await readFile(output, 'utf8'), 'preserve these bytes\n');
    await assert.rejects(readFile(audit), { code: 'ENOENT' });
    const duplicate = spawnSync(process.execPath, ['training/build_holdout_v5.mjs', '--out', output, '--audit', output], { cwd: ROOT, encoding: 'utf8' });
    assert.notEqual(duplicate.status, 0); assert.match(duplicate.stderr, /distinct output and audit paths/);
    const malformed = spawnSync(process.execPath, ['training/build_holdout_v5.mjs', '--out'], { cwd: ROOT, encoding: 'utf8' });
    assert.notEqual(malformed.status, 0); assert.match(malformed.stderr, /Usage:/);
  } finally { await rm(directory, { recursive: true, force: true }); }
});
