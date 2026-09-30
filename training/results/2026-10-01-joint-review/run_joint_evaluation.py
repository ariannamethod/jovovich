"""Select once, audit the export, and run the frozen generation cohorts."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path.cwd()
here = Path(__file__).resolve().parent
stem = 'models/joint-review'
arm = sys.argv[1]
assert arm in ('control', 'joint') and len(sys.argv) == 2
def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()
def save(path, value):
    with open(path, 'x') as f:
        f.write(json.dumps(value, indent=2) + '\n')
def readl(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines()]
plan = json.loads(Path(stem + '-plan.json').read_text())
for item in plan['frozen_evaluation'].values():
    assert sha(item['path']) == item['sha256'], item['path']
env = dict(os.environ, NT_NO_I8='1', NT_QMV_THREADS='2', NT_ATTN_THREADS='2', NT_SIMD_THREADS='2')
if arm == 'joint':
    result = json.loads(Path(stem + '-resource.json').read_text())
    assert result['exit_code'] == 0 and result['sources_unchanged']
    subprocess.run(['python3', 'training/score_decisions.py', stem + '-metrics.jsonl',
                    '--output', stem + '-scores.json'], check=True)
    scores = json.loads(Path(stem + '-scores.json').read_text())
    update = scores['selected_update']
    assert update in (25, 50, 100)
    print(json.dumps(dict(phase='selected', update=update)), flush=True)
    prefix = f'{stem}.epoch{update:02d}'
    model = stem + '-selected.gguf'
    physical = Path('/tmp/jovovich-joint-review-selected-2948c91.gguf')
    assert not physical.exists() and not Path(model).exists()
    subprocess.run(['build/jovovich-merge-mlp', 'models/base-qwen.gguf', prefix, str(physical)], check=True)
    Path(model).symlink_to(physical)
    subprocess.run(['python3', 'training/results/2026-09-29-verdict-balance/verify_verdict_export.py',
                    'models/base-qwen.gguf', model, prefix, stem + '-export-audit.json'], check=True)
    before = sha(model)
    with open(stem + '-parity.jsonl', 'x') as out, open(stem + '-parity.stderr', 'x') as err:
        subprocess.run(['build/jovovich-probe-mlp', 'models/base-qwen.gguf', model,
                        stem + '.bin', prefix, '0', '1', '2'], env=env, stdout=out, stderr=err, check=True)
    assert sha(model) == before
    save(stem + '-selected-model.json', dict(path=model, update=update, bytes=Path(model).stat().st_size, sha256=before))
    print(json.dumps(dict(phase='export_verified', update=update, sha256=before)), flush=True)
else:
    model = 'models/decision-small-step-selected.gguf'
    before = sha(model)
    assert before == plan['comparator']['model_sha256']
cohorts = [('train','shared'), ('audit','natural'), ('audit','shared')]
if arm == 'joint':
    cohorts = [('train','natural'), ('diagnostics','natural'), *cohorts]
jobs = []
for kind, mode in cohorts:
    for shard in ((0,1) if kind == 'train' else (None,)):
        name = f'{arm}-{kind}-{mode}' + (f'-{shard}' if shard is not None else '')
        output = stem + '-' + name + '.jsonl'
        command = ['node', str(here / 'evaluate_joint_reviews.mjs'), '--model', model,
                   '--kind', kind, '--mode', mode, '--output', output,
                   '--trace-dir', stem + '-' + name + '-traces']
        if shard is not None:
            command += ['--shard', str(shard)]
        jobs.append((name, command, output))
def evaluate(job):
    name, command, output = job
    print(json.dumps(dict(phase='evaluating', job=name)), flush=True)
    started = time.monotonic()
    with open(stem + '-' + name + '.stderr', 'x') as err, open(stem + '-' + name + '.stdout', 'x') as out:
        result = subprocess.run(command, env=env, stdout=out, stderr=err)
    record = dict(job=name, command=command, output=output, exit_code=result.returncode,
                  elapsed_seconds=time.monotonic() - started)
    assert result.returncode == 0, record
    print(json.dumps(dict(phase='evaluated', **record)), flush=True)
    return record
with concurrent.futures.ThreadPoolExecutor(max_workers=2 if arm=='control' else 4) as pool:
    completed = list(pool.map(evaluate, jobs))
save(stem + '-' + arm + '-evaluation-jobs.json', completed)
ids = [r['id'] for r in readl('training/sft_review_v2.jsonl') if r['kind']=='review']
for kind, mode in cohorts:
    if kind != 'train':
        continue
    path = f'{stem}-{arm}-{kind}-{mode}'
    rows = readl(path+'-0.jsonl') + readl(path+'-1.jsonl')
    by_name = {r['name']:r for r in rows}
    assert len(rows) == len(by_name) == 40 and set(by_name)==set(ids)
    with open(path+'.jsonl', 'x') as f:
        f.write(''.join(json.dumps(by_name[name], ensure_ascii=False)+'\n' for name in ids))
assert sha(model) == before
for item in plan['frozen_evaluation'].values():
    assert sha(item['path']) == item['sha256'], item['path']
save(stem + '-' + arm + '-evaluation-model-check.json', dict(sha256=before, unchanged=True))
print(json.dumps(dict(phase='complete', arm=arm, cases=56 if arm=='control' else 108)), flush=True)
