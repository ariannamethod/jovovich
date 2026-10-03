import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

const fixture = String.raw`
import copy, hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path
sys.path[:0]=['training/explanations','test']
import execute_evaluation as runner
from durable_archive import DurableArchive, ArchiveError
from durable_archive_fixture import FakeTransport
contract=json.loads(Path('training/explanations/evaluation_plan.json').read_text())
scenario=sys.argv[1]
Path('models').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='eval-execution-fixture-',dir='models') as temporary:
    temporary=Path(temporary).resolve();output=temporary/'evaluation'
    source=temporary/'bound.txt';source.write_bytes(b'frozen fixture input')
    parameters={'BEFORE_RUN':str(temporary/'before'),'AFTER_RUN':str(temporary/'after'),
      'EVALUATION_RUN':str(output),'EVALUATION_RUN_ID':'fixture-evaluation','INFER_SHA256':'a'*64,
      'SHARED_BASE_UPDATE0_SHA256':'b'*64}
    phases=[runner.export_unit(step,parameters,output) for arm in contract['exports'] for step in arm['steps']]
    for phase in phases:
        assert not (set(phase['outputs']) & {phase.get('stdout'),phase.get('stderr')})
    prepared=dict(schema_version=1,run_id='fixture-evaluation',parameters=parameters,
                  training={arm:{'directory':str(temporary/arm)} for arm in ('before','after')},
                  contract=contract,bindings=[runner.binding(source)],training_receipts=[],export_phases=phases)
    class DirectoryTransport(FakeTransport):
        def inventory(self,revision,prefix):
            return {name:value for name,value in super().inventory(revision,prefix).items() if name.startswith(prefix+'/')}
    transport=DirectoryTransport();archive=DurableArchive(transport,'fixture-evaluation','experiments/explanation-order')
    if scenario=='bootstrap-fail':
        transport.download_fault=lambda name,data:b'corrupt' if '/objects/' in name else data
    native_calls=[];collector_calls=[]
    def fake_command(argv,stdout,stderr,environment):
        assert environment['NT_NO_I8']=='1' and environment['NT_QMV_THREADS']=='4'
        assert all(k not in environment for k in ('HF_TOKEN','UNLABELED_CREDENTIAL','NT_QMV_IMPL','LD_PRELOAD'))
        stdout.parent.mkdir(parents=True,exist_ok=True);stderr.parent.mkdir(parents=True,exist_ok=True)
        stdout.write_bytes(b'');stderr.write_bytes(b'');native_calls.append(argv)
        if argv[0]=='build/jovovich-merge-mlp':
            assert argv[2].endswith('/adapter.epoch100')
            Path(argv[3]).write_bytes(('fixture export '+argv[2]).encode())
            if scenario=='merge-archive-fail':
                transport.download_fault=lambda name,data:b'corrupt' if '/objects/' in name else data
        elif argv[0]=='build/jovovich-probe-mlp':
            assert argv[-5:]==['0','1','2','3','51']
            stdout.write_text(''.join(json.dumps(dict(row=i,**{'pass':True},argmax_agree=7,completion_tokens=7,
                   logits_relative_l2=0,residual_relative_l2=0,max_batch_ce_diff=0))+'\n' for i in (0,1,2,3,51)))
        elif argv[1]=='training/results/2026-09-29-verdict-balance/verify_verdict_export.py':
            Path(argv[-1]).write_text(json.dumps(dict(valid=True,adapted=3,metadata_equal=True,
                 model=dict(sha256=runner.digest(argv[3])))))
        elif argv[1]=='training/score_decisions.py':
            Path(argv[-1]).write_text(json.dumps(dict(selected_update=25,trajectory=list(range(101)))))
        elif argv[1]=='training/explanations/score_generation.py':
            count=24 if argv[argv.index('--split')+1]=='holdout' else 52
            Path(argv[-1]).write_text(json.dumps(dict(status='complete',summary=dict(received_reviews=count))))
            if scenario=='generation-mutation':Path(argv[2]).write_text('altered after collector return')
        elif argv[1]=='-c' and argv[-1].endswith('endpoint-binding.json'):
            Path(argv[-1]).write_text('{"status":"pass"}\n')
        elif argv[1]=='-c' and argv[-1].endswith('parity.jsonl'):
            pass
        else:raise AssertionError(argv)
        return 0
    runner.run_command=fake_command
    def fake_collector(journal,**kwargs):
        # Both exports must have passed their remotely committed parity phase.
        state=transport.revisions[transport.current]
        manifests=[json.loads(raw) for path,raw in state.items() if '/units/' in path]
        assert all(any(m['unit_id']==arm+'-native-export-parity.result' for m in manifests) for arm in ('before','after'))
        collector_calls.append(kwargs['run_id'])
        assert 'HF_TOKEN' not in os.environ and 'UNLABELED_CREDENTIAL' not in os.environ
        if len(collector_calls)==1:
            child=subprocess.run([sys.executable,'-c','import os; assert "HF_TOKEN" not in os.environ and "UNLABELED_CREDENTIAL" not in os.environ'],capture_output=True)
            assert child.returncode==0
        out=kwargs['output'];out.mkdir(parents=True)
        cases=[];records=[];count=24 if kwargs['split']=='holdout' else 52
        for i in range(count):
            prompt=f'common {kwargs["split"]} prompt {i}'.encode()
            directory=out/'cases'/f'{i:03d}';directory.mkdir(parents=True)
            (directory/'prompt.txt').write_bytes(prompt)
            h=hashlib.sha256(prompt).hexdigest();case_id=f'{kwargs["split"]}-{i}'
            cases.append(dict(case_id=case_id,prompt_path=f'cases/{i:03d}/prompt.txt',prompt_sha256=h))
            ids=[1,i,2]
            if scenario=='prompt-mismatch' and 'after_update100' in kwargs['run_id'] and i==0:ids=[9,i,2]
            response='{"findings":[]}'
            records.append(dict(case_id=case_id,finish_reason='eos',raw_response=response,
               raw_response_sha256=hashlib.sha256(response.encode()).hexdigest(),
               metadata=dict(prompt_sha256=h,prompt_token_ids=ids,model_sha256=kwargs['expected_model_sha256'])))
        (out/'manifest.json').write_text(json.dumps(dict(cases=cases)))
        (out/'generations.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
        receipt=journal.sync_unit('completion',{'generations.jsonl':out/'generations.jsonl'},sequence=0)
        if scenario=='source-mutation':source.write_bytes(b'changed')
        if scenario=='outer-plan-mutation':(output/'plan.json').write_text('{}')
        return dict(status='completed',archive_status='verified',cases=count,run_id=kwargs['run_id'],remote_verification=receipt,
                    generations_sha256=runner.digest(out/'generations.jsonl'))
    os.environ.update(HF_TOKEN='fixture-token',UNLABELED_CREDENTIAL='fixture-token')
    try:
        result=runner.execute(archive,prepared,output,collector=fake_collector)
    except (RuntimeError,ArchiveError):
        assert scenario!='success'
        if scenario=='bootstrap-fail':assert not native_calls and not collector_calls
        if scenario=='merge-archive-fail':assert not collector_calls and sum(a[0]=='build/jovovich-merge-mlp' for a in native_calls)==1
        if scenario=='source-mutation':assert len(collector_calls)==1
        if scenario in ('generation-mutation','outer-plan-mutation'):assert len(collector_calls)==1 and not (output/'completion.json').exists()
        if scenario=='prompt-mismatch':assert len(collector_calls)==6 and not (output/'completion.json').exists()
    else:
        assert scenario=='success'
        assert result['generation_calls']==228 and result['semantic_audit']=='pending'
        assert result['teacher_forced_reports']==2 and result['structural_reports']==6
        assert result['remote_verification']['verified_remote_bytes']
        assert len(collector_calls)==6
        assert len([a for a in native_calls if a[0]=='build/jovovich-merge-mlp'])==2
        assert len([a for a in native_calls if a[0]=='build/jovovich-probe-mlp'])==2
        assert json.loads((output/'prompt-comparison.json').read_text())['unique_prompts']=={'train':52,'holdout':24}
        assert (output/'_receipts/completion.json').exists()
        assert all((output/'_receipts'/(job['id']+'.json')).exists() for job in contract['collector_jobs'])
        assert os.environ['HF_TOKEN']=='fixture-token' and os.environ['UNLABELED_CREDENTIAL']=='fixture-token'
`;

