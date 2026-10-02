import importlib.util,json,pathlib,struct,tempfile,subprocess,sys,copy,os
repo=pathlib.Path('/workspace/scratch/ec5ba60588d8/jovovich');p=repo/'training/layers/prepare_layers.py'
s=importlib.util.spec_from_file_location('layers',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
r=pathlib.Path(tempfile.mkdtemp(prefix='layers-final-helper-check-',dir='/workspace/scratch/ec5ba60588d8'))
out=r/'prepared';m.prepare(repo,out)
rows=r/'rows';rows.mkdir()
for i in range(52):
    n=100+i
    data=b'JVRL1\0\0\0'+struct.pack('<4I',1,24,2,896)+struct.pack('<5I',i,n,n+3,n-1,n+2)
    for boundary in range(2):
        for layer in range(24):data+=struct.pack('<896f',*([i*100+boundary*24+layer]*896))
    (rows/f'row-{i:03d}.bin').write_bytes(data)
    (rows/f'row-{i:03d}.z.bin').write_bytes(b'JVRF1\0\0\0'+struct.pack('<2I',1,896)+struct.pack('<896f',*([5000+i]*896)))
    ids=[151644,8948,198]+[198]*(n-6)+[151644,77091,198]+m.PREFIX_IDS
    trace={'row':i,'prompt_tokens':n,'input_tokens':n+3,'context_limit':32768,'feature_format':'JVRL1','feature_shape':[2,24,896],'feature_order':['position','layer','width'],'layer_boundary':'post_block_before_next_layer_or_final_output_norm','capture_positions':[n-1,n+2],'capture_names':['assistant_header_end','common_prefix_end'],'capture_token_ids':[198,819],'prefix_ids':m.PREFIX_IDS,'ordinary_capture_weights_modified':False,'fresh_kv':True,'finite_features':True,'capture_counts':[1]*48,'input_ids':ids,'anchor':{'feature_format':'JVRF1','feature_shape':[1,896],'capture_position':n+2,'layer':23,'boundary':'pre_final_mlp','fresh_kv':True,'temporary_zero_down':True,'down_bias_temporarily_disabled':True,'projection_restored':True},'verification':None}
    if i in (0,1):trace['verification']={'absolute_tolerance':1e-4,'relative_l2_tolerance':1e-5,'future_suffixes':[[4913,3903],[819,3903]],'comparisons':[{'name':name,'vectors':48,'max_abs':0,'max_relative_l2':0,'pass':True} for name in ('token_step','future_append','future_change')]}
    (rows/f'row-{i:03d}.trace.jsonl').write_text(json.dumps(trace)+'\n')
m.validate_row(out,rows,0,rows/'row-000.trace.jsonl')
negative=[]
trace_path=rows/'row-000.trace.jsonl';original=trace_path.read_text();trace=json.loads(original)
mutations={'missing_verification':lambda x:x.update(verification=None),'wrong_boundary_id':lambda x:x['input_ids'].__setitem__(-1,818),'missing_layer_capture':lambda x:x['capture_counts'].__setitem__(23,0),'unrestored_projection':lambda x:x['anchor'].update(projection_restored=False),'failed_numeric_error':lambda x:x['verification']['comparisons'][0].update(max_abs=1.1e-4)}
for name,mutate in mutations.items():
    trial=copy.deepcopy(trace);mutate(trial);trace_path.write_text(json.dumps(trial)+'\n')
    try:m.validated_row(out,rows,0,trace_path)
    except RuntimeError:negative.append(name)
    else:raise RuntimeError('accepted corrupt trace: '+name)
trace_path.write_text(original)
input_path=out/'layers-input.bin';original_input=input_path.read_bytes();input_path.write_bytes(original_input[:-1]+bytes([original_input[-1]^1]))
try:m.validated_row(out,rows,0,trace_path)
except RuntimeError:negative.append('changed_prompt_bytes')
else:raise RuntimeError('accepted changed input')
input_path.write_bytes(original_input)
m.assemble(out,rows)
checked=0
for boundary_i,boundary in enumerate(m.BOUNDARIES):
    for layer in range(24):
        raw=(out/f'{boundary}-layer-{layer:02d}.bin').read_bytes()
        for row in range(52):
            m.require(struct.unpack_from('<896f',raw,16+row*896*4)==(row*100+boundary_i*24+layer,)*896,'transposition mismatch')
            checked+=1
anchor=(out/'prefix-final-mlp-z.bin').read_bytes()
for row in range(52):m.require(struct.unpack_from('<896f',anchor,16+row*896*4)==(5000+row,)*896,'anchor mismatch')
old=repo/'training/results/2026-10-01-frozen-readout';fitdir=r/'fits';fitdir.mkdir()
for base,name in [('state-fits.jsonl','state'),('nuisance-fit-fits.jsonl','nuisance')]:
    records=[json.loads(x) for x in (old/base).read_text().splitlines()]
    selected=[x for x in records if x['type']!='fit' or x['permutation'] in (-1,0)]
    selected[0]['permutations']=1;selected[-1]={'type':'completion','fits':42,'failed_fits':0,'all_converged':True}
    f=r/(name+'.fits.jsonl');f.write_text(''.join(json.dumps(x)+'\n' for x in selected))
    for view in m.views():
        if (view['name']=='nuisance') == (name=='nuisance'):os.link(f,fitdir/(view['name']+'.fits.jsonl'))
m.summarize(out,fitdir)
summary=json.loads((out/'layers-summary.json').read_text());m.require(len(summary['views'])==50 and summary['views'][0]['observed']['correct']==29,'historical score preservation')
optimized=subprocess.run([sys.executable,'-O',str(p),'--help'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
m.require(optimized.returncode!=0,'optimized runner accepted')
receipt={'status':'pass','fixture_scope':'Synthetic fixed features/native trace fixtures and replay of archived C fit outputs; no model invocation.','scratch':str(r),'distinct_row_position_layer_slices_checked':checked,'anchor_rows_checked':52,'native_trace_rows_validated':52,'negative_fixtures_rejected':negative,'historical_fit_subset_per_view':42,'summary_views_checked':50,'historical_observed_correct_preserved':29,'optimized_runner_rejected':True,'helper':m.source(p),'protocol_template':m.source(p.with_name('protocol_template.json'))}
(r/'helper-validation.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
