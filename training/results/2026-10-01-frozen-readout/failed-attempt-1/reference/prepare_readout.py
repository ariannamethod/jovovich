#!/usr/bin/env python3
"""Prepare causal prompt inputs, frozen family masks and fixed lexical covariates.

Python performs serialization/counting only. Feature normalization and every fit,
prediction and statistical score belong to the native C solver.
"""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

CORPUS_SHA = "20afaa5692e88625d7152c7634c68e665a7bb165bfdc6dba15fec8c9e01edc1e"
RETAINED = ["scoped-python-analysis", "approved-binary-decoder", "sqlite-build-requirement", "background-service-scope", "model-parent-provenance", "scoped-design-record", "checksum-indirection", "sequence-field-width", "validated-port-conversion", "negative-offset-type", "exact-property-name", "idempotent-event-retry", "atomic-snapshot-publication", "save-status-propagation"]
QUARTETS = ["preserve-trie-credit", "allocation-null-guard", "zero-worker-guard", "write-permission-check", "stable-manifest-order", "allocation-product-overflow"]
FAMILIES = RETAINED + QUARTETS
SAME_DIFF = ["scoped-python-analysis", "approved-binary-decoder", "sqlite-build-requirement", "background-service-scope", "scoped-design-record", "checksum-indirection"]
FEATURES = ["native_prompt_token_count_without_common_prefix", "added_lines", "removed_lines", "context_lines", "after_if_statements", "after_sort_calls", "after_firwood_trie_occurrences"]

def digest(data):
    return hashlib.sha256(data).hexdigest()

