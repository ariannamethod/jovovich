#!/usr/bin/env node
// Fixed, hash-pinned diagnostic. Run only after the matched-shape plan is frozen.
import assert from 'node:assert/strict';
import { createReadStream } from 'node:fs';
import { readFile, mkdir, open, lstat, readdir, rmdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const SELF = fileURLToPath(import.meta.url), HERE = path.dirname(SELF);
const ROOT = process.cwd();
const PREFIX = '{"findings', PREFIX_IDS = [4913, 3903, 819];
const DECODING = { temperature: 0, continuation_tokens: 192, context: 2048, threads: 2, NT_NO_I8: '1' };
const FIXED = {
  model: path.join(ROOT, 'models/decision-small-step-selected.gguf'),
  cases: path.join(HERE, 'matched-shape-cases.jsonl'),
  runner: path.join(ROOT, 'build/jovovich-infer'),
  infer: path.join(ROOT, 'src/infer.c'), host: path.join(ROOT, 'bin/jovovich.mjs'), wrapper: SELF
};
const sha = value => createHash('sha256').update(value).digest('hex');
const resolveSource = value => path.resolve(ROOT, value);
async function fileHash(file) {
  const hash = createHash('sha256');
  for await (const bytes of createReadStream(file)) hash.update(bytes);
  return hash.digest('hex');
}
async function absent(file) {
  try { await lstat(file); } catch (e) { if (e.code === 'ENOENT') return; throw e; }
  throw new Error(`Destination already exists: ${file}`);
}
function ids(value, label) {
  assert.ok(Array.isArray(value) && value.length > 0 && value.every(n => Number.isSafeInteger(n) && n >= 0), label);
}
function assess(response, chunk, parseReview) {
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

async function main() {
  const opts = {};
  for (let i = 2; i < process.argv.length; i += 2) {
    const flag = process.argv[i], value = process.argv[i + 1];
    assert.ok(['--output', '--trace-dir', '--plan'].includes(flag) && value && !value.startsWith('--'), 'Unknown or incomplete argument');
    assert.ok(!Object.hasOwn(opts, flag), `Duplicate argument: ${flag}`); opts[flag] = value;
  }
  assert.ok(opts['--output'] && opts['--trace-dir'], 'Required: --output NEW.jsonl --trace-dir NEW_DIR [--plan PATH]');
  const outputPath = path.resolve(opts['--output']), traceDir = path.resolve(opts['--trace-dir']);
  const planPath = path.resolve(opts['--plan'] ?? path.join(HERE, 'matched-shape-plan.json'));
  const planText = await readFile(planPath, 'utf8'), plan = JSON.parse(planText), planHash = sha(planText);
  assert.equal(plan.schema_version, 1, 'Unsupported plan schema');
  assert.equal(resolveSource(plan.output), path.join(ROOT, 'models/matched-shape-control.jsonl'));
  assert.equal(resolveSource(plan.trace_dir), path.join(ROOT, 'models/matched-shape-control-traces'));
  assert.equal(outputPath, resolveSource(plan.output), 'Output destination differs from plan');
  assert.equal(traceDir, resolveSource(plan.trace_dir), 'Trace destination differs from plan');
  assert.deepEqual(plan.decoding, DECODING, 'Only the fixed decoding plan is supported');
  assert.equal(plan.supplied_prefix, PREFIX); assert.deepEqual(plan.supplied_prefix_ids, PREFIX_IDS);
  assert.equal(resolveSource(plan.model.path), FIXED.model, 'Only the selected checkpoint is supported');
  for (const key of ['cases', 'runner', 'infer', 'host', 'wrapper'])
    assert.equal(resolveSource(plan.sources[key]?.path), FIXED[key], `Unsupported source path: ${key}`);
  const pinned = [['model', plan.model], ...Object.entries(plan.sources)];
  assert.ok(!Object.hasOwn(plan.sources, 'model'), 'model belongs outside sources');
  for (const [name, entry] of pinned) {
    assert.equal(typeof entry.path, 'string', `Missing path: ${name}`);
    assert.match(entry.sha256, /^[a-f0-9]{64}$/, `Invalid SHA-256: ${name}`);
  }
  async function verifyHashes() {
    assert.equal(await fileHash(planPath), planHash, 'Plan changed during probe');
    for (const [name, entry] of pinned)
      assert.equal(await fileHash(resolveSource(entry.path)), entry.sha256, `Hash mismatch: ${name}`);
  }
  await verifyHashes();
  const sourceText = await readFile(FIXED.cases, 'utf8');
  assert.equal(sha(sourceText), plan.sources.cases.sha256);
  assert.ok(sourceText.endsWith('\n'), 'Cases must be newline-terminated JSONL');
  const cases = sourceText.trimEnd().split('\n').map(JSON.parse);
  assert.equal(cases.length, 8, 'Exactly eight cases are required');
  assert.equal(new Set(cases.map(c => c.name)).size, 8, 'Duplicate case name');
  assert.deepEqual(cases.map(c => c.name), plan.case_ids, 'Case IDs/order differ from plan');
  const pairs = new Map(), originals = new Map();
  for (const c of cases) {
    assert.equal(typeof c.name, 'string'); assert.ok(c.name); assert.equal(c.id, c.name);
    assert.equal(typeof c.pair, 'string'); assert.ok(c.pair);
    assert.deepEqual(c.messages.map(m => m.role), ['system', 'user']);
    assert.ok(c.messages.every(m => typeof m.content === 'string' && !m.content.includes('\0')));
    const prompt = c.messages.map(m => `<|im_start|>${m.role}\n${m.content}<|im_end|>\n`).join('') + '<|im_start|>assistant\n';
    assert.equal(c.prompt, prompt, `Stored ChatML differs: ${c.name}`);
    assert.equal(c.prompt_sha256, sha(prompt), `Stored prompt hash differs: ${c.name}`);
    assert.equal(typeof c.expected_concern, 'boolean');
    assert.ok(c.chunk && typeof c.chunk.path === 'string' && Array.isArray(c.chunk.lines) && c.chunk.lines.length);
    const shown = [...c.messages[1].content.matchAll(/^\[(\d+)\] (ADDED|REMOVED) (.+?):(\d+): (.*)$/gm)];
    assert.deepEqual(shown.map(m => Number(m[1])), c.chunk.lines.map((_, i) => i + 1), `Changed-line IDs differ: ${c.name}`);
    assert.ok(shown.every(m => m[3] === c.chunk.path), `Changed-line paths differ: ${c.name}`);
    assert.deepEqual(shown.map(m => ({ side: m[2] === 'ADDED' ? 'RIGHT' : 'LEFT', line: Number(m[4]), quote: m[5] })),
      c.chunk.lines.map(({ side, line, quote }) => ({ side, line, quote })), `Changed-line citations differ: ${c.name}`);
    assert.ok(Array.isArray(c.expected_line_ids) && c.expected_line_ids.every(n => Number.isInteger(n) && n >= 1 && n <= c.chunk.lines.length));
    assert.equal(c.expected_line_ids.length > 0, c.expected_concern);
    assert.ok(c.expected_reason_concept === null || typeof c.expected_reason_concept === 'string');
    assert.equal(typeof c.metadata?.is_original_baseline, 'boolean');
    assert.equal(typeof c.metadata.original_training_id, 'string'); assert.ok(c.metadata.original_training_id);
    if (c.metadata.is_original_baseline) {
      ids(c.original_prompt_expected_ids, `Baseline original IDs missing: ${c.name}`);
      assert.equal(typeof c.expected_response, 'string'); assert.ok(c.expected_response.startsWith(PREFIX));
    } else {
      assert.equal(c.original_prompt_expected_ids, null); assert.equal(c.expected_response, null);
    }
    pairs.set(c.pair, [...(pairs.get(c.pair) ?? []), c]);
    originals.set(c.metadata.original_training_id, [...(originals.get(c.metadata.original_training_id) ?? []), c]);
  }
  assert.equal(pairs.size, 4, 'Exactly four harmful/clean pairs are required');
  for (const pair of pairs.values()) {
    assert.deepEqual(pair.map(c => c.expected_concern).sort(), [false, true]);
    assert.equal(new Set(pair.map(c => c.metadata.original_training_id)).size, 1);
  }
  assert.equal(originals.size, 2, 'Exactly two original training cases are required');
  for (const group of originals.values()) {
    assert.equal(group.length, 4); assert.equal(group.filter(c => c.metadata.is_original_baseline).length, 1);
  }
  assert.equal(cases.filter(c => c.metadata.is_original_baseline).length, 2);
  assert.ok(Array.isArray(plan.baselines) && plan.baselines.length === 2, 'Exactly two baseline receipts are required');
  const baselineByName = new Map(plan.baselines.map(b => [b.name, b]));
  assert.equal(baselineByName.size, 2);
  for (const c of cases.filter(c => c.metadata.is_original_baseline)) {
    const baseline = baselineByName.get(c.name); assert.ok(baseline, `Missing baseline receipt: ${c.name}`);
    assert.equal(baseline.original_training_id, c.metadata.original_training_id);
    assert.equal(baseline.previous_prompt_sha256, c.prompt_sha256);
    assert.equal(baseline.expected_first_token_id, 66582);
    assert.match(baseline.previous_assembled_response_sha256, /^[a-f0-9]{64}$/);
    assert.match(baseline.previous_continuation_sha256, /^[a-f0-9]{64}$/);
    assert.ok(pinned.some(([, entry]) => resolveSource(entry.path) === resolveSource(baseline.previous_receipt_path)),
      `Baseline receipt source is not hash-pinned: ${c.name}`);
  }
  assert.notEqual(outputPath, traceDir);
  for (const [, entry] of pinned) assert.notEqual(outputPath, resolveSource(entry.path));
  assert.notEqual(outputPath, planPath);
  await absent(outputPath); await absent(traceDir);

  const { parseReview } = await import(pathToFileURL(FIXED.host));
  const env = { ...process.env, NT_NO_I8: '1', NT_QMV_THREADS: '2', NT_ATTN_THREADS: '2', NT_SIMD_THREADS: '2' };
  const run = (prompt, args = [], reserve = 192) => spawnSync(FIXED.runner,
    ['--model', FIXED.model, '--tokens', String(reserve), '--context', '2048', '--temperature', '0', ...args],
    { cwd: ROOT, input: prompt, encoding: 'utf8', env, timeout: 600_000, maxBuffer: 8 * 1024 * 1024 });
  const tokenize = (prompt, reserve = 192) => {
    const result = run(prompt, ['--token-ids'], reserve);
    assert.equal(result.status, 0, result.error?.message || result.stderr);
    assert.equal(result.signal, null); assert.match(result.stdout.trim(), /^\d+(,\d+)*$/);
    const value = result.stdout.trim().split(',').map(Number); ids(value, 'Invalid native token IDs'); return value;
  };
  // Complete every native boundary/baseline check before creating any artifact.
  const prepared = cases.map(c => {
    const original = tokenize(c.prompt), supplied = tokenize(c.prompt + PREFIX);
    assert.deepEqual(supplied, [...original, ...PREFIX_IDS], `Shared prefix token boundary differs: ${c.name}`);
    if (c.metadata.is_original_baseline)
      assert.deepEqual(original, c.original_prompt_expected_ids, `Original baseline token IDs differ: ${c.name}`);
    const gold = c.expected_response ? tokenize(c.prompt + c.expected_response, 1) : null;
    if (gold) {
      assert.deepEqual(gold.slice(0, supplied.length), supplied, `Gold prefix differs: ${c.name}`);
      assert.equal(gold[supplied.length], c.expected_concern ? 66582 : 788, `Gold next ID differs: ${c.name}`);
    }
    return { original_prompt_ids: original, supplied_prompt_ids: supplied,
      original_prompt_ids_sha256: sha(JSON.stringify(original)), supplied_prompt_ids_sha256: sha(JSON.stringify(supplied)),
      native_boundary_verified: true, baseline_original_ids_verified: c.metadata.is_original_baseline,
      gold_next_id_verified: gold ? gold[supplied.length] : null };
  });
  await verifyHashes();
  await absent(outputPath); await absent(traceDir);
  await mkdir(traceDir, { recursive: false });
  let output;
  try { output = await open(outputPath, 'wx', 0o600); }
  catch (e) { await rmdir(traceDir); throw e; }
  const outputIdentity = await output.stat(), traceIdentity = await lstat(traceDir);
  let writtenBytes = 0;
  const traceNames = [];
  const hashes = { model_sha256: plan.model.sha256, runner_sha256: plan.sources.runner.sha256,
    infer_source_sha256: plan.sources.infer.sha256, host_sha256: plan.sources.host.sha256,
    probe_source_sha256: plan.sources.wrapper.sha256, source_sha256: plan.sources.cases.sha256 };
  try {
    for (const [i, c] of cases.entries()) {
      const currentOutput = await lstat(outputPath), currentDir = await lstat(traceDir);
      assert.ok(currentOutput.isFile() && currentOutput.dev === outputIdentity.dev && currentOutput.ino === outputIdentity.ino);
      assert.equal(currentOutput.size, writtenBytes, 'Output changed externally');
      assert.ok(currentDir.isDirectory() && currentDir.dev === traceIdentity.dev && currentDir.ino === traceIdentity.ino);
      assert.deepEqual((await readdir(traceDir)).sort(), [...traceNames].sort(), 'Trace directory changed externally');
      const traceName = String(i).padStart(3, '0') + '.json', traceFile = path.join(traceDir, traceName);
      await absent(traceFile);
      const started = Date.now(), result = run(c.prompt + PREFIX, ['--trace-tokens', traceFile]);
      assert.equal(result.status, 0, result.error?.message || result.stderr); assert.equal(result.signal, null);
      const traceText = await readFile(traceFile, 'utf8'), trace = JSON.parse(traceText);
      assert.equal(trace.schema_version, 1); assert.deepEqual(trace.prompt_token_ids, prepared[i].supplied_prompt_ids);
      ids(trace.generated_token_ids, `No sampled trace IDs: ${c.name}`);
      assert.ok(trace.generated_token_ids.length <= 192);
      assert.ok(Number.isInteger(trace.emitted_tokens) && trace.emitted_tokens >= 0 && trace.emitted_tokens <= 192);
      assert.equal(trace.requested_limit, 192); assert.ok(['eos', 'token-limit'].includes(trace.stop_reason));
      assert.equal(trace.generated_token_ids.length, trace.emitted_tokens + (trace.stop_reason === 'eos' ? 1 : 0));
      if (trace.stop_reason === 'token-limit') assert.equal(trace.emitted_tokens, 192);
      const stop = result.stderr.match(/generated (\d+) tokens in [^\n]*stop=(eos|token-limit)/);
      assert.ok(stop, `Missing native stop summary: ${c.name}`);
      assert.equal(Number(stop[1]), trace.emitted_tokens); assert.equal(stop[2], trace.stop_reason);
      const assembled = PREFIX + result.stdout;
      const baseline = baselineByName.get(c.name);
      // Replay differences are measurements, not reasons to discard the record.
      const baselineComparison = baseline ? { ...baseline,
        actual_first_token_id_matches: trace.generated_token_ids[0] === baseline.expected_first_token_id,
        assembled_response_sha256: sha(assembled), continuation_sha256: sha(result.stdout),
        assembled_response_matches: sha(assembled) === baseline.previous_assembled_response_sha256,
        continuation_matches: sha(result.stdout) === baseline.previous_continuation_sha256 } : null;
      const record = { ...c, ...hashes, ...prepared[i], kind: 'matched-shape', mode: 'shared', shard: null,
        cohort_cases: 8, shard_cases: 8, model: FIXED.model, source: FIXED.cases, sources: plan.sources,
        plan: planPath, plan_sha256: planHash, prompt_sha256: sha(c.prompt), supplied_prompt_sha256: sha(c.prompt + PREFIX),
        supplied_prefix: PREFIX, supplied_prefix_ids: PREFIX_IDS, decoding: DECODING,
        audit_metadata: c.metadata, continuation: result.stdout, assembled_response: assembled,
        trace, trace_file: traceFile, trace_sha256: sha(traceText), actual_first_token_id: trace.generated_token_ids[0],
        generated_tokens: trace.emitted_tokens, stop_reason: trace.stop_reason,
        stop_stderr: { emitted_tokens: Number(stop[1]), stop_reason: stop[2] },
        assessment: assess(assembled, c.chunk, parseReview), semantic_assessment: null, baseline_comparison: baselineComparison,
        returncode: result.status, signal: result.signal, elapsed_ms: Date.now() - started, stderr: result.stderr };
      const line = JSON.stringify(record) + '\n';
      await output.writeFile(line); await output.sync(); writtenBytes += Buffer.byteLength(line); traceNames.push(traceName);
      process.stdout.write(JSON.stringify({ name: c.name, kind: record.kind, mode: record.mode,
        first_id: record.actual_first_token_id, stop: trace.stop_reason }) + '\n');
    }
    await verifyHashes();
  } finally { await output.close(); }
}

main().catch(e => { process.stderr.write(`matched-shape: ${e.message}\n`); process.exitCode = 1; });