for (const scenario of ['success', 'bootstrap-fail', 'merge-archive-fail', 'source-mutation', 'prompt-mismatch', 'generation-mutation', 'outer-plan-mutation']) {
  test(`evaluation orchestration: ${scenario}`, () => {
    const result = spawnSync('python3', ['-c', fixture, scenario], {encoding:'utf8', timeout:30000});
    assert.equal(result.status, 0, result.stderr || result.stdout || String(result.error));
  });
}

test('evaluation subprocess environment retains only declared native settings', () => {
  const code = String.raw`
import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,'training/explanations')
import execute_evaluation as runner
os.environ.update(HF_TOKEN='fixture-secret',UNLABELED_CREDENTIAL='fixture-secret',NT_QMV_IMPL='fixture',LD_PRELOAD='fixture')
env=runner.native_environment({'NT_NO_I8':'1','NT_QMV_THREADS':'4','NT_ATTN_THREADS':'4','NT_SIMD_THREADS':'4'})
with tempfile.TemporaryDirectory() as temporary:
    out=Path(temporary)/'stdout';err=Path(temporary)/'stderr'
    code='import os; assert all(k not in os.environ for k in ("HF_TOKEN","UNLABELED_CREDENTIAL","NT_QMV_IMPL","LD_PRELOAD")); assert os.environ["NT_NO_I8"]=="1"'
    assert runner.run_command([sys.executable,'-c',code],out,err,env)==0,err.read_text()
`;
  const result = spawnSync('python3', ['-c', code], {encoding:'utf8', timeout:15000});
  assert.equal(result.status, 0, result.stderr || result.stdout || String(result.error));
});

