#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
const [repoArg, inputArg, auditArg] = process.argv.slice(2);
assert.ok(repoArg && inputArg && auditArg, 'Usage: node independent_holdout_projection_audit.mjs REPO PROJECTED_SFT NEW_AUDIT');
const repo = path.resolve(repoArg), input = path.resolve(inputArg), audit = path.resolve(auditArg);
const { chunksFor, promptFor } = await import(pathToFileURL(path.join(repo, 'bin/jovovich.mjs')));
const corpus = path.join(repo, 'training/review_holdout_v5.jsonl');
const identityFile = path.join(repo, 'prompts/identity.txt');
const rows = fs.readFileSync(corpus, 'utf8').trimEnd().split('\n').map(JSON.parse);
const projected = fs.readFileSync(input, 'utf8').trimEnd().split('\n').map(JSON.parse);
const identity = fs.readFileSync(identityFile, 'utf8');
assert.equal(rows.length, 24); assert.equal(projected.length, 24);
for (let i=0; i<rows.length; i++) {
  const row=rows[i], p=projected[i], chunks=chunksFor(row.files); assert.equal(chunks.length, 1);
  const prompt=await promptFor(chunks[0], row.context, identity, 'chatml');
  const expected=`<|im_start|>system\n${p.messages[0].content}<|im_end|>\n<|im_start|>user\n${p.messages[1].content}<|im_end|>\n<|im_start|>assistant\n`;
  assert.equal(prompt, expected); assert.equal(p.id, row.id); assert.equal(p.pair, row.pair);
  assert.equal(p.messages[2].content, JSON.stringify(row.gold));
  assert.ok(!prompt.includes(row.id) && !prompt.includes(row.pair) && !prompt.includes(row.expected_reason_concept));
}
const binding=file=>({path:file,bytes:fs.statSync(file).size,sha256:createHash('sha256').update(fs.readFileSync(file)).digest('hex')});
fs.writeFileSync(audit, JSON.stringify({schema_version:1,status:'PASS',rows:24,
  method:'Rebuild every canonical holdout row through production chunksFor and promptFor; compare the complete ChatML prompt byte-for-byte to the native-token SFT projection system/user fields. Confirm id/pair/gold correspondence and exclude expected reason/metadata from prompts.',
  bindings:[corpus,identityFile,path.join(repo,'bin/jovovich.mjs'),input].map(binding)}, null, 2)+'\n', {flag:'wx'});
console.log(JSON.stringify({status:'PASS',rows:24,audit}));
