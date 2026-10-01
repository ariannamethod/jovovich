#!/usr/bin/env python3
import argparse, hashlib, json, re, subprocess, tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--repo',required=True);p.add_argument('--output',required=True);args=p.parse_args();repo=Path(args.repo)
corpus=repo/'training/review_holdout_v5.jsonl';rows=[json.loads(l) for l in corpus.read_text().splitlines()];assert len(rows)==24
sha=lambda b:hashlib.sha256(b).hexdigest()
def sides(patch):
 h,*lines=patch.splitlines();m=re.fullmatch(r'@@ -(\d+),(\d+) \+(\d+),(\d+) @@',h);assert m
 before='\n'.join(l[1:] for l in lines if l[0]!='+')+'\n';after='\n'.join(l[1:] for l in lines if l[0]!='-')+'\n'
 assert len(before.splitlines())==int(m[2]) and len(after.splitlines())==int(m[4]);return before,after

groups={};families=set();records=[];total_cases=0;raw_checks=0
for r in rows:
 groups.setdefault(r['pair'],[]).append(r);families.add(r['audit_metadata']['family']);assert r['audit_metadata']['split']=='evaluation-only'
 assert r['expected_concern']==bool(r['gold']['findings'])
 assert r['expected_line_ids']==(([1,2] if r['audit_metadata']['shape']=='replacement-noop' else [1]) if r['expected_concern'] else [])
for pair,rs in groups.items():
 assert len(rs)==2 and sorted(r['expected_concern'] for r in rs)==[False,True];assert rs[0]['context']==rs[1]['context'];assert rs[0]['files'][0]['path']==rs[1]['files'][0]['path']
 x,y=[r['files'][0]['patch'].splitlines() for r in rs];assert len(x)==len(y);d=[(a,b) for a,b in zip(x,y) if a!=b];assert len(d)==1 and all(a[0]==b[0]==' ' for a,b in d)
 assert [a for a in x if a[0] in '+-']==[a for a in y if a[0] in '+-']
 assert rs[0]['audit_metadata']['nuisance_counts_excluding_native_prompt']==rs[1]['audit_metadata']['nuisance_counts_excluding_native_prompt']
