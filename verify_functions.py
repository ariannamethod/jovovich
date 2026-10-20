import ast,copy,json,random,hashlib,subprocess,sys,concurrent.futures,pathlib
ROOT=pathlib.Path(__file__).resolve().parent
rows=json.loads((ROOT/'data/mbpp-source.json').read_text())
# Accept only the computation-only subset; execution also has process resource limits.
allowed={'math','re','collections','heapq','itertools','cmath','operator','array','bisect','copy'}
def safe(code):
 try:t=ast.parse(code)
 except SyntaxError:return False
 for n in ast.walk(t):
  if isinstance(n,ast.Import) and any(a.name not in allowed for a in n.names):return False
  if isinstance(n,ast.ImportFrom) and n.module not in allowed:return False
  if isinstance(n,ast.Name) and (n.id.startswith('__') or n.id in {'open','exec','eval','compile','input','globals','locals','getattr','setattr','delattr','breakpoint','exit','quit'}):return False
  if isinstance(n,ast.Attribute) and n.attr.startswith('__'):return False
 return True
runner='''import sys,json,resource,contextlib,io
resource.setrlimit(resource.RLIMIT_CPU,(1,1))
resource.setrlimit(resource.RLIMIT_AS,(268435456,268435456))
r=json.load(sys.stdin); ns={}
try:
 with contextlib.redirect_stdout(io.StringIO()): exec(r['code'],ns)
except Exception as e:
 print(json.dumps({'error':type(e).__name__}));sys.exit()
for s in r['tests']:
 try:
  with contextlib.redirect_stdout(io.StringIO()): exec(s,ns)
 except Exception as e:
  print(json.dumps({'failed':s,'error':type(e).__name__}));sys.exit()
print('{}')
'''
def check(code,tests):
 try:
  p=subprocess.run([sys.executable,'-I','-c',runner],input=json.dumps({'code':code,'tests':tests}),text=True,capture_output=True,timeout=2)
  return json.loads(p.stdout) if p.returncode==0 else {'error':'process failure'}
 except (subprocess.TimeoutExpired,json.JSONDecodeError):return {'error':'timeout'}
ops={ast.Add:ast.Sub,ast.Sub:ast.Add,ast.Mult:ast.Add,ast.FloorDiv:ast.Mult,ast.Mod:ast.FloorDiv,ast.BitAnd:ast.BitOr,ast.BitOr:ast.BitAnd,ast.Lt:ast.LtE,ast.LtE:ast.Lt,ast.Gt:ast.GtE,ast.GtE:ast.Gt,ast.Eq:ast.NotEq,ast.NotEq:ast.Eq,ast.And:ast.Or,ast.Or:ast.And}
def variants(code,seed):
 tree=ast.parse(code); nodes=list(ast.walk(tree)); options=[]
 for i,n in enumerate(nodes):
  if isinstance(n,(ast.BinOp,ast.BoolOp)) and type(n.op) in ops:options.append((i,'op',ops[type(n.op)]()))
  if isinstance(n,ast.Compare):
   for j,o in enumerate(n.ops):
    if type(o) in ops:options.append((i,j,ops[type(o)]()))
  if isinstance(n,ast.Constant) and type(n.value)==int and abs(n.value)<100:options.append((i,'value',n.value+1))
  if isinstance(n,ast.Constant) and type(n.value)==bool:options.append((i,'value',not n.value))
 random.Random(seed).shuffle(options)
 for idx,attr,val in options[:20]:
  t=copy.deepcopy(tree);n=list(ast.walk(t))[idx]; before=ast.unparse(n)
  if isinstance(attr,int):n.ops[attr]=val
  else:setattr(n,attr,val)
  yield ast.unparse(t),before,ast.unparse(n)
def process(r):
 imports='\n'.join(r['test_imports']); code=imports+'\n'+r['code'];tests=r['test_list']
 if not safe(code+'\n'+'\n'.join(tests)) or check(code,tests):return None
 for changed,before,after in variants(r['code'],r['task_id']):
  failure=check(imports+'\n'+changed,tests)
  if failure.get('error')=='AssertionError':
   return {'task_id':r['task_id'],'contract':r['prompt'],'original':r['code'],'changed':changed,'tests':tests,'imports':imports,'failure':failure['failed'],'expression_before':before,'expression_after':after}
 return None
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool: verified=[r for r in pool.map(process,rows) if r]
out=ROOT/'data/verified_functions.jsonl';out.write_text(''.join(json.dumps(r)+'\n' for r in verified))
print('verified independent functions:',len(verified),flush=True)
