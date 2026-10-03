import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

const fixture = String.raw`
import hashlib, json, os, sys, tempfile
from pathlib import Path
sys.path[:0] = ['training/explanations', 'test']
import collect_generation as collector
from durable_archive_fixture import FakeTransport
from durable_archive import DurableArchive, ArchiveError

def require(value, message):
    if not value: raise AssertionError(message)

scenario = sys.argv[1]
with tempfile.TemporaryDirectory(prefix='jovovich-generation-test-') as temporary:
    root = Path(temporary)
    model, exe, corpus = root/'model.gguf', root/'native', root/'corpus.jsonl'
    model.write_bytes(b'fake model for archive and subprocess contract')
    rows = []
    for index in range(2):
        rows.append({'id': f'case-{index}', 'kind':'review', 'pair':'same', 'messages':[
            {'role':'system','content':'system identity'},
            {'role':'user','content':f'source context {index}'},
            {'role':'assistant','content':'GOLD_ANALYSIS_MUST_NEVER_REACH_MODEL'}]})
    corpus.write_text(''.join(json.dumps(row)+'\n' for row in rows))
    calls = root/'calls.jsonl'
    marker = root/'ack.txt'
    marker.write_text('0')
    native = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
root = Path(__file__).parent
tokenizer = '--token-ids' in sys.argv
args = dict(zip(sys.argv[1:-1:2],sys.argv[2:-1:2])) if tokenizer else dict(zip(sys.argv[1::2],sys.argv[2::2]))
assert args['--tokens']=='512' and args['--context']=='8192' and args['--temperature']=='0'
assert all(os.environ[key]==value for key,value in
           {'NT_NO_I8':'1','NT_SIMD_THREADS':'4','NT_QMV_THREADS':'4','NT_ATTN_THREADS':'4'}.items())
assert all(key not in os.environ for key in
           ('HF_TOKEN','UNLABELED_CREDENTIAL','NT_QMV_IMPL','NT_NO_AVX2','NODE_OPTIONS','LD_PRELOAD'))
prompt = sys.stdin.buffer.read().decode()
assert 'GOLD_ANALYSIS_MUST_NEVER_REACH_MODEL' not in prompt
assert prompt.endswith('<|im_start|>assistant\n')
mode=(root/'mode.txt').read_text()
if tokenizer:
    with (root/'tokenizer-calls.jsonl').open('a') as stream:
        stream.write(json.dumps({'prompt':prompt,'argv':sys.argv})+'\n')
    if mode=='tokenizer-fail': raise SystemExit(4)
    sys.stdout.write('151644,1,2\n')
    raise SystemExit(0)
calls=root/'calls.jsonl'
index=len(calls.read_text().splitlines()) if calls.exists() else 0
assert int((root/'ack.txt').read_text()) == index
assert (root/f'tokenizer-{index}.ack').exists()
with calls.open('a') as stream: stream.write(json.dumps({'prompt':prompt,'argv':sys.argv})+'\n')
response=' \n{"analysis":"règle","findings":[]}\n '
sys.stdout.write(response)
sys.stderr.write('native diagnostic\n')
if mode=='native-fail': raise SystemExit(3)
if mode=='model-mutation': (root/'model.gguf').write_bytes(b'changed')
trace={'schema_version':1,'prompt_token_ids':[151644,1,2],
       'generated_token_ids':[7,151645] if index==0 else [7]*512,
       'requested_limit':512,'emitted_tokens':1 if index==0 else 512,
       'stop_reason':'eos' if index==0 else 'token-limit'}
if mode=='bad-trace': trace['emitted_tokens']=511
if mode=='wrong-prompt-ids': trace['prompt_token_ids']=[151644,99,2]
Path(args['--trace-tokens']).write_text(json.dumps(trace)+'\n')
'''
    exe.write_text(native)
    exe.chmod(0o755)
    (root/'mode.txt').write_text(scenario)
    transport = FakeTransport()
    backend = DurableArchive(transport, 'test-generation')
    synced = []
    class Journal:
        def sync_unit(self, unit, files, *, sequence):
            if scenario=='bootstrap-fail' and unit=='inputs':
                raise ArchiveError('injected bootstrap failure')
            if scenario=='result-fail' and unit=='case-000-result':
                # Fail the actual fresh object readback, after the commit exists.
                transport.download_fault=lambda name,data: b'corrupted' if '/objects/' in name else data
            if scenario=='tokenizer-archive-fail' and unit=='case-000-tokenizer':
                transport.download_fault=lambda name,data: b'corrupted' if '/objects/' in name else data
            if scenario=='completion-fail' and unit=='completion':
                transport.download_fault=lambda name,data: b'corrupted' if '/objects/' in name else data
            if scenario=='prompt-mutation' and unit=='case-000-intent':
                (root/'out/cases/000/prompt.txt').write_text('altered')
            receipt=backend.sync_unit(unit,files,sequence=sequence)
            require(receipt['verified_remote_bytes'], 'missing readback')
            synced.append(unit)
            if unit.endswith('-result'):
                marker.write_text(str(int(marker.read_text())+1))
            if unit.endswith('-tokenizer'):
                (root/f'tokenizer-{int(unit.split("-")[1])}.ack').write_text('verified')
            return receipt
    failed = None
    os.environ['HF_TOKEN']='must-never-reach-native'
    os.environ['UNLABELED_CREDENTIAL']='also-must-not-reach-native'
    os.environ['NT_QMV_IMPL']='unexpected-kernel'
    os.environ['NT_NO_AVX2']='1'
    os.environ['NODE_OPTIONS']='--throw-deprecation'
    try:
        result=collector.collect(Journal(),corpus=corpus,model=model,executable=exe,
                                 output=root/'out',run_id='test-generation',
                                 expected_model_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
                                 expected_infer_sha256=hashlib.sha256(exe.read_bytes()).hexdigest())
    except (RuntimeError, ValueError, ArchiveError) as error:
        failed=error
    count=len(calls.read_text().splitlines()) if calls.exists() else 0
    token_calls=root/'tokenizer-calls.jsonl'
    token_count=len(token_calls.read_text().splitlines()) if token_calls.exists() else 0
    if scenario=='normal':
        require(failed is None, str(failed))
        records=[json.loads(line) for line in (root/'out/generations.jsonl').read_text().splitlines()]
        require(count==2 and [row['finish_reason'] for row in records]==['eos','length'], 'stop reason changed')
        require(token_count==2, 'each generation requires its own native tokenizer preflight')
        for index,row in enumerate(records):
            raw=(root/f'out/cases/{index:03d}/stdout.bin').read_bytes()
            require(row['raw_response'].encode()==raw, 'raw output was trimmed or normalized')
            require(row['raw_response_sha256']==hashlib.sha256(raw).hexdigest(), 'response binding mismatch')
            prompt=(root/f'out/cases/{index:03d}/prompt.txt').read_bytes()
            require(row['metadata']['prompt_sha256']==hashlib.sha256(prompt).hexdigest(), 'prompt binding mismatch')
            require('GOLD_ANALYSIS' not in prompt.decode(), 'gold leak')
        require(synced==['inputs','case-000-intent','case-000-tokenizer','case-000-result',
                         'case-001-intent','case-001-tokenizer','case-001-result','completion'], 'archive ordering changed')
        require(result['cases']==2 and result['remote_verification']['verified_remote_bytes'], 'run not durable')
        require(result['status']=='completed' and result['archive_status']=='verified', 'missing verified final receipt')
        candidate=json.loads((root/'out/completion.json').read_text())
        require(candidate['status']=='native_completed' and candidate['archive_status']=='requires_verified_receipt', 'candidate falsely claims remote verification')
        restored=root/'recovered'
        backend.recover(restored)
        require((restored/'generations.jsonl').read_bytes()==(root/'out/generations.jsonl').read_bytes(), 'remote-only recovery changed output')
    else:
        require(failed is not None, 'fault did not stop collection')
        require(count==(2 if scenario=='completion-fail' else 0 if scenario in ('bootstrap-fail','prompt-mutation','tokenizer-fail','tokenizer-archive-fail') else 1), 'next model call escaped archive/error barrier')
        require(token_count==(2 if scenario=='completion-fail' else 0 if scenario in ('bootstrap-fail','prompt-mutation') else 1), 'tokenizer calls escaped failure barrier')
        if scenario=='completion-fail':
            candidate=json.loads((root/'out/completion.json').read_text())
            require(candidate['status']=='native_completed' and candidate['archive_status']=='requires_verified_receipt', 'failed remote completion claims verified success')
        else:
            require(not (root/'out/completion.json').exists(), 'failed run marked complete')
        if scenario not in ('bootstrap-fail','result-fail','tokenizer-archive-fail','completion-fail'):
            record=json.loads((root/'out/cases/000/record.json').read_text())
            require(record['finish_reason']=='error' and record['error'], 'missing closed error record')
            require(synced[-1]=='case-000-result', 'failure evidence not archived')
print(json.dumps({'scenario':scenario,'passed':True}))
`;

