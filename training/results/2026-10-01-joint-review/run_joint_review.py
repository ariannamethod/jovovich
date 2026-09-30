"""Run the frozen complete-answer objective from the repository root."""
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import time

stem = 'models/joint-review'
command = ['build/jovovich-train-mlp', 'models/base-qwen.gguf', stem + '.bin',
           stem, '100', '0.0001', '40', '25', 'joint', stem + '.pairs']
env = dict(os.environ, NT_QMV_THREADS='4', NT_ATTN_THREADS='4', NT_SIMD_THREADS='4', NT_NO_I8='1')
paths = {'source': 'training/train_mlp.c', 'binary': command[0],
         'dataset_binary': stem + '.bin', 'pair_map': stem + '.pairs',
         'plan': stem + '-plan.json'}
def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path, value):
    with open(path, 'x') as f:
        f.write(json.dumps(value, indent=2) + '\n')
receipt = {key + '_sha256': sha(value) for key, value in paths.items()}
plan = json.loads(Path(paths['plan']).read_text())
for key, path in paths.items():
    if key != 'plan':
        assert receipt[key + '_sha256'] == plan['frozen_training'][key]['sha256']
save(stem + '-training-source.json', receipt)
print(json.dumps(dict(phase='training', command=command, **receipt)), flush=True)
with open(stem + '-metrics.jsonl', 'x') as out, open(stem + '-train.stderr', 'x') as err:
    started = time.monotonic()
    result = subprocess.run(command, env=env, stdout=out, stderr=err)
usage = resource.getrusage(resource.RUSAGE_CHILDREN)
unchanged = all(sha(path) == receipt[key + '_sha256'] for key, path in paths.items())
record = dict(command=command, objective='joint', elapsed_seconds=time.monotonic() - started,
              peak_rss_kib=usage.ru_maxrss, user_seconds=usage.ru_utime,
              system_seconds=usage.ru_stime, exit_code=result.returncode, sources_unchanged=unchanged)
save(stem + '-resource.json', record)
print(json.dumps(dict(phase='complete', **record)), flush=True)
assert unchanged
raise SystemExit(result.returncode)
