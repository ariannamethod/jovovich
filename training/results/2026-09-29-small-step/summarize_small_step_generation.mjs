#!/usr/bin/env node
// Compare completed native generations; parsing and citation membership are independent of reason judgment.
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const root = process.cwd();
const outputFlag = process.argv.indexOf('--output');
if (outputFlag >= 0 && (!process.argv[outputFlag + 1] || process.argv[outputFlag + 1].startsWith('--'))) throw new Error('--output requires a path');
const output = path.resolve(outputFlag < 0 ? 'models/decision-small-step-generation-summary.json' : process.argv[outputFlag + 1]);
const { parseReview, parsePatch, chunksFor, promptFor } = await import(pathToFileURL(path.join(root, 'bin/jovovich.mjs')));
const sha = text => createHash('sha256').update(text).digest('hex');
const read = file => readFileSync(path.join(root, file), 'utf8');
const check = (ok, message) => { if (!ok) throw new Error(message); };
const canonical = x => JSON.stringify(x, (_, value) => value && typeof value === 'object' && !Array.isArray(value)
  ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b))) : value);
const same = (a, b) => canonical(a) === canonical(b);
const setSame = (a, b) => same([...new Set(a)].sort((a, b) => a - b), [...new Set(b)].sort((a, b) => a - b));
function load(file, count, key) {
  const text = read(file);
  check(text.endsWith('\n'), `${file}: incomplete final record`);
  const records = text.trimEnd().split('\n').map((line, index) => ({ row: JSON.parse(line), record_line: index + 1 }));
  check(records.length === count, `${file}: ${records.length}/${count} records`);
  const byID = new Map(records.map(item => [item.row[key], item]));
  check(byID.size === count && !byID.has(undefined), `${file}: duplicate or missing IDs`);
  return { file, sha256: sha(text), byID, count };
}
const sftFile = 'training/sft_review_v2.jsonl', diagnosticFile = 'training/review_holdout_v2.jsonl';
const sft = load(sftFile, 64, 'id'), diagnostic = load(diagnosticFile, 12, 'id');
const identity = read('prompts/identity.txt');
const reviewIDs = [...sft.byID].filter(([, item]) => item.row.kind === 'review').map(([id]) => id);
check(reviewIDs.length === 40, 'Expected 40 review training rows');
const prefixIDs = ['scoped-python-analysis-concern', 'allocation-null-guard-introduced', 'short-read-accepted', 'archive-subprocess-forbidden'];
const forcedPrefix = '{"findings":[{"';
const sources = new Map();
for (const id of reviewIDs) {
  const row = sft.byID.get(id).row;
  const task = row.messages[1].content;
  const shown = [...task.matchAll(/^\[(\d+)\] (ADDED|REMOVED) (.+?):(\d+): (.*)$/gm)];
  check(shown.length && shown.every((m, i) => Number(m[1]) === i + 1 && m[3] === shown[0][3]), `${id}: invalid citation table`);
  const chunk = { path: shown[0][3], lines: shown.map(m => ({ side: m[2] === 'ADDED' ? 'RIGHT' : 'LEFT', line: Number(m[4]), quote: m[5] })) };
  const diff = task.split('\n\nSurrounding diff:\n')[1]?.split('\n\nChanged lines to review:\n')[0];
  check(diff && same(parsePatch(diff), chunk.lines), `${id}: diff/citation mismatch`);
  const findings = JSON.parse(row.messages[2].content).findings;
  sources.set(id, { id, pair: row.pair, concern: findings.length > 0, lineIDs: findings.map(f => f.line_id), chunk,
    prompt: `<|im_start|>system\n${row.messages[0].content}<|im_end|>\n<|im_start|>user\n${task}<|im_end|>\n<|im_start|>assistant\n`,
    system: row.messages[0].content, task, target: row.messages[2].content, context: 2048 });
}
for (const [id, item] of diagnostic.byID) {
  const row = item.row, chunks = chunksFor(row.files);
  check(chunks.length === 1 && !sources.has(id), `${id}: invalid diagnostic chunk/ID`);
  sources.set(id, { id, pair: row.pair, concern: row.expected_concern, lineIDs: row.expected_line_ids,
    chunk: chunks[0], prompt: await promptFor(chunks[0], row.context, identity, 'chatml'), context: 8192 });
}
const clean = text => text.trim().replace(/(?:<\|im_end\|>|<\|endoftext\|>)+\s*$/, '').trim().replace(/^```(?:json)?\s*/, '').replace(/\s*```$/, '');
const json = text => { try { return { ok: true, value: JSON.parse(text) }; } catch { return { ok: false }; } };
function assess(raw, source, processOK) {
  const direct = typeof raw === 'string' ? json(raw.trim()) : { ok: false };
  const normalized = typeof raw === 'string' ? json(clean(raw)) : { ok: false };
  const obj = normalized.ok && Array.isArray(normalized.value) ? { findings: normalized.value } : normalized.value;
  const candidates = obj && Array.isArray(obj.findings) ? obj.findings : null;
  let parsed = null, error = null;
  try { check(typeof raw === 'string', 'No response captured'); parsed = parseReview(raw, source.chunk).findings; }
  catch (e) { error = e.message; }
  const usable = parsed !== null && processOK;
  const ids = parsed !== null ? candidates.map(f => Number(f.line_id)) : null;
  return { strict_json: direct.ok, normalized_json: normalized.ok,
    starts_with_trained_shared_prefix: typeof raw === 'string' && raw.startsWith('{"findings'),
    starts_with_fence: typeof raw === 'string' && raw.trimStart().startsWith('```'),
    normalized_top_level: !normalized.ok ? null : Array.isArray(normalized.value) ? 'array' : normalized.value !== null && typeof normalized.value === 'object' ? 'object' : 'other',
    json_findings_state: candidates ? candidates.length ? 'nonempty' : 'empty' : null,
    runtime_parse: parsed !== null, parse_error: error, usable,
    state: usable ? parsed.length ? 'nonempty' : 'empty' : 'unusable',
    expected_presence_match: usable && (parsed.length > 0) === source.concern,
    returned_line_ids: ids,
    expected_line_set_match: source.concern && ids !== null ? setSame(ids, source.lineIDs) : null,
    any_expected_line: source.concern && ids !== null ? ids.some(id => source.lineIDs.includes(id)) : null,
    alternative_line_ids: source.concern && ids !== null ? ids.filter(id => !source.lineIDs.includes(id)) : null,
    findings: parsed?.map((f, i) => ({ line_id: ids[i], ...f })) ?? null,
    invalid_candidates: parsed === null && candidates ? candidates.map(f => ({ line_id: f?.line_id ?? null, reason: f?.reason ?? null })) : null,
    reason_assessment: null };
}

