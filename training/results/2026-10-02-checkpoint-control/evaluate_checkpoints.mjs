// One fixed arm; the Python controller permits at most two concurrent arms.
import assert from 'node:assert/strict';
import { createReadStream } from 'node:fs';
import { readFile, writeFile, mkdir, open, stat } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { assess } from '../2026-09-29-small-step/probe_shared_prefix.mjs';
const archive = 'training/results/2026-10-02-checkpoint-control';
const arm = process.argv[2];
assert.ok(['update25', 'update100'].includes(arm));
const hash = value => createHash('sha256').update(value).digest('hex');
async function fileHash(file) {
  const h = createHash('sha256');
  for await (const chunk of createReadStream(file)) h.update(chunk);
  return h.digest('hex');
}
const rawPlan = await readFile(`${archive}/protocol.json`), plan = JSON.parse(rawPlan);
const rawModels = await readFile(`${archive}/verified-models.json`), models = JSON.parse(rawModels);
const rawCases = await readFile(`${archive}/cases.jsonl`);
const cases = rawCases.toString().trim().split('\n').map(JSON.parse);
assert.equal(cases.length, 24);
assert.equal(hash(rawCases), plan.cases.sha256);
assert.equal(models.protocol_sha256, hash(rawPlan));
assert.equal(models.status, 'export_and_parity_passed');
const model = models.models[arm];
assert.equal(await fileHash(model.path), model.sha256);
const originalStat = await stat(model.path);
const frozenSources = plan.bindings.filter(b => !b.path.startsWith('models/'));
async function checkFrozen() {
  assert.equal(hash(await readFile(`${archive}/protocol.json`)), hash(rawPlan));
  assert.equal(hash(await readFile(`${archive}/verified-models.json`)), hash(rawModels));
  for (const binding of frozenSources) assert.equal(await fileHash(binding.path), binding.sha256, binding.path);
  const now = await stat(model.path);
  for (const key of ['dev','ino','size','mtimeMs','ctimeMs']) assert.equal(now[key], originalStat[key], `model ${key} changed`);
}
const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('NT_')));
Object.assign(env, plan.native_environment);
const outdir = `${archive}/${arm}`;
await mkdir(outdir, {recursive:false});
const output = await open(`${outdir}/responses.jsonl`, 'wx');
let done = 0;
try {
  for (const c of cases) {
    await checkFrozen();
    assert.equal(hash(c.prompt), c.prompt_sha256);
    const base = `${outdir}/${String(c.index).padStart(3,'0')}`;
    const args = ['--model', model.path, '--tokens','192','--context','8192','--temperature','0'];
    const opts = {cwd:process.cwd(),input:c.prompt,encoding:'utf8',env,timeout:600000,maxBuffer:8*1024*1024};
    const start = new Date().toISOString();
    await writeFile(`${base}.intent.json`, JSON.stringify({schema:1,arm,name:c.name,protocol_sha256:hash(rawPlan),model,
      prompt_sha256:c.prompt_sha256,runner:plan.runner.path,args,started_at:start},null,2)+'\n',{flag:'wx'});
    const encoded = spawnSync(plan.runner.path,[...args,'--token-ids'],opts);
    await writeFile(`${base}.tokenize.stdout.txt`, encoded.stdout ?? '', {flag:'wx'});
    await writeFile(`${base}.tokenize.stderr.txt`, encoded.stderr ?? '', {flag:'wx'});
    assert.equal(encoded.status,0,encoded.error?.message || encoded.stderr);
    assert.match(encoded.stdout.trim(),/^\d+(,\d+)*$/);
    const originalIds = encoded.stdout.trim().split(',').map(Number);
    const tracePath = `${base}.trace.json`;
    const r = spawnSync(plan.runner.path,[...args,'--trace-tokens',tracePath],opts);
    await writeFile(`${base}.stdout.txt`,r.stdout ?? '',{flag:'wx'});
    await writeFile(`${base}.stderr.txt`,r.stderr ?? '',{flag:'wx'});
    await writeFile(`${base}.process.json`,JSON.stringify({returncode:r.status,signal:r.signal,
      error:r.error ? {name:r.error.name,message:r.error.message,code:r.error.code} : null,
      finished_at:new Date().toISOString()},null,2)+'\n',{flag:'wx'});
    assert.equal(r.status,0,r.error?.message || r.stderr);
    const traceRaw = await readFile(tracePath), trace = JSON.parse(traceRaw);
    assert.equal(trace.schema_version,1);
    assert.deepEqual(trace.prompt_token_ids,originalIds);
    assert.equal(trace.requested_limit,192);
    assert.ok(['eos','token-limit'].includes(trace.stop_reason));
    assert.ok(trace.generated_token_ids.length > 0 && trace.generated_token_ids.length <=192);
    assert.ok(trace.generated_token_ids.every(id => Number.isInteger(id) && id >= 0));
    assert.equal(trace.generated_token_ids.length,trace.emitted_tokens+(trace.stop_reason==='eos'?1:0));
    if (trace.stop_reason==='token-limit') assert.equal(trace.emitted_tokens,192);
    const record = {...c,arm,model,protocol_sha256:hash(rawPlan),verified_models_sha256:hash(rawModels),
      mode:'natural',supplied_prefix:'',supplied_prefix_ids:[],original_prompt_ids:originalIds,
      decoding:plan.decoding,continuation:r.stdout,assembled_response:r.stdout,
      response_sha256:hash(r.stdout),trace,trace_file:tracePath,trace_sha256:hash(traceRaw),
      assessment:assess(r.stdout,c.chunk),started_at:start,finished_at:new Date().toISOString(),returncode:r.status,stderr:r.stderr};
    await output.write(JSON.stringify(record)+'\n'); await output.sync();
    done++;
    console.log(JSON.stringify({arm,done,total:24,name:c.name,stop:trace.stop_reason}));
  }
  await checkFrozen();
  assert.equal(await fileHash(model.path),model.sha256);
  await writeFile(`${outdir}/complete.json`,JSON.stringify({status:'complete',arm,cases:done,
    protocol_sha256:hash(rawPlan),verified_models_sha256:hash(rawModels),model,
    responses_sha256:await fileHash(`${outdir}/responses.jsonl`),frozen_sources_unchanged:true,
    model_sha256_unchanged:true,finished_at:new Date().toISOString()},null,2)+'\n',{flag:'wx'});
} catch (error) {
  await writeFile(`${outdir}/failure.json`,JSON.stringify({arm,completed_cases:done,error:{name:error.name,message:error.message,stack:error.stack},
    finished_at:new Date().toISOString()},null,2)+'\n',{flag:'wx'});
  throw error;
} finally { await output.close(); }
