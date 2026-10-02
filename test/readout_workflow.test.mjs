import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, writeFileSync, mkdirSync, rmSync, existsSync, copyFileSync, chmodSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const helpers = path.join(repo, 'training/readout');
const archive = path.join(repo, 'training/results/2026-10-01-frozen-readout');
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const readJSON = filename => JSON.parse(readFileSync(filename, 'utf8'));
const readJSONL = filename => readFileSync(filename, 'utf8').trimEnd().split('\n').map(JSON.parse);
const writeJSONL = (filename, rows) => writeFileSync(filename, rows.map(x => JSON.stringify(x)).join('\n') + '\n');
const modes = [
  { name: 'python -O', argv: ['-O'], optimize: '0' },
  { name: 'PYTHONOPTIMIZE=1', argv: [], optimize: '1' },
];

function python(mode, args) {
  return spawnSync('python3', [...mode.argv, ...args], {
    cwd: repo, encoding: 'utf8', maxBuffer: 2 * 1024 * 1024,
    env: { ...process.env, PYTHONOPTIMIZE: mode.optimize, PYTHONDONTWRITEBYTECODE: '1' },
  });
}
function temporary(t) {
  const directory = mkdtempSync(path.join(tmpdir(), 'jovovich-readout-workflow-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  return directory;
}
function rejected(result, pattern = /ValueError:/) {
  assert.notEqual(result.status, 0, result.stdout);
  assert.match(result.stderr, pattern);
}
function summaryArgs(output, overrides = {}) {
  return [path.join(helpers, 'summarize_readout.py'),
    '--z', overrides.z ?? path.join(archive, 'state-fits.jsonl'),
    '--nuisance', path.join(archive, 'nuisance-fit-fits.jsonl'),
    '--rows', path.join(archive, 'readout-rows.json'),
    '--masks-json', path.join(archive, 'readout-masks.json'), '--output', output];
}

test('collector accepts documented repository helpers with an external scratch run', t => {
  const directory = temporary(t);
  const checkout = path.join(directory, 'repo');
  const reference = path.join(checkout, 'training/readout');
  const run = path.join(directory, 'scratch/run');
  mkdirSync(reference, { recursive: true });
  mkdirSync(run, { recursive: true });
  for (const name of ['run_readout.py', 'collect_readout.py']) {
    copyFileSync(path.join(helpers, name), path.join(reference, name));
  }
  const record = filename => {
    const bytes = readFileSync(filename);
    return { path: filename, sha256: sha(bytes), bytes: bytes.length };
  };
  const copied = filename => {
    const target = path.join(run, filename);
    copyFileSync(path.join(archive, filename), target);
    return record(target);
  };
  const originalReceipt = readJSON(path.join(archive, 'readout-run.json'));
  const phases = originalReceipt.phases.map(phase => ({
    name: phase.name, argv: ['fixture', phase.name], returncode: 0,
    stdout: copied(path.basename(phase.stdout.path)), stderr: copied(path.basename(phase.stderr.path)),
    created_files: phase.created_files.map(item => copied(path.basename(item.path))),
    missing_created_files: [],
  }));
  const plan = {
    protocol_frozen: true, parent_commit: 'fixture',
    model: { base_sha256: 'fixture-base', notorch_pin: 'fixture-substrate' },
    frozen_inputs: {
      'input:readout-input.bin': copied('readout-input.bin'),
      'parity-sft': copied('readout-sft.bin'),
      'helper:run_readout.py': record(path.join(reference, 'run_readout.py')),
    },
    execution: { phases: phases.map(phase => ({
      name: phase.name, argv: phase.argv, creates: phase.created_files.map(item => item.path),
    })) },
  };
  const planPath = path.join(directory, 'scratch/plan.json');
  writeFileSync(planPath, JSON.stringify(plan));
  writeFileSync(path.join(run, 'readout-run.json'), JSON.stringify({
    status: 'completed', all_frozen_inputs_unchanged: true, plan: record(planPath), phases,
  }));
  const output = path.join(directory, 'collected');
  const result = python(modes[0], [path.join(reference, 'collect_readout.py'),
    '--repo', checkout, '--reference', reference, '--run-dir', run, '--plan', planPath,
    '--summary', path.join(run, 'readout-summary.json'), '--output', output]);
  assert.equal(result.status, 0, result.stderr);
  const manifest = readJSON(path.join(output, 'manifest.json'));
  for (const name of ['readout-input.bin', 'readout-sft.bin']) {
    assert.deepEqual(readFileSync(path.join(output, name)), readFileSync(path.join(archive, name)));
    assert.equal(manifest.evidence[name].sha256, plan.frozen_inputs[name === 'readout-sft.bin' ? 'parity-sft' : `input:${name}`].sha256);
  }
  assert.ok(manifest.source_files['training/readout/run_readout.py']);
});

for (const mode of modes) {
  test(`${mode.name}: v4 preparation and summary retain archived results`, t => {
    const directory = temporary(t);
    const out = path.join(directory, 'prepared');
    const prepared = python(mode, [path.join(helpers, 'prepare_readout.py'), '--repo', repo, '--out', out]);
    assert.equal(prepared.status, 0, prepared.stderr);
    for (const name of ['readout-input.bin', 'readout-rows.json', 'readout-metadata.txt',
      'readout-masks.txt', 'readout-masks.json']) {
      assert.deepEqual(readFileSync(path.join(out, name)), readFileSync(path.join(archive, name)), name);
    }
    const completed = python(mode, [path.join(helpers, 'prepare_readout.py'), '--out', out,
      '--trace', path.join(archive, 'extract.stdout.jsonl')]);
    assert.equal(completed.status, 0, completed.stderr);
    for (const name of ['readout-nuisance.bin', 'readout-nuisance-metadata.txt', 'readout-nuisance.json']) {
      assert.deepEqual(readFileSync(path.join(out, name)), readFileSync(path.join(archive, name)), name);
    }
    const output = path.join(directory, 'summary.json');
    const summarized = python(mode, summaryArgs(output));
    assert.equal(summarized.status, 0, summarized.stderr);
    const actual = readJSON(output);
    const expected = readJSON(path.join(archive, 'readout-summary.json'));
    delete actual.sources;
    delete expected.sources;
    assert.deepEqual(actual, expected, 'Only source bindings change when auditing the same native predictions');
  });

  test(`${mode.name}: corpus fingerprint and nested structural checks cannot disappear`, t => {
    const directory = temporary(t);
    mkdirSync(path.join(directory, 'training'));
    const filename = path.join(directory, 'training/sft_review_v4.jsonl');
    const rows = readJSONL(path.join(repo, 'training/sft_review_v4.jsonl'));
    rows.find(r => r.kind === 'review').messages[2].role = 'user';
    writeJSONL(filename, rows);
    const out = path.join(directory, 'out');
    rejected(python(mode, [path.join(helpers, 'prepare_readout.py'), '--repo', directory, '--out', out]), /ValueError:.*CORPUS_SHA/);
    assert.equal(existsSync(out), false);
    // Supply the fixture's own fingerprint to reach the structural gate too.
    // This changes a test-local module constant, never the production source.
    rejected(python(mode, ['-c',
      'import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); import prepare_readout as p; p.CORPUS_SHA=p.digest(Path(sys.argv[2]).read_bytes()); p.prepare(Path(sys.argv[3]),Path(sys.argv[4]))',
      helpers, filename, directory, out]), /ValueError:.*role/);
    assert.equal(existsSync(out), false);
  });

  test(`${mode.name}: malformed native traces are rejected before writing nuisance data`, t => {
    const directory = temporary(t);
    const mutations = [
      rows => { rows[0].capture_position++; },
      rows => { rows[0].prefix_ids[0]++; },
      rows => { rows[0].input_ids[0] = -1; },
      rows => { rows[1].row = 0; },
    ];
    mutations.forEach((mutate, index) => {
      const out = path.join(directory, String(index));
      mkdirSync(out);
      writeFileSync(path.join(out, 'readout-rows.json'), readFileSync(path.join(archive, 'readout-rows.json')));
      const records = readJSONL(path.join(archive, 'extract.stdout.jsonl'));
      mutate(records);
      const trace = path.join(out, 'trace.jsonl');
      writeJSONL(trace, records);
      rejected(python(mode, [path.join(helpers, 'prepare_readout.py'), '--out', out, '--trace', trace]));
      assert.equal(existsSync(path.join(out, 'readout-nuisance.bin')), false);
    });
  });

  test(`${mode.name}: malformed native fits and transitive summary gates are rejected`, t => {
    const directory = temporary(t);
    const mutations = [
      rows => { rows.find(r => r.type === 'fit').converged = false; },
      rows => { rows.find(r => r.type === 'fit').predictions[0].label ^= 1; },
      rows => { rows.find(r => r.type === 'normalization').training_rows.pop(); },
      rows => { rows[0].lambda = 0.1; },
      rows => { const indices = rows.flatMap((r, i) => r.type === 'fit' ? [i] : []); rows[indices[1]] = rows[indices[0]]; },
    ];
    mutations.forEach((mutate, index) => {
      const rows = readJSONL(path.join(archive, 'state-fits.jsonl'));
      mutate(rows);
      const z = path.join(directory, `fits-${index}.jsonl`);
      writeJSONL(z, rows);
      const output = path.join(directory, `summary-${index}.json`);
      rejected(python(mode, summaryArgs(output, { z })));
      assert.equal(existsSync(output), false);
    });
    rejected(python(mode, ['-c',
      'import sys; sys.path.insert(0,sys.argv[1]); import summarize_readout as s; s.tail(0,[])', helpers]));
    rejected(python(mode, ['-c',
      'import sys; sys.path.insert(0,sys.argv[1]); import summarize_readout as s; p={"row":0,"prediction":0,"label":0}; s.counts([p,p],[])', helpers]));
  });

  test(`${mode.name}: runner retains partial hashes and requires every successful output`, t => {
    const directory = temporary(t);
    for (const scenario of [
      { name: 'partial-failure', code: 7, complete: false, status: 'failed' },
      { name: 'successful-process-missing-output', code: 0, complete: false, status: 'failed' },
      { name: 'all-outputs', code: 0, complete: true, status: 'completed' },
    ]) {
      const run = path.join(directory, scenario.name);
      mkdirSync(run);
      const partial = path.join(run, 'partial.jsonl');
      const second = path.join(run, 'second.jsonl');
      const body = 'partial native result\n';
      const program = [
        'import sys; from pathlib import Path',
        `Path(sys.argv[1]).write_text(${JSON.stringify(body)})`,
        scenario.complete ? 'Path(sys.argv[2]).write_text("complete\\n")' : 'pass',
        `sys.exit(${scenario.code})`,
      ].join('; ');
      const runner = path.join(helpers, 'run_readout.py');
      const bytes = readFileSync(runner);
      const plan = path.join(run, 'plan.json');
      writeFileSync(plan, JSON.stringify({
        protocol_frozen: true,
        frozen_inputs: { runner: { path: runner, sha256: sha(bytes), bytes: bytes.length } },
        execution: { cwd: repo, phases: [{ name: 'fixture',
          argv: ['python3', '-c', program, partial, second],
          stdout: path.join(run, 'stdout'), stderr: path.join(run, 'stderr'), creates: [partial, second] }] },
      }));
      const result = python(mode, [runner, '--plan', plan, '--output-dir', run]);
      if (scenario.status === 'failed') rejected(result);
      else assert.equal(result.status, 0, result.stderr);
      const receipt = readJSON(path.join(run, 'readout-run.json'));
      assert.equal(receipt.status, scenario.status);
      assert.equal(receipt.phases[0].returncode, scenario.code);
      assert.deepEqual(receipt.phases[0].created_files[0], { path: partial, sha256: sha(body), bytes: Buffer.byteLength(body) });
      assert.deepEqual(receipt.phases[0].missing_created_files, scenario.complete ? [] : [second]);
      assert.equal(receipt.phases[0].created_files.length, scenario.complete ? 2 : 1);
      if (scenario.code === 7) assert.match(receipt.failure, /phase failed/);
      if (scenario.name === 'successful-process-missing-output') assert.match(receipt.failure, /did not create declared files/);
    }
  });

  test(`${mode.name}: runner retains phase evidence when executable permission prevents launch`, t => {
    const run = temporary(t);
    const executable = path.join(run, 'not-executable');
    writeFileSync(executable, '#!/usr/bin/env python3\nraise RuntimeError("must not run")\n');
    chmodSync(executable, 0o644);
    const runner = path.join(helpers, 'run_readout.py');
    const bytes = readFileSync(runner);
    const output = path.join(run, 'declared-output.jsonl');
    const stdout = path.join(run, 'stdout');
    const stderr = path.join(run, 'stderr');
    const plan = path.join(run, 'plan.json');
    writeFileSync(plan, JSON.stringify({
      protocol_frozen: true,
      frozen_inputs: { runner: { path: runner, sha256: sha(bytes), bytes: bytes.length } },
      execution: { cwd: repo, phases: [{ name: 'cannot-launch', argv: [executable],
        stdout, stderr, creates: [output] }] },
    }));
    const result = python(mode, [runner, '--plan', plan, '--output-dir', run]);
    rejected(result, /PermissionError:/);
    const receipt = readJSON(path.join(run, 'readout-run.json'));
    assert.equal(receipt.status, 'failed');
    assert.equal(receipt.failure_type, 'PermissionError');
    assert.equal(receipt.phases.length, 1);
    const phase = receipt.phases[0];
    assert.equal(phase.name, 'cannot-launch');
    assert.deepEqual(phase.argv, [executable]);
    assert.equal(phase.failure_type, 'PermissionError');
    assert.equal(phase.failure, receipt.failure);
    assert.match(phase.failure, /Permission denied/);
    assert.ok(phase.elapsed_seconds >= 0);
    for (const key of ['returncode', 'peak_rss_kib', 'user_cpu_seconds', 'system_cpu_seconds']) {
      assert.equal(phase[key], null, `${key}: no child was launched`);
    }
    for (const [field, filename] of [['stdout', stdout], ['stderr', stderr]]) {
      assert.deepEqual(phase[field], { path: filename, sha256: sha(''), bytes: 0 });
      assert.equal(readFileSync(filename).length, 0);
    }
    assert.deepEqual(phase.missing_log_files, []);
    assert.deepEqual(phase.created_files, []);
    assert.deepEqual(phase.missing_created_files, [output]);
    assert.equal(existsSync(output), false);
  });

  test(`${mode.name}: runner retains stdout when opening stderr fails before launch`, t => {
    const run = temporary(t);
    const runner = path.join(helpers, 'run_readout.py');
    const bytes = readFileSync(runner);
    const output = path.join(run, 'declared-output.jsonl');
    const childRan = path.join(run, 'child-ran');
    const stdout = path.join(run, 'stdout');
    const stderr = path.join(run, 'stderr');
    const argv = ['python3', '-c',
      'import pathlib,sys; pathlib.Path(sys.argv[1]).write_text("ran"); pathlib.Path(sys.argv[2]).write_text("output")',
      childRan, output];
    const plan = path.join(run, 'plan.json');
    writeFileSync(plan, JSON.stringify({
      protocol_frozen: true,
      frozen_inputs: { runner: { path: runner, sha256: sha(bytes), bytes: bytes.length } },
      execution: { cwd: repo, phases: [
        // Create the obstruction after initial output-path validation, using
        // a real preceding phase rather than mocking the runner's file API.
        { name: 'create-stderr-directory', argv: ['python3', '-c',
          'import pathlib,sys; pathlib.Path(sys.argv[1]).mkdir()', stderr],
          stdout: path.join(run, 'setup.stdout'), stderr: path.join(run, 'setup.stderr'), creates: [] },
        { name: 'stderr-open-fails', argv, stdout, stderr, creates: [output] },
      ] },
    }));
    const result = python(mode, [runner, '--plan', plan, '--output-dir', run]);
    rejected(result, /FileExistsError:/);
    const receipt = readJSON(path.join(run, 'readout-run.json'));
    assert.equal(receipt.status, 'failed');
    assert.equal(receipt.failure_type, 'FileExistsError');
    assert.equal(receipt.phases.length, 2);
    assert.equal(receipt.phases[0].returncode, 0);
    const phase = receipt.phases[1];
    assert.equal(phase.name, 'stderr-open-fails');
    assert.deepEqual(phase.argv, argv);
    assert.equal(phase.failure_type, 'FileExistsError');
    assert.equal(phase.failure, receipt.failure);
    assert.match(phase.failure, /File exists/);
    assert.ok(phase.elapsed_seconds >= 0);
    for (const key of ['returncode', 'peak_rss_kib', 'user_cpu_seconds', 'system_cpu_seconds']) {
      assert.equal(phase[key], null, `${key}: no child was launched`);
    }
    assert.deepEqual(phase.stdout, { path: stdout, sha256: sha(''), bytes: 0 });
    assert.equal(readFileSync(stdout).length, 0);
    assert.equal(phase.stderr, null);
    assert.deepEqual(phase.missing_log_files, [stderr]);
    assert.deepEqual(phase.created_files, []);
    assert.deepEqual(phase.missing_created_files, [output]);
    assert.equal(existsSync(output), false);
    assert.equal(existsSync(childRan), false);
  });
}
