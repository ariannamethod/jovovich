"""Aggregate explicit hash-bound human/agent readings of the 176 full responses.

This is validation and arithmetic, not an automatic semantic classifier. The
manual case notes are the semantic evidence and remain available verbatim.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEM = 'models/counterbalanced-review-'
ARMS = ('control', 'counterbalanced')
COHORTS = {'train-natural': 52, 'transfer-natural': 24, 'diagnostics-natural': 12}
SOURCES = {}
def read(path, lines=False):
    path = Path(path)
    b = path.read_bytes()
    SOURCES[str(path)] = {'sha256': hashlib.sha256(b).hexdigest(), 'bytes': len(b)}
    assert b.endswith(b'\n'), path
    return [json.loads(s) for s in b.splitlines()] if lines else json.loads(b)
def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()
def summarize(cases):
    def n(predicate): return sum(bool(predicate(c)) for c in cases)
    pairs = {}
    for c in cases: pairs.setdefault(c['pair'], []).append(c)
    for pair in pairs.values():
        assert len(pair) == 2 and sorted(c['expected_concern'] for c in pair) == [False, True]
    return dict(cases=len(cases), concerns=n(lambda c:c['expected_concern']),
        clean=n(lambda c:not c['expected_concern']),
        json_syntax_valid=n(lambda c:c['outcome']['json_valid']),
        production_usable=n(lambda c:c['outcome']['production_parse']),
        parsed_concern=n(lambda c:c['outcome']['concern'] is True),
        parsed_empty=n(lambda c:c['outcome']['concern'] is False),
        parsed_presence_null=n(lambda c:c['outcome']['concern'] is None),
        correct_presence=n(lambda c:c['outcome']['presence_correct'] is True),
        genuine_issues_detected=n(lambda c:c['expected_concern'] and c['judgment']['genuine_issue_detected']),
        reason_grounded_cases=n(lambda c:c['judgment']['reason_grounded']),
        grounded_concern_reviews=n(lambda c:c['expected_concern'] and c['full_review_pass']),
        correct_clean_reviews=n(lambda c:not c['expected_concern'] and c['full_review_pass']),
        full_reviews_pass=n(lambda c:c['full_review_pass']),
        clean_nonempty_responses=n(lambda c:not c['expected_concern'] and c['outcome']['concern'] is True),
        invalid_clean_responses=n(lambda c:not c['expected_concern'] and not c['outcome']['production_parse']),
        pairs=len(pairs), full_review_pairs=sum(all(c['full_review_pass'] for c in pair) for pair in pairs.values()),
        complete_presence_pairs=sum(all(c['outcome']['presence_correct'] is True for c in pair) for pair in pairs.values()),
        complete_usable_presence_pairs=sum(all(c['outcome']['usable_presence_correct'] for c in pair) for pair in pairs.values()),
        eos=n(lambda c:c['stop_reason']=='eos'), token_limit=n(lambda c:c['stop_reason']=='token-limit'))
def contrasts(cases):
    families = {}
    for c in cases:
        m = c['audit_metadata']
        if m is None: continue
        family = m.get('family', m.get('context_block'))
        shape = 'deletion' if m['shape'] in ('deletion', 'pure-deletion') else 'replacement'
        key = (shape, c['expected_concern'])
        assert family and key not in families.setdefault(family, {})
        families[family][key] = c
    output = []
    for family, cells in families.items():
        assert len(cells) == 4
        within, across = [], []
        for shape in ('deletion', 'replacement'):
            a,b = cells[shape,True],cells[shape,False]
            within.append(dict(shape=shape,harmful=a['id'],clean=b['id'],
                both_full_reviews_pass=a['full_review_pass'] and b['full_review_pass'],
                harmful_issue_detected=a['judgment']['genuine_issue_detected'],
                correct_clean=b['full_review_pass'],
                presence_changes_with_context=None if a['outcome']['concern'] is None or b['outcome']['concern'] is None else a['outcome']['concern'] != b['outcome']['concern']))
        for expected in (True,False):
            a,b = cells['deletion',expected],cells['replacement',expected]
            across.append(dict(expected_concern=expected,deletion=a['id'],replacement=b['id'],
                both_full_reviews_pass=a['full_review_pass'] and b['full_review_pass'],
                same_presence=None if a['outcome']['concern'] is None or b['outcome']['concern'] is None else a['outcome']['concern']==b['outcome']['concern'],
                same_sampled_decision_id=None if a['sampled_decision_id'] is None or b['sampled_decision_id'] is None else a['sampled_decision_id']==b['sampled_decision_id']))
        output.append(dict(family=family,all_four_full_reviews_pass=all(c['full_review_pass'] for c in cells.values()),within_shape=within,across_shape=across))
    return output

plan = read(STEM+'plan.json')
generation = read(STEM+'generation-summary.json')
assert generation['protocol']['plan_sha256'] == SOURCES[STEM+'plan.json']['sha256']
assert generation['protocol']['generated_responses'] == plan['evaluation']['new_responses'] == 176
for path, binding in generation['sources'].items():
    b=Path(path).read_bytes()
    assert hashlib.sha256(b).hexdigest() == binding['sha256'],path
manual_path = HERE/'counterbalanced-manual-judgments.json'
manual = read(manual_path)
assert isinstance(manual['method'],str) and manual['method']
assert len(manual['cases']) == 176
judgments={}
for j in manual['cases']:
    key=j['arm'],j['cohort'],j['id']
    assert key not in judgments
    assert j['arm'] in ARMS and j['cohort'] in COHORTS
    for field in ('reason_grounded','genuine_issue_detected','all_findings_grounded','citation_causally_appropriate'):
        assert type(j[field]) is bool,(key,field)
    assert j['all_material_claims_supported'] is None or type(j['all_material_claims_supported']) is bool
    for field in ('supported_fragments','unsupported_claims'):
        assert isinstance(j[field],list) and all(isinstance(s,str) for s in j[field])
    assert isinstance(j['note'],str) and j['note'].strip()
    if j['genuine_issue_detected']:
        assert j['reason_grounded'] and j['citation_causally_appropriate'],key
    if j['unsupported_claims']:
        assert j['all_material_claims_supported'] is False,key
    judgments[key]=j
assert isinstance(manual['sources'],list) and manual['sources']
fragment_cases = {}
for binding in manual['sources']:
    fragment = read(binding['path'])
    assert SOURCES[binding['path']]['sha256'] == binding['sha256']
    for j in fragment['cases']:
        key = j['arm'],j['cohort'],j['id']
        assert key not in fragment_cases and judgments[key] == j
        fragment_cases[key] = j
assert set(fragment_cases) == set(judgments)

corpus_audit=read(plan['frozen_evaluation']['corpus_audit']['path'])
cohorts,subsets,quartets={},{},{}
used=set()
for arm in ARMS:
    cohorts[arm]={};quartets[arm]={}
    for cohort,count in COHORTS.items():
        path=STEM+arm+'-'+cohort+'.jsonl'
        rows=read(path,lines=True)
        assert len(rows)==count
        structural=generation['cohorts'][arm][cohort]
        summaries={c['name']:c for c in structural['cases']}
        assert len(summaries)==count
        cases=[]
        for index,r in enumerate(rows):
            key=arm,cohort,r['name'];j=judgments[key];used.add(key)
            s=summaries[r['name']]
            assert s['response_sha256']==sha(r['assembled_response'])
            for field,value in [('model_sha256',r['model_sha256']),('prompt_sha256',r['prompt_sha256']),('response_sha256',s['response_sha256']),('trace_sha256',r['trace_sha256'])]:
                assert j[field]==value,(key,field)
            assert s['outcome']['production_parse']==(r['assessment']['parsed_findings'] is not None)
            assert s['outcome']['concern']==r['assessment']['concern']
            assert r['model_sha256']==structural['model_sha256']
            o=s['outcome']
            full=bool(o['production_parse'] and (
                o['concern'] is False if not r['expected_concern'] else
                o['concern'] is True and j['genuine_issue_detected'] and j['all_findings_grounded'] and j['all_material_claims_supported'] is True))
            if o['concern'] is False:
                assert not j['genuine_issue_detected'] and not j['reason_grounded'],key
            cases.append(dict(id=r['name'],pair=r['pair'],arm=arm,cohort=cohort,source=path,record_line=index+1,
                model_sha256=r['model_sha256'],prompt_sha256=r['prompt_sha256'],response_sha256=s['response_sha256'],trace_sha256=r['trace_sha256'],
                expected_concern=r['expected_concern'],expected_line_ids=r['expected_line_ids'],
                audit_metadata=r['audit_metadata'],raw_response=r['assembled_response'],stop_reason=r['stop_reason'],
                sampled_decision_id=s['sampled_decision_id'],outcome=o,judgment=j,full_review_pass=full))
        cohorts[arm][cohort]=dict(model_sha256=structural['model_sha256'],source=path,source_sha256=SOURCES[path]['sha256'],counts=summarize(cases),cases=cases)
        if cohort!='diagnostics-natural':quartets[arm][cohort]=contrasts(cases)
    train=cohorts[arm]['train-natural']['cases']
    subsets[arm]={
        'retained_pairs':summarize([c for c in train if c['pair'] in corpus_audit['retained_pairs']]),
        'retained_same_diff_pairs':summarize([c for c in train if c['pair'] in corpus_audit['retained_same_diff_pairs']]),
        'new_quartets':summarize([c for c in train if c['audit_metadata'] is not None])}
assert used==set(judgments)
result=dict(schema_version=1,complete=True,created_at_utc=datetime.now(timezone.utc).isoformat(),
    scope=dict(total_responses=176,control_responses_manually_read=88,counterbalanced_responses_manually_read=88),
    method=manual['method'],rubric=plan['full_answer_judgment'],sources=SOURCES,
    models=dict(control_sha256=cohorts['control']['train-natural']['model_sha256'],
        counterbalanced_sha256=cohorts['counterbalanced']['train-natural']['model_sha256'],
        counterbalanced_selected_update=generation['selected_training']['counterbalanced']['selected_update']),
    cohorts=cohorts,training_subsets=subsets,quartet_contrasts=quartets)
with Path(STEM+'semantic-assessment.json').open('x') as f:f.write(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({a:{c:d['counts'] for c,d in groups.items()} for a,groups in cohorts.items()}))
