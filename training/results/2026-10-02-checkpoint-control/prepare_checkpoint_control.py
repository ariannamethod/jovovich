"""Build and preregister a new repeated-holdout checkpoint diagnostic; no forward calls."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, os, platform, subprocess

ROOT = Path.cwd()
OUT = Path('training/results/2026-10-02-checkpoint-control')
BIN = Path('models/checkpoint-control')
BIN.mkdir(exist_ok=False)

def now(): return datetime.now(timezone.utc).isoformat()
def binding(path):
    path = Path(path)
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''): h.update(chunk)
    return dict(path=str(path), bytes=path.stat().st_size, sha256=h.hexdigest())
def write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())

substrate = ['deps/notorch/notorch.c', 'deps/notorch/gguf.c', 'deps/notorch/harness/runtime.c',
             'deps/notorch/harness/arch_llama.c', 'deps/notorch/examples/bpe.c']
flags = ['cc','-Ideps/notorch','-Itraining','-O2','-Wall','-Wextra','-std=gnu11','-march=native']
commands = [
    flags + ['-DUSE_SIMD','-o',str(BIN/'export-saved'),str(OUT/'export_saved_mlp.c')] + substrate + ['-lm','-pthread'],
    flags + ['-DUSE_SIMD','-o',str(BIN/'probe-mlp'),'training/probe_mlp.c'] + substrate + ['-lm','-pthread'],
    flags + ['-o',str(BIN/'infer'),'src/infer.c'] + substrate + ['-lm','-pthread'],
    flags + ['-o',str(BIN/'merge-mlp'),'training/merge_mlp.c','deps/notorch/gguf.c','-lm','-pthread'],
    ['node',str(OUT/'prepare_cases.mjs')],
]
receipts=[]
env={k:v for k,v in os.environ.items() if not k.startswith('NT_')}
for i,argv in enumerate(commands):
    stem=OUT/f'prepare-{i:02d}'
    entry=dict(argv=argv,started_at=now(),stdout=str(stem)+'.stdout.txt',stderr=str(stem)+'.stderr.txt')
    write(str(stem)+'.intent.json',entry)
    with open(entry['stdout'],'xb') as out, open(entry['stderr'],'xb') as err:
        result=subprocess.run(argv,stdout=out,stderr=err,env=env)
    entry.update(exit_code=result.returncode,finished_at=now())
    write(str(stem)+'.receipt.json',entry);receipts.append(entry)
    if result.returncode: raise RuntimeError(f'preparation phase {i} failed')
recovery = json.loads(Path('training/results/2026-10-02-gradient-control/weight-recovery.json').read_text())
assert recovery['status']=='complete'
models={}
for f in recovery['files']:
    if f['local_path']=='models/base-qwen.gguf' or any(x in f['local_path'] for x in ['selected.gguf','epoch25.','epoch100.','matched-review.bin']):
        actual=binding(f['local_path'])
        assert actual['bytes']==f['actual']['bytes'] and actual['sha256']==f['actual']['sha256']
        models[actual['path']]=actual
assert len(models)==9
source_paths=substrate + ['deps/notorch/notorch.h','deps/notorch/gguf.h','deps/notorch/notorch_simd.h',
 'deps/notorch/harness/runtime.h','deps/notorch/harness/arch.h','deps/notorch/harness/arch_models.h',
 'deps/notorch/examples/bpe.h','deps/notorch/examples/unicode_numbers.h','training/train_mlp.c',
 'training/probe_mlp.c','training/merge_mlp.c','src/infer.c','bin/jovovich.mjs','prompts/identity.txt',
 'training/review_holdout_v5.jsonl','training/holdout_v5_design.json',
 'training/results/2026-09-29-small-step/probe_shared_prefix.mjs',
 'training/results/2026-09-29-verdict-balance/verify_verdict_export.py',
 'training/results/2026-09-29-convergence/check_convergence_export.py',
 'training/results/2026-10-01-matched-protections/protocol.json',
 'training/results/2026-10-02-gradient-control/weight-recovery.json']
source_paths += [str(OUT/n) for n in ['export_saved_mlp.c','prepare_cases.mjs','evaluate_checkpoints.mjs',
                                     'prepare_checkpoint_control.py','run_checkpoint_control.py','cases.jsonl']]
source_paths += [str(BIN/n) for n in ['export-saved','probe-mlp','infer','merge-mlp']]
bindings=[binding(p) for p in source_paths]+list(models.values())
cases=[json.loads(line) for line in (OUT/'cases.jsonl').read_text().splitlines()]
old=json.loads(Path('training/results/2026-10-01-matched-protections/protocol.json').read_text())
plan=dict(schema='jovovich.checkpoint-control.v1',frozen_at=now(),status='frozen_before_any_generation',
 question='Does the saved update100 checkpoint improve natural grounded reviews over the originally selected update25 checkpoint of the same v5 run?',
 scope='New repeated-holdout diagnostic, not reconstruction of deleted historical responses. The 24 v5 holdout cases have previously been inspected; they are not an untouched confirmation set.',
 arms=['update25','update100'],case_count=24,pair_count=12,family_count=6,
 primary='Number of fully grounded concern/clean pairs on the same 12 pairs; retain individual, parser, and stop counts.',
 manual_rubric=old['full_answer_judgment'],
 adjudication='Generator does not assign semantic judgments. Root and a separate auditor read complete response/prompt pairs; preserve explicit sensitivity decisions.',
 no_changes=['No retraining','No changed original checkpoint selection rule','No new runtime promotion','No forced answer prefix'],
 parity=dict(rows=[0,1,2],both_arms=True,criteria='Unmodified training/probe_mlp.c: all argmax agree, residual/logit relative L2 <=1e-5, batch CE delta <=1e-4.'),
 export='Load exact recovered gate/up/down LoRA into unchanged native bank, native snapshot; merge update100 with existing merger; independent GGUF byte audit for both arms before parity/generation.',
 cases=binding(OUT/'cases.jsonl'),case_order=[c['name'] for c in cases],runner=binding(BIN/'infer'),
 decoding=dict(temperature=0,continuation_tokens=192,context=8192,threads=2,NT_NO_I8='1',mode='natural',chat_template='chatml'),
 native_environment={'NT_NO_I8':'1','NT_QMV_THREADS':'2','NT_ATTN_THREADS':'2','NT_SIMD_THREADS':'2'},
 scheduling=dict(max_parallel_workers=2,one_worker_per_arm=True,case_order='source order',max_emitted_tokens=9216,
  environment='Strip inherited NT_* settings before applying recorded native environment.'),
 model_inputs=models,bindings=bindings,build=receipts,
 provenance=dict(git_head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
  notorch_commit=subprocess.check_output(['git','-C','deps/notorch','rev-parse','HEAD'],text=True).strip(),
  hf_repository='ataeff/jovovich',hf_revision='c9484feec99c5df47be5702d29098297aced1389',
  platform=platform.platform(),python=platform.python_version(),node=subprocess.check_output(['node','--version'],text=True).strip()),
 model_forward_calls_so_far=0)
write(OUT/'protocol.json',plan)
print(json.dumps(binding(OUT/'protocol.json')))
