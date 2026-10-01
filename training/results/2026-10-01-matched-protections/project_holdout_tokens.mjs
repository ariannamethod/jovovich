#!/usr/bin/env node
// Evaluation-only SFT-shaped prompt projection for native tokenizer auditing.
import { readFile, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
const [repoArg, outputArg] = process.argv.slice(2);
if (!repoArg || !outputArg || process.argv.length !== 4) throw new Error('Usage: node project_holdout_tokens.mjs REPO NEW_OUTPUT.jsonl');
const repo = resolve(repoArg), output = resolve(outputArg);
const { buildHoldoutV5 } = await import(pathToFileURL(join(repo, 'training/build_holdout_v5.mjs')));
const built = await buildHoldoutV5(repo);
const fixture = await readFile(join(repo, 'training/review_holdout_v5.jsonl'), 'utf8');
if (fixture !== built.data) throw new Error('Committed held-out fixture differs from builder projection');
const data = built.sftRows.map(row => JSON.stringify(row)).join('\n') + '\n';
await writeFile(output, data, { flag: 'wx' });
console.log(JSON.stringify({ output, bytes: Buffer.byteLength(data), rows: built.sftRows.length, sha256: createHash('sha256').update(data).digest('hex'), fixture_sha256: built.sha256, purpose: 'tokenizer-only evaluation prompt serialization; not training input' }));
