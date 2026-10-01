#!/usr/bin/env python3
import argparse, hashlib, json, re, subprocess, tempfile
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--repo',required=True);p.add_argument('--output',required=True);a=p.parse_args()
repo=Path(a.repo); output=Path(a.output)
def sha(b):return hashlib.sha256(b).hexdigest()
def bind(p):
 b=p.read_bytes();return {'path':str(p.relative_to(repo)) if p.is_relative_to(repo) else str(p),'bytes':len(b),'sha256':sha(b)}
v4p=repo/'training/sft_review_v4.jsonl';v5p=repo/'training/sft_review_v5.jsonl'; dp=repo/'training/review_v5_design.json'
v4lines=v4p.read_text().splitlines();v5lines=v5p.read_text().splitlines();v4=[json.loads(s) for s in v4lines];v5=[json.loads(s) for s in v5lines]
assert len(v4)==len(v5)==76
assert [r['id'] for r in v4]==[r['id'] for r in v5]
design=json.loads(dp.read_text()); families={f['family']:f for f in design['families']}

def splitrow(r):
 text=r['messages'][1]['content']; pre,tail=text.split('\n\nSurrounding diff:\n');diff,tail=tail.split('\n\nChanged lines to review:\n');listing,end=tail.split('\n\nReview the changed lines against these rules.')
 return pre,diff,listing,end

def sides(diff):
 hdr,*lines=diff.splitlines();m=re.fullmatch(r'@@ -(\d+),(\d+) \+(\d+),(\d+) @@',hdr);assert m
 assert all(l and l[0] in ' +-' for l in lines)
 old=[l[1:] for l in lines if l[0]!='+'];new=[l[1:] for l in lines if l[0]!='-'];assert len(old)==int(m[2]) and len(new)==int(m[4])
 return old,new

def features(diff):
 _,*lines=diff.splitlines();after='\n'.join(l[1:] for l in lines if l[0]!='-')
 return [sum(l[0]=='+' for l in lines),sum(l[0]=='-' for l in lines),sum(l[0]==' ' for l in lines),len(re.findall(r'\bif\s*\(',after)),len(re.findall(r'\.sort\s*\(',after)),after.count('firwood/trie')]

changed=[];groups={}; rows=[]; leakage=[]
for i,(old,new) in enumerate(zip(v4,v5)):
 assert old.keys()==new.keys()
 assert old['messages'][0]==new['messages'][0] and old['messages'][2]==new['messages'][2]
 assert {k:v for k,v in old.items() if k!='messages'}=={k:v for k,v in new.items() if k!='messages'}
 if v4lines[i]!=v5lines[i]:
  oldparts=splitrow(old);newparts=splitrow(new);assert oldparts[0]==newparts[0] and oldparts[2:]==newparts[2:]
  x=oldparts[1].splitlines();y=newparts[1].splitlines();assert len(x)==len(y)
  diffs=[(u,v) for u,v in zip(x,y) if u!=v];assert len(diffs)==1 and all(u.startswith(' ') and v.startswith(' ') for u,v in diffs)
  changed.append(new['id'])
 if new['kind']!='review': continue
 pre,diff,listing,end=splitrow(new); bfr,afr=sides(diff); gold=json.loads(new['messages'][2]['content']); concern=bool(gold['findings'])
 assert new['id'] not in pre+diff+listing+end and new['pair'] not in pre+diff+listing+end
 groups.setdefault(new['pair'],[]).append(new)
 fam=next((f for f in families if new['pair'] in (f+'-deletion',f+'-replacement')),None)
 if fam:
  rows.append({'id':new['id'],'family':fam,'concern':concern,'before':bfr,'after':afr})
for pair,rs in groups.items():
 assert len(rs)==2 and sorted(bool(json.loads(r['messages'][2]['content'])['findings']) for r in rs)==[False,True]
 if any(pair in (f+'-deletion',f+'-replacement') for f in families):
  x,y=map(splitrow,rs);assert x[0]==y[0] and x[2:]==y[2:]
  assert features(x[1])==features(y[1]),pair
  xls=x[1].splitlines();yls=y[1].splitlines();assert len(xls)==len(yls)
  d=[(u,v) for u,v in zip(xls,yls) if u!=v];assert len(d)==1 and all(u[0]==v[0]==' ' for u,v in d)
  returns=[len(re.findall(r'\breturn\b','\n'.join(sides(z[1])[1]))) for z in (x,y)]
  leakage.append({'pair':pair,'return_counts_in_row_order':returns,'equal':returns[0]==returns[1]})
