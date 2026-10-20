"""Run pinned model candidates on the same fixtures using native chat templates."""
import argparse
import json
from pathlib import Path

from review import messages


def gguf_reviews(args, rows):
    import concurrent.futures
    import os
    import subprocess
    import tarfile
    import time
    import urllib.request
    from huggingface_hub import hf_hub_download
    root = Path('/tmp/jovovich-llama-b11669')
    root.mkdir(exist_ok=True)
    for prefix in ('llama', 'cudart-llama'):
        name = prefix + '-b11669-bin-ubuntu-cuda-12.8-x64.tar.gz'
        archive = root / name
        if not archive.exists():
            urllib.request.urlretrieve('https://github.com/ggml-org/llama.cpp/releases/download/b11669/' + name, archive)
            with tarfile.open(archive) as tar:
                tar.extractall(root, filter='data')
    binary = next(root.rglob('llama-server'))
    libs = {str(p.parent) for p in root.rglob('*.so*')}
    env = dict(os.environ, LD_LIBRARY_PATH=':'.join(sorted(libs)) + ':' + os.environ.get('LD_LIBRARY_PATH', ''))
    path = hf_hub_download(args.model, args.gguf_file, revision=args.revision)
    log = open(str(args.output) + '.server.log', 'w')
    server = subprocess.Popen([str(binary), '-m', path, '-ngl', '99',
        '--host', '127.0.0.1', '--port', '8081', '-c', '32768', '-np', '4', '--jinja'],
        env=env, stdout=log, stderr=log)
    def request(row):
        body = {'messages': row.get('prompt_messages') or messages(row['context']),
                'temperature': 0.6 if args.thinking else 0, 'top_p': 0.95,
                'top_k': 20, 'seed': 42, 'max_tokens': args.max_tokens,
                'chat_template_kwargs': {'enable_thinking': args.thinking}}
        req = urllib.request.Request('http://127.0.0.1:8081/v1/chat/completions',
            data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=300) as response:
            result = json.load(response)
        choice = result['choices'][0]
        answer = choice['message'].get('content') or ''
        reason = choice['message'].get('reasoning_content') or ''
        return {'id': row['id'], 'expected': row['expected'], 'review': answer.strip(),
                'raw_review': reason + '\n' + answer, 'complete': choice['finish_reason'] == 'stop',
                'finish_reason': choice['finish_reason'], 'model': args.model,
                'revision': args.revision, 'gguf_file': args.gguf_file,
                'thinking': args.thinking, 'backend': 'llama.cpp-b11669',
                'generated_tokens': result.get('usage', {}).get('completion_tokens')}
    try:
        ready = False
        for _ in range(120):
            if server.poll() is not None:
                raise RuntimeError('llama-server failed: ' + Path(log.name).read_text()[-2500:])
            try:
                with urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=1) as response:
                    ready = response.status == 200
            except OSError:
                pass
            if ready:
                break
            time.sleep(1)
        if not ready:
            raise TimeoutError('llama-server startup exceeded 120 seconds')
        with Path(args.output).open('w', buffering=1) as out, concurrent.futures.ThreadPoolExecutor(4) as pool:
            for result in pool.map(request, rows):
                line = json.dumps(result, ensure_ascii=False)
                out.write(line + '\n')
                print('JOVOVICH_REVIEW ' + line, flush=True)
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill(); server.wait()
        log.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model', required=True)
    p.add_argument('--revision', required=True)
    p.add_argument('--cases', nargs='+', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--thinking', action='store_true')
    p.add_argument('--max-tokens', type=int, default=4096)
    p.add_argument('--batch-size', type=int, default=64)
    p.add_argument('--gguf-file')
    args = p.parse_args()
    rows = [json.loads(line) for filename in args.cases
            for line in Path(filename).read_text().splitlines() if line.strip()]
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate fixture IDs')
    if args.gguf_file:
        gguf_reviews(args, rows)
        return
    from transformers import AutoConfig, AutoTokenizer
    from vllm import LLM, SamplingParams
    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.revision)
    config = AutoConfig.from_pretrained(args.model, revision=args.revision)
    kwargs = {}
    if config.model_type in ('qwen3_5', 'qwen3_5_moe'):
        kwargs['limit_mm_per_prompt'] = {'image': 0, 'video': 0}
    llm = LLM(model=args.model, revision=args.revision, dtype='bfloat16',
              max_model_len=12288, max_num_seqs=args.batch_size,
              gpu_memory_utilization=0.85, enforce_eager=True,
              enable_prefix_caching=False, **kwargs)
    sampling = SamplingParams(temperature=0.6 if args.thinking else 0,
                              top_p=0.95 if args.thinking else 1,
                              top_k=20 if args.thinking else -1,
                              max_tokens=args.max_tokens, seed=42)
    with Path(args.output).open('w', buffering=1) as out:
        for start in range(0, len(rows), args.batch_size):
            batch = rows[start:start + args.batch_size]
            prompts = [tokenizer.apply_chat_template(
                r.get('prompt_messages') or messages(r['context']), tokenize=False,
                add_generation_prompt=True, enable_thinking=args.thinking) for r in batch]
            results = llm.generate(prompts, sampling, use_tqdm=False)
            for row, result in zip(batch, results):
                completion = result.outputs[0]
                raw = completion.text
                answer = raw.split('</think>', 1)[-1].strip()
                complete = completion.finish_reason == 'stop' and (
                    not args.thinking or '</think>' in raw)
                if not complete:
                    answer = '[Incomplete generation] ' + answer
                record = {'id': row['id'], 'expected': row['expected'], 'review': answer,
                          'raw_review': raw, 'complete': complete,
                          'finish_reason': completion.finish_reason,
                          'generated_tokens': len(completion.token_ids),
                          'model': args.model, 'revision': args.revision,
                          'thinking': args.thinking, 'dtype': 'bfloat16'}
                line = json.dumps(record, ensure_ascii=False)
                out.write(line + '\n')
                print('JOVOVICH_REVIEW ' + line, flush=True)


if __name__ == '__main__':
    main()
