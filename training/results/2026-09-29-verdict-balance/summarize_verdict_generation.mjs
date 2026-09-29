#!/usr/bin/env node
// Read-only model-result audit. Writes a summary only once both new files are complete.
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(process.env.JOVOVICH_AUDIT_ROOT || process.cwd());
const out = path.resolve(process.env.JOVOVICH_AUDIT_OUTPUT || 'models/verdict-generation-summary.json');
const { parseReview, parsePatch, chunksFor, promptFor } = await import(pathToFileURL(path.join(root, 'bin/jovovich.mjs')));
const hash = value => createHash('sha256').update(value).digest('hex');
const fileHash = file => hash(readFileSync(path.join(root, file)));
const requireThat = (condition, message) => { if (!condition) throw new Error(message); };
const readRows = file => {
  const text = readFileSync(path.join(root, file), 'utf8');
  requireThat(text.endsWith('\n'), `${file}: last record has not finished`);
  return text.trimEnd().split('\n').map((line, i) => {
    try { return JSON.parse(line); } catch { throw new Error(`${file}:${i + 1}: invalid record JSON`); }
  });
};
const sftPath = 'training/sft_review_v2.jsonl';
const diagnosticPath = 'training/review_holdout_v2.jsonl';
const sft = readRows(sftPath), diagnostics = readRows(diagnosticPath);
requireThat(sft.length === 64 && diagnostics.length === 12, 'Unexpected frozen corpus size');
const identity = readFileSync(path.join(root, 'prompts/identity.txt'), 'utf8');
const cleanForHost = text => text.trim().replace(/(?:<\|im_end\|>|<\|endoftext\|>)+\s*$/, '').trim().replace(/^```(?:json)?\s*/, '').replace(/\s*```$/, '');
const maybeJSON = text => { try { return { valid: true, value: JSON.parse(text) }; } catch (e) { return { valid: false, error: e.message }; } };
const sameSet = (a, b) => [...new Set(a)].sort((a, b) => a - b).join(',') === [...new Set(b)].sort((a, b) => a - b).join(',');

function trainingChunk(source) {
  const prompt = source.messages[1].content;
  const matched = /Repository rules for (.+):\n/.exec(prompt);
  requireThat(matched, `Missing review path: ${source.id}`);
  const pathName = matched[1];
  const body = prompt.split('\n\nChanged lines to review:\n')[1]?.split('\n\nReview the changed lines')[0];
  requireThat(body, `Missing changed-line block: ${source.id}`);
  const lines = body.split('\n').map((line, index) => {
    const m = /^\[(\d+)\] (ADDED|REMOVED) (.+?):(\d+): (.*)$/.exec(line);
    requireThat(m && Number(m[1]) === index + 1 && m[3] === pathName, `Invalid changed-line record: ${source.id}`);
    return { side: m[2] === 'ADDED' ? 'RIGHT' : 'LEFT', line: Number(m[4]), quote: m[5] };
  });
  const diff = prompt.split('\n\nSurrounding diff:\n')[1]?.split('\n\nChanged lines to review:\n')[0];
  requireThat(diff && JSON.stringify(parsePatch(diff)) === JSON.stringify(lines), `Diff/citation mismatch: ${source.id}`);
  return { path: pathName, lines, surrounding_diff: diff };
}

