#!/usr/bin/env node
// Structural results from frozen natural generations; semantic judgments are stored separately.
import assert from 'node:assert/strict';
import { readFile, writeFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { PLAN_PATH, casesFor, frozenPlan, validateTrace, sha, jsonl, fileHash } from './evaluate_counterbalanced_reviews.mjs';
const ROOT = process.cwd();
const { assess, casesFor: priorCasesFor, PREFIX_IDS } = await import(pathToFileURL(path.join(ROOT, 'training/results/2026-09-29-small-step/probe_shared_prefix.mjs')));
const sameSet = (a, b) => a.length === b.length && [...new Set(a)].sort().join(',') === [...new Set(b)].sort().join(',');

export function outcome(response, stop, job) {
  const parsed = assess(response, job.chunk);
  const usable = parsed.parsed_findings !== null;
  const ids = usable ? parsed.parsed_findings.map(f => job.chunk.lines.findIndex(l =>
    f.line === l.line && f.side === l.side && f.quote === l.quote) + 1) : null;
  return { json_valid: parsed.json_valid, findings_schema: parsed.findings_count !== null,
    findings_count: parsed.findings_count, concern: parsed.concern,
    empty: parsed.concern === false, production_parse: usable, citation_error: parsed.citation_error,
    returned_line_ids: ids, parsed_findings: parsed.parsed_findings,
    presence_correct: parsed.concern === null ? null : parsed.concern === job.expected_concern,
    usable_presence_correct: usable && parsed.concern === job.expected_concern,
    reference_line_set_match: usable ? sameSet([...new Set(ids)], [...new Set(job.expected_line_ids)]) : null,
    returned_lines_within_expected: usable ? ids.every(id => (job.audit_metadata?.expected_valid_citation_alternatives ?? job.audit_metadata?.expected_line_ids ?? job.expected_line_ids).includes(id)) && (ids.length > 0) === job.expected_concern : null,
    exact_target: typeof job.expected_response === 'string' ? stop === 'eos' && response === job.expected_response : null,
    stop_reason: stop, semantic_assessment: null };
}

export function totals(cases) {
  const count = fn => cases.filter(fn).length;
  const pairs = new Map();
  for (const c of cases) pairs.set(c.pair, [...(pairs.get(c.pair) || []), c]);
  for (const rows of pairs.values()) {
    assert.equal(rows.length, 2);
    assert.deepEqual(rows.map(c => c.expected_concern).sort(), [false, true]);
  }
  return { cases: cases.length, pairs: pairs.size, expected_concerns: count(c => c.expected_concern),
    expected_clean: count(c => !c.expected_concern), json_valid: count(c => c.outcome.json_valid),
    findings_schema: count(c => c.outcome.findings_schema), production_parse: count(c => c.outcome.production_parse),
    empty_responses: count(c => c.outcome.empty), concern_responses: count(c => c.outcome.concern === true),
    undecidable_presence: count(c => c.outcome.concern === null),
    correct_clean_presence: count(c => !c.expected_concern && c.outcome.empty),
    usable_correct_clean: count(c => !c.expected_concern && c.outcome.empty && c.outcome.production_parse),
    correct_concern_presence: count(c => c.expected_concern && c.outcome.concern === true),
    usable_correct_concern_presence: count(c => c.expected_concern && c.outcome.concern === true && c.outcome.production_parse),
    correct_presence: count(c => c.outcome.presence_correct === true),
    usable_correct_presence: count(c => c.outcome.usable_presence_correct),
    complete_presence_pairs: [...pairs.values()].filter(rows => rows.every(c => c.outcome.presence_correct === true)).length,
    complete_usable_presence_pairs: [...pairs.values()].filter(rows => rows.every(c => c.outcome.usable_presence_correct)).length,
    reference_line_set_match: count(c => c.outcome.reference_line_set_match === true),
    returned_lines_within_expected: count(c => c.outcome.returned_lines_within_expected === true),
    exact_target: count(c => c.outcome.exact_target === true),
    eos: count(c => c.outcome.stop_reason === 'eos'), token_limit: count(c => c.outcome.stop_reason === 'token-limit'),
    semantic_assessment: null };
}

function quartetContrasts(cases) {
  const families = new Map();
  for (const c of cases) {
    const m = c.audit_metadata; if (!m) continue;
    const family = m.family ?? m.context_block;
    const shape = ['deletion', 'pure-deletion'].includes(m.shape) ? 'deletion' : 'replacement';
    assert.ok(family && ['deletion', 'pure-deletion', 'replacement', 'replacement-noop'].includes(m.shape));
    const cells = families.get(family) ?? new Map(), key = `${shape}-${c.expected_concern}`;
    assert.ok(!cells.has(key)); cells.set(key, c); families.set(family, cells);
  }
  return [...families].map(([family, cells]) => {
    assert.equal(cells.size, 4);
    const withinShape = ['deletion', 'replacement'].map(shape => {
      const harmful = cells.get(`${shape}-true`), clean = cells.get(`${shape}-false`);
      assert.ok(harmful && clean);
      return { shape, harmful: harmful.name, clean: clean.name,
        harmful_presence: harmful.outcome.concern, clean_presence: clean.outcome.concern,
        harmful_sampled_decision_id: harmful.sampled_decision_id, clean_sampled_decision_id: clean.sampled_decision_id,
        decision_changes_with_context: harmful.sampled_decision_id === null || clean.sampled_decision_id === null ? null :
          harmful.sampled_decision_id !== clean.sampled_decision_id,
        presence_changes_with_context: harmful.outcome.concern === null || clean.outcome.concern === null ? null : harmful.outcome.concern !== clean.outcome.concern,
        both_presence_correct: [harmful, clean].every(c => c.outcome.presence_correct === true),
        both_usable_presence_correct: [harmful, clean].every(c => c.outcome.usable_presence_correct),
        semantic_assessment: null };
    });
    const acrossShape = [true, false].map(expected => {
      const deletion = cells.get(`deletion-${expected}`), replacement = cells.get(`replacement-${expected}`);
      return { expected_concern: expected, deletion: deletion.name, replacement: replacement.name,
        deletion_presence: deletion.outcome.concern, replacement_presence: replacement.outcome.concern,
        same_presence: deletion.outcome.concern === null || replacement.outcome.concern === null ? null : deletion.outcome.concern === replacement.outcome.concern,
        same_first_token: deletion.actual_first_token_id === replacement.actual_first_token_id,
        deletion_sampled_decision_id: deletion.sampled_decision_id, replacement_sampled_decision_id: replacement.sampled_decision_id,
        same_sampled_decision_id: deletion.sampled_decision_id === null || replacement.sampled_decision_id === null ? null :
          deletion.sampled_decision_id === replacement.sampled_decision_id,
        semantic_assessment: null };
    });
    return { family, within_shape: withinShape, across_shape: acrossShape, semantic_assessment: null };
  });
}

async function main() {
  assert.ok(process.argv.length <= 3, 'Usage: node summarize_counterbalanced_reviews.mjs [NEW_OUTPUT.json]');
  const output = process.argv[2] ?? 'models/counterbalanced-review-generation-summary.json';
  const { plan, plan_sha256 } = await frozenPlan(), sources = {};
  async function read(file, format = 'json') {
    const bytes = await readFile(file); sources[file] = { sha256: sha(bytes), bytes: bytes.length };
    return format === 'bytes' ? bytes : format === 'jsonl' ? jsonl(bytes.toString('utf8')) : JSON.parse(bytes);
  }
  await read(PLAN_PATH);
  assert.equal(sources[PLAN_PATH].sha256, plan_sha256);
  assert.equal(await fileHash(fileURLToPath(import.meta.url)), plan.frozen_evaluation.summary.sha256);
  for (const binding of Object.values(plan.frozen_evaluation))
    sources[binding.path] = { sha256: binding.sha256, bytes: (await stat(binding.path)).size };
  const jobs = {};
  for (const kind of ['train', 'transfer', 'diagnostics']) jobs[kind] = (await casesFor(kind, plan)).cases;
  const audit = await read(plan.frozen_evaluation.corpus_audit.path);
  const originalCorpus = await read('training/sft_review_v2.jsonl', 'jsonl');
  const originalCases = (await priorCasesFor('train')).cases;
  const originalCaseIndex = new Map(originalCorpus.map((r, i) => [r.id, i]));
  const originalPromptIndex = new Map(originalCases.map(c => [c.prompt, { ...c, source_row: originalCaseIndex.get(c.name) }]));
  assert.equal(originalPromptIndex.size, originalCases.length);
  const specs = {
    control: { prefix: 'training/results/2026-10-01-joint-review/', corpus: 'training/sft_review_v2.jsonl' },
    counterbalanced: { prefix: 'models/counterbalanced-review-', corpus: plan.frozen_evaluation.corpus.path }
  };
  const cohorts = {}, raw = {}, native = {}, selectedTraining = {}, conditionalTeacher = {}, quartets = {}, subsets = {};
  for (const [arm, spec] of Object.entries(specs)) {
    const scores = await read(spec.prefix + 'scores.json'), metrics = await read(spec.prefix + 'metrics.jsonl', 'jsonl');
    const selected = await read(spec.prefix + 'selected-model.json');
    if (!sources[spec.corpus]) await read(spec.corpus, 'bytes');
    assert.equal(scores.metrics_sha256, sources[spec.prefix + 'metrics.jsonl'].sha256);
    assert.equal(scores.sft_sha256, sources[spec.corpus].sha256);
    assert.ok([25, 50, 100].includes(scores.selected_update));
    assert.equal(selected.update, scores.selected_update);
    if (arm === 'control') {
      assert.equal(selected.update, 100);
      assert.equal(selected.sha256, plan.comparator.model_sha256);
    }
    const measured = metrics.filter(m => m.stage === 'decision_train' && m.update === selected.update);
    assert.equal(measured.length, 1); assert.equal(measured[0].snapshot_saved, true);
    const full = metrics.filter(m => m.stage === 'sft' && m.epoch === selected.update); assert.equal(full.length, 1);
    const fullRows = new Map(full[0].teacher_forced_rows.map(r => [r.row, r]));
    native[arm] = new Map(measured[0].decision_rows.map(r => [r.row, r]));
    const referenceJobs = arm === 'control' ? originalCases.map(c => ({ ...c, source_row: originalCaseIndex.get(c.name) })) : jobs.train;
    assert.equal(native[arm].size, referenceJobs.length);
    assert.deepEqual([...native[arm].keys()].sort((a, b) => a - b), referenceJobs.map(c => c.source_row).sort((a, b) => a - b));
    selectedTraining[arm] = { selected_update: selected.update, model_sha256: selected.sha256,
      corpus_sha256: scores.sft_sha256, selected: scores.selected, joint_normalization: scores.joint_normalization,
      full_readout: scores.full_readouts.find(r => r.update === selected.update) };
    cohorts[arm] = {}; raw[arm] = {}; quartets[arm] = {};
    for (const [kind, expectedJobs] of Object.entries(jobs)) {
      const slug = `${kind}-natural`, file = `models/counterbalanced-review-${arm}-${slug}.jsonl`;
      const rows = await read(file, 'jsonl'); assert.equal(rows.length, expectedJobs.length);
      const keyed = new Map(rows.map((r, i) => [r.name, { row: r, record_line: i + 1 }]));
      assert.equal(keyed.size, expectedJobs.length); raw[arm][kind] = keyed;
      const binding = plan.frozen_evaluation[kind === 'train' ? 'corpus' : kind];
      const cases = expectedJobs.map((job, jobIndex) => {
        const item = keyed.get(job.name); assert.ok(item, `missing case ${arm}/${kind}/${job.name}`);
        const r = item.row;
        assert.equal(r.plan_sha256, plan_sha256); assert.equal(r.kind, kind); assert.equal(r.mode, 'natural');
        assert.equal(r.pair, job.pair); assert.equal(r.source_row, job.source_row);
        assert.equal(r.model_sha256, selected.sha256); assert.equal(r.source_sha256, binding.sha256);
        assert.equal(r.source, binding.path); assert.equal(r.cohort_cases, expectedJobs.length);
        assert.ok(r.shard === null || kind === 'train' && r.shard === jobIndex % 2);
        assert.equal(r.shard_cases, r.shard === null ? expectedJobs.length : Math.floor((expectedJobs.length + 1 - r.shard) / 2));
        for (const [field, key] of [['runner_sha256', 'runner'], ['host_sha256', 'host'], ['infer_source_sha256', 'infer'], ['probe_source_sha256', 'probe']])
          assert.equal(r[field], plan.frozen_evaluation[key].sha256);
        assert.equal(r.prompt, job.prompt); assert.deepEqual(r.chunk, JSON.parse(JSON.stringify(job.chunk)));
        assert.equal(r.expected_concern, job.expected_concern); assert.deepEqual(r.expected_line_ids, job.expected_line_ids);
        assert.equal(r.expected_response, job.expected_response); assert.equal(r.expected_reason_concept, job.expected_reason_concept);
        assert.deepEqual(r.audit_metadata, job.audit_metadata); assert.equal(r.returncode, 0);
        assert.equal(r.supplied_prefix, ''); assert.deepEqual(r.supplied_prefix_ids, []);
        assert.equal(r.prompt_sha256, sha(job.prompt)); assert.equal(r.supplied_prompt_sha256, sha(job.prompt));
        assert.equal(r.assembled_response, r.continuation);
        assert.deepEqual(r.decoding, { temperature: 0, continuation_tokens: 192, context: job.context, threads: 2, NT_NO_I8: '1' });
        assert.ok(r.original_prompt_ids.length && r.original_prompt_ids.every(id => Number.isInteger(id) && id >= 0));
        validateTrace(r.trace, r.original_prompt_ids);
        assert.equal(r.stop_reason, r.trace.stop_reason);
        assert.equal(sha(JSON.stringify(r.trace) + '\n'), r.trace_sha256);
        assert.equal(r.actual_first_token_id, r.trace.generated_token_ids[0]);
        assert.deepEqual(r.assessment, assess(r.assembled_response, job.chunk));
        const generatedIds = r.trace.generated_token_ids;
        const prefixExact = generatedIds.length > PREFIX_IDS.length && PREFIX_IDS.every((id, i) => generatedIds[i] === id);
        return { name: job.name, pair: job.pair, expected_concern: job.expected_concern,
          source: file, record_line: item.record_line, response_sha256: sha(r.assembled_response),
          actual_first_token_id: r.actual_first_token_id, emitted_tokens: r.trace.emitted_tokens,
          generated_prefix_exact: prefixExact, sampled_decision_id: prefixExact ? generatedIds[PREFIX_IDS.length] : null,
          audit_metadata: job.audit_metadata, outcome: outcome(r.assembled_response, r.stop_reason, job) };
      });
      cohorts[arm][slug] = { model_sha256: selected.sha256, selected_update: selected.update, counts: totals(cases), cases };
      if (kind !== 'diagnostics') quartets[arm][kind] = quartetContrasts(cases);
    }
    const comparisons = jobs.train.map(job => {
      const original = arm === 'control' ? originalPromptIndex.get(job.prompt) : job;
      const generated = raw[arm].train.get(job.name).row;
      if (!original) return { name: job.name, status: 'no-identical-teacher-prompt', semantic_assessment: null };
      const row = native[arm].get(original.source_row), fullRow = fullRows.get(original.source_row);
      assert.ok(row && fullRow); assert.equal(row.decision_position, PREFIX_IDS.length);
      assert.equal(row.decision_correct, row.decision_predicted_id === row.decision_target_id);
      const ids = generated.trace.generated_token_ids;
      const exactPrefix = ids.length > row.decision_position && PREFIX_IDS.every((id, i) => ids[i] === id);
      return { name: job.name, teacher_source_row: original.source_row, teacher_name: original.name,
        status: exactPrefix ? 'compared' : 'generated-prefix-differs',
        teacher_prefix_exact: fullRow.prefix_exact ?? null, generated_prefix_exact: exactPrefix,
        teacher_predicted_id: row.decision_predicted_id, target_id: row.decision_target_id,
        teacher_target_correct: row.decision_correct,
        sampled_decision_id: exactPrefix ? ids[row.decision_position] : null,
        sampled_matches_teacher: exactPrefix ? ids[row.decision_position] === row.decision_predicted_id : null,
        sampled_matches_target: exactPrefix ? ids[row.decision_position] === row.decision_target_id : null,
        semantic_assessment: null };
    });
    conditionalTeacher[arm] = { cases: comparisons.length, identical_teacher_prompts: comparisons.filter(c => c.status !== 'no-identical-teacher-prompt').length,
      compared: comparisons.filter(c => c.status === 'compared').length, matched_teacher: comparisons.filter(c => c.sampled_matches_teacher === true).length,
      mismatches: comparisons.filter(c => c.sampled_matches_teacher === false), rows: comparisons };
    const trainCases = cohorts[arm]['train-natural'].cases;
    subsets[arm] = {
      retained_pairs: totals(trainCases.filter(c => audit.retained_pairs.includes(c.pair))),
      retained_same_diff_pairs: totals(trainCases.filter(c => audit.retained_same_diff_pairs.includes(c.pair))),
      new_quartets: totals(trainCases.filter(c => c.audit_metadata !== null))
    };
  }
  for (const [kind, cases] of Object.entries(jobs)) for (const job of cases) {
    const a = raw.control[kind].get(job.name).row, b = raw.counterbalanced[kind].get(job.name).row;
    assert.equal(a.prompt_sha256, b.prompt_sha256); assert.deepEqual(a.trace.prompt_token_ids, b.trace.prompt_token_ids);
  }
  const generated = Object.values(cohorts).flatMap(arm => Object.values(arm)).reduce((n, c) => n + c.counts.cases, 0);
  assert.equal(generated, plan.evaluation.new_responses);
  const result = { sources, protocol: { plan_sha256, mode: 'natural', supplied_prefix: '', supplied_prefix_ids: [],
    generated_responses: generated, cohorts: Object.keys(specs).length * Object.keys(jobs).length,
    semantic_assessment: 'Stored separately after reading complete generated responses.',
    conditional_teacher_comparison: 'Requires an identical teacher prompt and exact native sampled common-prefix IDs before comparing the decision ID.' },
    cohorts, selected_training: selectedTraining, training_subsets: subsets,
    natural_conditional_teacher_comparison: conditionalTeacher, quartet_contrasts: quartets };
  assert.equal((await frozenPlan()).plan_sha256, plan_sha256);
  await writeFile(output, JSON.stringify(result, null, 2) + '\n', { flag: 'wx' });
  process.stdout.write(JSON.stringify({ output, generated_responses: generated,
    cohorts: Object.fromEntries(Object.entries(cohorts).map(([arm, groups]) => [arm, Object.fromEntries(Object.entries(groups).map(([name, c]) => [name, c.counts]))])) }) + '\n');
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url))
  main().catch(error => { process.stderr.write(`summarize-counterbalanced: ${error.message}\n`); process.exitCode = 1; });
