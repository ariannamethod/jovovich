#!/usr/bin/env node
// Match the recorded surface features without changing the review task or targets.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, open, unlink, mkdtemp, writeFile, rm } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chunksFor, parseReview } from '../bin/jovovich.mjs';
import { buildCorpus as buildV4, patchSides } from './build_review_v4.mjs';

export const DESIGN = 'training/review_v5_design.json';
export const BASE = 'training/sft_review_v4.jsonl';
const sha = value => createHash('sha256').update(value).digest('hex');
const DIFF = '\n\nSurrounding diff:\n', LINES = '\n\nChanged lines to review:\n';
const END = '\n\nReview the changed lines against these rules.';
const CELLS = ['harmful_deletion', 'redundant_deletion', 'harmful_replacement', 'redundant_replacement'];

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
export function diffFeatures(patch) {
  const body = patch.split('\n').slice(1), { after } = patchSides(patch), text = after.join('\n');
  return [body.filter(l => l[0] === '+').length, body.filter(l => l[0] === '-').length,
    body.filter(l => l[0] === ' ').length, [...text.matchAll(/\bif\s*\(/g)].length,
    [...text.matchAll(/\.sort\s*\(/g)].length, [...text.matchAll(/firwood\/trie/g)].length];
}

export async function buildCorpus(root = process.cwd()) {
  const [v4, baseText, designText] = await Promise.all([buildV4(root), readFile(path.join(root, BASE), 'utf8'), readFile(path.join(root, DESIGN), 'utf8')]);
  assert.equal(baseText, v4.text, 'v4 artifact must match its frozen generator');
  const design = JSON.parse(designText);
  assert.equal(design.base.path, BASE); assert.equal(design.base.sha256, sha(baseText));
  assert.equal(design.families.length, 6);
  assert.equal(new Set(design.families.map(f => f.family)).size, 6);
  const sourceLines = baseText.trimEnd().split('\n'), source = sourceLines.map(JSON.parse), lines = [], retained = [], edits = [], pairs = new Map();
  const semanticDesign = structuredClone(v4.design);
  for (const [i, original] of source.entries()) {
    const spec = design.families.find(f => original.pair === `${f.family}-deletion` || original.pair === `${f.family}-replacement`);
    if (!spec) { lines.push(sourceLines[i]); retained.push({ id: original.id, line: i + 1, raw_row_sha256: sha(sourceLines[i]) }); continue; }
    const old = parts(original.messages[1].content), concern = JSON.parse(original.messages[2].content).findings.length > 0;
    const shape = original.pair.endsWith('-deletion') ? 'deletion' : 'replacement';
    const oldContext = spec[concern ? 'v4_concern_context' : 'v4_clean_context'], newContext = spec[concern ? 'concern_context' : 'clean_context'];
    const patchLines = old.patch.split('\n'), positions = patchLines.flatMap((line, j) => line === ' ' + oldContext ? [j] : []);
    assert.equal(positions.length, 1, `${original.id}: unique context line`);
    const at = positions[0]; patchLines[at] = ' ' + newContext;
    const patch = patchLines.join('\n'), row = structuredClone(original);
    row.messages[1].content = old.preamble + DIFF + patch + LINES + old.listing + old.instruction;
    const oldChunk = chunksFor([{ path: spec.path, patch: old.patch }]), chunks = chunksFor([{ path: spec.path, patch }]);
    assert.equal(chunks.length, 1); assert.equal(chunks[0].surrounding_diff, patch);
    assert.equal(listingFor(chunks[0]), old.listing); assert.deepEqual(chunks[0].lines, oldChunk[0].lines);
    const accepted = parseReview(row.messages[2].content, chunks[0]).findings;
    assert.equal(accepted.length, +concern);
    assert.throws(() => parseReview(JSON.stringify({ findings: [{ line_id: chunks[0].lines.length + 1, reason: 'Context is not a changed line.' }] }), chunks[0]));
    const before = patchSides(old.patch), after = patchSides(patch);
    assert.equal(after.before.length, before.before.length); assert.equal(after.after.length, before.after.length);
    assert.equal(row.messages[0].content, original.messages[0].content); assert.equal(row.messages[2].content, original.messages[2].content);
    const semanticFamily = semanticDesign.families.find(f => f.family === spec.family);
    assert.ok(semanticFamily); semanticFamily.patches[`${concern ? 'harmful' : 'redundant'}_${shape}`] = patch;
    lines.push(newContext === oldContext ? sourceLines[i] : JSON.stringify(row));
    edits.push({ id: row.id, line: i + 1, family: spec.family, shape, concern, changed: newContext !== oldContext,
      hunk_context_index: at, from: oldContext, to: newContext, before_sha256: sha(after.before.join('\n')), after_sha256: sha(after.after.join('\n')) });
    pairs.set(row.pair, [...(pairs.get(row.pair) || []), { row, concern, patch, native_prompt_tokens: spec.native_prompt_tokens[shape] }]);
  }
  const matching = [];
  for (const [pair, members] of pairs) {
    assert.equal(members.length, 2); assert.deepEqual(members.map(m => m.concern), [true, false]);
    const a = parts(members[0].row.messages[1].content), b = parts(members[1].row.messages[1].content);
    assert.equal(a.preamble, b.preamble); assert.equal(a.listing, b.listing); assert.equal(a.instruction, b.instruction);
    assert.deepEqual(diffFeatures(a.patch), diffFeatures(b.patch), `${pair}: six diff-only nuisance features`);
    const countReturns = patch => [...patchSides(patch).after.join('\n').matchAll(/\breturn\b/g)].length;
    assert.equal(countReturns(a.patch), countReturns(b.patch), `${pair}: return count`);
    const pa = a.patch.split('\n'), pb = b.patch.split('\n');
    assert.equal(pa.length, pb.length); const differences = pa.flatMap((line, i) => line === pb[i] ? [] : [i]);
    assert.equal(differences.length, 1); assert.equal(pa[differences[0]][0], ' '); assert.equal(pb[differences[0]][0], ' ');
    matching.push({ pair, native_prompt_tokens: members[0].native_prompt_tokens, diff_features: diffFeatures(a.patch), after_return_count: countReturns(a.patch) });
  }
  const text = lines.join('\n') + '\n', rows = lines.map(JSON.parse);
  assert.equal(rows.length, 76); assert.equal(retained.length, 52); assert.equal(edits.length, 24); assert.equal(matching.length, 12);
  assert.equal(new Set(rows.map(r => r.id)).size, 76);
  assert.deepEqual(design.counts, { total_rows: rows.length, review_rows: rows.filter(r => r.kind === 'review').length,
    review_pairs: new Set(rows.filter(r => r.kind === 'review').map(r => r.pair)).size, quartet_rows: edits.length,
    retained_raw_rows: retained.length, voice_rows: rows.filter(r => r.kind === 'voice').length, code_rows: rows.filter(r => r.kind === 'code').length });
  assert.equal(edits.filter(e => e.changed).length, 16, 'only recorded context interventions');
  for (const pair of matching) assert.ok(Number.isInteger(pair.native_prompt_tokens) && pair.native_prompt_tokens > 0);
  for (let i = 0; i < rows.length; i++) {
    const old = source[i], row = rows[i];
    assert.equal(row.id, old.id); assert.equal(row.pair, old.pair); assert.equal(row.kind, old.kind);
    assert.equal(row.messages[0].content, old.messages[0].content); assert.equal(row.messages[2].content, old.messages[2].content);
    if (row.kind === 'review') {
      const p = parts(row.messages[1].content), file = /^Repository rules for (.+):$/m.exec(p.preamble)[1];
      const chunks = chunksFor([{ path: file, patch: p.patch }]); assert.equal(chunks.length, 1);
      assert.equal(listingFor(chunks[0]), p.listing); parseReview(row.messages[2].content, chunks[0]);
    }
  }
  return { text, rows, design: semanticDesign, spec: design, audit: { schema_version: 1,
    base: { path: BASE, sha256: sha(baseText) }, design: { path: DESIGN, sha256: sha(designText) },
    corpus: { sha256: sha(text), bytes: Buffer.byteLength(text) }, counts: design.counts,
    preserved_system_messages: 76, preserved_gold_answers: 76, preserved_ids_kinds_pairs_and_order: 76,
    preserved_changed_line_listings: 52, production_gold_acceptance: 52, quartet_context_citation_rejections: 24,
    retained_rows: retained, quartet_rows: edits, changed_context_rows: edits.filter(e => e.changed).length,
    feature_order: design.nuisance_features.feature_order, matched_pairs: matching,
    native_token_matching: design.nuisance_features.native_prompt_tokens } };
}

function cWrapper(family, name, body) {
  if (family === 'allocation-null-guard') return `node *${name}(int value) {\n${body}\n}`;
  if (family === 'zero-worker-guard') return `int ${name}(size_t total, size_t workers) {\n${body}\n}`;
  if (family === 'write-permission-check') return `int ${name}(session_t session, int id, int value) {\n(void)session;\n${body}\n}`;
  assert.equal(family, 'allocation-product-overflow');
  return `uint64_t *${name}(size_t count) {\nuint64_t *items;\n${body}\nreturn items;\n}`;
}

export async function checkFixtureSemantics(design) {
  const dir = await mkdtemp(path.join(tmpdir(), 'jovovich-v5-'));
  const records = [], raw = [], probes = [], assertions = [];
  const common = '#include <assert.h>\n#include <stddef.h>\n#include <stdint.h>\n#include <stdbool.h>\n#include <errno.h>\n#include <stdlib.h>\n#include <string.h>\n';
  const declarations = 'typedef struct { int value; } node;\ntypedef struct { int can_write; } session_t;\nenum { DENIED = -41 };\nint assign_share(size_t);\nint replace_record(int, int);\n';
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
          if (family.family === 'allocation-null-guard') assertions.push(`reset(); fail_allocation=1; assert(${name}(7)==NULL); assert(hazard==${+harmful} && alloc_calls==1);\nreset(); node *n_${name}=${name}(7); assert(n_${name} && n_${name}->value==7 && !hazard && alloc_calls==1);\nreset(); assert(${name}(0)->value==0 && !hazard);`);
          if (family.family === 'zero-worker-guard') assertions.push(`reset(); assert(${name}(12,0)==${harmful ? '-99' : 'EINVAL'}); assert(hazard==${+harmful} && call_count==0);\nreset(); assert(${name}(12,3)==73 && call_count==1 && last_share==4 && !hazard);\nreset(); assert(${name}(0,3)==73 && call_count==1 && last_share==0 && !hazard);\nreset(); assert(${name}(0,0)==${harmful ? '-99' : 'EINVAL'} && hazard==${+harmful});`);
          if (family.family === 'write-permission-check') assertions.push(`reset(); assert(${name}((session_t){0},2,7)==${harmful ? '81' : 'DENIED'}); assert(call_count==${+harmful});\nreset(); assert(${name}((session_t){1},2,7)==81 && call_count==1 && last_id==2 && last_value==7);\nreset(); assert(${name}((session_t){1},0,0)==81 && call_count==1 && last_id==0 && last_value==0);\nreset(); assert(${name}((session_t){0},0,7)==${harmful ? '81' : 'DENIED'} && call_count==${+harmful});`);
          if (family.family === 'allocation-product-overflow') assertions.push(`reset(); assert((${name}(SIZE_MAX/sizeof(uint64_t)+2)!=NULL)==${+harmful}); assert(alloc_calls==${+harmful}); ${harmful ? 'assert(last_bytes==sizeof(uint64_t));' : ''}\nreset(); assert(${name}(3)!=NULL && alloc_calls==1 && last_bytes==3*sizeof(uint64_t));\nreset(); assert(${name}(0)!=NULL && alloc_calls==1 && last_bytes==0);\nreset(); assert(${name}(SIZE_MAX/sizeof(uint64_t))!=NULL && alloc_calls==1 && last_bytes==SIZE_MAX-(sizeof(uint64_t)-1));\nreset(); assert(${name}(SIZE_MAX/sizeof(uint32_t)+1)==NULL && alloc_calls==0);`);
          records.push({ family: family.family, cell, stage, language: 'C', unsafe_condition_reaches_operation: harmful,
            ordinary_input_passes: true, zero_value_case_passes: true,
            ...(family.family === 'allocation-product-overflow' ? { exact_safe_boundary_passes: true, weaker_guard_rejects_above_its_own_boundary: true, wrapped_allocation_bytes: harmful ? 8 : null } : {}) });
        } else if (family.path.endsWith('.mjs')) {
          const file = path.join(dir, name + '.mjs');
          await writeFile(file, `export function manifest(entries) { const output = [];\n${body}\nreturn output.join('\\n'); }\n`);
          const syntax = spawnSync(process.execPath, ['--check', file], { encoding: 'utf8' });
          assert.equal(syntax.status, 0, syntax.stderr);
          const manifest = new Function('entries', `const output = [];\n${body}\nreturn output.join('\\n');`);
          const a = manifest({ beta: 2, alpha: 1 }), b = manifest({ alpha: 1, beta: 2 });
          assert.equal(a !== b, harmful); if (!harmful) assert.equal(a, 'alpha:1\nbeta:2');
          assert.equal(manifest({}), ''); assert.equal(manifest({ alpha: 1 }), 'alpha:1');
          records.push({ family: family.family, cell, stage, language: 'JavaScript', syntax_passed: true,
            equal_mappings_produce_different_bytes: a !== b, output_insertion_beta_first: a, output_insertion_alpha_first: b,
            empty_and_single_entry_cases_pass: true });
        } else {
          assert.equal(family.path, 'NOTICE');
          const implementation = lines.filter(l => /^(?:Trie design adapted|Trie implementation derived) from firwood\/trie \(MIT\)\.$/.test(l));
          const documentation = lines.filter(l => /^Trie documentation derived from firwood\/trie \(MIT\)\.$/.test(l));
          assert.equal(implementation.length > 0, !harmful);
          assert.equal(documentation.length, +cell.startsWith('harmful_'));
          records.push({ family: family.family, cell, stage, language: 'NOTICE', implementation_credit_present: implementation.length > 0,
            implementation_credits: implementation, unrelated_documentation_credit_count: documentation.length,
            literal_upstream_count: [...body.matchAll(/firwood\/trie/g)].length,
            retained_implementation_explicit_in_description: family.shared_description.includes('implementation remains') });
        }
      }
    }
    const cc = process.env.CC || 'cc';
    const warningFlags = ['-Werror', '-Wno-error=address', '-Wno-error=type-limits'];
    const diagnosticAudit = result => {
      const diagnostics = result.stderr.replaceAll(dir, '<fixture>');
      const classes = [...diagnostics.matchAll(/warning:.*\[-W([^\]]+)\]/g)].map(m => m[1]);
      assert.ok(classes.every(c => ['address', 'type-limits', 'tautological-pointer-compare', 'tautological-unsigned-zero-compare'].includes(c)));
      return { expected_warning_classes: classes.reduce((o, c) => ({ ...o, [c]: (o[c] || 0) + 1 }), {}), diagnostics };
    };
    const rawSource = common + declarations + raw.join('\n'), rawFile = path.join(dir, 'original.c');
    await writeFile(rawFile, rawSource);
    const syntax = spawnSync(cc, ['-std=c11', '-Wall', '-Wextra', ...warningFlags, '-fsyntax-only', rawFile], { encoding: 'utf8' });
    assert.equal(syntax.status, 0, syntax.error?.message || syntax.stderr);
    const source = common + declarations + `
static int hazard, fail_allocation, alloc_calls, call_count, last_id, last_value;
static size_t last_share, last_bytes;
static node storage;
static uint64_t vector_storage;
static void reset(void) { hazard=fail_allocation=alloc_calls=call_count=last_id=last_value=errno=0; last_share=last_bytes=0; memset(&storage,0,sizeof storage); }
int assign_share(size_t share) { call_count++; last_share=share; return 73; }
int replace_record(int id, int value) { last_id=id; last_value=value; call_count++; return 81; }
static void *fake_calloc(size_t count, size_t size) { assert(count==1 && size==sizeof(node)); alloc_calls++; return fail_allocation ? NULL : &storage; }
static void *fake_malloc(size_t bytes) { alloc_calls++; last_bytes=bytes; return &vector_storage; }
#define calloc fake_calloc
#define malloc fake_malloc
_Static_assert(sizeof(uint64_t)==8 && sizeof(uint32_t)==4, "fixed-width element sizes");
` + probes.join('\n') + '\nint main(void) {\n' + assertions.join('\n') + '\nreturn 0;\n}\n';
    const sourceFile = path.join(dir, 'probe.c'), executable = path.join(dir, 'probe');
    await writeFile(sourceFile, source);
    const compile = spawnSync(cc, ['-std=c11', '-O0', '-Wall', '-Wextra', ...warningFlags, sourceFile, '-o', executable], { encoding: 'utf8' });
    assert.equal(compile.status, 0, compile.error?.message || compile.stderr);
    const run = spawnSync(executable, [], { cwd: dir, encoding: 'utf8', timeout: 10000 });
    assert.equal(run.status, 0, run.error?.message || run.stderr); assert.equal(records.length, 48);
    return { method: 'Compile all exact C snippets; execute instrumented NULL/zero-divisor reachability and allocation/write call witnesses with ordinary and boundary inputs. Execute exact JavaScript snippets. Distinguish implementation from documentation attribution in NOTICE.',
      c_original_syntax_checks: raw.length, c_executed_states: probes.length,
      c_expected_diagnostic_policy: 'The intentional wrong-address and unsigned-negative comparisons may warn; all other warnings are errors.',
      c_raw_diagnostics: diagnosticAudit(syntax), c_probe_diagnostics: diagnosticAudit(compile),
      c_undefined_operations_instrumentation: 'Sentinel immediately before the NULL dereference or zero division records arrival and returns. All preceding statements are unchanged.',
      c_stubs: 'calloc supplies success/failure, malloc records sizes without allocating, assign_share and replace_record record calls/arguments.',
      c_syntax_source_sha256: sha(rawSource), c_probe_source_sha256: sha(source),
      javascript_syntax_and_execution_states: 8, notice_provenance_states: 8, states: records };
  } finally { await rm(dir, { recursive: true, force: true }); }
}

