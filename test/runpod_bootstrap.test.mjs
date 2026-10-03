import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
test('Runpod watchdog: own-pod API, credential isolation, deadline, and failure cleanup', { timeout: 30_000 }, () => {
  const result = spawnSync('python3', ['test/runpod_bootstrap_fixture.py'], {
    cwd: repo, encoding: 'utf8', timeout: 25_000,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
  });
  assert.equal(result.status, 0, result.stderr || result.error?.message);
  assert.deepEqual(JSON.parse(result.stdout.trim()), { passed: true, tests: 15, network_calls: 0 });
});
