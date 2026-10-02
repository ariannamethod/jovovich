/* Run the per-layer readout for one body and leave the receipts behind.
 *
 * One native extraction captures every depth in a single forward pass per
 * sequence; one native fit per depth with the published solver arguments; one
 * audit per depth with the published counting rules. Every input and output is
 * hashed, every phase records its own return code taken directly, and nothing
 * is summarized that a later reader cannot recompute from the files named here.
 *
 * Usage: node run_layers.mjs --model M.gguf --prompts P.bin --metadata M.txt
 *          --masks M.txt --masks-json M.json --rows R.json --width N
 *          --out DIR --label NAME [--threads 4]
 */
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, readdirSync, writeFileSync, statSync } from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const opts = {};
for (let i = 0; i < argv.length; i += 2) {
  if (!argv[i].startsWith('--') || i + 1 >= argv.length) fail(`bad argument: ${argv[i]}`);
  opts[argv[i].slice(2)] = argv[i + 1];
}
for (const key of ['model', 'prompts', 'metadata', 'masks', 'masks-json', 'rows', 'width', 'out', 'label'])
  if (!opts[key]) fail(`missing --${key}`);
const threads = opts.threads || '4';

function fail(message) { process.stderr.write(`run-layers: ${message}\n`); process.exit(1); }
/* Paths are recorded relative to the working directory: a receipt in a public
 * repository names files, not whose machine they sat on. */
function receipt(file) {
  const raw = readFileSync(file);
  return { path: path.relative(process.cwd(), file), sha256: createHash('sha256').update(raw).digest('hex'), bytes: raw.length };
}
function phase(name, command, args, { stdout, stderr, env }) {
  const started = Date.now();
  const result = spawnSync(command, args, { env: { ...process.env, ...env } });
  if (result.error) fail(`${name}: ${result.error.message}`);
  if (stdout) writeFileSync(stdout, result.stdout);
  if (stderr) writeFileSync(stderr, result.stderr);
  const record = { name, argv: [command, ...args], rc: result.status, elapsed_seconds: (Date.now() - started) / 1000 };
  if (result.status !== 0) {
    writeFileSync(path.join(opts.out, 'incomplete.json'), `${JSON.stringify({ failed: record }, null, 2)}\n`);
    fail(`${name} returned ${result.status}; evidence kept in ${opts.out}`);
  }
  return record;
}

mkdirSync(path.join(opts.out, 'features'), { recursive: true });
mkdirSync(path.join(opts.out, 'fits'), { recursive: true });
mkdirSync(path.join(opts.out, 'summaries'), { recursive: true });
const started = new Date().toISOString();
const inputs = {
  model: receipt(opts.model), prompts: receipt(opts.prompts), metadata: receipt(opts.metadata),
  masks: receipt(opts.masks), 'masks-json': receipt(opts['masks-json']), rows: receipt(opts.rows),
  'binary:extract-layers': receipt('build/jovovich-extract-layers'),
  'binary:readout-fit': receipt('build/jovovich-readout-fit'),
  'helper:layer_summary.mjs': receipt('training/readout/layer_summary.mjs'),
  'helper:run_layers.mjs': receipt('training/readout/run_layers.mjs')
};

/* --reuse-extraction points at a features directory this runner already wrote.
 * The matrices are content-addressed in the manifest either way, so a reader
 * verifies them by hash rather than by trusting which process produced them;
 * what this buys is a second pass over an extraction that cost an hour. */
const phases = [];
if (opts['reuse-extraction']) {
  const from = opts['reuse-extraction'];
  for (const file of readdirSync(from)) {
    if (!file.endsWith('.bin')) continue;
    writeFileSync(path.join(opts.out, 'features', file), readFileSync(path.join(from, file)), { flag: 'wx' });
  }
  for (const side of ['extract.stdout.jsonl', 'extract.stderr.txt'])
    writeFileSync(path.join(opts.out, side), readFileSync(path.join(path.dirname(from), side)), { flag: 'wx' });
  phases.push({ name: 'extract', reused_from_an_earlier_run_of_this_runner: true,
                argv: ['build/jovovich-extract-layers', opts.model, opts.prompts, '<features>', threads],
                rc: 0, elapsed_seconds: null });
} else {
  phases.push(phase('extract', 'build/jovovich-extract-layers',
    [opts.model, opts.prompts, path.join(opts.out, 'features'), threads], {
      stdout: path.join(opts.out, 'extract.stdout.jsonl'),
      stderr: path.join(opts.out, 'extract.stderr.txt'),
      env: { NT_NO_I8: '1', NT_QMV_THREADS: threads, NT_ATTN_THREADS: threads, NT_SIMD_THREADS: threads }
    }));
}

