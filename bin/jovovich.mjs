#!/usr/bin/env node
import { readFile, writeFile, mkdir, rename, stat, rm } from 'node:fs/promises';
import { createReadStream, createWriteStream } from 'node:fs';
import { createHash } from 'node:crypto';
import { spawn, execFileSync } from 'node:child_process';
import { pipeline } from 'node:stream/promises';
import { Readable } from 'node:stream';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const MARKER = '<!-- jovovich:advisory:v1 -->';
const API = 'https://api.github.com';
export const modelPath = () => path.resolve(process.env.JOVOVICH_MODEL || path.join(ROOT, 'models/jovovich.gguf'));
const limit = (s, n) => s.length > n ? s.slice(0, n) + '\n[context excerpt ends]' : s;
const literal = s => s.replaceAll('<|', '\\u003c|').replaceAll('|>', '|\\u003e');
const quoteMarkdown = s => s.replaceAll('`', '\\`').replaceAll('@', '@\u200b').replaceAll('<', '&lt;');
const agentsFor = file => {
  const dirs = file.split('/').slice(0, -1);
  return ['AGENTS.md', ...dirs.map((_, i) => `${dirs.slice(0, i + 1).join('/')}/AGENTS.md`)];
};
function rulePaths(files) {
  for (const file of files) file.agent_paths = agentsFor(file.path);
  return [...new Set(['AGENTS.md', 'README.md', ...files.flatMap(f => f.agent_paths)])];
}

export function parsePatch(patch) {
  let left = 0, right = 0, inHunk = false;
  const lines = [];
  for (const text of patch.split('\n')) {
    const h = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(text);
    if (h) { left = +h[1]; right = +h[2]; inHunk = true; continue; }
    if (!inHunk) continue;
    if (text[0] === '+') lines.push({ side: 'RIGHT', line: right++, quote: text.slice(1) });
    else if (text[0] === '-') lines.push({ side: 'LEFT', line: left++, quote: text.slice(1) });
    else if (text[0] === ' ') { left++; right++; }
  }
  return lines;
}

// Hunk boundaries survive chunking; every cited location is checked against these lines.
export function chunksFor(files, maxChars = 4500) {
  const chunks = [];
  for (const f of files) {
    if (!f.patch) continue;
    const lines = parsePatch(f.patch);
    let group = [], size = 0;
    for (const line of lines) {
      const cost = line.quote.length + 32;
      if (group.length && size + cost > maxChars) { chunks.push({ path: f.path, agent_paths: f.agent_paths, lines: group, surrounding_diff: limit(f.patch, 1800) }); group = []; size = 0; }
      if (cost > maxChars) throw new Error(`Changed line too large to review faithfully: ${f.path}:${line.line}`);
      group.push(line); size += cost;
    }
    if (group.length) chunks.push({ path: f.path, agent_paths: f.agent_paths, lines: group, surrounding_diff: limit(f.patch, 1800) });
  }
  return chunks;
}

export function parseReview(text, chunk) {
  const clean = text.trim().replace(/(?:<\|im_end\|>|<\|endoftext\|>)+\s*$/, '').trim().replace(/^```(?:json)?\s*/, '').replace(/\s*```$/, '');
  let obj;
  try { obj = JSON.parse(clean); } catch { throw new Error('Model did not return a complete JSON review'); }
  if (Array.isArray(obj)) obj = { findings: obj };
  if (!obj || !Array.isArray(obj.findings)) throw new Error('Model review schema mismatch');
  if (obj.findings.length > 8) throw new Error('Model review exceeds output limits');
  const findings = [];
  for (const f of obj.findings) {
    const id = typeof f.line_id === 'string' && /^[1-9][0-9]*$/.test(f.line_id) ? Number(f.line_id) : f.line_id;
    if (!Number.isInteger(id) || id < 1 || id > chunk.lines.length || typeof f.reason !== 'string' || !f.reason.trim() || f.reason.length > 1500) {
      throw new Error('Model finding lacks an exact changed-line citation');
    }
    findings.push({ path: chunk.path, ...chunk.lines[id - 1], reason: f.reason.trim() });
  }
  return { findings };
}

