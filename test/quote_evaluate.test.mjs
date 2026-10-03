import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const python = (code, ...args) => spawnSync('python3', ['-c', code, ...args], { cwd: ROOT, encoding: 'utf8', timeout: 60000 });

// Frozen by the coordinator: quote = before + one variable, token-exact.
const SUBSTITUTIONS = [
  ['before-endpoint-binding', 'quote-endpoint-binding'],
  ['before-merge', 'quote-merge'],
  ['before-byte-export-audit', 'quote-byte-export-audit'],
  ['before-native-export-parity', 'quote-native-export-parity'],
  ['@BEFORE_RUN@', '@QUOTE_RUN@'],
  ['/exports/before/', '/exports/quote/'],
  ['training/results/2026-10-03-explanation-order-run/native/before.bin', '@QUOTE_NATIVE@/quote.bin'],
  ['before_update100', 'quote_update100'],
  ['@BEFORE_UPDATE100_SHA256@', '@QUOTE_UPDATE100_SHA256@'],
];
const FIELD_SUBSTITUTIONS = [{ path: ['export', 'arm'], from: 'before', to: 'quote' }];

test('committed quote contract equals its derivation', () => {
  const r = spawnSync('python3', ['training/quote/evaluate_quote.py', 'derive', '--check'], { cwd: ROOT, encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
});

test('quote contract differs from the before branch only by the frozen substitution list', () => {
  const raw = readFileSync(join(ROOT, 'training/explanations/evaluation_plan.json'));
  const plan = JSON.parse(raw);
  const contract = JSON.parse(readFileSync(join(ROOT, 'training/quote/evaluation_contract.json'), 'utf8'));
  assert.deepEqual(Object.keys(contract), ['schema', 'derived_from', 'substitutions', 'field_substitutions', 'resolution',
    'native_environment', 'generation', 'parity', 'export', 'collector_jobs']);
  assert.equal(contract.schema, 'jovovich.quote.evaluation.v1');
  assert.deepEqual(contract.substitutions, SUBSTITUTIONS);
  assert.deepEqual(contract.field_substitutions, FIELD_SUBSTITUTIONS);
  assert.equal(contract.export.arm, 'quote');
  assert.deepEqual(contract.derived_from, { path: 'training/explanations/evaluation_plan.json',
    sha256: createHash('sha256').update(raw).digest('hex'), export_arm: 'before',
    collector_jobs: ['before_update100-train', 'before_update100-holdout'] });
  const invert = value => typeof value === 'string'
    ? [...SUBSTITUTIONS].reverse().reduce((text, [old, quote]) => text.split(quote).join(old), value)
    : Array.isArray(value) ? value.map(invert)
      : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).map(([k, v]) => [k, invert(v)])) : value;
  const restored = invert({ export: contract.export, collector_jobs: contract.collector_jobs });
  for (const { path: [parent, key], from, to } of [...FIELD_SUBSTITUTIONS].reverse()) {
    assert.equal(restored[parent][key], to);
    restored[parent][key] = from;
  }
  assert.deepEqual(restored.export, plan.exports.find(item => item.arm === 'before'));
  assert.deepEqual(restored.collector_jobs, plan.collector_jobs.filter(job => job.model === 'before_update100'));
  const derived = JSON.stringify([contract.export, contract.collector_jobs]);
  for (const [old] of SUBSTITUTIONS) assert.ok(!derived.includes(old), 'before token survived: ' + old);
  for (const key of ['native_environment', 'generation', 'parity']) assert.deepEqual(contract[key], plan[key]);
  assert.deepEqual(contract.resolution, { INFER_SHA256: plan.resolution.INFER_SHA256,
    SHARED_BASE_UPDATE0_SHA256: plan.resolution.SHARED_BASE_UPDATE0_SHA256 });
});