function analyzeReview(raw, chunk, expected, process) {
  const strict = typeof raw === 'string' ? maybeJSON(raw.trim()) : { valid: false, error: 'No response captured' };
  const normalized = typeof raw === 'string' ? maybeJSON(cleanForHost(raw)) : strict;
  const obj = normalized.valid ? (Array.isArray(normalized.value) ? { findings: normalized.value } : normalized.value) : null;
  const array = obj && Array.isArray(obj.findings) ? obj.findings : null;
  let parsed = null, parseError = null;
  try { requireThat(typeof raw === 'string', 'No response captured'); parsed = parseReview(raw, chunk).findings; }
  catch (e) { parseError = e.message; }
  const parseOK = parsed !== null;
  const usable = parseOK && process.failure !== true && !process.recorded_host_failure;
  const ids = parseOK ? array.map(f => Number(f.line_id)) : null;
  const state = usable ? (parsed.length ? 'nonempty' : 'empty') : 'unusable';
  const expectedIDs = expected.line_ids;
  const presenceMatch = usable && (parsed.length > 0) === expected.concern;
  return {
    expected_concern: expected.concern,
    expected_line_ids: expectedIDs,
    expected_reason_reference: expected.reason,
    strict_json_syntax: strict.valid,
    host_normalized_json_syntax: normalized.valid,
    normalized_json_top_level: !normalized.valid ? null : Array.isArray(normalized.value) ? 'array' : normalized.value === null ? 'null' : typeof normalized.value,
    normalization_changed_text: typeof raw === 'string' ? cleanForHost(raw) !== raw.trim() : null,
    json_findings_state: array ? (array.length ? 'nonempty' : 'empty') : null,
    runtime_parse_ok: parseOK,
    runtime_parse_error: parseError,
    usable_host_review: usable,
    runtime_findings_state: state,
    expected_presence_match: presenceMatch,
    raw_returned_line_ids: array?.map(f => f?.line_id ?? null) ?? null,
    returned_line_ids: ids,
    has_any_expected_line: expected.concern && parseOK ? ids.some(id => expectedIDs.includes(id)) : null,
    contains_all_expected_lines: expected.concern && parseOK ? expectedIDs.every(id => ids.includes(id)) : null,
    exact_expected_line_set: expected.concern && parseOK ? sameSet(ids, expectedIDs) : null,
    alternative_line_ids: expected.concern && parseOK ? ids.filter(id => !expectedIDs.includes(id)) : null,
    parsed_findings: parsed,
    changed_lines: chunk.lines.map((line, i) => ({ line_id: i + 1, path: chunk.path, ...line })),
    semantic_assessment: null,
    manual_assessment_required: usable && parsed.length > 0,
    line_comparison_note: 'Expected-line membership is a reference comparison only. An alternative changed line may support the same valid concern; matching the expected line does not validate the reason.'
  };
}

function aggregate(rows) {
  const review = rows.filter(r => r.review);
  const pairs = new Map();
  for (const row of review) { const p = pairs.get(row.pair) || []; p.push(row); pairs.set(row.pair, p); }
  const pairRows = [...pairs].map(([pair, members]) => {
    requireThat(members.length === 2 && members.filter(r => r.review.expected_concern).length === 1, `Invalid output pair: ${pair}`);
    return { pair, case_ids: members.map(r => r.id), both_expected_presence_match: members.every(r => r.review.expected_presence_match),
      both_runtime_parse_ok: members.every(r => r.review.runtime_parse_ok),
      both_strict_target_exact: members.every(r => typeof r.strict_target_exact === 'boolean') ? members.every(r => r.strict_target_exact) : null,
      outcomes: members.map(r => ({ id: r.id, expected_concern: r.review.expected_concern, actual: r.review.runtime_findings_state, expected_line_set_match: r.review.exact_expected_line_set })) };
  });
  const group = selection => ({ rows: selection.length,
    review_rows: selection.filter(r => r.review).length,
    exact_target_defined: selection.filter(r => typeof r.strict_target_exact === 'boolean').length,
    stop_reason_available: selection.filter(r => r.stop_reason !== null).length,
    strict_target_exact: selection.filter(r => r.strict_target_exact === true).length,
    normalized_target_match: selection.filter(r => r.normalized_target_match === true).length,
    eos_stops: selection.filter(r => r.stop_reason === 'eos').length,
    token_limit_stops: selection.filter(r => r.stop_reason === 'token-limit').length,
    process_failures: selection.filter(r => r.process.failure === true).length,
    strict_json_valid: selection.filter(r => r.review?.strict_json_syntax).length,
    normalized_json_valid: selection.filter(r => r.review?.host_normalized_json_syntax).length,
    runtime_parse_ok: selection.filter(r => r.review?.runtime_parse_ok).length,
    usable_empty: selection.filter(r => r.review?.runtime_findings_state === 'empty').length,
    usable_nonempty: selection.filter(r => r.review?.runtime_findings_state === 'nonempty').length,
    unusable_reviews: selection.filter(r => r.review?.runtime_findings_state === 'unusable').length,
    expected_presence_match: selection.filter(r => r.review?.expected_presence_match).length,
    concern_expected_line_set_match: selection.filter(r => r.review?.exact_expected_line_set === true).length,
    concern_any_expected_line: selection.filter(r => r.review?.has_any_expected_line === true).length,
    concern_alternative_citation_cases: selection.filter(r => r.review?.alternative_line_ids?.length).length });
  return { all: group(rows), groups: Object.fromEntries([...new Set(rows.map(r => r.group))].map(k => [k, group(rows.filter(r => r.group === k))])),
    review_pairs: pairs.size, pairs_both_expected_presence_match: pairRows.filter(p => p.both_expected_presence_match).length,
    pairs_exact_target_defined: pairRows.filter(p => typeof p.both_strict_target_exact === 'boolean').length,
    pairs_both_strict_target_exact: pairRows.filter(p => p.both_strict_target_exact === true).length, pairs: pairRows };
}