function summarize(rows, paired = true) {
  const count = cases => ({ cases: cases.length,
    exact_target_defined: cases.filter(r => r.exact_target !== null).length,
    exact_target: cases.filter(r => r.exact_target).length,
    strict_json: cases.filter(r => r.result.strict_json).length,
    normalized_json: cases.filter(r => r.result.normalized_json).length,
    starts_with_trained_shared_prefix: cases.filter(r => r.result.starts_with_trained_shared_prefix).length,
    starts_with_fence: cases.filter(r => r.result.starts_with_fence).length,
    runtime_parse: cases.filter(r => r.result.runtime_parse).length,
    empty: cases.filter(r => r.result.state === 'empty').length,
    nonempty: cases.filter(r => r.result.state === 'nonempty').length,
    unusable: cases.filter(r => r.result.state === 'unusable').length,
    expected_presence_match: cases.filter(r => r.result.expected_presence_match).length,
    expected_line_set_match: cases.filter(r => r.result.expected_line_set_match).length,
    alternative_citations: cases.filter(r => r.result.alternative_line_ids?.length).length,
    stop_reason_available: cases.filter(r => r.stop_reason !== null).length,
    eos: cases.filter(r => r.stop_reason === 'eos').length,
    token_limit: cases.filter(r => r.stop_reason === 'token-limit').length });
  const pairs = new Map();
  if (paired) for (const row of rows) { const p = pairs.get(row.pair) || []; p.push(row); pairs.set(row.pair, p); }
  for (const [id, pair] of pairs) check(pair.length === 2 && pair.filter(r => r.expected_concern).length === 1, `Incomplete pair ${id}`);
  return { all: count(rows), concern: count(rows.filter(r => r.expected_concern)), clean: count(rows.filter(r => !r.expected_concern)),
    pairs: paired ? pairs.size : null,
    complete_presence_pairs: paired ? [...pairs.values()].filter(p => p.every(r => r.result.expected_presence_match)).length : null,
    complete_exact_target_pairs: paired && rows.every(r => r.exact_target !== null) ? [...pairs.values()].filter(p => p.every(r => r.exact_target)).length : null };
}