export async function promptFor(chunk, context, identity, template = process.env.JOVOVICH_CHAT_TEMPLATE || 'chatml') {
  if (!['chatml', 'qwen3-no-think'].includes(template)) throw new Error(`Unknown chat template: ${template}`);
  const lines = chunk.lines.map((l, i) => `[${i + 1}] ${l.side === 'LEFT' ? 'REMOVED' : 'ADDED'} ${chunk.path}:${l.line}: ${l.quote}`).join('\n');
  const stored = context.rules || {};
  const applicable = (chunk.agent_paths || agentsFor(chunk.path)).filter(name => Object.hasOwn(stored, name));
  const rules = [
    ...(Object.hasOwn(stored, 'README.md') ? [`README.md (repository-wide context):\n${limit(stored['README.md'], 1500)}`] : []),
    ...applicable.map(name => `${name}:\n${limit(stored[name], 4000)}`)
  ].join('\n');
  const task = `Repository: ${context.repository || ''}\nPurpose: ${context.title || context.commit || ''}\n${context.description || ''}\nRepository rules for ${chunk.path}:\nAGENTS.md rules below are ordered root to nearest directory. Where they conflict, the closest scope wins.\n${rules}\n\nSurrounding diff:\n${chunk.surrounding_diff || ''}\n\nChanged lines to review:\n${lines}\n\nReview the changed lines against these rules. Return only a JSON object with findings. Each finding uses line_id (the bracketed number) and reason (explain the concrete conflict). If clean, return an empty findings list. At most two findings.`;
  // Qwen3's embedded enable_thinking=false template completes an empty thinking
  // block before generation. Select it explicitly; Qwen2 keeps plain ChatML.
  const suffix = template === 'qwen3-no-think' ? '<think>\n\n</think>\n\n' : '';
  return `<|im_start|>system\n${identity.trim()}<|im_end|>\n<|im_start|>user\n${literal(task)}<|im_end|>\n<|im_start|>assistant\n${suffix}`;
}

export function infer(prompt, tokens = 512) {
  return new Promise((resolve, reject) => {
    const exe = process.env.JOVOVICH_INFER || path.join(ROOT, 'build/jovovich-infer');
    const child = spawn(exe, ['--model', modelPath(), '--tokens', String(tokens), '--context', '8192', '--temperature', '0'], { stdio: ['pipe', 'pipe', 'pipe'] });
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    let out = '', err = '';
    const timer = setTimeout(() => child.kill('SIGTERM'), 600_000);
    child.stdout.on('data', b => { out += b; if (out.length > 65536) child.kill('SIGTERM'); });
    child.stderr.on('data', b => { err = (err + b).slice(-4000); });
    child.on('error', e => { clearTimeout(timer); reject(e); });
    child.on('close', code => { clearTimeout(timer); code === 0 ? resolve(out) : reject(new Error(`notorch inference failed (${code}): ${err}`)); });
    child.stdin.on('error', () => {});
    child.stdin.end(prompt);
  });
}

export async function review(input, runner = infer) {
  const identity = await readFile(path.join(ROOT, 'prompts/identity.txt'), 'utf8');
  const chunks = chunksFor(input.files);
  if (chunks.length > 24) throw new Error(`Change needs ${chunks.length} review chunks; narrow the diff (limit 24)`);
  const result = { ...input, reviews: [], failures: [], chunks: chunks.length };
  for (let i = 0; i < chunks.length; i++) {
    process.stderr.write(`JOVOVICH reviews ${chunks[i].path} (${i + 1}/${chunks.length})\n`);
    try {
      const raw = await runner(await promptFor(chunks[i], input.context, identity));
      result.reviews.push(parseReview(raw, chunks[i]));
    } catch (e) { result.failures.push(`${chunks[i].path}: ${e.message}`); }
  }
  return result;
}

