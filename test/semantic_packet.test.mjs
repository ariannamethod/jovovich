import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

test('semantic packets validate synthetic recovered evidence and keep reviewers blinded', { timeout: 120000 }, () => {
  const result = spawnSync('python3', ['test/semantic_packet_test.py'], {
    encoding: 'utf8', timeout: 110000,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
  });
  assert.equal(result.status, 0, result.stderr || result.stdout || String(result.error));
  assert.match(result.stderr, /Ran 10 tests/);
});
