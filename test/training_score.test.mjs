import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

test('training summaries preserve pair direction and select by complete review pairs', () => {
  const result = spawnSync('python3', ['-c', `
import sys
sys.path.insert(0, 'training')
from score_training import summarize, selection_key
data=[]
for pair in ('a','b'):
    for concern in (True,False):
        answer='{"findings":[{"line_id":1,"reason":"defect"}]}' if concern else '{"findings":[]}'
        data.append(dict(kind='review',pair=pair,messages=[{},{},{'content':answer}]))
data.append(dict(kind='voice',messages=[{},{},{'content':'identity'}]))
def metric(epoch,correct):
    totals=[4,1,10,1,2]
    rows=[dict(row=i,tokens=n,correct=c) for i,(n,c) in enumerate(zip(totals,correct))]
    return dict(epoch=epoch,mean_token_ce=.1,teacher_forced_rows=list(reversed(rows)),
                teacher_forced_correct_tokens=sum(correct),
                teacher_forced_exact_examples=sum(c==n for c,n in zip(correct,totals)))
a=summarize(data,metric(4,[4,1,9,1,2]))
assert a['review_pairs']==2 and a['review_pairs_exact']==1
assert a['groups']['concern']['example_mean_token_accuracy']==.95
assert a['groups']['clean']['exact_examples']==2
assert a['groups']['voice']['exact_examples']==1
b=summarize(data,metric(8,[4,1,10,1,0]))
assert selection_key(b)>selection_key(a)
c=summarize(data,metric(12,[4,1,10,1,0]))
assert selection_key(b)>selection_key(c)
try:
    bad=metric(4,[4,1,9,1,2]); bad['teacher_forced_correct_tokens']+=1
    summarize(data,bad)
except ValueError:
    pass
else:
    raise AssertionError('aggregate mismatch accepted')
print('pair aggregation, row order, primary selection, tie break, and aggregate validation pass')
`], { encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
});

test('decision summaries retain full-vocabulary correctness without changing checkpoint selection', () => {
  const result = spawnSync('python3', ['-c', `
import sys
sys.path.insert(0, 'training')
from score_training import summarize, selection_key
data=[]
for pair in ('a','b'):
    for concern in (True,False):
        answer='{"findings":[{"line_id":1,"reason":"defect"}]}' if concern else '{"findings":[]}'
        data.append(dict(kind='review',pair=pair,messages=[{},{},{'content':answer}]))
rows=[dict(row=i,tokens=6,correct=5,decision_position=3,
           decision_correct=i!=2,decision_margin=[2.,1.,3.,.5][i]) for i in range(4)]
metric=dict(epoch=4,mean_token_ce=.1,teacher_forced_rows=rows,
            teacher_forced_correct_tokens=20,teacher_forced_exact_examples=0)
a=summarize(data,metric)
assert a['review_decision_pairs']==2 and a['review_decision_pairs_exact']==1
assert a['groups']['concern']['decision_correct']==1
assert a['groups']['concern']['decision_positive_margin']==2
assert a['groups']['concern']['decision_mean_margin']==2.5
key=selection_key(a)
for row in rows:
    for field in ('decision_position','decision_correct','decision_margin'):
        row.pop(field)
b=summarize(data,metric)
assert selection_key(b)==key and 'review_decision_pairs' not in b
rows[0].update(decision_position=3,decision_correct=True,decision_margin=1.)
try:
    summarize(data,metric)
except ValueError as error:
    assert 'incomplete decision-token pair' in str(error)
else:
    raise AssertionError('partial decision pair accepted')
print('decision counts, target-token margin and unchanged selection pass')
`], { encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
});

test('decision summaries reject contradictory IDs, margins and missing declared pairs', () => {
  const result = spawnSync('python3', ['-c', `
import copy
import sys
sys.path.insert(0, 'training')
from score_training import summarize
data=[]
for pair in ('a','b'):
    for concern in (True,False):
        answer='{"findings":[{"line_id":1,"reason":"defect"}]}' if concern else '{"findings":[]}'
        data.append(dict(kind='review',pair=pair,messages=[{},{},{'content':answer}]))
rows=[dict(row=i,tokens=6,correct=5,decision_position=3,decision_correct=i!=2,
           decision_margin=0. if i==0 else 1.,decision_target_id=100+i,
           decision_alternative_id=200+i,decision_predicted_id=999 if i==2 else 100+i)
      for i in range(4)]
metric=dict(epoch=4,mean_token_ce=.1,teacher_forced_rows=rows,decision_pairs=2,
            teacher_forced_correct_tokens=20,teacher_forced_exact_examples=0)
# A target can win a tie; a third token can beat a target with positive paired margin.
assert summarize(data,metric)['review_decision_pairs_exact']==1
def rejected(bad, fragment):
    try:
        summarize(data,bad)
    except ValueError as error:
        assert fragment in str(error), str(error)
    else:
        raise AssertionError('contradictory decision metrics accepted')
bad=copy.deepcopy(metric)
bad['teacher_forced_rows'][0]['decision_margin']=-1.
rejected(bad,'margin')
bad=copy.deepcopy(metric)
bad['teacher_forced_rows'][0]['decision_predicted_id']=200
rejected(bad,'token IDs')
bad=copy.deepcopy(metric)
for row in bad['teacher_forced_rows'][:2]:
    for field in tuple(row):
        if field.startswith('decision_'): row.pop(field)
rejected(bad,'pair count')
bad=copy.deepcopy(metric)
bad['teacher_forced_rows'][0].pop('decision_margin')
rejected(bad,'incomplete decision-token metrics')
bad=copy.deepcopy(metric)
bad['teacher_forced_rows'][0].pop('decision_alternative_id')
rejected(bad,'incomplete decision token IDs')
for index,correct in ((0,0),(2,6)):
    bad=copy.deepcopy(metric)
    bad['teacher_forced_rows'][index]['correct']=correct
    bad['teacher_forced_correct_tokens']=15+correct
    bad['teacher_forced_exact_examples']=int(correct==6)
    rejected(bad,'token counts')
# Later epochs retain predicted IDs but need not repeat the target/alternative IDs.
for row in rows:
    row.pop('decision_target_id'); row.pop('decision_alternative_id')
assert summarize(data,metric)['review_decision_pairs_exact']==1
print('decision ID/margin/count consistency, complete diagnostics and epoch compatibility pass')
`], { encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
});
