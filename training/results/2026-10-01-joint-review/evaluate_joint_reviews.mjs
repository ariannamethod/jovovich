#!/usr/bin/env node
import assert from 'node:assert/strict';
import { createReadStream } from 'node:fs';
import { readFile, mkdir, open } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const ROOT=process.cwd(), HERE=path.dirname(fileURLToPath(import.meta.url));
const {casesFor,assess,PREFIX,PREFIX_IDS}=await import(pathToFileURL(path.join(ROOT,'training/results/2026-09-29-small-step/probe_shared_prefix.mjs')));
const {chunksFor,promptFor}=await import(pathToFileURL(path.join(ROOT,'bin/jovovich.mjs')));
const sha=s=>createHash('sha256').update(s).digest('hex');
async function fileHash(p){const h=createHash('sha256');for await(const b of createReadStream(p))h.update(b);return h.digest('hex');}
function jsonl(s){assert.ok(s.endsWith('\n'));return s.trim().split('\n').map(JSON.parse);}
const opts={};
for(let i=2;i<process.argv.length;i+=2){assert.ok(process.argv[i].startsWith('--')&&process.argv[i+1]);const k=process.argv[i].slice(2);assert.ok(!Object.hasOwn(opts,k));opts[k]=process.argv[i+1];}
for(const k of Object.keys(opts))assert.ok(['model','kind','mode','output','trace-dir','shard'].includes(k),'unknown argument');
for(const k of ['model','kind','mode','output','trace-dir'])assert.ok(opts[k],k+' required');
assert.ok(['train','diagnostics','audit'].includes(opts.kind));assert.ok(['natural','shared'].includes(opts.mode));
assert.ok(opts.shard===undefined||['0','1'].includes(opts.shard));
let cases,source,sourceText;
if(opts.kind==='audit'){
 source=path.join(HERE,'diff-shape-audit.jsonl');sourceText=await readFile(source,'utf8');
 const rows=jsonl(sourceText),identity=await readFile(path.join(ROOT,'prompts/identity.txt'),'utf8');assert.equal(rows.length,8);
 cases=[];
 for(const r of rows){const chunks=chunksFor(r.files);assert.equal(chunks.length,1);cases.push({name:r.id,pair:r.pair,cohort:'audit',prompt:await promptFor(chunks[0],r.context,identity,'chatml'),chunk:chunks[0],context:8192,expected_concern:r.expected_concern,expected_line_ids:r.expected_line_ids,expected_reason_concept:r.expected_reason_concept,audit_metadata:r.audit_metadata??r.metadata??null});}
}else{const cohort=opts.kind==='train'?'train':'runtime';const c=await casesFor(cohort);cases=c.cases;source=c.source;sourceText=await readFile(source,'utf8');}
assert.equal(new Set(cases.map(c=>c.name)).size,cases.length);
const allCases=cases,shard=opts.shard===undefined?null:Number(opts.shard);
cases=cases.filter((c,i)=>shard===null||i%2===shard);
const model=path.resolve(opts.model),runner=path.join(ROOT,'build/jovovich-infer');
const hashes={model_sha256:await fileHash(model),runner_sha256:await fileHash(runner),infer_source_sha256:await fileHash(path.join(ROOT,'src/infer.c')),host_sha256:await fileHash(path.join(ROOT,'bin/jovovich.mjs')),probe_source_sha256:await fileHash(fileURLToPath(import.meta.url)),source_sha256:sha(sourceText)};
const env={...process.env,NT_NO_I8:'1',NT_QMV_THREADS:'2',NT_ATTN_THREADS:'2',NT_SIMD_THREADS:'2'};
const run=(c,prompt,args)=>spawnSync(runner,['--model',model,'--tokens','192','--context',String(c.context),'--temperature','0',...args],{cwd:ROOT,input:prompt,encoding:'utf8',env,timeout:600000,maxBuffer:8*1024*1024});
const prepared=cases.map(c=>{
 const r=run(c,c.prompt,['--token-ids']);assert.equal(r.status,0,r.error?.message||r.stderr);assert.match(r.stdout.trim(),/^\d+(,\d+)*$/);
 return {c,originalIds:r.stdout.trim().split(',').map(Number)};
});
await mkdir(path.dirname(path.resolve(opts.output)),{recursive:true});
await mkdir(path.resolve(opts['trace-dir']),{recursive:false});
const output=await open(opts.output,'wx');
try{
 for(const [i,{c,originalIds}] of prepared.entries()){
  const prefix=opts.mode==='shared'?PREFIX:'', supplied=c.prompt+prefix;
  const traceFile=path.resolve(opts['trace-dir'],String(i).padStart(3,'0')+'.json');
  const started=Date.now(),r=run(c,supplied,['--trace-tokens',traceFile]);
  assert.equal(r.status,0,r.error?.message||r.stderr);
  const traceText=await readFile(traceFile,'utf8'),trace=JSON.parse(traceText);
  assert.equal(trace.schema_version,1);
  assert.deepEqual(trace.prompt_token_ids,[...originalIds,...(prefix?PREFIX_IDS:[])]);
  assert.ok(Array.isArray(trace.generated_token_ids)&&trace.generated_token_ids.length>0);
  assert.ok(trace.generated_token_ids.every(x=>Number.isInteger(x)&&x>=0));
  assert.ok(trace.generated_token_ids.length<=192);
  assert.ok(Number.isInteger(trace.emitted_tokens)&&trace.emitted_tokens>=0&&trace.emitted_tokens<=192);
  assert.equal(trace.requested_limit,192);assert.ok(['eos','token-limit'].includes(trace.stop_reason));
  assert.equal(trace.generated_token_ids.length,trace.emitted_tokens+(trace.stop_reason==='eos'?1:0));
  if(trace.stop_reason==='token-limit')assert.equal(trace.emitted_tokens,192);
  const assembled=prefix+r.stdout;
  const record={...hashes,name:c.name,pair:c.pair,kind:opts.kind,mode:opts.mode,shard,cohort_cases:allCases.length,shard_cases:cases.length,model,source,expected_concern:c.expected_concern,expected_line_ids:c.expected_line_ids,expected_reason_concept:c.expected_reason_concept??null,expected_response:c.expected_response??null,audit_metadata:c.audit_metadata??null,prompt:c.prompt,prompt_sha256:sha(c.prompt),supplied_prompt_sha256:sha(supplied),supplied_prefix:prefix,supplied_prefix_ids:prefix?PREFIX_IDS:[],original_prompt_ids:originalIds,chunk:c.chunk,decoding:{temperature:0,continuation_tokens:192,context:c.context,threads:2,NT_NO_I8:'1'},continuation:r.stdout,assembled_response:assembled,trace,trace_file:traceFile,trace_sha256:sha(traceText),actual_first_token_id:trace.generated_token_ids[0],stop_reason:trace.stop_reason,assessment:assess(assembled,c.chunk),returncode:r.status,elapsed_ms:Date.now()-started,stderr:r.stderr};
  await output.write(JSON.stringify(record)+'\n');await output.sync();
  process.stdout.write(JSON.stringify({name:c.name,kind:opts.kind,mode:opts.mode,first_id:record.actual_first_token_id,stop:trace.stop_reason})+'\n');
 }
 assert.equal(await fileHash(model),hashes.model_sha256);assert.equal(await fileHash(runner),hashes.runner_sha256);assert.equal(await fileHash(path.join(ROOT,'src/infer.c')),hashes.infer_source_sha256);
}finally{await output.close();}
