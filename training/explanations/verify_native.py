#!/usr/bin/env python3
"""Check the complete order-control corpora with the native Qwen tokenizer."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'training'))
from prepare import prepare, review_pairs, review_prefixes


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def binding(path):
    path = Path(path).resolve()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest}


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def command(argv, out, name, jsonl=False):
    receipt = {'argv': list(map(str, argv)), 'started_utc': datetime.now(timezone.utc).isoformat()}
    save(out / (name + '.intent.json'), receipt)
    so, se = out / (name + '.stdout.txt'), out / (name + '.stderr.txt')
    with so.open('xb') as stdout, se.open('xb') as stderr:
        result = subprocess.run(receipt['argv'], cwd=ROOT, stdout=stdout, stderr=stderr)
    receipt.update(return_code=result.returncode, finished_utc=datetime.now(timezone.utc).isoformat(),
                   stdout=binding(so), stderr=binding(se))
    save(out / (name + '.receipt.json'), receipt)
    require(result.returncode == 0, name + ' failed; evidence retained')
    return [json.loads(line) for line in so.read_text().splitlines()] if jsonl else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    base, out = args.base.resolve(), args.out.resolve()
    require(not out.exists(), 'output directory must be new')
    model = json.loads((ROOT / 'model.json').read_text())
    sources = [Path(__file__).resolve(), *[ROOT / p for p in (
        'Makefile', 'training/train_mlp.c', 'training/probe_pairs.c',
        'training/probe_tokenization.c', 'src/infer.c', 'training/prepare.py',
        'training/explanations/build_corpora.py', 'training/explanations/reasons.json',
        'training/sft_review_v5.jsonl', 'training/sft_review_v6_before.jsonl',
        'training/sft_review_v6_after.jsonl', 'deps/notorch/examples/bpe.c',
        'deps/notorch/examples/bpe.h', 'deps/notorch/notorch.c', 'deps/notorch/notorch.h',
        'deps/notorch/gguf.c', 'deps/notorch/gguf.h', 'deps/notorch/harness/runtime.c',
        'deps/notorch/harness/arch_llama.c')]]
    frozen = [binding(p) for p in [base, *sources]]
    require(frozen[0]['sha256'] == model['sha256'] and frozen[0]['bytes'] == model['bytes'],
            'base differs from pinned model.json')
    out.mkdir(parents=True)
    save(out / 'bindings.json', {'files': frozen, 'notorch_commit': subprocess.check_output(
        ['git', '-C', str(ROOT / 'deps/notorch'), 'rev-parse', 'HEAD'], text=True).strip()})
    command(['make', '-j2', 'probe-pairs', 'probe-tokenization'], out, 'build')
    binaries = [ROOT / 'build/jovovich-probe-pairs', ROOT / 'build/jovovich-probe-tokenization']
    built = [binding(p) for p in binaries]
    save(out / 'binary-bindings.json', {'files': built})
    original = [json.loads(s) for s in (ROOT / 'training/sft_review_v5.jsonl').read_text().splitlines()]
    corpora, maps, datasets, summaries = {}, {}, [], {}
    for arm in ('before', 'after'):
        source = ROOT / ('training/sft_review_v6_' + arm + '.jsonl')
        data = [json.loads(s) for s in source.read_text().splitlines()]
        require(len(data) == len(original) == 76, 'wrong corpus length')
        corpora[arm] = data
        dataset, pairs = out / (arm + '.bin'), out / (arm + '.pairs.bin')
        prepare(source, None, dataset, pairs, pair_format=2)
        records = command([binaries[0], base, dataset, pairs], out, arm, jsonl=True)
        require(records[0] == {'stage': 'pair_configuration', 'pair_map_version': 2, 'rows': 76, 'pairs': 26},
                'native pair configuration differs')
        require(records[-1] == {'stage': 'pair_completion', 'pass': True, 'review_rows': 52},
                'native probe incomplete')
        rows = {r['row']: r for r in records[1:-1]}
        require(len(rows) == len(records) - 2 == 52, 'native duplicate/missing review')
        require(set(rows) == {i for pair in review_pairs(data) for i in pair}, 'native review coverage differs')
        prefixes = review_prefixes(data)
        for i, row in rows.items():
            require(row['decision_prefix'] == prefixes[i] and
                    row['decision_prefix_bytes'] == len(prefixes[i].encode()), 'prefix provenance mismatch')
            require(row['total_tokens'] == row['prompt_tokens'] + len(row['answer_ids']), 'token counts differ')
            require(row['prompt_tokens'] + 512 <= 8192, 'generation context capacity exceeded')
            require(row['total_tokens'] < 4096, 'training context capacity exceeded')
            require(len(row['answer_ids']) <= 512, 'gold answer exceeds shared generation budget')
        maps[arm] = rows
        summaries[arm] = {'review_rows': len(rows), 'pairs': len(review_pairs(data)),
                          'decision_tokens': len(rows),
                          'residual_tokens': sum(len(r['answer_ids']) - 1 for r in rows.values()),
                          'max_prompt_tokens': max(r['prompt_tokens'] for r in rows.values()),
                          'max_answer_tokens_including_eos': max(len(r['answer_ids']) for r in rows.values()),
                          'verdict_position_min': min(r['decision_position'] for r in rows.values()),
                          'verdict_position_max': max(r['decision_position'] for r in rows.values())}
        datasets.append(dataset)
    comparisons = []
    for i, old in enumerate(original):
        before, after = corpora['before'][i], corpora['after'][i]
        if old['kind'] != 'review':
            require(before == after == old, 'nonreview row changed')
            continue
        require(before['messages'][:2] == after['messages'][:2], 'arm prompts differ')
        a = json.loads(before['messages'][2]['content']); b = json.loads(after['messages'][2]['content'])
        require(list(a) == ['analysis', 'findings'] and list(b) == ['findings', 'analysis'], 'wrong key order')
        require(a == b and a['findings'] == json.loads(old['messages'][2]['content'])['findings'],
                'arm content/original findings differ')
        ra, rb = maps['before'][i], maps['after'][i]
        require(ra['prompt_tokens'] == rb['prompt_tokens'], 'native prompt counts differ')
        require(ra['decision_position'] > rb['decision_position'], 'before verdict did not move after analysis')
        require((ra['decision_target_id'], ra['decision_alternative_id']) ==
                (rb['decision_target_id'], rb['decision_alternative_id']), 'arm verdict target IDs differ')
        comparisons.append({'id': old['id'], 'row': i, 'before_position': ra['decision_position'],
                            'after_position': rb['decision_position'],
                            'before_answer_tokens': len(ra['answer_ids']), 'after_answer_tokens': len(rb['answer_ids']),
                            'target_id': ra['decision_target_id'], 'alternative_id': ra['decision_alternative_id']})
    alignment = command([binaries[1], base, *datasets], out, 'chatml', jsonl=True)
    require(len(alignment) == 2 and all(r['pass'] and r['failures'] == 0 for r in alignment), 'ChatML mismatch')
    require(frozen == [binding(Path(f['path'])) for f in frozen], 'source/input changed during verification')
    require(built == [binding(Path(f['path'])) for f in built], 'binary changed during verification')
    report = {'status': 'pass', 'arms': summaries, 'identical_prompt_and_content_rows': len(comparisons),
              'unchanged_nonreview_rows': 24, 'native_chatml_comparisons': sum(r['comparisons'] for r in alignment),
              'comparisons': comparisons, 'inference_calls': 0, 'training_updates': 0}
    save(out / 'verification.json', report)
    print(json.dumps({k: v for k, v in report.items() if k != 'comparisons'}))


if __name__ == '__main__':
    main()
