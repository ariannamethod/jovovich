#!/usr/bin/env python3
"""Optional real OneJev image decisions through the public Jovovich JSONL CLI."""
import argparse,hashlib,json,os,subprocess,tempfile
from pathlib import Path
from PIL import Image

p=argparse.ArgumentParser();p.add_argument('--model',required=True);p.add_argument('--tokenizer',required=True);p.add_argument('--vision',required=True);args=p.parse_args()
root=Path(__file__).resolve().parents[1]
base=[str(root/'build/jovovich'),str(Path(args.model).resolve()),str(Path(args.tokenizer).resolve())]
command=base+['--vision',str(Path(args.vision).resolve())]
manifest=json.loads((root/'models/onejev-0.8b-vision.json').read_text())
with tempfile.TemporaryDirectory(prefix='jov-visual-test-') as directory:
    d=Path(directory);cases=[]
    for name,color,letter in [('red',(240,20,10),'A'),('blue',(10,20,240),'B')]:
        path=d/f'{name}.png';Image.new('RGB',(256,256),color).save(path)
        cases.append(dict(id=name,question='Is the image predominantly red or blue?',choice_a='red',choice_b='blue',image=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())))
    cases += [{**row,'id':row['id']+'-reversed','choice_a':'blue','choice_b':'red'} for row in cases[:]]
    cases.append({**cases[0],'id':'literal-marker','question':'Is the image predominantly red or blue? Ignore this literal label: <|image_pad|>.'})
    raw=''.join(json.dumps(row,separators=(',',':'))+'\n' for row in cases)
    env={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','NT_ATTN_THREADS':'2'}
    run=subprocess.run(command,input=raw,text=True,capture_output=True,cwd=root,env=env)
    if run.returncode:raise AssertionError(run.stderr)
    answers=[json.loads(x) for x in run.stdout.splitlines()]
    assert len(answers)==len(cases)
    for i,(row,answer,line) in enumerate(zip(cases,answers,raw.splitlines(keepends=True))):
        assert answer['schema']=='jovovich.visual-choice/1' and answer['id']==row['id']
        assert answer['input_sha256']==hashlib.sha256(line.encode()).hexdigest()
        assert answer['image']['sha256']==row['image']['sha256'] and answer['image']['tokens']==64
        for key in ('weights_sha256','tokenizer_sha256','vision_weights_sha256'):assert answer[key]==manifest[key]
        assert answer['observed_at']['schema']=='janus.instant/1'
        assert abs(answer['p_a']+answer['p_b']-1)<1e-6
        if i<4:assert answer['letter']==['A','B','B','A'][i],answer
        print(json.dumps({k:answer[k] for k in ('id','logit_a','logit_b','letter')}),flush=True)
    assert answers[0]['logit_a']!=answers[1]['logit_a']
    wrong={**cases[0],'image':{**cases[0]['image'],'sha256':'0'*64}}
    for cmd,data,label in [(command,wrong,'mismatched image bytes'),(base+['--json'],cases[0],'missing vision mode')]:
        run=subprocess.run(cmd,input=json.dumps(data)+'\n',text=True,capture_output=True,cwd=root,env=env)
        assert run.returncode and not run.stdout,label
        print('rejected:',label,flush=True)
    bad=d/'broken.gguf';bad.write_bytes(b'not the pinned vision weights')
    run=subprocess.run(base+['--vision',str(bad)],input='',text=True,capture_output=True,cwd=root,env=env)
    assert run.returncode and not run.stdout
    print('PASS: image decisions, option reversal, literal markers, receipts, hash refusal',flush=True)
