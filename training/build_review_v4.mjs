#!/usr/bin/env node
// Materialize the six approved counterbalanced quartets. Run from the repository root.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, open, unlink, mkdtemp, writeFile, rm } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chunksFor, parseReview } from '../bin/jovovich.mjs';

export const DESIGN = 'training/results/2026-10-01-joint-review/joint-next-control.json';
export const BASE = 'training/sft_review_v3.jsonl';
const DESIGN_SHA = 'b8b0158c08129342215f4349accc7dce4fdfda56af45dac01a09cabbf52668c9';
const BASE_SHA = '98f42d19c7b5b5d2c59f5cbd597e606e3e4d1455182ac077378944d5448398e7';
const sha = s => createHash('sha256').update(s).digest('hex');
const CELLS = ['harmful_deletion', 'redundant_deletion', 'harmful_replacement', 'redundant_replacement'];
const DIFF = '\n\nSurrounding diff:\n', LINES = '\n\nChanged lines to review:\n';
const END = '\n\nReview the changed lines against these rules.';

export function patchSides(patch) {
  const [header, ...body] = patch.split('\n');
  const m = /^@@ -(\d+),(\d+) \+(\d+),(\d+) @@$/.exec(header);
  assert.ok(m, `unsupported hunk: ${header}`);
  assert.ok(body.every(line => /^[ +\-]/.test(line)));
  const before = body.filter(line => line[0] !== '+').map(line => line.slice(1));
  const after = body.filter(line => line[0] !== '-').map(line => line.slice(1));
  assert.equal(before.length, Number(m[2]), 'old-side hunk count');
  assert.equal(after.length, Number(m[4]), 'new-side hunk count');
  return { before, after, old_start: Number(m[1]), new_start: Number(m[3]),
    context: body.filter(line => line[0] === ' ').map(line => line.slice(1)) };
}

function parts(user) {
  assert.equal(user.split(DIFF).length, 2);
  const [preamble, tail] = user.split(DIFF);
  assert.equal(tail.split(LINES).length, 2);
  const [patch, rest] = tail.split(LINES);
  assert.equal(rest.split(END).length, 2);
  const [listing, instruction] = rest.split(END);
  return { preamble, patch, listing, instruction: END + instruction };
}

function listingFor(chunk) {
  return chunk.lines.map((line, i) => `[${i + 1}] ${line.side === 'LEFT' ? 'REMOVED' : 'ADDED'} ${chunk.path}:${line.line}: ${line.quote}`).join('\n');
}

function rowChunk(row) {
  assert.deepEqual(row.messages.map(m => m.role), ['system', 'user', 'assistant']);
  const p = parts(row.messages[1].content);
  const match = /^Repository rules for (.+):$/m.exec(p.preamble);
  assert.ok(match);
  const chunks = chunksFor([{ path: match[1], patch: p.patch }]);
  assert.equal(chunks.length, 1, row.id);
  assert.equal(chunks[0].surrounding_diff, p.patch, 'host must retain the complete hunk');
  assert.equal(listingFor(chunks[0]), p.listing, `host listing: ${row.id}`);
  patchSides(p.patch);
  return { ...p, chunk: chunks[0] };
}

function revisePreamble(original, family) {
  const start = original.indexOf('\n', original.indexOf('Purpose:')) + 1;
  const end = original.indexOf('\nRepository rules for ');
  assert.ok(start > 0 && end > start);
  if (!family.shared_description_changes_from_v3)
    assert.equal(original.slice(start, end), family.shared_description);
  return original.slice(0, start) + family.shared_description + original.slice(end);
}

