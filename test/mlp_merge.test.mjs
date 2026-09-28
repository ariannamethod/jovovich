import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const u32 = n => { const b = Buffer.alloc(4); b.writeUInt32LE(n); return b; };
const u64 = n => { const b = Buffer.alloc(8); b.writeBigUInt64LE(BigInt(n)); return b; };
const text = s => { const b = Buffer.from(s); return Buffer.concat([u64(b.length), b]); };
const stringKV = (key, value) => Buffer.concat([text(key), u32(8), text(value)]);
const uintKV = (key, value) => Buffer.concat([text(key), u32(4), u32(value)]);
const aligned = n => Math.ceil(n / 32) * 32;

function fixture(file, architecture, wrongShape = false) {
  const kv = [
    stringKV('general.architecture', architecture),
    uintKV('general.alignment', 32),
    uintKV(`${architecture}.block_count`, 2),
    uintKV(`${architecture}.embedding_length`, 4),
    uintKV(`${architecture}.feed_forward_length`, 8),
    stringKV('general.description', 'Freckles / веснушки / '.repeat(30)),
    Buffer.concat([text('custom.array'), u32(9), u32(8), u64(2), text('one'), text('two')])
  ];
  // Q8_0, F16, and F32 have different payload lengths. Directory order is
  // intentionally unrelated to block/MLP order, as in real GGUF exports.
  const tensors = [
    { name: 'token_embd.weight', shape: [4, 2], type: 0, data: Buffer.alloc(32, 0x21) },
    { name: 'blk.1.ffn_up.weight', shape: [4, 8], type: 1, data: Buffer.alloc(64, 0x32) },
    { name: 'blk.0.ffn_gate.weight', shape: [4, 8], type: 8, data: Buffer.alloc(34, 0x43) },
    { name: 'blk.1.ffn_down.weight', shape: wrongShape ? [4, 8] : [8, 4], type: 8, data: Buffer.alloc(34, 0x54) },
    { name: 'blk.0.ffn_up.weight', shape: [4, 8], type: 0, data: Buffer.alloc(128, 0x65) },
    { name: 'blk.1.ffn_gate.weight', shape: [4, 8], type: 8, data: Buffer.alloc(34, 0x76) },
    { name: 'blk.0.ffn_down.weight', shape: [8, 4], type: 1, data: Buffer.alloc(64, 0x17) },
    { name: 'output_norm.weight', shape: [4], type: 0, data: Buffer.alloc(16, 0x28) }
  ];
  let offset = 0;
  const directory = tensors.map(tensor => {
    tensor.offset = offset;
    offset += aligned(tensor.data.length);
    return Buffer.concat([text(tensor.name), u32(tensor.shape.length), ...tensor.shape.map(u64), u32(tensor.type), u64(tensor.offset)]);
  });
  const metadata = Buffer.concat([Buffer.from('GGUF'), u32(3), u64(tensors.length), u64(kv.length), ...kv]);
  const header = Buffer.concat([metadata, ...directory]);
  const payloads = tensors.flatMap(tensor => [tensor.data, Buffer.alloc(aligned(tensor.data.length) - tensor.data.length, 0xab)]);
  writeFileSync(file, Buffer.concat([header, Buffer.alloc(aligned(header.length) - header.length, 0xcd), ...payloads]));
  return { metadata, tensors };
}

function directory(file, metadataBytes) {
  const bytes = readFileSync(file);
  let cursor = metadataBytes;
  const take32 = () => { const n = bytes.readUInt32LE(cursor); cursor += 4; return n; };
  const take64 = () => { const n = Number(bytes.readBigUInt64LE(cursor)); cursor += 8; return n; };
  const tensors = Array.from({ length: Number(bytes.readBigUInt64LE(8)) }, () => {
    const length = take64();
    const name = bytes.subarray(cursor, cursor + length).toString(); cursor += length;
    const shape = Array.from({ length: take32() }, take64);
    const type = take32(), offset = take64();
    return { name, shape, type, offset };
  });
  return { bytes, tensors, dataOffset: aligned(cursor) };
}