test('a contract that drifts from its derivation is rejected', () => {
  const r = python(String.raw`
import json,sys,tempfile
from pathlib import Path
sys.path.insert(0,'training/quote')
import evaluate_quote as quote
c=json.loads(Path(quote.CONTRACT).read_text());s=c['collector_jobs'][1]['score_argv'];s[s.index('--order')+1]='after'
with tempfile.TemporaryDirectory() as t:
    p=Path(t)/'contract.json';p.write_bytes(quote.render(c))
    try:quote.check_contract(p,quote.TEMPLATE)
    except RuntimeError as e:assert str(e)=='quote evaluation contract differs from its derivation',str(e)
    else:raise AssertionError('drifted contract accepted')
`);
  assert.equal(r.status, 0, r.stderr);
});

const BEFORE = String.raw`
import hashlib,json
def write_before(directory,split,rows,model='before_update100'):
    cases=[];records=[]
    for i in range(rows):
        prompt=f'common {split} prompt {i}'.encode();rel=f'cases/{i:03d}/prompt.txt'
        p=directory/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(prompt)
        h=hashlib.sha256(prompt).hexdigest();case_id=f'{split}-{i}';response='{"analysis":"x","findings":[]}'
        cases.append(dict(case_id=case_id,prompt_path=rel,prompt_sha256=h))
        records.append(dict(case_id=case_id,finish_reason='eos',raw_response=response,
            raw_response_sha256=hashlib.sha256(response.encode()).hexdigest(),
            metadata=dict(prompt_sha256=h,prompt_token_ids=[1,i,2],model_sha256='d'*64)))
    (directory/'manifest.json').write_text(json.dumps(dict(split=split,run_id=f'fixture-before-{model}-{split}',
        model=dict(sha256='d'*64),cases=cases)))
    (directory/'generations.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
    return directory
`;