export async function buildCorpus(root = process.cwd()) {
  const [baseText, designText] = await Promise.all([readFile(path.join(root, BASE), 'utf8'), readFile(path.join(root, DESIGN), 'utf8')]);
  assert.equal(sha(baseText), BASE_SHA, 'v3 source changed');
  assert.equal(sha(designText), DESIGN_SHA, 'approved design changed');
  assert.ok(baseText.endsWith('\n'));
  const design = JSON.parse(designText), sourceLines = baseText.slice(0, -1).split('\n');
  const source = sourceLines.map(JSON.parse), sourceById = new Map(source.map(r => [r.id, r]));
  assert.equal(source.length, 64); assert.equal(sourceById.size, 64); assert.equal(design.families.length, 6);
  const introduced = new Map(design.families.map(f => [f.source_introduced_id, f]));
  const omitted = new Set(design.families.map(f => f.source_repaired_id));
  const lines = [], rowAudit = [], retained = [];
  for (const [sourceIndex, original] of source.entries()) {
    if (omitted.has(original.id)) continue;
    const family = introduced.get(original.id);
    if (!family) {
      lines.push(sourceLines[sourceIndex]);
      retained.push({ id: original.id, source_line: sourceIndex + 1, output_line: lines.length, raw_row_sha256: sha(sourceLines[sourceIndex]) });
      continue;
    }
    assert.equal(original.kind, 'review'); assert.equal(original.pair, family.family);
    assert.equal(source[family.source_v2_v3_jsonl_lines[0] - 1].id, original.id);
    assert.equal(source[family.source_v2_v3_jsonl_lines[1] - 1].id, family.source_repaired_id);
    const other = sourceById.get(family.source_repaired_id);
    assert.equal(other.messages[0].content, original.messages[0].content);
    const originalParts = parts(original.messages[1].content);
    const preamble = revisePreamble(originalParts.preamble, family);
    assert.equal(revisePreamble(parts(other.messages[1].content).preamble, family), preamble);
    assert.equal(parts(other.messages[1].content).instruction, originalParts.instruction);
    for (const cell of CELLS) {
      const [harm, shape] = cell.split('_'), concern = harm === 'harmful';
      const patch = family.patches[cell], sides = patchSides(patch);
      assert.equal(sides.old_start, 11); assert.equal(sides.new_start, 11);
      assert.equal(sides.context[family.candidate_line - 11], concern ? family.harmful_unchanged_context : family.redundant_unchanged_context);
      const chunks = chunksFor([{ path: family.path, patch }]);
      assert.equal(chunks.length, 1);
      const chunk = chunks[0];
      assert.deepEqual(chunk.lines, [
        { side: 'LEFT', line: family.candidate_line, quote: family.removed_candidate },
        ...(shape === 'replacement' ? [{ side: 'RIGHT', line: family.candidate_line, quote: family.replacement_addition }] : [])
      ]);
      const gold = concern ? family.concern_gold : family.clean_gold;
      const row = { id: `${family.family}-${shape}-${concern ? 'concern' : 'clean'}`, kind: 'review', pair: `${family.family}-${shape}`,
        messages: [original.messages[0], { role: 'user', content: preamble + DIFF + patch + LINES + listingFor(chunk) + originalParts.instruction },
          { role: 'assistant', content: JSON.stringify(gold) }] };
      lines.push(JSON.stringify(row));
      rowAudit.push({ id: row.id, family: family.family, shape, concern, source_id: original.id, output_line: lines.length,
        candidate_line: family.candidate_line, expected_line_ids: concern ? (shape === 'replacement' ? [1, 2] : [1]) : [],
        canonical_line_id: concern ? 1 : null, citation_condition: concern ? 'A removal or replacement mechanism must support the cited changed line.' : null,
        patch_sha256: sha(patch), before_sha256: sha(sides.before.join('\n')), after_sha256: sha(sides.after.join('\n')) });
    }
  }
  const text = lines.join('\n') + '\n', rows = lines.map(JSON.parse), pairs = new Map();
  const counts = { total_rows: rows.length, review_rows: 0, concern_reviews: 0, clean_reviews: 0, review_pairs: 0,
    new_quartet_rows: rowAudit.length, retained_review_rows: 0, voice_rows: 0, code_rows: 0,
    pure_deletion: { concern: 0, clean: 0 }, has_added_line: { concern: 0, clean: 0 } };
  assert.equal(new Set(rows.map(r => r.id)).size, rows.length);
  for (const row of rows) {
    if (row.kind !== 'review') { assert.ok(['voice', 'code'].includes(row.kind)); counts[`${row.kind}_rows`]++; continue; }
    const { chunk } = rowChunk(row), gold = JSON.parse(row.messages[2].content);
    const findings = parseReview(row.messages[2].content, chunk).findings, concern = findings.length > 0;
    assert.equal(findings.length, gold.findings.length);
    assert.ok(findings.length <= 1);
    assert.throws(() => parseReview(JSON.stringify({ findings: [{ line_id: chunk.lines.length + 1, reason: 'Unchanged context is not a changed line.' }] }), chunk));
    counts.review_rows++; counts[concern ? 'concern_reviews' : 'clean_reviews']++;
    counts[chunk.lines.some(l => l.side === 'RIGHT') ? 'has_added_line' : 'pure_deletion'][concern ? 'concern' : 'clean']++;
    if (retained.some(r => r.id === row.id)) counts.retained_review_rows++;
    pairs.set(row.pair, [...(pairs.get(row.pair) || []), { row, concern }]);
  }
  counts.review_pairs = pairs.size;
  for (const [id, pair] of pairs) assert.deepEqual(pair.map(p => p.concern).sort(), [false, true], id);
  assert.deepEqual(counts, design.corpus_revision.proposed_counts);
  assert.equal(retained.length, 52);
  for (const entry of retained) assert.equal(lines[entry.output_line - 1], sourceLines[entry.source_line - 1]);
  for (const family of design.families) {
    for (const shape of ['deletion', 'replacement']) {
      const pair = pairs.get(`${family.family}-${shape}`).map(p => rowChunk(p.row));
      assert.equal(pair[0].preamble, pair[1].preamble); assert.equal(pair[0].listing, pair[1].listing);
      assert.equal(pair[0].instruction, pair[1].instruction);
      const a = pair[0].patch.split('\n'), b = pair[1].patch.split('\n');
      assert.equal(a.length, b.length); assert.equal(a[0], b[0]);
      const differences = a.flatMap((line, i) => line === b[i] ? [] : [i]);
      assert.equal(differences.length, 1); assert.equal(a[differences[0]][0], ' '); assert.equal(b[differences[0]][0], ' ');
    }
    for (const concern of [true, false]) {
      const matching = rowAudit.filter(r => r.family === family.family && r.concern === concern).map(r => rows[r.output_line - 1]);
      assert.equal(matching.length, 2); assert.equal(matching[0].messages[2].content, matching[1].messages[2].content);
    }
  }
  for (const id of design.context_coverage.retained_exact_same_diff_context_pairs) {
    const pair = pairs.get(id).map(p => rowChunk(p.row));
    assert.equal(pair[0].patch, pair[1].patch); assert.equal(pair[0].listing, pair[1].listing);
  }
  const actualRetainedPairs = [...pairs.keys()].filter(id => !design.families.some(f => id.startsWith(f.family + '-')));
  assert.deepEqual(actualRetainedPairs, design.context_coverage.retained_14_pairs);
  return { text, rows, design, audit: { schema_version: 1, design: { path: DESIGN, sha256: sha(designText) },
    base: { path: BASE, sha256: sha(baseText) }, corpus: { sha256: sha(text), bytes: Buffer.byteLength(text) }, counts,
    structural_checks: { production_chunks_and_gold_acceptance: 52, unchanged_citation_rejections: 52,
      raw_retained_rows_identical: 52, same_diff_context_pairs_preserved: 6, one_unchanged_context_line_per_label_pair: 12,
      identical_gold_across_shape_per_label: 12 },
    retained_pairs: actualRetainedPairs, retained_same_diff_pairs: design.context_coverage.retained_exact_same_diff_context_pairs,
    retained_rows: retained, quartet_rows: rowAudit,
    interpretation: design.corpus_revision.attribution_of_results,
    evaluation_boundary: design.evaluation_boundary } };
}

