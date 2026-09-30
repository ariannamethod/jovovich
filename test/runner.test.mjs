import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { once } from 'node:events';

const u32 = n => { const b = Buffer.alloc(4); b.writeUInt32LE(n); return b; };
const u64 = n => { const b = Buffer.alloc(8); b.writeBigUInt64LE(BigInt(n)); return b; };
const text = s => { const b = Buffer.from(s); return Buffer.concat([u64(b.length), b]); };
const stringKV = (key, value) => Buffer.concat([text(key), u32(8), text(value)]);
const uintKV = (key, value) => Buffer.concat([text(key), u32(4), u32(value)]);
const arrayKV = (key, type, values) => Buffer.concat([text(key), u32(9), u32(type), u64(values.length), ...values]);
const aligned = n => Math.ceil(n / 32) * 32;
const runner = path.resolve('build/jovovich-infer');

/* One real Qwen2 block, with zero attention/MLP residual updates. Embeddings
 * and the output projection select A, then B, then EOS. The tokenizer merges
 * AB into a different ID, so re-encoding stdout cannot pass the trace test. */
function fixture(file, mode = 'sequence', stopID = 1) {
  const vocab = ['<|im_start|>', '<|im_end|>', '<|endoftext|>', 'A', 'B', 'AB'];
  const width = 4;
  const kv = [
    stringKV('general.architecture', 'qwen2'),
    uintKV('qwen2.block_count', 1), uintKV('qwen2.embedding_length', width),
    uintKV('qwen2.feed_forward_length', width), uintKV('qwen2.attention.head_count', 1),
    uintKV('qwen2.attention.head_count_kv', 1), uintKV('qwen2.context_length', 64),
    stringKV('tokenizer.ggml.model', 'gpt2'), stringKV('tokenizer.ggml.pre', 'qwen2'),
    arrayKV('tokenizer.ggml.tokens', 8, vocab.map(text)),
    arrayKV('tokenizer.ggml.token_type', 4, vocab.map((_, i) => u32(i < 3 ? 3 : 1))),
    arrayKV('tokenizer.ggml.merges', 8, [text('A B')]),
    uintKV('tokenizer.ggml.eos_token_id', 1),
    Buffer.concat([text('tokenizer.ggml.add_bos_token'), u32(7), Buffer.from([0])])
  ];
  const embedding = new Float32Array(width * vocab.length);
  for (let id = 0; id < vocab.length; id++) embedding[id * width] = 1;
  const output = new Float32Array(width * vocab.length);
  if (mode === 'immediate') output[stopID * width] = 1;
  else if (mode === 'repeat') output[3 * width] = 1;
  else {
    embedding[3 * width] = 0; embedding[3 * width + 1] = 1;
    embedding[4 * width] = 0; embedding[4 * width + 2] = 1;
    output[3 * width] = 1; output[4 * width + 1] = 1; output[stopID * width + 2] = 1;
  }
  const tensors = [];
  const add = (name, shape, values) => {
    const data = Buffer.alloc(values.length * 4);
    values.forEach((v, i) => data.writeFloatLE(v, i * 4));
    tensors.push({ name, shape, data });
  };
  add('token_embd.weight', [width, vocab.length], embedding);
  add('output.weight', [width, vocab.length], output);
  for (const name of ['output_norm.weight', 'blk.0.attn_norm.weight', 'blk.0.ffn_norm.weight'])
    add(name, [width], new Float32Array(width).fill(1));
  for (const name of ['attn_q', 'attn_k', 'attn_v', 'attn_output', 'ffn_gate', 'ffn_up', 'ffn_down']) {
    if (mode === 'missing' && name === 'ffn_down') continue;
    add(`blk.0.${name}.weight`, [width, width], new Float32Array(width * width));
  }
  let offset = 0;
  const directory = tensors.map(t => {
    const entry = Buffer.concat([text(t.name), u32(t.shape.length), ...t.shape.map(u64), u32(0), u64(offset)]);
    offset += aligned(t.data.length);
    return entry;
  });
  const header = Buffer.concat([Buffer.from('GGUF'), u32(3), u64(tensors.length), u64(kv.length), ...kv, ...directory]);
  writeFileSync(file, Buffer.concat([header, Buffer.alloc(aligned(header.length) - header.length),
    ...tensors.flatMap(t => [t.data, Buffer.alloc(aligned(t.data.length) - t.data.length)])]));
}