async function analyze(label, trainingFile, reviewFile) {
  const training = readRows(trainingFile), diagnostic = readRows(reviewFile);
  requireThat(training.length === 64 && diagnostic.length === 12, `${label}: inputs incomplete (${training.length}/64, ${diagnostic.length}/12)`);
  const trainingByID = new Map(training.map(r => [r.name, r]));
  const reviewByID = new Map(diagnostic.map(r => [r.case_id, r]));
  requireThat(trainingByID.size === 64 && reviewByID.size === 12, `${label}: duplicate result IDs`);
  requireThat(new Set([...training, ...diagnostic].map(r => r.model_sha256)).size === 1, `${label}: mixed model artifacts`);
  const trainRows = sft.map(source => {
    const r = trainingByID.get(source.id);
    requireThat(r, `${label}: missing training ID ${source.id}`);
    requireThat(r.cases_sha256 === fileHash(sftPath), `${label}: training corpus hash mismatch`);
    requireThat(r.system === source.messages[0].content && r.prompt === source.messages[1].content && r.expected_response === source.messages[2].content, `${label}: training text mismatch ${source.id}`);
    const prompt = `<|im_start|>system\n${r.system}<|im_end|>\n<|im_start|>user\n${r.prompt}<|im_end|>\n<|im_start|>assistant\n`;
    requireThat(hash(prompt) === r.prompt_sha256, `${label}: prompt hash mismatch ${source.id}`);
    const process = { returncode: r.returncode ?? null, failure: typeof r.returncode === 'number' ? r.returncode !== 0 : null, recorded_error: r.error ?? null };
    const result = { id: source.id, pair: source.pair ?? null, group: source.kind, prompt_sha256: r.prompt_sha256,
      decoding: r.decoding, stop_reason: r.stop_reason ?? null, generated_tokens: r.generated_tokens ?? null, process,
      raw_response: r.response, expected_response: r.expected_response,
      strict_target_exact: r.returncode === 0 && r.stop_reason === 'eos' && r.response === r.expected_response,
      normalized_target_match: r.response.trim() === r.expected_response.trim() };
    if (source.kind === 'review') {
      const gold = JSON.parse(r.expected_response).findings;
      result.group = gold.length ? 'concern' : 'clean';
      result.review = analyzeReview(r.response, trainingChunk(source), { concern: !!gold.length, line_ids: gold.map(f => f.line_id), reason: gold.map(f => f.reason) }, process);
    }
    return result;
  });
  const reviewRows = [];
  for (const source of diagnostics) {
    const r = reviewByID.get(source.id);
    requireThat(r, `${label}: missing diagnostic ID ${source.id}`);
    requireThat(r.cases_sha256 === fileHash(diagnosticPath), `${label}: diagnostic corpus hash mismatch`);
    const chunks = chunksFor(source.files);
    requireThat(chunks.length === 1, `${source.id}: expected exactly one review chunk`);
    const prompt = await promptFor(chunks[0], source.context, identity, 'chatml');
    requireThat(hash(prompt) === r.prompt_sha256, `${label}: diagnostic prompt changed ${source.id}`);
    requireThat(r.expected_concern === source.expected_concern && sameSet(r.expected_line_ids, source.expected_line_ids), `${label}: expected diagnostic labels changed ${source.id}`);
    // The review harness records the failure phase, but not a child return code.
    const process = { returncode: null, failure: r.error?.phase === 'inference' ? true : r.error === null || r.error?.phase === 'parse' ? false : null, recorded_error: r.error ?? null, recorded_host_failure: !!r.error };
    const result = { id: source.id, pair: source.pair, group: source.expected_concern ? 'concern' : 'clean', prompt_sha256: r.prompt_sha256,
      decoding: { ...r.decoding, tokens: r.tokens }, stop_reason: null, generated_tokens: null, process, raw_response: r.raw_response,
      strict_target_exact: null, normalized_target_match: null,
      review: analyzeReview(r.raw_response, chunks[0], { concern: source.expected_concern, line_ids: source.expected_line_ids, reason: source.expected_reason_concept }, process),
      recorded_structural_location_pass: r.structural_location_pass, recorded_semantic_assessment: r.semantic_assessment ?? null };
    requireThat((result.review.runtime_parse_ok && !r.error) === (r.parsed_findings !== null && !r.error), `${label}: parser agreement changed ${source.id}`);
    reviewRows.push(result);
  }
  return { label, model_sha256: training[0].model_sha256,
    files: { training: { path: trainingFile, sha256: fileHash(trainingFile) }, diagnostics: { path: reviewFile, sha256: fileHash(reviewFile) } },
    training: { summary: aggregate(trainRows), rows: trainRows }, diagnostics: { summary: aggregate(reviewRows), rows: reviewRows } };
}