assert len(groups)==26 and len(rows)==24
# Some clean contexts may remain byte-identical to v4. Every changed row must belong to a declared quartet.
assert set(changed).issubset({r['id'] for r in rows})

common=r'''#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
typedef struct { int value; } node;
typedef struct { int can_write; } session_t;
enum { DENIED = -41 };
static node memory;
static uint64_t vector;
static int failure, hazard, allocations, assignments, writes, last_id, last_value;
static size_t bytes_requested, share_recorded;
static void reset(void) { failure=hazard=allocations=assignments=writes=0;bytes_requested=share_recorded=0;errno=0; }
static void *audit_calloc(size_t n,size_t z) { assert(n==1 && z==sizeof(node));allocations++;return failure ? NULL : &memory; }
static void *audit_malloc(size_t n) { allocations++;bytes_requested=n;return &vector; }
static int assign_share(size_t n) { assignments++;share_recorded=n;return 73; }
static int replace_record(int id,int value) { writes++;last_id=id;last_value=value;return 81; }
#define calloc audit_calloc
#define malloc audit_malloc
'''
functions=[];checks=[];records=[]
for idx,row in enumerate(rows):
 family=row['family']
 for stage in ['before','after']:
  body='\n'.join(row[stage]);name=f'fixture_{idx}_{stage}';harm=row['concern'] and stage=='after'
  rec={'id':row['id'],'stage':stage,'family':family}
  if family=='allocation-null-guard':
   assert body.count('n->value = value;')==1
   body=body.replace('n->value = value;','if (!n) { hazard=1; return NULL; } n->value = value;')
   functions.append(f'static node *{name}(int value) {{\n{body}\n}}')
   checks.append('{ int values[]={INT_MIN,-1,0,1,INT_MAX}; for(size_t i=0;i<sizeof(values)/sizeof(values[0]);i++){'+f'reset();failure=1;assert({name}(values[i])==NULL && hazard=={int(harm)} && allocations==1);reset();node *n={name}(values[i]);assert(n==&memory && n->value==values[i] && !hazard && allocations==1);'+'}}')
   rec['witness_cases']=10
  elif family=='zero-worker-guard':
   assert body.count('size_t share = total / workers;')==1
   body=body.replace('size_t share = total / workers;','if (!workers) { hazard=1; return -99; } size_t share = total / workers;')
   functions.append(f'static int {name}(size_t total,size_t workers) {{\n{body}\n}}')
   checks.append('{ size_t totals[]={0,1,12,SIZE_MAX}, workers[]={1,3,SIZE_MAX};for(size_t i=0;i<4;i++){'+f'reset();assert({name}(totals[i],0)=={ -99 if harm else "EINVAL"} && hazard=={int(harm)} && !assignments);'+'for(size_t j=0;j<3;j++){'+f'reset();assert({name}(totals[i],workers[j])==73 && !hazard && assignments==1 && share_recorded==totals[i]/workers[j]);'+'}}}')
   rec['witness_cases']=16
  elif family=='write-permission-check':
   functions.append(f'static int {name}(session_t session,int id,int value) {{\n{body}\n}}')
   checks.append('{ int ids[]={-1,0,2},permissions[]={0,1,2,-1};for(size_t i=0;i<3;i++)for(size_t j=0;j<4;j++){'+f'int allowed=permissions[j]!=0 || {int(harm)};reset();assert({name}((session_t){{permissions[j]}},ids[i],7)==(allowed?81:DENIED));assert(writes==allowed);if(allowed)assert(last_id==ids[i] && last_value==7);'+'}}')
   rec['witness_cases']=12
  elif family=='allocation-product-overflow':
   functions.append(f'static uint64_t *{name}(size_t count) {{ uint64_t *items;\n{body}\nreturn items; }}')
   checks.append('{ size_t values[]={0,1,3,SIZE_MAX/8,SIZE_MAX/8+1,SIZE_MAX/8+2,SIZE_MAX/4,SIZE_MAX/4+1,SIZE_MAX};for(size_t i=0;i<9;i++){'+f'size_t count=values[i];int admitted=count<=SIZE_MAX/{4 if harm else 8};reset();assert(({name}(count)!=NULL)==admitted);assert(allocations==admitted);if(admitted)assert(bytes_requested==count*sizeof(uint64_t));'+'}}')
   rec['witness_cases']=9
  elif family=='stable-manifest-order':
   rec['language']='JavaScript'
   rec['body']=body
  elif family=='preserve-trie-credit':
   # The object of attribution, not simply the upstream-name occurrence, controls this witness.
   credits=[line for line in row[stage] if 'firwood/trie (MIT)' in line]
   implementation=[line for line in credits if line.startswith('Trie design adapted from ') or line.startswith('Trie implementation derived from ')]
   assert bool(implementation)!=harm
   rec.update({'language':'NOTICE','implementation_credit_present':bool(implementation),'credit_lines':credits,'witness_cases':1})
  else:raise AssertionError(family)
  records.append(rec)
