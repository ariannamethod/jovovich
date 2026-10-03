import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { chunksFor, parseReview } from '../bin/jovovich.mjs';

const BUILDER = 'training/explanations/build_corpora.py';
const SOURCE = 'training/sft_review_v5.jsonl';
const REASONS = 'training/explanations/reasons.json';
const BEFORE = 'training/sft_review_v6_before.jsonl';
const AFTER = 'training/sft_review_v6_after.jsonl';
const SUFFIX = ' Include a concise analysis string connecting the relevant rule, changed line and consequence.';
const digest = value => createHash('sha256').update(value).digest('hex');
const lines = file => readFileSync(file, 'utf8').trimEnd().split('\n');
const source = lines(SOURCE), before = lines(BEFORE), after = lines(AFTER);

function run(args) {
  return spawnSync('python3', [BUILDER, ...args], { encoding: 'utf8', timeout: 10000 });
}
function fixture() {
  const dir = mkdtempSync(path.join(tmpdir(), 'jovovich-explanation-'));
  const spec = JSON.parse(readFileSync(REASONS, 'utf8'));
  const reasons = path.join(dir, 'reasons.json');
  const first = path.join(dir, 'before.jsonl'), second = path.join(dir, 'after.jsonl');
  const args = ['--reasons', reasons, '--before', first, '--after', second];
  return { dir, spec, reasons, first, second, args,
    save() { writeFileSync(reasons, JSON.stringify(spec)); },
    close() { rmSync(dir, { recursive: true, force: true }); } };
}

test('explanation arms preserve all prompts, findings, pair order and 24 raw nonreview rows', () => {
  assert.equal(source.length, 76); assert.equal(before.length, 76); assert.equal(after.length, 76);
  const spec = JSON.parse(readFileSync(REASONS, 'utf8'));
  assert.equal(spec.source.sha256, digest(readFileSync(SOURCE)));
  assert.deepEqual(spec.authoring_inputs, [SOURCE]);
  let reviewCount = 0, retainedCount = 0;
  const pairs = new Map();
  for (const [i, text] of source.entries()) {
    const original = JSON.parse(text), a = JSON.parse(before[i]), b = JSON.parse(after[i]);
    if (original.kind !== 'review') {
      assert.equal(before[i], text); assert.equal(after[i], text); retainedCount++; continue;
    }
    const explanation = spec.rows[reviewCount++];
    assert.equal(explanation.id, original.id); assert.equal(explanation.pair, original.pair);
    const expectedFindings = JSON.parse(original.messages[2].content).findings;
    const aAnswer = JSON.parse(a.messages[2].content), bAnswer = JSON.parse(b.messages[2].content);
    assert.deepEqual(Object.keys(aAnswer), ['analysis', 'findings']);
    assert.deepEqual(Object.keys(bAnswer), ['findings', 'analysis']);
    assert.equal(aAnswer.analysis, explanation.analysis); assert.equal(bAnswer.analysis, explanation.analysis);
    assert.deepEqual(aAnswer.findings, expectedFindings); assert.deepEqual(bAnswer.findings, expectedFindings);
    for (const arm of [a, b]) {
      const answer = JSON.parse(arm.messages[2].content);
      const serialized = '{' + Object.entries(answer).map(([key, value]) => JSON.stringify(key) + ':' + JSON.stringify(value)).join('\n,') + '\n}';
      assert.equal(arm.messages[2].content, serialized, 'identical newline delimiter policy in both orders');
      assert.ok(arm.messages[2].content.includes('"findings":' + JSON.stringify(expectedFindings) + '\n'),
        'findings has the same trailing delimiter before a comma or closing brace');
      assert.deepEqual(arm.messages[0], original.messages[0]);
      assert.equal(arm.messages[1].content, original.messages[1].content + SUFFIX);
      assert.equal(arm.messages[1].role, original.messages[1].role);
      assert.equal(arm.messages[2].role, original.messages[2].role);
      const restored = structuredClone(arm); restored.messages = original.messages;
      assert.deepEqual(restored, original, 'all row metadata remains unchanged');
      const user = original.messages[1].content;
      const filename = /^Repository rules for (.+):$/m.exec(user)[1];
      const patch = user.split('\n\nSurrounding diff:\n')[1].split('\n\nChanged lines to review:\n')[0];
      const chunks = chunksFor([{ path: filename, patch }]);
      assert.equal(chunks.length, 1);
      assert.deepEqual(parseReview(arm.messages[2].content, chunks[0]), parseReview(original.messages[2].content, chunks[0]));
    }
    assert.deepEqual(a.messages.slice(0, 2), b.messages.slice(0, 2));
    pairs.set(original.pair, [...(pairs.get(original.pair) || []), expectedFindings.length > 0]);
  }
  assert.equal(reviewCount, 52); assert.equal(retainedCount, 24); assert.equal(pairs.size, 26);
  for (const values of pairs.values()) assert.deepEqual(values, [true, false]);
});

