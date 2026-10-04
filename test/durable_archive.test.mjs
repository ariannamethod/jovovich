import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const fixture = path.join(repo, 'test/durable_archive_fixture.py');
const scenarios = [
  'normal', 'lost-ack', 'corrupt-remote', 'missing-remote', 'corrupt-readback',
  'local-loss', 'parent-conflict', 'unsafe-paths', 'source-mutation', 'privacy',
  'auth-redaction', 'sequence-gate', 'verification-barrier',
  'hf-transport-contract', 'hf-request-timeouts',
  'retry-transient', 'retry-commit', 'retry-terminal', 'retry-exhaustion',
  'retry-deadline', 'retry-immutable', 'retry-metadata',
  'runner-barrier', 'runner-lost-ack', 'runner-interrupted',
  'runner-preflight', 'runner-stale-output',
  'runner-symlink', 'runner-failed-work',
  'runner-validation-failure',
];

for (const scenario of scenarios) {
  test(`durable archive: ${scenario}`, () => {
    const result = spawnSync('python3', [fixture, scenario], {
      cwd: repo, encoding: 'utf8', timeout: 30_000,
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', PYTHONOPTIMIZE: '0' },
    });
    assert.equal(result.status, 0, result.stderr || result.error?.message);
    assert.deepEqual(JSON.parse(result.stdout), { scenario, passed: true, optimization: 0 });
  });
}

for (const mode of [
  { label: 'python -O', flags: ['-O'], optimize: '0' },
  { label: 'PYTHONOPTIMIZE=1', flags: [], optimize: '1' },
]) {
  test(`durable archive: verification survives ${mode.label}`, () => {
    for (const scenario of ['normal', 'corrupt-remote', 'unsafe-paths', 'privacy',
      'hf-transport-contract', 'hf-request-timeouts',
  'retry-transient', 'retry-commit', 'retry-terminal', 'retry-exhaustion',
  'retry-deadline', 'retry-immutable', 'retry-metadata', 'runner-barrier', 'runner-preflight']) {
      const result = spawnSync('python3', [...mode.flags, fixture, scenario], {
        cwd: repo, encoding: 'utf8', timeout: 30_000,
        env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', PYTHONOPTIMIZE: mode.optimize },
      });
      assert.equal(result.status, 0, `${scenario}: ${result.stderr || result.error?.message}`);
      assert.equal(JSON.parse(result.stdout).optimization, 1);
    }
  });
}
