#!/usr/bin/env python3
"""Assemble manually reviewed joint/control semantics; runs only the production parser."""
import json, hashlib, re, subprocess, datetime
from pathlib import Path
from collections import defaultdict

ROOT=Path.cwd()
REF=Path(__file__).resolve().parent
OUT=ROOT/'models/joint-review-semantic-assessment.json'
assert not OUT.exists(), 'Refuse to replace completed semantic evidence'
SOURCES={}
def sha(b): return hashlib.sha256(b).hexdigest()
def tsha(s): return sha(s.encode())
def desc(path):
    p=Path(path); p=p if p.is_absolute() else ROOT/p
    b=p.read_bytes(); SOURCES[str(p)]={'sha256':sha(b),'bytes':len(b)}
    return p,b
def read(path, lines=False):
    p,b=desc(path)
    if lines:
        assert b.endswith(b'\n'),str(p)
        rows=[json.loads(x) for x in b.splitlines()]
        SOURCES[str(p)]['records']=len(rows)
        return rows
    return json.loads(b)
def same(a,b): assert a==b,(a,b)
sft=read('training/sft_review_v2.jsonl',True)
sftmap={r['id']:r for r in sft if r['kind']=='review'}
read('training/review_holdout_v2.jsonl',True)
audit=read(REF/'diff-shape-audit.jsonl',True)
auditmap={r['id']:r for r in audit}
summary=read('models/joint-review-generation-summary.json')
selected=read('models/joint-review-selected-model.json')
plan=read('models/joint-review-plan.json')
trainmanual=read(REF/'joint-train-manual-judgments.json')
othermanual=read(REF/'joint-eval-manual-judgments.json')
oldsem=read('training/results/2026-09-29-small-step/shared-new-semantic-assessment.json')
oldrows=read('training/results/2026-09-29-small-step/shared-prefix-new.jsonl',True)
oldmap={r['name']:r for r in oldrows};oldnotes={r['id']:r for r in oldsem['cases']}
auditsem=read(REF/'control-diff-shape-assessment.json')
auditnotes={(r['mode'],r['name']):r for r in auditsem['cases']}
othernotes={(r['cohort'],r['name']):r for r in othermanual['records']}
reviewed={(r['source'],r['name'],r['response_sha256']) for r in trainmanual['reviewed_responses']}
same(selected['sha256'],'6aaf2f70764de35db1ee13b2c7d974b1064b6dfbd044024b164a2856fdafadd1')
same(selected['update'],100)
spec={'control':{'train-shared':40,'audit-natural':8,'audit-shared':8},
      'joint':{'train-natural':40,'train-shared':40,'diagnostics-natural':12,'audit-natural':8,'audit-shared':8}}
raw={}; allfiles=[]
for arm,co in spec.items():
    raw[arm]={}
    for slug,n in co.items():
        fn='models/joint-review-'+arm+'-'+slug+'.jsonl'
        rows=read(fn,True);same(len(rows),n);same(len({r['name'] for r in rows}),n)
        raw[arm][slug]=rows;allfiles.append(fn)
