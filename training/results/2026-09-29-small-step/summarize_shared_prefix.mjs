#!/usr/bin/env node
// Recompute the paired diagnostic from immutable raw outputs; no inference.
import assert from 'node:assert/strict';
import { readFile, open } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { PREFIX, PREFIX_IDS, casesFor, matchingNatural, verifyBoundary } from './probe_shared_prefix.mjs';

const ROOT = process.cwd(), HERE = path.dirname(fileURLToPath(import.meta.url));
const { parseReview } = await import(pathToFileURL(path.join(ROOT, 'bin/jovovich.mjs')));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const jsonl = text => {
  assert.ok(text.endsWith('\n'), 'incomplete final JSONL record');
  return text.trim().split('\n').filter(Boolean).map(JSON.parse);
};

export function outcome(response, stop, job) {
  assert.equal(typeof response, 'string');
  assert.ok(['eos', 'token-limit'].includes(stop), 'missing generation stop reason');
  const clean = response.trim().replace(/(?:<\|im_end\|>|<\|endoftext\|>)+\s*$/, '').trim()
    .replace(/^```(?:json)?\s*/, '').replace(/\s*```$/, '');
  let jsonValid = false, findings = null, parsed = null, error = null;
  try {
    const value = JSON.parse(clean); jsonValid = true;
    const candidate = Array.isArray(value) ? value : value?.findings;
    if (Array.isArray(candidate)) findings = candidate;
  } catch {}
  try { parsed = parseReview(response, job.chunk).findings; }
  catch (e) { error = e.message; }
  const concern = findings === null ? null : findings.length > 0;
  const returnedIds = parsed?.map(f => job.chunk.lines.findIndex(l =>
    l.side === f.side && l.line === f.line && l.quote === f.quote) + 1) ?? null;
  const expectedSet = new Set(job.expected_line_ids), returnedSet = new Set(returnedIds || []);
  const locationMatch = parsed !== null && expectedSet.size === returnedSet.size &&
    [...expectedSet].every(id => returnedSet.has(id));
  return { json_valid: jsonValid, findings_schema: findings !== null,
    findings_count: findings?.length ?? null, concern, presence_correct: concern === job.expected_concern,
    production_usable: parsed !== null, citation_error: error, returned_line_ids: returnedIds,
    expected_location_set_match: locationMatch, exact_target_match: stop === 'eos' && response === job.expected_response,
    stop_reason: stop, eos: stop === 'eos' };
}

export function summarize(cases, outcomes) {
  assert.equal(cases.length, outcomes.length);
  const count = fn => outcomes.filter(fn).length;
  const pairs = new Map();
  for (const [i, c] of cases.entries()) pairs.set(c.pair, [...(pairs.get(c.pair) || []), i]);
  for (const indices of pairs.values()) {
    assert.equal(indices.length, 2);
    assert.deepEqual(indices.map(i => cases[i].expected_concern).sort(), [false, true]);
  }
  return {
    cases: cases.length, pairs: pairs.size, json_valid: count(o => o.json_valid), findings_schema: count(o => o.findings_schema),
    concern_responses: count(o => o.concern === true), clean_responses: count(o => o.concern === false),
    invalid_presence: count(o => o.concern === null), presence_correct: count(o => o.presence_correct),
    concern_presence_correct: cases.filter((c, i) => c.expected_concern && outcomes[i].presence_correct).length,
    clean_presence_correct: cases.filter((c, i) => !c.expected_concern && outcomes[i].presence_correct).length,
    complete_presence_pairs: [...pairs.values()].filter(ii => ii.every(i => outcomes[i].presence_correct)).length,
    production_usable: count(o => o.production_usable), usable_correct_presence: count(o => o.production_usable && o.presence_correct),
    complete_usable_presence_pairs: [...pairs.values()].filter(ii => ii.every(i => outcomes[i].production_usable && outcomes[i].presence_correct)).length,
    concern_responses_with_valid_citations: count(o => o.concern === true && o.production_usable),
    citation_or_schema_errors: count(o => !o.production_usable), expected_location_set_match: count(o => o.expected_location_set_match),
    exact_target_match: count(o => o.exact_target_match), eos: count(o => o.eos), token_limit: count(o => !o.eos)
  };
}

