#!/usr/bin/env python3
"""Bind the native depth survey and its durable execution order before launch."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess

REPO = Path(__file__).resolve().parents[2]


def binding(path):
    path = Path(path)
    before = path.stat()
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise RuntimeError('file changed while binding')
    return {'path': str(path.relative_to(REPO)), 'bytes': after.st_size, 'sha256': h.hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    prepared = args.prepared.resolve()
    import prepare_layers
    prepare_layers.read_rows(prepared)
    views = prepare_layers.views()
    paths = [
        'Makefile', 'training/train_mlp.c', 'training/extract_readout.c',
        'training/extract_layers.c', 'training/readout_fit.c',
        'training/durable_archive.py', 'training/layers/run_layers.py',
        'training/layers/freeze_layers.py', 'training/layers/prepare_layers.py',
        'training/layers/protocol_template.json', 'training/sft_review_v5.jsonl',
        'test/durable_archive.test.mjs', 'test/durable_archive_fixture.py', 'test/layer_extract.c',
        'build/jovovich-extract-layers', 'build/jovovich-readout-fit',
        'deps/notorch/notorch.c', 'deps/notorch/notorch.h',
        'deps/notorch/notorch_simd.h', 'deps/notorch/gguf.c', 'deps/notorch/gguf.h',
        'deps/notorch/harness/arch_llama.c', 'deps/notorch/harness/runtime.c',
        'deps/notorch/harness/runtime.h', 'deps/notorch/harness/arch.h',
        'deps/notorch/harness/arch_models.h', 'deps/notorch/examples/bpe.c',
        'deps/notorch/examples/bpe.h', 'deps/notorch/examples/unicode_numbers.h',
    ]
    bound = [{**binding(REPO / p), 'snapshot': 'snapshot/' + p} for p in paths]
    base = binding(REPO / 'models/base-qwen.gguf')
    if base['sha256'] != 'e1a77721fa97d412f121878223eec81fb4ae6f271e18f922d746711f67b344d1':
        raise RuntimeError('wrong base model')
    bound.append(base)
    bootstrap = []
    for p in sorted(prepared.iterdir()):
        if not p.is_file():
            raise RuntimeError('unexpected prepared entry')
        b = binding(p)
        bootstrap.append({'source': b['path'], 'path': p.name,
                          'sha256': b['sha256'], 'bytes': b['bytes']})
    evidence = [
        'training/results/2026-10-02-layer-readout/preflight-audit.json',
        'training/results/2026-10-02-layer-readout/binder-audit.json',
        'training/results/2026-10-02-layer-readout/tests.json',
        'training/results/2026-10-02-layer-readout/tests.stdout.txt',
        'training/results/2026-10-02-layer-readout/tests.stderr.txt',
        'training/results/2026-10-02-layer-readout/helper-validation.json',
        'training/results/2026-10-02-layer-readout/check_layer_helpers.executed.py',
        'training/results/2026-10-02-durable-sync/live_smoke.py',
        'training/results/2026-10-02-durable-sync/live-smoke-protocol.json',
        'training/results/2026-10-02-durable-sync/live-smoke-receipt.json',
        'training/results/2026-10-02-durable-sync/tests-final.stdout.txt',
        'training/results/2026-10-02-durable-sync/tests-final.stderr.txt',
    ]
    for p in evidence:
        b = binding(REPO / p)
        bootstrap.append({'source': p, 'path': 'evidence/' + Path(p).name,
                          'sha256': b['sha256'], 'bytes': b['bytes']})
    phases = []
    for i in range(52):
        name = f'row-{i:03d}'
        argv = ['build/jovovich-extract-layers', 'models/base-qwen.gguf',
                '@RUN@/layers-input.bin', f'@RUN@/rows/{name}.bin', str(i), '4',
                '--anchor', f'@RUN@/rows/{name}.z.bin']
        if i < 2:
            argv.append('--verify')
        phases.append({'id': name, 'argv': argv,
                       'stdout': f'rows/{name}.trace.jsonl',
                       'outputs': [f'rows/{name}.bin', f'rows/{name}.z.bin'],
                       'check_argv': ['python3', 'training/layers/prepare_layers.py',
                                      'validate-row', '--out', '@RUN@', '--row-dir',
                                      '@RUN@/rows', '--index', str(i), '--trace',
                                      f'@RUN@/rows/{name}.trace.jsonl']})
    phases.append({'id': 'assemble',
                   'argv': ['python3', 'training/layers/prepare_layers.py', 'assemble',
                            '--out', '@RUN@', '--row-dir', '@RUN@/rows'],
                   'outputs': [v['name'] + '.bin' for v in views] + ['layers-assembly.json']})
    for view in views:
        name = view['name']
        metadata = 'nuisance-metadata.txt' if name == 'nuisance' else 'layers-metadata.txt'
        phases.append({'id': 'fit-' + name,
                       'argv': ['build/jovovich-readout-fit', '--matrix', '@RUN@/' + name + '.bin',
                                '--metadata', '@RUN@/' + metadata, '--masks', '@RUN@/layers-masks.txt',
                                '--output', '@RUN@/fits/' + name + '.fits.jsonl',
                                '--normalization', view['normalization'], '--lambda', '0.01',
                                '--interpolation-lambda', '1e-8', '--gradient-tolerance', '1e-8',
                                '--max-iterations', '100'],
                       'outputs': ['fits/' + name + '.fits.jsonl']})
    phases.append({'id': 'summarize',
                   'argv': ['python3', 'training/layers/prepare_layers.py', 'summarize',
                            '--out', '@RUN@', '--fit-dir', '@RUN@/fits'],
                   'outputs': ['layers-summary.json', 'layers-table.tsv']})
    plan = {'schema_version': 1, 'run_id': args.run_id,
            'frozen_utc': datetime.now(timezone.utc).isoformat(),
            'model_forward_calls_before_freeze': 0,
            'repository_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
            'notorch_commit': subprocess.check_output(['git', '-C', 'deps/notorch', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
            'host': {'platform': platform.platform(), 'python': platform.python_version(),
                     'compiler': subprocess.check_output(['cc', '--version'], text=True).splitlines()[0]},
            'remote': {'repo': 'ataeff/jovovich', 'private': True, 'prefix': 'experiments/layer-readout',
                       'hub_client_version': '0.35.3', 'unit_order': 'bootstrap, then intent/result per phase, then completion'},
            'bindings': bound, 'bootstrap': bootstrap,
            'environment': {'NT_NO_I8': '1', 'NT_QMV_THREADS': '4', 'NT_ATTN_THREADS': '4',
                            'NT_SIMD_THREADS': '4', 'PYTHONDONTWRITEBYTECODE': '1'},
            'phases': phases}
    from run_layers import validate_plan
    validate_plan(plan)
    with args.output.open('x') as stream:
        json.dump(plan, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status': 'frozen', 'phases': len(phases),
                      'remote_units_if_complete': 2 + 2 * len(phases), 'plan': binding(args.output.resolve())}))


if __name__ == '__main__':
    main()