function cWrapper(family, name, body) {
  if (family === 'allocation-null-guard') return `node *${name}(int value) {\n${body}\n}`;
  if (family === 'zero-worker-guard') return `int ${name}(size_t total, size_t workers) {\n${body}\n}`;
  if (family === 'write-permission-check') return `int ${name}(session_t session, int id, int value) {\n(void)session;\n${body}\n}`;
  assert.equal(family, 'allocation-product-overflow');
  return `uint64_t *${name}(size_t count) {\nuint64_t *items;\n${body}\nreturn items;\n}`;
}

// Execute wrappers for the exact before/after snippets. The two undefined operations
// have reachability sentinels immediately before them; the original snippets also
// compile without those sentinels. Allocation/write stubs expose calls and sizes.
export async function checkFixtureSemantics(design) {
  const dir = await mkdtemp(path.join(tmpdir(), 'jovovich-v4-'));
  const records = [], raw = [], probes = [], assertions = [];
  const common = `#include <assert.h>\n#include <stddef.h>\n#include <stdint.h>\n#include <errno.h>\n#include <stdlib.h>\n#include <string.h>\n`;
  const declarations = `typedef struct { int value; } node;\ntypedef struct { int can_write; } session_t;\nenum { DENIED = -41 };\nint assign_share(size_t);\nint replace_record(int, int);\n`;
  try {
    for (const family of design.families) for (const cell of CELLS) {
      const sides = patchSides(family.patches[cell]);
      for (const stage of ['before', 'after']) {
        const lines = sides[stage], body = lines.join('\n'), harmful = stage === 'after' && cell.startsWith('harmful_');
        const name = `${family.family}_${cell}_${stage}`.replaceAll('-', '_');
        if (family.path.endsWith('.c')) {
          raw.push(cWrapper(family.family, `raw_${name}`, body));
          let instrumented = body;
          if (family.family === 'allocation-null-guard') instrumented = body.replace('    n->value = value;', '    if (n == NULL) { hazard = 1; return NULL; }\n    n->value = value;');
          if (family.family === 'zero-worker-guard') instrumented = body.replace('    size_t share = total / workers;', '    if (workers == 0) { hazard = 1; return -99; }\n    size_t share = total / workers;');
          probes.push(cWrapper(family.family, name, instrumented));
          if (family.family === 'allocation-null-guard') assertions.push(`reset(); fail_allocation=1; assert(${name}(7)==NULL); assert(hazard==${+harmful}); assert(alloc_calls==1);\nreset(); node *n_${name}=${name}(7); assert(n_${name} && n_${name}->value==7 && !hazard && alloc_calls==1);`);
          if (family.family === 'zero-worker-guard') assertions.push(`reset(); assert(${name}(12,0)==${harmful ? '-99' : 'EINVAL'}); assert(hazard==${+harmful} && call_count==0);\nreset(); assert(${name}(12,3)==73 && call_count==1 && last_share==4 && !hazard);`);
          if (family.family === 'write-permission-check') assertions.push(`reset(); assert(${name}((session_t){0},2,7)==${harmful ? '81' : 'DENIED'}); assert(call_count==${+harmful});\nreset(); assert(${name}((session_t){1},2,7)==81 && call_count==1);`);
          if (family.family === 'allocation-product-overflow') assertions.push(`reset(); assert((${name}(SIZE_MAX/sizeof(uint64_t)+2)!=NULL)==${+harmful}); assert(alloc_calls==${+harmful}); ${harmful ? 'assert(last_bytes==sizeof(uint64_t));' : ''}\nreset(); assert(${name}(3)!=NULL && alloc_calls==1 && last_bytes==3*sizeof(uint64_t));\nreset(); assert(${name}(SIZE_MAX/sizeof(uint64_t))!=NULL && alloc_calls==1 && last_bytes==SIZE_MAX-(sizeof(uint64_t)-1));`);
          records.push({ family: family.family, cell, stage, language: 'C', unsafe_condition_reaches_operation: harmful,
            ordinary_input_passes: true, ...(family.family === 'allocation-product-overflow' ? { exact_safe_boundary_passes: true, wrapped_allocation_bytes: harmful ? 8 : null } : {}) });
        } else if (family.path.endsWith('.mjs')) {
          const file = path.join(dir, name + '.mjs');
          await writeFile(file, `export function manifest(entries) { const output = [];\n${body}\nreturn output.join('\\n'); }\n`);
          const syntax = spawnSync(process.execPath, ['--check', file], { encoding: 'utf8' });
          assert.equal(syntax.status, 0, syntax.stderr);
          const manifest = new Function('entries', `const output = [];\n${body}\nreturn output.join('\\n');`);
          const a = manifest({ beta: 2, alpha: 1 }), b = manifest({ alpha: 1, beta: 2 });
          assert.equal(a !== b, harmful);
          if (!harmful) assert.equal(a, 'alpha:1\nbeta:2');
          records.push({ family: family.family, cell, stage, language: 'JavaScript', syntax_passed: true,
            equal_mappings_produce_different_bytes: a !== b, output_insertion_beta_first: a, output_insertion_alpha_first: b });
        } else {
          assert.equal(family.path, 'NOTICE');
          const credit = lines.filter(l => /\bfirwood\/trie \(MIT\)/.test(l));
          assert.equal(credit.length > 0, !harmful);
          assert.ok(lines.every(l => !l.includes('upstream') || l.includes('firwood/trie')));
          records.push({ family: family.family, cell, stage, language: 'NOTICE', explicit_equivalent_upstream_credit_present: credit.length > 0,
            credits: credit, retained_implementation_explicit_in_description: family.shared_description.includes('implementation remains') });
        }
      }
    }
    const cc = process.env.CC || 'cc';
    const rawFile = path.join(dir, 'original.c');
    await writeFile(rawFile, common + declarations + raw.join('\n'));
    const syntax = spawnSync(cc, ['-std=c11', '-Wall', '-Wextra', '-Werror', '-fsyntax-only', rawFile], { encoding: 'utf8' });
    assert.equal(syntax.status, 0, syntax.error?.message || syntax.stderr);
    const source = common + declarations + `
static int hazard, fail_allocation, alloc_calls, call_count;
static size_t last_share, last_bytes;
static node storage;
static uint64_t vector_storage;
static void reset(void) { hazard=fail_allocation=alloc_calls=call_count=0; last_share=last_bytes=0; memset(&storage,0,sizeof storage); }
int assign_share(size_t share) { call_count++; last_share=share; return 73; }
int replace_record(int id, int value) { assert(id==2 && value==7); call_count++; return 81; }
static void *fake_calloc(size_t count, size_t size) { assert(count==1 && size==sizeof(node)); alloc_calls++; return fail_allocation ? NULL : &storage; }
static void *fake_malloc(size_t bytes) { alloc_calls++; last_bytes=bytes; return &vector_storage; }
#define calloc fake_calloc
#define malloc fake_malloc
_Static_assert(sizeof(uint64_t)==8, "uint64_t must be eight bytes");
` + probes.join('\n') + '\nint main(void) {\n' + assertions.join('\n') + '\nreturn 0;\n}\n';
    const sourceFile = path.join(dir, 'probe.c'), executable = path.join(dir, 'probe');
    await writeFile(sourceFile, source);
    const compile = spawnSync(cc, ['-std=c11', '-O0', '-Wall', '-Wextra', '-Werror', sourceFile, '-o', executable], { encoding: 'utf8' });
    assert.equal(compile.status, 0, compile.error?.message || compile.stderr);
    const run = spawnSync(executable, [], { cwd: dir, encoding: 'utf8', timeout: 10000 });
    assert.equal(run.status, 0, run.error?.message || run.stderr);
    assert.equal(records.length, 48);
    return { method: 'Compile all original C before/after snippets; execute instrumented C control flow with failing/ordinary inputs and overflow boundary; parse and execute exact JavaScript snippets; inspect explicit upstream name/license credit in every NOTICE state.',
      c_original_syntax_checks: raw.length, c_executed_states: probes.length,
      c_undefined_operations_instrumentation: 'NULL dereference and zero division get a sentinel immediately before the original unsafe operation; a sentinel records arrival and returns. No preceding guard or statement changes.',
      c_stubs: 'calloc supplies success or failure; malloc records requested byte count without allocating huge boundary buffers; assign_share and replace_record record calls.',
      c_syntax_source_sha256: sha(common + declarations + raw.join('\n')), c_probe_source_sha256: sha(source),
      javascript_syntax_and_execution_states: 8, notice_provenance_states: 8, states: records };
  } finally { await rm(dir, { recursive: true, force: true }); }
}

