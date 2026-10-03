import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import process from 'node:process';
import { isDeepStrictEqual, parseArgs } from 'node:util';

const EXPECT = {
  v5: 'a677211e90576dea45ad4fa534fc97a3a6496944d63df99315ed934505936417',
  before: 'a2f22e789b176b1f23ed1262b3e94449819a1484ed31ddb87c3dbedbb8574250',
  after: 'd5f3e06e62440135d2a4e8a91c99705d68e69ce3ad2dde5bac272ba647b42218',
  reasons: 'c2269304dea5dbe65a42308116a51b383d9a535ec47fca7cedd122136c670e45',
};
const FORBIDDEN = [
  /\b\d+\s+(lines?|additions?|deletions?|hunks?|changes)\b/gi,
  /line count/gi,
  /number of (lines|changes)/gi,
  /\bshape\b/gi,
  /deletion itself/gi,
  /(only|just|merely|simply) (deletes?|removes?|adds?)/gi,
  /(small|large|short|long|tiny|big)(er)? (diff|change|patch)/gi,
  /(diff|change|patch) (is|looks) (small|large|short|long)/gi,
];

const die = text => { console.error(`v6_check: ${text}`); process.exit(2); };
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const parse = text => { try { return JSON.parse(text); } catch { return undefined; } };
const msg = (row, role) => { const m = row.messages.find(x => x.role === role); if (!m) throw new Error(`${row.id}: no ${role} message`); return m.content; };
const sentences = text => text.trim().split(/(?<=[.!?])\s+/);
const citations = text => [...new Set([...text.matchAll(/\[(\d+)\]/g)].map(m => m[1]))].sort((a, b) => a - b);
const words = text => new Set(text.toLowerCase().match(/\w+/g) || []);
const byPair = rows => rows.reduce((m, r) => m.set(r.pair, [...(m.get(r.pair) || []), r]), new Map());
function changed(row) {
  const u = msg(row, 'user'), head = 'Changed lines to review:\n', s = u.indexOf(head), e = u.indexOf('\n\nReview the', s);
  if (s < 0 || e < 0) throw new Error(`${row.id}: no changed-lines block`);
  const block = u.slice(s + head.length, e);
  return { block, sides: new Map(block.split('\n').flatMap(l => { const m = /^\[(\d+)\] (ADDED|REMOVED) /.exec(l); return m ? [[m[1], m[2]]] : []; })) };
}
function splitLines(buf) {
  const out = []; let start = 0, i;
  while ((i = buf.indexOf(10, start)) !== -1) { out.push(buf.subarray(start, i)); start = i + 1; }
  return start < buf.length ? [...out, buf.subarray(start)] : out;
}

let opts;
try {
  opts = parseArgs({ options: {
    v5: { type: 'string', default: 'training/sft_review_v5.jsonl' },
    before: { type: 'string', default: 'training/sft_review_v6_before.jsonl' },
    after: { type: 'string', default: 'training/sft_review_v6_after.jsonl' },
    reasons: { type: 'string', default: 'training/explanations/reasons.json' },
    adjudications: { type: 'string' },
    out: { type: 'string' },
  } }).values;
} catch (e) { die(e.message); }
if (!opts.out) die('usage: v6_check.mjs --out REPORT [--v5 F] [--before F] [--after F] [--reasons F] [--adjudications F]');

const inputs = {}, raw = {};
for (const k of ['v5', 'before', 'after', 'reasons', ...(opts.adjudications ? ['adjudications'] : [])]) {
  try { raw[k] = readFileSync(opts[k]); } catch (e) { die(`${opts[k]}: ${e.message}`); }
  inputs[k] = { path: opts[k], sha256: digest(raw[k]), bytes: raw[k].length };
}
let adj = {};
if (opts.adjudications) {
  adj = parse(raw.adjudications.toString('utf8'));
  if (!adj || typeof adj !== 'object' || Array.isArray(adj)) die(`${opts.adjudications}: expected a JSON object`);
}
const L = {}, R = {};
for (const k of ['v5', 'before', 'after']) { L[k] = splitLines(raw[k]); R[k] = L[k].map(b => parse(b.toString('utf8'))); }
const V = R.v5, ARMS = [['before', R.before], ['after', R.after]];
const reasons = parse(raw.reasons.toString('utf8'));
const REV = V.flatMap((r, i) => r?.kind === 'review' ? [i] : []);

function analyses() {
  const cls = new Map(REV.map(i => [V[i].id, parse(msg(V[i], 'assistant')).findings.length ? 'concern' : 'clean']));
  return reasons.rows.map(r => ({ id: r.id, pair: r.pair, class: cls.get(r.id) ?? null, analysis: r.analysis,
    sentences: sentences(r.analysis), citations: citations(r.analysis) }));
}

