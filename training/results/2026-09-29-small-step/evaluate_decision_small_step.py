"""Select before generation, verify the export, and run the fixed 56 review probes."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

root = Path.cwd()
stem = 'models/decision-small-step'
prior = Path('training/results/2026-09-29-verdict-balance')

def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()

while not Path(stem + '-resource.json').exists():
    time.sleep(5)
resource = json.loads(Path(stem + '-resource.json').read_text())
assert resource['exit_code'] == 0, resource
receipt = json.loads(Path(stem + '-training-source.json').read_text())
assert sha('training/train_mlp.c') == receipt['source_sha256']
subprocess.run(['python3', 'training/score_decisions.py', stem + '-metrics.jsonl',
                '--output', stem + '-scores.json'], check=True)
scores = json.loads(Path(stem + '-scores.json').read_text())
update = scores['selected_update']
assert update in (25, 50, 100)
print(json.dumps(dict(phase='selected', update=update)), flush=True)
prefix = f'{stem}.epoch{update:02d}'
model = stem + '-selected.gguf'
physical_model = Path('/tmp/jovovich-decision-small-step-selected-e655134.gguf')
assert not physical_model.exists() and not Path(model).exists()
subprocess.run(['build/jovovich-merge-mlp', 'models/base-qwen.gguf', prefix, str(physical_model)], check=True)
Path(model).symlink_to(physical_model)
subprocess.run(['python3', str(prior / 'verify_verdict_export.py'), 'models/base-qwen.gguf',
                model, prefix, stem + '-export-audit.json'], check=True)
before = sha(model)
env = dict(os.environ, NT_NO_I8='1', NT_QMV_THREADS='2', NT_ATTN_THREADS='2', NT_SIMD_THREADS='2')
with open(stem + '-parity.jsonl', 'x') as out, open(stem + '-parity.stderr', 'x') as err:
    subprocess.run(['build/jovovich-probe-mlp', 'models/base-qwen.gguf', model,
                    stem + '.bin', prefix, '0', '1', '2'], env=env, stdout=out, stderr=err, check=True)
assert sha(model) == before
model_record = dict(path=model, update=update, epoch=update, bytes=Path(model).stat().st_size, sha256=before)
Path(stem + '-selected-model.json').write_text(json.dumps(model_record, indent=2) + '\n')
print(json.dumps(dict(phase='export_verified', **model_record)), flush=True)
rows = [json.loads(s) for s in Path('training/sft_review_v2.jsonl').read_text().splitlines()]
reviews = [r for r in rows if r['kind'] == 'review']
assert len(reviews) == 40
jobs = []
for shard in (0, 1):
    output = f'{stem}-train-generation-{shard}.jsonl'
    jobs.append((f'train-{shard}', ['python3', 'training/evaluate.py', model,
                 '--sft', 'training/sft_review_v2.jsonl', '--tokens', '192', '--threads', '2',
                 '--output', output, '--names', *(r['id'] for r in reviews[shard::2])]))
jobs.extend([
    ('review', ['node', 'training/evaluate_review.mjs', '--model', model,
                '--cases', 'training/review_holdout_v2.jsonl', '--tokens', '192',
                '--output', stem + '-review.jsonl']),
    ('prefix', ['node', str(prior / 'probe_verdict_prefix.mjs'), model, stem + '-prefix.jsonl']),
])

def evaluate(job):
    name, command = job
    print(json.dumps(dict(phase='evaluating', job=name)), flush=True)
    started = time.monotonic()
    with open(f'{stem}-{name}.stderr', 'x') as err:
        result = subprocess.run(command, env=env, stdout=subprocess.DEVNULL, stderr=err)
    record = dict(job=name, command=command, exit_code=result.returncode,
                  elapsed_seconds=time.monotonic() - started)
    if name == 'review' and result.returncode == 2:
        output = [json.loads(s) for s in Path(stem + '-review.jsonl').read_text().splitlines()]
        assert len(output) == 12 and all(r['error'] is None or r['error']['phase'] == 'parse' for r in output)
    elif result.returncode != 0:
        raise RuntimeError(record)
    print(json.dumps(dict(phase='evaluated', **record)), flush=True)
    return record

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    completed = list(pool.map(evaluate, jobs))
Path(stem + '-evaluation-jobs.json').write_text(json.dumps(completed, indent=2) + '\n')
generated = []
for shard in (0, 1):
    generated += [json.loads(s) for s in Path(f'{stem}-train-generation-{shard}.jsonl').read_text().splitlines()]
by_name = {r['name']: r for r in generated}
assert len(generated) == len(by_name) == len(reviews)
ordered = [by_name[r['id']] for r in reviews]
Path(stem + '-train-generation.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in ordered))
assert sha(model) == before
Path(stem + '-evaluation-model-check.json').write_text(json.dumps(dict(sha256=before, unchanged=True), indent=2) + '\n')
print(json.dumps(dict(phase='complete', generation_counts=dict(training_reviews=40, diagnostic_reviews=12, prefix=4))), flush=True)