async function run(label, paths) {
  const files = { training: load(paths.training, 40, 'name'), diagnostics: load(paths.diagnostics, 12, 'case_id'), prefix: load(paths.prefix, 4, 'name') };
  check(same([...files.training.byID.keys()].sort(), [...reviewIDs].sort()), `${label}: unexpected training IDs`);
  check(same([...files.diagnostics.byID.keys()].sort(), [...diagnostic.byID.keys()].sort()), `${label}: unexpected diagnostic IDs`);
  check(same([...files.prefix.byID.keys()].sort(), [...prefixIDs].sort()), `${label}: unexpected prefix IDs`);
  const hashes = new Set(Object.values(files).flatMap(f => [...f.byID.values()].map(x => x.row.model_sha256)));
  check(hashes.size === 1 && /^[a-f0-9]{64}$/.test([...hashes][0]), `${label}: mixed/invalid model hashes`);
  const results = {};
  for (const [split, ids] of Object.entries({ training: reviewIDs, diagnostics: [...diagnostic.byID.keys()], prefix: prefixIDs })) {
    results[split] = [];
    for (const id of ids) {
      const { row: r, record_line } = files[split].byID.get(id), source = sources.get(id);
      const prompt = source.prompt + (split === 'prefix' ? forcedPrefix : '');
      check(r.prompt_sha256 === sha(prompt), `${label}/${split}/${id}: prompt hash mismatch`);
      let raw, processOK;
      if (split === 'training') {
        check(r.cases_sha256 === sft.sha256 && r.system === source.system && r.prompt === source.task && r.expected_response === source.target,
          `${label}/${id}: training provenance mismatch`);
        check(r.identity_sha256 === sha(source.system), `${label}/${id}: identity hash mismatch`);
        raw = r.response; processOK = r.returncode === 0;
      } else if (split === 'diagnostics') {
        check(r.cases_sha256 === diagnostic.sha256 && r.identity_sha256 === sha(identity), `${label}/${id}: diagnostic provenance mismatch`);
        check(r.expected_concern === source.concern && setSame(r.expected_line_ids, source.lineIDs), `${label}/${id}: diagnostic labels mismatch`);
        raw = r.raw_response; processOK = r.error?.phase !== 'inference' && (r.error === null || r.error?.phase === 'parse');
      } else {
        check(r.prompt === source.prompt && r.forced_prefix === forcedPrefix && r.context === source.context,
          `${label}/${id}: forced-prefix provenance mismatch`);
        check(r.chunk.path === source.chunk.path && same(r.chunk.lines, source.chunk.lines) && setSame(r.expected_line_ids, source.lineIDs),
          `${label}/${id}: forced-prefix citations mismatch`);
        if (source.target !== undefined) check(r.expected_response === source.target, `${label}/${id}: prefix reference target mismatch`);
        check(typeof r.continuation === 'string' && r.assembled_response === forcedPrefix + r.continuation, `${label}/${id}: assembled continuation mismatch`);
        raw = r.assembled_response; processOK = r.returncode === 0 && !r.signal;
      }
      const result = assess(raw, source, processOK);
      if ('parsed_findings' in r && (r.error === null || r.error?.phase === 'parse')) check(same(result.findings?.map(({ line_id, ...f }) => f) ?? null, r.parsed_findings), `${label}/${id}: recorded/runtime parser disagreement`);
      const exact = source.target === undefined ? null : processOK && r.stop_reason === 'eos' && raw === source.target;
      results[split].push({ id, pair: source.pair, expected_concern: source.concern, expected_line_ids: source.lineIDs,
        source_record_line: record_line, prompt_sha256: r.prompt_sha256,
        decoding: split === 'diagnostics' ? { ...r.decoding, tokens: r.tokens } : r.decoding,
        process_ok: processOK, recorded_error: r.error ?? null, stop_reason: r.stop_reason ?? null,
        exact_target: exact, forced_prefix: split === 'prefix', result });
    }
  }
  return { label, model_sha256: [...hashes][0], files: Object.fromEntries(Object.entries(files).map(([key, f]) => [key, { path: f.file, sha256: f.sha256, records: f.count }])),
    summaries: Object.fromEntries(Object.entries(results).map(([key, rows]) => [key, summarize(rows, key !== 'prefix')])), cases: results };
}

