/* Audit one native readout fit file and aggregate the prespecified counts.
 *
 * No fitting, normalization or model arithmetic happens here: the native solver
 * has already written every prediction. The definitions are the published
 * summarize_readout.py ones — correct rows, per-class recall, complete heldout
 * pairs, and the (1 + #{reference >= observed}) / 100 upper-tail fraction over
 * the 99 family-label permutations. The nuisance view is layer-independent and
 * is cited from the published record rather than refitted, so this reads one
 * view at a time and takes the feature width as an argument.
 *
 * Usage: node layer_summary.mjs --fits F --rows R --masks-json M --width N
 *                              --label TEXT [--output F]
 * Writes one JSON object; with no --output it goes to stdout as one line.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';

const argv = process.argv.slice(2);
const opts = {};
for (let i = 0; i < argv.length; i += 2) {
  if (!argv[i].startsWith('--') || i + 1 >= argv.length) fail(`bad argument: ${argv[i]}`);
  opts[argv[i].slice(2)] = argv[i + 1];
}
for (const key of ['fits', 'rows', 'masks-json', 'width', 'label']) if (!opts[key]) fail(`missing --${key}`);

function fail(message) { process.stderr.write(`layer-summary: ${message}\n`); process.exit(1); }
function require_(condition, message) { if (!condition) fail(message); }
function digest(path) { return createHash('sha256').update(readFileSync(path)).digest('hex'); }
/* Paths are recorded relative to the working directory: a receipt in a public
 * repository names files, not whose machine they sat on. */
function source(file) {
  const raw = readFileSync(file);
  return { path: path.relative(process.cwd(), file), sha256: createHash('sha256').update(raw).digest('hex'), bytes: raw.length };
}

const width = Number(opts.width);
require_(Number.isInteger(width) && width > 0, 'width must be a positive integer');
const rowdata = JSON.parse(readFileSync(opts.rows, 'utf8'));
const maskdata = JSON.parse(readFileSync(opts['masks-json'], 'utf8'));
const rows = rowdata.rows, masks = maskdata.masks;
require_(rows.length === 52 && rows.every((r, i) => r.index === i), 'rows must be the 52 frozen rows in order');
require_(masks.length === 99 && new Set(masks).size === 99, 'masks must be the 99 distinct frozen masks');
require_(masks.every(m => m.length === 20 && /^[01]+$/.test(m) && m.includes('1')), 'each mask is a 20-bit nonzero bitstring');
require_(JSON.stringify(rowdata.family_order) === JSON.stringify(maskdata.family_order), 'family order disagrees');

const records = readFileSync(opts.fits, 'utf8').split('\n').filter(l => l.length).map(l => JSON.parse(l));
require_(records.length === 2025, `expected 2025 records, read ${records.length}`);
const config = records[0], completion = records[records.length - 1];
require_(config.type === 'configuration' && completion.type === 'completion', 'first and last records must bound the run');
const expected = {
  rows: 52, width, families: 20, pairs: 26, permutations: 99, normalization: 'centered-rms',
  lambda: 0.01, interpolation_lambda: 1e-8, gradient_tolerance: 1e-8, max_iterations: 100,
  intercept_penalized: false, positive_class: 'concern', tie_class: 'clean',
  armijo_c1: 0.0001, maximum_halvings: 60, direction_curvature_floor: 1e-12
};
for (const [key, value] of Object.entries(expected))
  require_(config[key] === value, `configuration ${key}: ${JSON.stringify(config[key])} != ${JSON.stringify(value)}`);
require_(JSON.stringify(config.interpolation_mask_indices) === '[-1,0]', 'interpolation mask indices must be [-1,0]');
require_(completion.fits === 2002 && completion.failed_fits === 0 && completion.all_converged === true,
  `completion: ${JSON.stringify(completion)}`);

const fits = records.filter(r => r.type === 'fit');
const norms = records.filter(r => r.type === 'normalization');
require_(fits.length === 2002 && norms.length === 21, 'record mix must be 2002 fits and 21 normalizations');
require_(JSON.stringify(norms.map(n => n.heldout_family).sort((a, b) => a - b)) ===
  JSON.stringify([...Array(21)].map((_, i) => i - 1)), 'normalization folds must be -1..19');
