#!/usr/bin/env node
// Prefix each review analysis with the rule it applies; --identity rebuilds the base bytes.
import { createHash } from 'node:crypto';
import { closeSync, fsyncSync, openSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import { parseArgs } from 'node:util';

const BASE_SHA256 = 'a2f22e789b176b1f23ed1262b3e94449819a1484ed31ddb87c3dbedbb8574250';
const REASONS_SHA256 = 'c2269304dea5dbe65a42308116a51b383d9a535ec47fca7cedd122136c670e45';
const DIFF = '\n\nSurrounding diff:';
const sha = value => createHash('sha256').update(value).digest('hex');
const fail = (code, message) => { process.stderr.write(`quote corpus: ${message}\n`); process.exit(code); };
const need = (ok, message) => { if (!ok) throw new Error(message); };
const answerJson = answer => '{' + Object.entries(answer).map(([k, v]) => JSON.stringify(k) + ':' + JSON.stringify(v)).join('\n,') + '\n}';
const read = file => { try { return readFileSync(file); } catch (error) { fail(2, error.message); } };
const lines = bytes => {
  const parts = [];
  for (let at = 0; at < bytes.length;) { const end = bytes.indexOf(10, at) + 1 || bytes.length; parts.push(bytes.subarray(at, end)); at = end; }
  return parts;
};

let args;
try {
  args = parseArgs({ options: {
    base: { type: 'string', default: 'training/sft_review_v6_before.jsonl' },
    reasons: { type: 'string', default: 'training/explanations/reasons.json' },
    out: { type: 'string' }, check: { type: 'string' }, identity: { type: 'boolean', default: false } } }).values;
} catch (error) { fail(2, error.message); }
if ((args.out === undefined) === (args.check === undefined)) fail(2, 'exactly one of --out PATH or --check PATH');

const baseBytes = read(args.base), reasonBytes = read(args.reasons);
if (sha(baseBytes) !== BASE_SHA256) fail(2, `base sha256 mismatch: ${args.base}`);
if (sha(reasonBytes) !== REASONS_SHA256) fail(2, `reasons sha256 mismatch: ${args.reasons}`);
let reasons;
try { reasons = JSON.parse(reasonBytes.toString('utf8')).rows; need(Array.isArray(reasons), 'rows must be a list'); }
catch (error) { fail(1, `reasons: ${error.message}`); }
if (baseBytes.at(-1) !== 10) fail(1, 'base must end with a newline');

const raw = lines(baseBytes), built = [], ids = [];
let review = 0, transformed = 0;
for (const [i, line] of raw.entries()) {
  let id = `line ${i}`;
  try {
    const text = line.toString('utf8'), row = JSON.parse(text);
    ids.push(id = row.id);
    if (row.kind !== 'review') { built.push(line); continue; }
    need(JSON.stringify(row) + '\n' === text, 'row is not compact JSON in insertion order');
    need(JSON.stringify(row.messages.map(m => m.role)) === '["system","user","assistant"]', 'expected system/user/assistant');
    const user = row.messages[1].content, content = row.messages[2].content, answer = JSON.parse(content);
    need(JSON.stringify(Object.keys(answer)) === '["analysis","findings"]', 'answer keys must be exactly analysis, findings');
    need(answerJson(answer) === content, 'answer serialization differs from base');
    const reason = reasons[review++];
    need(reason?.id === id && reason.pair === row.pair, 'reasons row id/pair mismatch');
    need(reason.analysis === answer.analysis, 'reasons analysis differs from answer');
    const rule = reason.evidence?.rule;
    need(typeof rule === 'string' && rule.length > 0 && typeof user === 'string', 'rule and user content must be strings');
    const at = user.indexOf(rule), cut = user.indexOf(DIFF);
    need(at >= 0 && user.indexOf(rule, at + 1) < 0, 'rule must occur exactly once in user content');
    need(cut >= 0 && at + rule.length <= cut, 'rule must lie inside the rules block');
    if (!args.identity) { answer.analysis = 'Rule: ' + rule + ' ' + answer.analysis; transformed++; }
    row.messages[2].content = answerJson(answer);
    built.push(Buffer.from(JSON.stringify(row) + '\n'));
  } catch (error) { fail(1, `${id}: ${error.message}`); }
}
if (raw.length !== 76 || review !== 52 || reasons.length !== 52)
  fail(1, `expected 76 rows, 52 review, 52 reasons; got ${raw.length}, ${review}, ${reasons.length}`);

const bytes = Buffer.concat(built);
if (args.check !== undefined) {
  const have = lines(read(args.check)), i = built.findIndex((line, j) => !have[j]?.equals(line));
  if (i >= 0 || have.length !== built.length) {
    const at = i < 0 ? built.length : i;
    fail(1, `differs at line index ${at} id ${ids[at] ?? '(past end)'}`);
  }
} else {
  let fd;
  try { fd = openSync(args.out, 'wx'); } catch (error) { fail(2, error.code === 'EEXIST' ? `refusing to overwrite ${args.out}` : error.message); }
  try { writeFileSync(fd, bytes); fsyncSync(fd); closeSync(fd); }
  catch (error) { try { closeSync(fd); } catch {} unlinkSync(args.out); fail(2, error.message); }
}
console.log(`rows ${raw.length} review ${review} transformed ${transformed} sha256 ${sha(bytes)}`);