def save(path, value):
    data = value if isinstance(value, bytes) else (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
    with path.open("xb") as f:
        f.write(data)
    return {"path": path.name, "sha256": digest(data), "bytes": len(data)}

def metadata(rows, width):
    lines = ["JOVOVICH_READOUT_V1", f"52 {width} 20 26"]
    lines += [f"{r['label']} {r['family_index']} {r['pair_index']} {int(r['same_full_diff_subset'])}" for r in rows]
    return ("\n".join(lines) + "\n").encode()

def prepare(repo, out):
    corpus = repo / "training/sft_review_v4.jsonl"
    raw = corpus.read_bytes()
    assert digest(raw) == CORPUS_SHA
    all_rows = [json.loads(s) for s in raw.decode().splitlines()]
    reviews = [r for r in all_rows if r['kind'] == 'review']
    assert len(all_rows) == 76 and len(reviews) == 52
    pair_names = list(dict.fromkeys(r['pair'] for r in reviews))
    assert len(pair_names) == 26
    binary = bytearray(b'JVRO1\0\0\0' + struct.pack('<I', len(reviews)))
    rows = []
    patches = {}
    for index, r in enumerate(reviews):
        assert [m['role'] for m in r['messages']] == ['system', 'user', 'assistant']
        system, user, answer = [m['content'] for m in r['messages']]
        for text in (system, user):
            blob = text.encode()
            binary.extend(struct.pack('<I', len(blob)))
            binary.extend(blob)
        gold = json.loads(answer)
        assert set(gold) == {'findings'} and isinstance(gold['findings'], list)
        label = int(bool(gold['findings']))
        pair = r['pair']
        family = pair if pair in RETAINED else next(f for f in QUARTETS if pair in (f+'-deletion', f+'-replacement'))
        assert user.count('\n\nSurrounding diff:\n') == 1
        patch = user.split('\n\nSurrounding diff:\n')[1].split('\n\nChanged lines to review:\n')[0]
        header, *body = patch.splitlines()
        match = re.fullmatch(r'@@ -(\d+),(\d+) \+(\d+),(\d+) @@', header)
        assert match and all(line and line[0] in ' +-' for line in body)
        assert sum(line[0] != '+' for line in body) == int(match[2])
        assert sum(line[0] != '-' for line in body) == int(match[4])
        after = '\n'.join(line[1:] for line in body if line[0] != '-')
        counts = [sum(line[0] == ch for line in body) for ch in '+- ']
        counts += [len(re.findall(r'\bif\s*\(', after)), len(re.findall(r'\.sort\s*\(', after)), after.count('firwood/trie')]
        rows.append({"index": index, "id": r['id'], "label": label, "family": family,
                     "family_index": FAMILIES.index(family), "pair": pair, "pair_index": pair_names.index(pair),
                     "same_full_diff_subset": pair in SAME_DIFF, "system_sha256": digest(system.encode()),
                     "user_sha256": digest(user.encode()), "patch_sha256": digest(patch.encode()),
                     "nuisance_counts_without_prompt_tokens": counts})
        patches.setdefault(pair, []).append(patch)
    for p in pair_names:
        rr = [r for r in rows if r['pair'] == p]
        assert len(rr) == 2 and sorted(r['label'] for r in rr) == [0, 1]
    for f in FAMILIES:
        rr = [r for r in rows if r['family'] == f]
        assert len(rr) == (2 if f in RETAINED else 4)
        assert sum(r['label'] for r in rr) == len(rr) // 2
    for p in SAME_DIFF:
        assert patches[p][0] == patches[p][1]
    masks, counters, seen = [], [], set()
    counter = 0
    while len(masks) < 99:
        payload = f'jovovich-readout-permutation:20261001:{counter}'.encode('ascii')
        number = int.from_bytes(hashlib.sha256(payload).digest()[:4], 'little') & ((1 << 20) - 1)
        if number and number not in seen:
            seen.add(number)
            masks.append(''.join(str((number >> bit) & 1) for bit in range(20)))
            counters.append(counter)
        counter += 1
    for mask in masks:
        for p in pair_names:
            assert sum(r['label'] ^ int(mask[r['family_index']]) for r in rows if r['pair'] == p) == 1
    out.mkdir(parents=True, exist_ok=True)
    sources = [save(out/'readout-input.bin', bytes(binary)),
               save(out/'readout-rows.json', {"corpus_sha256": CORPUS_SHA, "features": FEATURES, "family_order": FAMILIES, "pair_order": pair_names, "rows": rows}),
               save(out/'readout-metadata.txt', metadata(rows, 896)),
               save(out/'readout-masks.txt', ('JOVOVICH_MASKS_V1\n99 20\n' + '\n'.join(masks) + '\n').encode()),
               save(out/'readout-masks.json', {"seed": 20261001, "algorithm": "SHA256 of ASCII jovovich-readout-permutation:20261001:{counter}; first 4 digest bytes little-endian masked to 20 bits; bit k is family_order[k]. Reject zero and duplicate masks only. All-ones and complements are eligible.", "accepted_counters": counters, "family_order": FAMILIES, "masks": masks, "capacity_control_mask_index": 0})]
    receipt = {"status": "prepared before model feature extraction or fitting", "corpus": {"path": str(corpus), "sha256": digest(raw), "bytes": len(raw)}, "rows": 52, "pairs": 26, "families": 20, "same_full_diff_pairs": 6, "prompt_input_contains": "system and user UTF-8 only; neither labels, identifiers nor assistant answers", "nuisance_features": FEATURES, "files": sources, "preparer": {"sha256": digest(Path(__file__).read_bytes())}}
    save(out/'readout-preparation.json', receipt)
    print(json.dumps(receipt))

def finish(out, trace):
    """Serialize measured native token counts, not model arithmetic."""
    data = json.loads((out/'readout-rows.json').read_text())
    rows = data['rows']
    records = [json.loads(line) for line in trace.read_text().splitlines() if line.strip()]
    records = [r for r in records if 'row' in r]
    assert len(records) == 52 and [r['row'] for r in records] == list(range(52))
    matrix = bytearray(b'JVRF1\0\0\0' + struct.pack('<II', 52, 7))
    completed = []
    for r, native in zip(rows, records):
        n = native['prompt_tokens']
        assert isinstance(n, int) and n > 0
        assert native['prefix_ids'] == [4913, 3903, 819]
        assert native['capture_position'] == n + 2
        assert native['input_tokens'] == n + 3
        assert len(native['input_ids']) == n + 3
        assert native['input_ids'][-3:] == [4913, 3903, 819]
        assert all(isinstance(token, int) and token >= 0 for token in native['input_ids'])
        vector = [n] + r['nuisance_counts_without_prompt_tokens']
        matrix.extend(struct.pack('<7f', *vector))
        completed.append({"rowindex": r['index'], "features": vector})
    files = [save(out/'readout-nuisance.bin', bytes(matrix)), save(out/'readout-nuisance-metadata.txt', metadata(rows, 7))]
    save(out/'readout-nuisance.json', {"feature_names": FEATURES, "rows": completed, "trace_sha256": digest(trace.read_bytes()), "files": files, "source_rows_sha256": digest((out/'readout-rows.json').read_bytes())})
    print(json.dumps(files))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--trace', type=Path)
    args = parser.parse_args()
    if args.trace:
        finish(args.out, args.trace)
    else:
        assert args.repo is not None
        prepare(args.repo, args.out)
