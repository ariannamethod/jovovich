#!/usr/bin/env python3
"""Candidate history: whole review prompts, native tokenizer, no model inference."""
import copy,json,subprocess,sys
from pathlib import Path
root=Path('/workspace/scratch/ec5ba60588d8')
repo=root/'jovovich'; out=root/'matched-reference'
source=[json.loads(x) for x in (repo/'training/sft_review_v4.jsonl').read_text().splitlines()]
candidates={
'zero-worker-guard': ['    if (total == 0) errno = EDOM;', '    if (total == 0) errno = ERANGE;', '    if (total == 0) errno = ENOMEM;', '    if (total == 0) puts("empty");', '    if (!total) { errno = EINVAL; }', '    if (total == 0) warn_empty();', '    if (total == 0) ++errno;', '    if (total == 0) errno |= EINVAL;'],
'write-permission-check': ['    if (id == 0) errno = EDOM;', '    if (id == 0) errno = ERANGE;', '    if (id == 0) errno = ENOMEM;', '    if (id == 0) puts("empty");', '    if (!id) { errno = EINVAL; }', '    if (id == 0) warn_empty();', '    if (id == 0) ++errno;', '    if (id == 0) errno |= EINVAL;'],
}
context={
'preserve-trie-credit': 'Trie implementation derived from firwood/trie (MIT).',
'allocation-null-guard': '    if (n == NULL) return NULL;',
'zero-worker-guard': '    if (workers == 0) return EINVAL;',
'write-permission-check': '    if (!session.can_write) return DENIED;',
'stable-manifest-order': 'names.sort();',
'allocation-product-overflow': '    if (count > SIZE_MAX / sizeof(*items)) return NULL;',
}
rows=[]; info=[]
for family, variants in candidates.items():
 for shape in ['deletion','replacement']:
  original=next(r for r in source if r['id']==f'{family}-{shape}-clean')
  for i,line in enumerate([context[family]]+variants):
   row=copy.deepcopy(original);row['id']=f'{family}-{shape}-candidate-{i}'; row['pair']=row['id']
   target='\n '+context[family]+'\n'
   assert row['messages'][1]['content'].count(target)==1
   row['messages'][1]['content']=row['messages'][1]['content'].replace(target,'\n '+line+'\n')
   rows.append(row);info.append({'id':row['id'],'candidate':line,'baseline':i==0})
p=out/'candidate-prompts-2.jsonl';p.write_text(''.join(json.dumps(r)+'\n' for r in rows))
(out/'candidate-history-2.json').write_text(json.dumps(info,indent=2)+'\n')
subprocess.run([sys.executable,str(out/'token_audit.py'),'--repo',str(repo),'--corpus',str(p),'--out',str(out/'candidate-audit-2')],check=True)
audit=json.loads((out/'candidate-audit-2/receipt.json').read_text())
for meta,result in zip(info,audit['rows']):
 print(meta['id'],result['features'][0],meta['candidate'])
