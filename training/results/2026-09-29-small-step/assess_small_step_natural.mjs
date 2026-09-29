#!/usr/bin/env node
// Records the manually inspected empty-review outcome, with source and parser checks.
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const root = process.cwd();
const { parseReview, chunksFor } = await import(pathToFileURL(path.join(root, 'bin/jovovich.mjs')));
const sha = data => createHash('sha256').update(data).digest('hex');
const check = (ok, message) => { if (!ok) throw new Error(message); };
const sources = {};
function read(file, count, key) {
  const data = readFileSync(file, 'utf8');
  check(data.endsWith('\n'), `${file}: incomplete final record`);
  const rows = data.trimEnd().split('\n').map(JSON.parse);
  check(rows.length === count && new Set(rows.map(r => r[key])).size === count, `${file}: count or IDs`);
  sources[file] = { sha256: sha(data), records: count };
  return rows;
}
const corpus = read('training/sft_review_v2.jsonl', 64, 'id').filter(r => r.kind === 'review');
const diagnostics = read('training/review_holdout_v2.jsonl', 12, 'id');
const model = JSON.parse(readFileSync('models/decision-small-step-selected-model.json', 'utf8'));
const groups = [
  { name: 'training', count: 40, key: 'name', text: 'response', gold: corpus, file: 'train-generation.jsonl' },
  { name: 'diagnostics', count: 12, key: 'case_id', text: 'raw_response', gold: diagnostics, file: 'review.jsonl' }
];
const report = {
  method: {
    scope: 'Complete naturally generated reviews on the fixed 40 training prompts and 12 existing diagnostic prompts.',
    causal_concern: 'A correct concern identifies the applicable rule conflict or concrete failure mechanism and cites an available causally appropriate changed line.',
    full_review_pass: 'The complete response passes production parsing and gives the correct grounded review, including clean verdicts and any additional findings.',
    parse_errors: 'Invalid responses are counted separately from false-positive findings on clean cases.',
    provenance: 'Every response was read; all 52 contain the same fenced empty array. Production parsing is recomputed against the actual changed-line table. Pair accuracy requires both full reviews to pass.'
  },
  sources,
  counts: {},
  cases: []
};
for (const group of groups) {
  const file = `models/decision-small-step-${group.file}`;
  const rows = read(file, group.count, group.key);
  const old = read(`training/results/2026-09-29-decision-only/${group.file}`, group.count, group.key);
  const oldByID = new Map(old.map(r => [r[group.key], r]));
  const goldByID = new Map(group.gold.map(r => [r.id, r]));
  const cases = rows.map((r, i) => {
    const id = r[group.key], gold = goldByID.get(id);
    check(gold, `${id}: missing gold`);
    check(r.model_sha256 === model.sha256, `${id}: selected model differs`);
    check(r[group.text] === '```json\n[]\n```', `${id}: response needs fresh semantic assessment`);
    const prior = oldByID.get(id);
    check(prior && prior[group.text] === r[group.text], `${id}: baseline response differs`);
    check(r.prompt_sha256 === prior.prompt_sha256, `${id}: prompt differs from baseline`);
    let chunk, concern;
    if (group.name === 'training') {
      check(r.returncode === 0 && r.expected_response === gold.messages[2].content, `${id}: execution or target`);
      check(r.prompt === gold.messages[1].content && r.system === gold.messages[0].content, `${id}: training prompt`);
      const shown = [...r.prompt.matchAll(/^\[(\d+)\] (ADDED|REMOVED) (.+?):(\d+): (.*)$/gm)];
      check(shown.length && shown.every((m, j) => +m[1] === j + 1), `${id}: citation table`);
      chunk = { path: shown[0][3], lines: shown.map(m => ({ side: m[2] === 'ADDED' ? 'RIGHT' : 'LEFT', line: +m[4], quote: m[5] })) };
      concern = JSON.parse(gold.messages[2].content).findings.length > 0;
    } else {
      check(r.error === null && r.expected_concern === gold.expected_concern, `${id}: execution or target`);
      [chunk] = chunksFor(gold.files);
      concern = gold.expected_concern;
    }
    const parsed = parseReview(r[group.text], chunk);
    check(parsed.findings.length === 0, `${id}: parser result`);
    const result = {
      id, cohort: group.name, pair: gold.pair, source: file, record_line: i + 1,
      expected_concern: concern, production_usable: true, parse_error: null,
      finding_count: 0, grounded_causal_concern: concern ? false : null,
      full_review_pass: !concern, baseline_response_identical: true,
      assessment: concern ? 'Empty findings list omits the supplied concern.' : 'Empty findings list correctly accepts the clean change.'
    };
    if (group.name === 'training') result.stop_reason = r.stop_reason;
    return result;
  });
  const pairs = new Map();
  for (const c of cases) { if (!pairs.has(c.pair)) pairs.set(c.pair, []); pairs.get(c.pair).push(c); }
  check([...pairs.values()].every(p => p.length === 2 && p.filter(r => r.expected_concern).length === 1), 'Pair balance');
  report.counts[group.name] = {
    cases: cases.length, concerns: cases.filter(c => c.expected_concern).length,
    clean: cases.filter(c => !c.expected_concern).length, production_usable: cases.length,
    invalid_parse: 0, grounded_concerns: 0, missed_concerns: cases.filter(c => c.expected_concern).length,
    correct_clean: cases.filter(c => !c.expected_concern).length, clean_false_positives: 0,
    full_review_pass: cases.filter(c => c.full_review_pass).length,
    pairs: pairs.size, full_pairs_pass: [...pairs.values()].filter(p => p.every(c => c.full_review_pass)).length,
    baseline_identical: cases.length
  };
  if (group.name === 'training') report.counts[group.name].eos = cases.filter(c => c.stop_reason === 'eos').length;
  report.cases.push(...cases);
}
check(report.cases.length === 52, 'Combined cohort size');
report.sources['bin/jovovich.mjs'] = { sha256: sha(readFileSync('bin/jovovich.mjs')) };
report.model_sha256 = model.sha256;
report.finding = 'All 52 natural responses match the prior checkpoint: fenced empty arrays. Training concerns 0/20, clean 20/20, complete pairs 0/20; diagnostics concerns 0/6, clean 6/6, complete pairs 0/6. All 52 pass production parsing.';
const output = process.argv[2] || '../reference/small-step-natural-assessment.json';
writeFileSync(output, JSON.stringify(report, null, 2) + '\n', { flag: 'wx' });
process.stdout.write(JSON.stringify({ output, counts: report.counts }) + '\n');