async function main() {
  const opts = { output: 'training/sft_review_v4.jsonl' };
  const seen = new Set();
  for (let i = 2; i < process.argv.length; i += 2) {
    const name = process.argv[i].replace(/^--/, '');
    assert.ok(['output', 'audit'].includes(name) && process.argv[i] === `--${name}` && process.argv[i + 1] && !seen.has(name),
      'Usage: node training/build_review_v4.mjs [--output NEW.jsonl] [--audit NEW.json]');
    seen.add(name); opts[name] = process.argv[i + 1];
  }
  if (opts.audit) assert.notEqual(path.resolve(opts.output), path.resolve(opts.audit));
  const built = await buildCorpus();
  built.audit.semantic_checks = await checkFixtureSemantics(built.design);
  built.audit.builder = { path: 'training/build_review_v4.mjs', sha256: sha(await readFile(fileURLToPath(import.meta.url))) };
  const files = [[opts.output, built.text], ...(opts.audit ? [[opts.audit, JSON.stringify(built.audit, null, 2) + '\n']] : [])];
  const opened = [];
  try {
    // Reserve every destination before writing any bytes; never overwrite evidence.
    for (const [file] of files) opened.push({ file, handle: await open(file, 'wx') });
    for (let i = 0; i < files.length; i++) { await opened[i].handle.writeFile(files[i][1]); await opened[i].handle.sync(); }
  } catch (error) {
    for (const { handle } of opened) await handle.close();
    for (const { file } of opened) await unlink(file);
    throw error;
  }
  for (const { handle } of opened) await handle.close();
  process.stdout.write(JSON.stringify({ ...built.audit.corpus, ...built.audit.counts, semantic_states_checked: built.audit.semantic_checks.states.length }) + '\n');
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url))
  main().catch(e => { process.stderr.write(`review-v4: ${e.message}\n`); process.exitCode = 1; });