const depths = readdirSync(path.join(opts.out, 'features')).filter(f => f.endsWith('.bin')).sort()
  .map(f => f.replace(/^features-/, '').replace(/\.bin$/, ''));
if (!depths.length) fail('extraction produced no feature matrices');

const table = [];
for (const depth of depths) {
  const matrix = path.join(opts.out, 'features', `features-${depth}.bin`);
  const fits = path.join(opts.out, 'fits', `${depth}.fits.jsonl`);
  phases.push(phase(`fit:${depth}`, 'build/jovovich-readout-fit', [
    '--matrix', matrix, '--metadata', opts.metadata, '--masks', opts.masks, '--output', fits,
    '--normalization', 'centered-rms', '--lambda', '0.01', '--interpolation-lambda', '1e-8',
    '--gradient-tolerance', '1e-8', '--max-iterations', '100'
  ], { stdout: path.join(opts.out, 'fits', `${depth}.stdout.txt`), stderr: path.join(opts.out, 'fits', `${depth}.stderr.txt`) }));
  const summary = path.join(opts.out, 'summaries', `${depth}.json`);
  phases.push(phase(`summary:${depth}`, process.execPath, [
    'training/readout/layer_summary.mjs', '--fits', fits, '--rows', opts.rows,
    '--masks-json', opts['masks-json'], '--width', opts.width, '--label', `${opts.label}:${depth}`,
    '--output', summary
  ], { stderr: path.join(opts.out, 'summaries', `${depth}.stderr.txt`) }));
  const report = JSON.parse(readFileSync(summary, 'utf8'));
  const raw = readFileSync(matrix);
  const rowCount = raw.readUInt32LE(8), rowWidth = raw.readUInt32LE(12);
  const rowHashes = new Set();
  for (let r = 0; r < rowCount; r++)
    rowHashes.add(createHash('sha256').update(raw.subarray(16 + r * rowWidth * 4, 16 + (r + 1) * rowWidth * 4)).digest('hex'));
  table.push({
    body: opts.label, depth,
    distinct_feature_rows: rowHashes.size,
    correct: report.observed.correct, correct_concern: report.observed.correct_concern,
    correct_clean: report.observed.correct_clean, complete_pairs: report.observed.complete_pairs,
    permutation_reference_at_least_observed: report.permutation_reference.reference_at_least_observed,
    permutation_exceedance: report.permutation_reference.plus_one_upper_tail_fraction,
    permutation_reference_maximum: report.permutation_reference.reference_maximum,
    active_columns_minimum: Math.min(...readFileSync(fits, 'utf8').split('\n').filter(l => l.length)
      .map(line => JSON.parse(line)).filter(r => r.type === 'fit').map(r => r.active_columns)),
    maximum_gradient_inf: report.convergence.maximum_gradient_inf,
    maximum_iterations: report.convergence.maximum_iterations,
    capacity_correct: report.capacity[0].correct, capacity_train_ce: report.capacity[0].train_ce
  });
}

const outputs = {};
for (const depth of depths) {
  outputs[`features:${depth}`] = receipt(path.join(opts.out, 'features', `features-${depth}.bin`));
  outputs[`fits:${depth}`] = receipt(path.join(opts.out, 'fits', `${depth}.fits.jsonl`));
  outputs[`summary:${depth}`] = receipt(path.join(opts.out, 'summaries', `${depth}.json`));
}
outputs['extract.stdout.jsonl'] = receipt(path.join(opts.out, 'extract.stdout.jsonl'));

const manifest = {
  schema_version: 1, label: opts.label, started_at_utc: started, finished_at_utc: new Date().toISOString(),
  repository: path.basename(process.cwd()), threads, width: Number(opts.width), depths,
  solver: {
    normalization: 'centered-rms', lambda: 0.01, interpolation_lambda: 1e-8,
    gradient_tolerance: 1e-8, max_iterations: 100, intercept_penalized: false,
    positive_class: 'concern', permutations: 99
  },
  environment: {
    node: process.version, platform: `${process.platform} ${process.arch}`,
    NT_NO_I8: '1', NT_QMV_THREADS: threads, NT_ATTN_THREADS: threads, NT_SIMD_THREADS: threads
  },
  inputs, outputs, phases, table
};
writeFileSync(path.join(opts.out, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`, { flag: 'wx' });
writeFileSync(path.join(opts.out, 'table.json'), `${JSON.stringify(table, null, 2)}\n`, { flag: 'wx' });
process.stderr.write(`run-layers ${opts.label}: ${depths.length} depths, ${statSync(path.join(opts.out, 'manifest.json')).size} bytes of manifest\n`);
for (const row of table)
  process.stderr.write(`  ${row.depth}: correct ${row.correct}/52 concern ${row.correct_concern}/26 clean ${row.correct_clean}/26 pairs ${row.complete_pairs}/26 exceedance ${row.permutation_exceedance}\n`);
