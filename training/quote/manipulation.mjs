#!/usr/bin/env node
// Manipulation check: the analysis opens with "Rule: " and a verbatim span of the prompt's own AGENTS.md sections.
import { createHash } from 'node:crypto';
import { closeSync, openSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { parseArgs } from 'node:util';

const MIN_QUOTE = 40;
const PREAMBLE = 'AGENTS.md rules below are ordered root to nearest directory.';
const README = 'README.md (repository-wide context):';
const DIFF = '\n\nSurrounding diff:';
const USER = '<|im_start|>user\n', END = '<|im_end|>';
const sha = value => createHash('sha256').update(value).digest('hex');
const fail = message => { process.stderr.write(`quote manipulation: ${message}\n`); process.exit(2); };
const read = file => { try { return readFileSync(file); } catch (error) { fail(error.message); } };

let args;
try {
  args = parseArgs({ options: { run: { type: 'string' }, split: { type: 'string' },
    reasons: { type: 'string' }, out: { type: 'string' } } }).values;
} catch (error) { fail(error.message); }
if (!args.run || !args.out || !['train', 'heldout'].includes(args.split))
  fail('usage: --run DIR --split train|heldout [--reasons FILE] --out REPORT');
if (args.reasons !== undefined && args.split !== 'train') fail('--reasons applies only to --split train');

let rules = null;
if (args.reasons !== undefined) {
  rules = new Map();
  try {
    for (const row of JSON.parse(read(args.reasons).toString('utf8')).rows) {
      if (rules.has(row.id) || typeof row.evidence?.rule !== 'string') throw new Error(`bad or duplicate row ${row.id}`);
      rules.set(row.id, row.evidence.rule);
    }
  } catch (error) { fail(`reasons: ${error.message}`); }
}

function sections(prompt, at) {
  const start = prompt.indexOf(USER), stop = prompt.indexOf(END, start + USER.length);
  if (start < 0 || stop < 0) fail(`${at}: no user message`);
  const lines = prompt.slice(start + USER.length, stop).split('\n');
  const first = lines.findIndex(line => line.startsWith(PREAMBLE));
  if (first < 0) fail(`${at}: no rules preamble`);
  const area = lines.slice(first + 1).join('\n'), cut = area.indexOf(DIFF);
  if (cut < 0) fail(`${at}: no surrounding diff after the rules`);
  const found = [];
  let current = null;
  for (const line of area.slice(0, cut).split('\n')) {
    if (line.endsWith('AGENTS.md:') || line.startsWith(README)) found.push(current = { agents: line.endsWith('AGENTS.md:'), lines: [] });
    else current?.lines.push(line);
  }
  return found.filter(section => section.agents).map(section => section.lines.join('\n'));
}

function score(raw, texts) {
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

const generations = read(path.join(args.run, 'generations.jsonl')), text = generations.toString('utf8');
if (!text.endsWith('\n')) fail('generations.jsonl must be nonempty and end with a newline');
const cases = text.slice(0, -1).split('\n').map((line, i) => {
  let record;
  try { record = JSON.parse(line); } catch (error) { fail(`generations line ${i}: ${error.message}`); }
  if (typeof record?.case_id !== 'string' || !(record.raw_response === null || typeof record.raw_response === 'string') ||
      typeof record.metadata?.prompt_sha256 !== 'string') fail(`generations line ${i}: malformed record`);
  const prompt = read(path.join(args.run, 'cases', String(i).padStart(3, '0'), 'prompt.txt'));
  if (sha(prompt) !== record.metadata.prompt_sha256) fail(`line ${i} ${record.case_id}: prompt sha256 mismatch`);
  const { quote = null, reason } = score(record.raw_response, sections(prompt.toString('utf8'), `line ${i}`));
  const pass = reason === null;
  let decisive = null, full_rule = null;
  if (rules) {
    const rule = rules.get(record.case_id);
    if (rule === undefined) fail(`line ${i}: no reasons row for ${record.case_id}`);
    decisive = pass && rule.includes(quote);
    full_rule = pass && quote.startsWith(rule);
  }
  return { case_id: record.case_id, pass, reason, quote_chars: quote === null ? null : quote.length, quote,
    decisive, full_rule, finish_reason: record.finish_reason ?? null };
});

const count = field => cases.filter(c => c[field]).length;
const totals = { cases: cases.length, pass: count('pass'),
  decisive: rules ? count('decisive') : null, full_rule: rules ? count('full_rule') : null };
const report = { schema_version: 1, split: args.split, run: { generations_sha256: sha(generations) },
  min_quote: MIN_QUOTE, cases, totals };
let fd;
try { fd = openSync(args.out, 'wx'); } catch (error) { fail(error.code === 'EEXIST' ? `refusing to overwrite ${args.out}` : error.message); }
try { writeFileSync(fd, JSON.stringify(report, null, 2) + '\n'); closeSync(fd); }
catch (error) { try { closeSync(fd); } catch {} unlinkSync(args.out); fail(error.message); }
const show = value => value === null ? '-' : value;
console.log(`cases ${totals.cases} pass ${totals.pass} decisive ${show(totals.decisive)} full_rule ${show(totals.full_rule)}`);
