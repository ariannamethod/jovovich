import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

const fixture = `
import copy, json, sys
from pathlib import Path
sys.path.insert(0, 'training')
from score_decisions import score_run, corpus_map
data=[json.loads(line) for line in Path('training/sft_review_v2.jsonl').read_text().splitlines()]
prior=json.loads(Path('training/results/2026-09-29-verdict-balance/metrics.jsonl').read_text().splitlines()[0])
pairs,mapping=corpus_map(data)
native={s['row']:s for s in prior['teacher_forced_rows']}
def decisions(update,hits):
    scores=[]
    for row in sorted(mapping):
        ref=native[row]
        score={k:ref[k] for k in ('decision_position','decision_target_id','decision_alternative_id')}
        hit=row in hits
        score.update(row=row,pair_index=mapping[row]['pair_index'],decision_correct=hit,
                     decision_predicted_id=ref['decision_target_id'] if hit else ref['decision_alternative_id'],
                     decision_margin=1. if hit else -1.)
        scores.append(score)
    return dict(stage='decision_train',epoch=update,update=update,
                measurement='initial' if update==0 else 'post_update',
                snapshot_saved=update in (25,50,75,100),mean_decision_ce=.1,
                decision_positions=40,decision_correct=len(hits),decision_pairs=20,
                decision_pairs_exact=sum(a in hits and b in hits for a,b in pairs),decision_rows=scores)
def full(update,decision):
    dec={s['row']:s for s in decision['decision_rows']}
    scores=[]
    for row in range(64):
        n=native[row]['tokens']; hit=dec.get(row,{}).get('decision_correct',True)
        score=dict(row=row,tokens=n,correct=n if hit else n-1,first_error_position=-1 if hit else 3)
        if row in dec:
            score.update({k:v for k,v in dec[row].items() if k.startswith('decision_')})
            if update:
                score.pop('decision_target_id');score.pop('decision_alternative_id')
        scores.append(score)
    return dict(stage='sft_initial' if update==0 else 'sft',objective='decisions',epoch=update,
                examples=64,tokens=sum(r['tokens'] for r in scores),decision_pairs=20,
                mean_token_ce=.1,teacher_forced_correct_tokens=sum(r['correct'] for r in scores),
                teacher_forced_exact_examples=sum(r['correct']==r['tokens'] for r in scores),teacher_forced_rows=scores)
def run(pattern=None):
    pattern=pattern or {}
    zero=decisions(0,set())
    result=[full(0,zero),zero]
    for update in range(1,101):
        metric=decisions(update,pattern.get(update,set()))
        result.append(metric)
        if update in (25,50,75,100):result.append(full(update,metric))
    return result
def hits(complete,singles=0):
    return {row for pair in pairs[:complete] for row in pair} | {pairs[i][0] for i in range(complete,complete+singles)}
def at(metrics,step):return next(m for m in metrics if m['stage']=='decision_train' and m['update']==step)
def rejected(metrics,fragment):
    try: score_run(data,metrics)
    except ValueError as error:
        assert fragment in str(error), str(error)
    else: raise AssertionError('invalid metrics accepted: '+fragment)
`;

