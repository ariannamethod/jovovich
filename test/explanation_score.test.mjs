import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

const fixture = `
import copy, hashlib, importlib.util, json, subprocess, sys, tempfile
from pathlib import Path
spec=importlib.util.spec_from_file_location('score_generation','training/explanations/score_generation.py')
score=importlib.util.module_from_spec(spec);spec.loader.exec_module(score)
work=tempfile.TemporaryDirectory();directory=Path(work.name)
source=[json.loads(x) for x in Path('training/sft_review_v5.jsonl').read_text().splitlines()]
rows=copy.deepcopy(source[:6])
for r in rows:
    if r['kind']=='review':
        old=json.loads(r['messages'][2]['content'])
        r['messages'][2]['content']=json.dumps(dict(analysis='Compare the nearest applicable rule with the added line.',findings=old['findings']),separators=(',',':'))
corpus=directory/'corpus.jsonl';generated=directory/'generations.jsonl'
def write_rows(path,items):path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\\n' for x in items))
write_rows(corpus,rows)
def h(text):return hashlib.sha256(text.encode()).hexdigest()
def record(r,raw=None,finish='eos'):
    raw=r['messages'][2]['content'] if raw is None else raw
    return dict(case_id=r['id'],corpus_sha256=score.sha256(corpus.read_bytes()),raw_response=raw,raw_response_sha256=h(raw),finish_reason=finish)
good=[record(r) for r in rows if r['kind']=='review']
def run(records=None,order='before'):
    write_rows(generated,good if records is None else records)
    return score.score_files(corpus,generated,order)
def with_raw(raw,finish='eos'):
    records=copy.deepcopy(good);records[0]=record(rows[0],raw,finish);return records
def rejected(records,fragment):
    try:run(records)
    except ValueError as error:assert fragment in str(error),str(error)
    else:raise AssertionError('accepted bad record: '+fragment)
`;

function python(code) {
  const result = spawnSync('python3', ['-c', fixture + '\n' + code], { encoding: 'utf8', timeout: 15000 });
  assert.equal(result.status, 0, result.stderr || result.stdout || String(result.error));
}

test('free generation scorer binds raw files and complete concern/clean pairs', () => {
  python(`
result=run();s=result['summary']
assert result['status']=='complete' and s['expected_reviews']==4 and s['expected_pairs']==2
assert s['classification_correct']==4 and s['complete_classification_pairs']==2
assert s['complete_strict_output_pairs']==2 and s['format_pass']==4
assert result['semantic_assessment'] is None and result['production_acceptance'] is None
assert all(r['semantic_assessment'] is None for r in result['rows'])
assert result['generations']['sha256']==score.sha256(generated.read_bytes())
assert result['corpus']['sha256']==score.sha256(corpus.read_bytes())
assert result['generations']['path']==str(generated.resolve())
assert result['rows'][0]['generation_record']['sha256']==score.sha256(generated.read_bytes().splitlines(keepends=True)[0])
assert result['rows'][0]['corpus_record']['sha256']==score.sha256(corpus.read_bytes().splitlines(keepends=True)[0])
# Record ordering cannot pair one case with another case's gold.
reversed_result=run(list(reversed(good)))
assert reversed_result['summary']==s
assert [r['case_id'] for r in reversed_result['rows']]==[r['case_id'] for r in result['rows']]
`);
});

test('full JSON rejects fences, substrings, duplicate keys, NaN and incomplete output', () => {
  python(`
raw=good[0]['raw_response']
invalid=[raw+'<|im_end|>', 'prefix '+raw, raw+' trailing', '\x60\x60\x60json\\n'+raw+'\\n\x60\x60\x60',
         raw[:-1], '', raw+raw, '{"analysis":"a","analysis":"b","findings":[]}',
         '{"analysis":"a","findings":[{"line_id":1,"line_id":1,"reason":"r"}]}',
         '{"analysis":NaN,"findings":[]}', '{"analysis":Infinity,"findings":[]}']
for bad in invalid:
    row=run(with_raw(bad))['rows'][0]
    assert row['status']=='invalid_json' and not row['json_valid'] and not row['classification_correct'],bad
assert run(with_raw(' \\n'+raw+'\\t '))['rows'][0]['strict_output_pass']
`);
});

