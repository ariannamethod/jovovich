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
                decision_positions=len(mapping),decision_correct=len(hits),decision_pairs=len(pairs),
                decision_pairs_exact=sum(a in hits and b in hits for a,b in pairs),decision_rows=scores)
def full(update,decision):
    dec={s['row']:s for s in decision['decision_rows']}
    scores=[]
    for row in range(len(data)):
        n=native[row]['tokens']; hit=dec.get(row,{}).get('decision_correct',True)
        score=dict(row=row,tokens=n,correct=n if hit else n-1,first_error_position=-1 if hit else 3)
        if row in dec:
            score.update({k:v for k,v in dec[row].items() if k.startswith('decision_')})
            if update:
                score.pop('decision_target_id');score.pop('decision_alternative_id')
        scores.append(score)
    return dict(stage='sft_initial' if update==0 else 'sft',objective='decisions',epoch=update,
                examples=len(data),tokens=sum(r['tokens'] for r in scores),decision_pairs=len(pairs),
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

const jointFixture = `
def joint(pattern=None):
    metrics=run(pattern)
    total=sum(native[row]['tokens'] for row in mapping)
    for metric in metrics:
        if metric['stage']=='decision_train':
            update=metric['update']
            decision_ce=.1+update*.001
            residual_ce=.8-update*.002
            norm=(0.,1.,1.000001,2.5)[update%4]
            metric.update(mean_decision_ce=decision_ce,mean_residual_ce=residual_ce,
                          mean_joint_ce=decision_ce+residual_ce,
                          residual_positions=total-len(mapping),joint_positions=total,residual_lambda=1.,
                          gradient_norm=None if update==0 else norm,
                          clip_scale=None if update==0 else (1./(norm+1e-6) if norm>1 else 1.),
                          clipped=None if update==0 else norm>1,
                          gradient_measurement=None if update==0 else 'pre_update',
                          online_joint_ce=None if update==0 else .1+(update-1)*.001+.8-(update-1)*.002)
        else:
            metric['objective']='joint'
            if metric['epoch']:
                previous=metric['epoch']-1
                metric['online_mean_objective_ce']=.1+previous*.001+.8-previous*.002
            for row in metric['teacher_forced_rows']:
                if row['row'] in mapping:
                    n=row['decision_position']
                    row.update(prefix_tokens=n,prefix_correct=n,prefix_exact=True)
            metric.update(prefix_positions=sum(native[r]['decision_position'] for r in mapping),
                          prefix_correct=sum(native[r]['decision_position'] for r in mapping),
                          prefix_exact_examples=len(mapping),prefix_examples=len(mapping))
    metrics[0].update(decision_positions=len(mapping),residual_positions=total-len(mapping),joint_positions=total,
                      residual_lambda=1.,clip_limit=1.,microbatch_tokens=40)
    return metrics
def full_at(metrics,update):
    return next(m for m in metrics if m['stage'] in ('sft_initial','sft') and m['epoch']==update)
def prefix_miss(metrics,update,index):
    metric=full_at(metrics,update)
    row=next(r for r in metric['teacher_forced_rows'] if r['row']==index)
    assert row['prefix_exact']
    row.update(prefix_correct=row['prefix_tokens']-1,prefix_exact=False,
               correct=row['correct']-1,first_error_position=0)
    metric['prefix_correct']-=1
    metric['prefix_exact_examples']-=1
    metric['teacher_forced_correct_tokens']-=1
    metric['teacher_forced_exact_examples']=sum(r['correct']==r['tokens'] for r in metric['teacher_forced_rows'])
def invalid_joint(metrics,label):
    try: score_run(data,metrics)
    except ValueError: pass
    else: raise AssertionError('invalid joint metrics accepted: '+label)
`;

function jointPython(code) {
  python(jointFixture + '\n' + code);
}

test('joint scoring preserves checkpoint selection and exposes loss, gradient and prefix diagnostics', () => {
  jointPython(`
metrics=joint({25:hits(2,3),50:hits(3),75:hits(20),100:hits(3)})
# A prefix error can coexist with either a correct or an incorrect decision token.
prefix_miss(metrics,25,pairs[0][0])
prefix_miss(metrics,25,pairs[10][0])
result=score_run(data,metrics)
assert result['objective']=='joint'
assert result['joint_normalization']==dict(decision_positions=40,residual_positions=792,
    joint_positions=832,residual_lambda=1.,clip_limit=1.,microbatch_tokens=40)
assert result['selected_update']==50 and result['selected_epoch']==50
assert result['eligible_updates']==[25,50,100]
assert len(result['trajectory'])==101
assert result['trajectory'][75]['complete_decision_pairs']==20
assert not result['trajectory'][75]['eligible']
assert score_run(data,joint({25:hits(3,1),50:hits(3,1),100:hits(3,1)}))['selected_update']==25
assert score_run(data,joint({25:hits(3),50:hits(3,1),100:hits(3,1)}))['selected_update']==50
fields=('mean_residual_ce','mean_joint_ce','residual_positions','joint_positions','residual_lambda',
        'gradient_norm','clip_scale','clipped','gradient_measurement','online_joint_ce')
for update in (0,1,2,3,4,25,100):
    metric=at(metrics,update)
    summary=result['trajectory'][update]
    for field in fields: assert summary[field]==metric[field], (update,field)
assert [s['update'] for s in result['full_readouts']]==[0,25,50,75,100]
for index,correct,exact in ((0,120,40),(1,118,38)):
    readout=result['full_readouts'][index]
    assert {key:readout[key] for key in ('prefix_positions','prefix_correct','prefix_exact_examples','prefix_examples')}==dict(
        prefix_positions=120,prefix_correct=correct,prefix_exact_examples=exact,prefix_examples=40)
assert result['full_readouts'][1]['groups']['voice']['examples']==12
`);
});

test('joint scoring enforces fixed coverage and independently normalized finite losses', () => {
  jointPython(`
metrics=joint()
for field,value in (('decision_positions',39),('residual_positions',791),('joint_positions',833),
                    ('residual_positions',792.),('decision_positions',True),('residual_lambda',.5),
                    ('clip_limit',2.),('microbatch_tokens',32)):
    bad=copy.deepcopy(metrics);bad[0][field]=value
    invalid_joint(bad,'initial '+field)
for field in ('decision_positions','residual_positions','joint_positions','residual_lambda','clip_limit','microbatch_tokens'):
    bad=copy.deepcopy(metrics);bad[0].pop(field)
    invalid_joint(bad,'missing initial '+field)
for field,value in (('residual_positions',791),('joint_positions',2359),('residual_lambda',.5),
                    ('residual_positions',True),('joint_positions',832.)):
    bad=copy.deepcopy(metrics);at(bad,1)[field]=value
    invalid_joint(bad,'trajectory '+field)
for field in ('mean_decision_ce','mean_residual_ce','mean_joint_ce'):
    for value in (float('nan'),float('inf'),-.1,True):
        bad=copy.deepcopy(metrics);at(bad,1)[field]=value
        invalid_joint(bad,field+' must be finite and nonnegative')
for field in ('mean_residual_ce','mean_joint_ce','residual_positions','joint_positions','residual_lambda'):
    bad=copy.deepcopy(metrics);at(bad,1).pop(field)
    invalid_joint(bad,'missing trajectory '+field)
# Joint loss is the sum of two separately normalized means, not a pooled token mean.
bad=copy.deepcopy(metrics);metric=at(bad,1)
metric['mean_joint_ce']=(40*metric['mean_decision_ce']+792*metric['mean_residual_ce'])/832
invalid_joint(bad,'pooled normalization')
bad=copy.deepcopy(metrics);at(bad,1)['mean_joint_ce']+=.01
invalid_joint(bad,'joint CE is not the sum')
`);
});

test('joint online loss is measured before the update and matches the previous frozen readout', () => {
  jointPython(`
metrics=joint()
result=score_run(data,metrics)
for update in range(1,101):
    assert abs(at(metrics,update)['online_joint_ce']-result['trajectory'][update-1]['mean_joint_ce'])<1e-12
    assert abs(at(metrics,update)['online_joint_ce']-result['trajectory'][update]['mean_joint_ce'])>.0009
bad=copy.deepcopy(metrics);at(bad,2)['online_joint_ce']=at(bad,2)['mean_joint_ce']
invalid_joint(bad,'online CE incorrectly uses current post-update value')
bad=copy.deepcopy(metrics);at(bad,2)['online_joint_ce']=at(bad,0)['mean_joint_ce']
invalid_joint(bad,'online CE uses the wrong previous update')
for value in (None,float('nan'),float('inf'),-.1,True):
    bad=copy.deepcopy(metrics);at(bad,2)['online_joint_ce']=value
    invalid_joint(bad,'invalid online CE')
bad=copy.deepcopy(metrics);at(bad,2)['gradient_measurement']='post_update'
invalid_joint(bad,'post-update gradient label')
bad=copy.deepcopy(metrics);full_at(bad,25)['online_mean_objective_ce']=.123
invalid_joint(bad,'full snapshot online CE contradicts decision diagnostic')
`);
});

test('joint gradient diagnostics distinguish zero, boundary and clipped norms with declared tolerance', () => {
  jointPython(`
metrics=joint()
result=score_run(data,metrics)
assert result['trajectory'][1]['gradient_norm']==1. and not result['trajectory'][1]['clipped']
assert result['trajectory'][2]['gradient_norm']>1. and result['trajectory'][2]['clipped']
assert result['trajectory'][4]['gradient_norm']==0. and result['trajectory'][4]['clip_scale']==1.
# Rounded native output within the declared tolerance remains valid.
good=copy.deepcopy(metrics);at(good,3)['clip_scale']+=.000003
score_run(data,good)
good=copy.deepcopy(metrics);at(good,3).update(gradient_norm=1e20,clip_scale=1./(1e20+1e-6))
score_run(data,good)
bad=copy.deepcopy(good);at(bad,3)['clip_scale']=1e-6
invalid_joint(bad,'large finite norm requires correspondingly small scale')
for field,value in (('gradient_norm',-.1),('gradient_norm',float('nan')),
                    ('gradient_norm',float('inf')),('gradient_norm',True),
                    ('clip_scale',float('nan')),('clip_scale',float('inf')),
                    ('clip_scale',-.1),('clip_scale',True),('clipped',1),
                    ('clipped',False),('clip_scale',1.)):
    bad=copy.deepcopy(metrics);at(bad,3)[field]=value
    invalid_joint(bad,'clipped diagnostic '+field+' '+str(value))
bad=copy.deepcopy(metrics);at(bad,1)['clipped']=True
invalid_joint(bad,'norm exactly one must not be clipped')
bad=copy.deepcopy(metrics);at(bad,2)['clipped']=False
invalid_joint(bad,'norm just above one must be clipped')
bad=copy.deepcopy(metrics);at(bad,4)['clip_scale']=.5
invalid_joint(bad,'zero norm has unit scale')
bad=copy.deepcopy(metrics);at(bad,3)['clip_scale']+=.000005
invalid_joint(bad,'scale exceeds relative tolerance')
`);
});

test('joint initial gradient diagnostics are explicitly null and later diagnostics are mandatory', () => {
  jointPython(`
metrics=joint()
fields=('gradient_norm','clip_scale','clipped','gradient_measurement','online_joint_ce')
for field,value in zip(fields,(0.,1.,False,'pre_update',.9)):
    bad=copy.deepcopy(metrics);at(bad,0)[field]=value
    invalid_joint(bad,'update zero '+field+' must be null')
for field in fields:
    bad=copy.deepcopy(metrics);at(bad,0).pop(field)
    invalid_joint(bad,'missing update zero '+field)
    bad=copy.deepcopy(metrics);at(bad,1)[field]=None
    invalid_joint(bad,'null trained update '+field)
    bad=copy.deepcopy(metrics);at(bad,1).pop(field)
    invalid_joint(bad,'missing trained update '+field)
`);
});

test('joint runs retain the fixed stage order, objective and complete snapshot schedule', () => {
  jointPython(`
metrics=joint()
bad=copy.deepcopy(metrics);bad[-1],bad[-2]=bad[-2],bad[-1]
invalid_joint(bad,'full readout precedes its decision readout')
bad=copy.deepcopy(metrics);at(bad,1)['update']=2
invalid_joint(bad,'duplicate decision update')
bad=copy.deepcopy(metrics);bad.pop()
invalid_joint(bad,'missing final full snapshot')
bad=copy.deepcopy(metrics);at(bad,75)['snapshot_saved']=False
invalid_joint(bad,'ineligible checkpoint still requires its saved snapshot')
bad=copy.deepcopy(metrics);full_at(bad,25)['objective']='decisions'
invalid_joint(bad,'full objective changed')
bad=copy.deepcopy(metrics);at(bad,1)['objective']='decisions'
invalid_joint(bad,'decision objective changed')
bad=copy.deepcopy(metrics);full_at(bad,50)['epoch']=75
invalid_joint(bad,'full snapshot update changed')
`);
});

test('joint prefix summaries require complete mapped-row coverage and consistent aggregates', () => {
  jointPython(`
metrics=joint()
for field in ('prefix_tokens','prefix_correct','prefix_exact'):
    bad=copy.deepcopy(metrics);full_at(bad,25)['teacher_forced_rows'][0].pop(field)
    invalid_joint(bad,'missing mapped-row '+field)
    bad=copy.deepcopy(metrics)
    row=next(r for r in full_at(bad,25)['teacher_forced_rows'] if r['row'] not in mapping)
    row[field]=True if field=='prefix_exact' else 3
    invalid_joint(bad,'prefix field on unmapped row: '+field)
for field,value in (('prefix_positions',119),('prefix_correct',119),('prefix_exact_examples',39),
                    ('prefix_examples',39),('prefix_positions',120.),('prefix_examples',True)):
    bad=copy.deepcopy(metrics);full_at(bad,25)[field]=value
    invalid_joint(bad,'aggregate '+field)
for field in ('prefix_positions','prefix_correct','prefix_exact_examples','prefix_examples'):
    bad=copy.deepcopy(metrics);full_at(bad,25).pop(field)
    invalid_joint(bad,'missing aggregate '+field)
for field,value in (('prefix_tokens',4),('prefix_tokens',3.),('prefix_correct',4),
                    ('prefix_correct',-1),('prefix_correct',True),('prefix_exact',False),
                    ('prefix_exact',1)):
    bad=copy.deepcopy(metrics);full_at(bad,25)['teacher_forced_rows'][0][field]=value
    invalid_joint(bad,'row '+field)
`);
});

test('joint prefix accuracy must agree with first error and complete-row accuracy', () => {
  jointPython(`
metrics=joint({25:hits(1)})
# An exact prefix cannot contain the row's first error.
bad=copy.deepcopy(metrics);full_at(bad,0)['teacher_forced_rows'][0]['first_error_position']=0
invalid_joint(bad,'exact prefix contains first error')
# Inexact prefixes require a first error before the decision token.
bad=copy.deepcopy(metrics);prefix_miss(bad,25,pairs[0][0])
full_at(bad,25)['teacher_forced_rows'][pairs[0][0]]['first_error_position']=4
invalid_joint(bad,'inexact prefix but first error follows decision')
# Every prefix position before first_error_position is necessarily correct.
bad=copy.deepcopy(metrics);prefix_miss(bad,25,pairs[0][0])
metric=full_at(bad,25);row=metric['teacher_forced_rows'][pairs[0][0]]
row.update(prefix_correct=0,first_error_position=1)
metric['prefix_correct']-=2
invalid_joint(bad,'prefix correct count below first error')
# A claimed perfect full row cannot carry an inexact prefix.
bad=copy.deepcopy(metrics);prefix_miss(bad,25,pairs[0][0])
metric=full_at(bad,25);row=metric['teacher_forced_rows'][pairs[0][0]]
row.update(correct=row['tokens'],first_error_position=-1)
metric['teacher_forced_correct_tokens']+=1;metric['teacher_forced_exact_examples']+=1
invalid_joint(bad,'perfect row with inexact prefix')
# The complete row cannot contain fewer correct tokens than its prefix.
bad=copy.deepcopy(metrics);prefix_miss(bad,25,pairs[10][0])
metric=full_at(bad,25);row=metric['teacher_forced_rows'][pairs[10][0]]
metric['teacher_forced_correct_tokens']-=row['correct']-1
row.update(correct=1,first_error_position=0)
invalid_joint(bad,'full accuracy below prefix accuracy')
# Prefix errors cannot disappear from the complete-row error count.
bad=copy.deepcopy(metrics);prefix_miss(bad,25,pairs[0][0])
metric=full_at(bad,25);row=metric['teacher_forced_rows'][pairs[0][0]]
row['prefix_correct']=1;metric['prefix_correct']-=1
invalid_joint(bad,'full row has fewer errors than its prefix')
`);
});

const expandedCorpus = `
# Keep the original 64 rows, then add six complete pairs after the voice/code rows.
# This exercises mapped indices beyond 63 and a microbatch smaller than 52 decisions.
original_pairs=list(pairs)
for number,(concern,clean) in enumerate(original_pairs[:6]):
    for original in (concern,clean):
        index=len(data)
        row=copy.deepcopy(data[original])
        row['id']='expanded-'+row['id']
        row['pair']='expanded-'+str(number)
        data.append(row)
        native[index]=dict(native[original],row=index)
pairs,mapping=corpus_map(data)
assert len(data)==76 and len(pairs)==26 and len(mapping)==52
`;

test('joint scorer derives 76-row coverage, 26-pair group means and residual normalization from the corpus', () => {
  jointPython(expandedCorpus + `
metrics=joint({25:hits(21),50:hits(23,1),75:hits(26),100:hits(23,1)})
result=score_run(data,metrics,joint_microbatch_tokens=40)
assert result['selected_update']==50 and result['selected_epoch']==50
assert result['selected']['correct_targets']==47
assert result['selected']['complete_decision_pairs']==23
assert result['trajectory'][75]['complete_decision_pairs']==26 and not result['trajectory'][75]['eligible']
groups=result['selected']['groups']
assert groups['concern']['examples']==groups['clean']['examples']==26
assert groups['concern']['correct']==24 and groups['clean']['correct']==23
assert abs(groups['concern']['mean_margin']-22/26)<1e-14
assert abs(groups['clean']['mean_margin']-20/26)<1e-14
assert abs(result['selected']['mean_pair_context_separation']-42/26)<1e-14
assert result['selected']['min_pair_context_separation']==-2.
total=sum(native[row]['tokens'] for row in mapping)
assert result['joint_normalization']==dict(decision_positions=52,residual_positions=total-52,
    joint_positions=total,residual_lambda=1,clip_limit=1,microbatch_tokens=40)
readout=result['full_readouts'][2]
assert readout['review_pairs']==readout['review_decision_pairs']==26
assert readout['review_pairs_exact']==readout['review_decision_pairs_exact']==23
assert readout['groups']['concern']['examples']==readout['groups']['clean']['examples']==26
assert readout['groups']['voice']['examples']==readout['groups']['code']['examples']==12
assert readout['prefix_positions']==156 and readout['prefix_examples']==52
assert readout['prefix_exact_examples']==52 and readout['prefix_correct']==156
assert sum(g['tokens'] for g in readout['groups'].values())==sum(r['tokens'] for r in native.values())
assert result==score_run(data,metrics)  # The documented default is explicitly 40, not the row count.
`);
});

test('expanded joint corpus rejects tampered counts, row coverage, token totals and microbatch declarations', () => {
  jointPython(expandedCorpus + `
metrics=joint()
for field,value in (('examples',64),('examples',True),('decision_pairs',20),
                    ('decision_positions',40),('residual_positions',792),('joint_positions',832),
                    ('microbatch_tokens',52),('microbatch_tokens',39),('microbatch_tokens',True)):
    bad=copy.deepcopy(metrics);bad[0][field]=value
    invalid_joint(bad,'expanded initial '+field)
for field,value in (('decision_pairs',20),('decision_positions',40)):
    bad=copy.deepcopy(metrics);at(bad,1)[field]=value
    invalid_joint(bad,'expanded decision '+field)
for field,value in (('examples',64),('decision_pairs',20),('tokens',1),('prefix_examples',40)):
    bad=copy.deepcopy(metrics);full_at(bad,25)[field]=value
    invalid_joint(bad,'expanded full '+field)
for stage in ('decision','full'):
    bad=copy.deepcopy(metrics)
    metric=at(bad,25) if stage=='decision' else full_at(bad,25)
    metric['microbatch_tokens']=52
    invalid_joint(bad,'changed '+stage+' microbatch declaration')
for update in (0,25):
    bad=copy.deepcopy(metrics);full_at(bad,update)['teacher_forced_rows'].pop()
    invalid_joint(bad,'missing expanded full row')
    bad=copy.deepcopy(metrics);rows=full_at(bad,update)['teacher_forced_rows'];rows[-1]=copy.deepcopy(rows[0])
    invalid_joint(bad,'duplicate expanded full row')
bad=copy.deepcopy(metrics);at(bad,1)['decision_rows'].pop()
invalid_joint(bad,'missing expanded mapped decision row')
bad=copy.deepcopy(metrics);at(bad,1)['decision_rows'][-1]['row']=76
invalid_joint(bad,'mapped decision index outside corpus')
bad=copy.deepcopy(metrics);bad[0]['teacher_forced_rows'][-1]['decision_alternative_id']=999
invalid_joint(bad,'expanded nonreciprocal decision IDs')
for expected in (0,-1,True,40.,52):
    try:score_run(data,metrics,joint_microbatch_tokens=expected)
    except ValueError:pass
    else:raise AssertionError('invalid expected joint microbatch accepted: '+str(expected))
# A different deliberate run size is valid only if the native metadata agrees.
explicit=copy.deepcopy(metrics);explicit[0]['microbatch_tokens']=32
assert score_run(data,explicit,joint_microbatch_tokens=32)['joint_normalization']['microbatch_tokens']==32
invalid_joint(explicit,'undeclared different joint microbatch')
`);
});

test('corpus validation requires unique IDs, known task kinds and complete role-valid review pairs', () => {
  python(`
def invalid_corpus(candidate):
    try:corpus_map(candidate)
    except ValueError:pass
    else:raise AssertionError('invalid corpus accepted')
invalid_corpus([])
invalid_corpus({})
invalid_corpus([None])
for mutation in ('id','kind','roles','content','missing_messages','pair','findings'):
    bad=copy.deepcopy(data)
    if mutation=='id':bad[-1]['id']=bad[0]['id']
    elif mutation=='kind':bad[-1]['kind']='unknown'
    elif mutation=='roles':bad[-1]['messages'][2]['role']='user'
    elif mutation=='content':bad[-1]['messages'][2]['content']=None
    elif mutation=='missing_messages':bad[-1].pop('messages')
    elif mutation=='pair':bad[0]['pair']=''
    elif mutation=='findings':bad[0]['messages'][2]['content']='{}'
    invalid_corpus(bad)
bad=copy.deepcopy(data);bad.pop(pairs[-1][1]);invalid_corpus(bad)
bad=copy.deepcopy(data);bad[pairs[-1][1]]['messages'][2]['content']=bad[pairs[-1][0]]['messages'][2]['content']
invalid_corpus(bad)
invalid_corpus([r for r in data if r['kind']!='review'])
`);
});

test('supplied corpus determines non-review group sizes as well as mapped decision ranges', () => {
  jointPython(`
indices=[pairs[0][0],pairs[0][1],pairs[1][0],pairs[1][1]]
indices += [i for i,r in enumerate(data) if r['kind']=='voice'][:1]
indices += [i for i,r in enumerate(data) if r['kind']=='code'][:2]
data=[data[i] for i in indices]
native={j:dict(native[i],row=j) for j,i in enumerate(indices)}
pairs,mapping=corpus_map(data)
metrics=joint({25:hits(1),50:hits(2),100:hits(2)})
result=score_run(data,metrics)
assert result['selected_update']==50
assert result['selected']['groups']['concern']['examples']==2
groups=result['full_readouts'][2]['groups']
assert groups['voice']['examples']==1 and groups['code']['examples']==2
assert result['joint_normalization']['decision_positions']==4
assert result['joint_normalization']['microbatch_tokens']==40
`);
});

test('historical decision-only, small-step and joint scores remain exactly unchanged', () => {
  python(`
for name in ('2026-09-29-decision-only','2026-09-29-small-step','2026-10-01-joint-review'):
    directory=Path('training/results')/name
    metrics=[json.loads(line) for line in (directory/'metrics.jsonl').read_text().splitlines()]
    stored=json.loads((directory/'scores.json').read_text())
    for key in ('metrics','metrics_sha256','sft','sft_sha256'):stored.pop(key)
    actual=score_run(data,metrics)
    assert actual==stored,name
`);
});

test('joint scorer CLI requires explicit agreement for a nondefault microbatch', () => {
  jointPython(expandedCorpus + `
import subprocess,tempfile
metrics=joint();metrics[0]['microbatch_tokens']=32
with tempfile.TemporaryDirectory() as temporary:
    directory=Path(temporary)
    corpus_path=directory/'sft.jsonl';metric_path=directory/'metrics.jsonl'
    corpus_path.write_text(''.join(json.dumps(row)+chr(10) for row in data))
    metric_path.write_text(''.join(json.dumps(row)+chr(10) for row in metrics))
    command=[sys.executable,'training/score_decisions.py',str(metric_path),'--sft',str(corpus_path)]
    output=directory/'explicit.json'
    result=subprocess.run(command+['--output',str(output),'--joint-microbatch-tokens','32'],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    scored=json.loads(output.read_text())
    assert scored['joint_normalization']['microbatch_tokens']==32
    assert scored['selected']['groups']['concern']['examples']==26
    rejected_output=directory/'default.json'
    result=subprocess.run(command+['--output',str(rejected_output)],capture_output=True,text=True)
    assert result.returncode!=0 and 'joint microbatch disagrees' in result.stderr
    assert not rejected_output.exists()
`);
});
