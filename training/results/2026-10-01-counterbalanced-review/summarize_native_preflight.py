#!/usr/bin/env python3
"""Validate saved native preflight rows and write their provenance receipt."""
import collections
import hashlib
import json
from pathlib import Path
import struct

root = Path.cwd()
here = Path(__file__).resolve().parent
raw = root / 'models/counterbalanced-review-preflight.jsonl'
reports = [json.loads(line) for line in raw.read_text().splitlines()]
summary, rows = reports[-1], reports[:-1]
data = [json.loads(line) for line in (root / 'training/sft_review_v4.jsonl').read_text().splitlines()]
assert len(rows) == len(data) == 76
assert {r['row'] for r in rows} == set(range(76))
pairmap = (root / 'models/counterbalanced-review.pairs').read_bytes()
assert pairmap[:8] == b'JVPR\1\0\0\0'
assert struct.unpack_from('<II', pairmap, 8) == (76, 26)
pairs = [struct.unpack_from('<II', pairmap, 16 + 8*i) for i in range(26)]
assert len(pairmap) == 16 + 8*26

def ids_hash(ids):
    return hashlib.sha256(struct.pack('<' + 'I'*len(ids), *ids)).hexdigest()

metadata, decision_ids, prefixes = [], collections.Counter(), set()
for i, (r, d) in enumerate(zip(rows, data)):
    assert r['row'] == i and r['mapped_review'] == (d['kind'] == 'review')
    ids, start, end = r['token_ids'], r['prompt_tokens'], r['full_tokens']
    assert len(ids) == end and r['capture_start'] == start - 1
    assert end - start == r['completion_targets']
    assert ids[-1] == r['terminal_target_id'] == 151645
    item = {k: v for k, v in r.items() if k not in ('token_ids', 'stage')}
    item.update(id=d['id'], kind=d['kind'], prompt_ids_sha256=ids_hash(ids[:start]),
                full_ids_sha256=ids_hash(ids))
    if r['mapped_review']:
        pos = r['decision_position']
        assert 0 <= pos < r['completion_targets'] - 1
        assert r['decision_target_id'] == ids[start + pos]
        assert r['residual_targets'] == r['completion_targets'] - 1
        decision_ids[r['decision_target_id']] += 1
        prefixes.add(tuple(ids[start:start + pos]))
        item.update(pair=d['pair'])
    else:
        assert r['trained_targets'] == r['residual_targets'] == 0
    metadata.append(item)
for index, (a, b) in enumerate(pairs):
    x, y = rows[a], rows[b]
    assert x['pair_index'] == y['pair_index'] == index
    assert data[a]['pair'] == data[b]['pair']
    assert json.loads(data[a]['messages'][2]['content'])['findings']
    assert not json.loads(data[b]['messages'][2]['content'])['findings']
    assert x['decision_position'] == y['decision_position']
    assert x['decision_target_id'] == y['decision_alternative_id']
    assert y['decision_target_id'] == x['decision_alternative_id']
    pos = x['decision_position']
    assert x['token_ids'][x['prompt_tokens']:x['prompt_tokens'] + pos] == \
        y['token_ids'][y['prompt_tokens']:y['prompt_tokens'] + pos]
assert summary['pass'] and summary['decision_positions'] == 52
assert summary['residual_positions'] == 1012 and summary['joint_positions'] == 1064
assert sum(r['completion_targets'] for r in rows) == 2591
assert sum(r['trained_targets'] for r in rows) == 1064
assert summary['prompt_tokens_max'] + 192 <= 2048

def item(path):
    path = Path(path)
    data = path.read_bytes()
    return dict(path=str(path.relative_to(root) if path.is_relative_to(root) else path),
                sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))

native = ['notorch.c', 'notorch.h', 'notorch_simd.h', 'gguf.c', 'gguf.h',
          'harness/runtime.c', 'harness/runtime.h', 'harness/arch_llama.c',
          'harness/arch.h', 'harness/arch_models.h', 'examples/bpe.c',
          'examples/bpe.h', 'examples/unicode_numbers.h']
source_paths = [here / 'probe_counterbalanced.c', Path(__file__).resolve(),
                root / 'training/train_mlp.c', root / 'src/infer.c',
                *[root / 'deps/notorch' / p for p in native]]
compile_cmd = ['cc', '-Ideps/notorch', '-Itraining', '-O2', '-Wall', '-Wextra',
               '-std=gnu11', '-march=native', '-DUSE_SIMD', '-o',
               'build/jovovich-probe-counterbalanced', str(here / 'probe_counterbalanced.c'),
               *['deps/notorch/' + p for p in native if p.endswith('.c')], '-lm', '-pthread']
receipt = dict(schema_version=1, status='Native preflight and independent receipt consistency checks passed.',
    compile_command=compile_cmd,
    run_command=['build/jovovich-probe-counterbalanced', 'models/base-qwen.gguf',
                 'models/counterbalanced-review.bin', 'models/counterbalanced-review.pairs', '40'],
    working_directory=str(root), model_forward_calls=0, summary=summary,
    training_visits=dict(updates=100, decision_targets=5200, residual_targets=101200,
                         all_review_targets=106400, old_joint_v2_review_targets=83200,
                         review_target_exposure_ratio=1064/832),
    decision_target_counts=dict(decision_ids),
    review_common_prefix_id_sequences=[list(p) for p in sorted(prefixes)],
    native_pair_indices=[list(p) for p in pairs], per_row=metadata,
    sources=[item(p) for p in source_paths],
    artifacts=[item(root / p) for p in ['models/base-qwen.gguf',
       'models/counterbalanced-review.bin', 'models/counterbalanced-review.pairs',
       'training/sft_review_v4.jsonl', 'build/jovovich-probe-counterbalanced',
       'models/counterbalanced-review-preflight.jsonl', 'models/counterbalanced-review-preflight.stderr']])
out = here / 'native-preflight.json'
with out.open('x') as handle:
    json.dump(receipt, handle, indent=2)
    handle.write('\n')
print(json.dumps(dict(receipt=item(out), summary=summary,
                     decision_ids=dict(decision_ids), prefixes=[list(p) for p in sorted(prefixes)])))
