"""Byte-level check for one base + last-MLP F32 export; run from repo root."""
from contextlib import ExitStack
import importlib.util,json,mmap,sys
from pathlib import Path
helper=Path('training/results/2026-09-29-convergence/check_convergence_export.py')
spec=importlib.util.spec_from_file_location('gguf_audit',helper);audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
base_path,model_path,prefix,output=map(Path,sys.argv[1:])
with ExitStack() as stack:
 def mapped(p):
  f=stack.enter_context(p.open('rb'));return stack.enter_context(mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ))
 base,model=mapped(base_path),mapped(model_path);b,a=audit.parse_gguf(base),audit.parse_gguf(model)
 assert audit.normalized_header(base,b)==audit.normalized_header(model,a)
 assert len(a['tensors'])==len(b['tensors'])
 last=max(int(t['name'].split('.')[1]) for t in b['tensors'] if t['name'].startswith('blk.') and t['name'].endswith('.ffn_gate.weight'))
 adapted={f'blk.{last}.ffn_{part}.weight':part for part in ['gate','up','down']}
 counts=dict(unchanged=0,adapted=0);cursor=0
 for original,actual in zip(b['tensors'],a['tensors']):
  assert original['name']==actual['name'] and original['shape']==actual['shape']
  assert actual['offset']==cursor
  if actual['name'] in adapted:
   expected=mapped(Path(str(prefix)+'.'+adapted[actual['name']]+'.f32'));start=0
   assert actual['type']==0 and len(expected)==actual['bytes'];counts['adapted']+=1
  else:
   expected=base;start=b['data_offset']+original['offset'];counts['unchanged']+=1
   assert original['type']==actual['type'] and original['bytes']==actual['bytes']
  assert audit.equal_payload(model,a['data_offset']+actual['offset'],expected,start,actual['bytes'])
  cursor=audit.align32(cursor+actual['bytes'])
 assert counts['adapted']==3 and len(model)==a['data_offset']+cursor
 record=dict(base=dict(path=str(base_path),sha256=audit.digest(base),bytes=len(base)),model=dict(path=str(model_path),sha256=audit.digest(model),bytes=len(model)),prefix=str(prefix),metadata_equal=True,expected_extent=a['data_offset']+cursor,**counts,valid=True)
Path(output).write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))
