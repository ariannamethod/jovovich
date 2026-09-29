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