const checks = [];
function check(id, hard, fn, extra = {}, failStatus = hard ? 'FAIL' : 'DEVIATION') {
  const c = { id, hard, ...extra, status: 'PASS', detail: null, failure_count: 0, failures: [] };
  const fail = f => { if (c.failure_count++ < 20) c.failures.push(f); };
  try { c.detail = fn(fail); if (c.failure_count) c.status = failStatus; }
  catch (e) { c.status = 'ERROR'; c.detail = { error: String(e?.stack ?? e) }; }
  checks.push(c);
  const note = c.status === 'ERROR' ? c.detail.error.split('\n')[0] : c.detail?.summary ?? '';
  console.log(`${id} ${c.status} failures=${c.failure_count} ${note}`.trimEnd());
}

check('H1', true, fail => {
  for (const [k, want] of Object.entries(EXPECT))
    if (inputs[k].sha256 !== want) fail({ input: k, path: inputs[k].path, expected: want, actual: inputs[k].sha256 });
  const recorded = reasons.source.sha256;
  if (recorded !== inputs.v5.sha256) fail({ field: 'reasons.source.sha256', recorded, actual: inputs.v5.sha256 });
  return { summary: `reasons.source.sha256=${recorded}`, reasons_source_sha256: recorded };
});

check('H2', true, fail => {
  const meta = r => [r.id, r.kind, Object.hasOwn(r, 'pair'), r.pair];
  for (const [k, rows] of Object.entries(R)) {
    if (rows.length !== 76) fail({ input: k, rows: rows.length, expected: 76 });
    rows.forEach((r, i) => { if (!r || typeof r !== 'object') fail({ input: k, index: i, error: 'invalid JSON object' }); });
  }
  for (const [k, rows] of ARMS)
    for (let i = 0; i < Math.max(V.length, rows.length); i++)
      if (!V[i] || !rows[i] || !isDeepStrictEqual(meta(V[i]), meta(rows[i])))
        fail({ arm: k, index: i, v5: V[i] && meta(V[i]), arm_meta: rows[i] && meta(rows[i]) });
  const want = REV.map(i => [V[i].id, V[i].pair]), got = reasons.rows.map(r => [r.id, r.pair]);
  if (want.length !== 52) fail({ v5_review_rows: want.length, expected: 52 });
  if (got.length !== 52) fail({ reasons_rows: got.length, expected: 52 });
  for (let i = 0; i < Math.max(want.length, got.length); i++)
    if (!isDeepStrictEqual(want[i], got[i])) fail({ reasons_index: i, v5: want[i], reasons: got[i] });
  return { summary: `rows ${V.length}/${R.before.length}/${R.after.length} review ${want.length} reasons ${got.length}`,
    rows: { v5: V.length, before: R.before.length, after: R.after.length }, review_rows: want.length, reasons_rows: got.length };
});

check('H3', true, fail => {
  let n = 0;
  V.forEach((r, i) => {
    if (!r || r.kind === 'review') return;
    n++;
    for (const k of ['before', 'after']) if (!L[k][i] || !L[k][i].equals(L.v5[i])) fail({ arm: k, index: i, id: r.id });
  });
  if (n !== 24) fail({ nonreview_rows: n, expected: 24 });
  return { summary: `nonreview ${n}`, nonreview_rows: n };
});

check('H4_strict', false, fail => {
  for (const i of REV) for (const [k, rows] of ARMS) {
    const system = msg(rows[i], 'system') === msg(V[i], 'system'), user = msg(rows[i], 'user') === msg(V[i], 'user');
    if (!system || !user) fail({ id: V[i].id, arm: k, system_identical: system, user_identical: user });
  }
  return { summary: `review rows ${REV.length} x 2 arms`, review_rows: REV.length };
});

check('H4_suffix', true, fail => {
  const deltas = new Map();
  if (REV.length !== 52) fail({ review_rows: REV.length, expected: 52 });
  for (const i of REV) {
    const v = V[i], vu = msg(v, 'user'), roles = v.messages.map(m => m.role);
    for (const [k, rows] of ARMS) {
      const r = rows[i], u = msg(r, 'user');
      if (!isDeepStrictEqual(r.messages.map(m => m.role), roles)) fail({ id: v.id, arm: k, error: 'role array differs' });
      if (msg(r, 'system') !== msg(v, 'system')) fail({ id: v.id, arm: k, error: 'system content differs' });
      if (!u.startsWith(vu)) { fail({ id: v.id, arm: k, error: 'user does not start with v5 user' }); continue; }
      const d = u.slice(vu.length);
      if (!d) fail({ id: v.id, arm: k, error: 'empty user delta' });
      deltas.set(d, (deltas.get(d) || 0) + 1);
    }
    if (msg(R.before[i], 'user') !== msg(R.after[i], 'user')) fail({ id: v.id, error: 'before.user !== after.user' });
  }
  if (deltas.size !== 1) fail({ unique_deltas: deltas.size, expected: 1 });
  const list = [...deltas].map(([delta, count]) => ({ delta, count }));
  return { summary: `unique_deltas=${deltas.size} ${list.map(x => `${JSON.stringify(x.delta)}x${x.count}`).join(' ')}`, deltas: list };
});