function replacements(prefix) {
  return Object.fromEntries(['gate', 'up', 'down'].map((part, index) => {
    const bytes = Buffer.alloc(32 * 4);
    for (let i = 0; i < 32; i++) bytes.writeFloatLE((index + 1) * 0.25 - i / 16, i * 4);
    writeFileSync(`${prefix}.${part}.f32`, bytes);
    return [part, bytes];
  }));
}

function setup(t, architecture = 'qwen2', wrongShape = false) {
  const dir = mkdtempSync(path.join(tmpdir(), 'jovovich-mlp-merge-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const base = path.join(dir, 'base.gguf'), prefix = path.join(dir, 'trained'), output = path.join(dir, 'merged.gguf');
  const source = fixture(base, architecture, wrongShape);
  const merged = replacements(prefix);
  const run = () => spawnSync('build/jovovich-merge-mlp', [base, prefix, output], { encoding: 'utf8' });
  return { base, prefix, output, source, merged, run };
}

for (const architecture of ['qwen2', 'qwen3']) test(`${architecture} MLP export replaces only the last three MLP tensors`, t => {
  const { base, output, source, merged, run } = setup(t, architecture);
  const before = readFileSync(base);
  const result = run();
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(readFileSync(base), before);
  const exported = directory(output, source.metadata.length);
  assert.deepEqual(exported.bytes.subarray(0, source.metadata.length), source.metadata);
  assert.equal(exported.dataOffset % 32, 0);
  assert.equal(exported.tensors.length, source.tensors.length);
  for (const [i, actual] of exported.tensors.entries()) {
    const original = source.tensors[i];
    assert.equal(actual.name, original.name);
    assert.deepEqual(actual.shape, original.shape);
    assert.equal(actual.offset % 32, 0);
    const part = /^blk\.1\.ffn_(gate|up|down)\.weight$/.exec(actual.name)?.[1];
    const expectedBytes = part ? merged[part] : original.data;
    assert.equal(actual.type, part ? 0 : original.type);
    const start = exported.dataOffset + actual.offset;
    assert.deepEqual(exported.bytes.subarray(start, start + expectedBytes.length), expectedBytes);
    if (i + 1 < exported.tensors.length)
      assert.equal(exported.tensors[i + 1].offset, actual.offset + aligned(expectedBytes.length));
  }
});

test('MLP export rejects malformed replacements and removes an incomplete output', t => {
  const { prefix, output, run } = setup(t);
  for (const value of [NaN, Infinity, -Infinity]) {
    replacements(prefix);
    const bytes = readFileSync(`${prefix}.down.f32`);
    bytes.writeFloatLE(value, 12);
    writeFileSync(`${prefix}.down.f32`, bytes);
    const result = run();
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /non-finite/);
    assert.equal(existsSync(output), false);
  }
  for (const size of [124, 132]) {
    replacements(prefix);
    writeFileSync(`${prefix}.up.f32`, Buffer.alloc(size));
    const result = run();
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /expected 128 bytes/);
    assert.equal(existsSync(output), false);
  }
});

test('MLP export refuses to overwrite an existing file', t => {
  const { output, run } = setup(t);
  const sentinel = Buffer.from('existing GGUF stays intact');
  writeFileSync(output, sentinel);
  const result = run();
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /create export/);
  assert.deepEqual(readFileSync(output), sentinel);
});

test('MLP export checks last-block matrix orientation and rejects Qwen MoE', t => {
  const wrongShape = setup(t, 'qwen2', true);
  const shapeResult = wrongShape.run();
  assert.notEqual(shapeResult.status, 0);
  assert.match(shapeResult.stderr, /shape disagrees/);
  assert.equal(existsSync(wrongShape.output), false);
  const moe = setup(t, 'qwen3moe');
  const moeResult = moe.run();
  assert.notEqual(moeResult.status, 0);
  assert.match(moeResult.stderr, /dense qwen2 or qwen3/);
  assert.equal(existsSync(moe.output), false);
});
