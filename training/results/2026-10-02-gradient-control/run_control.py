#!/usr/bin/env python3
"""Freeze and run the bounded Qwen derivative control; orchestration only."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def now():
    return datetime.now(timezone.utc).isoformat()


def binding(path):
    path = path.resolve()
    first = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    last = path.stat()
    if (first.st_ino, first.st_size, first.st_mtime_ns, first.st_ctime_ns) != (
            last.st_ino, last.st_size, last.st_mtime_ns, last.st_ctime_ns):
        raise RuntimeError('file changed while hashing: ' + str(path))
    return {'path': str(path.relative_to(REPO)), 'sha256': digest.hexdigest(), 'bytes': last.st_size}


def save(path, value, exclusive=False):
    raw = json.dumps(value, indent=2, allow_nan=False) + '\n'
    if exclusive:
        with path.open('x') as stream:
            stream.write(raw)
    else:
        temporary = path.with_name(path.name + '.part')
        temporary.write_text(raw)
        temporary.replace(path)


def freeze():
    recovered = REPO / 'models/recovered-matched'
    binary = REPO / 'build/jovovich-probe-gradients'
    base = REPO / 'models/base-qwen.gguf'
    data = recovered / 'matched-review.bin'
    pairs = recovered / 'matched-review.pairs'
    suffixes = ('gate', 'up', 'down')
    sources = ['training/probe_gradients.c', 'training/train_mlp.c', 'Makefile',
               'deps/notorch/notorch.c', 'deps/notorch/notorch.h', 'deps/notorch/notorch_simd.h',
               'deps/notorch/gguf.c', 'deps/notorch/gguf.h', 'deps/notorch/harness/arch_llama.c',
               'deps/notorch/harness/runtime.c', 'deps/notorch/harness/runtime.h',
               'deps/notorch/harness/arch.h', 'deps/notorch/harness/arch_models.h',
               'deps/notorch/examples/bpe.c', 'deps/notorch/examples/bpe.h',
               'deps/notorch/examples/unicode_numbers.h']
    paths = [REPO / p for p in sources] + [Path(__file__), binary, base, data, pairs]
    paths += [recovered / f'matched-review.epoch{step}.{part}.lora'
              for step in (25, 100) for part in suffixes]
    bindings = [binding(p) for p in paths]
    if binding(base)['sha256'] != 'e1a77721fa97d412f121878223eec81fb4ae6f271e18f922d746711f67b344d1':
        raise RuntimeError('wrong public base')
    states = []
    for name in ('initial', 'epoch25', 'epoch100'):
        prefix = 'initial' if name == 'initial' else str(recovered / ('matched-review.' + name))
        states.append({'name': name, 'argv': [str(binary), str(base), str(data), str(pairs), prefix, '38', '39']})
    protocol = {
        'schema_version': 1, 'frozen_utc': now(), 'model_calls_before_freeze': 0,
        'question': 'Do native adapter derivatives agree with an independent smooth F64 suffix oracle on four real cached Qwen targets?',
        'states': states, 'bindings': bindings,
        'sample': {'dataset_rows': [38, 39], 'targets': ['row38 decision', 'row39 decision', 'row38 EOS', 'row39 first prefix token'],
                   'weights': 'Original full-corpus coefficient: 1/52 decision, 1/1012 residual; no rescaling.'},
        'directions': ['largest-absolute-analytic-gradient coordinate per tensor', 'unit Rademacher vector per tensor, xorshift32 seed 20261002+tensor_index'],
        'epsilons': [.01, .003, .001, .0003],
        'gates': {'gradient': 'Every direction must agree and be stable at both smallest adjacent eps; abs<=2e-7+0.01*max(abs(analytic),abs(numeric)).',
                  'active_coverage': 'Each nonzero-expected tensor needs at least one agreeing direction with analytic and numeric magnitude>=2e-5. Matching weaker directions are inconclusive.',
                  'initial_A': 'All A gradients and finest two numerical derivatives must be exactly zero when B=0.',
                  'baseline_per_target': 'max logit abs<=1e-3, logit relative L2<=1e-5, CE abs<=1e-4.',
                  'weighted_loss': 'abs production loss minus oracle<=1e-4*sum(target coefficients)+1e-7.',
                  'unchanged': 'Native parameter/cache byte guard and unchanged SHA256 input/source bindings.'},
        'limits': ['F64 oracle differentiates the smooth mathematical suffix using stored F32 values, not the rounded F32 program.',
                   'Four sampled contributions do not constitute the full 1064-target gradient.',
                   'Frozen attention and preceding blocks, clean EOS, and semantic reason tokens are not tested.',
                   'No optimizer update, training, checkpoint selection or runtime promotion.'],
        'environment': {'NT_NO_I8': '1', 'NT_QMV_THREADS': '4', 'NT_ATTN_THREADS': '4'},
        'host': {'system': platform.platform(), 'compiler': subprocess.check_output(['cc', '--version'], text=True).splitlines()[0]},
        'notorch_pin': subprocess.check_output(['git', '-C', str(REPO / 'deps/notorch'), 'rev-parse', 'HEAD'], text=True).strip(),
    }
    save(HERE / 'protocol.json', protocol, exclusive=True)
    print(json.dumps({'status': 'frozen', 'protocol': binding(HERE / 'protocol.json')}))


def run():
    protocol = json.loads((HERE / 'protocol.json').read_text())
    receipt = {'schema_version': 1, 'started_utc': now(), 'status': 'running',
               'protocol': binding(HERE / 'protocol.json'), 'phases': []}
    destination = HERE / 'run-receipt.json'
    save(destination, receipt, exclusive=True)
    try:
        for item in protocol['bindings']:
            if binding(REPO / item['path']) != item:
                raise RuntimeError('pre-run binding changed: ' + item['path'])
        env = {k: v for k, v in os.environ.items() if not k.startswith('NT_')}
        env.update(protocol['environment'])
        for state in protocol['states']:
            stdout = HERE / (state['name'] + '.jsonl')
            stderr = HERE / (state['name'] + '.stderr')
            phase = {'name': state['name'], 'argv': state['argv'], 'started_utc': now(),
                     'exit_code': None, 'stdout': None, 'stderr': None}
            receipt['phases'].append(phase)
            save(destination, receipt)
            started = time.monotonic()
            try:
                with stdout.open('xb') as out, stderr.open('xb') as err:
                    child = subprocess.Popen(state['argv'], cwd=REPO, env=env, stdout=out, stderr=err)
                    phase['pid'] = child.pid
                    save(destination, receipt)
                    phase['exit_code'] = child.wait()
            except BaseException as error:
                phase['exception'] = type(error).__name__ + ': ' + str(error)
                raise
            finally:
                phase['elapsed_seconds'] = time.monotonic() - started
                phase['ended_utc'] = now()
                for key, path in (('stdout', stdout), ('stderr', stderr)):
                    if path.is_file():
                        phase[key] = binding(path)
                save(destination, receipt)
            records = [json.loads(line) for line in stdout.read_text().splitlines()]
            summary = [row for row in records if row.get('kind') == 'summary']
            if len(summary) != 1 or phase['exit_code'] not in (0, 1):
                raise RuntimeError('incomplete native gradient result: ' + state['name'])
            phase['summary'] = summary[0]
            print(json.dumps({'phase': state['name'], 'exit_code': phase['exit_code'], 'summary': summary[0]}), flush=True)
            save(destination, receipt)
        for item in protocol['bindings']:
            if binding(REPO / item['path']) != item:
                raise RuntimeError('post-run binding changed: ' + item['path'])
        receipt['bindings_unchanged'] = True
        receipt['status'] = 'passed' if all(p['exit_code'] == 0 and p['summary']['pass'] for p in receipt['phases']) else 'numerical_gate_failed'
    except BaseException as error:
        receipt['status'] = 'execution_failed'
        receipt['exception'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        receipt['ended_utc'] = now()
        save(destination, receipt)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['freeze', 'run'])
    args = parser.parse_args()
    freeze() if args.mode == 'freeze' else run()
