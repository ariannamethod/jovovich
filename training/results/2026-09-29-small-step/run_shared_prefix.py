"""Run the predeclared shared-prefix diagnostic after the matched natural reviews."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

here = Path(__file__).resolve().parent
plan_path = here / 'shared-prefix-plan.json'
probe = here / 'probe_shared_prefix.mjs'
stem = 'models/shared-prefix'

def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

preflight = dict(plan_sha256=sha(plan_path), probe_sha256=sha(probe),
                 created_unix_seconds=time.time(), generations=80, global_workers=4)
with open(stem + '-preflight.json', 'x') as f:
    json.dump(preflight, f, indent=2)
    f.write('\n')
print(json.dumps(dict(phase='plan_fixed', **preflight)), flush=True)
while not Path('models/decision-small-step-evaluation-model-check.json').exists():
    resource_path = Path('models/decision-small-step-resource.json')
    if resource_path.exists():
        assert json.loads(resource_path.read_text())['exit_code'] == 0
    time.sleep(5)
assert sha(plan_path) == preflight['plan_sha256'] and sha(probe) == preflight['probe_sha256']
selected = json.loads(Path('models/decision-small-step-selected-model.json').read_text())
models = dict(control='models/decision-only-selected.gguf', new=selected['path'])
expected = dict(control='a762677b82851868fb3c328c8c824b133c697c05bcd728662b71faa9da395518',
                new=selected['sha256'])
natural = dict(control='training/results/2026-09-29-decision-only/train-generation.jsonl',
               new='models/decision-small-step-train-generation.jsonl')
for arm, model in models.items():
    assert sha(model) == expected[arm]
jobs = [(arm, shard) for arm in models for shard in (0, 1)]
env = dict(os.environ, NT_NO_I8='1', NT_QMV_THREADS='2', NT_ATTN_THREADS='2', NT_SIMD_THREADS='2')

def run(job):
    arm, shard = job
    output = f'{stem}-{arm}-{shard}.jsonl'
    command = ['node', str(probe), models[arm], natural[arm], output, '--shard', str(shard)]
    started = time.monotonic()
    print(json.dumps(dict(phase='evaluating', arm=arm, shard=shard)), flush=True)
    with open(f'{stem}-{arm}-{shard}.stdout', 'x') as out, open(f'{stem}-{arm}-{shard}.stderr', 'x') as err:
        result = subprocess.run(command, env=env, stdout=out, stderr=err)
    record = dict(arm=arm, shard=shard, command=command, exit_code=result.returncode,
                  elapsed_seconds=time.monotonic() - started)
    if result.returncode:
        raise RuntimeError(record)
    print(json.dumps(dict(phase='evaluated', **record)), flush=True)
    return record

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    records = list(pool.map(run, jobs))
Path(stem + '-jobs.json').write_text(json.dumps(records, indent=2) + '\n')
ids = [r['id'] for r in map(json.loads, Path('training/sft_review_v2.jsonl').read_text().splitlines()) if r['kind'] == 'review']
combined = {}
for arm, model in models.items():
    rows = []
    for shard in (0, 1):
        rows += [json.loads(s) for s in Path(f'{stem}-{arm}-{shard}.jsonl').read_text().splitlines()]
    keyed = {r['name']: r for r in rows}
    assert len(rows) == len(keyed) == len(ids) == 40 and set(keyed) == set(ids)
    assert all(r['returncode'] == 0 and r['native_boundary_verified'] and
               r['model_sha256'] == expected[arm] and r['probe_source_sha256'] == preflight['probe_sha256']
               for r in rows)
    combined[arm] = [keyed[name] for name in ids]
    with open(f'{stem}-{arm}.jsonl', 'x') as f:
        f.write(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in combined[arm]))
    assert sha(model) == expected[arm]
for previous, current in zip(combined['control'], combined['new']):
    for field in ('name', 'original_prompt_sha256', 'supplied_prompt_sha256',
                  'original_prompt_ids', 'supplied_prompt_ids', 'gold_next_id_verified'):
        assert previous[field] == current[field], (current['name'], field)
assert sha(plan_path) == preflight['plan_sha256'] and sha(probe) == preflight['probe_sha256']
Path(stem + '-verification.json').write_text(json.dumps(dict(models_sha256=expected,
    unchanged=True, matched_native_prefixes=40, generated_responses=80, **preflight), indent=2) + '\n')
print(json.dumps(dict(phase='complete', matched_native_prefixes=40, generated_responses=80)), flush=True)
