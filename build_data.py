"""Construct disjoint task-level splits; no path variants or duplicated samples."""
import ast
import builtins
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from review import messages, SYSTEM
from fixture_quality import QUARANTINED_GROUPS

ROOT = Path(__file__).parent
DATA = ROOT / 'data'

def observed_examples(code, tests):
    """Compute supervision from the retained, computation-only MBPP source."""
    from verify_functions import safe
    if not safe(code + '\n' + '\n'.join(tests)):
        raise ValueError('Unapproved executable training source')
    runner = '''import ast,contextlib,io,json,resource,sys
resource.setrlimit(resource.RLIMIT_CPU,(1,1))
resource.setrlimit(resource.RLIMIT_AS,(268435456,268435456))
r=json.load(sys.stdin);ns={};out=[]
with contextlib.redirect_stdout(io.StringIO()):
 exec(r['code'],ns)
 for test in r['tests']:
  node=ast.parse(test).body[0].test
  if not isinstance(node,ast.Compare) or len(node.ops)!=1 or not isinstance(node.ops[0],ast.Eq):continue
  actual=eval(compile(ast.Expression(node.left),'example','eval'),ns)
  expected=eval(compile(ast.Expression(node.comparators[0]),'example','eval'),ns)
  a,b=repr(actual),repr(expected)
  if max(len(a),len(b))<=160:
   out.append({'call':ast.unparse(node.left),'actual':a,'expected':b,'passed':actual==expected,'test':test})
print(json.dumps(out))
'''
    p = subprocess.run([sys.executable, '-I', '-c', runner],
        input=json.dumps({'code': code, 'tests': tests}), capture_output=True, text=True, timeout=3)
    if p.returncode:
        raise ValueError('Could not compute training evidence: ' + p.stderr[-300:])
    return json.loads(p.stdout)

def split(group):
    bucket = int(hashlib.sha256(group.encode()).hexdigest(), 16) % 10
    return 'test' if bucket == 0 else 'validation' if bucket == 1 else 'train'

def function_fingerprint(code):
    class Normalize(ast.NodeTransformer):
        def __init__(self):
            self.names = {}
        def name(self, name):
            if name in vars(builtins): return name
            return self.names.setdefault(name, 'symbol_' + str(len(self.names)))
        def visit_FunctionDef(self, node):
            node.name = self.name(node.name)
            return self.generic_visit(node)
        def visit_arg(self, node):
            node.arg = self.name(node.arg)
            return node
        def visit_Name(self, node):
            node.id = self.name(node.id)
            return node
    return ast.dump(Normalize().visit(ast.parse(code)), include_attributes=False)

def main():
    groups = {name: [] for name in ('train', 'validation', 'test')}
    def add(group, suffix, context, answer, verdict):
        groups[split(group)].append({
            'id': group + '-' + suffix, 'group': group, 'context': context,
            'expected': verdict,
            'messages': messages(context) + [{'role': 'assistant', 'content': answer + '\nVerdict: ' + verdict}]})
    seen_functions = set()
    for line in (DATA / 'verified_functions.jsonl').read_text().splitlines():
        r = json.loads(line)
        fingerprint = function_fingerprint(r['original'])
        if fingerprint in seen_functions: continue
        seen_functions.add(fingerprint)
        if 'mbpp-' + str(r['task_id']) in QUARANTINED_GROUPS:
            continue
        group = 'mbpp-' + str(r['task_id'])
        path = 'functions.py'
        for kind, code, verdict in [('original', r['original'], 'CLEAN'), ('changed', r['changed'], 'CONCERN')]:
            code = ast.unparse(ast.parse(code))
            context = ('File: ' + path + '\nChange: add this function.\nRequirement: ' + r['contract'] +
                       '\nRequired examples:\n```python\n' + '\n'.join(r['tests']) + '\n```\nProposed code:\n```python\n' +
                       r['imports'] + '\n' + code + '\n```')
            if verdict == 'CONCERN':
                answer = (f"{path}: The expression `{r['expression_after']}` breaks the required behavior: "
                          f"`{r['failure']}` fails. Replacing it with `{r['expression_before']}` restores the supplied examples.")
            else:
                answer = f'{path}: This implementation satisfies the supplied examples for the stated function. No defect is demonstrated by these cases.'
            if split(group) == 'train':
                examples = observed_examples(r['imports'] + '\n' + code,
                    r['tests'] if verdict == 'CLEAN' else [r['failure']])
                if verdict == 'CLEAN' and examples:
                    ex = examples[0]
                    assert all(e['passed'] for e in examples)
                    answer = (f"{path}: For `{ex['call']}`, the implementation returns `{ex['actual']}`, "
                              f"matching the required `{ex['expected']}`. All supplied examples pass. "
                              'No correctness objection under the stated contract.')
                elif verdict == 'CONCERN':
                    failed = [e for e in examples if not e['passed'] and e['test'] == r['failure']]
                    if failed:
                        ex = failed[0]
                        answer += (f" On that failing example, the current result is `{ex['actual']}`; "
                                   f"the required result is `{ex['expected']}`.")
            add(group, kind, context, answer, verdict)
    for i, r in enumerate(json.loads((DATA / 'policies.json').read_text())):
        group = 'policy-' + str(i)
        if group in QUARANTINED_GROUPS:
            continue
        cases = [('bad', r['bad'], r['rule'], r['why'], 'CONCERN'),
                 ('good', r['good'], r['rule'], r['ok'], 'CLEAN')]
        if 'permissive' in r:
            cases.append(('permitted', r['bad'], r['permissive'], r['permissive_reason'], 'CLEAN'))
        for kind, code, rule, answer, verdict in cases:
            context = f"File: {r['path']}\nRepository rule: {rule}\nProposed code or text:\n```\n{code}\n```"
            if split(group) == 'train':
                answer = f'The repository requires: {rule} {answer}'
            add(group, kind, context, r['path'] + ': ' + answer, verdict)
    for i, (question, answer) in enumerate(json.loads((DATA / 'identity.json').read_text())):
        groups['train'].append({'id': f'identity-{i}', 'group': 'identity', 'messages': [
            {'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': question},
            {'role': 'assistant', 'content': answer}]})
    print('distinct function bodies:', len(seen_functions))
    seen = set()
    for name, rows in groups.items():
        for row in rows:
            prompt = json.dumps(row['messages'][:-1], sort_keys=True)
            if prompt in seen: raise ValueError('Duplicate prompt across dataset: ' + row['id'])
            seen.add(prompt)
        (DATA / (name + '.jsonl')).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
        print(name, len(rows), 'rows;', len({r['group'] for r in rows}), 'source tasks')
    sets = [{r['group'] for r in groups[n]} for n in groups]
    assert all(not sets[i] & sets[j] for i in range(3) for j in range(i))

if __name__ == '__main__': main()
