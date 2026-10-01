import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, mkdtemp, writeFile, access, rm } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { buildCorpus, checkFixtureSemantics, diffFeatures } from '../training/build_review_v5.mjs';

test('v5 changes only sixteen declared context lines and keeps task, targets, changed lines and cohort', async () => {
  const built = await buildCorpus();
  assert.equal(built.text, await readFile('training/sft_review_v5.jsonl', 'utf8'));
  assert.equal(built.audit.corpus.sha256, 'a677211e90576dea45ad4fa534fc97a3a6496944d63df99315ed934505936417');
  const source = (await readFile('training/sft_review_v4.jsonl', 'utf8')).trimEnd().split('\n');
  const output = built.text.trimEnd().split('\n');
  assert.equal(built.audit.retained_rows.length, 52);
  for (const r of built.audit.retained_rows) assert.equal(output[r.line - 1], source[r.line - 1]);
  assert.equal(built.audit.changed_context_rows, 16);
  assert.equal(source.filter((r, i) => r !== output[i]).length, 16);
  assert.equal(built.audit.preserved_gold_answers, 76);
  assert.equal(built.audit.preserved_changed_line_listings, 52);
  assert.equal(built.audit.matched_pairs.length, 12);
  for (const p of built.audit.matched_pairs) {
    assert.ok(Number.isInteger(p.native_prompt_tokens) && p.native_prompt_tokens > 0);
    assert.equal(p.diff_features.length, 6);
  }
  assert.deepEqual(diffFeatures('@@ -11,2 +11,1 @@\n-removed\n if (ready) return;'), [0, 1, 1, 1, 0, 0]);
});

test('v5 witnesses distinguish ineffective protection and retain correct before/ordinary/boundary behavior', async () => {
  const { design } = await buildCorpus();
  const checked = await checkFixtureSemantics(design);
  assert.equal(checked.states.length, 48);
  assert.equal(checked.c_original_syntax_checks, 32);
  assert.equal(checked.c_executed_states, 32);
  assert.equal(checked.javascript_syntax_and_execution_states, 8);
  assert.equal(checked.notice_provenance_states, 8);
  const nullCleanBroken = structuredClone(design);
  const nullFamily = nullCleanBroken.families.find(f => f.family === 'allocation-null-guard');
  nullFamily.patches.redundant_deletion = nullFamily.patches.redundant_deletion.replace('\n     if (n == NULL) return NULL;', '\n     if (&n == NULL) return NULL;');
  await assert.rejects(checkFixtureSemantics(nullCleanBroken));
  const sortBeforeBroken = structuredClone(design);
  const sortFamily = sortBeforeBroken.families.find(f => f.family === 'stable-manifest-order');
  sortFamily.patches.harmful_deletion = sortFamily.patches.harmful_deletion.replace('-names.sort();', '-output.sort();');
  await assert.rejects(checkFixtureSemantics(sortBeforeBroken));
  const creditMadeEquivalent = structuredClone(design);
  const creditFamily = creditMadeEquivalent.families.find(f => f.family === 'preserve-trie-credit');
  creditFamily.patches.harmful_deletion = creditFamily.patches.harmful_deletion.replace('Trie documentation derived', 'Trie implementation derived');
  await assert.rejects(checkFixtureSemantics(creditMadeEquivalent));
});

test('v5 builder reserves destinations without overwriting an existing corpus or audit', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'jovovich-v5-output-'));
  const output = path.join(dir, 'rows.jsonl'), audit = path.join(dir, 'audit.json');
  const invoke = () => spawnSync(process.execPath, ['training/build_review_v5.mjs', '--output', output, '--audit', audit], { encoding: 'utf8' });
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