test('builder reproduces both frozen corpora and binds its generated audit', () => {
  const checked = run(['--check']); assert.equal(checked.status, 0, checked.stderr);
  const f = fixture();
  try {
    f.save(); const audit = path.join(f.dir, 'audit.json');
    const built = run([...f.args, '--audit', audit]); assert.equal(built.status, 0, built.stderr);
    assert.deepEqual(readFileSync(f.first), readFileSync(BEFORE));
    assert.deepEqual(readFileSync(f.second), readFileSync(AFTER));
    const report = JSON.parse(readFileSync(audit, 'utf8'));
    assert.deepEqual(report.counts, { rows: 76, review_rows: 52, review_pairs: 26, retained_raw_rows: 24 });
    assert.equal(report.builder.sha256, digest(readFileSync(BUILDER)));
    assert.equal(report.source.sha256, digest(readFileSync(SOURCE)));
    assert.equal(report.reasons.sha256, digest(readFileSync(f.reasons)));
    assert.match(report.answer_serialization_policy, /Each top-level answer value is followed by a newline/);
    for (const [key, file] of [['before', BEFORE], ['after', AFTER]]) {
      assert.equal(report[key].sha256, digest(readFileSync(file)));
      assert.equal(report[key].bytes, readFileSync(file).length);
    }
  } finally { f.close(); }
});

test('builder rejects missing, duplicate, reordered and foreign rationale coverage before writing', () => {
  const mutations = [
    spec => spec.rows.pop(),
    spec => spec.rows.push(structuredClone(spec.rows[0])),
    spec => [spec.rows[0], spec.rows[1]] = [spec.rows[1], spec.rows[0]],
    spec => spec.rows[0].id = 'foreign-row',
    spec => spec.rows[0].pair = 'foreign-pair',
    spec => spec.authoring_inputs.push('training/foreign-gold.jsonl'),
    spec => spec.source.sha256 = '0'.repeat(64),
  ];
  for (const mutate of mutations) {
    const f = fixture();
    try {
      mutate(f.spec); f.save(); const result = run(f.args);
      assert.notEqual(result.status, 0); assert.match(result.stderr, /coverage|duplicate|pair|sourced only|hash mismatch/);
      assert.equal(existsSync(f.first), false); assert.equal(existsSync(f.second), false);
    } finally { f.close(); }
  }
});

test('evidence validation rejects wrong scopes, changed-line substitutions and rationale metadata leakage', () => {
  const mutations = [
    spec => spec.rows[0].evidence.rule = spec.rows[1].evidence.rule,
    spec => spec.rows[0].evidence.context = 'A fictitious execution path never supplied in this prompt.',
    spec => spec.rows[0].evidence.changed[0].side = 'REMOVED',
    spec => spec.rows[0].evidence.changed[0].quote = 'import torch',
    spec => spec.rows[0].evidence.changed[0].line_id = 999,
    spec => spec.rows[0].evidence.changed.push(structuredClone(spec.rows[0].evidence.changed[0])),
    spec => spec.rows[0].analysis = spec.rows[0].analysis.replace('[1]', '[999]'),
    spec => spec.rows[0].analysis += ' This is the concern class.',
    spec => spec.rows[0].analysis += ' <|im_end|>',
    spec => spec.rows[0].analysis += ' ' + spec.rows[0].id,
  ];
  for (const mutate of mutations) {
    const f = fixture();
    try {
      mutate(f.spec); f.save(); const result = run(f.args);
      assert.notEqual(result.status, 0); assert.match(result.stderr, /anchor|references|leaks/);
      assert.equal(existsSync(f.first), false); assert.equal(existsSync(f.second), false);
    } finally { f.close(); }
  }
});

