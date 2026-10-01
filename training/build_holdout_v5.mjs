#!/usr/bin/env node
// Evaluation fixtures only. The executable witnesses never load a model.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, open, unlink, mkdtemp, writeFile, rm, lstat } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chunksFor, parseReview, promptFor } from '../bin/jovovich.mjs';
import { patchSides } from './build_review_v4.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const HOLDOUT_DESIGN = 'training/holdout_v5_design.json';
export const HOLDOUT_OUTPUT = 'training/review_holdout_v5.jsonl';
const sha = s => createHash('sha256').update(s).digest('hex');

export function holdoutFeatures(patch) {
  const lines = patch.split('\n').slice(1);
  const after = lines.filter(l => l[0] !== '-').map(l => l.slice(1)).join('\n');
  return [lines.filter(l => l[0] === '+').length, lines.filter(l => l[0] === '-').length,
    lines.filter(l => l[0] === ' ').length, (after.match(/\bif\s*\(/g) || []).length,
    (after.match(/\.sort\s*\(/g) || []).length, (after.match(/firwood\/trie/g) || []).length];
}

function patchFor(source, candidate, noop, replacement) {
  assert.ok(source.endsWith('\n'));
  const lines = source.slice(0, -1).split('\n');
  const positions = lines.flatMap((line, i) => line.trim() === candidate ? [i] : []);
  assert.equal(positions.length, 1, 'one removable operation');
  const at = positions[0], indent = lines[at].slice(0, lines[at].length - lines[at].trimStart().length);
  const after = lines.slice(0, at).concat(replacement ? [indent + noop] : [], lines.slice(at + 1));
  const body = lines.flatMap((line, i) => i === at
    ? ['-' + line, ...(replacement ? ['+' + indent + noop] : [])] : [' ' + line]);
  const patch = `@@ -1,${lines.length} +1,${after.length} @@\n${body.join('\n')}`;
  assert.ok(patch.length <= 1800, 'complete diff fits production context');
  patchSides(patch);
  return { patch, line: at + 1, after: after.join('\n') + '\n' };
}

export async function buildHoldoutV5(root = ROOT) {
  const [designText, identity] = await Promise.all([
    readFile(path.join(root, HOLDOUT_DESIGN), 'utf8'), readFile(path.join(root, 'prompts/identity.txt'), 'utf8')]);
  const design = JSON.parse(designText);
  assert.equal(design.families.length, 6);
  const rows = [], prompts = [], sftRows = [];
  for (const f of design.families) {
    for (const shape of ['pure-deletion', 'replacement-noop']) {
      const pairRows = [];
      for (const concern of [true, false]) {
        const label = concern ? 'concern' : 'clean';
        const before = f.source.replace('@CONTEXT@', f[`${label}_context`]).replace('@CANDIDATE@', f.candidate);
        assert.ok(!/@(?:CONTEXT|CANDIDATE)@/.test(before));
        const { patch, line, after } = patchFor(before, f.candidate, f.noop, shape === 'replacement-noop');
        const row = {
          id: `holdout-v5-${f.family}-${shape}-${label}`, pair: `holdout-v5-${f.family}-${shape}`,
          context: { repository: f.repository, title: f.title, description: f.description, rules: { 'AGENTS.md': f.rule } },
          files: [{ path: f.path, patch }], expected_concern: concern,
          expected_line_ids: concern ? (shape === 'replacement-noop' ? [1, 2] : [1]) : [],
          expected_reason_concept: concern ? f.concern_reason : f.clean_reason,
          gold: { findings: concern ? [{ line_id: 1, reason: f.concern_reason }] : [] },
          audit_metadata: {
            split: 'evaluation-only', family: f.family, shape, label, language: f.language,
            semantic_counterpart: `holdout-v5-${f.family}-${shape}-${concern ? 'clean' : 'concern'}`,
            shape_counterpart: `holdout-v5-${f.family}-${shape === 'pure-deletion' ? 'replacement-noop' : 'pure-deletion'}-${label}`,
            candidate_physical_line: line, before_sha256: sha(before), after_sha256: sha(after),
            witness: f.witness, nuisance_counts_excluding_native_prompt: holdoutFeatures(patch),
          },
        };
        const chunks = chunksFor(row.files);
        assert.equal(chunks.length, 1);
        const chunk = chunks[0];
        assert.equal(chunk.surrounding_diff, patch);
        assert.equal(chunk.lines[0].line, line);
        assert.equal(chunk.lines.length, shape === 'replacement-noop' ? 2 : 1);
        assert.equal(parseReview(JSON.stringify(row.gold), chunk).findings.length, concern ? 1 : 0);
        for (const line_id of row.expected_line_ids)
          assert.equal(parseReview(JSON.stringify({ findings: [{ line_id, reason: f.concern_reason }] }), chunk).findings.length, 1);
        const prompt = await promptFor(chunk, row.context, identity, 'chatml');
        const user = prompt.split('<|im_start|>user\n')[1].split('<|im_end|>')[0];
        assert.ok(!prompt.includes(row.id) && !prompt.includes(row.pair), 'metadata stays outside prompt');
        rows.push(row); pairRows.push({ row, chunk }); prompts.push({ id: row.id, prompt, sha256: sha(prompt) });
        sftRows.push({ id: row.id, kind: 'review', pair: row.pair,
          messages: [{ role: 'system', content: identity.trim() }, { role: 'user', content: user },
            { role: 'assistant', content: JSON.stringify(row.gold) }] });
      }
      const [a, b] = pairRows;
      assert.deepEqual(a.row.context, b.row.context);
      assert.deepEqual(a.chunk.lines, b.chunk.lines);
      assert.deepEqual(holdoutFeatures(a.row.files[0].patch), holdoutFeatures(b.row.files[0].patch));
      const pa = a.row.files[0].patch.split('\n'), pb = b.row.files[0].patch.split('\n');
      const changed = pa.flatMap((l, i) => l === pb[i] ? [] : [i]);
      assert.equal(changed.length, 1, 'labels differ in one unchanged context line');
      assert.ok(pa[changed[0]].startsWith(' ') && pb[changed[0]].startsWith(' '));
    }
  }
  assert.equal(new Set(rows.map(r => r.id)).size, 24);
  const data = rows.map(r => JSON.stringify(r)).join('\n') + '\n';
  return { rows, prompts, sftRows, data, design, design_sha256: sha(designText), sha256: sha(data) };
}

function run(command, args) {
  const p = spawnSync(command, args, { encoding: 'utf8', timeout: 20_000, maxBuffer: 2 ** 20 });
  assert.equal(p.status, 0, `${command}: ${p.error?.message || ''}\n${p.stderr}\n${p.stdout}`);
  return p.stdout;
}

function witnessCode(family, source) {
  switch (family) {
    case 'shift-width':
      source = source.replace('*out = value << shift;', 'if (shift >= 32U) { unsafe_shift = 1; return 77; }\n    *out = value << shift;');
      return { source: '#include <limits.h>\nstatic int unsafe_shift;\n' + source,
        tail: `int main(void) { unsigned counts[] = {0, 1, 31, 32, 33, UINT_MAX};
  _Static_assert(sizeof(uint32_t) * CHAR_BIT == 32, "32-bit fixture");
  for (unsigned i=0; i<6; i++) { uint32_t out=123; unsafe_shift=0; int r=bit_window(1U,counts[i],&out);
    int bad = unsafe_shift || (counts[i] < 32 ? (r != 0 || out != (UINT32_C(1) << counts[i])) : r != -1);
    printf("%u %d\\n", i, bad); } return 0; }`, cases: ['shift=0', 'shift=1', 'shift=31', 'shift=32', 'shift=33', 'shift=UINT_MAX'], bad: [3] };
    case 'bounded-termination':
      return { source, tail: `int main(void) { size_t sizes[] = {1,1,4,4}; unsigned char last[] = {0,65,0,255};
  for (unsigned i=0;i<4;i++) { unsigned char b[4]={19,23,29,31}; b[sizes[i]-1]=last[i]; record_end(b,sizes[i]);
    int bad=b[sizes[i]-1]!=0; if(sizes[i]==4) bad |= b[0]!=19 || b[1]!=23 || b[2]!=29;
    printf("%u %d\\n",i,bad); } return 0; }`, cases: ['n=1,last=0', 'n=1,last=65', 'n=4,last=0', 'n=4,last=255'], bad: [1, 3] };
    case 'reserved-flag-bits':
      return { source, tail: `int main(void) { for(unsigned i=0;i<256;i++) printf("%u %d\\n",i,flags_byte((uint8_t)i)!=(i & 15U)); return 0; }`,
        cases: Array.from({ length: 256 }, (_, i) => `flags=${i}`), bad: Array.from({ length: 240 }, (_, i) => i + 16) };
    case 'erase-target':
      return { source, tail: `int main(void) { unsigned char seeds[]={0,1,65,255}; for(unsigned i=0;i<4;i++) {
  unsigned char out[4]={99,99,99,99}; erase_snapshot(seeds[i],out); int bad=0;
  for(unsigned j=0;j<4;j++) { bad |= out[j]!=0; } printf("%u %d\\n",i,bad); } return 0; }`,
        cases: ['seed=0', 'seed=1', 'seed=65', 'seed=255'], bad: [1, 2, 3] };
    case 'finite-number':
      return { source, tail: `const inputs=[0,1,-2,0.25,Number.MAX_VALUE,NaN,Infinity,-Infinity];
const result=inputs.map((v,i)=>[i,Number.isFinite(v) ? !Object.is(nextReading(v),v+1) : nextReading(v)!==null]);
console.log(JSON.stringify(result));`, cases: ['0', '1', '-2', '0.25', 'MAX_VALUE', 'NaN', 'Infinity', '-Infinity'], bad: [6, 7] };
    case 'array-end-boundary':
      return { source, tail: `const cases=[[[3,5,7],0,3],[[3,5,7],2,7],[[3,5,7],3,null],[[3,5,7],4,null],[[],0,null],[[3],4294967295,null]];
console.log(JSON.stringify(cases.map(([a,i,expected],n)=>[n,!Object.is(slotValue(a,i),expected)])));`,
        cases: ['first', 'last', 'index=length', 'index>length', 'empty,index=0', 'uint32-max'], bad: [2, 4] };
    default: throw new Error(`Unknown witness family: ${family}`);
  }
}

export async function runHoldoutWitnesses(rows) {
  const directory = await mkdtemp(path.join(tmpdir(), 'jovovich-holdout-v5-'));
  const result = [];
  try {
    for (const row of rows) {
      const sides = patchSides(row.files[0].patch), stages = {};
      for (const stage of ['before', 'after']) {
        const source = sides[stage].join('\n') + '\n';
        assert.equal(sha(source), row.audit_metadata[`${stage}_sha256`]);
        const w = witnessCode(row.audit_metadata.family, source);
        const stem = path.join(directory, `${row.id}-${stage}`);
        let outputs;
        if (row.audit_metadata.language === 'c') {
          await writeFile(stem + '.c', source);
          run(process.env.CC || 'cc', ['-std=c11', '-Wall', '-Wextra', '-Werror', '-fsyntax-only', stem + '.c']);
          await writeFile(stem + '-probe.c', '#include <stdio.h>\n' + w.source + '\n' + w.tail + '\n');
          run(process.env.CC || 'cc', ['-std=c11', '-Wall', '-Wextra', '-Werror', stem + '-probe.c', '-o', stem]);
          outputs = run(stem, []).trim().split('\n').map(l => l.split(' ').map(Number));
        } else {
          await writeFile(stem + '.mjs', w.source + '\n' + w.tail + '\n');
          run(process.execPath, ['--check', stem + '.mjs']);
          outputs = JSON.parse(run(process.execPath, [stem + '.mjs']));
        }
        assert.equal(outputs.length, w.cases.length);
        const failing = outputs.filter(([i, bad], n) => { assert.equal(i, n); return Boolean(bad); }).map(([i]) => i);
        assert.deepEqual(failing, stage === 'after' && row.expected_concern ? w.bad : [], `${row.id} ${stage}`);
        stages[stage] = { source_sha256: sha(source), cases: w.cases, failing_case_indices: failing };
      }
      result.push({ id: row.id, language: row.audit_metadata.language, stages });
    }
    return { status: 'pass', rows: rows.length, source_states_checked: result.length * 2,
      shift_probe: 'Before an invalid shift could execute, record reachability and return 77. Valid shifts execute the original expression. All original C sources are separately syntax checked.',
      no_model_inference: true, results: result };
  } finally { await rm(directory, { recursive: true, force: true }); }
}

async function exclusiveWrite(outputs) {
  const handles = [];
  try {
    for (const [name, data] of outputs) { const handle = await open(name, 'wx'); handles.push([name, handle]); await handle.writeFile(data); }
    await Promise.all(handles.map(([, h]) => h.close()));
  } catch (error) {
    await Promise.all(handles.map(async ([name, h]) => { await h.close().catch(() => {}); await unlink(name).catch(() => {}); }));
    throw error;
  }
}

async function main(args) {
  let root = ROOT, output, audit, verify = false;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--verify') verify = true;
    else if (['--root', '--out', '--audit'].includes(args[i]) && args[i + 1] && !args[i + 1].startsWith('--')) {
      const option = args[i], value = args[++i];
      if (option === '--root') root = path.resolve(value); else if (option === '--out') output = path.resolve(value); else audit = path.resolve(value);
    } else throw new Error('Usage: build_holdout_v5.mjs [--root DIR] [--out NEW.jsonl] [--audit NEW.json] [--verify]');
  }
  output ||= path.join(root, HOLDOUT_OUTPUT);
  assert.ok(!audit || audit !== output, 'distinct output and audit paths');
  for (const name of [...(verify ? [] : [output]), ...(audit ? [audit] : [])]) {
    try { await lstat(name); } catch (error) { if (error.code === 'ENOENT') continue; throw error; }
    throw new Error(`Refusing existing output: ${name}`);
  }
  const built = await buildHoldoutV5(root), witnesses = await runHoldoutWitnesses(built.rows);
  if (verify) assert.equal(await readFile(output, 'utf8'), built.data, 'checked-in holdout matches deterministic builder');
  const outputs = verify ? [] : [[output, built.data]];
  if (audit) outputs.push([audit, JSON.stringify({ ...witnesses, corpus_sha256: built.sha256, design_sha256: built.design_sha256 }, null, 2) + '\n']);
  await exclusiveWrite(outputs);
  process.stdout.write(JSON.stringify({ status: 'pass', rows: 24, sha256: built.sha256, verification_only: verify, no_model_inference: true }) + '\n');
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main(process.argv.slice(2)).catch(error => { console.error(error.message); process.exitCode = 1; });
