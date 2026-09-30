"""Bind the declared joint protocol to a fresh checkout, binaries and output paths."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess

here = Path(__file__).resolve().parent
root = Path.cwd().resolve()
def item(path):
    path = Path(path)
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return dict(path=os.path.relpath(path,root),sha256=h.hexdigest())
assert not os.environ.get('JOVOVICH_CHAT_TEMPLATE') and not os.environ.get('JOVOVICH_INFER')
p = json.loads(Path('training/results/2026-09-29-small-step/small-step-next-control.json').read_text())
assert item('models/base-qwen.gguf')['sha256'] == p['fixed_training']['base_sha256']
assert item('models/decision-small-step-selected.gguf')['sha256'] == p['comparator']['model_sha256']
assert item('training/sft_review_v2.jsonl')['sha256'] == p['fixed_training']['dataset_sha256']
assert item('models/joint-review.pairs')['sha256'] == p['fixed_training']['pair_map_sha256']
p.update(status='Frozen before training and control generation.',
         created_utc=datetime.now(timezone.utc).isoformat(),
         parent_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip())
p['frozen_training']={k:item(v) for k,v in dict(source='training/train_mlp.c',binary='build/jovovich-train-mlp',dataset_binary='models/joint-review.bin',pair_map='models/joint-review.pairs').items()}
paths=dict(infer='src/infer.c',runner='build/jovovich-infer',host='bin/jovovich.mjs',
           probe=here/'evaluate_joint_reviews.mjs',controller=here/'run_joint_evaluation.py',
           audit_cases=here/'diff-shape-audit.jsonl',corpus='training/sft_review_v2.jsonl',
           diagnostics='training/review_holdout_v2.jsonl',identity='prompts/identity.txt',
           shared_helper='training/results/2026-09-29-small-step/probe_shared_prefix.mjs',
           scorer='training/score_decisions.py',merger='build/jovovich-merge-mlp',parity='build/jovovich-probe-mlp')
p['frozen_evaluation']={k:item(v) for k,v in paths.items()}
p['training_runner']=item(here/'run_joint_review.py')
p['independent_audit']=item(here/'independent-jovovich-audit.json')
p['audit_design']={'cases':8,'blocks':['allocation-null','write-permission'],
                   'factors':['harmful vs redundant guard removal','pure deletion vs replacement with (void)0;'],
                   'selection_use':False,'training_use':False,'harmful_replacement_valid_citation_ids':[1,2]}
p['evaluation']={'new_responses':164,'control':{'train_shared':40,'audit_natural':8,'audit_shared':8},
                 'joint':{'train_natural':40,'diagnostics_natural':12,'train_shared':40,'audit_natural':8,'audit_shared':8},
                 'temperature':0,'budget_tokens':192,'threads_per_process':2,'activation_quantization':False,
                 'training_threads':4,'control_workers':2,'joint_workers':4,
                 'schedule':'Control generation may overlap training; joint generation starts after training finishes.',
                 'trace':'Actual native prompt and sampled token IDs including terminal EOS are embedded in every result row.'}
output=Path('models/joint-review-plan.json')
with output.open('x') as f:f.write(json.dumps(p,indent=2)+'\n')
print(json.dumps(dict(plan=str(output),sha256=item(output)['sha256'])))