source=common+'\n'.join(functions)+'\nint main(void) {\n'+'\n'.join(checks)+'\nreturn 0; }\n'
js_cases=[r for r in records if r.get('language')=='JavaScript']
script=r'''const cases=JSON.parse(process.argv[1]);for(const c of cases){const f=new Function('entries','const output=[];\n'+c.body+'\nreturn output.join("\\n");');const orders=[['gamma','alpha','beta'],['alpha','beta','gamma'],['beta','gamma','alpha']];const outputs=orders.map(keys=>f(Object.fromEntries(keys.map(k=>[k,k.length]))));const harm=c.stage==='after'&&c.id.endsWith('-concern');if((new Set(outputs).size>1)!==harm)throw Error(c.id);if(!harm&&outputs.some(x=>x!=='alpha:5\nbeta:4\ngamma:5'))throw Error('sort output');if(f({})!=='')throw Error('empty');if(f({only:1})!=='only:1')throw Error('singleton');c.outputs=outputs;delete c.body;c.witness_cases=5;}process.stdout.write(JSON.stringify(cases));'''
with tempfile.TemporaryDirectory(prefix='jovovich-v5-independent-') as td:
 td=Path(td);(td/'probe.c').write_text(source)
 cc=subprocess.run(['cc','-std=c11','-O0','-Wall','-Wextra','-Werror','-Wno-error=address','-Wno-error=type-limits',str(td/'probe.c'),'-o',str(td/'probe')],capture_output=True,text=True);assert cc.returncode==0,cc.stderr
 cr=subprocess.run([str(td/'probe')],capture_output=True,text=True);assert cr.returncode==0,cr.stderr
 jr=subprocess.run(['node','-e',script,json.dumps(js_cases)],capture_output=True,text=True);assert jr.returncode==0,jr.stderr
 js_results=json.loads(jr.stdout)
for r in records:
 if r.get('language')=='JavaScript': r.update(next(j for j in js_results if j['id']==r['id'] and j['stage']==r['stage']));r.pop('body',None)
result={'schema_version':1,'status':'PASS','scope':'Independent v5 corpus and exact before/after semantics audit; no model inference or training.','bindings':[bind(x) for x in (v4p,v5p,dp)],'structural':{'total_rows':76,'review_rows':52,'pairs':26,'quartet_rows':24,'raw_rows_changed':len(changed),'raw_rows_unchanged':76-len(changed),'gold_answers_identical':76,'unchanged_system_messages':76,'changed_rows_have_only_one_unchanged_diff_context_line_changed':len(changed),'matched_six_nontoken_nuisance_features_pairs':12,'pairwise_preamble_changed_listing_instruction_identical':12,'pairwise_label_difference_confined_to_one_context_line':12,'row_ids_and_pair_ids_absent_from_model_user_text':52},'semantic':{'states':48,'witness_cases':sum(r['witness_cases'] for r in records),'method':'Independent exact snippet compilation/execution; sentinels intercept null dereference and zero division immediately before the operation; allocation/writes are recorded with stubs. Boundary grids include zero total with nonzero workers, writable id zero, full integer domains at representative bounds and allocation mismatch band. JS independently tests three insertion orders, empty and singleton maps. NOTICE checks the attribution object.','c_source_sha256':sha(source.encode()),'c_compile_exit':cc.returncode,'c_compile_stderr':cc.stderr,'expected_nonfatal_warning_classes':['-Waddress','-Wtype-limits'],'c_run_exit':cr.returncode,'javascript_exit':jr.returncode,'records':records},'additional_count_audit':{'feature':'after-side return token count','pairs':leakage,'matched_pairs':sum(r['equal'] for r in leakage),'mismatched_pairs':sum(not r['equal'] for r in leakage),'scope':'The seven prescribed nuisance coordinates are the declared matching target. This additional feature records residual lexical structure.'},'native_token_matching':'Use the separately bound native-token audit for the seventh coordinate.'}
output.parent.mkdir(parents=True,exist_ok=True)
with output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
print(json.dumps({'status':result['status'],'output':str(output),'states':48,'witness_cases':result['semantic']['witness_cases'],'changed_rows':len(changed),'return_count_mismatched_pairs':result['additional_count_audit']['mismatched_pairs']}))