test('strict schema rejects unknown fields and invalid findings or line IDs', () => {
  python(`
answer=json.loads(good[0]['raw_response'])
variants=[None, [], {}, dict(answer, extra='hidden')]
for key,value in [('findings',None),('findings',{}),('findings',['x'])]:
    bad=copy.deepcopy(answer);bad[key]=value;variants.append(bad)
for id in [True,False,0,-1,2,1.5,'01','1.0','1e0',None]:
    bad=copy.deepcopy(answer);bad['findings'][0]['line_id']=id;variants.append(bad)
for reason in ['', '  ', None, 'r'*1501, '\U0001f600'*751]:
    bad=copy.deepcopy(answer);bad['findings'][0]['reason']=reason;variants.append(bad)
bad=copy.deepcopy(answer);bad['findings'][0]['path']='made-up.c';variants.append(bad)
bad=copy.deepcopy(answer);bad['findings']*=3;variants.append(bad)
for bad in variants:
    row=run(with_raw(json.dumps(bad)))['rows'][0]
    assert row['json_valid'] and not row['findings_schema_valid'] and not row['classification_correct'],bad
good_string=copy.deepcopy(answer);good_string['findings'][0]['line_id']='1'
assert run(with_raw(json.dumps(good_string)))['rows'][0]['exact_gold_line_ids']
good_number=copy.deepcopy(answer);good_number['findings'][0]['line_id']=1.0
assert run(with_raw(json.dumps(good_number)))['rows'][0]['exact_gold_line_ids']
`);
});

test('classification and canonical citations remain separate from explanation compliance', () => {
  python(`
answer=json.loads(good[0]['raw_response'])
for raw in [json.dumps({'findings':answer['findings']}),json.dumps(dict(answer,analysis=None)),
            json.dumps(dict(answer,analysis='  ')),
            json.dumps(dict(findings=answer['findings'],analysis=answer['analysis']))]:
    row=run(with_raw(raw))['rows'][0]
    assert row['classification_correct'] and row['exact_gold_line_ids']
    assert not row['format_pass'] and not row['strict_output_pass']
noanalysis=run(with_raw(json.dumps({'findings':answer['findings']})))
assert noanalysis['summary']['complete_classification_pairs']==2
assert noanalysis['summary']['complete_strict_output_pairs']==1
empty=run(with_raw(json.dumps(dict(answer,analysis='  '))))['rows'][0]
assert empty['schema_valid'] and empty['empty_analysis']
# Valid concern is independent of semantic quality of its text.
arbitrary=copy.deepcopy(answer);arbitrary['findings'][0]['reason']='The moon is made of cheese.'
row=run(with_raw(json.dumps(arbitrary)))['rows'][0]
assert row['classification_correct'] and row['semantic_assessment'] is None
# The after corpus has the same gold information with reversed field order.
for r in rows:
    if r['kind']=='review':
        a=json.loads(r['messages'][2]['content']);r['messages'][2]['content']=json.dumps(dict(findings=a['findings'],analysis=a['analysis']))
write_rows(corpus,rows);good=[record(r) for r in rows if r['kind']=='review']
assert run(order='after')['summary']['complete_strict_output_pairs']==2
try:run(order='before')
except ValueError as e:assert 'key order' in str(e)
else:raise AssertionError('wrong corpus order accepted')
`);
});

test('truncation, execution errors and missing cases cannot earn complete passes', () => {
  python(`
truncated=run(with_raw(good[0]['raw_response'],'length'))
row=truncated['rows'][0]
assert row['json_valid'] and row['schema_valid'] and row['status']=='truncated'
assert not row['classification_correct'] and not row['format_pass']
assert truncated['summary']['truncated_reviews']==1
assert truncated['summary']['complete_classification_pairs']==1
incomplete=run(good[:1])
assert incomplete['status']=='incomplete' and incomplete['summary']['expected_reviews']==4
assert incomplete['summary']['missing_reviews']==3 and incomplete['summary']['complete_classification_pairs']==0
assert run([])['summary']['missing_reviews']==4
for raw,rawhash in [(None,None),(good[0]['raw_response'],good[0]['raw_response_sha256'])]:
    records=copy.deepcopy(good);records[0].update(raw_response=raw,raw_response_sha256=rawhash,finish_reason='error',error='process exited 3')
    r=run(records);assert r['summary']['generation_errors']==1
    assert not r['rows'][0]['classification_correct']
`);
});