try {
  const previous = await analyze('previous_examples', 'training/results/2026-09-29-convergence/examples-train-generation.jsonl', 'training/results/2026-09-29-convergence/examples-review.jsonl');
  const compact = summary => Object.fromEntries(Object.entries(summary).filter(([key]) => key !== 'pairs'));
  if (process.argv.includes('--check-control')) {
    console.log(JSON.stringify({ status: 'control_read_verified_no_summary_written', training: compact(previous.training.summary), diagnostics: compact(previous.diagnostics.summary) }, null, 2));
  } else {
    const current = await analyze('verdict_balance', 'models/verdict-balance-train-generation.jsonl', 'models/verdict-balance-review.jsonl');
    const changes = {};
    for (const split of ['training', 'diagnostics']) changes[split] = current[split].rows.map((row, i) => {
      const old = previous[split].rows[i];
      requireThat(old.id === row.id && old.prompt_sha256 === row.prompt_sha256, `Cross-run prompt mismatch ${row.id}`);
      requireThat(JSON.stringify(old.decoding) === JSON.stringify(row.decoding), `Cross-run decoding mismatch ${row.id}`);
      return { id: row.id, previous_presence_match: old.review?.expected_presence_match ?? null, current_presence_match: row.review?.expected_presence_match ?? null,
        previous_state: old.review?.runtime_findings_state ?? null, current_state: row.review?.runtime_findings_state ?? null,
        previous_line_ids: old.review?.returned_line_ids ?? null, current_line_ids: row.review?.returned_line_ids ?? null,
        previous_strict_target_exact: old.strict_target_exact, current_strict_target_exact: row.strict_target_exact };
    });
    const summary = { generated_at: new Date().toISOString(), parser_file: 'bin/jovovich.mjs', parser_sha256: fileHash('bin/jovovich.mjs'),
      source_script_sha256: hash(readFileSync(new URL(import.meta.url))), completeness: { training_per_model: 64, diagnostics_per_model: 12 },
      method: 'Strict JSON syntax, host-normalized syntax, actual production parseReview acceptance, empty/nonempty presence and expected-line membership are separate. No automatic reason correctness or semantic grading. Error/invalid output is unusable, never clean. Alternate citations and complete reasons are retained for manual assessment.',
      comparison_note: 'Previous diagnostic prompts have already been inspected; this comparison is not a fresh blinded holdout. Exact target match requires successful process, EOS and byte-identical output and is only defined for training targets.',
      previous, current, changes };
    writeFileSync(out, JSON.stringify(summary, null, 2) + '\n', { flag: 'wx' });
    console.log(JSON.stringify({ output: out, sha256: hash(readFileSync(out)), previous: { training: compact(previous.training.summary), diagnostics: compact(previous.diagnostics.summary) }, current: { training: compact(current.training.summary), diagnostics: compact(current.diagnostics.summary) } }, null, 2));
  }
} catch (error) { console.error(`verdict-generation-summary: ${error.message}`); process.exitCode = 1; }