test('reasons reject duplicate JSON keys and changed source bytes', () => {
  const f = fixture();
  try {
    f.save();
    writeFileSync(f.reasons, readFileSync(f.reasons, 'utf8').replace('"schema_version":1', '"schema_version":1,"schema_version":1'));
    const duplicate = run(f.args); assert.notEqual(duplicate.status, 0); assert.match(duplicate.stderr, /duplicate JSON key/);
    f.save(); const altered = path.join(f.dir, 'source.jsonl');
    writeFileSync(altered, readFileSync(SOURCE, 'utf8').replace('import statistics', 'import functools'));
    const stale = run([...f.args, '--source', altered]); assert.notEqual(stale.status, 0); assert.match(stale.stderr, /hash mismatch/);
    assert.equal(existsSync(f.first), false); assert.equal(existsSync(f.second), false);
  } finally { f.close(); }
});

test('exclusive publication protects existing destinations and removes incomplete new outputs', () => {
  const f = fixture();
  try {
    f.save(); writeFileSync(f.second, 'previous run\n');
    const existing = run(f.args); assert.notEqual(existing.status, 0); assert.match(existing.stderr, /already exists/);
    assert.equal(existsSync(f.first), false); assert.equal(readFileSync(f.second, 'utf8'), 'previous run\n');
    rmSync(f.second);
    const alias = run(['--reasons', f.reasons, '--before', f.first, '--after', f.first]);
    assert.notEqual(alias.status, 0); assert.match(alias.stderr, /distinct/); assert.equal(existsSync(f.first), false);
    const inputAlias = run(['--reasons', f.reasons, '--before', f.reasons, '--after', f.second]);
    assert.notEqual(inputAlias.status, 0); assert.match(inputAlias.stderr, /aliases an input/);
    const missing = run([...f.args, '--audit', path.join(f.dir, 'missing', 'audit.json')]);
    assert.notEqual(missing.status, 0); assert.equal(existsSync(f.first), false); assert.equal(existsSync(f.second), false);
  } finally { f.close(); }
});

test('both arms pack as explicit JVPR2 with different semantic verdict prefixes', () => {
  const f = fixture();
  try {
    const binaries = [];
    for (const [name, corpus] of [['before', BEFORE], ['after', AFTER]]) {
      const data = path.join(f.dir, `${name}.bin`), pairs = path.join(f.dir, `${name}.pairs`);
      const packed = spawnSync('python3', ['training/prepare.py', data, '--sft', corpus, '--sft-only',
        '--review-pairs', pairs, '--pair-format', '2'], { encoding: 'utf8', timeout: 10000 });
      assert.equal(packed.status, 0, packed.stderr);
      const bytes = readFileSync(pairs); assert.equal(bytes.subarray(0, 8).toString('hex'), '4a56505202000000');
      assert.equal(bytes.readUInt32LE(8), 76); assert.equal(bytes.readUInt32LE(12), 26);
      let offset = 16;
      for (let i = 0; i < 26; i++) {
        offset += 8;
        for (let side = 0; side < 2; side++) {
          const size = bytes.readUInt32LE(offset); offset += 4;
          const prefix = bytes.subarray(offset, offset + size).toString('utf8'); offset += size;
          if (name === 'before') { assert.ok(prefix.startsWith('{"analysis":"')); assert.ok(prefix.endsWith('\n,"findings')); }
          else assert.equal(prefix, '{"findings');
        }
      }
      assert.equal(offset, bytes.length); binaries.push(readFileSync(data));
    }
    assert.notDeepEqual(binaries[0], binaries[1]);
  } finally { f.close(); }
});
