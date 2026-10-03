#!/usr/bin/env python3
"""Verify JVPR2 on the pinned Qwen tokenizer; no inference or training."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'training'))
from prepare import prepare, review_pairs, review_prefixes

BASE_SHA = 'e1a77721fa97d412f121878223eec81fb4ae6f271e18f922d746711f67b344d1'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def binding(path):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest}


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def command(argv, out, name):
    record = {'argv': [str(a) for a in argv],
              'started_utc': datetime.now(timezone.utc).isoformat()}
    save(out / (name + '.intent.json'), record)
    stdout, stderr = out / (name + '.jsonl'), out / (name + '.stderr.txt')
    with stdout.open('xb') as so, stderr.open('xb') as se:
        result = subprocess.run(record['argv'], cwd=ROOT, stdout=so, stderr=se)
    record.update(return_code=result.returncode,
                  finished_utc=datetime.now(timezone.utc).isoformat(),
                  stdout=binding(stdout), stderr=binding(stderr))
    save(out / (name + '.receipt.json'), record)
    require(result.returncode == 0, name + ' failed; process evidence preserved')
    return [json.loads(line) for line in stdout.read_text().splitlines()]


def probe_rows(records, count):
    require(records[-1] == {'stage': 'pair_completion', 'pass': True,
                            'review_rows': count}, 'incomplete native probe')
    rows = {r['row']: r for r in records[1:-1]}
    require(len(rows) == len(records) - 2 == count, 'duplicate or missing native row')
    return rows


def fixture(data):
    selected = review_pairs(data)[:3]
    rows = [copy.deepcopy(data[i]) for pair in selected for i in pair]
    explanations = [
        'The nearest directory rule requires Lua; the new file is Python.',
        'The local rule explicitly permits this Python analysis script, so its language belongs here.',
        'The package introduces a runtime dependency where the viewer allows built-ins only. '
        'The quoted word "findings" in this explanation is not a verdict field.',
        'The decoder is approved.',
        'Сборка требует SQLite всегда; правило разрешает его только как opt-in.',
        'SQLite is optional in this context. Проверено: the build requirement matches the supplied rule.',
    ]
    for index, row in enumerate(rows):
        original = json.loads(row['messages'][2]['content'])
        answer = {'analysis': explanations[index]}
        if index >= 4:
            answer['context'] = {'findings': 'nested tokenizer fixture decoy'}
        answer['findings'] = original['findings']
        row['messages'][2]['content'] = json.dumps(answer, ensure_ascii=False, separators=(',', ':'))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    base, out = args.base.resolve(), args.out.resolve()
    require(not out.exists(), 'output directory must be new')
    source = ROOT / 'training/sft_review_v5.jsonl'
    binaries = [ROOT / 'build/jovovich-probe-pairs', ROOT / 'build/jovovich-probe-tokenization']
    source_paths = [Path(__file__).resolve(), *[ROOT / p for p in ('training/prepare.py', 'training/train_mlp.c',
                    'training/probe_pairs.c', 'training/probe_tokenization.c',
                    'deps/notorch/examples/bpe.c', 'deps/notorch/examples/bpe.h')]]
    frozen = [binding(p) for p in [base, source, *binaries, *source_paths]]
    require(frozen[0]['sha256'] == BASE_SHA, 'base differs from pinned official Qwen')
    out.mkdir(parents=True)
    save(out / 'bindings.json', {'files': frozen, 'arithmetic': 'native tokenization only'})
    data = [json.loads(line) for line in source.read_text().splitlines()]
    short = fixture(data)
    short_path = out / 'boundary-fixture.jsonl'
    with short_path.open('x') as stream:
        for row in short:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    results, datasets = {}, []
    for name, corpus_path, corpus in (('v5', source, data), ('fixture', short_path, short)):
        outputs = {}
        for version in (1, 2):
            stem = f'{name}-v{version}'
            dataset, pairs = out / (stem + '.bin'), out / (stem + '.pairs.bin')
            prepare(corpus_path, None, dataset, pairs, pair_format=version)
            records = command([binaries[0], base, dataset, pairs], out, stem)
            require(records[0]['pair_map_version'] == version, 'wrong pair format reported')
            outputs[version] = probe_rows(records, 2 * len(review_pairs(corpus)))
        require((out / f'{name}-v1.bin').read_bytes() == (out / f'{name}-v2.bin').read_bytes(),
                'pair format changed the model dataset')
        prefixes = review_prefixes(corpus)
        comparisons = []
        for concern, clean in review_pairs(corpus):
            a, b = outputs[2][concern], outputs[2][clean]
            require(a['decision_target_id'] == b['decision_alternative_id'] and
                    b['decision_target_id'] == a['decision_alternative_id'], 'nonreciprocal IDs')
            if name == 'fixture':
                require(a['decision_position'] != b['decision_position'], 'fixture lost unequal positions')
            for index in (concern, clean):
                old, new = outputs[1][index], outputs[2][index]
                require(new['decision_prefix_bytes'] == len(prefixes[index].encode('utf-8')),
                        'native/corpus prefix byte count differs')
                require(new['decision_prefix'] == prefixes[index], 'native/corpus prefix text differs')
                require(old['answer_ids'] == new['answer_ids'], 'native full answer tokenization changed')
                fields = ('decision_position', 'decision_target_id', 'decision_alternative_id')
                if name == 'v5':
                    require(all(old[k] == new[k] for k in fields), 'legacy v5 verdict moved')
                else:
                    require(new['decision_position'] > old['decision_position'],
                            'fixture verdict did not move past explanation divergence')
                comparisons.append({'row': index, 'legacy_position': old['decision_position'],
                                    'explicit_position': new['decision_position'],
                                    'prefix_bytes': new['decision_prefix_bytes'],
                                    'target_id': new['decision_target_id'],
                                    'alternative_id': new['decision_alternative_id']})
        results[name] = comparisons
        datasets.append(out / f'{name}-v2.bin')
    alignment = command([binaries[1], base, *datasets], out, 'chatml-alignment')
    require(len(alignment) == 2 and all(r['pass'] and r['failures'] == 0 for r in alignment),
            'trainer/runtime ChatML tokenization differs')
    require(frozen == [binding(Path(item['path'])) for item in frozen], 'bound input changed')
    report = {'status': 'pass', 'base_sha256': BASE_SHA,
              'legacy_v5_review_rows_unchanged': len(results['v5']),
              'unequal_explanation_pairs_verified': len(results['fixture']) // 2,
              'native_chatml_comparisons': sum(r['comparisons'] for r in alignment),
              'comparisons': results, 'inference_calls': 0, 'training_updates': 0}
    save(out / 'verification.json', report)
    print(json.dumps({key: value for key, value in report.items() if key != 'comparisons'}))


if __name__ == '__main__':
    main()