function setup(t, mode, stopID) {
  const dir = mkdtempSync(path.join(tmpdir(), 'jovovich-runner-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const model = path.join(dir, 'tiny.gguf'), trace = path.join(dir, 'trace.json');
  fixture(model, mode, stopID);
  const args = ['--model', model, '--tokens', '4', '--context', '16', '--temperature', '0'];
  const options = { input: '<|im_start|>', encoding: 'utf8', timeout: 10_000,
    env: { ...process.env, NT_NO_I8: '1', NT_QMV_THREADS: '1', NT_ATTN_THREADS: '1', NT_SIMD_THREADS: '1' } };
  const run = (extra = [], overrides = {}) => spawnSync(runner, [...args, ...extra], { ...options, ...overrides });
  return { dir, model, trace, args, options, run };
}

test('runner traces sampled IDs before decoding and EOS, without changing stdout', t => {
  const { trace, run } = setup(t, 'sequence');
  const plain = run(), traced = run(['--trace-tokens', trace]);
  assert.equal(plain.status, 0, plain.stderr);
  assert.equal(traced.status, 0, traced.stderr);
  assert.equal(traced.stdout, plain.stdout);
  assert.equal(traced.stdout, 'AB');
  assert.deepEqual(JSON.parse(readFileSync(trace, 'utf8')), {
    schema_version: 1, prompt_token_ids: [0], generated_token_ids: [3, 4, 1],
    requested_limit: 4, emitted_tokens: 2, stop_reason: 'eos'
  });
  const reencoded = run(['--token-ids'], { input: traced.stdout });
  assert.equal(reencoded.status, 0, reencoded.stderr);
  assert.equal(reencoded.stdout, '5\n');
});

for (const stopID of [1, 2]) test(`runner traces immediate stopping ID ${stopID} with empty response stdout`, t => {
  const { trace, run } = setup(t, 'immediate', stopID);
  const result = run(['--trace-tokens', trace]);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, '');
  const saved = JSON.parse(readFileSync(trace, 'utf8'));
  assert.deepEqual(saved.generated_token_ids, [stopID]);
  assert.equal(saved.emitted_tokens, 0);
  assert.equal(saved.stop_reason, 'eos');
});

test('runner traces exactly the token limit and the complete supplied prompt IDs', t => {
  const { trace, run } = setup(t, 'repeat');
  const input = '<|im_start|>AB<|im_end|><|im_start|>';
  const plain = run([], { input }), traced = run(['--trace-tokens', trace], { input });
  assert.equal(plain.status, 0, plain.stderr);
  assert.equal(traced.status, 0, traced.stderr);
  assert.equal(traced.stdout, plain.stdout);
  assert.equal(traced.stdout, 'AAAA');
  assert.deepEqual(JSON.parse(readFileSync(trace, 'utf8')), {
    schema_version: 1, prompt_token_ids: [0, 5, 1, 0], generated_token_ids: [3, 3, 3, 3],
    requested_limit: 4, emitted_tokens: 4, stop_reason: 'token-limit'
  });
});

test('runner refuses existing trace files and symlinks before inference', t => {
  const { dir, model, trace, run } = setup(t, 'sequence');
  const sentinel = Buffer.from('the original trace stays intact');
  writeFileSync(trace, sentinel);
  const link = path.join(dir, 'trace-link.json'); symlinkSync(trace, link);
  const modelBytes = readFileSync(model);
  for (const destination of [trace, link, model]) {
    const result = run(['--trace-tokens', destination]);
    assert.notEqual(result.status, 0);
    assert.equal(result.stdout, '');
    assert.match(result.stderr, /cannot create token trace/);
    assert.doesNotMatch(result.stderr, /jovovich: prompt=/);
    assert.deepEqual(readFileSync(trace), sentinel);
    assert.deepEqual(readFileSync(model), modelBytes);
  }
});

test('runner validates trace options and destination before generation', t => {
  const { dir, trace, run } = setup(t, 'sequence');
  for (const mode of ['--token-ids', '--tokens-only']) {
    const result = run(['--trace-tokens', trace, mode]);
    assert.equal(result.status, 2);
    assert.match(result.stderr, /requires generation/);
    assert.equal(existsSync(trace), false);
  }
  const duplicate = run(['--trace-tokens', trace, '--trace-tokens', trace]);
  assert.equal(duplicate.status, 2);
  assert.equal(existsSync(trace), false);
  const missing = run(['--trace-tokens', path.join(dir, 'missing', 'trace.json')]);
  assert.notEqual(missing.status, 0);
  assert.equal(missing.stdout, '');
  assert.match(missing.stderr, /cannot create token trace/);
});

test('runner removes its incomplete trace when model loading fails', t => {
  const { trace, run } = setup(t, 'missing');
  const result = run(['--trace-tokens', trace]);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /required tensor .*ffn_down.weight.* missing/);
  assert.equal(result.stdout, '');
  assert.equal(existsSync(trace), false);
});