node=r"""
import {readFile} from 'node:fs/promises';
import {parseReview} from './bin/jovovich.mjs';
const files=JSON.parse(process.argv[1]), out={};
for(const file of files){
 const rows=(await readFile(file,'utf8')).trim().split('\n').map(JSON.parse);
 out[file]=rows.map(r=>{
  const text=r.assembled_response;
  const norm=text.trim().replace(/(?:<\|im_end\|>|<\|endoftext\|>)+\s*$/,'').trim().replace(/^\x60\x60\x60(?:json)?\s*/,'').replace(/\s*\x60\x60\x60$/,'');
  let obj=null,syntax=false,strict=false,fs=null,usable=false,parsed=null,error=null;
  try{JSON.parse(text);strict=true;}catch{}
  try{obj=JSON.parse(norm);syntax=true;}catch{}
  if(syntax)fs=Array.isArray(obj)?obj:(obj&&Array.isArray(obj.findings)?obj.findings:null);
  try{parsed=parseReview(text,r.chunk).findings;usable=true;}catch(e){error=e.message;}
  const ids=fs===null?null:fs.map(f=>{const x=f&&f.line_id;return typeof x==='string'&&/^[1-9][0-9]*$/.test(x)?Number(x):x??null;});
  return {name:r.name,json_syntax_valid:syntax,strict_raw_json:strict,
   canonical_findings_object:!!(syntax&&obj&&!Array.isArray(obj)&&Array.isArray(obj.findings)),
   finding_objects_schema_valid:fs===null?false:fs.every(f=>f!==null&&typeof f==='object'&&!Array.isArray(f)&&Object.hasOwn(f,'line_id')&&typeof f.reason==='string'),
   parsed_concern:fs===null?null:fs.length>0,findings_count:fs===null?null:fs.length,
   returned_line_ids:ids,cited_ids_available:ids===null||!ids.length?null:ids.every(x=>Number.isInteger(x)&&x>=1&&x<=r.chunk.lines.length),
   production_usable:usable,parse_error:error,parsed_findings:parsed};
 });}
process.stdout.write(JSON.stringify(out));
"""
parsed=json.loads(subprocess.check_output(['node','--input-type=module','-e',node,json.dumps(allfiles)],cwd=ROOT,text=True))
same(sha(desc('bin/jovovich.mjs')[1]),'570f01033adcc144f6bac8448dcec0a357b9fa2c193a6f2bc9f4a3ca7fa981c2')
desc(Path(__file__).resolve())
MKEYS=['reason_grounded','genuine_issue_detected','all_material_claims_supported','all_findings_grounded',
 'citation_causally_appropriate','supported_fragments','unsupported_claims','reason_class','full_review_pass','correct_clean']
def empty_note(r):
    expected=r['expected_concern'];gold=json.loads(sftmap[r['name']]['messages'][2]['content'])
    why=gold['findings'][0]['reason'] if expected else None
    return dict(reason_grounded=False,genuine_issue_detected=False,all_material_claims_supported=None,all_findings_grounded=True,
      citation_causally_appropriate=None,supported_fragments=[],unsupported_claims=[],reason_class='empty_miss' if expected else 'correct_clean',
      full_review_pass=not expected,correct_clean=not expected,assessment='The empty review misses the supplied issue: '+why if expected else 'The complete empty review correctly accepts this change under its supplied code and rules.')
def control_note(r):
    if r['assessment']['concern'] is False:return empty_note(r)
    name=r['name'];claims=None;support=[];bad=[];klass='diff_copy_without_reason'
    if name=='preserve-trie-credit-introduced':
        claims=False;support=['The visible reason copies the removed upstream credit.'];bad=['Trailing prose invents old-versus-new notices and dependency distinctions.'];klass='invented_provenance_account'
    elif name=='allocation-null-guard-introduced':
        claims=False;bad=['The guard belongs inside calloc rather than this source file.'];klass='invented_scope'
    elif name=='zero-worker-guard-introduced':
        claims=False;support=['The guard checks workers against zero.'];bad=['The src/shard.c guard is presented as an AGENTS.md source line.'];klass='guard_copy_without_mechanism'
    elif name=='write-permission-check-introduced':
        claims=False;support=['replace_record should only run with write permission.'];bad=['The removed guard has a scope defect relative to replace_record.'];klass='true_requirement_with_incorrect_scope_claim'
    elif name=='stable-manifest-order-introduced':
        claims=False;support=['The manifest must be identical for the same mapping regardless of insertion order.'];bad=['The response invents a conflict between manifest.mjs and tools/manifest.mjs.','Sorting is called inside the output array.','Byte-identical output is undesirable.'];klass='true_rule_with_false_elaboration'
    elif name=='allocation-product-overflow-introduced':
        claims=False;bad=['The guard must be moved from src/vector_alloc.c to vector_alloc.c.'];klass='invented_file_placement'
    return dict(reason_grounded=False,genuine_issue_detected=False,all_material_claims_supported=claims,all_findings_grounded=False,
      citation_causally_appropriate=False,supported_fragments=support,unsupported_claims=bad,reason_class=klass,
      assessment=oldnotes[name]['assessment'],full_review_pass=False,correct_clean=False)
def control_audit_note(r,mode):
    n=auditnotes[(mode,r['name'])];same(n['response_sha256'],tsha(r['assembled_response']));same(n['response'],r['assembled_response'])
    correct=not r['expected_concern'] and r['assessment']['concern'] is False and r['assessment']['parsed_findings'] is not None
    return dict(reason_grounded=False,genuine_issue_detected=False,all_material_claims_supported=None,
      all_findings_grounded=r['assessment']['concern'] is False,citation_causally_appropriate=None if mode=='natural' else False,
      supported_fragments=[],unsupported_claims=[],reason_class=('empty_miss' if r['expected_concern'] else 'correct_clean') if mode=='natural' else 'diff_copy_without_reason',
      assessment=n['assessment'],full_review_pass=correct,correct_clean=correct)
