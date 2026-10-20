#!/usr/bin/env python3
"""Archive the exported body, then preserve each native review as it closes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'training'), str(ROOT / 'training/explanations')]
from durable_archive import DurableArchive, HFTransport, sync_unit_with_retry
from collect_generation import review_cases, render_prompt, validate_trace
from score_generation import score_files


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def save(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', required=True, type=Path)
    p.add_argument('--infer', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--token-file', required=True, type=Path)
    p.add_argument('--run-id', required=True)
    p.add_argument('--branch', default='main')
    p.add_argument('--export-log', required=True, type=Path)
    p.add_argument('--parity-log', required=True, type=Path)
    a = p.parse_args()
    a.model, a.infer, a.output = (x.resolve() for x in (a.model, a.infer, a.output))
    a.output.mkdir(parents=True, exist_ok=False)
    archive = DurableArchive(HFTransport('ataeff/jovovich', a.token_file.read_text().strip(), a.branch),
                             a.run_id, prefix='training/full-lora-delivery')
    sequence = 0

    def sync(unit, files):
        nonlocal sequence
        receipt = sync_unit_with_retry(archive, unit, files, sequence=sequence,
                                      deadline=time.monotonic() + 1800)
        save(a.output / f'receipt-{sequence:03d}.json', receipt)
        sequence += 1
        print(json.dumps({'event': 'delivery_verified', 'unit': unit}), flush=True)

    corpus = ROOT / 'training/review_holdout_v5.jsonl'
    demo_corpus = ROOT / 'training/sft_review_v6_before.jsonl'
    corpus_hash = digest(corpus)
    manifest = dict(model_sha256=digest(a.model), model_bytes=a.model.stat().st_size,
                    infer_sha256=digest(a.infer), corpus_sha256=corpus_hash,
                    training_demo_corpus_sha256=digest(demo_corpus),
                    run_id=a.run_id, temperature=0, max_tokens=512,
                    prompt_policy='production ChatML plus the trained concise-analysis instruction')
    save(a.output / 'model.json', manifest)
    sync('model', {'jovovich.gguf': a.model, 'model.json': a.output / 'model.json',
                   'export.log': a.export_log, 'parity.log': a.parity_log,
                   'deliver.py': Path(__file__).resolve(), 'holdout.jsonl': corpus,
                   'training-demo-source.jsonl': demo_corpus})
    cases = review_cases(corpus.read_bytes(), split='holdout')
    env = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL') if k in os.environ}
    env.update(NT_NO_I8='1', NT_QMV_THREADS='4', NT_ATTN_THREADS='4',
               NT_SIMD_THREADS='4', OPENBLAS_NUM_THREADS='4')
    records = []

    def generate(case, index, split):
        directory = a.output / f'{split}-{index:03d}'
        directory.mkdir()
        prompt = directory / 'prompt.txt'
        prompt.write_bytes(case['prompt'])
        trace = directory / 'trace.json'
        command = [str(a.infer), '--model', str(a.model), '--tokens', '512',
                   '--context', '8192', '--temperature', '0', '--trace-tokens', str(trace)]
        started = time.monotonic()
        launch_error = None
        try:
            result = subprocess.run(command, input=case['prompt'], capture_output=True,
                                    env=env, timeout=600)
        except subprocess.TimeoutExpired as exc:
            result = subprocess.CompletedProcess(command, 124, exc.stdout or b'', exc.stderr or b'')
        except OSError as exc:
            # Preserve a closed error case even when exec itself fails; exception
            # text can contain private host paths, so record only its type.
            launch_error = type(exc).__name__
            result = subprocess.CompletedProcess(command, 127, b'',
                ('native process launch failed: ' + launch_error + '\n').encode('utf-8'))
        (directory / 'stdout.bin').write_bytes(result.stdout)
        (directory / 'stderr.bin').write_bytes(result.stderr)
        invalid_utf8 = False
        try:
            response = result.stdout.decode('utf-8')
        except UnicodeDecodeError:
            response, invalid_utf8 = result.stdout.decode('utf-8', errors='replace'), True
        try:
            token_trace = json.loads(trace.read_text())
            finish = validate_trace(token_trace) if result.returncode == 0 else 'error'
        except (OSError, ValueError):
            token_trace, finish = {}, 'error'
        if invalid_utf8:
            finish = 'error'
        record = dict(case_id=case['case_id'], corpus_sha256=case.get('corpus_sha256', corpus_hash),
                      raw_response=response, raw_response_sha256=hashlib.sha256(response.encode()).hexdigest(),
                      finish_reason=finish, metadata={'model_path': str(a.model),
                          'model_sha256': manifest['model_sha256'], 'prompt_sha256': digest(prompt),
                          'requested_limit': 512})
        if finish == 'error':
            record['error'] = 'native inference or trace validation failed'
        save(directory / 'execution.json', {'elapsed_seconds': time.monotonic()-started,
             'returncode': result.returncode, 'launch_error': launch_error,
             'split': split, 'environment': env})
        save(directory / 'record.json', record)
        sync(f'{split}-{index:03d}', {f'{split}-{index:03d}/{x.name}': x for x in directory.iterdir()})
        print(json.dumps({'event': 'review', **record}, ensure_ascii=False), flush=True)
        if finish == 'error':
            raise RuntimeError('native inference failed; closed evidence saved')
        return record

    for index, case in enumerate(cases):
        records.append(generate(case, index, 'holdout'))
    generations = a.output / 'generations.jsonl'
    with generations.open('x', encoding='utf-8') as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
    score = score_files(corpus, generations, 'before', 'holdout')
    save(a.output / 'score.json', score)
    sync('scores', {'generations.jsonl': generations, 'score.json': a.output / 'score.json'})
    print(json.dumps({'event': 'review_score', 'summary': score['summary']}, ensure_ascii=False), flush=True)
    # Explicitly labelled training examples demonstrate voice/code, not held-out accuracy.
    rows = [json.loads(x) for x in demo_corpus.read_text(encoding='utf-8').splitlines()]
    demonstrations = [r for kind in ('voice', 'code') for r in [x for x in rows if x['kind'] == kind][:2]]
    for index, row in enumerate(demonstrations):
        generate({'case_id': row['id'], 'prompt': render_prompt(row),
                  'corpus_sha256': manifest['training_demo_corpus_sha256']}, index, 'training-demonstration')
    save(a.output / 'completed.json', {'status': 'completed', 'heldout_cases': len(cases),
                                      'training_demonstrations': len(demonstrations), **manifest})
    sync('completed', {'completed.json': a.output / 'completed.json'})


if __name__ == '__main__':
    main()
