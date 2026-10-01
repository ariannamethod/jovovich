"""Collect four completed manual readings without changing their case judgments."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
FRAGMENTS = {
    'control-train-manual-judgments.json': ('control', {'train-natural': 52}),
    'control-eval-manual-judgments.json': ('control', {'transfer-natural': 24, 'diagnostics-natural': 12}),
    'counterbalanced-train-manual-judgments.json': ('counterbalanced', {'train-natural': 52}),
    'counterbalanced-eval-manual-judgments.json': ('counterbalanced', {'transfer-natural': 24, 'diagnostics-natural': 12}),
}
sources, cases, seen = [], [], set()
for name, (arm, expected) in FRAGMENTS.items():
    path = HERE / name
    data = path.read_bytes()
    fragment = json.loads(data)
    counts = dict.fromkeys(expected, 0)
    for case in fragment['cases']:
        assert case['arm'] == arm and case['cohort'] in counts, name
        key = case['arm'], case['cohort'], case['id']
        assert key not in seen, key
        seen.add(key)
        counts[case['cohort']] += 1
        cases.append(case)
    assert counts == expected, (name, counts, expected)
    sources.append({'path': str(path), 'sha256': hashlib.sha256(data).hexdigest()})
assert len(cases) == 176
result = {
    'method': (
        'Manual reading of every complete prompt and answer under the frozen rubric. '
        'A genuine detected issue is separate from an entirely grounded, causally cited '
        'and production-accepted review. Correct paraphrases and causal alternative '
        'citations are allowed; every additional material claim must be supported. '
        'Empty and malformed answers are retained. Hash-bound individual fragments '
        'preserve the readings; this helper only combines them and assigns no labels.'
    ),
    'sources': sources,
    'cases': cases,
}
with (HERE / 'counterbalanced-manual-judgments.json').open('x') as stream:
    stream.write(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
print(json.dumps({'fragments': len(sources), 'cases': len(cases)}))
