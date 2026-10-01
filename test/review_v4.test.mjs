import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, mkdtemp, writeFile, access, rm } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { buildCorpus, checkFixtureSemantics, patchSides } from '../training/build_review_v4.mjs';

test('v4 artifact exactly regenerates approved quartets while retaining every other v3 raw row', async () => {
  const built = await buildCorpus();
  assert.equal(built.text, await readFile('training/sft_review_v4.jsonl', 'utf8'));
  assert.equal(built.audit.corpus.sha256, '20afaa5692e88625d7152c7634c68e665a7bb165bfdc6dba15fec8c9e01edc1e');
  const source = (await readFile('training/sft_review_v3.jsonl', 'utf8')).trimEnd().split('\n');
  const output = built.text.trimEnd().split('\n');
  assert.equal(built.audit.retained_rows.length, 52);
  for (const r of built.audit.retained_rows) assert.equal(output[r.output_line - 1], source[r.source_line - 1]);
  assert.deepEqual(built.audit.counts.pure_deletion, { concern: 6, clean: 6 });
  assert.deepEqual(built.audit.counts.has_added_line, { concern: 20, clean: 20 });
  assert.throws(() => patchSides('@@ -11,2 +11,1 @@\n-removed'), /old-side hunk count/);
});

test('v4 builder refuses existing destinations and removes its unused reservation if audit already exists', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'jovovich-v4-output-'));
  const output = path.join(dir, 'rows.jsonl'), audit = path.join(dir, 'audit.json');
  const invoke = () => spawnSync(process.execPath, ['training/build_review_v4.mjs', '--output', output, '--audit', audit], { encoding: 'utf8' });
  try {
    await writeFile(audit, 'previous audit\n');
    let result = invoke();
    assert.notEqual(result.status, 0); assert.match(result.stderr, /EEXIST/);
    assert.equal(await readFile(audit, 'utf8'), 'previous audit\n');
    await assert.rejects(access(output), { code: 'ENOENT' });
    await writeFile(output, 'previous corpus\n');
    result = invoke();
    assert.notEqual(result.status, 0); assert.match(result.stderr, /EEXIST/);
    assert.equal(await readFile(output, 'utf8'), 'previous corpus\n');
    assert.equal(await readFile(audit, 'utf8'), 'previous audit\n');
  } finally { await rm(dir, { recursive: true, force: true }); }
});

test('v4 semantics exercise unsafe inputs, retained protections, ordering and credit; lost redundant guard fails', async () => {
  const { design } = await buildCorpus();
  const semantic = await checkFixtureSemantics(design);
  assert.equal(semantic.states.length, 48);
  assert.equal(semantic.c_original_syntax_checks, 32);
  assert.equal(semantic.c_executed_states, 32);
  const broken = structuredClone(design);
  const family = broken.families.find(f => f.family === 'allocation-null-guard');
  family.patches.redundant_deletion = family.patches.redundant_deletion.replace('\n     if (n == NULL) return NULL;', '\n     (void)0;');
  await assert.rejects(checkFixtureSemantics(broken));
});
