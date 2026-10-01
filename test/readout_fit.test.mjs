import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

function fixture(run) {
  const directory = mkdtempSync(join(tmpdir(), 'jovovich-readout-test-'));
  const matrix = join(directory, 'matrix.jvrf');
  const metadata = join(directory, 'metadata.txt');
  const masks = join(directory, 'masks.txt');
  const values = Array.from({ length: 8 }, (_, row) => [
    (row % 2 ? 1 : -1) + row / 20,
    Math.sin(row),
    10,
  ]);
  const bytes = Buffer.alloc(16 + 8 * 3 * 4);
  bytes.write('JVRF1'); bytes.writeUInt32LE(8, 8); bytes.writeUInt32LE(3, 12);
  values.flat().forEach((value, i) => bytes.writeFloatLE(value, 16 + 4 * i));
  writeFileSync(matrix, bytes);
  const rows = Array.from({ length: 8 }, (_, row) => `${row % 2} ${row >> 1} ${row >> 1} ${row < 2 ? 1 : 0}`);
  writeFileSync(metadata, `JOVOVICH_READOUT_V1\n8 3 4 4\n${rows.join('\n')}\n`);
  writeFileSync(masks, 'JOVOVICH_MASKS_V1\n3 4\n1000\n0101\n1111\n');
  let invocation = 0;
  const execute = (extra = [], fixedOutput) => {
    const output = fixedOutput || join(directory, `output-${invocation++}.jsonl`);
    const result = spawnSync('build/jovovich-readout-fit', [
      '--matrix', matrix, '--metadata', metadata, '--masks', masks,
      '--output', output, '--normalization', 'per-feature-rms', ...extra,
    ], { encoding: 'utf8' });
    return { ...result, output };
  };
  try { run({ directory, matrix, metadata, masks, execute, bytes, rows }); }
  finally { rmSync(directory, { recursive: true, force: true }); }
}

test('native readout applies every family mask to complete pairs, keeps held-out rows out of statistics, and exports no coefficients', () => {
  fixture(({ execute }) => {
    const result = execute();
    assert.equal(result.status, 0, result.stderr);
    const records = readFileSync(result.output, 'utf8').trim().split('\n').map(JSON.parse);
    const config = records[0];
    assert.equal(config.tie_class, 'clean');
    assert.equal(config.intercept_penalized, false);
    assert.deepEqual(config.interpolation_mask_indices, [-1, 0]);
    const fits = records.filter(record => record.type === 'fit');
    assert.equal(fits.length, 18); // 4 folds * (observed + 3 masks) + 2 capacity fits.
    const normalizations = records.filter(record => record.type === 'normalization');
    assert.equal(normalizations.length, 5);
    for (const normalization of normalizations) {
      assert.equal(normalization.active_columns, 2);
      assert.equal(normalization.feature_population_std[2], 0);
      const expected = Array.from({ length: 8 }, (_, row) => row)
        .filter(row => (row >> 1) !== normalization.heldout_family);
      assert.deepEqual(normalization.training_rows, expected);
    }
    const maskBits = [null, '1000', '0101', '1111'];
    for (const fit of fits) {
      assert.equal(fit.converged, true);
      assert.ok(fit.gradient_inf <= config.gradient_tolerance);
      assert.equal('w' in fit || 'weights' in fit || 'bias' in fit || 'intercept' in fit, false);
      assert.ok(Math.abs(fit.objective - fit.train_ce - fit.penalty) < 1e-14);
      assert.equal(fit.predictions.length, fit.mode === 'interpolation' ? 8 : 2);
      for (const prediction of fit.predictions) {
        const bits = maskBits[fit.permutation + 1];
        assert.equal(prediction.label, (prediction.row % 2) ^ (bits ? Number(bits[prediction.family]) : 0));
        assert.equal(prediction.prediction, Number(prediction.score > 0));
        if (fit.mode === 'heldout') assert.equal(prediction.family, fit.heldout_family);
      }
    }
    assert.deepEqual(records.at(-1), { type: 'completion', fits: 18, failed_fits: 0, all_converged: true });
    const original = readFileSync(result.output);
    const overwrite = execute([], result.output);
    assert.equal(overwrite.status, 1);
    assert.match(overwrite.stderr, /exclusively create/);
    assert.deepEqual(readFileSync(result.output), original);
  });
});

test('native readout reports incomplete optimization as a failed gate without dropping fits', () => {
  fixture(({ execute }) => {
    const result = execute(['--max-iterations', '1']);
    assert.equal(result.status, 2, result.stderr);
    const records = readFileSync(result.output, 'utf8').trim().split('\n').map(JSON.parse);
    const fits = records.filter(record => record.type === 'fit');
    assert.equal(fits.length, 18);
    const failed = fits.filter(fit => !fit.converged);
    assert.ok(failed.length > 0);
    assert.deepEqual(records.at(-1), {
      type: 'completion', fits: 18, failed_fits: failed.length, all_converged: false,
    });
    for (const fit of failed) assert.ok(fit.gradient_inf > 1e-8);
  });
});

test('native readout rejects broken pairs, duplicated or identity masks, nonfinite and trailing matrix data', () => {
  fixture(({ matrix, metadata, masks, execute, bytes, rows }) => {
    for (const [contents, pattern] of [
      ['JOVOVICH_MASKS_V1\n1 4\n0000\n', /identity mask/],
      ['JOVOVICH_MASKS_V1\n2 4\n0010\n0010\n', /duplicate/],
      ['JOVOVICH_MASKS_V1\n1 4\n00100\n', /too long/],
    ]) {
      writeFileSync(masks, contents);
      const result = execute(); assert.equal(result.status, 1); assert.match(result.stderr, pattern);
    }
    writeFileSync(masks, 'JOVOVICH_MASKS_V1\n1 4\n1000\n');
    const broken = [...rows]; broken[1] = '0 0 0 1';
    writeFileSync(metadata, `JOVOVICH_READOUT_V1\n8 3 4 4\n${broken.join('\n')}\n`);
    let result = execute(); assert.equal(result.status, 1); assert.match(result.stderr, /opposite labels/);
    writeFileSync(metadata, `JOVOVICH_READOUT_V1\n8 3 4 4\n${rows.join('\n')}\n`);
    const nonfinite = Buffer.from(bytes); nonfinite.writeFloatLE(NaN, 16);
    writeFileSync(matrix, nonfinite);
    result = execute(); assert.equal(result.status, 1); assert.match(result.stderr, /nonfinite feature/);
    writeFileSync(matrix, Buffer.concat([bytes, Buffer.from([0])]));
    result = execute(); assert.equal(result.status, 1); assert.match(result.stderr, /trailing input/);
  });
});
