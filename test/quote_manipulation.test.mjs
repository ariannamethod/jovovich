import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

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
    return JSON.stringify({ case_id: record.case_id, raw_response: record.raw_response, finish_reason: 'eos',
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
  const names = Object.keys(records);
  const dir = fixture(names.map(name => ({ case_id: row.id, prompt: records[name][0], raw_response: records[name][1] })));
  try {
    const r = score(dir, 'train', '--reasons', REASONS);
    assert.equal(r.status, 0, r.stderr);
    const result = Object.fromEntries(names.map((name, i) => [name, r.report.cases[i]]));
    assert.deepEqual(Object.fromEntries(names.map(name => [name, result[name].pass])),
      { preamble: false, header: false, readme: false, 'quote 39': false, 'quote 40': true, 'no space': false, unparsable: false, null: false });
    assert.equal(result['quote 39'].quote_chars, 39); assert.equal(result['quote 40'].quote_chars, 40);
    assert.equal(result['quote 40'].decisive, true); assert.equal(result['quote 40'].full_rule, false);
    assert.equal(r.report.min_quote, 40);
    const heldout = score(dir, 'heldout');
    assert.equal(heldout.status, 0, heldout.stderr);
    assert.equal(heldout.stdout, 'cases 8 pass 1 decisive - full_rule -\n');
    assert.equal(heldout.report.cases[4].decisive, null);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test('a prompt changed after its hash was recorded stops the run with exit 2', () => {
  const dir = fixture(gold(v7.slice(0, 1)));
  try {
    const file = path.join(dir, 'cases', '000', 'prompt.txt'), bytes = readFileSync(file, 'utf8');
    assert.ok(bytes.includes('Lua')); writeFileSync(file, bytes.replace('Lua', 'Lub'));
    const r = score(dir, 'train', '--reasons', REASONS);
    assert.equal(r.status, 2); assert.match(r.stderr, /prompt sha256 mismatch/); assert.equal(r.report, null);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