test('record corruption, stale source hashes, duplicate and unknown cases are rejected', () => {
  python(`
rejected(good+[good[0]],'duplicate generation')
bad=copy.deepcopy(good);bad[0]['case_id']='unknown';rejected(bad,'unknown/non-review')
bad=copy.deepcopy(good);bad[0]['case_id']=rows[2]['id'];rejected(bad,'unknown/non-review')
for key,value,fragment in [('raw_response_sha256','0'*64,'response hash'),('corpus_sha256','0'*64,'corpus hash'),
                         ('finish_reason','token-limit','finish_reason'),('raw_response',None,'literal text'),
                         ('error','hidden error','error message')]:
    bad=copy.deepcopy(good);bad[0][key]=value;rejected(bad,fragment)
bad=copy.deepcopy(good);bad[0]['extra']=1;rejected(bad,'record keys')
bad=copy.deepcopy(good);bad[0]['finish_reason']='error';rejected(bad,'requires an error')
bad=copy.deepcopy(good);bad[0]['metadata']={'prompt_sha256':'0'*64};rejected(bad,'prompt hash mismatch')
bad=copy.deepcopy(good);bad[0]['metadata']={'generated_token_ids':[True]};rejected(bad,'metadata')
bad=copy.deepcopy(good);bad[0]['metadata']={'unknown':1};rejected(bad,'metadata')
write_rows(corpus,rows+[rows[0]])
try:run()
except ValueError as e:assert 'unique' in str(e)
else:raise AssertionError('duplicate corpus IDs accepted')
`);
});

test('CLI marks incomplete coverage and preserves existing output files', () => {
  python(`
write_rows(generated,good[:1]);output=directory/'score.json'
cmd=[sys.executable,'training/explanations/score_generation.py',str(generated),'--sft',str(corpus),'--order','before','--output',str(output)]
done=subprocess.run(cmd,capture_output=True,text=True)
assert done.returncode==2,done.stderr
assert json.loads(output.read_text())['status']=='incomplete'
original=output.read_bytes();done=subprocess.run(cmd,capture_output=True,text=True)
assert done.returncode==1 and output.read_bytes()==original
write_rows(generated,good);output.unlink();done=subprocess.run(cmd,capture_output=True,text=True)
assert done.returncode==0,done.stderr
assert json.loads(output.read_text())['summary']['classification_correct']==4
`);
});

test('heldout scorer shares production prompts and keeps alternate citations separate', () => {
  python(`
corpus=Path('training/review_holdout_v5.jsonl')
heldout=[json.loads(line) for line in corpus.read_text().splitlines()]
sys.path.insert(0,str(Path('training/explanations').resolve()))
from collect_generation import review_cases
prompts=review_cases(corpus.read_bytes(),split='holdout')
records=[]
for row,prompt in zip(heldout,prompts):
    raw=json.dumps(dict(analysis='Fixture analysis for structural scoring.',findings=row['gold']['findings']))
    records.append(dict(case_id=row['id'],corpus_sha256=score.sha256(corpus.read_bytes()),
                        raw_response=raw,raw_response_sha256=h(raw),finish_reason='eos',
                        metadata={'prompt_sha256':prompt['prompt_sha256']}))
write_rows(generated,records)
result=score.score_files(corpus,generated,'before','holdout')
assert result['summary']['expected_reviews']==24 and result['summary']['complete_strict_output_pairs']==12
index=next(i for i,row in enumerate(heldout) if row['expected_line_ids']==[1,2])
assert result['rows'][index]['expected_line_ids']==[1]
assert result['rows'][index]['supplied_candidate_line_ids']==[1,2]
answer=json.loads(records[index]['raw_response']);answer['findings'][0]['line_id']=2
raw=json.dumps(answer);records[index].update(raw_response=raw,raw_response_sha256=h(raw))
write_rows(generated,records)
row=score.score_files(corpus,generated,'before','holdout')['rows'][index]
assert row['classification_correct'] and not row['exact_gold_line_ids']
assert row['semantic_assessment'] is None
# Gold has no analysis; expected arm order is supplied independently.
after=score.score_files(corpus,generated,'after','holdout')
assert after['summary']['classification_correct']==24 and after['summary']['format_pass']==0
assert 'analysis' not in heldout[0]['gold']
`);
});
