#!/usr/bin/env python3
"""Independently check frozen prompt-only serialization, folds and masks. No model arithmetic."""
from pathlib import Path
import hashlib,json,struct
BASE=Path(__file__).resolve().parent
REPO=BASE.parent/'jovovich'
CORPUS=REPO/'training/sft_review_v4.jsonl'
PLAN=BASE/'readout-plan-draft.json'
INPUTS=BASE/'frozen-inputs'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
plan=json.loads(PLAN.read_text()); all_rows=[json.loads(s) for s in CORPUS.read_text().splitlines()]
reviews=[r for r in all_rows if r['kind']=='review']; receipt=json.loads((INPUTS/'readout-preparation.json').read_text())
meta=json.loads((INPUTS/'readout-rows.json').read_text()); source_rows=meta['rows']
assert sha(CORPUS)==plan['cohort']['corpus_sha256']==receipt['corpus']['sha256']
assert sha(BASE/'prepare_readout.py')==receipt['preparer']['sha256']
for f in receipt['files']:assert sha(INPUTS/f['path'])==f['sha256'] and (INPUTS/f['path']).stat().st_size==f['bytes']
assert len(reviews)==len(source_rows)==52
binary=(INPUTS/'readout-input.bin').read_bytes(); assert binary[:8]==b'JVRO1\0\0\0'
assert struct.unpack_from('<I',binary,8)==(52,); offset=12
for original,row in zip(reviews,source_rows):
 assert row['id']==original['id'] and row['pair']==original['pair']
 roles={m['role']:m['content'] for m in original['messages']}
 assert row['label']==int(bool(json.loads(roles['assistant'])['findings']))
 for role in ('system','user'):
  size,=struct.unpack_from('<I',binary,offset);offset+=4
  actual=binary[offset:offset+size];offset+=size
  assert actual==roles[role].encode()
 assert row['family_index']==plan['cohort']['family_order'].index(row['family'])
assert offset==len(binary)
seen=[]
for family in range(20):
 train=[r for r in source_rows if r['family_index']!=family];test=[r for r in source_rows if r['family_index']==family]
 assert len(test) in (2,4) and len(train)+len(test)==52
 assert sum(r['label'] for r in train)*2==len(train)
 seen.extend(r['index'] for r in test)
assert sorted(seen)==list(range(52))
maskjson=json.loads((INPUTS/'readout-masks.json').read_text());masks=maskjson['masks']
assert len(masks)==len(set(masks))==99
assert (INPUTS/'readout-masks.txt').read_text().splitlines()==['JOVOVICH_MASKS_V1','99 20']+masks
reproduced=[];accepted=[];counter=0
while len(reproduced)<99:
 n=int.from_bytes(hashlib.sha256(f'jovovich-readout-permutation:20261001:{counter}'.encode()).digest()[:4],'little')&((1<<20)-1)
 mask=''.join(str(n>>k&1) for k in range(20))
 if n and mask not in reproduced:reproduced.append(mask);accepted.append(counter)
 counter+=1
assert masks==reproduced and accepted==maskjson['accepted_counters']
for mask in masks:
 assert len(mask)==20 and set(mask)<={'0','1'} and mask!='0'*20
 for pair in range(26):
  members=[r for r in source_rows if r['pair_index']==pair]
  assert len(members)==2 and len({r['family_index'] for r in members})==1
  assert sum(r['label']^int(mask[r['family_index']]) for r in members)==1
result={'status':'pass','scope':'Preparation, not model extraction or fitting','checks':['corpus and all input receipt hashes','prompt binary contains exactly all52 original system/user strings and no other fields','labels derive directly from gold findings','20fold disjoint heldout coverage and training class balance','99 unique nonidentity SHA-family masks independently reproduced','paired balance and quartet shared-family coupling for every mask'],'bound_sources':{'corpus':sha(CORPUS),'preparer':sha(BASE/'prepare_readout.py'),'prompt_input':sha(INPUTS/'readout-input.bin'),'rows':sha(INPUTS/'readout-rows.json'),'masks':sha(INPUTS/'readout-masks.txt')},'model_run_performed':False}
print(json.dumps(result,indent=2))