check('H5', true, fail => {
  const pairs = new Map();
  for (const i of REV) {
    const v = V[i], vf = parse(msg(v, 'assistant'))?.findings;
    if (!Array.isArray(vf)) { fail({ id: v.id, error: 'v5 findings not an array' }); continue; }
    const cls = vf.length ? 'concern' : 'clean';
    pairs.set(v.pair, [...(pairs.get(v.pair) || []), cls]);
    for (const [k, rows] of ARMS) {
      const text = msg(rows[i], 'assistant'), f = parse(text)?.findings;
      if (!isDeepStrictEqual(f, vf)) fail({ id: v.id, arm: k, error: 'findings differ from v5' });
      if (!text.includes('"findings":' + JSON.stringify(vf))) fail({ id: v.id, arm: k, error: 'compact findings substring missing' });
      if (!text.includes(cls === 'concern' ? '"findings":[{' : '"findings":[]')) fail({ id: v.id, arm: k, error: `${cls} marker missing` });
      if ((Array.isArray(f) && f.length ? 'concern' : 'clean') !== cls) fail({ id: v.id, arm: k, error: 'class differs from v5' });
    }
  }
  for (const [pair, cs] of pairs)
    if (cs.length !== 2 || !cs.includes('concern') || !cs.includes('clean')) fail({ pair, classes: cs });
  if (pairs.size !== 26) fail({ pairs: pairs.size, expected: 26 });
  return { summary: `pairs ${pairs.size}`, pairs: pairs.size };
});

check('H6', true, fail => {
  const byId = new Map(reasons.rows.map(r => [r.id, r]));
  for (const i of REV) {
    const id = V[i].id, want = byId.get(id)?.analysis;
    const a = parse(msg(R.before[i], 'assistant')), b = parse(msg(R.after[i], 'assistant'));
    if (!isDeepStrictEqual(Object.keys(a ?? {}), ['analysis', 'findings'])) fail({ id, arm: 'before', keys: Object.keys(a ?? {}) });
    if (!isDeepStrictEqual(Object.keys(b ?? {}), ['findings', 'analysis'])) fail({ id, arm: 'after', keys: Object.keys(b ?? {}) });
    if (typeof want !== 'string') fail({ id, error: 'no reasons analysis' });
    if (a?.analysis !== want || b?.analysis !== want || a?.analysis !== b?.analysis) fail({ id, error: 'analysis differs from reasons or between arms' });
  }
  return { summary: `review rows ${REV.length}` };
});

check('H7', true, fail => {
  const rows = analyses(), counts = {};
  if (rows.length !== 52) fail({ rows: rows.length, expected: 52 });
  for (const r of rows) {
    const n = r.sentences.length, ends = /[.!?]$/.test(r.analysis.trim());
    counts[n] = (counts[n] || 0) + 1;
    if (!ends || n < 2 || n > 4) fail({ id: r.id, ends_with_terminal: ends, sentence_count: n, sentences: r.sentences });
  }
  return { summary: `sentence counts ${JSON.stringify(counts)}`, sentence_counts: counts };
});

check('H8', false, fail => {
  const out = []; let sameCount = 0, sameCites = 0;
  for (const [pair, ms] of byPair(analyses())) {
    const c = ms.find(m => m.class === 'concern'), k = ms.find(m => m.class === 'clean');
    if (ms.length !== 2 || !c || !k) { fail({ pair, ids: ms.map(m => m.id), classes: ms.map(m => m.class) }); continue; }
    const counts = c.sentences.length === k.sentences.length, cites = isDeepStrictEqual(c.citations, k.citations);
    sameCount += counts; sameCites += cites;
    out.push({ pair, concern: { id: c.id, sentences: c.sentences.length, citations: c.citations },
      clean: { id: k.id, sentences: k.sentences.length, citations: k.citations }, equal_sentences: counts, equal_citations: cites });
    if (!counts || !cites) fail(out.at(-1));
  }
  if (out.length !== 26) fail({ pairs: out.length, expected: 26 });
  return { summary: `sentences ${sameCount}/26 citations ${sameCites}/26`, pairs: out };
}, { superseded_by: 'H8v2', note: 'measure defect: mirrored introduced/repaired pairs index different diffs, so equal [n] numbers do not mean equal lines' }, 'FAIL');

