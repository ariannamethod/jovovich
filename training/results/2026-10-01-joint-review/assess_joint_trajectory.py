"""Compare completed joint and decision-only trajectories from the repository root."""
import hashlib
import json
from pathlib import Path

old=Path('training/results/2026-09-29-small-step')
stem='models/joint-review-'
paths=dict(control_scores=old/'scores.json',control_metrics=old/'metrics.jsonl',
           joint_scores=Path(stem+'scores.json'),joint_metrics=Path(stem+'metrics.jsonl'))
read=lambda p:json.loads(p.read_text())
readl=lambda p:[json.loads(s) for s in p.read_text().splitlines()]
scores={a:read(paths[a+'_scores']) for a in ('control','joint')}
metrics={a:readl(paths[a+'_metrics']) for a in ('control','joint')}
old0,new0=metrics['control'][0],metrics['joint'][0]
assert old0['stage']==new0['stage']=='sft_initial'
scalar_keys=['mean_token_ce','examples','tokens','rank','alpha','layer','trainable_parameters',
             'seed','teacher_forced_correct_tokens','teacher_forced_exact_examples']
for key in scalar_keys:assert old0[key]==new0[key],key
assert len(old0['teacher_forced_rows'])==len(new0['teacher_forced_rows'])==64
for a,b in zip(old0['teacher_forced_rows'],new0['teacher_forced_rows']):
    for key,value in a.items():assert b[key]==value,(a['row'],key)
def decision_rows(arm):return [m for m in metrics[arm] if m['stage']=='decision_train']
assert decision_rows('control')[0]['mean_decision_ce']==decision_rows('joint')[0]['mean_decision_ce']
result=dict(sources={k:dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for k,p in paths.items()},
            initial_readouts_identical=True,initial_compared_scalar_fields=scalar_keys,
            initial_compared_rows=64,selection_rule=scores['joint']['selection'],arms={})
for arm,s in scores.items():
    raw=decision_rows(arm)
    assert len(raw)==101 and [r['update'] for r in raw]==list(range(101))
    full=[r for r in metrics[arm] if r['stage'] in ('sft_initial','sft')]
    chosen=next(r for r in raw if r['update']==s['selected_update'])
    data=dict(selected_update=s['selected_update'],selected=s['selected'],
              one_sided_updates=sum((r['groups']['concern']['correct'],r['groups']['clean']['correct']) in ((20,0),(0,20)) for r in s['trajectory'][1:]),
              best_observed=max(s['trajectory'][1:],key=lambda r:(r['complete_decision_pairs'],r['correct_targets'],-r['update'])),
              full_readouts=s['full_readouts'])
    if arm=='joint':
        norms=[r['gradient_norm'] for r in raw[1:]]
        data.update(clipped_updates=sum(r['clipped'] for r in raw[1:]),
                    gradient_norm_min=min(norms),gradient_norm_max=max(norms),
                    clip_scale_min=min(r['clip_scale'] for r in raw[1:]),
                    initial_components={k:raw[0][k] for k in ('mean_decision_ce','mean_residual_ce','mean_joint_ce')},
                    selected_components={k:chosen[k] for k in ('mean_decision_ce','mean_residual_ce','mean_joint_ce')},
                    prefix_readouts=[dict(update=r.get('epoch',0),positions=r['prefix_positions'],correct=r['prefix_correct'],exact_examples=r['prefix_exact_examples'],examples=r['prefix_examples']) for r in full])
    result['arms'][arm]=data
output=Path(stem+'trajectory-assessment.json')
with output.open('x') as f:f.write(json.dumps(result,indent=2)+'\n')
print(json.dumps(dict(output=str(output),selected_update=scores['joint']['selected_update'],initial_readouts_identical=True)))
