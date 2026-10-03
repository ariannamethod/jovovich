"""Actual tiny-Qwen trainer, independent remote faults and Chuck continuity."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'training'))
sys.path.insert(0, str(ROOT / 'test'))
from explanations.run_training import ARCHIVE_CAPABILITY, ARCHIVE_HELLO, TrainingError, run_training, validate_plan, digest
from durable_archive import DurableArchive
from durable_archive_fixture import FakeTransport


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def calls(path):
    return [json.loads(line[len('CHUCK_AUDIT '):]) for line in path.read_text().splitlines()
            if line.startswith('CHUCK_AUDIT ')]


def main():
    here = ROOT / 'training/results/2026-10-03-verdict-positions/integration-chuck'
    smoke = load(here / 'run_smoke.py', 'chuck_smoke')
    (ROOT / 'build').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='archive-gate-', dir=ROOT / 'build') as temp:
        directory = Path(temp)
        binary, wrapper = directory / 'trainer', directory / 'main.c'
        wrapper.write_text('#include "' + str(here / 'chuck_call_audit.h') + '"\n'
                           '#define nt_tape_chuck_step audited_chuck_step\n'
                           '#include "' + str(ROOT / 'training/train_mlp.c') + '"\n')
        substrate = [ROOT / 'deps/notorch' / name for name in
                     ('notorch.c', 'gguf.c', 'harness/runtime.c', 'harness/arch_llama.c', 'examples/bpe.c')]
        compile_result = subprocess.run(['cc', '-O1', '-std=gnu11', '-I' + str(ROOT / 'deps/notorch'),
                        '-o', str(binary), str(wrapper), *map(str, substrate), '-lm', '-pthread'],
                        capture_output=True, timeout=120)
        check(compile_result.returncode == 0, compile_result.stderr.decode())
        model, dataset, pairs = directory / 'tiny.gguf', directory / 'sft.bin', directory / 'pairs.bin'
        smoke.fixture(model)
        # Immutable matched fixture prepared through the same JVPR2 contract.
        from prepare import prepare
        data = [dict(id=str(i), kind='review', pair='tiny', messages=[dict(role='system', content='Review.'),
                dict(role='user', content='Diff.'), dict(role='assistant', content=a)]) for i, a in enumerate(
                ['{"analysis":"A longer reason.","findings":[{"reason":"bad"}]}',
                 '{"analysis":"Fine.","findings":[]}'])]
        source = directory / 'sft.jsonl'
        source.write_text(''.join(json.dumps(row) + '\n' for row in data))
        prepare(source, None, dataset, pairs, pair_format=2)
        binding_file = directory / 'bound.txt'
        binding_file.write_text('frozen source\n')
        names = [binary, model, dataset, pairs, ROOT / 'training/train_mlp.c', binding_file]
        plan = {'schema_version': 1, 'run_id': 'tiny-gate',
                'argv': [str(binary.relative_to(ROOT)), str(model.relative_to(ROOT)), str(dataset.relative_to(ROOT)),
                         '@RUN@/adapter', '8', '.003', '8', '2', 'joint', str(pairs.relative_to(ROOT))],
                'bindings': [{'path': str(p.relative_to(ROOT)), 'bytes': p.stat().st_size, 'sha256': digest(p)} for p in names],
                'environment': {'NT_NO_I8': '1', 'NT_QMV_THREADS': '1', 'NT_ATTN_THREADS': '1', 'NT_SIMD_THREADS': '1'}}
        capability = subprocess.run([str(binary), '--archive-protocol'], capture_output=True, timeout=5)
        check(capability.returncode == 0 and not capability.stderr and
              json.loads(capability.stdout) == ARCHIVE_CAPABILITY, 'native capability query failed')
        # A pre-protocol executable rejects the two-argument query. Its normal
        # training entrypoint must never be invoked, even if its hash is bound.
        stale = directory / 'stale-trainer'
        entered = directory / 'stale-model-work'
        stale.write_text('#!/usr/bin/env python3\nimport sys,pathlib\n'
                         'if len(sys.argv)<4: sys.exit(2)\n'
                         'pathlib.Path(' + repr(str(entered)) + ').write_text("model work entered")\n')
        stale.chmod(0o755)
        stale_plan = json.loads(json.dumps(plan))
        stale_plan['argv'][0] = str(stale.relative_to(ROOT))
        stale_plan['bindings'][0] = {'path': str(stale.relative_to(ROOT)),
                                    'bytes': stale.stat().st_size, 'sha256': digest(stale)}
        transport = FakeTransport()
        for check_launch in (lambda: validate_plan(stale_plan),
                             lambda: run_training(DurableArchive(transport, 'stale'), stale_plan, directory / 'stale-run')):
            try:
                check_launch()
            except TrainingError:
                pass
            else:
                raise RuntimeError('stale trainer capability accepted')
        check(not entered.exists() and transport.commits == 0 and not (directory / 'stale-run').exists(),
              'stale executable reached model work or remote launch')
        # A capability response is tied to the same on-disk executable bytes.
        changed = directory / 'changing-trainer'
        changed.write_text('#!/usr/bin/env python3\nimport pathlib,sys\n'
                           'print(' + repr(json.dumps(ARCHIVE_CAPABILITY)) + ')\n'
                           'with pathlib.Path(sys.argv[0]).open("a") as f: f.write("# changed\\n")\n')
        changed.chmod(0o755)
        changed_plan = json.loads(json.dumps(stale_plan))
        changed_plan['argv'][0] = str(changed.relative_to(ROOT))
        changed_plan['bindings'][0] = {'path': str(changed.relative_to(ROOT)),
                                      'bytes': changed.stat().st_size, 'sha256': digest(changed)}
        try:
            validate_plan(changed_plan)
        except RuntimeError:
            pass
        else:
            raise RuntimeError('trainer mutation during capability query accepted')
        argv = [str(binary), str(model), str(dataset), str(directory / 'plain'), '8', '.003', '8', '2', 'joint', str(pairs)]
        plain = subprocess.run(argv, capture_output=True, timeout=30)
        check(plain.returncode == 0, plain.stderr.decode())
        check(b'archive_ready' not in plain.stdout, 'default trainer emitted control records')
        remote = FakeTransport()
        archive = DurableArchive(remote, 'tiny-gate')
        original_sync = archive.sync_unit
        boundaries = []
        output = directory / 'success'
        def sync(name, files, *, sequence):
            if name.startswith('update-'):
                update = int(name.split('-')[1])
                observed = calls(output / 'stderr.log')
                check(len(observed) == update, 'native advanced before remote acknowledgement')
                boundaries.append(update)
            return original_sync(name, files, sequence=sequence)
        archive.sync_unit = sync
        result = run_training(archive, plan, output)
        check(result['status'] == 'completed' and boundaries == list(range(9)), 'missing successful boundaries')
        check(result['plan_sha256'] == digest(output / 'plan.json'), 'completion does not bind original plan bytes')
        check(json.loads((output / 'completion.json').read_text())['status'] == 'native_completed',
              'pre-archive completion manifest claims overall success')
        check(json.loads((output / '_units/completion.ack.json').read_text())['archive_status'] == 'verified',
              'successful final receipt missing verified status')
        check(remote.commits == 11 and remote.downloads, 'intent/boundaries/completion were not read back')
        audited = calls(output / 'stderr.log')
        check([r['step_after'] for r in audited] == list(range(1, 9)), 'Chuck state restarted across ACKs')
        for suffix in ('gate', 'up', 'down'):
            for extension in ('f32', 'lora'):
                name = suffix + '.' + extension
                check((output / ('adapter.' + name)).read_bytes() == (directory / ('plain.' + name)).read_bytes(),
                      'gated optimizer trajectory differs from uninterrupted control')
                check((output / ('adapter.epoch00.' + name)).is_file(), 'initial snapshot missing')
        raw = [json.loads(line) for line in (output / 'stdout.jsonl').read_text().splitlines()]
        metrics = [json.loads(line) for line in (output / 'metrics.jsonl').read_text().splitlines()]
        check(metrics == [row for row in raw if row['stage'] not in ('archive_ready', 'archive_hello')], 'control filtering changed native metrics')
        check(sum(row['stage'] == 'archive_ready' for row in raw) == 9, 'raw control evidence missing')
        check(raw[0] == ARCHIVE_HELLO, 'startup control missing from raw evidence')
        matched_plan = json.loads(json.dumps(plan))
        matched_plan['expected_initial_lora_sha256'] = result['initial_lora_sha256']
        matched_plan['argv'][4] = '0'
        matched = run_training(DurableArchive(FakeTransport(), 'matched-initial'), matched_plan, directory / 'matched-initial')
        check(matched['initial_lora_sha256'] == result['initial_lora_sha256'], 'matching initial adapters rejected')
        mismatched_plan = json.loads(json.dumps(plan))
        mismatched_plan['expected_initial_lora_sha256'] = dict(result['initial_lora_sha256'], gate='0' * 64)
        try:
            run_training(DurableArchive(FakeTransport(), 'mismatched-initial'), mismatched_plan, directory / 'mismatched-initial')
        except TrainingError:
            pass
        else:
            raise RuntimeError('mismatching initial adapters accepted')
        check(not calls(directory / 'mismatched-initial/stderr.log'), 'initial mismatch crossed first update')
        # Initial adapters also match an independent fresh process with zero updates.
        initial_argv = argv.copy()
        initial_argv[3], initial_argv[4] = str(directory / 'initial'), '0'
        zero = subprocess.run(initial_argv, capture_output=True, timeout=30)
        check(zero.returncode == 0, 'initial control failed')
        for suffix in ('gate', 'up', 'down'):
            check((output / ('adapter.epoch00.' + suffix + '.lora')).read_bytes() ==
                  (directory / ('initial.' + suffix + '.lora')).read_bytes(), 'initial A/B changed before gate0')
        for scenario in ('intent-failure', 'readback-corruption', 'lost-ack', 'binding-change', 'binding-during-archive', 'plan-during-archive'):
            dest = directory / scenario
            transport = FakeTransport()
            failed_archive = DurableArchive(transport, scenario)
            real_sync = failed_archive.sync_unit
            def fail_sync(name, files, *, sequence, scenario=scenario):
                if scenario == 'intent-failure' and name == 'intent':
                    transport.head_fault = RuntimeError('hf_SECRET_SENTINEL')
                if name == 'update-001':
                    if scenario == 'readback-corruption':
                        transport.download_fault = lambda path, data: data + b'corrupt'
                    if scenario == 'lost-ack':
                        def disconnect(_):
                            raise RuntimeError('hf_SECRET_SENTINEL')
                        transport.after_commit = disconnect
                receipt = real_sync(name, files, sequence=sequence)
                if scenario == 'binding-change' and name == 'intent':
                    binding_file.write_text('changed input\n')
                if scenario == 'binding-during-archive' and name == 'update-001':
                    binding_file.write_text('changed while archived\n')
                if scenario == 'plan-during-archive' and name == 'update-001':
                    changed = json.loads((dest / 'plan.json').read_text())
                    changed['argv'][5] = '.009'
                    (dest / 'plan.json').write_text(json.dumps(changed))
                return receipt
            failed_archive.sync_unit = fail_sync
            try:
                run_training(failed_archive, plan, dest)
            except TrainingError as exc:
                check('SECRET' not in str(exc), 'transport credentials leaked')
            else:
                raise RuntimeError('fault did not stop native run: ' + scenario)
            observed = calls(dest / 'stderr.log') if (dest / 'stderr.log').exists() else []
            check(len(observed) == (1 if scenario in ('readback-corruption', 'lost-ack', 'binding-during-archive', 'plan-during-archive') else 0),
                  'native update crossed failed archive gate')
            check(not (dest / 'adapter.gate.f32').exists(), 'failed attempt exported final model')
            check((dest / 'failure.json').is_file(), 'failure receipt missing')
            check(not (dest / '_units/completion.ack.json').exists(), 'failed trajectory claimed verified completion')
            binding_file.write_text('frozen source\n')
        for scenario in ('final-sync-failure', 'final-readback-corruption'):
            dest = directory / scenario
            transport = FakeTransport()
            failed_archive = DurableArchive(transport, scenario)
            real_sync = failed_archive.sync_unit
            def fail_final(name, files, *, sequence, scenario=scenario):
                if name == 'completion':
                    if scenario == 'final-sync-failure':
                        transport.head_fault = RuntimeError('hf_SECRET_SENTINEL')
                    else:
                        transport.download_fault = lambda path, data: data + b'corrupt'
                return real_sync(name, files, sequence=sequence)
            failed_archive.sync_unit = fail_final
            try:
                run_training(failed_archive, plan, dest)
            except TrainingError as exc:
                check('SECRET' not in str(exc), 'final transport credentials leaked')
            else:
                raise RuntimeError('failed final archive returned overall completion')
            candidate = json.loads((dest / 'completion.json').read_text())
            check(candidate['status'] == 'native_completed' and candidate['archive_status'] == 'requires_verified_receipt',
                  'failed final archive left an overall completion marker')
            check(not (dest / '_units/completion.ack.json').exists(), 'failed final archive wrote a verified receipt')
            check(len(calls(dest / 'stderr.log')) == 8 and (dest / 'failure.json').is_file(),
                  'final archive failure lost native trajectory or failure state')
        # Corrupt controller records are never treated as permission to ACK.
        for index, event in enumerate(({'stage': 'unknown_metric'},
                                       {'stage': 'archive_ready', 'update': 1, 'snapshot_saved': True},
                                       {'stage': 'archive_ready', 'update': False, 'snapshot_saved': True})):
            stub = directory / ('stub-%d' % index)
            stub.write_text('#!/usr/bin/env python3\nimport json,sys,pathlib\n'
                            'if sys.argv[1:] == ["--archive-protocol"]:\n print(' + repr(json.dumps(ARCHIVE_CAPABILITY)) + ');sys.exit(0)\n'
                            'print(' + repr(json.dumps(ARCHIVE_HELLO)) + ',flush=True)\n'
                            'if sys.stdin.readline() != "START\\n": sys.exit(1)\n'
                            'print(' + repr(json.dumps(event)) + ',flush=True)\n'
                            'ack=sys.stdin.readline()\n'
                            'if ack: pathlib.Path(sys.argv[3]+".advanced").write_text(ack)\n')
            stub.chmod(0o755)
            malformed_plan = json.loads(json.dumps(plan))
            malformed_plan['argv'][0] = str(stub.relative_to(ROOT))
            malformed_plan['bindings'][0] = {'path': str(stub.relative_to(ROOT)),
                                             'bytes': stub.stat().st_size, 'sha256': digest(stub)}
            destination = directory / ('bad-record-%d' % index)
            try:
                run_training(DurableArchive(FakeTransport(), 'bad-record'), malformed_plan, destination)
            except TrainingError:
                pass
            else:
                raise RuntimeError('invalid native event accepted')
            check(not (destination / 'adapter.advanced').exists(), 'invalid control record received ACK')
        for scenario in ('missing-startup', 'silent-startup'):
            stub = directory / scenario
            body = '' if scenario == 'silent-startup' else 'print("{}",flush=True)\n'
            stub.write_text('#!/usr/bin/env python3\nimport sys,pathlib\n'
                            'if sys.argv[1:] == ["--archive-protocol"]:\n print(' + repr(json.dumps(ARCHIVE_CAPABILITY)) + ');sys.exit(0)\n'
                            + body + 'ack=sys.stdin.readline()\n'
                            'if ack: pathlib.Path(sys.argv[3]+".advanced").write_text(ack)\n')
            stub.chmod(0o755)
            bad_plan = json.loads(json.dumps(plan))
            bad_plan['argv'][0] = str(stub.relative_to(ROOT))
            bad_plan['bindings'][0] = {'path': str(stub.relative_to(ROOT)),
                                      'bytes': stub.stat().st_size, 'sha256': digest(stub)}
            destination = directory / (scenario + '-run')
            try:
                run_training(DurableArchive(FakeTransport(), scenario), bad_plan, destination)
            except TrainingError:
                pass
            else:
                raise RuntimeError('missing native startup accepted')
            check(not (destination / 'adapter.advanced').exists(), 'missing startup received START')
        env = dict(os.environ, JOVOVICH_ARCHIVE_ACK='1', JOVOVICH_ARCHIVE_ACK_TIMEOUT_MS='30')
        for index, data in enumerate((b'START\n', b'START\nACK 1\n', b'START\nACK 0 \n', b'START\nACK 0\r\n')):
            malformed = argv.copy()
            malformed[3] = str(directory / ('bad-%d' % index))
            run = subprocess.run(malformed, input=data, env=env, capture_output=True, timeout=20)
            check(run.returncode != 0 and b'CHUCK_AUDIT' not in run.stderr, 'malformed/missing ACK advanced optimizer')
        timed = argv.copy()
        timed[3] = str(directory / 'timed')
        with (directory / 'timed.stdout').open('wb') as out, (directory / 'timed.stderr').open('wb') as err:
            proc = subprocess.Popen(timed, stdin=subprocess.PIPE, stdout=out, stderr=err, env=env)
            proc.stdin.write(b'STA')
            proc.stdin.flush()
            check(proc.wait(timeout=20) != 0, 'partial ACK did not time out')
            proc.stdin.close()
        check(b'archive ACK timeout' in (directory / 'timed.stderr').read_bytes(), 'wrong partial ACK failure')
        check(not calls(directory / 'timed.stderr'), 'timed out ACK advanced optimizer')
        check(b'cache ' not in (directory / 'timed.stderr').read_bytes(), 'native model work preceded START')
        missing_inputs = argv.copy()
        missing_inputs[1:4] = ['missing-model.gguf', 'missing-dataset.bin', str(directory / 'no-start')]
        no_start = subprocess.run(missing_inputs, input=b'', env=env, capture_output=True, timeout=5)
        check(no_start.returncode != 0 and json.loads(no_start.stdout) == ARCHIVE_HELLO and
              b'missing or invalid archive ACK' in no_start.stderr and b'dataset' not in no_start.stderr,
              'native opened inputs before START')
        print(json.dumps({'passed': True, 'native_updates': 8, 'bitwise_trajectory_match': True,
                          'verified_units': 11, 'fault_scenarios': 22,
                          'initial_adapter_match': True, 'scorer_metrics_preserved': True}))


if __name__ == '__main__':
    main()