export function render(result, lock) {
  const findings = result.reviews.flatMap(r => r.findings);
  const body = [MARKER, '## JOVOVICH', '*Juror Of Versioned Ontology, Vigilance, Integrity, Code & Heresy*', '', `Commit: \`${result.head}\` · ${result.reviews.length}/${result.chunks} chunks reviewed · ${lock.stage} weights`, '', '**JOVOVICH reviews. JOVOVICH does not rule.**', ''];
  if (findings.length) for (const f of findings) body.push(`- **${quoteMarkdown(f.path)}:${f.line} (${f.side})** — ${quoteMarkdown(f.reason)}\n  \`${quoteMarkdown(f.quote)}\``);
  else if (result.chunks && !result.failures.length) body.push('No grounded concerns returned for the reviewed changed lines.');
  else body.push('Review incomplete. No verdict on this change.');
  const unavailable = result.files.filter(f => !f.patch).map(f => f.path);
  if (unavailable.length) body.push('', `Files without a textual patch: ${unavailable.map(quoteMarkdown).join(', ')}.`);
  if (result.failures.length) body.push('', '**Incomplete chunks:**', ...result.failures.map(s => `- ${quoteMarkdown(s)}`));
  body.push('', '_Freckles checked. Merge button untouched._');
  return body.join('\n');
}

export function dispatch(reviewBody) {
  return { calls: [{ name: 'comment_review', arguments: { body: reviewBody } }], status: 'call' };
}

export async function githubRequest(route, { method = 'GET', body, accept } = {}) {
  const token = process.env.GITHUB_TOKEN;
  if (!token) throw new Error('GITHUB_TOKEN is required for GitHub review');
  const response = await fetch(API + route, {
    method, headers: { Authorization: `Bearer ${token}`, Accept: accept || 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(30_000)
  });
  if (!response.ok) throw new Error(`GitHub ${method} ${route}: HTTP ${response.status}`);
  return response.json();
}

export async function collectGithub(repo, pr, api = githubRequest) {
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo) || !Number.isSafeInteger(pr) || pr < 1) throw new Error('Expected --repo owner/name --pr positive-number');
  const route = `/repos/${repo}`;
  const info = await api(`${route}/pulls/${pr}`);
  if (info.state !== 'open') throw new Error('PR is not open');
  const files = [];
  for (let page = 1; page <= 30; page++) {
    const batch = await api(`${route}/pulls/${pr}/files?per_page=100&page=${page}`);
    files.push(...batch.map(f => {
      let patch = f.patch || '';
      if (patch && Number.isInteger(f.additions) && Number.isInteger(f.deletions)) {
        const changed = parsePatch(patch);
        if (changed.filter(l => l.side === 'RIGHT').length !== f.additions || changed.filter(l => l.side === 'LEFT').length !== f.deletions) patch = '';
      }
      return { path: f.filename, patch, status: f.status };
    }));
    if (batch.length < 100) break;
  }
  if (files.length !== info.changed_files) throw new Error('GitHub file listing is incomplete');
  const context = { repository: repo, title: limit(info.title, 300), description: limit(info.body || '', 1200), rules: {} };
  for (const file of rulePaths(files)) {
    try {
      const encoded = file.split('/').map(encodeURIComponent).join('/');
      const data = await api(`${route}/contents/${encoded}?ref=${encodeURIComponent(info.base.sha)}`);
      if (data.type === 'file' && !data.submodule_git_url && !data.target && data.encoding === 'base64') {
        context.rules[file] = limit(Buffer.from(data.content, 'base64').toString('utf8'), file === 'README.md' ? 1500 : 4000);
      }
    } catch (e) { if (!e.message.endsWith('HTTP 404')) throw e; }
  }
  const current = await api(`${route}/pulls/${pr}`);
  if (current.head.sha !== info.head.sha || current.base.sha !== info.base.sha) throw new Error('PR changed while collecting context; rerun');
  return { head: info.head.sha, base: info.base.sha, context, files };
}

export async function postGithub(repo, pr, input, body, api = githubRequest) {
  const current = await api(`/repos/${repo}/pulls/${pr}`);
  if (current.state !== 'open' || current.head.sha !== input.head || current.base.sha !== input.base) throw new Error('PR changed during review; comment not published');
  const envelope = dispatch(body);
  const call = envelope.calls[0];
  if (call.name !== 'comment_review') throw new Error('Unsupported action');
  // Commit-labelled comments remain truthful even if a push races this API call.
  return api(`/repos/${repo}/issues/${pr}/comments`, { method: 'POST', body: { body: call.arguments.body } });
}

