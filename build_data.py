"""Construct disjoint task-level splits; no path variants or duplicated samples."""
import ast
import builtins
import hashlib
import json
from pathlib import Path
from review import messages, SYSTEM

ROOT = Path(__file__).parent
DATA = ROOT / 'data'

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
            add(group, kind, context, answer, verdict)
    for i, r in enumerate(json.loads((DATA / 'policies.json').read_text())):
        group = 'policy-' + str(i)
        cases = [('bad', r['bad'], r['rule'], r['why'], 'CONCERN'),
                 ('good', r['good'], r['rule'], r['ok'], 'CLEAN')]
        if 'permissive' in r:
            cases.append(('permitted', r['bad'], r['permissive'], r['permissive_reason'], 'CLEAN'))
        for kind, code, rule, answer, verdict in cases:
            context = f"File: {r['path']}\nRepository rule: {rule}\nProposed code or text:\n```\n{code}\n```"
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
