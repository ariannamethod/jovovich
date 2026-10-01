import copy,json,subprocess,sys
from pathlib import Path
base=Path('/workspace/scratch/ec5ba60588d8'); ref=base/'matched-reference'
rows=[json.loads(s) for s in (base/'holdout-v5-tokenize.jsonl').read_text().splitlines() if 'erase-target' in s]
candidates=[]
for name in ['spare','backup','buffer','temp','other','decoy']:
 for original in rows:
  row=copy.deepcopy(original)
  row['id']+='-'+name;row['pair']+='-'+name
  row['messages'][1]['content']=row['messages'][1]['content'].replace('scratch',name)
  candidates.append(row)
p=ref/'holdout-erase-candidates.jsonl';p.write_text(''.join(json.dumps(r)+'\n' for r in candidates))
subprocess.run([sys.executable,str(ref/'token_audit.py'),'--repo',str(base/'jovovich'),'--corpus',str(p),'--out',str(ref/'holdout-erase-candidate-audit')],check=True)
audit=json.loads((ref/'holdout-erase-candidate-audit/receipt.json').read_text())
for pair in audit['pairs']:
 print(pair['pair'],[audit['rows'][i]['features'][0] for i in pair['rows']],pair['all_seven_equal'])