// A synthetic repository with a completed quote run; no model, no network.
const PREFLIGHT = BEFORE + String.raw`
import sys,tempfile
from pathlib import Path
sys.path[:0]=['training/quote','training/explanations']
import evaluate_quote as quote
import execute_evaluation as runner
variant=sys.argv[1];real=Path.cwd()
with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary).resolve();runner.ROOT=root
    def put(name,data):
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return p
    base=put('models/base-qwen.gguf',b'fixture base')
    template=json.loads((real/quote.TEMPLATE).read_text())
    template['resolution']['SHARED_BASE_UPDATE0_SHA256']=runner.digest(base)
    put(quote.TEMPLATE,json.dumps(template).encode())
    put(quote.CONTRACT,quote.render(quote.derive(root/quote.TEMPLATE)))
    scientific=json.loads((real/quote.SCIENTIFIC).read_text());put(quote.SCIENTIFIC,json.dumps(scientific).encode())
    names=[p for p in template['required_pretraining_launch_bindings'] if '/native/' not in p]+['models/base-qwen.gguf',
        quote.SCIENTIFIC,quote.CONTRACT,'training/sft_review_v7_quote.jsonl','training/explanations/reasons.json',
        'training/quote/manipulation.mjs','training/quote/evaluate_quote.py','training/explanations/execute_evaluation.py',
        'models/quote-native/quote.bin','models/quote-native/quote.pairs.bin']
    for name in names:
        if not (root/name).exists():put(name,('fixture '+name).encode())
    if variant=='unfrozen_source':names.remove('training/quote/manipulation.mjs')
    if variant=='unfrozen_contract':names.remove(quote.CONTRACT)
    bindings=[runner.binding(root/n) for n in dict.fromkeys(names)]
    directory=root/'models/quote-run';(directory/'_units').mkdir(parents=True)
    initial={'gate':'a'*64,'up':'b'*64,'down':'c'*64}
    launch=dict(arm='before' if variant=='arm' else 'quote',run_id='fixture-quote',
        argv=['build/jovovich-train-mlp','models/base-qwen.gguf','models/quote-native/quote.bin','@RUN@/adapter','100',
              '0.001' if variant=='lr' else '0.0001','40','25','joint','models/quote-native/quote.pairs.bin'],
        bindings=bindings,environment=scientific['training']['native_environment'],
        remote=dict(repo='other/archive' if variant=='remote' else 'ataeff/jovovich',prefix='experiments/explanation-order',private=True),
        evaluation_plan=quote.CONTRACT,expected_initial_lora_sha256=dict(initial,gate='f'*64) if variant=='initialization' else initial)
    (directory/'plan.json').write_text(json.dumps(launch))
    final=[];saved=[]
    for part in ('gate','up','down'):
        for ext in ('f32','lora'):
            for epoch,entries in (('',final),('.epoch100',saved)):
                name=f'adapter{epoch}.{part}.{ext}';p=directory/name;p.write_bytes((part+ext).encode())
                entries.append(dict(name=name,size=p.stat().st_size,sha256=runner.digest(p)))
    completion=dict(status='native_completed',archive_status='requires_verified_receipt',acknowledged_updates=100,return_code=0,
        plan_sha256=runner.digest(directory/'plan.json'),bindings=bindings,initial_lora_sha256=initial)
    for name,value in (('completion.json',completion),('metrics.jsonl',{})):
        p=directory/name;p.write_text(json.dumps(value));final.append(dict(name=name,size=p.stat().st_size,sha256=runner.digest(p)))
    receipt=dict(run_id='fixture-quote',verified_remote_bytes=True,unit_id='completion',files=final,sequence=103,revision='a'*40,
                 prefix='experiments/explanation-order/fixture-quote',manifest_sha256='b'*64)
    (directory/'_units/completion.ack.json').write_text(json.dumps(dict(completion,status='completed',archive_status='verified',remote_verification=receipt)))
    (directory/'_units/update-100.ack.json').write_text(json.dumps(dict(receipt,unit_id='update-100',files=saved,sequence=102)))
    collectors=[write_before(root/'models/before-evaluation'/split,split,rows-(variant=='before_rows' and split=='train'),
                             'shared_base_update0' if variant=='before_model' and split=='holdout' else 'before_update100')
                for split,rows in quote.SPLITS]
    if variant=='contract_drift':
        c=json.loads((root/quote.CONTRACT).read_text());c['parity']['rows'][4]['index']=50;put(quote.CONTRACT,quote.render(c))
    if variant=='source_drift':put('training/prepare.py',b'changed after the quote launch')
    if variant=='receipt_bytes':(directory/'adapter.gate.f32').write_bytes(b'changed')
    output=root/'models/quote-evaluation'
    if variant=='ok':
        prepared=quote.prepare(root/quote.CONTRACT,directory,collectors,output,'fixture-evaluation')
        p=prepared['parameters']
        assert p['QUOTE_RUN']==str(directory) and p['QUOTE_NATIVE']=='models/quote-native' and p['EVALUATION_RUN']==str(output)
        assert p['SHARED_BASE_UPDATE0_SHA256']==runner.digest(base) and prepared['training']['initial_lora_sha256']==initial
        phases=prepared['export_phases']
        assert [u['id'] for u in phases]==['quote-endpoint-binding','quote-merge','quote-byte-export-audit','quote-native-export-parity']
        assert phases[0]['argv'][3]==str(directory) and phases[1]['argv'][2:]==[str(directory)+'/adapter.epoch100',str(output/'exports/quote/jovovich.gguf')]
        assert phases[3]['argv'][3]=='models/quote-native/quote.bin' and phases[3]['stdout']=='exports/quote/parity.jsonl'
        paths={b['path'] for b in prepared['bindings']}
        assert {quote.CONTRACT,'models/quote-native/quote.bin','models/quote-run/adapter.epoch100.down.lora',
                'models/before-evaluation/train/cases/051/prompt.txt','models/before-evaluation/holdout/generations.jsonl'}<=paths
        assert prepared['before_collectors']=={'train':str(collectors[0]),'holdout':str(collectors[1])}
    sys.argv=['evaluate_quote.py','preflight','--quote-run',str(directory),'--contract',str(root/quote.CONTRACT),
              '--before-collectors',*map(str,collectors),'--output',str(output),'--run-id','fixture-evaluation']
    quote.main()
`;

