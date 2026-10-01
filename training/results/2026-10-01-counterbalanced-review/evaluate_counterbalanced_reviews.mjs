#!/usr/bin/env node
// Natural generation with complete native token traces and frozen input bindings.
import assert from 'node:assert/strict';
import { createReadStream } from 'node:fs';
import { readFile, mkdir, open } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = process.cwd();
export const PLAN_PATH = 'models/counterbalanced-review-plan.json';
const { assess } = await import(pathToFileURL(path.join(ROOT, 'training/results/2026-09-29-small-step/probe_shared_prefix.mjs')));
const { chunksFor, promptFor } = await import(pathToFileURL(path.join(ROOT, 'bin/jovovich.mjs')));
export const sha = bytes => createHash('sha256').update(bytes).digest('hex');
export const jsonl = text => {
  assert.ok(text.endsWith('\n'), 'incomplete final JSONL record');
  return text.trim().split('\n').filter(Boolean).map(JSON.parse);
};
export async function fileHash(file) {
  const h = createHash('sha256');
  for await (const bytes of createReadStream(file)) h.update(bytes);
  return h.digest('hex');
}
export async function frozenPlan() {
  const bytes = await readFile(PLAN_PATH), plan = JSON.parse(bytes);
  for (const [key, binding] of Object.entries(plan.frozen_evaluation)) {
    assert.equal(typeof binding.path, 'string', `missing binding path: ${key}`);
    assert.equal(await fileHash(binding.path), binding.sha256, `frozen evaluation changed: ${key}`);
  }
  return { plan, plan_sha256: sha(bytes) };
}

export async function casesFor(kind, plan) {
  assert.ok(['train', 'transfer', 'diagnostics'].includes(kind));
  const binding = plan.frozen_evaluation[kind === 'train' ? 'corpus' : kind];
  const source = binding.path, text = await readFile(source, 'utf8');
  assert.equal(sha(text), binding.sha256);
  const rows = jsonl(text), cases = [];
  if (kind === 'train') {
    const audit = JSON.parse(await readFile(plan.frozen_evaluation.corpus_audit.path, 'utf8'));
    assert.equal(audit.corpus.sha256, binding.sha256);
    const quartet = new Map(audit.quartet_rows.map(row => [row.id, row]));
    assert.equal(quartet.size, audit.quartet_rows.length);
    for (const [sourceRow, row] of rows.entries()) {
      if (row.kind !== 'review') continue;
      assert.deepEqual(row.messages.map(m => m.role), ['system', 'user', 'assistant']);
      const [system, user, answer] = row.messages.map(m => m.content);
      const shown = [...user.matchAll(/^\[(\d+)\] (ADDED|REMOVED) (.+?):(\d+): (.*)$/gm)];
      assert.ok(shown.length && shown.every((m, i) => Number(m[1]) === i + 1 && m[3] === shown[0][3]));
      const findings = JSON.parse(answer).findings; assert.ok(Array.isArray(findings));
      const chunk = { path: shown[0][3], lines: shown.map(m => ({ side: m[2] === 'ADDED' ? 'RIGHT' : 'LEFT', line: Number(m[4]), quote: m[5] })) };
      cases.push({ name: row.id, pair: row.pair, source_row: sourceRow, cohort: kind,
        prompt: `<|im_start|>system\n${system}<|im_end|>\n<|im_start|>user\n${user}<|im_end|>\n<|im_start|>assistant\n`,
        chunk, context: 2048, expected_concern: findings.length > 0,
        expected_line_ids: findings.map(f => f.line_id), expected_response: answer,
        expected_reason_concept: null, audit_metadata: quartet.get(row.id) ?? null });
    }
  } else {
    const identity = await readFile(plan.frozen_evaluation.identity.path, 'utf8');
    for (const row of rows) {
      const chunks = chunksFor(row.files); assert.equal(chunks.length, 1);
      cases.push({ name: row.id, pair: row.pair, source_row: null, cohort: kind,
        prompt: await promptFor(chunks[0], row.context, identity, 'chatml'), chunk: chunks[0], context: 8192,
        expected_concern: row.expected_concern, expected_line_ids: row.expected_line_ids,
        expected_response: null, expected_reason_concept: row.expected_reason_concept ?? null,
        audit_metadata: row.audit_metadata ?? row.metadata ?? null });
    }
  }
  assert.ok(cases.length);
  assert.equal(new Set(cases.map(c => c.name)).size, cases.length);
  const pairs = new Map();
  for (const c of cases) {
    assert.equal(typeof c.name, 'string'); assert.ok(c.name);
    assert.equal(typeof c.pair, 'string'); assert.ok(c.pair);
    assert.equal(typeof c.expected_concern, 'boolean');
    assert.ok(Array.isArray(c.expected_line_ids));
    assert.ok(c.expected_line_ids.every(id => Number.isInteger(id) && id > 0 && id <= c.chunk.lines.length));
    assert.equal(c.expected_line_ids.length > 0, c.expected_concern);
    pairs.set(c.pair, [...(pairs.get(c.pair) ?? []), c]);
  }
  for (const pair of pairs.values()) assert.deepEqual(pair.map(c => c.expected_concern).sort(), [false, true]);
  for (const arm of ['control', 'counterbalanced']) assert.equal(cases.length, plan.evaluation[arm][`${kind}_natural`]);
  return { cases, source, source_sha256: sha(text) };
}

