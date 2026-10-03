import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { frozenCases, sections, score as quoteScore } from '../training/quote/manipulation.mjs';

const TOOL = 'training/quote/manipulation.mjs';
const REASONS = 'training/explanations/reasons.json';
const PREAMBLE = 'AGENTS.md rules below are ordered root to nearest directory. Where they conflict, the closest scope wins.';
const digest = value => createHash('sha256').update(value).digest('hex');
const reviews = file => readFileSync(file, 'utf8').trimEnd().split('\n').map(line => JSON.parse(line)).filter(row => row.kind === 'review');
const render = messages => messages.slice(0, 2).map(m => `<|im_start|>${m.role}\n${m.content}<|im_end|>\n`).join('') + '<|im_start|>assistant\n';
const gold = rows => rows.map(row => ({ case_id: row.id, prompt: render(row.messages), raw_response: row.messages[2].content }));
const v7 = reviews('training/sft_review_v7_quote.jsonl'), before = reviews('training/sft_review_v6_before.jsonl');
const rules = new Map(JSON.parse(readFileSync(REASONS, 'utf8')).rows.map(row => [row.id, row.evidence.rule]));

function fixture(records) {
  const dir = mkdtempSync(path.join(realpathSync(tmpdir()), 'jovovich-quote-'));
  const lines = records.map((record, i) => {
    const prompt = Buffer.from(record.prompt), at = path.join(dir, 'cases', String(i).padStart(3, '0'));
    mkdirSync(at, { recursive: true }); writeFileSync(path.join(at, 'prompt.txt'), prompt);
    return JSON.stringify({ case_id: record.case_id, raw_response: record.raw_response,
      raw_response_sha256: record.raw_response === null ? null : digest(record.raw_response),
      finish_reason: record.raw_response === null ? 'error' : 'eos',
      metadata: { prompt_sha256: digest(prompt) } }) + '\n';
  });
  writeFileSync(path.join(dir, 'generations.jsonl'), lines.join(''));
  return dir;
}
function score(dir, split, ...extra) {
  const out = path.join(dir, `report-${split}.json`);
  const result = spawnSync('node', [TOOL, '--run', dir, '--split', split, ...extra, '--out', out], { encoding: 'utf8', timeout: 10000 });
  return { ...result, report: existsSync(out) ? JSON.parse(readFileSync(out, 'utf8')) : null };
}