test('preflight passes on a synthetic quote run', () => {
  const r = python(PREFLIGHT, 'ok');
  assert.equal(r.status, 0, r.stderr);
  assert.equal(JSON.parse(r.stdout.trim().split('\n').at(-1)).status, 'preflight_passed');
});

const rejected = [
  ['arm', 'supplied training directory is not the quote arm'],
  ['lr', 'training arguments or environment differ from the scientific contract'],
  ['remote', 'training endpoint or archive differs from frozen contract'],
  ['receipt_bytes', 'local training evidence differs from its remote receipt'],
  ['unfrozen_contract', 'quote evaluation contract was not frozen before training'],
  ['contract_drift', 'quote evaluation contract differs from its derivation'],
  ['source_drift', 'binding mismatch: '],
  ['initialization', 'quote initialization differs from the before arm'],
  ['unfrozen_source', 'quote evaluation source was not frozen in the training launch'],
  ['before_model', 'before collector is not the archived before_update100 run for its split'],
  ['before_rows', 'before collector coverage differs from its split'],
];

test('every preflight rejection has its own message', () => {
  assert.equal(new Set(rejected.map(([, message]) => message)).size, rejected.length);
});

for (const [variant, message] of rejected) {
  test(`preflight rejects ${variant}`, () => {
    const r = python(PREFLIGHT, variant);
    assert.equal(r.status, 1, r.stderr);
    assert.ok(r.stderr.startsWith('evaluate_quote: ' + message), r.stderr);
  });
}