export function collectLocal(repo, base = 'HEAD~1', head = 'HEAD') {
  const git = args => execFileSync('git', ['-C', repo, ...args], { encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 });
  const resolve = ref => git(['rev-parse', '--verify', '--end-of-options', `${ref}^{commit}`]).trim();
  const a = resolve(base), b = resolve(head);
  const names = git(['diff', '--no-ext-diff', '--no-textconv', '--no-renames', '--name-only', '-z', a, b, '--']).split('\0').filter(Boolean);
  const files = names.map(name => ({ path: name, patch: git(['diff', '--no-ext-diff', '--no-textconv', '--no-renames', '--unified=3', a, b, '--', name]) }));
  const context = { repository: path.basename(path.resolve(repo)), commit: limit(git(['log', '-1', '--format=%B', b, '--']), 1200), rules: {} };
  for (const file of rulePaths(files)) {
    const entry = git(['ls-tree', '-z', a, '--', `:(literal)${file}`]);
    if (!/^100(?:644|755) blob [a-f0-9]+\t/.test(entry)) continue;
    context.rules[file] = limit(git(['show', `${a}:${file}`]), file === 'README.md' ? 1500 : 4000);
  }
  return { head: b, base: a, files, context };
}

async function digest(file) {
  const hash = createHash('sha256');
  for await (const b of createReadStream(file)) hash.update(b);
  return hash.digest('hex');
}

export async function fetchModel() {
  const lock = JSON.parse(await readFile(path.join(ROOT, 'model.json'), 'utf8'));
  const dest = modelPath();
  try {
    if ((await stat(dest)).size === lock.bytes && await digest(dest) === lock.sha256) { process.stderr.write('Model checksum matches.\n'); return; }
  } catch (e) { if (e.code !== 'ENOENT') throw e; }
  const url = `https://huggingface.co/${lock.repo}/resolve/${lock.revision}/${lock.file}`;
  const headers = process.env.HF_TOKEN ? { Authorization: `Bearer ${process.env.HF_TOKEN}` } : {};
  const response = await fetch(url, { headers, signal: AbortSignal.timeout(600_000) });
  if (!response.ok) throw new Error(`Model download: HTTP ${response.status}`);
  await mkdir(path.dirname(dest), { recursive: true });
  const temp = `${dest}.${process.pid}.part`;
  try {
    await pipeline(Readable.fromWeb(response.body), createWriteStream(temp, { flags: 'wx', mode: 0o600 }));
    if ((await stat(temp)).size !== lock.bytes || await digest(temp) !== lock.sha256) throw new Error('Model checksum mismatch');
    await rename(temp, dest);
  } finally { await rm(temp, { force: true }); }
  process.stderr.write(`Model downloaded: ${lock.name} (${lock.stage}).\n`);
}

async function main() {
  const [command, ...args] = process.argv.slice(2);
  const opts = {};
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--post') opts.post = true;
    else if (['--repo', '--pr', '--base', '--head', '--output'].includes(args[i]) && args[i + 1]) { const key = args[i].slice(2); opts[key] = args[++i]; }
    else throw new Error(`Unknown or incomplete argument: ${args[i]}`);
  }
  if (command === 'fetch-model') return fetchModel();
  if (!['review', 'github'].includes(command)) {
    process.stdout.write('JOVOVICH reviews. JOVOVICH does not rule.\n\nnode bin/jovovich.mjs fetch-model\nnode bin/jovovich.mjs review --repo . --base HEAD~1 --head HEAD\nnode bin/jovovich.mjs github --repo owner/repo --pr 1 [--post]\n');
    if (command && command !== '--help') process.exitCode = 1;
    return;
  }
  const input = command === 'github' ? await collectGithub(opts.repo || '', Number(opts.pr)) : collectLocal(opts.repo || '.', opts.base, opts.head);
  const result = await review(input);
  const lock = JSON.parse(await readFile(path.join(ROOT, 'model.json'), 'utf8'));
  const body = render(result, modelPath() === path.join(ROOT, 'models/jovovich.gguf') ? lock : { stage: 'custom' });
  if (opts.output) await writeFile(opts.output, body + '\n'); else process.stdout.write(body + '\n');
  if (opts.post && command === 'github') {
    if (!result.reviews.length) throw new Error('No valid model review; nothing posted');
    const posted = await postGithub(opts.repo, Number(opts.pr), input, body);
    process.stderr.write(`JOVOVICH commented: ${posted.html_url}\n`);
  }
  if (result.failures.length) process.exitCode = 2;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(e => { process.stderr.write(`jovovich: ${e.message}\n`); process.exitCode = 1; });
}