check('H8v2', true, fail => {
  const rowById = new Map(REV.map(i => [V[i].id, V[i]])), tally = { same_diff: [0, 0], mirrored: [0, 0] }, out = [];
  let sameCount = 0;
  for (const [pair, ms] of byPair(analyses())) {
    const c = ms.find(m => m.class === 'concern'), k = ms.find(m => m.class === 'clean');
    if (ms.length !== 2 || !c || !k) { fail({ pair, ids: ms.map(m => m.id), classes: ms.map(m => m.class) }); continue; }
    const members = [c, k].map(m => ({ m, ch: changed(rowById.get(m.id)) }));
    const type = members[0].ch.block === members[1].ch.block ? 'same_diff' : 'mirrored';
    const sides = members.map(({ m, ch }) => [...new Set(m.citations.map(n => ch.sides.get(n)).filter(Boolean))].sort());
    const result = { sentences_equal: c.sentences.length === k.sentences.length,
      citations_exist: members.every(({ m, ch }) => m.citations.every(n => ch.sides.has(n))) };
    if (type === 'same_diff') result.citations_equal = isDeepStrictEqual(c.citations, k.citations);
    else result.sides_equal = sides[0].length > 0 && isDeepStrictEqual(sides[0], sides[1]);
    const ok = Object.values(result).every(Boolean);
    tally[type][0] += ok; tally[type][1]++; sameCount += result.sentences_equal;
    const [concern, clean] = members.map(({ m, ch }) => ({ id: m.id, citations: m.citations.map(n => ({ id: n, side: ch.sides.get(n) ?? null })) }));
    out.push({ pair, type, concern, clean, cited_sides: { concern: sides[0], clean: sides[1] }, ...result, pass: ok });
    if (!ok) fail(out.at(-1));
  }
  if (out.length !== 26) fail({ pairs: out.length, expected: 26 });
  const t = k => `${tally[k][0]}/${tally[k][1]}`;
  return { summary: `same_diff ${t('same_diff')} mirrored ${t('mirrored')} sentences ${sameCount}/26`, pairs: out };
}, { declared: 'post-factum after H8 measure defect, auditor ruling 2026-10-03' });

let hits = [];
check('H9', true, fail => {
  const rows = analyses(), pairs = byPair(rows);
  for (const r of rows) {
    const partner = pairs.get(r.pair).find(m => m.id !== r.id);
    FORBIDDEN.forEach((re, p) => {
      for (const m of r.analysis.matchAll(re)) {
        const key = `${r.id}:${p + 1}:${m[0]}`;
        hits.push({ key, id: r.id, pair: r.pair, pattern: re.source, match: m[0], analysis: r.analysis,
          partner_id: partner?.id ?? null, partner_analysis: partner?.analysis ?? null,
          adjudication: Object.hasOwn(adj, key) ? adj[key] : null });
      }
    });
  }
  for (const h of hits) if (h.adjudication?.verdict !== 'content') fail({ key: h.key, verdict: h.adjudication?.verdict ?? null });
  const keys = new Set(hits.map(h => h.key)), stale = Object.keys(adj).filter(k => !keys.has(k));
  for (const key of stale) fail({ key, error: 'stale adjudication' });
  const content = hits.filter(h => h.adjudication?.verdict === 'content').length;
  return { summary: `hits ${hits.length} content ${content} stale ${stale.length}`, hits: hits.length, content, stale };
});

let rows, pairs;
try { rows = analyses().map(({ analysis, ...r }) => r); } catch (e) { rows = [{ error: String(e) }]; }
try {
  pairs = [...byPair(analyses())].map(([pair, ms]) => {
    const [x, y] = ms, a = words(x.analysis), b = words(y.analysis), inter = [...a].filter(w => b.has(w)).length;
    return { pair, ids: ms.map(m => m.id), chars: ms.map(m => m.analysis.length),
      char_ratio: Math.min(x.analysis.length, y.analysis.length) / Math.max(x.analysis.length, y.analysis.length),
      word_jaccard: inter / (a.size + b.size - inter) };
  });
} catch (e) { pairs = [{ error: String(e) }]; }

const exit_code = checks.some(c => c.hard && c.status !== 'PASS') ? 1 : 0;
const report = { schema_version: 1, generated_by: 'training/acceptance/v6_check.mjs', inputs, checks, rows, pairs, h9_hits: hits, exit_code };
try { writeFileSync(opts.out, JSON.stringify(report, null, 2) + '\n'); } catch (e) { die(`${opts.out}: ${e.message}`); }
process.exit(exit_code);
