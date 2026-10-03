import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
test('checkpoint archive gate: actual native Chuck trajectory, readback failures, ACK protocol', { timeout: 180_000 }, () => {
  const result = spawnSync('python3', ['test/checkpoint_archive_gate_fixture.py'], {
    cwd: repo, encoding: 'utf8', timeout: 170_000,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', PYTHONOPTIMIZE: '0' },
  });
  assert.equal(result.status, 0, result.stderr || result.error?.message);
  assert.deepEqual(JSON.parse(result.stdout.trim().split('\n').at(-1)), {
    passed: true, native_updates: 8, bitwise_trajectory_match: true,
    verified_units: 11, fault_scenarios: 22, initial_adapter_match: true,
    scorer_metrics_preserved: true,
  });
});
