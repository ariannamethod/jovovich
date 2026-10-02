/* The parity gate for the per-layer audit: this summarizer against the
 * published 2026-10-01 frozen-readout summary, field by field, on the same
 * state-fits.jsonl. Equality here is what licenses the phrase "the published
 * procedure" for every per-layer row; a single unequal field fails the run.
 *
 * Usage: node compare_published.mjs --mine S.json --published readout-summary.json
 *                                   [--output F]
 * Returns 0 when every compared field is equal, 2 when any differs.
 */
import { readFileSync, writeFileSync } from 'node:fs';

const argv = process.argv.slice(2);
const opts = {};
for (let i = 0; i < argv.length; i += 2) opts[argv[i].replace(/^--/, '')] = argv[i + 1];
if (!opts.mine || !opts.published) {
  process.stderr.write('compare-published: need --mine and --published\n');
  process.exit(1);
}
const mine = JSON.parse(readFileSync(opts.mine, 'utf8'));
const theirs = JSON.parse(readFileSync(opts.published, 'utf8')).views.z;
const theirTail = JSON.parse(readFileSync(opts.published, 'utf8')).permutation_references.z_complete_pairs;

const checks = [];
const same = (name, a, b) => checks.push({ field: name, mine: a, published: b, equal: JSON.stringify(a) === JSON.stringify(b) });
for (const key of ['rows', 'correct', 'concern_rows', 'correct_concern', 'clean_rows', 'correct_clean',
                   'pairs', 'complete_pairs', 'complete_pair_indices', 'same_full_diff_pairs',
                   'same_full_diff_complete_pairs', 'exact_zero_score_rows'])
  same(`observed.${key}`, mine.observed[key], theirs.observed[key]);
for (const key of ['observed', 'reference_count', 'reference_at_least_observed',
                   'plus_one_upper_tail_fraction', 'reference_minimum', 'reference_maximum',
                   'reference_statistics'])
  same(`permutation_reference.${key}`, mine.permutation_reference[key], theirTail[key]);
for (const key of ['fits', 'maximum_gradient_inf', 'maximum_iterations',
                   'total_curvature_floors', 'total_line_search_backtracks'])
  same(`convergence.${key}`, mine.convergence[key], theirs.convergence[key]);
same('observed_predictions', mine.observed_predictions, theirs.observed_predictions);
same('family_breakdown', mine.family_breakdown.map(f => [f.family_index, f.family, f.correct, f.complete_pairs]),
     theirs.family_breakdown.map(f => [f.family_index, f.family, f.correct, f.complete_pairs]));
same('capacity', mine.capacity.map(c => [c.permutation, c.correct, c.train_ce, c.capacity_success]),
     theirs.capacity.map(c => [c.permutation, c.correct, c.train_ce, c.capacity_success]));

const unequal = checks.filter(c => !c.equal);
const report = {
  schema_version: 1,
  gate: 'per-layer audit reproduces the published frozen-readout z summary',
  mine: opts.mine, published: opts.published,
  compared_fields: checks.length, unequal_fields: unequal.length,
  all_equal: unequal.length === 0,
  unequal, checks: checks.map(c => ({ field: c.field, equal: c.equal }))
};
if (opts.output) writeFileSync(opts.output, `${JSON.stringify(report, null, 2)}\n`, { flag: 'wx' });
process.stderr.write(`compare-published: ${checks.length - unequal.length}/${checks.length} fields equal\n`);
for (const c of unequal) process.stderr.write(`  differs: ${c.field}\n`);
process.exit(unequal.length ? 2 : 0);