assert len(groups)==12 and len(families)==6
with tempfile.TemporaryDirectory(prefix='jovovich-holdout-independent-') as td:
 td=Path(td)
 for r in rows:
  family=r['audit_metadata']['family']
  for stage,source in zip(['before','after'],sides(r['files'][0]['patch'])):
   assert sha(source.encode())==r['audit_metadata'][stage+'_sha256'];harm=int(stage=='after' and r['expected_concern']);checks=0
   if r['audit_metadata']['language']=='c':
    raw=td/'raw.c';raw.write_text(source);q=subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsyntax-only',str(raw)],capture_output=True,text=True);assert q.returncode==0,q.stderr;raw_checks+=1
    if family=='shift-width':
     assert source.count('*out = value << shift;')==1
     source=source.replace('*out = value << shift;','if (shift >= 32U) { dangerous = 1; return 77; } *out = value << shift;')
     tail='int main(void){unsigned shifts[]={0,1,15,30,31,32,33,UINT_MAX};uint32_t values[]={0,1,0x80000000U,UINT32_MAX};for(unsigned i=0;i<8;i++)for(unsigned j=0;j<4;j++){uint32_t out=123;dangerous=0;int r=bit_window(values[j],shifts[i],&out);int bad='+str(harm)+' && shifts[i]==32;assert(dangerous==bad);if(bad)assert(r==77);else if(shifts[i]>=32)assert(r==-1 && out==123);else assert(r==0 && out==(uint32_t)(values[j]<<shifts[i]));}return 0;}'
     head='#include <limits.h>\nstatic int dangerous;\n';checks=32
    elif family=='bounded-termination':
     tail='int main(void){for(unsigned n=1;n<=4;n++)for(unsigned x=0;x<256;x++){unsigned char b[4]={11,22,33,44};b[n-1]=(unsigned char)x;record_end(b,n);assert(b[n-1]==('+str(harm)+'?x:0));for(unsigned i=0;i<4;i++)if(i!=n-1)assert(b[i]==(unsigned char)(11*(i+1)));}return 0;}';head='';checks=1024
    elif family=='reserved-flag-bits':
     tail='int main(void){for(unsigned x=0;x<256;x++)assert(flags_byte((uint8_t)x)==('+str(harm)+'?x:(x&15U)));return 0;}';head='';checks=256
    elif family=='erase-target':
     tail='int main(void){for(unsigned seed=0;seed<256;seed++){unsigned char b[4]={99,99,99,99};erase_snapshot((unsigned char)seed,b);for(unsigned j=0;j<4;j++)assert(b[j]==('+str(harm)+'?seed:0));}return 0;}';head='';checks=256
    else:raise AssertionError(family)
    src=td/'probe.c';src.write_text('#include <assert.h>\n'+head+source+'\n'+tail);q=subprocess.run(['cc','-std=c11','-O0','-Wall','-Wextra','-Werror',str(src),'-o',str(td/'probe')],capture_output=True,text=True);assert q.returncode==0,q.stderr
    q=subprocess.run([str(td/'probe')],capture_output=True,text=True);assert q.returncode==0,q.stderr
   else:
    if family=='finite-number':
     tail='const values=[0,-0,1,-1,Number.MIN_VALUE,-Number.MIN_VALUE,Number.MAX_VALUE,-Number.MAX_VALUE,0.5,NaN,Infinity,-Infinity];for(const v of values){const actual=nextReading(v);const expected=Number.isFinite(v)?v+1:(('+str(harm)+')&&!Number.isNaN(v)?v:null);assert.ok(Object.is(actual,expected));}';checks=12
    elif family=='array-end-boundary':
     tail='for(let n=0;n<=4;n++){const a=Array.from({length:n},(_,i)=>100+i);for(const i of [0,1,2,3,4,5,4294967295]){const expected=i<n?a[i]:(('+str(harm)+')&&i===n?undefined:null);assert.ok(Object.is(slotValue(a,i),expected));}}';checks=35
    else:raise AssertionError(family)
    js=td/'probe.mjs';js.write_text("import assert from 'node:assert/strict';\n"+source+'\n'+tail);q=subprocess.run(['node',str(js)],capture_output=True,text=True);assert q.returncode==0,q.stderr
   records.append({'id':r['id'],'family':family,'stage':stage,'source_sha256':r['audit_metadata'][stage+'_sha256'],'input_cases':checks,'expected_harmful_after':bool(harm),'status':'PASS'});total_cases+=checks
# Content provenance is kept separate from semantic family names.
prior_paths=['training/sft_review_v4.jsonl','training/results/2026-10-01-counterbalanced-review/fresh-transfer.jsonl','training/results/2026-10-01-joint-review/joint-diagnostics-natural.jsonl']
prior_text='\n'.join((repo/p).read_text() for p in prior_paths)
assert all(r['id'] not in prior_text and r['pair'] not in prior_text for r in rows)
result={'schema_version':1,'status':'PASS','scope':'Independent evaluation-only corpus audit; exact artifact before/after programs independently executed; no model inference.','bindings':[{'path':str(corpus.relative_to(repo)),'bytes':corpus.stat().st_size,'sha256':sha(corpus.read_bytes())},{'path':'training/holdout_v5_design.json','sha256':sha((repo/'training/holdout_v5_design.json').read_bytes())}], 'structural':{'rows':24,'pairs':12,'semantic_families':6,'pairwise_context_identical':12,'pairwise_changed_lines_identical':12,'pairwise_one_unchanged_context_line_difference':12,'pairwise_six_diff_nuisance_features_equal':12,'metadata_gold_consistency':24},'semantic':{'source_states':48,'independent_input_cases':total_cases,'original_c_syntax_checks':raw_checks,'all_compilation_and_execution_exit_codes':0,'invalid_shift_handling':'A sentinel immediately before the original shift records its reachability; valid shifts execute unchanged.','records':records},'novelty_review':{'source_paths':prior_paths,'new_ids_and_pair_ids_absent_from_prior_sources':True,'family_mechanisms':['uint32 shift width boundary','bounded final-byte termination','reserved high-bit clearing','nonfinite numeric acceptance','exclusive array endpoint','zeroization destination'],'shared_structural_relation':'Shift-width and array-end-boundary both distinguish inclusive from exclusive upper bounds. They are six semantic families.'},'native_prompt_lengths':'Seventh nuisance coordinate comes from separate native tokenizer audit.'}
out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
with out.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
print(json.dumps({'status':'PASS','path':str(out),'states':48,'independent_cases':total_cases}))