def counts(cs,ps):
    n=lambda f:sum(bool(f(c)) for c in cs)
    return dict(cases=len(cs),concerns=n(lambda c:c['expected_concern']),clean=n(lambda c:not c['expected_concern']),
      json_syntax_valid=n(lambda c:c['json_syntax_valid']),strict_raw_json=n(lambda c:c['strict_raw_json']),canonical_findings_objects=n(lambda c:c['canonical_findings_object']),
      production_usable=n(lambda c:c['production_usable']),invalid_parse=n(lambda c:not c['production_usable']),
      parsed_concern=n(lambda c:c['parsed_concern'] is True),parsed_empty=n(lambda c:c['parsed_concern'] is False),parsed_presence_null=n(lambda c:c['parsed_concern'] is None),
      correct_presence=n(lambda c:c['presence_correct'] is True),genuine_issues_detected=n(lambda c:c['expected_concern'] and c['genuine_issue_detected']),
      reason_grounded_cases=n(lambda c:c['reason_grounded']),grounded_concern_reviews=n(lambda c:c['expected_concern'] and c['full_review_pass']),
      correct_clean_reviews=n(lambda c:c['correct_clean']),full_reviews_pass=n(lambda c:c['full_review_pass']),
      clean_nonempty_responses=n(lambda c:not c['expected_concern'] and c['parsed_concern'] is True),
      production_clean_false_positives=n(lambda c:not c['expected_concern'] and c['parsed_concern'] is True and c['production_usable']),
      invalid_clean_responses=n(lambda c:not c['expected_concern'] and not c['production_usable']),
      pairs=len(ps),full_review_pairs=sum(p['full_review_pass'] for p in ps),complete_presence_pairs=sum(p['presence_correct'] for p in ps),
      complete_usable_presence_pairs=sum(p['usable_presence_correct'] for p in ps),eos=n(lambda c:c['stop_reason']=='eos'),token_limit=n(lambda c:c['stop_reason']=='token-limit'))
