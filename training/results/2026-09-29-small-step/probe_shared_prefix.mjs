#!/usr/bin/env node
// Scratch diagnostic: supply the common trained prefix, retaining both verdicts.
import assert from 'node:assert/strict';
import { createReadStream } from 'node:fs';
import { readFile, open } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const PREFIX = '{"findings';
export const PREFIX_IDS = [4913, 3903, 819];
const ROOT = process.cwd();
const { chunksFor, promptFor, parseReview } = await import(pathToFileURL(path.join(ROOT, 'bin/jovovich.mjs')));
const sha = value => createHash('sha256').update(value).digest('hex');
const jsonl = text => text.trim().split('\n').filter(Boolean).map(JSON.parse);
const chat = (system, user) => `<|im_start|>system\n${system}<|im_end|>\n<|im_start|>user\n${user}<|im_end|>\n<|im_start|>assistant\n`;

export function verifyBoundary(original, supplied, gold, expectedNext) {
  assert.deepEqual(supplied, [...original, ...PREFIX_IDS], 'native suffix must append exactly the three trained IDs');
  if (gold) {
    assert.deepEqual(gold.slice(0, supplied.length), supplied, 'gold answer does not share the complete supplied token prefix');
    assert.equal(gold[supplied.length], expectedNext, 'native first divergent gold token changed');
  }
}

export function assess(response, chunk) {
  const result = { json_valid: false, findings_count: null, concern: null, parsed_findings: null, citation_error: null };
  const clean = response.trim().replace(/(?:<\|im_end\|>|<\|endoftext\|>)+\s*$/, '').trim()
    .replace(/^```(?:json)?\s*/, '').replace(/\s*```$/, '');
  try {
    const decoded = JSON.parse(clean), findings = Array.isArray(decoded) ? decoded : decoded?.findings;
    result.json_valid = true;
    if (Array.isArray(findings)) { result.findings_count = findings.length; result.concern = findings.length > 0; }
  } catch {}
  try { result.parsed_findings = parseReview(response, chunk).findings; }
  catch (e) { result.citation_error = e.message; }
  return result;
}

export async function casesFor(cohort, root = ROOT) {
  assert.ok(['train', 'runtime'].includes(cohort), 'cohort must be train or runtime');
  const source = cohort === 'train' ? 'training/sft_review_v2.jsonl' : 'training/review_holdout_v2.jsonl';
  const sourceText = await readFile(path.join(root, source), 'utf8');
  const rows = jsonl(sourceText);
  const cases = [];
  if (cohort === 'train') {
    for (const row of rows.filter(r => r.kind === 'review')) {
      assert.deepEqual(row.messages.map(m => m.role), ['system', 'user', 'assistant']);
      const [system, user, answer] = row.messages.map(m => m.content);
      assert.ok(answer.startsWith(PREFIX), `training answer lacks common prefix: ${row.id}`);
      const shown = [...user.matchAll(/^\[(\d+)\] (ADDED|REMOVED) (.+?):(\d+): (.*)$/gm)];
      assert.ok(shown.length && shown.every((m, i) => Number(m[1]) === i + 1 && m[3] === shown[0][3]));
      const findings = JSON.parse(answer).findings;
      const chunk = { path: shown[0][3], lines: shown.map(m => ({ side: m[2] === 'ADDED' ? 'RIGHT' : 'LEFT', line: Number(m[4]), quote: m[5] })) };
      cases.push({ name: row.id, pair: row.pair, cohort, prompt: chat(system, user), chunk, context: 2048,
        expected_concern: findings.length > 0, expected_line_ids: findings.map(f => f.line_id), expected_response: answer,
        expected_next_id: findings.length ? 66582 : 788 });
    }
  } else {
    const identity = await readFile(path.join(root, 'prompts/identity.txt'), 'utf8');
    for (const row of rows) {
      const chunks = chunksFor(row.files); assert.equal(chunks.length, 1);
      cases.push({ name: row.id, pair: row.pair, cohort, prompt: await promptFor(chunks[0], row.context, identity, 'chatml'),
        chunk: chunks[0], context: 8192, expected_concern: row.expected_concern,
        expected_line_ids: row.expected_line_ids, expected_reason_concept: row.expected_reason_concept });
    }
  }
  assert.equal(cases.length, cohort === 'train' ? 40 : 12);
  assert.equal(new Set(cases.map(c => c.name)).size, cases.length);
  const pairs = new Map();
  for (const c of cases) pairs.set(c.pair, [...(pairs.get(c.pair) || []), c]);
  for (const pair of pairs.values()) assert.deepEqual(pair.map(c => c.expected_concern).sort(), [false, true]);
  return { cases, source, source_sha256: sha(sourceText) };
}

export function matchingNatural(cases, rows, modelHash) {
  const records = new Map();
  for (const r of rows) {
    const name = r.name ?? r.case_id;
    assert.ok(name && !records.has(name), 'duplicate or missing natural case ID');
    records.set(name, r);
  }
  assert.equal(records.size, cases.length, 'natural file must cover this exact cohort');
  return cases.map(c => {
    const r = records.get(c.name); assert.ok(r, `missing natural case ${c.name}`);
    assert.equal(r.model_sha256, modelHash, `natural model mismatch: ${c.name}`);
    assert.equal(r.prompt_sha256, sha(c.prompt), `natural prompt mismatch: ${c.name}`);
    assert.equal(r.decoding?.temperature, 0); assert.equal(r.decoding?.context, c.context);
    assert.equal(r.decoding?.NT_NO_I8, '1');
    assert.equal(r.decoding?.NT_QMV_THREADS, '2'); assert.equal(r.decoding?.NT_ATTN_THREADS, '2');
    assert.equal(r.tokens ?? r.decoding?.tokens, 192);
    assert.equal(r.returncode ?? 0, 0);
    assert.notEqual(r.error?.phase, 'inference');
    const response = r.response ?? r.raw_response; assert.equal(typeof response, 'string');
    return { response, response_sha256: sha(response), assessment: assess(response, c.chunk) };
  });
}

