import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const u32 = n => { const b = Buffer.alloc(4); b.writeUInt32LE(n); return b; };
const u64 = n => { const b = Buffer.alloc(8); b.writeBigUInt64LE(BigInt(n)); return b; };
const text = s => { const b = Buffer.from(s); return Buffer.concat([u64(b.length), b]); };
const stringKV = (key, value) => Buffer.concat([text(key), u32(8), text(value)]);
const uintKV = (key, value) => Buffer.concat([text(key), u32(4), u32(value)]);
const arrayKV = (key, type, values) => Buffer.concat([text(key), u32(9), u32(type), u64(values.length), ...values]);

/* A byte vocabulary with CONTROL markers, requiring no downloaded model.
 * This reproduces the actual Qwen contract: bpe_encode treats CONTROL
 * spellings literally; the chat caller must insert their token IDs. */
function fixture(file) {
  let extra = 0;
  const vocab = Array.from({ length: 256 }, (_, byte) => {
    const visible = (byte >= 33 && byte <= 126) || (byte >= 161 && byte <= 172) || byte >= 174;
    return String.fromCodePoint(visible ? byte : 256 + extra++);
  });
  vocab.push('<|im_start|>', '<|im_end|>', '<|endoftext|>');
  const kv = [
    stringKV('general.architecture', 'qwen2'),
    uintKV('qwen2.context_length', 32768),
    stringKV('tokenizer.ggml.model', 'gpt2'),
    stringKV('tokenizer.ggml.pre', 'qwen2'),
    arrayKV('tokenizer.ggml.tokens', 8, vocab.map(text)),
    arrayKV('tokenizer.ggml.token_type', 4, vocab.map((_, i) => u32(i < 256 ? 1 : 3))),
    arrayKV('tokenizer.ggml.merges', 8, []),
    uintKV('tokenizer.ggml.eos_token_id', 257),
    Buffer.concat([text('tokenizer.ggml.add_bos_token'), u32(7), Buffer.from([0])])
  ];
  const directory = Buffer.concat([text('token_embd.weight'), u32(2), u64(1), u64(vocab.length), u32(0), u64(0)]);
  const header = Buffer.concat([Buffer.from('GGUF'), u32(3), u64(1), u64(kv.length), ...kv, directory]);
  writeFileSync(file, Buffer.concat([header, Buffer.alloc((32 - header.length % 32) % 32), Buffer.alloc(vocab.length * 4)]));
}

test('runner inserts ChatML CONTROL IDs and measures that exact sequence', t => {
  const dir = mkdtempSync(path.join(tmpdir(), 'jovovich-chatml-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const model = path.join(dir, 'tokenizer.gguf');
  fixture(model);
  const prompt = '<|im_start|>system\nx<|im_end|>\n<|im_start|>user\nx<|im_end|>\n<|im_start|>assistant\n';
  const expected = [256, ...Buffer.from('system\nx'), 257, 10, 256, ...Buffer.from('user\nx'), 257, 10, 256, ...Buffer.from('assistant\n')];
  const run = (context, mode = '--token-ids') => spawnSync('build/jovovich-infer', [
    '--model', model, '--tokens', '1', '--context', String(context), mode
  ], { input: prompt, encoding: 'utf8' });
  const ids = run(expected.length + 1);
  assert.equal(ids.status, 0, ids.stderr);
  assert.deepEqual(ids.stdout.trim().split(',').map(Number), expected);
  const count = run(expected.length + 1, '--tokens-only');
  assert.equal(count.status, 0, count.stderr);
  assert.equal(Number(count.stdout.trim()), expected.length);
  const overflow = run(expected.length);
  assert.notEqual(overflow.status, 0);
  assert.equal(overflow.stdout, '');
  assert.match(overflow.stderr, /reserves 1 for output/);
});
