#!/usr/bin/env node
// Manipulation check: the analysis opens with "Rule: " and a verbatim span of the prompt's own AGENTS.md sections.
import { createHash } from 'node:crypto';
import { closeSync, openSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { chunksFor, promptFor } from '../../bin/jovovich.mjs';

const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const MIN_QUOTE = 40;
const PREAMBLE = 'AGENTS.md rules below are ordered root to nearest directory.';
const README = 'README.md (repository-wide context):';
const DIFF = '\n\nSurrounding diff:';
const USER = '<|im_start|>user\n', END = '<|im_end|>';
const sha = value => createHash('sha256').update(value).digest('hex');
const need = (ok, message) => { if (!ok) throw new Error(message); };
const PINS = {
  'training/sft_review_v6_before.jsonl': 'a2f22e789b176b1f23ed1262b3e94449819a1484ed31ddb87c3dbedbb8574250',
  'training/review_holdout_v5.jsonl': 'e066e033cd339243b0eb099291c69540cb183e725d1643f5c4e04af9e6c22451',
  'training/explanations/reasons.json': 'c2269304dea5dbe65a42308116a51b383d9a535ec47fca7cedd122136c670e45',
  'training/explanations/build_corpora.py': '1c8c2427571aad38176dae000272546af24bc07d8ab75e4ac122f36d8bd0c2bc',
  'bin/jovovich.mjs': '570f01033adcc144f6bac8448dcec0a357b9fa2c193a6f2bc9f4a3ca7fa981c2',
  'prompts/identity.txt': '187cdf809c21e28c1bb2f1fb71c6bbb1aabf32b7a0c987ba24b52bf4452d62f8',
};
const TRAIN_CORPUS_HASHES = [PINS['training/sft_review_v6_before.jsonl'],
  'd5f3e06e62440135d2a4e8a91c99705d68e69ce3ad2dde5bac272ba647b42218',
  '43d85910640550abc48685347f11644a9c3e086dbb083de1e16f1fbbd59d60f7'];

function source(file, expected) {
  const raw = readFileSync(file), digest = sha(raw);
  need(expected === undefined || digest === expected, `source sha256 mismatch: ${file}`);
  return { raw, binding: { path: path.relative(ROOT, file), bytes: raw.length, sha256: digest } };
}

// Shared pure helpers keep synthetic boundary tests outside the trusted CLI path.
export function sections(prompt, at = 'prompt') {
  const start = prompt.indexOf(USER), stop = prompt.indexOf(END, start + USER.length);
  need(start >= 0 && stop >= 0, `${at}: no user message`);
  const lines = prompt.slice(start + USER.length, stop).split('\n');
  const first = lines.findIndex(line => line.startsWith(PREAMBLE));
  need(first >= 0, `${at}: no rules preamble`);
  const area = lines.slice(first + 1).join('\n'), cut = area.indexOf(DIFF);
  need(cut >= 0, `${at}: no surrounding diff after the rules`);
  const found = [];
  let current = null;
  for (const line of area.slice(0, cut).split('\n')) {
    if (line.endsWith('AGENTS.md:') || line.startsWith(README)) found.push(current = { agents: line.endsWith('AGENTS.md:'), lines: [] });
    else current?.lines.push(line);
  }
  return found.filter(section => section.agents).map(section => section.lines.join('\n'));
}

export function score(raw, texts) {
  if (raw === null) return { reason: 'no response' };
  let answer;
  try { answer = JSON.parse(raw); } catch { return { reason: 'response is not JSON' }; }
  if (answer === null || typeof answer !== 'object' || Array.isArray(answer)) return { reason: 'response is not a JSON object' };
  if (typeof answer.analysis !== 'string') return { reason: 'analysis is not a string' };
  if (!answer.analysis.startsWith('Rule: ')) return { reason: 'analysis does not start with "Rule: "' };
  const rest = answer.analysis.slice(6);
  let n = 0;
  while (n < rest.length && texts.some(text => text.includes(rest.slice(0, n + 1)))) n++;
  return { quote: rest.slice(0, n), reason: n >= MIN_QUOTE ? null : `quote ${n} chars < ${MIN_QUOTE}` };
}

export async function frozenCases(split) {
  need(['train', 'heldout'].includes(split), 'invalid split');
  const bindings = [];
  const load = name => {
    const item = source(path.join(ROOT, name), PINS[name]);
    bindings.push(item.binding); return item.raw.toString('utf8');
  };
  const corpus = split === 'train' ? 'training/sft_review_v6_before.jsonl' : 'training/review_holdout_v5.jsonl';
  const text = load(corpus);
  need(text.endsWith('\n'), 'frozen source must end with a newline');
  const rows = text.slice(0, -1).split('\n').map(line => JSON.parse(line));
  let cases;
  if (split === 'train') {
    cases = rows.filter(row => row.kind === 'review').map(row => ({ case_id: row.id,
      prompt: row.messages.slice(0, 2).map(m => `<|im_start|>${m.role}\n${m.content}<|im_end|>\n`).join('') + '<|im_start|>assistant\n' }));
  } else {
    load('bin/jovovich.mjs');
    const identity = load('prompts/identity.txt');
    // Read the exact frozen collector extension, rather than another copy of it.
    const builder = load('training/explanations/build_corpora.py');
    const match = /^SUFFIX = ("(?:[^"\\]|\\.)*")$/m.exec(builder);
    need(match !== null, 'frozen common extension is missing');
    const suffix = JSON.parse(match[1]), end = '<|im_end|>\n<|im_start|>assistant\n';
    cases = [];
    for (const row of rows) {
      const chunks = chunksFor(row.files);
      need(chunks.length === 1, 'heldout requires one review chunk');
      const prompt = await promptFor(chunks[0], row.context, identity, 'chatml');
      need(prompt.endsWith(end), 'production ChatML changed');
      cases.push({ case_id: row.id, prompt: prompt.slice(0, -end.length) + suffix + end });
    }
  }
  need(cases.length === (split === 'train' ? 52 : 24) && new Set(cases.map(c => c.case_id)).size === cases.length,
    'frozen source coverage differs');
  return { cases, bindings, corpus };
}