export function shardIndices(length, shard) {
  assert.ok(shard === null || shard === 0 || shard === 1, 'shard must be 0 or 1');
  return Array.from({ length }, (_, i) => i).filter(i => shard === null || i % 2 === shard);
}

async function hashFile(file) {
  const h = createHash('sha256');
  for await (const bytes of createReadStream(file)) h.update(bytes);
  return h.digest('hex');
}

async function main() {
  const [modelArg, naturalArg, outputArg, ...extra] = process.argv.slice(2);
  if (!modelArg || !naturalArg || !outputArg || (extra.length &&
      (extra.length !== 2 || extra[0] !== '--shard' || !['0', '1'].includes(extra[1])))) throw new Error(
    'Usage (from repository root): node ../reference/probe_shared_prefix.mjs MODEL.gguf MATCHING_NATURAL.jsonl NEW_OUTPUT.jsonl [--shard 0|1]');
  const cohort = 'train', shard = extra.length ? Number(extra[1]) : null;
  const model = path.resolve(modelArg), runner = path.join(ROOT, 'build/jovovich-infer');
  const modelHash = await hashFile(model);
  const { cases: allCases, ...source } = await casesFor(cohort);
  const naturalText = await readFile(naturalArg, 'utf8');
  const allNatural = matchingNatural(allCases, jsonl(naturalText), modelHash);
  const indices = shardIndices(allCases.length, shard);
  const cases = indices.map(i => allCases[i]), natural = indices.map(i => allNatural[i]);
  const env = { ...process.env, NT_NO_I8: '1', NT_QMV_THREADS: '2', NT_ATTN_THREADS: '2', NT_SIMD_THREADS: '2' };
  const run = (c, prompt, tokenIds = false) => spawnSync(runner,
    ['--model', model, '--tokens', tokenIds ? '1' : '192', '--context', String(c.context), '--temperature', '0', ...(tokenIds ? ['--token-ids'] : [])],
    { cwd: ROOT, input: prompt, encoding: 'utf8', env, timeout: 600_000, maxBuffer: 8 * 1024 * 1024 });
  const tokenize = (c, prompt) => {
    const result = run(c, prompt, true);
    assert.equal(result.status, 0, result.error?.message || result.stderr);
    const text = result.stdout.trim(); assert.match(text, /^\d+(,\d+)*$/);
    return text.split(',').map(Number);
  };
  // Validate every boundary before any generation or result file is created.
  const tokenized = cases.map(c => {
    const original = tokenize(c, c.prompt), supplied = tokenize(c, c.prompt + PREFIX);
    const gold = c.expected_response ? tokenize(c, c.prompt + c.expected_response) : null;
    verifyBoundary(original, supplied, gold, c.expected_next_id);
    return { original_prompt_ids: original, supplied_prompt_ids: supplied,
      original_prompt_ids_sha256: sha(JSON.stringify(original)), supplied_prompt_ids_sha256: sha(JSON.stringify(supplied)),
      native_boundary_verified: true, gold_next_id_verified: gold ? c.expected_next_id : null };
  });
  const metadata = { model: modelArg, model_sha256: modelHash, natural_source: naturalArg,
    natural_source_sha256: sha(naturalText), ...source, runner_sha256: await hashFile(runner),
    infer_source_sha256: await hashFile(path.join(ROOT, 'src/infer.c')), host_sha256: await hashFile(path.join(ROOT, 'bin/jovovich.mjs')),
    probe_source_sha256: await hashFile(fileURLToPath(import.meta.url)), supplied_prefix: PREFIX, supplied_prefix_ids: PREFIX_IDS,
    shard, cohort_cases: allCases.length, shard_cases: cases.length,
    decoding: { temperature: 0, continuation_tokens: 192, supplied_prefix_tokens: 3, context: 2048, threads: 2, NT_NO_I8: '1' } };
  const file = await open(outputArg, 'wx');
  try {
    for (const [i, c] of cases.entries()) {
      const start = performance.now(), result = run(c, c.prompt + PREFIX);
      const assembled = PREFIX + result.stdout;
      const stop = result.stderr.match(/generated (\d+) tokens .*stop=(eos|token-limit)/);
      const record = { ...c, ...metadata, ...tokenized[i], original_prompt_sha256: sha(c.prompt),
        supplied_prompt_sha256: sha(c.prompt + PREFIX), natural: natural[i], continuation: result.stdout, assembled_response: assembled,
        returncode: result.status, signal: result.signal, generated_tokens: stop ? Number(stop[1]) : null,
        stop_reason: stop?.[2] ?? null, elapsed_ms: Math.round(performance.now() - start),
        assessment: result.status === 0 ? assess(assembled, c.chunk) : null,
        execution_error: result.status === 0 ? null : result.error?.message || result.stderr, semantic_assessment: null };
      await file.write(JSON.stringify(record) + '\n'); await file.sync();
      process.stdout.write(JSON.stringify({ case: c.name, returncode: result.status, stop_reason: record.stop_reason,
        natural_concern: natural[i].assessment.concern, supplied_prefix_concern: record.assessment?.concern }) + '\n');
      assert.equal(result.status, 0, record.execution_error);
    }
  } finally { await file.close(); }
  assert.equal(await hashFile(model), modelHash, 'model changed while probing');
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url))
  main().catch(e => { process.stderr.write(`shared-prefix: ${e.message}\n`); process.exitCode = 1; });
