"""Run the predeclared verdict arm after training, selecting before generation."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

root = Path.cwd()
reference = root / 'training/results/2026-09-29-verdict-balance'
os.chdir(root)
stem = 'models/verdict-balance'

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
metrics = [json.loads(s) for s in Path(stem + '-metrics.jsonl').read_text().splitlines()]
assert len(metrics) == 13 and metrics[-1]['epoch'] == 12
subprocess.run(['python3', 'training/score_training.py', stem + '-metrics.jsonl',
                '--checkpoint-every', '4', '--output', stem + '-scores.json'], check=True)
scores = json.loads(Path(stem + '-scores.json').read_text())
epoch = scores['runs'][0]['selected_epoch']
assert epoch in (4, 8, 12)
print(json.dumps(dict(phase='selected', epoch=epoch)), flush=True)
prefix = f'{stem}.epoch{epoch:02d}'
model = stem + '-selected.gguf'
env = dict(os.environ, NT_NO_I8='1', NT_QMV_THREADS='2', NT_ATTN_THREADS='2', NT_SIMD_THREADS='2')
subprocess.run(['build/jovovich-merge-mlp', 'models/base-qwen.gguf', prefix, model], check=True)
subprocess.run(['python3', str(reference / 'verify_verdict_export.py'), 'models/base-qwen.gguf',
                model, prefix, stem + '-export-audit.json'], check=True)
before = sha(model)
with open(stem + '-parity.jsonl', 'x') as out, open(stem + '-parity.stderr', 'x') as err:
    subprocess.run(['build/jovovich-probe-mlp', 'models/base-qwen.gguf', model,
                    stem + '.bin', prefix, '0', '1', '2'], env=env, stdout=out, stderr=err, check=True)
assert sha(model) == before
model_record = dict(path=model, epoch=epoch, bytes=Path(model).stat().st_size, sha256=before)
Path(stem + '-selected-model.json').write_text(json.dumps(model_record, indent=2) + '\n')
print(json.dumps(dict(phase='export_verified', **model_record)), flush=True)
rows = [json.loads(s) for s in Path('training/sft_review_v2.jsonl').read_text().splitlines()]
jobs = []
for shard in (0, 1):
    output = f'{stem}-train-generation-{shard}.jsonl'
    jobs.append((f'train-{shard}', ['python3', 'training/evaluate.py', model,
                 '--sft', 'training/sft_review_v2.jsonl', '--tokens', '192', '--threads', '2',
                 '--output', output, '--names', *(r['id'] for r in rows[shard::2])]))
jobs.extend([
    ('review', ['node', 'training/evaluate_review.mjs', '--model', model,
                '--cases', 'training/review_holdout_v2.jsonl', '--tokens', '192',
                '--output', stem + '-review.jsonl']),
    ('voice', ['python3', 'training/evaluate.py', model, '--cases', 'training/voice_cases_v2.jsonl',
               '--identity', 'prompts/identity.txt', '--tokens', '128', '--threads', '2',
               '--output', stem + '-voice.jsonl']),
    ('prefix', ['node', str(reference / 'probe_verdict_prefix.mjs'), model,
                'models/verdict-prefix-new.jsonl']),
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
assert len(generated) == len(by_name) == len(rows)
ordered = [by_name[r['id']] for r in rows]
Path(stem + '-train-generation.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in ordered))
assert sha(model) == before
Path(stem + '-evaluation-model-check.json').write_text(json.dumps(dict(sha256=before, unchanged=True), indent=2) + '\n')
print(json.dumps(dict(phase='complete', generation_counts=dict(training=64, review=12, voice=8, prefix=4))), flush=True)