cohorts={};replay=[]
for arm,co in raw.items():
    cohorts[arm]={}
    for slug,rows in co.items():
        kind,mode=slug.split('-');fn='models/joint-review-'+arm+'-'+slug+'.jsonl'
        mechan={c['name']:c for c in parsed[fn]};gc={c['name']:c for c in summary['cohorts'][arm][slug]['cases']};cases=[]
        for lineno,r in enumerate(rows,1):
            name=r['name'];p=mechan[name];g=gc[name];rs=tsha(r['assembled_response'])
            same(g['response_sha256'],rs);same(r['model_sha256'],selected['sha256'] if arm=='joint' else plan['comparator']['model_sha256'])
            same(tsha(r['prompt']),r['prompt_sha256']);same(r['returncode'],0)
            same(r['infer_source_sha256'],plan['frozen_evaluation']['infer']['sha256']);same(r['runner_sha256'],plan['frozen_evaluation']['runner']['sha256'])
            same(p['json_syntax_valid'],r['assessment']['json_valid']);same(p['parsed_concern'],r['assessment']['concern'])
            same(p['production_usable'],r['assessment']['parsed_findings'] is not None)
            same(p['production_usable'],g['outcome']['production_parse']);same(p['parsed_concern'],g['outcome']['concern']);same(p['findings_count'],g['outcome']['findings_count'])
            tb=Path(r['trace_file']).read_bytes();same(sha(tb),r['trace_sha256']);same(json.loads(tb),r['trace'])
            same(r['trace']['generated_token_ids'][0],r['actual_first_token_id']);same(r['trace']['stop_reason'],r['stop_reason'])
            if kind=='train':
                sr=sftmap[name]
                prompt=''.join('<|im_start|>'+m['role']+'\n'+m['content']+'<|im_end|>\n' for m in sr['messages'][:2])+'<|im_start|>assistant\n'
                same(prompt,r['prompt'])
            if arm=='control' and kind=='train':
                old=oldmap[name]
                for key in ['prompt','assembled_response','continuation','model_sha256','original_prompt_ids','stop_reason']:same(old[key],r[key])
                replay.append(dict(id=name,prompt_sha256=r['prompt_sha256'],response_sha256=rs,prompt_bytes_equal=True,response_bytes_equal=True))
                note=control_note(r);origin='Prior judgment reused after exact prompt/complete response verification; nonempty/malformed content reread.'
            elif arm=='control':
                note=control_audit_note(r,mode);origin='Previously independently read expanded control response; complete response/hash reverified.'
            elif kind=='train':
                assert (Path(fn).name,name,rs) in reviewed
                note=trainmanual['nonempty_case_judgments'][name] if p['parsed_concern'] is not False else empty_note(r)
                origin='Complete response manually read against v2; identical same-case natural/shared responses share the semantic reading.'
            else:
                n=othernotes[(slug,name)]
                same(n['response_sha256'],rs);same(n['response'],r['assembled_response']);same(n['prompt_sha256'],r['prompt_sha256'])
                same(n['source_file_sha256'],SOURCES[str(ROOT/fn)]['sha256'])
                note={k:n[k] for k in MKEYS};note['assessment']=n['manual_rationale']
                origin='Independent second reviewer read complete diagnostics/audit response; primary reconciled bindings and nonempty reasons.'
            alts=auditmap[name]['audit_metadata'].get('expected_valid_citation_alternatives',auditmap[name]['expected_line_ids']) if kind=='audit' else None
            c=dict(id=name,pair=r['pair'],arm=arm,cohort=slug,source=fn,record_line=lineno,prompt_sha256=r['prompt_sha256'],
              supplied_prompt_sha256=r['supplied_prompt_sha256'],response_sha256=rs,trace_sha256=r['trace_sha256'],model_sha256=r['model_sha256'],
              recorded_infer_source_sha256=r['infer_source_sha256'],recorded_runner_sha256=r['runner_sha256'],
              expected_concern=r['expected_concern'],expected_line_ids=r['expected_line_ids'],semantically_permitted_audit_citation_alternatives=alts,
              actual_first_token_id=r['actual_first_token_id'],stop_reason=r['stop_reason'],emitted_tokens=r['trace']['emitted_tokens'],
              response=r['assembled_response'],visible_line_ids=[int(x) for x in re.findall(r'"line_id"\s*:\s*"?([0-9]+)',r['assembled_response'])],
              review_origin=origin,**{k:v for k,v in p.items() if k!='name'},**note)
            c['presence_correct']=None if c['parsed_concern'] is None else c['parsed_concern']==c['expected_concern']
            assert not c['full_review_pass'] or c['production_usable']
            same(c['correct_clean'],not c['expected_concern'] and c['production_usable'] and c['parsed_concern'] is False)
            assert not c['genuine_issue_detected'] or c['reason_grounded'] and c['citation_causally_appropriate']
            if c['expected_concern']:assert not c['full_review_pass'] or c['genuine_issue_detected'] and c['all_findings_grounded'] and c['all_material_claims_supported']
            cases.append(c)
        grouped=defaultdict(list)
        for c in cases:grouped[c['pair']].append(c)
        pairs=[]
        for pair,cs in grouped.items():
            same(sorted(c['expected_concern'] for c in cs),[False,True])
            pairs.append(dict(pair=pair,case_ids=[c['id'] for c in cs],presence_correct=all(c['presence_correct'] is True for c in cs),
              usable_presence_correct=all(c['presence_correct'] is True and c['production_usable'] for c in cs),full_review_pass=all(c['full_review_pass'] for c in cs)))
        ct=counts(cases,pairs);mc=summary['cohorts'][arm][slug]['counts']
        for a,b in [('cases','cases'),('pairs','pairs'),('json_syntax_valid','json_valid'),('production_usable','production_parse'),
          ('parsed_presence_null','undecidable_presence'),('eos','eos'),('token_limit','token_limit'),('complete_presence_pairs','complete_presence_pairs'),
          ('complete_usable_presence_pairs','complete_usable_presence_pairs')]:same(ct[a],mc[b])
        same(ct['full_reviews_pass'],ct['grounded_concern_reviews']+ct['correct_clean_reviews'])
        cohorts[arm][slug]=dict(model_sha256=cases[0]['model_sha256'],source=fn,source_sha256=SOURCES[str(ROOT/fn)]['sha256'],counts=ct,cases=cases,pairs=pairs)

