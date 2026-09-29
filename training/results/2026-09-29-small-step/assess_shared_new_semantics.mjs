#!/usr/bin/env node
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

const { parseReview } = await import(pathToFileURL(path.resolve('bin/jovovich.mjs')));
const sha = data => createHash('sha256').update(data).digest('hex');
const check = (ok, message) => { if (!ok) throw new Error(message); };
const sources = {};
function load(file, count, key) {
  const data = readFileSync(file, 'utf8');
  check(data.endsWith('\n'), `${file}: incomplete final record`);
  const rows = data.trimEnd().split('\n').map(JSON.parse);
  check(rows.length === count && new Set(rows.map(r => r[key])).size === count, `${file}: expected ${count} unique records`);
  sources[file] = { sha256: sha(data), records: count };
  return rows;
}
const input = 'models/shared-prefix-new.jsonl';
const rows = load(input, 40, 'name');
const corpus = load('training/sft_review_v2.jsonl', 64, 'id').filter(r => r.kind === 'review');
const corpusByID = new Map(corpus.map(r => [r.id, r]));
const judgmentsFile = path.join(path.dirname(fileURLToPath(import.meta.url)), 'shared-new-judgments.json');
const judgmentsText = readFileSync(judgmentsFile, 'utf8');
const judgments = JSON.parse(judgmentsText);
sources[judgmentsFile] = { sha256: sha(judgmentsText) };
sources['bin/jovovich.mjs'] = { sha256: sha(readFileSync('bin/jovovich.mjs')) };
const model = JSON.parse(readFileSync('models/decision-small-step-selected-model.json', 'utf8'));
const used = new Set();
const cases = rows.map((r, i) => {
  const gold = corpusByID.get(r.name);
  check(gold && r.expected_response === gold.messages[2].content && r.pair === gold.pair, `${r.name}: corpus mismatch`);
  check(r.model_sha256 === model.sha256 && r.returncode === 0 && !r.execution_error, `${r.name}: model or execution`);
  check(r.supplied_prefix === '{"findings' && r.native_boundary_verified, `${r.name}: prefix/boundary`);
  const expectedConcern = JSON.parse(gold.messages[2].content).findings.length > 0;
  check(r.expected_concern === expectedConcern, `${r.name}: expected branch`);
  let syntax = false, rawFindings = null, parsed = null, parseError = null;
  try { const raw = JSON.parse(r.assembled_response); syntax = true; rawFindings = raw.findings; } catch {}
  try { parsed = parseReview(r.assembled_response, r.chunk); } catch (e) { parseError = e.message; }
  const nonempty = Array.isArray(rawFindings) && rawFindings.length > 0;
  let genuine = false, allGrounded = false, assessment;
  if (parsed?.findings.length === 0) {
    assessment = expectedConcern ? 'Empty findings list omits the supplied concern.' : 'Empty findings list correctly accepts the clean change.';
    allGrounded = true;
  } else {
    const j = judgments[r.name];
    check(j && j.response_sha256 === sha(r.assembled_response), `${r.name}: missing manual judgment for exact response`);
    check(typeof j.genuine_issue_detected === 'boolean' && typeof j.all_findings_grounded === 'boolean', `${r.name}: incomplete judgment`);
    used.add(r.name);
    genuine = j.genuine_issue_detected;
    allGrounded = j.all_findings_grounded;
    assessment = j.assessment;
  }
  const usable = parsed !== null;
  const full = usable && (expectedConcern ? genuine && allGrounded : parsed.findings.length === 0);
  return {
    id: r.name, pair: r.pair, source: input, record_line: i + 1,
    expected_concern: expectedConcern, json_syntax_valid: syntax,
    reported_findings_count: Array.isArray(rawFindings) ? rawFindings.length : null,
    production_usable: usable, parse_error: parseError,
    returned_line_ids: usable ? parsed.findings.map(f => r.chunk.lines.findIndex(l => l.line === f.line && l.side === f.side && l.quote === f.quote) + 1) : null,
    genuine_issue_detected: genuine, all_findings_grounded: allGrounded,
    full_review_pass: full, clean_nonempty_response: !expectedConcern && nonempty,
    production_clean_false_positive: !expectedConcern && usable && parsed.findings.length > 0,
    invalid_clean_response: !expectedConcern && !usable,
    stop_reason: r.stop_reason, assessment
  };
});
check(Object.keys(judgments).every(id => used.has(id)), 'Unused manual judgments');
const pairs = new Map();
for (const c of cases) { if (!pairs.has(c.pair)) pairs.set(c.pair, []); pairs.get(c.pair).push(c); }
check(pairs.size === 20 && [...pairs.values()].every(p => p.length === 2 && p.filter(c => c.expected_concern).length === 1), 'Pair membership');
const count = predicate => cases.filter(predicate).length;
const report = {
  sources, model_sha256: model.sha256,
  method: {
    cohort: 'Forty training prompts continued after the shared three-token prefix {"findings.',
    genuine_issue_detected: 'At least one finding explains the actual expected conflict or failure mechanism and cites an available causally appropriate changed line. Extra findings are assessed separately.',
    all_findings_grounded: 'Every reported finding has a supported causal explanation and an available causally appropriate changed-line citation; empty lists satisfy this condition.',
    full_review_pass: 'Production-usable review with all findings grounded and the expected issue detected, or an empty findings list for a clean case.',
    clean_counts: 'Production false positives, raw nonempty responses, and invalid clean responses are counted separately.',
    provenance: 'Nonempty or malformed responses receive a manual judgment bound to the exact response hash. Production parsing is recomputed against each supplied changed-line table.'
  },
  counts: {
    cases: cases.length, concerns: count(c => c.expected_concern), clean: count(c => !c.expected_concern),
    json_syntax_valid: count(c => c.json_syntax_valid), production_usable: count(c => c.production_usable),
    invalid_parse: count(c => !c.production_usable), nonempty_responses: count(c => c.reported_findings_count > 0),
    genuine_concerns_detected: count(c => c.expected_concern && c.genuine_issue_detected),
    full_concern_reviews_pass: count(c => c.expected_concern && c.full_review_pass),
    correct_clean: count(c => !c.expected_concern && c.full_review_pass),
    clean_nonempty_responses: count(c => c.clean_nonempty_response),
    production_clean_false_positives: count(c => c.production_clean_false_positive),
    invalid_clean_responses: count(c => c.invalid_clean_response),
    full_reviews_pass: count(c => c.full_review_pass), pairs: pairs.size,
    full_pairs_pass: [...pairs.values()].filter(p => p.every(c => c.full_review_pass)).length,
    eos: count(c => c.stop_reason === 'eos')
  }, cases
};
const output = process.argv[2] || 'models/shared-new-semantic-assessment.json';
writeFileSync(output, JSON.stringify(report, null, 2) + '\n', { flag: 'wx' });
process.stdout.write(JSON.stringify({ output, counts: report.counts }) + '\n');