export function validateTrace(trace, originalIds) {
  assert.equal(trace.schema_version, 1);
  assert.deepEqual(trace.prompt_token_ids, originalIds);
  assert.ok(Array.isArray(trace.generated_token_ids) && trace.generated_token_ids.length > 0);
  assert.ok(trace.generated_token_ids.every(id => Number.isInteger(id) && id >= 0));
  assert.ok(trace.generated_token_ids.length <= 192);
  assert.ok(Number.isInteger(trace.emitted_tokens) && trace.emitted_tokens >= 0 && trace.emitted_tokens <= 192);
  assert.equal(trace.requested_limit, 192);
  assert.ok(['eos', 'token-limit'].includes(trace.stop_reason));
  assert.equal(trace.generated_token_ids.length, trace.emitted_tokens + (trace.stop_reason === 'eos' ? 1 : 0));
  if (trace.stop_reason === 'token-limit') assert.equal(trace.emitted_tokens, 192);
}

async function main() {
  const opts = {};
  for (let i = 2; i < process.argv.length; i += 2) {
    assert.ok(process.argv[i].startsWith('--') && process.argv[i + 1]);
    const key = process.argv[i].slice(2); assert.ok(!Object.hasOwn(opts, key)); opts[key] = process.argv[i + 1];
  }
  for (const key of Object.keys(opts)) assert.ok(['model', 'kind', 'mode', 'output', 'trace-dir', 'shard'].includes(key), 'unknown argument');
  for (const key of ['model', 'kind', 'output', 'trace-dir']) assert.ok(opts[key], `${key} required`);
  assert.ok(opts.mode === undefined || opts.mode === 'natural', 'only natural generation is allowed');
  assert.ok(opts.shard === undefined || opts.kind === 'train' && ['0', '1'].includes(opts.shard), 'only train supports shards 0/1');
  const { plan, plan_sha256 } = await frozenPlan();
  assert.equal(plan.frozen_evaluation.probe.sha256, await fileHash(fileURLToPath(import.meta.url)));
  const { cases: allCases, ...source } = await casesFor(opts.kind, plan);
  const shard = opts.shard === undefined ? null : Number(opts.shard);
  const cases = allCases.filter((c, i) => shard === null || i % 2 === shard);
  const model = path.resolve(opts.model), runner = path.resolve(plan.frozen_evaluation.runner.path);
  const hashes = { plan_sha256, model_sha256: await fileHash(model),
    runner_sha256: plan.frozen_evaluation.runner.sha256, infer_source_sha256: plan.frozen_evaluation.infer.sha256,
    host_sha256: plan.frozen_evaluation.host.sha256, probe_source_sha256: plan.frozen_evaluation.probe.sha256,
    source_sha256: source.source_sha256 };
  const env = { ...process.env, NT_NO_I8: '1', NT_QMV_THREADS: '2', NT_ATTN_THREADS: '2', NT_SIMD_THREADS: '2' };
  const run = (c, args) => spawnSync(runner, ['--model', model, '--tokens', '192', '--context', String(c.context), '--temperature', '0', ...args],
    { cwd: ROOT, input: c.prompt, encoding: 'utf8', env, timeout: 600000, maxBuffer: 8 * 1024 * 1024 });
  const prepared = cases.map(c => {
    const r = run(c, ['--token-ids']); assert.equal(r.status, 0, r.error?.message || r.stderr);
    assert.match(r.stdout.trim(), /^\d+(,\d+)*$/);
    return { c, originalIds: r.stdout.trim().split(',').map(Number) };
  });
  await mkdir(path.dirname(path.resolve(opts.output)), { recursive: true });
  await mkdir(path.resolve(opts['trace-dir']), { recursive: false });
  const output = await open(opts.output, 'wx');
  try {
    for (const [i, { c, originalIds }] of prepared.entries()) {
      const traceFile = path.resolve(opts['trace-dir'], String(i).padStart(3, '0') + '.json');
      const started = Date.now(), r = run(c, ['--trace-tokens', traceFile]);
      assert.equal(r.status, 0, r.error?.message || r.stderr);
      const traceText = await readFile(traceFile, 'utf8'), trace = JSON.parse(traceText);
      validateTrace(trace, originalIds);
      const record = { ...hashes, name: c.name, pair: c.pair, kind: opts.kind, mode: 'natural', shard,
        cohort_cases: allCases.length, shard_cases: cases.length, source_row: c.source_row, model, source: source.source,
        expected_concern: c.expected_concern, expected_line_ids: c.expected_line_ids,
        expected_reason_concept: c.expected_reason_concept, expected_response: c.expected_response,
        audit_metadata: c.audit_metadata, prompt: c.prompt, prompt_sha256: sha(c.prompt), supplied_prompt_sha256: sha(c.prompt),
        supplied_prefix: '', supplied_prefix_ids: [], original_prompt_ids: originalIds, chunk: c.chunk,
        decoding: { temperature: 0, continuation_tokens: 192, context: c.context, threads: 2, NT_NO_I8: '1' },
        continuation: r.stdout, assembled_response: r.stdout, trace, trace_file: traceFile, trace_sha256: sha(traceText),
        actual_first_token_id: trace.generated_token_ids[0], stop_reason: trace.stop_reason,
        assessment: assess(r.stdout, c.chunk), returncode: r.status, elapsed_ms: Date.now() - started, stderr: r.stderr };
      await output.write(JSON.stringify(record) + '\n'); await output.sync();
      process.stdout.write(JSON.stringify({ name: c.name, kind: opts.kind, first_id: record.actual_first_token_id, stop: trace.stop_reason }) + '\n');
    }
    assert.equal(await fileHash(model), hashes.model_sha256, 'model changed');
    assert.equal((await frozenPlan()).plan_sha256, plan_sha256, 'plan changed');
  } finally { await output.close(); }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url))
  main().catch(error => { process.stderr.write(`evaluate-counterbalanced: ${error.message}\n`); process.exitCode = 1; });