test('runner reports trace write failure and removes the incomplete file', t => {
  const { trace, args, options } = setup(t, 'sequence');
  // An ignored SIGXFSZ makes the actual stdio flush return EFBIG. stdout is a
  // pipe, so generation succeeds while the zero-byte regular-file limit
  // exercises the trace's own error path rather than a model failure.
  const result = spawnSync('sh', ['-c', 'ulimit -f 0; trap "" XFSZ; exec "$@"',
    'trace-write-limit', runner, ...args, '--trace-tokens', trace], options);
  assert.equal(result.signal, null, result.stderr);
  assert.equal(result.status, 1, result.stderr);
  assert.equal(result.stdout, 'AB');
  assert.match(result.stderr, /cannot write complete token trace/);
  assert.equal(existsSync(trace), false);
});


test('runner reports a closed stdout reader and removes its reserved trace', async t => {
  const { trace, args, options } = setup(t, 'sequence');
  const child = spawn(runner, [...args, '--trace-tokens', trace], {
    env: options.env, stdio: ['pipe', 'pipe', 'pipe'], timeout: 10_000
  });
  const exited = once(child, 'close');
  let stderr = '', inputError = null;
  child.stderr.setEncoding('utf8');
  child.stderr.on('data', data => { stderr += data; });
  child.stdin.on('error', error => { inputError = error; });
  // read_prompt blocks until EOF: close the sole reader before supplying any
  // input, so the first emitted token deterministically encounters EPIPE.
  const readerClosed = once(child.stdout, 'close');
  child.stdout.destroy();
  await readerClosed;
  child.stdin.end(options.input);
  const [status, signal] = await exited;
  assert.equal(inputError, null);
  assert.equal(signal, null, stderr);
  assert.equal(status, 1, stderr);
  assert.match(stderr, /cannot emit complete output token/);
  assert.equal(existsSync(trace), false);
});

for (const mode of ['--tokens-only', '--token-ids'])
  test(`runner reports buffered stdout failure in ${mode} mode`, t => {
    const { dir, args, options } = setup(t, 'sequence');
    const destination = path.join(dir, 'stdout-limit');
    // These small printf writes remain buffered until common cleanup. The
    // ignored file-size signal forces fclose's flush to return an I/O error.
    const result = spawnSync('sh', ['-c',
      'ulimit -f 0; trap "" XFSZ; destination=$1; shift; exec "$@" > "$destination"',
      'stdout-write-limit', destination, runner, ...args, mode], options);
    assert.equal(result.signal, null, result.stderr);
    assert.equal(result.status, 1, result.stderr);
    assert.match(result.stderr, /cannot finish stdout/);
    assert.equal(readFileSync(destination).length, 0);
  });