nat={r['name']:r for r in raw['joint']['train-natural']};shared={r['name']:r for r in raw['joint']['train-shared']}
comp=[]
for name,a in nat.items():
    b=shared[name];same(a['prompt'],b['prompt']);same(a['chunk'],b['chunk'])
    at=a['trace']['generated_token_ids'];bt=b['trace']['generated_token_ids']
    comp.append(dict(id=name,same_original_prompt_and_chunk=True,natural_response_sha256=tsha(a['assembled_response']),shared_response_sha256=tsha(b['assembled_response']),
      complete_response_bytes_equal=a['assembled_response']==b['assembled_response'],natural_stop_reason=a['stop_reason'],shared_stop_reason=b['stop_reason'],
      stop_reasons_equal=a['stop_reason']==b['stop_reason'],natural_starts_shared_prefix_ids=at[:3]==[4913,3903,819],
      continuation_ids_equal_over_natural_observed_span=at[3:]==bt[:len(at)-3],natural_sampled_ids_including_eos=len(at),shared_sampled_ids_including_eos=len(bt)))
same(len(comp),40)
for key,n in [('complete_response_bytes_equal',38),('stop_reasons_equal',40),('natural_starts_shared_prefix_ids',40),('continuation_ids_equal_over_natural_observed_span',40)]:same(sum(c[key] for c in comp),n)
same(sum(c['counts']['cases'] for c in cohorts['joint'].values()),108);same(sum(c['counts']['cases'] for c in cohorts['control'].values()),56)
for slug in ['train-natural','train-shared']:
    for key,value in dict(genuine_issues_detected=4,grounded_concern_reviews=3,correct_clean_reviews=15,full_reviews_pass=18,full_review_pairs=2).items():same(cohorts['joint'][slug]['counts'][key],value)
same(cohorts['joint']['diagnostics-natural']['counts']['correct_clean_reviews'],5)
same_diff=['scoped-python-analysis','approved-binary-decoder','sqlite-build-requirement','background-service-scope','scoped-design-record','checksum-indirection']
for cs in cohorts.values():
    for slug,c in cs.items():
        if slug.startswith('train-'):
            ps=[p for p in c['pairs'] if p['pair'] in same_diff];xs=[x for x in c['cases'] if x['pair'] in same_diff]
            c['same_diff_context_subscore']={'families':same_diff,'counts':counts(xs,ps)}
