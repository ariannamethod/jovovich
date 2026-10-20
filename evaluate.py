"""Score complete fixture runs and execute proposed repairs against retained MBPP tests.

This evaluator is for the bundled fixtures; review.py never executes repository code.
"""
import ast,copy,sys,pathlib,json,re,collections
root=pathlib.Path(__file__).resolve().parent
from verify_functions import safe,check
src={r['task_id']:r for r in map(json.loads,(root/'data/verified_functions.jsonl').read_text().splitlines())}
rows=list(map(json.loads,pathlib.Path(sys.argv[1]).read_text().splitlines()))
case_files=sys.argv[2:] or [str(root/'data/test.jsonl'),str(root/'data/acceptance.jsonl')]
cases={}
for path in case_files:
 for row in map(json.loads,pathlib.Path(path).read_text().splitlines()):
  if row['id'] in cases:raise ValueError('Duplicate expected case: '+row['id'])
  cases[row['id']]=row
ids=[r['id'] for r in rows]
if len(ids)!=len(set(ids)) or set(ids)!=set(cases):raise ValueError('Missing, duplicate or unexpected generated cases')
if any(r['expected']!=cases[r['id']]['expected'] for r in rows):raise ValueError('Generated case metadata does not match the reference')
counts=collections.Counter();details=[];identity=[];suites=collections.defaultdict(collections.Counter)
for r in rows:
 if r['expected']=='IDENTITY':
  identity.append({'id':r['id'],'response':r['review']});continue
 text=r['review'];m=re.search(r'Verdict:\s*(CLEAN|CONCERN)\s*$',text);pred=m[1] if m else 'INVALID'
 suite=suites['repository_acceptance' if r['id'].startswith('accept-') else 'legacy_control'];suite['total']+=1;suite['correct_verdict']+=pred==r['expected']
 counts['total']+=1;counts['correct_verdict']+=pred==r['expected'];counts[r['expected']+'->'+pred]+=1
 if not re.fullmatch(r'mbpp-\d+-changed',r['id']):continue
 task=src[int(r['id'].split('-')[1])];parts=re.findall(r'`([^`]+)`',text);counterexample=False;repair=False
 structured=re.search(r'The expression `([^`]+)` breaks the required behavior: `(assert[^`]+)` fails\. Replacing it with `([^`]+)`',text)
 if structured:parts=list(structured.groups())
 if len(parts)>=3:
  expr,assertion,fix=parts[:3]
  try:
   dump=lambda t:ast.dump(t,include_attributes=False)
   counterexample=any(dump(ast.parse(assertion))==dump(ast.parse(t)) for t in task['tests']) and check(task['imports']+'\n'+task['changed'],[assertion]).get('error')=='AssertionError'
   old=ast.parse(expr,mode='eval').body;new=ast.parse(fix,mode='eval').body;tree=ast.parse(task['changed'])
   for idx,node in enumerate(ast.walk(tree)):
    if dump(node)!=dump(old):continue
    t=copy.deepcopy(tree);target=list(ast.walk(t))[idx]
    class Replace(ast.NodeTransformer):
     def visit(self,n):return copy.deepcopy(new) if n is target else super().visit(n)
    code=task['imports']+'\n'+ast.unparse(ast.fix_missing_locations(Replace().visit(t)))
    if safe(code) and check(code,task['tests'])=={}:repair=True;break
  except (SyntaxError,ValueError,TypeError):pass
 counts['mutation_reviews']+=1;counts['verified_counterexamples']+=counterexample;counts['passing_repairs']+=repair
 details.append({'id':r['id'],'counterexample':counterexample,'repair':repair})
print(json.dumps({'counts':dict(counts),'suites':dict(suites),'repair_checks':details,'identity_responses':identity},indent=2))
