"""Run the fixed decision-only control from the repository root."""
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import time

stem = 'models/decision-only'
command = ['build/jovovich-train-mlp', 'models/base-qwen.gguf', stem + '.bin',
           stem, '100', '0.001', '40', '25', 'decisions', stem + '.pairs']
env = dict(os.environ, NT_QMV_THREADS='4', NT_ATTN_THREADS='4', NT_SIMD_THREADS='4')
paths = {'source': 'training/train_mlp.c', 'binary': command[0],
         'dataset_binary': stem + '.bin', 'pair_map': stem + '.pairs',
         'plan': stem + '-plan.json'}
receipt = {key + '_sha256': hashlib.sha256(Path(value).read_bytes()).hexdigest()
           for key, value in paths.items()}
Path(stem + '-training-source.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(dict(phase='training', command=command, **receipt)), flush=True)
with open(stem + '-metrics.jsonl', 'x') as out, open(stem + '-train.stderr', 'x') as err:
    started = time.monotonic()
    result = subprocess.run(command, env=env, stdout=out, stderr=err)
usage = resource.getrusage(resource.RUSAGE_CHILDREN)
record = dict(command=command, objective='decisions', elapsed_seconds=time.monotonic() - started,
              peak_rss_kib=usage.ru_maxrss, user_seconds=usage.ru_utime,
              system_seconds=usage.ru_stime, exit_code=result.returncode)
Path(stem + '-resource.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(dict(phase='complete', **record)), flush=True)
raise SystemExit(result.returncode)
