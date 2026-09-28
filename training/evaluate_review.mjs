#!/usr/bin/env node
import { createReadStream } from 'node:fs';
import { readFile, open, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chunksFor, promptFor, infer, parseReview } from '../bin/jovovich.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sha256 = data => createHash('sha256').update(data).digest('hex');
const help = `Usage: node training/evaluate_review.mjs --model MODEL.gguf --output RESULTS.jsonl
  [--tokens 256] [--cases training/review_cases.jsonl] [--suffix-file FILE]

Uses the normal JOVOVICH prompt and notorch inference path. A suffix file is
appended verbatim after the assistant prefix; no model template is guessed.
The output must be a new file. Results are written after each case.
structural_location_pass checks concern presence and expected changed-line IDs.
Reason meaning is retained for manual assessment, with no keyword grading.
`;

async function main() {
  const args = process.argv.slice(2);
  if (args.includes('--help')) { process.stdout.write(help); return; }
  const opts = { tokens: '256', cases: path.join(ROOT, 'training/review_cases.jsonl') };
  for (let i = 0; i < args.length; i++) {
    if (!['--model', '--output', '--tokens', '--cases', '--suffix-file'].includes(args[i]) || !args[i + 1]) throw new Error(`Unknown or incomplete argument: ${args[i]}`);
    opts[args[i].slice(2)] = args[++i];
  }
  const tokens = Number(opts.tokens);
  if (!opts.model || !opts.output || !Number.isInteger(tokens) || tokens < 1 || tokens >= 8192) throw new Error(help);
  const casesText = await readFile(opts.cases, 'utf8');
  const cases = casesText.split(/\r?\n/).filter(line => line.trim()).map(line => JSON.parse(line));
  if (!cases.length || new Set(cases.map(c => c.id)).size !== cases.length) throw new Error('Cases must have unique IDs and cannot be empty');
  const prepared = cases.map(c => {
    const chunks = chunksFor(c.files);
    if (chunks.length !== 1 || typeof c.expected_concern !== 'boolean' || !Array.isArray(c.expected_line_ids) ||
        c.expected_concern !== (c.expected_line_ids.length > 0) ||
        c.expected_line_ids.some(id => !Number.isInteger(id) || id < 1 || id > chunks[0].lines.length)) {
      throw new Error(`Invalid single-chunk case or expected line IDs: ${c.id}`);
    }
    return { ...c, chunk: chunks[0] };
  });
  const identity = await readFile(path.join(ROOT, 'prompts/identity.txt'), 'utf8');
  const suffix = opts['suffix-file'] ? await readFile(opts['suffix-file'], 'utf8') : '';
  const model = path.resolve(opts.model);
  const modelHash = createHash('sha256');
  for await (const bytes of createReadStream(model)) modelHash.update(bytes);
  const metadata = {
    model, model_sha256: modelHash.digest('hex'), tokens,
    cases_sha256: sha256(casesText), identity_sha256: sha256(identity),
    host_sha256: sha256(await readFile(path.join(ROOT, 'bin/jovovich.mjs'))),
    infer_source_sha256: sha256(await readFile(path.join(ROOT, 'src/infer.c'))),
    decoding: {
      temperature: 0, context: 8192,
      NT_NO_I8: process.env.NT_NO_I8 || null,
      NT_QMV_THREADS: process.env.NT_QMV_THREADS || null,
      NT_ATTN_THREADS: process.env.NT_ATTN_THREADS || null
    },
    chat_template_env: process.env.JOVOVICH_CHAT_TEMPLATE || null,
    suffix_file: opts['suffix-file'] ? path.resolve(opts['suffix-file']) : null,
    suffix_sha256: sha256(suffix)
  };
  await mkdir(path.dirname(path.resolve(opts.output)), { recursive: true });
  const output = await open(opts.output, 'wx');
  const previous = process.env.JOVOVICH_MODEL;
  process.env.JOVOVICH_MODEL = model;
  let passed = 0, errors = 0;
  try {
    for (const c of prepared) {
      const prompt = await promptFor(c.chunk, c.context, identity) + suffix;
      const record = {
        ...metadata, case_id: c.id, pair: c.pair, started_at: new Date().toISOString(),
        prompt_sha256: sha256(prompt),
        expected_concern: c.expected_concern, expected_line_ids: c.expected_line_ids,
        expected_reason_concept: c.expected_reason_concept,
        raw_response: null, parsed_findings: null, returned_line_ids: null,
        error: null, structural_location_pass: false, semantic_assessment: null
      };
      const started = performance.now();
      let phase = 'inference';
      try {
        record.raw_response = await infer(prompt, tokens);
        phase = 'parse';
        record.parsed_findings = parseReview(record.raw_response, c.chunk).findings;
        record.returned_line_ids = record.parsed_findings.map(f => c.chunk.lines.findIndex(l => l.line === f.line && l.side === f.side && l.quote === f.quote) + 1);
        record.structural_location_pass = c.expected_concern
          ? c.expected_line_ids.every(id => record.returned_line_ids.includes(id)) && record.returned_line_ids.every(id => c.expected_line_ids.includes(id))
          : record.parsed_findings.length === 0;
      } catch (e) {
        record.error = { phase, message: e.message };
        errors++;
      }
      record.elapsed_ms = Math.round(performance.now() - started);
      if (record.structural_location_pass) passed++;
      await output.write(JSON.stringify(record) + '\n');
      await output.sync();
      process.stderr.write(`${c.id}: structural/location ${record.structural_location_pass ? 'PASS' : 'FAIL'}${record.error ? ` (${record.error.phase} error)` : ''}, ${record.elapsed_ms} ms\n`);
    }
  } finally {
    await output.close();
    if (previous === undefined) delete process.env.JOVOVICH_MODEL;
    else process.env.JOVOVICH_MODEL = previous;
  }
  process.stderr.write(`Structural/location: ${passed}/${prepared.length}; execution/parse errors: ${errors}. Reasons await manual assessment.\n`);
  if (errors) process.exitCode = 2;
}

main().catch(e => { process.stderr.write(`evaluate_review: ${e.message}\n`); process.exitCode = 1; });
