"""Explicit-error revalidation; none of its gates disappear under python -O."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, importlib.util, json, math, mmap, os, sys
from contextlib import ExitStack

OUT=Path('training/results/2026-10-02-checkpoint-control')
def require(ok,message):
    if not ok: raise RuntimeError(message)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def binding(path):
    path=Path(path);h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return dict(path=str(path),bytes=path.stat().st_size,sha256=h.hexdigest())
def read(path):return json.loads(Path(path).read_text())
def rows(path):return [json.loads(line) for line in Path(path).read_text().splitlines()]
plan=read(OUT/'protocol.json');plan_sha=binding(OUT/'protocol.json')['sha256']
for b in plan['bindings']:require(binding(b['path'])==b,f'changed frozen input {b["path"]}')
verified=read(OUT/'verified-models.json')
require(verified['protocol_sha256']==plan_sha and verified['status']=='export_and_parity_passed','model gate metadata')
for b in verified['models'].values():require(binding(b['path'])==b,'model hash mismatch')
for b in verified['generated_weights']+verified['checks']:require(binding(b['path'])==b,'generated weight/audit changed')
spec=importlib.util.spec_from_file_location('independent_gguf_audit','training/results/2026-09-29-convergence/check_convergence_export.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
def verify_gguf(model,update):
    with ExitStack() as stack:
        def mapped(p):
            f=stack.enter_context(Path(p).open('rb'));return stack.enter_context(mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ))
        base=mapped('models/base-qwen.gguf');merged=mapped(model);b=audit.parse_gguf(base);m=audit.parse_gguf(merged)
        require(audit.normalized_header(base,b)==audit.normalized_header(merged,m),'GGUF header mismatch')
        require(len(b['tensors'])==len(m['tensors'])==291,'tensor count')
        replaced={f'blk.23.ffn_{p}.weight':p for p in ['gate','up','down']}
        cursor=0;changed=0;unchanged=0
        for original,actual in zip(b['tensors'],m['tensors']):
            name=actual['name']
            require(name==original['name'] and actual['shape']==original['shape'],'tensor identity')
            require(actual['offset']==cursor,'tensor layout')
            if name in replaced:
                reference=mapped(f'models/checkpoint-control/update{update}.{replaced[name]}.f32');start=0
                require(actual['type']==0 and len(reference)==actual['bytes'],'replacement type/size');changed+=1
            else:
                reference=base;start=b['data_offset']+original['offset'];unchanged+=1
                require(actual['type']==original['type'] and actual['bytes']==original['bytes'],'unchanged tensor type/size')
            require(audit.equal_payload(merged,m['data_offset']+actual['offset'],reference,start,actual['bytes']),name+' payload')
            cursor=audit.align32(cursor+actual['bytes'])
        require(changed==3 and unchanged==288 and len(merged)==m['data_offset']+cursor==714116992,'GGUF extent/count')
        return dict(adapted_equal=changed,unchanged_equal=unchanged,exact_extent=True)
export_checks={};parity_checks={};arm_counts={};all_rows={}
cases=rows(OUT/'cases.jsonl');require(len(cases)==24 and len({c['name'] for c in cases})==24,'case count/identity')
pairs={}
for c in cases:pairs.setdefault(c['pair'],[]).append(c['expected_concern'])
require(len(pairs)==12 and all(sorted(labels)==[False,True] for labels in pairs.values()),'pair coverage')
require(len({c['audit_metadata']['family'] for c in cases})==6,'family coverage')
for arm,update in [('update25',25),('update100',100)]:
    for part in ['gate','up','down']:
        require(binding(f'models/recovered-matched/matched-review.epoch{update}.{part}.lora')['sha256']==
            binding(f'models/checkpoint-control/update{update}.{part}.lora')['sha256'],'adapter serialization changed')
    export_checks[arm]=verify_gguf(verified['models'][arm]['path'],update)
    parity_receipt=read(OUT/f'parity-{update}.receipt.json')
    require(parity_receipt['exit_code']==0 and parity_receipt['argv']==['models/checkpoint-control/probe-mlp',
        'models/base-qwen.gguf',verified['models'][arm]['path'],'models/recovered-matched/matched-review.bin',
        f'models/recovered-matched/matched-review.epoch{update}','0','1','2'],'native parity command/exit')
    parity=rows(OUT/f'parity-{update}.stdout.txt');require([r['row'] for r in parity]==[0,1,2],'parity row coverage')
    for r in parity:
        require(r['pass'] and r['argmax_agree']==r['completion_tokens'],'parity argmax')
        for key,limit in [('logits_relative_l2',1e-5),('residual_relative_l2',1e-5),('max_batch_ce_diff',1e-4)]:
            require(math.isfinite(r[key]) and 0<=r[key]<=limit,'parity threshold '+key)
    parity_checks[arm]=dict(positions=sum(r['completion_tokens'] for r in parity),argmax_agree=sum(r['argmax_agree'] for r in parity),max_batch_ce_diff=max(r['max_batch_ce_diff'] for r in parity))
    records=rows(OUT/arm/'responses.jsonl');all_rows[arm]=records
    require(len(records)==24 and [r['name'] for r in records]==plan['case_order'],'generation cohort')
    for c,r in zip(cases,records):
        stem=OUT/arm/f'{c["index"]:03d}'
        require(all(r[k]==v for k,v in c.items()),'case/prompt changed')
        require(r['prompt_sha256']==sha(r['prompt'].encode()),'prompt hash')
        require(r['supplied_prefix']=='' and r['supplied_prefix_ids']==[] and r['mode']=='natural','forced prefix')
        require(r['model']==verified['models'][arm] and r['protocol_sha256']==plan_sha,'response model/plan binding')
        raw=Path(str(stem)+'.stdout.txt').read_bytes();require(raw.decode()==r['continuation']==r['assembled_response'],'raw output mismatch')
        require(sha(raw)==r['response_sha256'],'raw output digest')
        trace_raw=Path(str(stem)+'.trace.json').read_bytes();trace=json.loads(trace_raw)
        require(trace==r['trace'] and sha(trace_raw)==r['trace_sha256'],'trace binding')
        ids=[int(x) for x in Path(str(stem)+'.tokenize.stdout.txt').read_text().strip().split(',')]
        require(ids==r['original_prompt_ids']==trace['prompt_token_ids'],'prompt token IDs')
        require(trace['requested_limit']==192 and trace['stop_reason'] in ['eos','token-limit'],'trace mode')
        generated=trace['generated_token_ids'];require(0<len(generated)<=192 and all(type(x)is int and 0<=x<151936 for x in generated),'generated IDs')
        require(len(generated)==trace['emitted_tokens']+(1 if trace['stop_reason']=='eos' else 0),'trace length')
        if trace['stop_reason']=='token-limit':require(trace['emitted_tokens']==192,'token-limit length')
        require(read(str(stem)+'.process.json')['returncode']==r['returncode']==0,'child exit')
    arm_counts[arm]=dict(cases=len(records),parser_usable=sum(r['assessment']['parsed_findings'] is not None for r in records),
        empty_findings=sum(r['assessment']['parsed_findings']==[] for r in records),
        correct_clean_empty=sum(not r['expected_concern'] and r['assessment']['parsed_findings']==[] for r in records),
        eos=sum(r['trace']['stop_reason']=='eos' for r in records),token_limit=sum(r['trace']['stop_reason']=='token-limit' for r in records))
require(all(a['original_prompt_ids']==b['original_prompt_ids'] for a,b in zip(all_rows['update25'],all_rows['update100'])),'different arm tokenized prompts')
complete=read(OUT/'complete.json');require(complete['status']=='complete' and complete['total_responses']==48 and complete['protocol_sha256']==plan_sha,'completion metadata')
result=dict(schema='jovovich.checkpoint-explicit-validation.v1',status='passed',created_at=datetime.now(timezone.utc).isoformat(),
    validator=binding(__file__),python_optimization_level=sys.flags.optimize,protocol_sha256=plan_sha,frozen_bindings_verified=len(plan['bindings']),export_checks=export_checks,
    parity_checks=parity_checks,mechanical_counts=arm_counts,total_responses=48,semantic_judgments='Not performed by this validator.',
    guard_note='All validation predicates use explicit RuntimeError checks and remain active under optimized Python.')
with (OUT/'explicit-validation.json').open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
print(json.dumps(result))
