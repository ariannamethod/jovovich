/* Assemble the one combined table: every body against every depth, with the
 * declared reading applied as a comparison rather than a judgement. No body and
 * no depth is dropped, including the depths that read as empty — a table with
 * the empty rows removed is a different claim from the one that was frozen.
 *
 * Usage: node layer_table.mjs --plan plan.json --table LABEL=path/to/table.json
 *          [--table ...] --output-json F --output-md F
 */
import { readFileSync, writeFileSync } from 'node:fs';

const argv = process.argv.slice(2);
const opts = { table: [] };
for (let i = 0; i < argv.length; i += 2) {
  const key = argv[i].replace(/^--/, ''), value = argv[i + 1];
  if (key === 'table') opts.table.push(value); else opts[key] = value;
}
if (!opts.plan || !opts.table.length || !opts['output-json'] || !opts['output-md']) {
  process.stderr.write('layer-table: need --plan, at least one --table LABEL=path, --output-json and --output-md\n');
  process.exit(1);
}
const plan = JSON.parse(readFileSync(opts.plan, 'utf8'));
const floorCorrect = plan.declared_reading.floor_correct;
const floorPairs = plan.declared_reading.floor_complete_pairs;
/* The seven-feature lexical baseline from the published record. It is
 * layer-independent and is not refitted here, but a depth that does not beat it
 * has not shown anything a token counter could not. */
const nuisance = { correct: 35, complete_pairs: 9,
  source: 'training/results/2026-10-01-frozen-readout/readout-summary.json, views.nuisance.observed' };

const rows = [];
for (const spec of opts.table) {
  const split = spec.indexOf('=');
  const label = spec.slice(0, split), file = spec.slice(split + 1);
  for (const row of JSON.parse(readFileSync(file, 'utf8')))
    rows.push({ ...row, body: label,
      cleared: row.correct > floorCorrect && row.complete_pairs > floorPairs,
      above_published_nuisance: row.correct > nuisance.correct && row.complete_pairs > nuisance.complete_pairs });
}
const bodies = [...new Set(rows.map(r => r.body))];
const perBody = bodies.map(body => {
  const mine = rows.filter(r => r.body === body);
  const cleared = mine.filter(r => r.cleared).map(r => r.depth);
  const best = mine.reduce((a, b) => (b.correct > a.correct || (b.correct === a.correct && b.complete_pairs > a.complete_pairs) ? b : a));
  return {
    body, depths: mine.length, cleared_depths: cleared, any_depth_cleared: cleared.length > 0,
    best_depth: best.depth, best_correct: best.correct, best_complete_pairs: best.complete_pairs,
    best_exceedance: best.permutation_exceedance,
    maximum_complete_pairs: Math.max(...mine.map(r => r.complete_pairs)),
    minimum_exceedance: Math.min(...mine.map(r => r.permutation_exceedance)),
    all_converged: mine.every(r => r.maximum_gradient_inf <= 1e-8)
  };
});

const report = {
  schema_version: 1,
  plan: opts.plan, plan_sha256_note: 'hashed in the run manifests; this file is derived from the per-body tables only',
  declared_reading: plan.declared_reading.statement,
  floor: { correct: floorCorrect, complete_pairs: floorPairs },
  published_nuisance_baseline: nuisance,
  bodies: perBody,
  rows,
  depths_cleared: rows.filter(r => r.cleared).length,
  depths_total: rows.length,
  depths_above_published_nuisance: rows.filter(r => r.above_published_nuisance).length,
  null_result: !perBody.some(b => b.any_depth_cleared),
  multiplicity: `the declared reading was fixed per depth and carries no multiplicity rule; it is applied here to ${rows.length} body-depth cells, so an exceedance near 0.01 is expected to appear about once by chance alone`,
  caveat: plan.limits[1]
};
writeFileSync(opts['output-json'], `${JSON.stringify(report, null, 2)}\n`, { flag: 'wx' });

const md = [];
md.push('| body | depth | correct/52 | concern/26 | clean/26 | pairs/26 | exceedance | reading |');
md.push('| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |');
for (const r of rows)
  md.push(`| ${r.body} | ${r.depth} | ${r.correct} | ${r.correct_concern} | ${r.correct_clean} | ${r.complete_pairs} | ${r.permutation_exceedance} | ${r.cleared ? 'cleared' : 'below the floor'} |`);
md.push('');
md.push(`Declared reading: ${plan.declared_reading.statement}. The floor is ${floorCorrect}/52 and ${floorPairs}/26.`);
md.push('');
md.push(`${rows.filter(r => r.cleared).length} of ${rows.length} body-depth cells clear that floor. The published seven-feature lexical baseline reached ${nuisance.correct}/52 and ${nuisance.complete_pairs}/26 on the same corpus; ${rows.filter(r => r.above_published_nuisance).length} of ${rows.length} cells are above it.`);
md.push('');
md.push('| body | depths | depths cleared | best depth | best correct/52 | best pairs/26 | lowest exceedance |');
md.push('| --- | ---: | --- | --- | ---: | ---: | ---: |');
for (const b of perBody)
  md.push(`| ${b.body} | ${b.depths} | ${b.cleared_depths.length ? b.cleared_depths.join(', ') : 'none' } | ${b.best_depth} | ${b.best_correct} | ${b.best_complete_pairs} | ${b.minimum_exceedance} |`);
writeFileSync(opts['output-md'], `${md.join('\n')}\n`, { flag: 'wx' });
process.stderr.write(`layer-table: ${rows.length} rows, ${perBody.filter(b => b.any_depth_cleared).length}/${perBody.length} bodies with a cleared depth\n`);
for (const b of perBody)
  process.stderr.write(`  ${b.body}: cleared ${b.cleared_depths.length ? b.cleared_depths.join(',') : 'none'}; best ${b.best_depth} ${b.best_correct}/52 ${b.best_complete_pairs}/26 exceedance ${b.best_exceedance}\n`);
