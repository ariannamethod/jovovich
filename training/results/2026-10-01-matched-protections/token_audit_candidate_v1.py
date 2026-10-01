#!/usr/bin/env python3
"""Serialize review prompts; native notorch alone supplies Qwen token IDs/counts.

Writes an exclusive audit directory. No model forward pass, fit or training.
Usage: token_audit.py --repo REPO --corpus FILE --out NEW_DIRECTORY
"""
import argparse
import hashlib
import json
import re
import struct
import subprocess
import time
from pathlib import Path

FEATURES = ['native_prompt_token_count_without_common_prefix', 'added_lines', 'removed_lines', 'context_lines', 'after_if_statements', 'after_sort_calls', 'after_firwood_trie_occurrences']
SOURCES = ['training/extract_readout.c', 'training/train_mlp.c', 'src/infer.c', 'Makefile',
           'deps/notorch/notorch.c', 'deps/notorch/notorch.h', 'deps/notorch/notorch_simd.h',
           'deps/notorch/gguf.c', 'deps/notorch/gguf.h', 'deps/notorch/harness/runtime.c',
           'deps/notorch/harness/runtime.h', 'deps/notorch/harness/arch_llama.c',
           'deps/notorch/harness/arch.h', 'deps/notorch/harness/arch_models.h',
           'deps/notorch/examples/bpe.c', 'deps/notorch/examples/bpe.h',
           'deps/notorch/examples/unicode_numbers.h']

def binding(path):
    raw = Path(path).read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

def save(path, obj):
    path.write_text(json.dumps(obj, indent=2) + '\n')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', type=Path, required=True)
    ap.add_argument('--corpus', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    repo, corpus, out = args.repo.resolve(), args.corpus.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    model, binary = repo/'models/base-qwen.gguf', repo/'build/jovovich-extract-readout'
    original = [binding(p) for p in [corpus, model, binary, Path(__file__).resolve()] + [repo/s for s in SOURCES]]
    rows = [json.loads(line) for line in corpus.read_text().splitlines() if line.strip()]
    rows = [row for row in rows if row['kind'] == 'review']
    assert 0 < len(rows) <= 10000
    data = bytearray(b'JVRO1\0\0\0' + struct.pack('<I', len(rows)))
    for row in rows:
        assert [m['role'] for m in row['messages']] == ['system', 'user', 'assistant']
        for m in row['messages'][:2]:
            raw = m['content'].encode('utf-8')
            data.extend(struct.pack('<I', len(raw))); data.extend(raw)
    inp = out/'prompts.bin'; inp.write_bytes(data)
    command = [str(binary), str(model), str(inp), '--tokenize-only']
    started = time.monotonic()
    with (out/'token-trace.jsonl').open('xb') as stdout, (out/'stderr.txt').open('xb') as stderr:
        run = subprocess.run(command, stdout=stdout, stderr=stderr, check=False)
    elapsed = time.monotonic() - started
    if run.returncode:
        save(out/'receipt.json', {'status': 'native failure', 'returncode': run.returncode, 'command': command, 'elapsed_seconds': elapsed, 'bindings_before': original})
        raise SystemExit(run.returncode)
    traces = [json.loads(line) for line in (out/'token-trace.jsonl').read_text().splitlines()]
    assert len(traces) == len(rows)
    paired = {}; audited = []
    for i, (row, trace) in enumerate(zip(rows, traces)):
        n = trace['prompt_tokens']
        assert trace['row'] == i and trace['tokenize_only'] is True
        assert trace['input_tokens'] == n+3 and trace['capture_position'] == n+2
        assert len(trace['input_ids']) == n+3 and trace['input_ids'][-3:] == [4913,3903,819]
        user = row['messages'][1]['content']
        patch = user.split('\n\nSurrounding diff:\n')[1].split('\n\nChanged lines to review:\n')[0]
        header, *body = patch.splitlines()
        match = re.fullmatch(r'@@ -(\d+),(\d+) \+(\d+),(\d+) @@', header)
        assert match and all(line and line[0] in ' +-' for line in body)
        assert sum(line[0] != '+' for line in body) == int(match[2])
        assert sum(line[0] != '-' for line in body) == int(match[4])
        after = '\n'.join(line[1:] for line in body if line[0] != '-')
        v = [n] + [sum(line[0] == c for line in body) for c in '+- ']
        v += [len(re.findall(r'\bif\s*\(', after)), len(re.findall(r'\.sort\s*\(', after)), after.count('firwood/trie')]
        answer = json.loads(row['messages'][2]['content'])
        record = {'row': i, 'id': row['id'], 'pair': row['pair'], 'label': int(bool(answer['findings'])), 'features': v, 'user_sha256': hashlib.sha256(user.encode()).hexdigest()}
        audited.append(record); paired.setdefault(row['pair'], []).append(record)
    pairs = []
    for name, members in paired.items():
        equal = len(members) == 2 and members[0]['features'] == members[1]['features']
        pairs.append({'pair': name, 'rows': [r['row'] for r in members], 'opposite_labels': sorted(r['label'] for r in members) == [0,1], 'all_seven_equal': equal, 'differing_features': [FEATURES[j] for j in range(7) if len({r['features'][j] for r in members}) > 1]})
    current = [binding(b['path']) for b in original]
    assert current == original, 'input/source changed during audit'
    receipt = {'status': 'complete', 'command': command, 'returncode': 0, 'elapsed_seconds': elapsed, 'native_operation': 'GGUF metadata and tokenizer loading, exact ChatML tokenization, no forward pass', 'feature_names': FEATURES, 'review_rows': len(rows), 'pairs': pairs, 'rows': audited, 'bindings_before': original, 'bindings_unchanged': True, 'outputs': [binding(out/name) for name in ('prompts.bin','token-trace.jsonl','stderr.txt')]}
    save(out/'receipt.json', receipt)
    print(json.dumps({'out': str(out), 'rows': len(rows), 'pairs': len(pairs), 'all_seven_equal_pairs': sum(p['all_seven_equal'] for p in pairs), 'elapsed_seconds': elapsed}))

if __name__ == '__main__':
    main()