export function selectedDecisions(metrics, update, allRows, cases) {
  const decision = metrics.filter(m => m.stage === 'decision_train' && m.update === update);
  const full = metrics.filter(m => m.stage === 'sft' && m.epoch === update);
  assert.equal(decision.length, 1); assert.equal(full.length, 1);
  assert.equal(decision[0].measurement, 'post_update'); assert.equal(decision[0].snapshot_saved, true);
  assert.equal(decision[0].decision_positions, 40); assert.equal(decision[0].decision_pairs, 20);
  assert.ok(Number.isFinite(decision[0].mean_decision_ce) && decision[0].mean_decision_ce >= 0);
  assert.equal(decision[0].decision_rows.length, cases.length);
  const byRow = new Map(decision[0].decision_rows.map(r => [r.row, r]));
  const fullByRow = new Map(full[0].teacher_forced_rows.map(r => [r.row, r]));
  assert.equal(byRow.size, cases.length); assert.equal(fullByRow.size, 64);
  const indices = new Map(allRows.map((r, i) => [r.id, i]));
  const results = cases.map(c => {
    const row = indices.get(c.name), r = byRow.get(row), f = fullByRow.get(row);
    assert.ok(r && f); assert.equal(r.decision_position, 3);
    assert.equal(r.decision_target_id, c.expected_next_id);
    assert.equal(r.decision_alternative_id, c.expected_concern ? 788 : 66582);
    assert.ok(Number.isInteger(r.decision_predicted_id) && r.decision_predicted_id >= 0);
    assert.equal(r.decision_correct, r.decision_predicted_id === r.decision_target_id);
    assert.ok(Number.isFinite(r.decision_margin));
    if (r.decision_predicted_id === r.decision_target_id) assert.ok(r.decision_margin >= 0);
    if (r.decision_predicted_id === r.decision_alternative_id) assert.ok(r.decision_margin <= 0);
    if (r.decision_margin === 0 && [r.decision_target_id, r.decision_alternative_id].includes(r.decision_predicted_id))
      assert.equal(r.decision_predicted_id, Math.min(r.decision_target_id, r.decision_alternative_id));
    assert.equal(f.decision_predicted_id, r.decision_predicted_id);
    assert.equal(f.decision_correct, r.decision_correct);
    assert.ok(Math.abs(f.decision_margin-r.decision_margin) <= 2e-5 + 1e-5*Math.abs(r.decision_margin));
    return { position: r.decision_position, target_id: r.decision_target_id, winner_id: r.decision_predicted_id,
      target_correct: r.decision_correct, target_minus_alternative_margin: r.decision_margin,
      full_answer_first_error_position: f.first_error_position };
  });
  const pairs = new Map();
  cases.forEach((c, i) => pairs.set(c.pair, [...(pairs.get(c.pair) || []), i]));
  const correct = results.filter(r => r.target_correct).length;
  const exactPairs = [...pairs.values()].filter(ii => ii.every(i => results[i].target_correct)).length;
  assert.equal(correct, decision[0].decision_correct); assert.equal(exactPairs, decision[0].decision_pairs_exact);
  return { rows: results, summary: { update, mean_decision_ce: decision[0].mean_decision_ce,
    correct_targets: correct, complete_decision_pairs: exactPairs,
    concern_correct: cases.filter((c, i) => c.expected_concern && results[i].target_correct).length,
    clean_correct: cases.filter((c, i) => !c.expected_concern && results[i].target_correct).length } };
}