for (const scenario of ['normal', 'bootstrap-fail', 'result-fail', 'native-fail',
  'bad-trace', 'model-mutation', 'prompt-mutation', 'tokenizer-fail',
  'tokenizer-archive-fail', 'wrong-prompt-ids', 'completion-fail']) {
  test(`explanation generation: ${scenario}`, () => {
    const result = spawnSync('python3', ['-c', fixture, scenario], {
      encoding: 'utf8', timeout: 30_000,
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
    });
    assert.equal(result.status, 0, result.stderr || result.error?.message);
    assert.deepEqual(JSON.parse(result.stdout), { scenario, passed: true });
  });
}

test('explanation generation: heldout prompts use production context and empty assistant header', () => {
  const source = String.raw`
import json,sys
from pathlib import Path
sys.path.insert(0,'training/explanations')
import collect_generation as collector
from build_corpora import SUFFIX
raw=Path('training/review_holdout_v5.jsonl').read_bytes()
cases=collector.review_cases(raw,split='holdout')
assert len(cases)==24
for case in cases:
    assert case['prompt'].endswith((SUFFIX+'<|im_end|>\n<|im_start|>assistant\n').encode())
    assert case['prompt'].count(b'<|im_start|>assistant')==1
rows=[json.loads(line) for line in raw.splitlines()]
for row in rows:
    row['gold']={'findings':'GOLD_LEAK_SENTINEL'}
    row['expected_reason_concept']='GOLD_LEAK_SENTINEL'
    row['expected_concern']='GOLD_LEAK_SENTINEL'
    row['expected_line_ids']='GOLD_LEAK_SENTINEL'
    row['audit_metadata']={'leak':'GOLD_LEAK_SENTINEL'}
changed=''.join(json.dumps(row)+'\n' for row in rows).encode()
others=collector.review_cases(changed,split='holdout')
assert [case['prompt'] for case in others]==[case['prompt'] for case in cases]
assert all(b'GOLD_LEAK_SENTINEL' not in case['prompt'] for case in others)
print('ok')
`;
  const result = spawnSync('python3', ['-c', source], { encoding: 'utf8', timeout: 30_000 });
  assert.equal(result.status, 0, result.stderr || result.error?.message);
  assert.equal(result.stdout.trim(), 'ok');
});

test('explanation generation: native trace rejects truncation ambiguities', () => {
  const source = String.raw`
import copy,sys
sys.path.insert(0,'training/explanations')
from collect_generation import validate_trace
trace={'schema_version':1,'prompt_token_ids':[1], 'generated_token_ids':[7,2],
       'requested_limit':512,'emitted_tokens':1,'stop_reason':'eos'}
assert validate_trace(trace)=='eos'
for key,value in [('emitted_tokens',2),('stop_reason','token-limit'),('requested_limit',511),
                  ('generated_token_ids',[]),('prompt_token_ids',[]),('schema_version',True)]:
    changed=copy.deepcopy(trace);changed[key]=value
    try:validate_trace(changed)
    except ValueError:pass
    else:raise AssertionError(key)
print('ok')
`;
  const result = spawnSync('python3', ['-c', source], { encoding: 'utf8', timeout: 30_000 });
  assert.equal(result.status, 0, result.stderr || result.error?.message);
  assert.equal(result.stdout.trim(), 'ok');
});