// One-arm orchestration with a fake archive transport and stub native commands.
const RUN = BEFORE + String.raw`
import os,subprocess,sys,tempfile
from pathlib import Path
sys.path[:0]=['training/quote','training/explanations','test']
import evaluate_quote as quote
from durable_archive import DurableArchive, ArchiveError
from durable_archive_fixture import FakeTransport
contract=json.loads(Path(quote.CONTRACT).read_text())
scenario=sys.argv[1]
with tempfile.TemporaryDirectory(prefix='quote-evaluation-fixture-',dir='models') as temporary:
    temporary=Path(temporary).resolve();output=temporary/'evaluation';run=temporary/'quote-run'
    source=temporary/'bound.txt';source.write_bytes(b'frozen fixture input')
    before={split:str(write_before(temporary/'before'/split,split,rows)) for split,rows in quote.SPLITS}
    parameters={'QUOTE_RUN':str(run),'QUOTE_NATIVE':'models/quote-native','EVALUATION_RUN':str(output),
                'EVALUATION_RUN_ID':'fixture-evaluation','INFER_SHA256':'a'*64,'SHARED_BASE_UPDATE0_SHA256':'b'*64}
    phases=[quote.export_unit(step,parameters,output) for step in contract['export']['steps']]
    prepared=dict(schema_version=1,arm='quote',run_id='fixture-evaluation',parameters=parameters,training={'directory':str(run)},
                  before_collectors=before,contract=contract,bindings=[quote.binding(source)],training_receipts=[],export_phases=phases)
    class DirectoryTransport(FakeTransport):
        def inventory(self,revision,prefix):
            return {name:value for name,value in super().inventory(revision,prefix).items() if name.startswith(prefix+'/')}
    transport=DirectoryTransport();archive=DurableArchive(transport,'fixture-evaluation','experiments/explanation-order')
    corrupt=lambda name,data:b'corrupt' if '/objects/' in name else data
    if scenario=='bootstrap-fail':transport.download_fault=corrupt
    native_calls=[];collector_calls=[]
    def fake_command(argv,stdout,stderr,environment):
        assert environment['NT_NO_I8']=='1' and environment['NT_QMV_THREADS']=='4'
        assert all(k not in environment for k in ('HF_TOKEN','UNLABELED_CREDENTIAL'))
        stdout.parent.mkdir(parents=True,exist_ok=True);stderr.parent.mkdir(parents=True,exist_ok=True)
        stdout.write_bytes(b'');stderr.write_bytes(b'');native_calls.append(argv)
        if argv[0]=='build/jovovich-merge-mlp':
            assert argv[2:]==[str(run)+'/adapter.epoch100',str(output/'exports/quote/jovovich.gguf')]
            Path(argv[3]).write_bytes(b'fixture quote export')
            if scenario=='merge-archive-fail':transport.download_fault=corrupt
        elif argv[0]=='build/jovovich-probe-mlp':
            assert argv[3]=='models/quote-native/quote.bin' and argv[-5:]==['0','1','2','3','51']
            stdout.write_text(''.join(json.dumps(dict(row=i,**{'pass':True},argmax_agree=7,completion_tokens=7,
                   logits_relative_l2=0,residual_relative_l2=0,max_batch_ce_diff=0))+'\n' for i in (0,1,2,3,51)))
        elif argv[1]=='training/results/2026-09-29-verdict-balance/verify_verdict_export.py':
            Path(argv[-1]).write_text(json.dumps(dict(valid=True,adapted=3,metadata_equal=True,model=dict(sha256=quote.digest(argv[3])))))
        elif argv[1]=='training/score_decisions.py':
            assert argv[2:5]==[str(run)+'/metrics.jsonl','--sft','training/sft_review_v7_quote.jsonl']
            Path(argv[-1]).write_text(json.dumps(dict(selected_update=25)))
        elif argv[1]=='training/explanations/score_generation.py':
            split=argv[argv.index('--split')+1]
            assert argv[argv.index('--order')+1]=='before'
            assert argv[argv.index('--sft')+1]==('training/sft_review_v6_before.jsonl' if split=='train' else 'training/review_holdout_v5.jsonl')
            Path(argv[-1]).write_text(json.dumps(dict(status='complete',summary=dict(received_reviews=24 if split=='holdout' else 52))))
        elif argv[0]=='node':
            assert argv[1]=='training/quote/manipulation.mjs'
            split=argv[argv.index('--split')+1];collected=Path(argv[argv.index('--run')+1])
            assert ('--reasons' in argv)==(split=='train') and split in ('train','heldout')
            assert collected==output/'generation'/('quote_update100-'+('train' if split=='train' else 'holdout'))
            if scenario=='manipulation-fail':return 2
            count=52 if split=='train' else 24
            Path(argv[argv.index('--out')+1]).write_text(json.dumps(dict(split=split,coverage=dict(source_order_verified=True),
                totals=dict(cases=count),run=dict(generations_sha256=quote.digest(collected/'generations.jsonl')))))
        elif argv[1]=='-c' and argv[-1].endswith('endpoint-binding.json'):
            assert argv[-2]==str(run);Path(argv[-1]).write_text('{"status":"pass"}\n')
        elif argv[1]=='-c' and argv[-1].endswith('parity.jsonl'):
            pass
        else:raise AssertionError(argv)
        return 0
    quote.run_command=fake_command
    def fake_collector(journal,**kwargs):
        state=transport.revisions[transport.current]
        manifests=[json.loads(raw) for path,raw in state.items() if '/units/' in path]
        assert any(m['unit_id']=='quote-native-export-parity.result' for m in manifests)
        assert 'HF_TOKEN' not in os.environ and 'UNLABELED_CREDENTIAL' not in os.environ
        collector_calls.append(kwargs['run_id'])
        out=kwargs['output'];out.mkdir(parents=True)
        cases=[];records=[];split=kwargs['split'];count=24 if split=='holdout' else 52
        assert str(kwargs['corpus'])==('training/sft_review_v6_before.jsonl' if split=='train' else 'training/review_holdout_v5.jsonl')
        for i in range(count):
            prompt=f'common {split} prompt {i}'.encode()
            directory=out/'cases'/f'{i:03d}';directory.mkdir(parents=True);(directory/'prompt.txt').write_bytes(prompt)
            h=hashlib.sha256(prompt).hexdigest();case_id=f'{split}-{i}'
            cases.append(dict(case_id=case_id,prompt_path=f'cases/{i:03d}/prompt.txt',prompt_sha256=h))
            ids=[9,i,2] if scenario=='prompt-mismatch' and split=='train' and i==0 else [1,i,2]
            response='{"analysis":"Rule: x","findings":[]}'
            records.append(dict(case_id=case_id,finish_reason='eos',raw_response=response,
               raw_response_sha256=hashlib.sha256(response.encode()).hexdigest(),
               metadata=dict(prompt_sha256=h,prompt_token_ids=ids,model_sha256=kwargs['expected_model_sha256'])))
        (out/'manifest.json').write_text(json.dumps(dict(cases=cases)))
        (out/'generations.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
        receipt=journal.sync_unit('completion',{'generations.jsonl':out/'generations.jsonl'},sequence=0)
        if scenario=='source-mutation':source.write_bytes(b'changed')
        return dict(status='completed',archive_status='verified',cases=count,run_id=kwargs['run_id'],remote_verification=receipt,
                    generations_sha256=quote.digest(out/'generations.jsonl'))
    os.environ.update(HF_TOKEN='fixture-token',UNLABELED_CREDENTIAL='fixture-token')
    node=lambda:[a for a in native_calls if a[0]=='node']
    try:
        result=quote.execute(archive,prepared,output,collector=fake_collector)
    except (RuntimeError,ArchiveError):
        assert scenario!='success'
        assert not (output/'completion.json').exists()
        if scenario=='bootstrap-fail':assert not native_calls and not collector_calls
        if scenario=='merge-archive-fail':assert not collector_calls and sum(a[0]=='build/jovovich-merge-mlp' for a in native_calls)==1
        if scenario=='source-mutation':assert len(collector_calls)==1
        if scenario=='prompt-mismatch':assert len(collector_calls)==2 and not node()
        if scenario=='manipulation-fail':assert len(node())==1
    else:
        assert scenario=='success'
        assert result['arm']=='quote' and result['generation_calls']==76 and result['semantic_audit']=='pending'
        assert result['structural_reports']==2 and result['teacher_forced_reports']==1 and result['manipulation_reports']==2
        assert result['remote_verification']['verified_remote_bytes']
        assert collector_calls==['fixture-evaluation-quote_update100-train','fixture-evaluation-quote_update100-holdout']
        assert sum(a[0]=='build/jovovich-merge-mlp' for a in native_calls)==1 and sum(a[0]=='build/jovovich-probe-mlp' for a in native_calls)==1
        assert [a[a.index('--split')+1] for a in node()]==['train','heldout']
        assert json.loads((output/'prompt-comparison.json').read_text())['unique_prompts']=={'train':52,'holdout':24}
        units={json.loads(raw)['unit_id']:json.loads(raw)['sequence'] for path,raw in transport.revisions[transport.current].items() if '/units/' in path}
        assert units['before-prompts.result']<units['quote_update100-train-manipulation.intent']<units['quote_update100-holdout-manipulation.result']
        assert (output/'manipulation/train.json').exists() and (output/'manipulation/holdout.json').exists()
        assert (output/'_receipts/completion.json').exists()
        assert os.environ['HF_TOKEN']=='fixture-token'
`;

for (const scenario of ['success', 'bootstrap-fail', 'merge-archive-fail', 'source-mutation', 'prompt-mismatch', 'manipulation-fail']) {
  test(`quote evaluation orchestration: ${scenario}`, () => {
    const r = python(RUN, scenario);
    assert.equal(r.status, 0, r.stderr || r.stdout || String(r.error));
  });
}
