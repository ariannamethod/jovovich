#!/usr/bin/env python3
"""Execute unchanged trainer mains against a tiny synthetic Qwen body."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'training'))
from prepare import prepare


def u32(n): return struct.pack('<I', n)
def u64(n): return struct.pack('<Q', n)
def string(value):
    value = value.encode('utf-8')
    return u64(len(value)) + value
def field(value):
    value = value.encode('utf-8')
    return u32(len(value)) + value
def pad(value): return value + bytes((-len(value)) % 32)
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def dump(path, value): path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def fixture(path):
    visible = set(range(33, 127)) | set(range(161, 173)) | set(range(174, 256))
    missing = [b for b in range(256) if b not in visible]
    vocab = [chr(b if b in visible else 256 + missing.index(b)) for b in range(256)]
    vocab += ['<|im_start|>', '<|im_end|>', '\":', '\":[', '\":[]', '\":[{']
    def sk(k, v): return string(k) + u32(8) + string(v)
    def ik(k, v): return string(k) + u32(4) + u32(v)
    def arr(k, values): return string(k) + u32(9) + u32(8) + u64(len(values)) + b''.join(map(string, values))
    meta = [sk('general.architecture', 'qwen2'), ik('qwen2.block_count', 1),
            ik('qwen2.embedding_length', 8), ik('qwen2.feed_forward_length', 12),
            ik('qwen2.attention.head_count', 1), ik('qwen2.attention.head_count_kv', 1),
            ik('qwen2.context_length', 1024),
            string('qwen2.attention.layer_norm_rms_epsilon') + u32(6) + struct.pack('<f', 1e-6),
            sk('tokenizer.ggml.model', 'gpt2'), sk('tokenizer.ggml.pre', 'qwen2'),
            arr('tokenizer.ggml.tokens', vocab),
            arr('tokenizer.ggml.merges', ['" :', '": [', '":[ ]', '":[ {']),
            ik('tokenizer.ggml.eos_token_id', 257)]
    tensors = []
    def add(name, shape, scale, phase=0):
        count = math.prod(shape)
        values = [1.0] * count if scale == 0 else [scale * math.sin(i * .73 + phase) for i in range(count)]
        tensors.append((name, shape, struct.pack('<' + 'f' * count, *values)))
    add('token_embd.weight', [8, len(vocab)], .3, .2)
    add('output.weight', [8, len(vocab)], .2, .7)
    for name in ['output_norm.weight', 'blk.0.attn_norm.weight', 'blk.0.ffn_norm.weight']:
        add(name, [8], 0)
    for i, name in enumerate(['attn_q', 'attn_k', 'attn_v', 'attn_output']):
        add('blk.0.' + name + '.weight', [8, 8], .04, i + 1)
    for i, name in enumerate(['ffn_gate', 'ffn_up']):
        add('blk.0.' + name + '.weight', [8, 12], .12, i + 1)
    add('blk.0.ffn_down.weight', [12, 8], .11, 3)
    directory, values, offset = [], [], 0
    for name, shape, data in tensors:
        directory.append(string(name) + u32(len(shape)) + b''.join(map(u64, shape)) + u32(0) + u64(offset))
        values.append(pad(data)); offset += len(values[-1])
    header = b'GGUF' + u32(3) + u64(len(tensors)) + u64(len(meta)) + b''.join(meta) + b''.join(directory)
    path.write_bytes(pad(header) + b''.join(values))


def execute(out, name, command):
    receipt = {'argv': list(map(str, command)), 'started_utc': datetime.now(timezone.utc).isoformat()}
    dump(out / (name + '.intent.json'), receipt)
    result = subprocess.run(receipt['argv'], cwd=ROOT, capture_output=True)
    stdout, stderr = out / (name + '.stdout.txt'), out / (name + '.stderr.txt')
    stdout.write_bytes(result.stdout); stderr.write_bytes(result.stderr)
    receipt.update(return_code=result.returncode, finished_utc=datetime.now(timezone.utc).isoformat(),
                   stdout_sha256=digest(stdout), stderr_sha256=digest(stderr))
    dump(out / (name + '.receipt.json'), receipt)
    if result.returncode:
        raise RuntimeError(name + ' failed: ' + result.stderr.decode(errors='replace')[-1800:])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(); out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    sources = ['training/train_mlp.c', 'training/train_head.c', 'training/prepare.py',
               'deps/notorch/notorch.c', 'deps/notorch/notorch.h', 'deps/notorch/notorch_simd.h',
               'deps/notorch/gguf.c', 'deps/notorch/harness/runtime.c',
               'deps/notorch/harness/arch_llama.c', 'deps/notorch/examples/bpe.c']
    bound = {name: digest(ROOT / name) for name in sources}
    dump(out / 'bindings.json', {'source_sha256': bound, 'audit_header_sha256': digest(HERE / 'chuck_call_audit.h'),
                               'notorch_pin': subprocess.check_output(['git', '-C', str(ROOT / 'deps/notorch'), 'rev-parse', 'HEAD'], text=True).strip()})
    fixture(out / 'tiny.gguf')
    answers = ['{"analysis":"A longer reason.","findings":[{"reason":"bad"}]}',
               '{"analysis":"Fine.","findings":[]}']
    data = [dict(id=str(i), kind='review', pair='tiny', messages=[dict(role='system', content='Review.'),
            dict(role='user', content='Diff.'), dict(role='assistant', content=a)]) for i, a in enumerate(answers)]
    (out / 'sft.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in data))
    prepare(out / 'sft.jsonl', None, out / 'sft.bin', out / 'pairs.bin', pair_format=2)
    head_rows = [(0, 's', 'p', 'A', ''), (1, 's', 'p', 'A', 'B')]
    (out / 'head.bin').write_bytes(b'JVDS\1\0\0\0' + u32(2) + b''.join(u32(kind) + b''.join(map(field, text)) for kind, *text in head_rows))
    temp = Path(tempfile.mkdtemp(prefix='jovovich-chuck-main-'))
    binaries = {}
    substrate = [ROOT / name for name in sources if name.startswith('deps/') and name.endswith('.c')]
    for kind in ('mlp', 'head'):
        wrapper = out / (kind + '-main.c')
        wrapper.write_text('#include "' + str(HERE / 'chuck_call_audit.h') + '"\n'
                           '#define nt_tape_chuck_step audited_chuck_step\n'
                           '#include "' + str(ROOT / ('training/train_' + kind + '.c')) + '"\n'
                           '#undef nt_tape_chuck_step\n')
        binary = temp / kind; binaries[kind] = binary
        execute(out, 'compile-' + kind, ['cc', '-O2', '-Wall', '-Wextra', '-std=gnu11', '-march=native',
                '-DUSE_SIMD', '-I' + str(ROOT / 'deps/notorch'), '-o', binary, wrapper, *substrate, '-lm', '-pthread'])
    results = {}
    for objective, batch in [('joint', 8), ('tokens', 128)]:
        result = execute(out, objective, [binaries['mlp'], out / 'tiny.gguf', out / 'sft.bin',
                         out / objective, '20', '.003', str(batch), '10', objective, out / 'pairs.bin'])
        metrics = [json.loads(line) for line in result.stdout.splitlines()]
        calls = [json.loads(line[len(b'CHUCK_AUDIT '):]) for line in result.stderr.splitlines() if line.startswith(b'CHUCK_AUDIT ')]
        expected = 20 if objective == 'joint' else 20 * math.ceil(metrics[0]['tokens'] / batch)
        assert len(calls) == expected and all(row['slots'] == 6 for row in calls)
        assert [row['step_after'] for row in calls] == list(range(1, expected + 1))
        assert any(abs(row['parameter_sum_delta']) > 0 for row in calls)
        assert metrics[0]['pair_map_version'] == 2
        positions = [row['decision_position'] for row in metrics[0]['teacher_forced_rows']]
        assert positions[0] != positions[1]
        if objective == 'joint':
            online = [row['online_joint_ce'] for row in metrics if row['stage'] == 'decision_train' and row['update']]
            assert len(online) == len(calls)
            assert all(math.isclose(a, b['loss'], rel_tol=1e-6) for a, b in zip(online, calls))
        results[objective] = {'chuck_calls': len(calls), 'decision_positions': positions,
                              'final_frozen_slots': calls[-1]['frozen_slots'], 'final_noise': calls[-1]['noise'],
                              'first_loss': calls[0]['loss'], 'last_loss': calls[-1]['loss']}
    result = execute(out, 'head', [binaries['head'], out / 'tiny.gguf', out / 'head.bin', out / 'head', '20', '20', '.003'])
    metrics = [json.loads(line) for line in result.stdout.splitlines()]
    calls = [json.loads(line[len(b'CHUCK_AUDIT '):]) for line in result.stderr.splitlines() if line.startswith(b'CHUCK_AUDIT ')]
    assert len(calls) == 40 and all(row['slots'] == 2 for row in calls)
    assert [row['step_after'] for row in calls] == list(range(1, 21)) * 2
    assert calls[19]['resets'] == 0 and calls[20]['resets'] == 1
    for stage, selected in [('sft', calls[:20]), ('dpo', calls[20:])]:
        values = [row['online_mean_ce' if stage == 'sft' else 'online_mean_loss'] for row in metrics if row['stage'] == stage]
        assert all(math.isclose(a, b['loss'], rel_tol=1e-6) for a, b in zip(values, selected))
    assert any(abs(row['parameter_sum_delta']) > 0 for row in calls[20:])
    results['head'] = {'sft_chuck_calls': 20, 'dpo_chuck_calls': 20, 'optimizer_reset_at_dpo': True,
                       'sft_final_frozen_slots': calls[19]['frozen_slots'], 'dpo_final_frozen_slots': calls[-1]['frozen_slots']}
    assert bound == {name: digest(ROOT / name) for name in sources}, 'bound sources changed'
    report = {'status': 'pass', 'trainer_callsites_executed': 4, 'results': results,
              'controller_and_moments_preserved_across_diagnostics': True,
              'native_chuck_updates_used': True, 'source_modifications': False,
              'binary_sha256': {kind: digest(binary) for kind, binary in binaries.items()},
              'fixture_scope': 'Deterministic tiny synthetic one-block Qwen; integration assertions only.'}
    dump(out / 'summary.json', report); print(json.dumps(report))


if __name__ == '__main__': main()