async function main() {
  const args = parseArgs({ options: { run: { type: 'string' }, split: { type: 'string' },
    reasons: { type: 'string' }, out: { type: 'string' } } }).values;
  need(args.run && args.out && ['train', 'heldout'].includes(args.split),
    'usage: --run DIR --split train|heldout [--reasons FILE] --out REPORT');
  need(args.reasons === undefined || args.split === 'train', '--reasons applies only to --split train');
  const frozen = await frozenCases(args.split), bindings = [...frozen.bindings];
  bindings.push(source(fileURLToPath(import.meta.url)).binding);
  let rules = null;
  if (args.reasons !== undefined) {
    const item = source(path.resolve(args.reasons), PINS['training/explanations/reasons.json']);
    bindings.push(item.binding);
    const rows = JSON.parse(item.raw.toString('utf8')).rows;
    need(JSON.stringify(rows.map(r => r.id)) === JSON.stringify(frozen.cases.map(c => c.case_id)), 'reasons IDs differ from frozen source');
    rules = new Map(rows.map(row => [row.id, row.evidence.rule]));
  }
  const generationPath = path.join(args.run, 'generations.jsonl'), generations = readFileSync(generationPath);
  const text = generations.toString('utf8');
  need(text.endsWith('\n'), 'generations.jsonl must be nonempty and end with a newline');
  const records = text.slice(0, -1).split('\n').map((line, i) => {
    let record;
    try { record = JSON.parse(line); } catch (error) { throw new Error(`generations line ${i}: ${error.message}`); }
    need(typeof record?.case_id === 'string' && (record.raw_response === null || typeof record.raw_response === 'string') &&
      typeof record.metadata?.prompt_sha256 === 'string', `generations line ${i}: malformed record`);
    return record;
  });
  need(records.length === frozen.cases.length, `frozen ${args.split} coverage requires ${frozen.cases.length} rows, got ${records.length}`);
  need(new Set(records.map(r => r.case_id)).size === records.length, 'duplicate generation case_id');
  need(records.every((r, i) => r.case_id === frozen.cases[i].case_id), `generation IDs/order differ from frozen ${args.split} source`);
  const cases = records.map((record, i) => {
    const prompt = readFileSync(path.join(args.run, 'cases', String(i).padStart(3, '0'), 'prompt.txt'));
    const promptSha = sha(prompt), responseSha = record.raw_response === null ? null : sha(record.raw_response);
    need(promptSha === record.metadata.prompt_sha256, `line ${i} ${record.case_id}: prompt sha256 mismatch`);
    need(prompt.equals(Buffer.from(frozen.cases[i].prompt)), `line ${i} ${record.case_id}: prompt differs from frozen source`);
    if (Object.hasOwn(record, 'raw_response_sha256'))
      need(record.raw_response_sha256 === responseSha, `line ${i} ${record.case_id}: raw response sha256 mismatch`);
    if (Object.hasOwn(record, 'corpus_sha256'))
      need((args.split === 'train' ? TRAIN_CORPUS_HASHES : [PINS[frozen.corpus]]).includes(record.corpus_sha256),
        `line ${i} ${record.case_id}: corpus sha256 differs from frozen split`);
    const { quote = null, reason } = score(record.raw_response, sections(prompt.toString('utf8'), `line ${i}`));
    const pass = reason === null;
    let decisive = null, full_rule = null;
    if (rules) {
      const rule = rules.get(record.case_id);
      decisive = pass && rule.includes(quote);
      full_rule = pass && quote.startsWith(rule);
    }
    return { case_id: record.case_id, prompt_sha256: promptSha, raw_response_sha256: responseSha,
      response_hash_checked: Object.hasOwn(record, 'raw_response_sha256'), pass, reason,
      quote_chars: quote === null ? null : quote.length, quote, decisive, full_rule, finish_reason: record.finish_reason ?? null };
  });
  const count = field => cases.filter(c => c[field]).length;
  const totals = { cases: cases.length, pass: count('pass'), decisive: rules ? count('decisive') : null, full_rule: rules ? count('full_rule') : null };
  const report = { schema_version: 2, split: args.split,
    run: { generations_sha256: sha(generations), generations_bytes: generations.length },
    coverage: { source_order_verified: true, expected_cases: frozen.cases.length, unique_cases: cases.length },
    sources: bindings, min_quote: MIN_QUOTE, cases, totals };
  let fd;
  try { fd = openSync(args.out, 'wx'); }
  catch (error) { throw new Error(error.code === 'EEXIST' ? `refusing to overwrite ${args.out}` : error.message); }
  try { writeFileSync(fd, JSON.stringify(report, null, 2) + '\n'); closeSync(fd); }
  catch (error) { try { closeSync(fd); } catch {} unlinkSync(args.out); throw error; }
  const show = value => value === null ? '-' : value;
  console.log(`cases ${totals.cases} pass ${totals.pass} decisive ${show(totals.decisive)} full_rule ${show(totals.full_rule)}`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => { process.stderr.write(`quote manipulation: ${error.message}\n`); process.exitCode = 2; });
}