test('v7 gold copies its whole decisive rule in all 52 review rows', t => {
  assert.equal(v7.length, 52);
  const dir = fixture(gold(v7));
  try {
    const r = score(dir, 'train', '--reasons', REASONS);
    assert.equal(r.status, 0, r.stderr); t.diagnostic(`v7 gold: ${r.stdout.trim()}`);
    assert.equal(r.stdout, 'cases 52 pass 52 decisive 52 full_rule 52\n');
    assert.deepEqual(r.report.totals, { cases: 52, pass: 52, decisive: 52, full_rule: 52 });
    assert.equal(r.report.run.generations_sha256, digest(readFileSync(path.join(dir, 'generations.jsonl'))));
    assert.deepEqual(r.report.coverage, { source_order_verified: true, expected_cases: 52, unique_cases: 52 });
    assert.equal(r.report.schema_version, 2);
    for (const source of r.report.sources) {
      const raw = readFileSync(source.path);
      assert.equal(source.sha256, digest(raw)); assert.equal(source.bytes, raw.length);
    }
    assert.ok(r.report.cases.every(c => c.response_hash_checked));
    for (const c of r.report.cases) assert.equal(c.quote, rules.get(c.case_id));
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test('v6_before gold never opens with a copied rule', t => {
  assert.equal(before.length, 52);
  const dir = fixture(gold(before));
  try {
    const r = score(dir, 'train', '--reasons', REASONS);
    assert.equal(r.status, 0, r.stderr); t.diagnostic(`v6_before gold: ${r.stdout.trim()}`);
    assert.deepEqual(r.report.totals, { cases: 52, pass: 0, decisive: 0, full_rule: 0 });
    for (const c of r.report.cases) assert.equal(c.reason, 'analysis does not start with "Rule: "');
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test('preamble, header lines and README never count; the boundary is exactly 40 characters', () => {
  const row = v7[0], rule = rules.get(row.id), prompt = render(row.messages);
  const header = 'analysis/AGENTS.md:\n' + rule;
  const readme = 'Release archives are signed by the maintainers on tagged commits only.';
  assert.ok(prompt.includes(PREAMBLE + '\n') && prompt.includes('\n' + header + '\n'));
  const withReadme = prompt.replace(PREAMBLE + '\n', `${PREAMBLE}\nREADME.md (repository-wide context):\n${readme}\n`);
  const answer = analysis => JSON.stringify({ analysis, findings: [] });
  const records = {
    preamble: [prompt, answer('Rule: ' + PREAMBLE)],
    header: [prompt, answer('Rule: ' + header)],
    readme: [withReadme, answer('Rule: ' + readme)],
    'quote 39': [prompt, answer('Rule: ' + rule.slice(0, 39) + '\u0000x')],
    'quote 40': [prompt, answer('Rule: ' + rule.slice(0, 40) + ' zzz')],
    'no space': [prompt, answer('Rule:' + rule)],
    unparsable: [prompt, '{not json'],
    null: [prompt, null],
  };
  const result = Object.fromEntries(Object.entries(records).map(([name, [input, response]]) =>
    [name, quoteScore(response, sections(input))]));
  assert.deepEqual(Object.fromEntries(Object.entries(result).map(([name, r]) => [name, r.reason === null])),
    { preamble: false, header: false, readme: false, 'quote 39': false, 'quote 40': true, 'no space': false, unparsable: false, null: false });
  assert.equal(result['quote 39'].quote.length, 39); assert.equal(result['quote 40'].quote.length, 40);
  assert.equal(rule.includes(result['quote 40'].quote), true);
  assert.equal(result['quote 40'].quote.startsWith(rule), false);
});

test('a prompt changed after its hash was recorded stops the run with exit 2', () => {
  const dir = fixture(gold(v7));
  try {
    const file = path.join(dir, 'cases', '000', 'prompt.txt'), bytes = readFileSync(file, 'utf8');
    assert.ok(bytes.includes('Lua')); writeFileSync(file, bytes.replace('Lua', 'Lub'));
    const r = score(dir, 'train', '--reasons', REASONS);
    assert.equal(r.status, 2); assert.match(r.stderr, /prompt sha256 mismatch/); assert.equal(r.report, null);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

function rewriteRecords(dir, change) {
  const file = path.join(dir, 'generations.jsonl');
  const records = readFileSync(file, 'utf8').trimEnd().split('\n').map(line => JSON.parse(line));
  writeFileSync(file, change(records).map(record => JSON.stringify(record) + '\n').join(''));
}

for (const [name, transform, error] of [
  ['missing row', rows => rows.slice(1), /coverage requires 52 rows/],
  ['duplicate ID', rows => rows.map((r, i) => i === 1 ? { ...r, case_id: rows[0].case_id } : r), /duplicate generation case_id/],
  ['reordered IDs', rows => [rows[1], rows[0], ...rows.slice(2)], /IDs\/order differ/],
  ['unknown ID', rows => rows.map((r, i) => i === 0 ? { ...r, case_id: 'unknown' } : r), /IDs\/order differ/],
  ['changed response', rows => rows.map((r, i) => i === 0 ? { ...r, raw_response: '{}' } : r), /raw response sha256 mismatch/],
  ['wrong corpus', rows => rows.map(r => ({ ...r, corpus_sha256: '0'.repeat(64) })), /corpus sha256 differs/],
]) {
  test(`${name} cannot produce an adoption-count report`, () => {
    const dir = fixture(gold(v7));
    try {
      rewriteRecords(dir, transform);
      const r = score(dir, 'train');
      assert.equal(r.status, 2); assert.match(r.stderr, error); assert.equal(r.report, null);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });
}

test('recomputing the self-hash cannot bind a changed prompt to the frozen case', () => {
  const dir = fixture(gold(v7));
  try {
    const file = path.join(dir, 'cases', '000', 'prompt.txt');
    const prompt = readFileSync(file, 'utf8').replace('Lua', 'Lub');
    writeFileSync(file, prompt);
    rewriteRecords(dir, rows => rows.map((r, i) => i === 0 ? { ...r, metadata: { prompt_sha256: digest(prompt) } } : r));
    const r = score(dir, 'train');
    assert.equal(r.status, 2); assert.match(r.stderr, /prompt differs from frozen source/); assert.equal(r.report, null);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test('train rows and duplicate train rows cannot masquerade as the 24 heldout cases', () => {
  for (const records of [gold(v7.slice(0, 1)), gold(v7.slice(0, 24)), Array(24).fill(gold(v7)[0])]) {
    const dir = fixture(records);
    try {
      const r = score(dir, 'heldout');
      assert.equal(r.status, 2); assert.match(r.stderr, /coverage requires 24|duplicate generation case_id|IDs\/order differ/);
      assert.equal(r.report, null);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  }
});

test('complete heldout source stays at 24 cases when a response is missing', async () => {
  const frozen = await frozenCases('heldout');
  const records = frozen.cases.map((c, i) => ({ ...c,
    raw_response: i === 0 ? null : JSON.stringify({ analysis: 'Rule: ' + sections(c.prompt)[0].trim(), findings: [] }) }));
  const dir = fixture(records);
  try {
    const r = score(dir, 'heldout');
    assert.equal(r.status, 0, r.stderr);
    assert.deepEqual(r.report.totals, { cases: 24, pass: 23, decisive: null, full_rule: null });
    assert.equal(r.report.cases[0].reason, 'no response');
    assert.equal(r.report.cases[0].raw_response_sha256, null);
    assert.equal(r.report.coverage.expected_cases, 24);
    assert.deepEqual(r.report.sources.map(s => s.path), [
      'training/review_holdout_v5.jsonl', 'bin/jovovich.mjs', 'prompts/identity.txt',
      'training/explanations/build_corpora.py', TOOL,
    ]);
    for (const source of r.report.sources) assert.equal(source.sha256, digest(readFileSync(source.path)));
    // Output creation remains exclusive.
    const second = score(dir, 'heldout');
    assert.equal(second.status, 2); assert.match(second.stderr, /refusing to overwrite/);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test('train decisive-scope annotation requires the frozen reasons bytes', () => {
  const dir = fixture(gold(v7));
  try {
    const reasons = path.join(dir, 'reasons.json');
    writeFileSync(reasons, readFileSync(REASONS, 'utf8').replace('Lua', 'Lub'));
    const r = score(dir, 'train', '--reasons', reasons);
    assert.equal(r.status, 2); assert.match(r.stderr, /source sha256 mismatch/); assert.equal(r.report, null);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
