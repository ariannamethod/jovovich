"""Run the frozen counterbalanced complete-answer objective from the repository root."""
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import time

stem = 'models/counterbalanced-review'
command = ['build/jovovich-train-mlp', 'models/base-qwen.gguf', stem + '.bin',
           stem, '100', '0.0001', '40', '25', 'joint', stem + '.pairs']
env = dict(os.environ, NT_QMV_THREADS='4', NT_ATTN_THREADS='4', NT_SIMD_THREADS='4', NT_NO_I8='1')
paths = {'source': 'training/train_mlp.c', 'binary': command[0],
         'dataset_binary': stem + '.bin', 'pair_map': stem + '.pairs',
         'plan': stem + '-plan.json'}
def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()
def save(path, value):
    with open(path, 'x') as f:
        f.write(json.dumps(value, indent=2) + '\n')
receipt = {key + '_sha256': sha(value) for key, value in paths.items()}
plan = json.loads(Path(paths['plan']).read_text())
assert not os.environ.get('JOVOVICH_CHAT_TEMPLATE') and not os.environ.get('JOVOVICH_INFER')
for key, path in paths.items():
    if key != 'plan':
        assert receipt[key + '_sha256'] == plan['frozen_training'][key]['sha256']
for group in ('frozen_training', 'frozen_evaluation'):
    for item in plan[group].values():
        assert sha(item['path']) == item['sha256'], item['path']
assert sha('models/base-qwen.gguf') == plan['fixed_training']['base_sha256']
assert sha(__file__) == plan['training_runner']['sha256']
for suffix in ('-resource.json', '-metrics.jsonl', '-train.stderr', '.gate.lora',
               '.epoch25.gate.lora', '.epoch50.gate.lora', '.epoch75.gate.lora', '.epoch100.gate.lora'):
    assert not Path(stem + suffix).exists(), suffix
save(stem + '-training-source.json', receipt)
print(json.dumps(dict(phase='training', command=command, **receipt)), flush=True)
with open(stem + '-metrics.jsonl', 'x') as out, open(stem + '-train.stderr', 'x') as err:
    started = time.monotonic()
    result = subprocess.run(command, env=env, stdout=out, stderr=err)
usage = resource.getrusage(resource.RUSAGE_CHILDREN)
unchanged = all(sha(path) == receipt[key + '_sha256'] for key, path in paths.items())
unchanged = unchanged and sha('models/base-qwen.gguf') == plan['fixed_training']['base_sha256']
unchanged = unchanged and subprocess.check_output(['git', '-C', 'deps/notorch', 'rev-parse', 'HEAD'], text=True).strip() == plan['fixed_training']['notorch_pin']
record = dict(command=command, objective='joint', elapsed_seconds=time.monotonic() - started,
              peak_rss_kib=usage.ru_maxrss, user_seconds=usage.ru_utime,
              system_seconds=usage.ru_stime, exit_code=result.returncode, sources_unchanged=unchanged)
save(stem + '-resource.json', record)
print(json.dumps(dict(phase='complete', **record)), flush=True)
assert unchanged
raise SystemExit(result.returncode)