result=dict(schema_version=1,complete=True,created_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
 scope=dict(total_responses=164,new_joint_responses_manually_read=108,verified_control_responses=56,matched_followup_responses=8,matched_followup_included_here=False,matched_followup_summary='models/matched-shape-summary.json'),
 method='Complete text was read against its exact diff/rules/behavior. All108 new joint responses were manually read; identical same-case natural/shared responses reuse a reading after equality verification. Control40 reuse requires exact prompt/response matches; expanded control16 retain their individually read hash-bound judgments. Production parseReview was invoked read-only on all164. No model/tokenizer execution.',
 rubric={
  'parsed_concern':'True/false only from a complete JSON findings array after allowed fence/EOS normalization. Malformed JSON or absent findings array stays null; visible malformed reasons are still read.',
  'production_usable':'Unchanged parseReview accepts the complete response and changed-line citations. Canonical object format is separate because production also accepts bare arrays.',
  'reason_grounded':'A reason or intelligible visible fragment identifies an actual concrete rule conflict or failure mechanism. Exact gold wording is not required; citation/whole-response usability are separate.',
  'genuine_issue_detected':'At least one supported concrete mechanism has an available causally appropriate citation, even if inaccurate extras spoil the complete review.',
  'all_material_claims_supported':'Every intelligible factual/causal claim is supported. Null means no material claim. True descriptive fragments can occur without a detected issue.',
  'all_findings_grounded':'Every finding explains a real supported concern with causal citation and no inaccurate elaboration. Empty findings satisfy this vacuously.',
  'full_review_pass':'Production accepted complete review: concern requires genuine cited issue, all findings/material claims supported and no unsupported extras; clean requires empty findings.',
  'alternative_citations':'Canonical reference IDs are not a scoring criterion. Any available changed line with a valid causal connection earns credit. Audit harmful replacements explicitly permit ID1 or2; unchanged context cannot be cited.',
  'full_review_pairs':'Both concern and clean reviews pass fully. Presence and usable-presence pairs are separate weaker measurements.',
  'language_precision':'Awkward meaningful explanations can pass: zero workers proceeding and read-only replacement identify prohibited behavior. Fluency/exact wording are not required.',
  'overflow_adjudication':'The removed threshold check and overflow are genuinely detected; strict full review rejects added inaccurate numerical/probabilistic detail. A generous one-case sensitivity is reported.'},
 sources=SOURCES,models=dict(control_sha256=plan['comparator']['model_sha256'],joint_sha256=selected['sha256'],joint_selected_update=100),cohorts=cohorts,
 comparisons={
  'control_shared_judgment_reuse':dict(verified_prompt_and_response_matches=40,cases=replay),
  'joint_natural_vs_shared_training':dict(cases=40,complete_response_byte_matches=38,stop_reason_matches=40,natural_prefix_id_matches=40,
   aligned_continuation_id_matches_over_natural_span=40,different_complete_responses=[x['id'] for x in comp if not x['complete_response_bytes_equal']],
   explanation='All40 natural paths emit the three supplied-prefix IDs and following sampled IDs agree over the natural observed span. The38 EOS-complete responses are byte-identical. Separate-document and NULL-guard reasons loop to limit192 in both modes; shared samples three extra continuation tokens because its prefix is supplied outside that generation budget.',
   cases_detail=comp),
  'shared_training_first_tokens':summary['shared_training_first_token'],
  'overflow_sensitivity':dict(case='allocation-product-overflow-introduced',complete_response=nat['allocation-product-overflow-introduced']['assembled_response'],
   primary=dict(genuine_issue_detected=True,full_review_pass=False,per_training_mode=dict(genuine_issues_detected=4,grounded_concern_reviews=3,correct_clean_reviews=15,full_reviews_pass=18,full_review_pairs=2)),
   alternative_generous_bound_language_reading=dict(genuine_issue_detected=True,full_review_pass=True,per_training_mode=dict(genuine_issues_detected=4,grounded_concern_reviews=4,correct_clean_reviews=15,full_reviews_pass=19,full_review_pairs=3)),
   independent_disagreement=trainmanual['nonempty_case_judgments']['allocation-product-overflow-introduced']['adjudication'],
   meaning='Primary records detected overflow with inaccurate elaboration, not a missed overflow.')},
 observations=[
  'Joint learns the natural three-token findings opening on all40 training prompts. Natural/shared semantic outcomes agree; only the two budget-limited looping tails differ in complete bytes.',
  'Each training mode detects four genuine issues: lost trie attribution, zero workers reaching the algorithm, read-only replacement and allocation-product overflow. Three strict complete concern reviews pass; overflow is detected with inaccurate additional detail.',
  'Trie attribution is correctly flagged when removed, but the clean restoration receives a benign restatement as a finding. The two strict full pairs are zero-worker-guard and write-permission-check.',
  'Control shared -> joint shared: production acceptance29->38/40, strict grounded concerns0->3/20, correct clean14->15/20, full pairs0->2/20. Presence pairs1->5 remain separate.',
  'Existing diagnostics12 yield no genuine/fully grounded concern, five correct clean and no full pair. Approved-send output loops; automatic-network output makes a false offline claim.',
  'Both expanded joint audit modes return eight empty reviews: four clean pass and four harmful miss per mode. Shared-control diff copying is replaced by valid empty output, without detecting either harmful mechanism.',
  'Expanded and matched suites informed the proposed corpus revision and are development diagnostics. The matched-template8 follow-up is scored separately, outside these164.'],
 verification=dict(all_source_jsonl_complete=True,all_case_ids_and_counts_complete=True,all164_trace_files_hash_and_embedded_object_verified=True,
  all164_production_parses_recomputed=True,all_parse_presence_counts_agree_with_generation_summary=True,all80_joint_training_prompts_reconstructed_from_v2=True,
  control40_prompt_and_response_reuse_verified=True,all108_new_joint_responses_have_manual_bindings=True,assessment_changed_training_inference_sources=False))
with OUT.open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
print(json.dumps(dict(output=str(OUT),sha256=sha(OUT.read_bytes()),bytes=OUT.stat().st_size,
 counts={a:{s:c['counts'] for s,c in cs.items()} for a,cs in cohorts.items()}),indent=2))