function python(code) {
  const result = spawnSync('python3', ['-c', fixture + '\n' + code], { encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr || result.stdout);
}

test('decision selector prioritizes complete pairs, then hits, then earlier eligible saved step', () => {
  python(`
# More complete pairs wins despite fewer total correct targets; 75 is never eligible.
metrics=run({25:hits(2,3),50:hits(3),75:hits(20),100:hits(3)})
result=score_run(data,metrics)
assert result['selected_update']==50 and result['selected_epoch']==50
assert result['eligible_updates']==[25,50,100]
assert len(result['trajectory'])==101
assert [s['update'] for s in result['full_readouts']]==[0,25,50,75,100]
assert result['trajectory'][75]['complete_decision_pairs']==20
assert not result['trajectory'][75]['eligible']
# Within the same pair count, total hits wins; the final tie picks the earlier step.
assert score_run(data,run({25:hits(3),50:hits(3,1),100:hits(3,1)}))['selected_update']==50
assert score_run(data,run({25:hits(3,1),50:hits(3,1),100:hits(3,1)}))['selected_update']==25
assert result['full_readouts'][2]['groups']['voice']['examples']==12
assert result['full_readouts'][2]['review_decision_pairs_exact']==3
`);
});

test('decision scoring rejects missing updates, snapshots, pair rows and false saved claims', () => {
  python(`
metrics=run()
rejected(metrics[:-1],'incomplete run')
bad=copy.deepcopy(metrics);bad.pop(1)
rejected(bad,'incomplete run')
bad=copy.deepcopy(metrics);at(bad,25)['snapshot_saved']=False
rejected(bad,'snapshot_saved')
bad=copy.deepcopy(metrics);at(bad,1)['update']=2
rejected(bad,'exactly 0..100')
bad=copy.deepcopy(metrics);at(bad,1)['decision_rows'].pop()
rejected(bad,'cover every expected row')
bad=copy.deepcopy(metrics);rows=at(bad,1)['decision_rows'];rows[-1]=copy.deepcopy(rows[0])
rejected(bad,'duplicate decision scores row')
bad=copy.deepcopy(metrics);at(bad,1)['decision_rows'][0]['pair_index']=1
rejected(bad,'explicit corpus map')
bad=copy.deepcopy(metrics);at(bad,1)['measurement']='before_update'
rejected(bad,'post-update measurement')
bad=copy.deepcopy(metrics);at(bad,1)['decision_positions']=True
rejected(bad,'invalid decision positions')
`);
});

test('decision scoring rejects contradictory IDs, margins and declared counts', () => {
  python(`
metrics=run()
bad=copy.deepcopy(metrics);at(bad,1)['decision_rows'][0].pop('decision_target_id')
rejected(bad,'incomplete decision token fields')
bad=copy.deepcopy(metrics);at(bad,1)['decision_rows'][0]['decision_alternative_id']=999
rejected(bad,'changed from initial metadata')
bad=copy.deepcopy(metrics);at(bad,1)['decision_rows'][0]['decision_correct']=True
rejected(bad,'predicted ID')
bad=copy.deepcopy(metrics);at(bad,1)['decision_rows'][0]['decision_margin']=1.
rejected(bad,'margin contradicts argmax')
bad=copy.deepcopy(metrics);at(bad,1)['decision_rows'][0]['decision_margin']=float('nan')
rejected(bad,'invalid decision margin')
bad=copy.deepcopy(metrics);at(bad,1)['decision_correct']=1
rejected(bad,'aggregate correct count')
bad=copy.deepcopy(metrics);at(bad,1)['decision_pairs_exact']=1
rejected(bad,'aggregate pair count')
bad=copy.deepcopy(metrics);bad[0]['teacher_forced_rows'][0]['decision_alternative_id']=123
rejected(bad,'not reciprocal')
# A third vocabulary token can win despite a positive target-versus-alternative margin.
good=copy.deepcopy(metrics);row=at(good,1)['decision_rows'][0]
row['decision_predicted_id']=123;row['decision_margin']=2.
result=score_run(data,good)
assert result['trajectory'][1]['groups']['concern']['positive_margin']==1
assert result['trajectory'][1]['correct_targets']==0
`);
});

test('full readouts must agree with the decision trajectory and every corpus row', () => {
  python(`
metrics=run({25:hits(1)})
bad=copy.deepcopy(metrics)
full25=next(m for m in bad if m['stage']=='sft' and m['epoch']==25)
full25['teacher_forced_rows'][0]['decision_predicted_id']=788
full25['teacher_forced_rows'][0]['decision_correct']=False
full25['teacher_forced_rows'][0]['decision_margin']=-1.
rejected(bad,'full/decision readout disagreement')
bad=copy.deepcopy(metrics)
full25=next(m for m in bad if m['stage']=='sft' and m['epoch']==25)
full25['teacher_forced_rows'][0]['decision_margin']=5.
rejected(bad,'full/decision margin disagreement')
bad=copy.deepcopy(metrics);bad[0]['teacher_forced_rows'][0]['tokens']=1
rejected(bad,'EOS or outside completion')
bad=copy.deepcopy(metrics)
full25=next(m for m in bad if m['stage']=='sft' and m['epoch']==25)
full25['teacher_forced_rows'][0]['first_error_position']=3
rejected(bad,'first-error position')
bad=copy.deepcopy(metrics)
full25=next(m for m in bad if m['stage']=='sft' and m['epoch']==25)
full25['teacher_forced_correct_tokens']+=1
rejected(bad,'aggregate')
bad=copy.deepcopy(metrics)
full25=next(m for m in bad if m['stage']=='sft' and m['epoch']==25)
full25['teacher_forced_rows'][2].update(correct=1,first_error_position=3)
rejected(bad,'first-error position')
bad=copy.deepcopy(metrics);at(bad,1)['objective']='verdict'
rejected(bad,'objective changed')
bad_data=copy.deepcopy(data);bad_data[1]['id']=bad_data[0]['id']
try:score_run(bad_data,metrics)
except ValueError as error:assert 'unique' in str(error)
else:raise AssertionError('duplicate corpus ID accepted')
`);
});

test('native argmax tie ordering is distinguished from positive-margin counts', () => {
  python(`
metrics=run()
# The clean target 788 beats alternative 66582 at an exact tie.
clean=pairs[0][1];metric=at(metrics,1)
row=next(r for r in metric['decision_rows'] if r['row']==clean)
row.update(decision_correct=True,decision_predicted_id=788,decision_margin=0.)
metric['decision_correct']=1
result=score_run(data,metrics)
assert result['trajectory'][1]['groups']['clean']['correct']==1
assert result['trajectory'][1]['groups']['clean']['positive_margin']==0
# The concern target cannot beat the lower-ID alternative at the same tie.
bad=run();metric=at(bad,1);row=metric['decision_rows'][0]
row.update(decision_correct=True,decision_predicted_id=66582,decision_margin=0.)
metric['decision_correct']=1
rejected(bad,'tie contradicts')
`);
});
