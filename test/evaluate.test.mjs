import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

test('SFT exact match requires raw equality, successful execution, and EOS', t => {
  const dir = mkdtempSync(path.join(tmpdir(), 'jovovich-evaluate-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const model = path.join(dir, 'fixture.gguf');
  const cases = path.join(dir, 'cases.jsonl');
  const runner = path.join(dir, 'runner.cjs');
  const output = path.join(dir, 'results.jsonl');
  const names = ['exact', 'whitespace', 'limit', 'unknown', 'failed'];
  writeFileSync(model, 'unused model fixture');
  writeFileSync(cases, names.map(name => JSON.stringify({ id: name, messages: [
    { role: 'system', content: `system for ${name}` },
    { role: 'user', content: name },
    { role: 'assistant', content: 'expected' }
  ] })).join('\n') + '\n');
  writeFileSync(runner, `#!/usr/bin/env node
const fs = require('node:fs');
const prompt = fs.readFileSync(0, 'utf8');
const name = /<\\|im_start\\|>user\\n(.*?)<\\|im_end\\|>/.exec(prompt)[1];
if (!prompt.includes('system\\nsystem for ' + name + '<|im_end|>')) process.exit(9);
process.stdout.write(name === 'whitespace' ? ' expected\\n' : 'expected');
if (name !== 'unknown') process.stderr.write('jovovich: prefill 0 ms, generated 1 tokens in 0 ms, stop=' + (name === 'limit' ? 'token-limit' : 'eos') + '\\n');
process.exitCode = name === 'failed' ? 7 : 0;
`, { mode: 0o755 });
  const result = spawnSync('python3', ['training/evaluate.py', model,
    '--sft', cases, '--runner', runner, '--output', output], { encoding: 'utf8' });
  assert.equal(result.status, 7, result.stderr);
  const rows = readFileSync(output, 'utf8').trim().split('\n').map(JSON.parse);
  assert.deepEqual(rows.map(row => row.name), names);
  assert.deepEqual(rows.map(row => row.exact_match), [true, false, false, false, false]);
  assert.deepEqual(rows.map(row => row.normalized_text_match), names.map(() => true));
  assert.equal(rows[1].response, ' expected\n');
  assert.equal(rows[2].stop_reason, 'token-limit');
  assert.equal(rows[3].stop_reason, null);
  assert.equal(rows[4].returncode, 7);
});
