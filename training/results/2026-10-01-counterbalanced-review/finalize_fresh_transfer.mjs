#!/usr/bin/env node
// Verify prompt/corpus overlap and freeze inputs after an independent code audit.
import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const HERE=path.dirname(fileURLToPath(import.meta.url));
const ROOT=process.cwd();
const {chunksFor,promptFor,parseReview}=await import(pathToFileURL(path.join(ROOT,'bin/jovovich.mjs')));
const sha=x=>createHash('sha256').update(x).digest('hex');
const jsonl=t=>t.trim().split('\n').map(JSON.parse);
const fixturesText=await readFile(path.join(HERE,'fresh-transfer.jsonl'),'utf8');
const rows=jsonl(fixturesText);
const audit=JSON.parse(await readFile(path.join(HERE,'fresh-transfer-audit.json'),'utf8'));
assert.equal(audit.fixtures_sha256,sha(fixturesText));
const identity=await readFile(path.join(ROOT,'prompts/identity.txt'),'utf8');
const prepared=[];
for(const r of rows){
 const chunks=chunksFor(r.files);assert.equal(chunks.length,1);
 const chunk=chunks[0];assert.equal(chunk.surrounding_diff,r.files[0].patch);
 const prompt=await promptFor(chunk,r.context,identity,'chatml');
 const user=prompt.split('<|im_start|>user\n')[1].split('<|im_end|>')[0];
 assert.equal(chunk.lines[0].side,'LEFT');assert.equal(chunk.lines[0].line,r.audit_metadata.candidate_physical_line);
 assert.equal(chunk.lines.length,r.audit_metadata.shape==='pure-deletion'?1:2);
 assert.equal(parseReview(JSON.stringify(r.gold),chunk).findings.length,r.expected_concern?1:0);
 for(const id of r.expected_line_ids) assert.equal(parseReview(JSON.stringify({findings:[{line_id:id,reason:r.expected_reason_concept}]}),chunk).findings.length,1);
 prepared.push({r,chunk,prompt,user});
}
for(const p of prepared){
 const mate=prepared.find(q=>q.r.id===p.r.audit_metadata.semantic_counterpart);assert.ok(mate);
 assert.deepEqual(p.r.context,mate.r.context);assert.deepEqual(p.chunk.lines,mate.chunk.lines);
 const a=p.r.files[0].patch.split('\n'), b=mate.r.files[0].patch.split('\n');
 assert.equal(a[0],b[0]);assert.equal(a.length,b.length);
 const changed=a.map((l,i)=>l!==b[i]?i:null).filter(x=>x!==null);
 assert.equal(changed.length,1);assert.ok(a[changed[0]].startsWith(' ')&&b[changed[0]].startsWith(' '));
 for(const regex of [/\bif\b/g,/\.sort\(/g,/dawnline\/leaf-cache/g]) assert.equal((a.join('\n').match(regex)||[]).length,(b.join('\n').match(regex)||[]).length);
}
const sources=[
 'training/sft_review_v2.jsonl','training/sft_review_v3.jsonl','training/sft_review_v4.jsonl',
 'training/review_holdout_v2.jsonl',
 'training/results/2026-10-01-joint-review/diff-shape-audit.jsonl',
 'training/results/2026-10-01-joint-review/matched-shape-cases.jsonl'
];
const overlap=[];
for(const source of sources){
 const text=await readFile(path.join(ROOT,source),'utf8'), items=jsonl(text), corpus=[];
 for(const r of items){
  if(r.messages){
   if(r.kind!==undefined&&r.kind!=='review')continue;
   const user=r.messages.find(m=>m.role==='user').content;
   corpus.push({id:r.id,user,patch:user.split('Surrounding diff:\n')[1]?.split('\n\nChanged lines to review:')[0],quotes:[...user.matchAll(/^\[\d+\] (?:REMOVED|ADDED) .+?:\d+: (.*)$/gm)].map(m=>m[1])});
  }else if(r.files){
   const c=chunksFor(r.files);assert.equal(c.length,1);
   const prompt=await promptFor(c[0],r.context,identity,'chatml');
   corpus.push({id:r.id,user:prompt.split('<|im_start|>user\n')[1].split('<|im_end|>')[0],patch:r.files[0].patch,quotes:c[0].lines.map(l=>l.quote)});
  }else if(r.prompt){
   const user=r.prompt.split('<|im_start|>user\n')[1].split('<|im_end|>')[0];
   corpus.push({id:r.id??r.name,user,patch:user.split('Surrounding diff:\n')[1]?.split('\n\nChanged lines to review:')[0],quotes:r.chunk?.lines.map(l=>l.quote)??[]});
  }else throw new Error('Unknown overlap row in '+source);
 }
 const exactUser=[], exactPatch=[], pathReuse=[], repoReuse=[], sharedQuotes=new Set();
 for(const {r,user,chunk} of prepared){
  for(const c of corpus){
   if(user===c.user)exactUser.push([r.id,c.id]);
   if(r.files[0].patch===c.patch)exactPatch.push([r.id,c.id]);
   if(c.user.includes(r.files[0].path))pathReuse.push([r.id,c.id]);
   if(c.user.includes(r.context.repository))repoReuse.push([r.id,c.id]);
   for(const l of chunk.lines)if(c.quotes.some(q=>q.trim()===l.quote.trim()))sharedQuotes.add(l.quote.trim());
  }
 }
 assert.equal(exactUser.length,0);assert.equal(exactPatch.length,0);assert.equal(pathReuse.length,0);assert.equal(repoReuse.length,0);
 overlap.push({source,sha256:sha(text),rows:items.length,review_rows:corpus.length,exact_user_prompt_matches:exactUser,exact_patch_matches:exactPatch,reused_paths:pathReuse,reused_repositories:repoReuse,shared_changed_line_quotes:[...sharedQuotes].sort()});
}
audit.prompt_checks={host_sha256:sha(await readFile(path.join(ROOT,'bin/jovovich.mjs'))),identity_sha256:sha(identity),chat_template:'chatml',cases:prepared.map(p=>({id:p.r.id,prompt_sha256:sha(p.prompt),prompt_bytes:Buffer.byteLength(p.prompt),patch_characters:p.r.files[0].patch.length,candidate_physical_line:p.r.audit_metadata.candidate_physical_line,changed_line_count:p.chunk.lines.length,gold_parses:true,alternative_citations_parse:true})),all_patches_visible_without_truncation:true,semantic_pairs_same_changed_lines:true,semantic_pairs_equal_hunk_and_context_counts:true,semantic_pair_diff_exactly_one_unchanged_line:true,semantic_pairs_equal_if_sort_upstream_string_counts:true};
audit.overlap_report={sources:overlap,shared_structure:'Production identity, Qwen ChatML framing, review instruction and JSON output contract are shared intentionally. Six semantic families are shared by design; repository names, source paths, candidate code/credit, full patches and contextual mechanisms are fresh. Neutral C (void)0; and JS void 0; shape controls are intentionally reused.',variant_split:'Each four-case family is frozen together. No fixture enters training, checkpoint selection, or dataset revision during this run.'};
const independentPath=path.join(HERE,'fresh-transfer-independent-audit.json');
const independentText=await readFile(independentPath,'utf8');
const independent=JSON.parse(independentText);
assert.equal(independent.status,'pass');
assert.equal(independent.fixtures.sha256,sha(fixturesText),'Independent audit must bind current fixture bytes');
assert.equal(independent.reviewed_all_cases,24);
assert.deepEqual(independent.findings,[]);
assert.equal(independent.cases.length,24);
assert.ok(independent.cases.every(c=>c.semantic_label_correct&&c.hunk_counts_correct&&c.source_hashes_match&&c.context_and_changed_lines_balanced&&c.guard_sort_credit_counts_balanced));
audit.independent_audit={path:'fresh-transfer-independent-audit.json',sha256:sha(independentText),bytes:Buffer.byteLength(independentText)};
audit.status='frozen_before_new_model_outputs';
audit.frozen_at_utc=new Date().toISOString();
audit.no_model_inference=true;
audit.finalizer_sha256=sha(await readFile(fileURLToPath(import.meta.url)));
await writeFile(path.join(HERE,'fresh-transfer-audit.json'),JSON.stringify(audit,null,2)+'\n');
process.stdout.write(JSON.stringify({fixtures_sha256:sha(fixturesText),rows:rows.length,status:audit.status,overlap_sources:overlap.length})+'\n');
