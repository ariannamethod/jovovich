import { readFile, open } from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const ROOT = process.cwd();
const { chunksFor, promptFor, parseReview } = await import(pathToFileURL(path.join(ROOT, 'bin/jovovich.mjs')));
const [model, output] = process.argv.slice(2);
if (!model || !output) throw new Error('Usage: node probe_verdict_prefix.mjs MODEL.gguf NEW_OUTPUT.jsonl (from repository root)');
const sha = s => createHash('sha256').update(s).digest('hex');
const modelHash = createHash('sha256');
for await (const bytes of createReadStream(model)) modelHash.update(bytes);
const model_sha256 = modelHash.digest('hex');
const forced_prefix = '{"findings":[{"';
const sft = (await readFile('training/sft_review_v2.jsonl', 'utf8')).trim().split('\n').map(JSON.parse);
const review = (await readFile('training/review_holdout_v2.jsonl', 'utf8')).trim().split('\n').map(JSON.parse);
const identity = await readFile('prompts/identity.txt', 'utf8');
const jobs = [];
for (const name of ['scoped-python-analysis-concern', 'allocation-null-guard-introduced']) {
  const row = sft.find(r => r.id === name);
  const prompt = `<|im_start|>system\n${row.messages[0].content}<|im_end|>\n<|im_start|>user\n${row.messages[1].content}<|im_end|>\n<|im_start|>assistant\n`;
  const shown = [...row.messages[1].content.matchAll(/^\[(\d+)\] (ADDED|REMOVED) (.+?):(\d+): (.*)$/gm)];
  if (!shown.length || shown.some((m, i) => Number(m[1]) !== i + 1)) throw new Error('Invalid changed-line fixture');
  const chunk = { path: shown[0][3], lines: shown.map(m => ({ side: m[2] === 'ADDED' ? 'RIGHT' : 'LEFT', line: Number(m[4]), quote: m[5] })) };
  jobs.push({ name, source: 'exact training prompt', prompt, chunk, context: 2048,
    expected_line_ids: JSON.parse(row.messages[2].content).findings.map(f => f.line_id), expected_response: row.messages[2].content });
}
for (const name of ['short-read-accepted', 'archive-subprocess-forbidden']) {
  const row = review.find(r => r.id === name), chunks = chunksFor(row.files);
  if (chunks.length !== 1 || !row.expected_concern) throw new Error('Invalid review diagnostic');
  jobs.push({ name, source: 'existing review diagnostic', prompt: await promptFor(chunks[0], row.context, identity),
    chunk: chunks[0], context: 8192, expected_line_ids: row.expected_line_ids, expected_reason_concept: row.expected_reason_concept });
}
const file = await open(output, 'wx');
try {
  for (const job of jobs) {
    const prompt = job.prompt + forced_prefix, start = performance.now();
    const result = spawnSync('build/jovovich-infer', ['--model', model, '--tokens', '192', '--context', String(job.context), '--temperature', '0'],
      { input: prompt, encoding: 'utf8', env: { ...process.env, NT_NO_I8: '1', NT_QMV_THREADS: '2', NT_ATTN_THREADS: '2', NT_SIMD_THREADS: '2' } });
    const assembled_response = forced_prefix + result.stdout;
    const stop = result.stderr.match(/generated (\d+) tokens .*stop=(eos|token-limit)/);
    const record = { ...job, model, model_sha256, forced_prefix, prompt_sha256: sha(prompt),
      continuation: result.stdout, assembled_response, returncode: result.status, signal: result.signal,
      decoding: { temperature: 0, tokens: 192, context: job.context, threads: 2, NT_NO_I8: '1' },
      generated_tokens: stop ? Number(stop[1]) : null, stop_reason: stop?.[2] ?? null,
      elapsed_ms: Math.round(performance.now() - start), structural_location_pass: false, parsed_findings: null, error: null };
    if (result.status !== 0) record.error = { phase: 'inference', message: result.stderr };
    else {
      try {
        record.parsed_findings = parseReview(assembled_response, job.chunk).findings;
        record.returned_line_ids = record.parsed_findings.map(f => job.chunk.lines.findIndex(l => l.line === f.line && l.side === f.side && l.quote === f.quote) + 1);
        record.structural_location_pass = job.expected_line_ids.every(id => record.returned_line_ids.includes(id)) && record.returned_line_ids.every(id => job.expected_line_ids.includes(id));
      } catch (e) { record.error = { phase: 'parse', message: e.message }; }
    }
    await file.write(JSON.stringify(record) + '\n'); await file.sync();
    process.stdout.write(JSON.stringify({ name: job.name, returncode: result.status, stop_reason: record.stop_reason, structural_location_pass: record.structural_location_pass }) + '\n');
    if (result.status !== 0) throw new Error('Native forced-prefix inference failed');
  }
} finally { await file.close(); }