test('evaluation preflight accepts arm-local datasets and rejects swapped arms or protocol drift', () => {
  const code = String.raw`
import copy,json,sys,tempfile
from pathlib import Path
sys.path.insert(0,'training/explanations')
import execute_evaluation as runner
original_root=runner.ROOT
contract=json.loads(Path('training/explanations/evaluation_plan.json').read_text())
scientific=json.loads(Path('training/explanations/plan.json').read_text())
with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary);runner.ROOT=root
    runner.__file__=str(root/'training/explanations/execute_evaluation.py')
    inputs=contract['required_pretraining_launch_bindings']+['models/base-qwen.gguf',contract['scientific_plan'],
         'training/explanations/execute_evaluation.py','training/score_decisions.py']
    for name in inputs:
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(('fixture '+name).encode())
    contract['resolution']['SHARED_BASE_UPDATE0_SHA256']=runner.digest(root/'models/base-qwen.gguf')
    plan=root/'training/explanations/evaluation_plan.json';plan.write_text(json.dumps(contract))
    (root/contract['scientific_plan']).write_text(json.dumps(scientific))
    allbindings={name:runner.binding(root/name) for name in inputs}
    directories={}
    for arm in ('before','after'):
        directory=root/'models'/arm;(directory/'_units').mkdir(parents=True);directories[arm]=directory
        other='after' if arm=='before' else 'before'
        skip={f'training/results/2026-10-03-explanation-order-run/native/{other}.bin',
              f'training/results/2026-10-03-explanation-order-run/native/{other}.pairs.bin',
              'training/explanations/execute_evaluation.py'}
        bindings=[item for name,item in allbindings.items() if name not in skip]
        launch=dict(arm=arm,run_id='fixture-'+arm,argv=['build/jovovich-train-mlp','models/base-qwen.gguf',
             f'training/results/2026-10-03-explanation-order-run/native/{arm}.bin','@RUN@/adapter','100','0.0001','40','25','joint',
             f'training/results/2026-10-03-explanation-order-run/native/{arm}.pairs.bin'],bindings=bindings,
             environment=scientific['training']['native_environment'],
             remote=dict(repo='ataeff/jovovich',prefix='experiments/explanation-order',private=True))
        (directory/'plan.json').write_text(json.dumps(launch))
        final=[];saved=[]
        for part in ('gate','up','down'):
            for ext in ('f32','lora'):
                for epoch,entries in [('',final),('.epoch100',saved)]:
                    name=f'adapter{epoch}.{part}.{ext}';path=directory/name;path.write_bytes((part+ext).encode())
                    entries.append(dict(name=name,size=path.stat().st_size,sha256=runner.digest(path)))
        completion=dict(status='native_completed',archive_status='requires_verified_receipt',
          acknowledged_updates=100,return_code=0,plan_sha256=runner.digest(directory/'plan.json'),bindings=bindings,
          initial_lora_sha256={part:'a'*64 for part in ('gate','up','down')})
        for name,value in [('completion.json',completion),('metrics.jsonl',{})]:
            path=directory/name;path.write_text(json.dumps(value))
            final.append(dict(name=name,size=path.stat().st_size,sha256=runner.digest(path)))
        receipt=dict(run_id=launch['run_id'],verified_remote_bytes=True,unit_id='completion',files=final,
                     sequence=103,revision='a'*40,prefix='experiments/explanation-order/'+launch['run_id'],manifest_sha256='b'*64)
        (directory/'_units/completion.ack.json').write_text(json.dumps(dict(completion,status='completed',archive_status='verified',remote_verification=receipt)))
        (directory/'_units/update-100.ack.json').write_text(json.dumps(dict(receipt,unit_id='update-100',files=saved,sequence=102)))
    args=(plan,directories['before'],directories['after'],root/'models/evaluation','test-evaluation')
    prepared=runner.prepare(*args)
    paths={b['path'] for b in prepared['bindings']}
    assert set(contract['required_pretraining_launch_bindings'])<=paths
    def reject(args,fragment):
        try:runner.prepare(*args)
        except RuntimeError as error:assert fragment in str(error),str(error)
        else:raise AssertionError('bad preflight accepted')
    reject((plan,directories['after'],directories['before'],root/'models/evaluation','test-evaluation'),'wrong arm')
    reject((plan,directories['before'],directories['before'],root/'models/evaluation','test-evaluation'),'wrong arm')
    launchpath=directories['before']/'plan.json';original=launchpath.read_text();changed=json.loads(original)
    changed['argv'][5]='0.001';launchpath.write_text(json.dumps(changed));reject(args,'scientific contract');launchpath.write_text(original)
    changed=json.loads(original);changed['environment']['NT_QMV_THREADS']='8';launchpath.write_text(json.dumps(changed));reject(args,'scientific contract')
`;
  const result = spawnSync('python3', ['-c', code], {encoding:'utf8', timeout:15000});
  assert.equal(result.status, 0, result.stderr || result.stdout || String(result.error));
});