for (const norm of norms) {
  const held = norm.heldout_family;
  const want = rows.filter(r => held < 0 || r.family_index !== held).map(r => r.index);
  require_(JSON.stringify(norm.training_rows) === JSON.stringify(want), `normalization fold ${held} training rows`);
  require_(norm.mean.length === width && norm.feature_population_std.length === width, 'normalization vector width');
  require_(norm.mean.every(Number.isFinite) && norm.feature_population_std.every(Number.isFinite), 'nonfinite normalization');
}

const byKey = new Map();
for (const fit of fits) {
  const key = `${fit.mode}|${fit.permutation}|${fit.heldout_family}`;
  require_(!byKey.has(key), `duplicate fit ${key}`);
  byKey.set(key, fit);
  require_(['heldout', 'interpolation'].includes(fit.mode) && fit.permutation >= -1 && fit.permutation < 99, `fit key ${key}`);
  require_(fit.converged === true && fit.gradient_inf <= 1e-8, `unconverged fit ${key}`);
  require_(fit.iterations >= 0 && fit.iterations <= 100, `iteration count ${key}`);
  require_(fit.lambda === (fit.mode === 'interpolation' ? 1e-8 : 0.01), `lambda ${key}`);
  const held = fit.heldout_family;
  require_(fit.train_rows === rows.filter(r => held < 0 || r.family_index !== held).length, `train rows ${key}`);
  for (const k of ['objective', 'train_ce', 'gradient_inf', 'penalty', 'weight_norm', 'global_rms'])
    require_(Number.isFinite(fit[k]), `nonfinite ${k} in ${key}`);
  const wanted = rows.filter(r => fit.mode === 'interpolation' || r.family_index === held);
  require_(JSON.stringify(fit.predictions.map(p => p.row)) === JSON.stringify(wanted.map(r => r.index)), `prediction rows ${key}`);
  fit.predictions.forEach((p, i) => {
    const row = wanted[i];
    require_(p.family === row.family_index && p.pair === row.pair_index, `prediction binding ${key} row ${p.row}`);
    require_(p.subset === (row.same_full_diff_subset ? 1 : 0), `subset binding ${key} row ${p.row}`);
    const flip = fit.permutation >= 0 ? Number(masks[fit.permutation][row.family_index]) : 0;
    require_(p.label === (row.label ^ flip), `label ${key} row ${p.row}`);
    require_(Number.isFinite(p.score) && p.probability >= 0 && p.probability <= 1, `score ${key} row ${p.row}`);
    require_(p.prediction === (p.score > 0 ? 1 : 0), `prediction rule ${key} row ${p.row}`);
  });
}
for (let permutation = -1; permutation < 99; permutation++)
  for (let family = 0; family < 20; family++)
    require_(byKey.has(`heldout|${permutation}|${family}`), `missing heldout fit ${permutation}/${family}`);
require_(byKey.has('interpolation|-1|-1') && byKey.has('interpolation|0|-1'), 'missing capacity fits');

function counts(predictions) {
  const sorted = [...predictions].sort((a, b) => a.row - b.row);
  require_(new Set(sorted.map(p => p.row)).size === sorted.length, 'repeated prediction row');
  const correct = new Map(sorted.map(p => [p.row, p.prediction === p.label]));
  const pairs = [...new Set(sorted.map(p => p.pair))].sort((a, b) => a - b);
  const members = new Map(pairs.map(pair => [pair, sorted.filter(p => p.pair === pair)]));
  for (const members_ of members.values())
    require_(members_.length === 2 && members_.map(p => p.label).sort().join() === '0,1', 'a pair must hold both labels');
  const complete = pairs.filter(pair => members.get(pair).every(p => correct.get(p.row)));
  const same = pairs.filter(pair => members.get(pair)[0].subset);
  return {
    rows: sorted.length,
    correct: sorted.filter(p => correct.get(p.row)).length,
    concern_rows: sorted.filter(p => p.label === 1).length,
    correct_concern: sorted.filter(p => p.label === 1 && correct.get(p.row)).length,
    clean_rows: sorted.filter(p => p.label === 0).length,
    correct_clean: sorted.filter(p => p.label === 0 && correct.get(p.row)).length,
    pairs: pairs.length, complete_pairs: complete.length, complete_pair_indices: complete,
    same_full_diff_pairs: same.length,
    same_full_diff_complete_pairs: same.filter(pair => complete.includes(pair)).length,
    exact_zero_score_rows: sorted.filter(p => p.score === 0).length
  };
}