try {
  const base = 'training/results/2026-09-29-decision-only/';
  const previous = await run('decision_only_lr_0_001', { training: base + 'train-generation.jsonl', diagnostics: base + 'review.jsonl', prefix: base + 'prefix.jsonl' });
  if (process.argv.includes('--check-control')) {
    console.log(JSON.stringify({ status: 'previous_artifacts_verified_no_summary_written', model_sha256: previous.model_sha256, summaries: previous.summaries }, null, 2));
  } else {
    const current = await run('decision_only_lr_0_0001', { training: 'models/decision-small-step-train-generation.jsonl', diagnostics: 'models/decision-small-step-review.jsonl', prefix: 'models/decision-small-step-prefix.jsonl' });
    const changes = {};
    for (const split of Object.keys(current.cases)) changes[split] = current.cases[split].map((now, i) => {
      const before = previous.cases[split][i];
      check(now.id === before.id && now.prompt_sha256 === before.prompt_sha256 && same(now.decoding, before.decoding), `${split}/${now.id}: unmatched comparison input/decoding`);
      return { id: now.id, previous_state: before.result.state, current_state: now.result.state,
        previous_presence_match: before.result.expected_presence_match, current_presence_match: now.result.expected_presence_match,
        previous_line_ids: before.result.returned_line_ids, current_line_ids: now.result.returned_line_ids,
        previous_exact_target: before.exact_target, current_exact_target: now.exact_target,
        previous_starts_with_trained_shared_prefix: before.result.starts_with_trained_shared_prefix,
        current_starts_with_trained_shared_prefix: now.result.starts_with_trained_shared_prefix,
        findings_changed: !same(before.result.findings, now.result.findings) };
    });
    const summary = { generated_at: new Date().toISOString(), source_script_sha256: sha(readFileSync(new URL(import.meta.url))),
      parser: { path: 'bin/jovovich.mjs', sha256: sha(read('bin/jovovich.mjs')) },
      corpora: { training: { path: sftFile, sha256: sft.sha256 }, diagnostics: { path: diagnosticFile, sha256: diagnostic.sha256 } },
      measurements: 'JSON syntax, production parser acceptance, finding presence, reference-line membership and exact target reproduction are reported separately. Reasons are retained without automatic grading. Source file and record line locate the complete raw output. The four prefix cases already supply a nonempty finding structure, so their presence counts measure continuation only.',
      previous, current, changes };
    writeFileSync(output, JSON.stringify(summary, null, 2) + '\n', { flag: 'wx' });
    console.log(JSON.stringify({ output, sha256: sha(readFileSync(output)), previous: previous.summaries, current: current.summaries }, null, 2));
  }
} catch (error) { console.error(`small-step-generation-summary: ${error.message}`); process.exitCode = 1; }
