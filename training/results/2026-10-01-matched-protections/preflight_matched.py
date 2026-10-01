#!/usr/bin/env python3
"""Pack a new corpus and run the existing native token/objective preflight."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

def record(path):
    path = Path(path)
    raw = path.read_bytes()
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--repo', type=Path, required=True)
    p.add_argument('--corpus', type=Path, required=True)
    p.add_argument('--probe', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    root, corpus, probe, out = [v.resolve() for v in (a.repo, a.corpus, a.probe, a.out)]
    out.mkdir(parents=True, exist_ok=False)
    source_paths = [corpus, probe, Path(__file__).resolve(), root/'training/prepare.py',
                    root/'training/train_mlp.c', root/'src/infer.c', root/'models/base-qwen.gguf']
    bindings = [record(v) for v in source_paths]
    commands = [
        ['python3', str(root/'training/prepare.py'), str(out/'data.bin'), '--sft', str(corpus),
         '--sft-only', '--review-pairs', str(out/'pairs.bin')],
        [str(probe), str(root/'models/base-qwen.gguf'), str(out/'data.bin'), str(out/'pairs.bin'), '40']]
    receipt = {'status': 'running', 'bindings': bindings, 'phases': [], 'model_forward_calls': 0}
    try:
        for i, argv in enumerate(commands):
            start = time.monotonic()
            with (out/f'phase-{i}.stdout').open('x') as stdout, (out/f'phase-{i}.stderr').open('x') as stderr:
                result = subprocess.run(argv, cwd=root, stdout=stdout, stderr=stderr)
            receipt['phases'].append({'argv': argv, 'returncode': result.returncode,
                'elapsed_seconds': time.monotonic()-start,
                'stdout': record(out/f'phase-{i}.stdout'), 'stderr': record(out/f'phase-{i}.stderr')})
            if result.returncode:
                raise ValueError('native preflight phase failed')
            if [record(v['path']) for v in bindings] != bindings:
                raise ValueError('source changed during native preflight')
        summary = json.loads((out/'phase-1.stdout').read_text().splitlines()[-1])
        if summary['model_forward_calls'] != 0 or summary['pass'] is not True:
            raise ValueError('invalid native preflight summary')
        receipt.update(status='completed', summary=summary, sources_unchanged=True)
    except BaseException as exc:
        receipt.update(status='failed', failure_type=type(exc).__name__, failure=str(exc))
        raise
    finally:
        receipt['artifacts'] = [record(out/n) for n in ('data.bin','pairs.bin') if (out/n).exists()]
        with (out/'receipt.json').open('x') as f:
            json.dump(receipt, f, indent=2); f.write('\n')
    print(json.dumps({'receipt': str(out/'receipt.json'), 'summary': receipt['summary']}))

if __name__ == '__main__':
    main()
