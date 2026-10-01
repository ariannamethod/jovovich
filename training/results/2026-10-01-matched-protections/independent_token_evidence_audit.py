#!/usr/bin/env python3
import argparse, hashlib,json,re,struct
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--repo',required=True);p.add_argument('--reference',required=True);p.add_argument('--holdout-sft',required=True);p.add_argument('--output',required=True);a=p.parse_args();repo=Path(a.repo);ref=Path(a.reference)
sha=lambda b:hashlib.sha256(b).hexdigest()
def bind(path):return {'path':str(path),'bytes':path.stat().st_size,'sha256':sha(path.read_bytes())}
reports=[]
for name,corpus,receipt in [('training',repo/'training/sft_review_v5.jsonl',ref/'v5-token-final/receipt.json'),('holdout',Path(a.holdout_sft),ref/'holdout-token-final/receipt.json')]:
 raw=receipt.read_bytes();d=json.loads(raw);assert d['status']=='complete' and d['returncode']==0 and d['bindings_unchanged'] is True
 expectedbinding=next(x for x in d['bindings_before'] if x['path']==str(corpus));assert expectedbinding==bind(corpus)
 rows=[json.loads(l) for l in corpus.read_text().splitlines()];rows=[r for r in rows if r['kind']=='review'];n=len(rows)
 for b in d['outputs']:assert bind(Path(b['path']))==b
 binary=receipt.parent/'prompts.bin';data=binary.read_bytes();assert data[:8]==b'JVRO1\0\0\0';assert struct.unpack_from('<I',data,8)[0]==n;at=12
 for r in rows:
  assert [m['role'] for m in r['messages']]==['system','user','assistant']
  for m in r['messages'][:2]:
   size=struct.unpack_from('<I',data,at)[0];at+=4;text=data[at:at+size].decode('utf8');at+=size;assert text==m['content']
 assert at==len(data)
 traces=[json.loads(l) for l in (receipt.parent/'token-trace.jsonl').read_text().splitlines()];assert len(traces)==n==len(d['rows'])
 groups={}
 for i,(row,t,rec) in enumerate(zip(rows,traces,d['rows'])):
  assert t['row']==i and t['tokenize_only'] is True
  assert len(t['input_ids'])==t['input_tokens']==t['prompt_tokens']+3
  assert t['input_ids'][-3:]==t['prefix_ids']==[4913,3903,819]
  assert t['capture_position']==t['input_tokens']-1
  user=row['messages'][1]['content'];patch=user.split('\n\nSurrounding diff:\n')[1].split('\n\nChanged lines to review:\n')[0];h,*lines=patch.splitlines();aft='\n'.join(l[1:] for l in lines if l[0]!='-')
  f=[t['prompt_tokens']]+[sum(l[0]==c for l in lines) for c in '+- ']+[len(re.findall(r'\bif\s*\(',aft)),len(re.findall(r'\.sort\s*\(',aft)),aft.count('firwood/trie')]
  returns=len(re.findall(r'\breturn\b',aft));assert f==rec['features'] and returns==rec['after_return_statements'];assert rec['id']==row['id'] and rec['label']==int(bool(json.loads(row['messages'][2]['content'])['findings']))
  groups.setdefault(row['pair'],[]).append((f,returns,rec['label']))
 targetfamilies={f['family'] for f in json.loads((repo/'training/review_v5_design.json').read_text())['families']}
 target=[]
 for k,members in groups.items():
  assert len(members)==2 and sorted(m[2] for m in members)==[0,1]
  if name=='holdout' or any(k in (f+'-deletion',f+'-replacement') for f in targetfamilies):
   assert members[0][:2]==members[1][:2];target.append(k)
 assert len(target)==12
 reports.append({'cohort':name,'input':bind(corpus),'receipt':bind(receipt),'native_prompt_binary':bind(binary),'token_trace':bind(receipt.parent/'token-trace.jsonl'),'rows':n,'paired_groups':len(groups),'exact_system_user_only_serialized_rows':n,'all_trace_counts_and_feature_vectors_recomputed':n,'target_pairs_matching_seven_coordinates_and_return_count':target,'seven_feature_identical_pairs_in_entire_cohort':sum(m[0][0]==m[1][0] for m in groups.values()),'target_pair_feature_only_complete_correct_upper_bound':0})
result={'schema_version':1,'status':'PASS','scope':'Independent reparse of saved native token-only evidence; no tokenizer rerun, inference or training.','evidence':reports,'extractor_source_branch_inspection':'tokenize_only emits traces immediately after model metadata/tokenizer loading and prompt tokenization. The transformer load and forward_residual path is exclusively in the else branch.','feature_matching_consequence':'Each selected opposite-label pair has the same feature vector. A deterministic classifier given only that vector assigns the same label to both rows and therefore completes zero such pairs.','holdout_projection_note':'The separately audited holdout projection must remain bound to the canonical 24-row holdout corpus.'}
out=Path(a.output)
with out.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
print(json.dumps({'status':'PASS','cohorts':2,'serialized_rows':sum(x['rows'] for x in reports),'matched_target_pairs':24,'output':str(out)}))