async function main() {
  assert.ok(process.argv.length <= 3, 'Usage: node summarize_shared_prefix.mjs [NEW_OUTPUT.json]');
  const output = process.argv[2] || 'models/shared-prefix-summary.json';
  const sources = {};
  const read = async (key, filename, format = 'json') => {
    const bytes = await readFile(filename);
    sources[key] = { path: filename, sha256: sha(bytes) };
    if (format === 'bytes') return bytes;
    const text = bytes.toString('utf8');
    return format === 'jsonl' ? jsonl(text) : JSON.parse(text);
  };
  const plan = await read('plan', path.join(HERE, 'shared-prefix-plan.json'));
  const preflight = await read('preflight', 'models/shared-prefix-preflight.json');
  const verification = await read('verification', 'models/shared-prefix-verification.json');
  await read('probe', path.join(HERE, 'probe_shared_prefix.mjs'), 'bytes');
  await read('summarizer', fileURLToPath(import.meta.url), 'bytes');
  await read('host', 'bin/jovovich.mjs', 'bytes'); await read('infer_source', 'src/infer.c', 'bytes');
  await read('runner', 'build/jovovich-infer', 'bytes');
  assert.equal(preflight.plan_sha256, sources.plan.sha256); assert.equal(preflight.probe_sha256, sources.probe.sha256);
  assert.equal(preflight.generations, 80); assert.equal(preflight.global_workers, 4);
  assert.equal(verification.plan_sha256, sources.plan.sha256); assert.equal(verification.probe_sha256, sources.probe.sha256);
  assert.equal(verification.unchanged, true); assert.equal(verification.matched_native_prefixes, 40);
  assert.equal(verification.generated_responses, 80);
  const allRows = await read('dataset', 'training/sft_review_v2.jsonl', 'jsonl');
  const { cases } = await casesFor('train');
  assert.equal(sources.dataset.sha256, plan.cohort.source_sha256);
  assert.equal(plan.cohort.total_generations, 80); assert.deepEqual(plan.intervention.supplied_prefix_ids, PREFIX_IDS);
  assert.equal(plan.intervention.supplied_prefix, PREFIX);
  const arms = {}, combined = {}, comparison = cases.map(c => ({ name: c.name, pair: c.pair, expected_concern: c.expected_concern }));
  for (const [arm, specification] of [['control', plan.models[0]], ['new', plan.models[1]]]) {
    const selection = await read(`${arm}_selection`, specification.selection_reference);
    assert.ok([25, 50, 100].includes(selection.update));
    if (arm === 'control') { assert.equal(selection.update, 50); assert.equal(selection.sha256, specification.model_sha256); }
    assert.equal(verification.models_sha256[arm], selection.sha256);
    const naturalRows = await read(`${arm}_natural`, specification.natural_generation_reference, 'jsonl');
    const natural = matchingNatural(cases, naturalRows, selection.sha256);
    const naturalByName = new Map(naturalRows.map(r => [r.name, r]));
    const metrics = await read(`${arm}_metrics`, specification.teacher_forced_reference, 'jsonl');
    const teacher = selectedDecisions(metrics, selection.update, allRows, cases);
    const rows = await read(`${arm}_shared_prefix`, `models/shared-prefix-${arm}.jsonl`, 'jsonl');
    assert.equal(rows.length, 40);
    const byName = new Map(rows.map(r => [r.name, r])); assert.equal(byName.size, 40);
    combined[arm] = cases.map(c => { const r = byName.get(c.name); assert.ok(r); return r; });
    const naturalOutcomes = [], sharedOutcomes = [];
    for (const [i, c] of cases.entries()) {
      const r = combined[arm][i], n = naturalByName.get(c.name);
      assert.equal(r.pair, c.pair); assert.equal(r.cohort, 'train'); assert.equal(r.model_sha256, selection.sha256);
      assert.equal(path.resolve(r.model), path.resolve(selection.path));
      assert.equal(r.source_sha256, sources.dataset.sha256);
      assert.equal(path.resolve(r.source), path.resolve(plan.cohort.source));
      assert.equal(r.natural_source_sha256, sources[`${arm}_natural`].sha256);
      assert.equal(path.resolve(r.natural_source), path.resolve(specification.natural_generation_reference));
      for (const [field, key] of [['probe_source_sha256', 'probe'], ['runner_sha256', 'runner'],
        ['host_sha256', 'host'], ['infer_source_sha256', 'infer_source']]) assert.equal(r[field], sources[key].sha256);
      assert.equal(r.prompt, c.prompt); assert.deepEqual(r.chunk, c.chunk);
      assert.equal(r.expected_concern, c.expected_concern); assert.equal(r.expected_response, c.expected_response);
      assert.deepEqual(r.expected_line_ids, c.expected_line_ids); assert.equal(r.expected_next_id, c.expected_next_id);
      assert.equal(r.context, 2048); assert.equal(r.shard, i % 2); assert.equal(r.cohort_cases, 40); assert.equal(r.shard_cases, 20);
      assert.deepEqual(r.decoding, { temperature: 0, continuation_tokens: 192, supplied_prefix_tokens: 3, context: 2048, threads: 2, NT_NO_I8: '1' });
      assert.equal(r.supplied_prefix, PREFIX); assert.deepEqual(r.supplied_prefix_ids, PREFIX_IDS);
      assert.equal(r.original_prompt_sha256, sha(c.prompt)); assert.equal(r.supplied_prompt_sha256, sha(c.prompt + PREFIX));
      assert.ok(r.original_prompt_ids.length && r.original_prompt_ids.every(id => Number.isInteger(id) && id >= 0));
      assert.equal(r.original_prompt_ids_sha256, sha(JSON.stringify(r.original_prompt_ids)));
      assert.equal(r.supplied_prompt_ids_sha256, sha(JSON.stringify(r.supplied_prompt_ids)));
      verifyBoundary(r.original_prompt_ids, r.supplied_prompt_ids, null);
      assert.equal(r.native_boundary_verified, true); assert.equal(r.gold_next_id_verified, c.expected_next_id);
      assert.equal(r.returncode, 0); assert.equal(r.execution_error, null); assert.equal(r.signal, null);
      assert.equal(typeof r.continuation, 'string'); assert.equal(r.assembled_response, PREFIX + r.continuation);
      assert.ok(Number.isInteger(r.generated_tokens) && r.generated_tokens >= 0 && r.generated_tokens <= 192);
      if (r.stop_reason === 'token-limit') assert.equal(r.generated_tokens, 192);
      assert.deepEqual(r.natural, natural[i]);
      const no = outcome(natural[i].response, n.stop_reason, c), so = outcome(r.assembled_response, r.stop_reason, c);
      assert.equal(r.assessment.json_valid, so.json_valid); assert.equal(r.assessment.findings_count, so.findings_count);
      assert.equal(r.assessment.concern, so.concern); assert.equal(r.assessment.citation_error, so.citation_error);
      let parsed = null; try { parsed = parseReview(r.assembled_response, c.chunk).findings; } catch {}
      assert.deepEqual(r.assessment.parsed_findings, parsed);
      naturalOutcomes.push(no); sharedOutcomes.push(so);
      comparison[i][arm] = { teacher_forced: teacher.rows[i], natural: no, shared_prefix: so };
    }
    arms[arm] = { selected_update: selection.update, model_sha256: selection.sha256,
      teacher_forced: teacher.summary, natural: summarize(cases, naturalOutcomes), shared_prefix: summarize(cases, sharedOutcomes) };
  }
  for (let i = 0; i < cases.length; i++) for (const field of ['original_prompt_sha256', 'supplied_prompt_sha256',
    'original_prompt_ids', 'supplied_prompt_ids', 'gold_next_id_verified', 'decoding'])
    assert.deepEqual(combined.control[i][field], combined.new[i][field], `cross-model ${field}: ${cases[i].name}`);
  const result = { sources, protocol: { matched_cases: 40, pairs: 20, models: 2, supplied_prefix: PREFIX,
    supplied_prefix_ids: PREFIX_IDS, first_emitted_token: 'not inferred from continuation text',
    production_usable: 'Production parseReview accepts the complete response and every citation; explanation meaning is scored separately.',
    exact_target_match: 'Raw complete response equals the training target and terminates at EOS.',
    semantic_assessment: 'Pending manual review of reason meaning.' }, arms, cases: comparison };
  const file = await open(output, 'wx');
  try { await file.write(JSON.stringify(result, null, 2) + '\n'); } finally { await file.close(); }
  process.stdout.write(JSON.stringify({ output, arms }) + '\n');
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url))
  main().catch(e => { process.stderr.write(`summarize-shared-prefix: ${e.message}\n`); process.exitCode = 1; });