async function main() {
  const opts = { output: 'training/sft_review_v5.jsonl' }, seen = new Set();
  for (let i = 2; i < process.argv.length; i += 2) {
    const name = process.argv[i].replace(/^--/, '');
    assert.ok(['output', 'audit'].includes(name) && process.argv[i] === `--${name}` && process.argv[i + 1] && !seen.has(name),
      'Usage: node training/build_review_v5.mjs [--output NEW.jsonl] [--audit NEW.json]');
    seen.add(name); opts[name] = process.argv[i + 1];
  }
  if (opts.audit) assert.notEqual(path.resolve(opts.output), path.resolve(opts.audit));
  const built = await buildCorpus(); built.audit.semantic_checks = await checkFixtureSemantics(built.design);
  built.audit.builder = { path: 'training/build_review_v5.mjs', sha256: sha(await readFile(fileURLToPath(import.meta.url))) };
  const files = [[opts.output, built.text], ...(opts.audit ? [[opts.audit, JSON.stringify(built.audit, null, 2) + '\n']] : [])], opened = [];
  try {
    for (const [file] of files) opened.push({ file, handle: await open(file, 'wx') });
    for (let i = 0; i < files.length; i++) { await opened[i].handle.writeFile(files[i][1]); await opened[i].handle.sync(); }
  } catch (error) {
    for (const { handle } of opened) await handle.close();
    for (const { file } of opened) await unlink(file);
    throw error;
  }
  for (const { handle } of opened) await handle.close();
  process.stdout.write(JSON.stringify({ ...built.audit.corpus, ...built.audit.counts, changed_context_rows: built.audit.changed_context_rows, semantic_states_checked: built.audit.semantic_checks.states.length }) + '\n');
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url))
  main().catch(e => { process.stderr.write(`review-v5: ${e.message}\n`); process.exitCode = 1; });