const scores = [];
let observedPredictions = [];
for (let permutation = -1; permutation < 99; permutation++) {
  const predictions = [];
  for (let family = 0; family < 20; family++) predictions.push(...byKey.get(`heldout|${permutation}|${family}`).predictions);
  require_(predictions.map(p => p.row).sort((a, b) => a - b).join() === [...Array(52)].map((_, i) => i).join(),
    `fold union for permutation ${permutation}`);
  scores.push({ permutation, ...counts(predictions) });
  if (permutation === -1) observedPredictions = [...predictions].sort((a, b) => a.row - b.row);
}
const capacity = [-1, 0].map(permutation => {
  const fit = byKey.get(`interpolation|${permutation}|-1`);
  const item = counts(fit.predictions);
  require_(item.correct === fit.train_correct, 'capacity count disagrees with the solver');
  return { permutation, ...item, train_ce: fit.train_ce, gradient_inf: fit.gradient_inf,
           capacity_success: item.correct === 52 && fit.train_ce <= 0.001 };
});
const families = [...Array(20)].map((_, family) => ({
  family_index: family, family: rows.find(r => r.family_index === family).family,
  ...counts(byKey.get(`heldout|-1|${family}`).predictions)
}));

const observed = scores[0], reference = scores.slice(1).map(s => s.complete_pairs);
const exceeds = reference.filter(value => value >= observed.complete_pairs).length;
const report = {
  schema_version: 1,
  label: opts.label,
  width,
  observed,
  permutation_reference: {
    statistic: 'complete heldout concern/clean pairs, denominator 26',
    observed: observed.complete_pairs, reference_count: 99, reference_at_least_observed: exceeds,
    plus_one_upper_tail_fraction: (1 + exceeds) / 100,
    reference_minimum: Math.min(...reference), reference_maximum: Math.max(...reference),
    reference_statistics: reference,
    interpretation: 'Exploratory conditional family-label permutation reference; not confirmatory significance.'
  },
  correct_reference: (() => {
    const ref = scores.slice(1).map(s => s.correct);
    const over = ref.filter(value => value >= observed.correct).length;
    return { statistic: 'correct rows, denominator 52', observed: observed.correct, reference_count: 99,
             reference_at_least_observed: over, plus_one_upper_tail_fraction: (1 + over) / 100,
             reference_minimum: Math.min(...ref), reference_maximum: Math.max(...ref) };
  })(),
  capacity,
  family_breakdown: families,
  observed_predictions: observedPredictions,
  convergence: {
    fits: fits.length, all_converged: true,
    maximum_gradient_inf: Math.max(...fits.map(f => f.gradient_inf)),
    maximum_iterations: Math.max(...fits.map(f => f.iterations)),
    total_curvature_floors: fits.reduce((a, f) => a + f.curvature_floors, 0),
    total_line_search_backtracks: fits.reduce((a, f) => a + f.backtracks, 0)
  },
  configuration: config,
  completion,
  sources: [opts.fits, opts.rows, opts['masks-json'], new URL(import.meta.url).pathname].map(source)
};
const text = JSON.stringify(report);
if (opts.output) writeFileSync(opts.output, `${text}\n`, { flag: 'wx' });
else process.stdout.write(`${text}\n`);
process.stderr.write(`layer-summary ${opts.label}: correct ${observed.correct}/52 concern ${observed.correct_concern}/26 clean ${observed.correct_clean}/26 pairs ${observed.complete_pairs}/26 exceedance ${exceeds}/99 tail ${(1 + exceeds) / 100} fits_sha ${digest(opts.fits).slice(0, 12)}\n`);
