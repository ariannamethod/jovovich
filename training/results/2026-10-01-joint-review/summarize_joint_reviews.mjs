#!/usr/bin/env node
// Summarize completed generations and native emitted IDs. This file runs no inference.
import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = process.cwd(), HERE = path.dirname(fileURLToPath(import.meta.url));
const OLD = 'training/results/2026-09-29-small-step';
const { casesFor, assess, PREFIX, PREFIX_IDS } = await import(pathToFileURL(path.join(ROOT, OLD, 'probe_shared_prefix.mjs')));
const { chunksFor, promptFor } = await import(pathToFileURL(path.join(ROOT, 'bin/jovovich.mjs')));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const jsonl = text => {
  assert.ok(text.endsWith('\n'), 'incomplete final JSONL record');
  return text.trim().split('\n').filter(Boolean).map(JSON.parse);
};
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
    exact_target: count(c => c.outcome.exact_target === true),
    eos: count(c => c.outcome.stop_reason === 'eos'), token_limit: count(c => c.outcome.stop_reason === 'token-limit'),
    semantic_assessment: null };
}

async function main() {
  assert.ok(process.argv.length <= 3, 'Usage from repository root: node summarize_joint_reviews.mjs [NEW_OUTPUT.json]');
  const output = process.argv[2] || 'models/joint-review-generation-summary.json';
  const sources = {};
  async function read(name, format = 'json') {
    const bytes = await readFile(name); sources[name] = { sha256: sha(bytes), bytes: bytes.length };
    return format === 'bytes' ? bytes : format === 'jsonl' ? jsonl(bytes.toString('utf8')) : JSON.parse(bytes);
  }
  const sft = await read('training/sft_review_v2.jsonl', 'jsonl');
  const index = new Map(sft.map((row, i) => [row.id, i]));
  const train = (await casesFor('train')).cases, diagnostics = (await casesFor('runtime')).cases;
  const auditPath = path.join(HERE, 'diff-shape-audit.jsonl');
  const auditRows = await read(auditPath, 'jsonl'); assert.equal(auditRows.length, 8);
  const identity = (await read('prompts/identity.txt', 'bytes')).toString('utf8');
  const audit = await Promise.all(auditRows.map(async row => {
    const chunks = chunksFor(row.files); assert.equal(chunks.length, 1);
    return { name: row.id, pair: row.pair, prompt: await promptFor(chunks[0], row.context, identity, 'chatml'),
      chunk: chunks[0], context: 8192, expected_concern: row.expected_concern,
      expected_line_ids: row.expected_line_ids, expected_reason_concept: row.expected_reason_concept,
      audit_metadata: row.audit_metadata };
  }));
  await read('training/review_holdout_v2.jsonl', 'bytes');
  await read('bin/jovovich.mjs', 'bytes'); await read('src/infer.c', 'bytes');
  await read('build/jovovich-infer', 'bytes'); await read(fileURLToPath(import.meta.url), 'bytes');
  const wrapper = path.join(HERE, 'evaluate_joint_reviews.mjs'); await read(wrapper, 'bytes');
  const expectedSource = { train: sources['training/sft_review_v2.jsonl'].sha256,
    diagnostics: sources['training/review_holdout_v2.jsonl'].sha256, audit: sources[auditPath].sha256 };
  const specifications = {
    control: { prefix: OLD + '/', score: 'scores.json', metric: 'metrics.jsonl', selected: 'selected-model.json', modes: ['train-shared', 'audit-natural', 'audit-shared'] },
    joint: { prefix: 'models/joint-review-', score: 'scores.json', metric: 'metrics.jsonl', selected: 'selected-model.json', modes: ['train-shared', 'train-natural', 'diagnostics-natural', 'audit-natural', 'audit-shared'] }
  };
  const cohorts = {}, teacherComparisons = {}, native = {}, raw = {};
  for (const [arm, spec] of Object.entries(specifications)) {
    const scores = await read(spec.prefix + spec.score), metrics = await read(spec.prefix + spec.metric, 'jsonl');
    const selected = await read(spec.prefix + spec.selected);
    assert.equal(scores.metrics_sha256, sources[spec.prefix + spec.metric].sha256);
    assert.equal(scores.sft_sha256, expectedSource.train);
    assert.ok([25, 50, 100].includes(scores.selected_update));
    assert.equal(selected.update, scores.selected_update);
    if (arm === 'control') assert.equal(selected.update, 100);
    const measured = metrics.filter(m => m.stage === 'decision_train' && m.update === scores.selected_update);
    assert.equal(measured.length, 1); assert.equal(measured[0].snapshot_saved, true);
    native[arm] = new Map(measured[0].decision_rows.map(row => [row.row, row]));
    assert.equal(native[arm].size, 40);
    assert.deepEqual([...native[arm].keys()].sort((a, b) => a-b), train.map(c => index.get(c.name)).sort((a, b) => a-b));
    cohorts[arm] = {}; raw[arm] = {};
    for (const slug of spec.modes) {
      const [kind, mode] = slug.split('-'), jobs = { train, diagnostics, audit }[kind];
      const file = `models/joint-review-${arm}-${slug}.jsonl`, rows = await read(file, 'jsonl');
      assert.equal(rows.length, jobs.length);
      const keyed = new Map(rows.map((row, i) => [row.name, { row, record_line: i + 1 }]));
      assert.equal(keyed.size, jobs.length);
      raw[arm][slug] = keyed;
      const cases = jobs.map(job => {
        const item = keyed.get(job.name); assert.ok(item, `missing case ${arm}/${slug}/${job.name}`);
        const r = item.row;
        assert.equal(r.kind, kind); assert.equal(r.mode, mode); assert.equal(r.pair, job.pair);
        assert.equal(r.model_sha256, selected.sha256); assert.equal(r.source_sha256, expectedSource[kind]);
        for (const [field, name] of [['runner_sha256', 'build/jovovich-infer'], ['host_sha256', 'bin/jovovich.mjs'],
          ['infer_source_sha256', 'src/infer.c'], ['probe_source_sha256', wrapper]]) assert.equal(r[field], sources[name].sha256);
        // JSONL omits optional undefined members (for example agent_paths).
        // Compare the complete expected wire value, retaining every JSON field.
        assert.equal(r.prompt, job.prompt); assert.deepEqual(r.chunk, JSON.parse(JSON.stringify(job.chunk)));
        assert.equal(r.expected_concern, job.expected_concern); assert.deepEqual(r.expected_line_ids, job.expected_line_ids);
        assert.equal(r.expected_response, job.expected_response ?? null);
        assert.equal(r.expected_reason_concept, job.expected_reason_concept ?? null);
        assert.deepEqual(r.audit_metadata, job.audit_metadata ?? null);
        assert.equal(r.returncode, 0);
        const prefix = mode === 'shared' ? PREFIX : '', ids = mode === 'shared' ? PREFIX_IDS : [];
        assert.equal(r.supplied_prefix, prefix); assert.deepEqual(r.supplied_prefix_ids, ids);
        assert.equal(r.prompt_sha256, sha(job.prompt)); assert.equal(r.supplied_prompt_sha256, sha(job.prompt + prefix));
        assert.equal(r.assembled_response, prefix + r.continuation);
        assert.deepEqual(r.decoding, { temperature: 0, continuation_tokens: 192, context: job.context, threads: 2, NT_NO_I8: '1' });
        assert.ok(r.original_prompt_ids.length && r.original_prompt_ids.every(id => Number.isInteger(id) && id >= 0));
        const t = r.trace;
        assert.equal(t.schema_version, 1); assert.equal(t.requested_limit, 192);
        assert.deepEqual(t.prompt_token_ids, [...r.original_prompt_ids, ...ids]);
        assert.ok(t.generated_token_ids.length && t.generated_token_ids.every(id => Number.isInteger(id) && id >= 0));
        assert.ok(['eos', 'token-limit'].includes(t.stop_reason)); assert.equal(r.stop_reason, t.stop_reason);
        assert.ok(Number.isInteger(t.emitted_tokens) && t.emitted_tokens >= 0 && t.emitted_tokens <= 192);
        assert.equal(t.generated_token_ids.length, t.emitted_tokens + (t.stop_reason === 'eos' ? 1 : 0));
        assert.ok(t.generated_token_ids.length <= 192);
        if (t.stop_reason === 'token-limit') assert.equal(t.emitted_tokens, 192);
        assert.equal(sha(JSON.stringify(t) + '\n'), r.trace_sha256);
        assert.equal(r.actual_first_token_id, t.generated_token_ids[0]);
        assert.deepEqual(r.assessment, assess(r.assembled_response, job.chunk));
        return { name: job.name, pair: job.pair, expected_concern: job.expected_concern,
          source: file, record_line: item.record_line, response_sha256: sha(r.assembled_response),
          actual_first_token_id: r.actual_first_token_id, emitted_tokens: t.emitted_tokens,
          audit_metadata: job.audit_metadata ?? null, outcome: outcome(r.assembled_response, t.stop_reason, job) };
      });
      cohorts[arm][slug] = { model_sha256: selected.sha256, selected_update: selected.update, counts: totals(cases), cases };
    }
    const compared = train.map(job => {
      const row = native[arm].get(index.get(job.name)), generated = raw[arm]['train-shared'].get(job.name).row;
      assert.equal(row.decision_position, PREFIX_IDS.length); assert.equal(row.decision_target_id, job.expected_next_id);
      assert.ok(Number.isInteger(row.decision_predicted_id) && row.decision_predicted_id >= 0);
      assert.equal(row.decision_correct, row.decision_predicted_id === row.decision_target_id);
      return { name: job.name, row: row.row, pair: job.pair, expected_concern: job.expected_concern,
        teacher_predicted_id: row.decision_predicted_id, target_id: row.decision_target_id,
        alternative_id: row.decision_alternative_id, actual_first_token_id: generated.actual_first_token_id,
        emitted_matches_teacher: generated.actual_first_token_id === row.decision_predicted_id,
        emitted_matches_target: generated.actual_first_token_id === row.decision_target_id,
        teacher_target_correct: row.decision_correct, semantic_assessment: null };
    });
    assert.equal(compared.filter(r => r.teacher_target_correct).length, scores.selected.correct_targets);
    teacherComparisons[arm] = { selected_update: selected.update, cases: compared.length,
      emitted_matches_teacher: compared.filter(c => c.emitted_matches_teacher).length,
      emitted_matches_target: compared.filter(c => c.emitted_matches_target).length,
      mismatches: compared.filter(c => !c.emitted_matches_teacher), rows: compared };
  }

  const oldRows = await read(OLD + '/shared-prefix-new.jsonl', 'jsonl');
  const oldByName = new Map(oldRows.map(r => [r.name, r])); assert.equal(oldRows.length, 40); assert.equal(oldByName.size, 40);
  const replay = train.map(job => {
    const old = oldByName.get(job.name), current = raw.control['train-shared'].get(job.name).row;
    assert.ok(old); assert.equal(old.model_sha256, current.model_sha256);
    assert.equal(old.original_prompt_sha256, current.prompt_sha256);
    assert.equal(old.supplied_prompt_sha256, current.supplied_prompt_sha256);
    assert.deepEqual(old.supplied_prompt_ids, current.trace.prompt_token_ids);
    assert.equal(old.decoding.temperature, current.decoding.temperature);
    assert.equal(old.decoding.context, current.decoding.context);
    assert.equal(old.decoding.continuation_tokens, current.decoding.continuation_tokens);
    assert.equal(old.decoding.threads, current.decoding.threads); assert.equal(old.decoding.NT_NO_I8, current.decoding.NT_NO_I8);
    return { name: job.name, assembled_response_identical: old.assembled_response === current.assembled_response,
      continuation_identical: old.continuation === current.continuation, stop_reason_identical: old.stop_reason === current.stop_reason,
      old_response_sha256: sha(old.assembled_response), current_response_sha256: sha(current.assembled_response) };
  });
  // Pairing comparisons retain parse failures and metadata identifying the controlled shape change.
  const auditComparisons = [], shapeComparisons = [];
  for (const arm of ['control', 'joint']) for (const mode of ['natural', 'shared']) {
    const cases = cohorts[arm][`audit-${mode}`].cases, pairs = new Map();
    for (const c of cases) pairs.set(c.pair, [...(pairs.get(c.pair) || []), c]);
    for (const [pair, members] of pairs) {
      const harmful = members.find(c => c.expected_concern), clean = members.find(c => !c.expected_concern);
      assert.equal(harmful.audit_metadata.shape, clean.audit_metadata.shape);
      auditComparisons.push({ arm, mode, pair, context_block: harmful.audit_metadata.context_block,
        shape: harmful.audit_metadata.shape, harmful, clean,
        both_presence_correct: members.every(c => c.outcome.presence_correct === true),
        both_usable_presence_correct: members.every(c => c.outcome.usable_presence_correct), semantic_assessment: null });
    }
    const byName = new Map(cases.map(c => [c.name, c]));
    for (const original of cases.filter(c => c.audit_metadata.shape === 'pure-deletion')) {
      const replacement = byName.get(original.audit_metadata.shape_counterpart); assert.ok(replacement);
      assert.equal(original.expected_concern, replacement.expected_concern);
      assert.equal(original.audit_metadata.context_block, replacement.audit_metadata.context_block);
      shapeComparisons.push({ arm, mode, context_block: original.audit_metadata.context_block,
        expected_concern: original.expected_concern, pure_deletion: original.name, replacement_noop: replacement.name,
        deletion_presence: original.outcome.concern, replacement_presence: replacement.outcome.concern,
        same_presence: original.outcome.concern === null || replacement.outcome.concern === null ? null :
          original.outcome.concern === replacement.outcome.concern,
        deletion_usable: original.outcome.production_parse, replacement_usable: replacement.outcome.production_parse,
        same_first_token: original.actual_first_token_id === replacement.actual_first_token_id,
        semantic_assessment: null });
    }
  }
  for (const slug of ['train-shared', 'audit-natural', 'audit-shared']) {
    for (const [name, item] of raw.control[slug]) {
      const other = raw.joint[slug].get(name).row;
      assert.equal(item.row.prompt_sha256, other.prompt_sha256);
      assert.deepEqual(item.row.trace.prompt_token_ids, other.trace.prompt_token_ids);
    }
  }
  const result = { sources, protocol: { interpretation: 'Finding presence, parser acceptance, exact native emitted IDs and manual semantic judgments are separate measurements.',
    semantic_assessment: 'Undecided here; manual assessment is stored separately.',
    native_first_token: 'The first ID sampled by the native runner, including an immediate stopping token.',
    prefix: PREFIX, prefix_ids: PREFIX_IDS, cohorts: 8, generated_responses: 164 },
    cohorts, shared_training_first_token: teacherComparisons,
    control_replay: { source: OLD + '/shared-prefix-new.jsonl', cases: replay.length,
      identical_responses: replay.filter(c => c.assembled_response_identical).length,
      identical_stop_reasons: replay.filter(c => c.stop_reason_identical).length, rows: replay },
    audit_within_shape_pairs: auditComparisons, audit_shape_counterparts: shapeComparisons };
  await writeFile(output, JSON.stringify(result, null, 2) + '\n', { flag: 'wx' });
  process.stdout.write(JSON.stringify({ output, cohorts: Object.fromEntries(Object.entries(cohorts).map(([arm, sets]) =>
    [arm, Object.fromEntries(Object.entries(sets).map(([name, cohort]) => [name, cohort.counts]))])),
    first_token_matches: Object.fromEntries(Object.entries(teacherComparisons).map(([arm, data]) => [arm, data.emitted_matches_teacher])),
    control_replay_identical: result.control_replay.identical_responses }) + '\n');
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url))
  main().catch(error => { process.stderr.write(`summarize-joint: ${error.message}\n`); process.exitCode = 1; });
