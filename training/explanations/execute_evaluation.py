#!/usr/bin/env python3
"""Execute the frozen endpoint/export/generation contract after both training arms."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'training'), str(Path(__file__).resolve().parent)]
from durable_archive import DurableArchive, HFTransport, ArchiveError
from layers.run_layers import check_binding, digest, identity, now, run_work_units, save, unit_paths
from collect_generation import collect


def need(value, message):
    if not value:
        raise RuntimeError(message)


def read(path):
    return json.loads(Path(path).read_text())


def local(path, *, existing=True):
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    need(path.resolve().is_relative_to(ROOT.resolve()) and not path.is_symlink(),
         'evaluation paths must stay inside the repository')
    if existing:
        need(path.is_file(), 'required evaluation input is missing')
    return path.resolve()


def binding(path):
    path = local(path)
    before = identity(path)
    result = dict(path=str(path.relative_to(ROOT)), bytes=path.stat().st_size, sha256=digest(path))
    need(identity(path) == before, 'input changed while hashing')
    return result


def resolve(value, parameters):
    if isinstance(value, str):
        for name, replacement in parameters.items():
            value = value.replace('@' + name + '@', replacement)
        need(re.search(r'@[A-Z0-9_]+@', value) is None, 'unresolved evaluation parameter')
        return value
    if isinstance(value, list):
        return [resolve(item, parameters) for item in value]
    if isinstance(value, dict):
        return {key: resolve(item, parameters) for key, item in value.items()}
    return value


def export_unit(step, parameters, output):
    result = resolve(step, parameters)
    for key in ('stdout', 'stderr'):
        if key in result:
            result[key] = str(Path(result[key]).relative_to(output))
    logs = {result[key] for key in ('stdout', 'stderr') if key in result}
    # run_work_units already includes stdout/stderr in its closed artifact set.
    # They must not also be declared outputs in a run_layers-compatible phase.
    result['outputs'] = [str(Path(path).relative_to(output)) for path in result.get('outputs', [])
                         if str(Path(path).relative_to(output)) not in logs]
    result['kind'] = 'command'
    return result


def native_environment(frozen):
    need(frozen == {'NT_NO_I8': '1', 'NT_QMV_THREADS': '4',
                    'NT_ATTN_THREADS': '4', 'NT_SIMD_THREADS': '4'},
         'evaluation native environment differs from frozen contract')
    env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'TMPDIR') if key in os.environ}
    env.update(frozen)
    return env


@contextmanager
def credential_free_parent_environment():
    # The collector launches Git in its parent environment. Keep transport
    # proxy/TLS configuration while credentials live only in HFTransport.
    words = ('TOKEN', 'SECRET', 'CREDENTIAL', 'PASSWORD', 'PRIVATE_KEY', 'ACCESS_KEY', 'API_KEY')
    removed = {key: value for key, value in os.environ.items() if any(word in key.upper() for word in words)}
    try:
        for key in removed:
            del os.environ[key]
        yield
    finally:
        os.environ.update(removed)


def run_command(argv, stdout, stderr, environment):
    stdout.parent.mkdir(parents=True, exist_ok=True)
    stderr.parent.mkdir(parents=True, exist_ok=True)
    with stdout.open('xb') as out, stderr.open('xb') as err:
        process = subprocess.Popen(argv, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=out, stderr=err)
        try:
            return process.wait()
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        finally:
            out.flush(); err.flush()
            os.fsync(out.fileno()); os.fsync(err.fileno())


def prepare(plan_path, before, after, output, run_id):
    need(not sys.flags.optimize and not os.environ.get('PYTHONOPTIMIZE'),
         'optimized Python execution is unsupported')
    need(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,49}', run_id), 'invalid evaluation run ID')
    plan_path = local(plan_path)
    output = local(output, existing=False)
    need(not output.exists(), 'evaluation destination must be new')
    contract = read(plan_path)
    need(contract.get('schema') == 'jovovich.explanation-order.evaluation.v1', 'unsupported evaluation contract')
    bindings, training, receipts, frozen_arms = {}, {}, [], {}
    scientific = read(local(contract['scientific_plan']))
    for arm, directory in (('before', before), ('after', after)):
        directory = local(directory, existing=False)
        launch_path = local(directory / 'plan.json')
        completion_path = local(directory / '_units/completion.ack.json')
        checkpoint_path = local(directory / '_units/update-100.ack.json')
        launch, completed, checkpoint = read(launch_path), read(completion_path), read(checkpoint_path)
        need(launch.get('arm') == arm, 'supplied training directory has the wrong arm')
        export = next(item for item in contract['exports'] if item['arm'] == arm)
        dataset = export['steps'][-1]['argv'][3]
        pairs = dataset[:-4] + '.pairs.bin'
        training_parameters = {
            'BASE': 'models/base-qwen.gguf', 'ARM_DATASET': dataset,
            'ARM_PREFIX': '@RUN@/adapter', 'ARM_PAIR_MAP': pairs}
        expected_argv = list(scientific['training']['argv_template'])
        for name, value in training_parameters.items():
            expected_argv = [argument.replace('@' + name + '@', value) for argument in expected_argv]
        need(launch['argv'] == expected_argv and launch['environment'] == scientific['training']['native_environment'],
             'training arguments or environment differ from the scientific contract')
        need(completed.get('status') == 'completed' and completed.get('archive_status') == 'verified' and
             completed.get('acknowledged_updates') == 100 and completed.get('return_code') == 0 and
             completed.get('plan_sha256') == digest(launch_path) and
             completed.get('bindings') == launch.get('bindings'), 'training completion is incomplete or unbound')
        need(launch['argv'][3] == '@RUN@/adapter' and launch['argv'][4] == '100' and
             launch['remote'] == {'repo': 'ataeff/jovovich', 'prefix': 'experiments/explanation-order', 'private': True},
             'training endpoint or archive differs from frozen contract')
        for receipt, unit in ((completed['remote_verification'], 'completion'), (checkpoint, 'update-100')):
            need(receipt.get('verified_remote_bytes') is True and receipt.get('run_id') == launch['run_id'] and
                 receipt.get('unit_id') == unit, 'training archive receipt mismatch')
            receipts.append(receipt)
            for entry in receipt['files']:
                path = local(directory / entry['name'])
                need(path.is_relative_to(directory), 'training receipt path escapes its attempt')
                item = binding(path)
                need(item['bytes'] == entry['size'] and item['sha256'] == entry['sha256'],
                     'local training evidence differs from its remote receipt')
                bindings[item['path']] = item
        raw_completion = read(directory / 'completion.json')
        need(all(completed.get(key) == value for key, value in raw_completion.items()
                 if key not in ('status', 'archive_status')), 'training completion receipt fields changed')
        frozen = {item['path']: item for item in launch['bindings']}
        need(dataset in frozen and pairs in frozen, 'arm packed inputs were not frozen before training')
        frozen_arms[arm] = {name: item for name, item in frozen.items() if name not in (dataset, pairs)}
        need(frozen[str(plan_path.relative_to(ROOT))]['sha256'] == digest(plan_path),
             'evaluation contract changed after training launch')
        for name, item in frozen.items():
            path = local(name)
            check_binding(path, item)
            need(name not in bindings or bindings[name] == item, 'training arm source bindings disagree')
            bindings[name] = item
        for path in (launch_path, completion_path, checkpoint_path, directory / 'completion.json'):
            item = binding(path); bindings[item['path']] = item
        for suffix in ('gate', 'up', 'down'):
            for extension in ('f32', 'lora'):
                for epoch in ('', '.epoch100'):
                    item = binding(directory / f'adapter{epoch}.{suffix}.{extension}')
                    bindings[item['path']] = item
        training[arm] = dict(directory=str(directory), run_id=launch['run_id'],
                             initial_lora_sha256=completed['initial_lora_sha256'])
    need(training['before']['directory'] != training['after']['directory'] and
         training['before']['run_id'] != training['after']['run_id'], 'training attempts must be distinct')
    need(frozen_arms['before'] == frozen_arms['after'], 'shared training source bindings disagree')
    need(set(contract['required_pretraining_launch_bindings']) <= set(bindings),
         'evaluation source was not frozen across the paired training launches')
    need(training['before']['initial_lora_sha256'] == training['after']['initial_lora_sha256'],
         'paired initialization hashes differ')
    helper = binding(Path(__file__))
    bindings[helper['path']] = helper
    parameters = {'BEFORE_RUN': training['before']['directory'], 'AFTER_RUN': training['after']['directory'],
                  'EVALUATION_RUN': str(output), 'EVALUATION_RUN_ID': run_id,
                  'INFER_SHA256': bindings['build/jovovich-infer']['sha256'],
                  'SHARED_BASE_UPDATE0_SHA256': bindings['models/base-qwen.gguf']['sha256']}
    need(parameters['SHARED_BASE_UPDATE0_SHA256'] == contract['resolution']['SHARED_BASE_UPDATE0_SHA256'],
         'base model differs from frozen Qwen')
    exports = [export_unit(step, parameters, output) for arm in contract['exports'] for step in arm['steps']]
    need([arm['arm'] for arm in contract['exports']] == ['before', 'after'] and len(exports) == 8,
         'expected both endpoint export sequences')
    need([r['index'] for r in contract['parity']['rows']] == [0, 1, 2, 3, 51], 'parity rows changed')
    need(sum(job['rows'] for job in contract['collector_jobs']) == 228 and len(contract['collector_jobs']) == 6,
         'expected six fixed collector jobs')
    native_environment(contract['native_environment'])
    return dict(schema_version=1, run_id=run_id, parameters=parameters, training=training,
                contract=contract, contract_source=str(plan_path.relative_to(ROOT)),
                bindings=list(bindings.values()), training_receipts=receipts, export_phases=exports)


def verify_training_receipts(archive, receipts, temporary):
    """Fresh pinned manifest and checkpoint/final bytes, before admitting exports."""
    verified = set()
    for index, receipt in enumerate(receipts):
        name = f"{receipt['prefix']}/units/{receipt['sequence']:06d}-{receipt['unit_id']}.json"
        path = temporary / f'manifest-{index}.json'
        archive._remote('download', name, receipt['revision'], path)
        need(digest(path) == receipt['manifest_sha256'], 'training remote manifest checksum mismatch')
        manifest = read(path)
        need(manifest['run_id'] == receipt['run_id'] and manifest['sequence'] == receipt['sequence'] and
             manifest['unit_id'] == receipt['unit_id'] and manifest['files'] == receipt['files'],
             'training remote receipt disagrees with pinned manifest')
        for entry in receipt['files']:
            if entry['sha256'] in verified:
                continue
            target = temporary / entry['sha256']
            archive._remote('download', entry['object'], receipt['revision'], target)
            need(target.stat().st_size == entry['size'] and digest(target) == entry['sha256'],
                 'training remote payload checksum mismatch')
            verified.add(entry['sha256'])
    return dict(status='verified', receipts=receipts, unique_payloads=len(verified))


def argument_map(argv):
    need(len(argv) >= 2 and len(argv[2:]) % 2 == 0, 'invalid frozen collector argv')
    args = dict(zip(argv[2::2], argv[3::2]))
    need(len(args) * 2 == len(argv[2:]) and set(args) == {
        '--sft', '--split', '--model', '--model-sha256', '--infer', '--infer-sha256',
        '--output', '--run-id', '--hf-repo', '--remote-prefix'}, 'collector arguments changed')
    need(args['--hf-repo'] == 'ataeff/jovovich' and args['--remote-prefix'] == 'experiments/explanation-order',
         'collector remote destination changed')
    return args


def compare_prompts(jobs):
    references, counts = {}, {}
    for job in jobs:
        args = argument_map(job['argv'])
        directory = Path(args['--output'])
        manifest = read(directory / 'manifest.json')
        rows = [json.loads(line) for line in (directory / 'generations.jsonl').read_text().splitlines()]
        need(len(rows) == job['rows'] == len(manifest['cases']), 'collector coverage mismatch')
        samples = []
        for row, case in zip(rows, manifest['cases']):
            raw = (directory / case['prompt_path']).read_bytes()
            need(row['case_id'] == case['case_id'] and row['finish_reason'] in ('eos', 'length'),
                 'collector case order or completion mismatch')
            need(row['metadata']['prompt_sha256'] == case['prompt_sha256'] and
                 digest(directory / case['prompt_path']) == case['prompt_sha256'], 'prompt bytes changed')
            need(row['metadata']['model_sha256'] == args['--model-sha256'] and
                 isinstance(row['raw_response'], str), 'generated model or literal response is unbound')
            need(hashlib.sha256(row['raw_response'].encode()).hexdigest() == row['raw_response_sha256'],
                 'generated response hash mismatch')
            samples.append((row['case_id'], raw, row['metadata']['prompt_token_ids']))
        split = job['split']
        if split in references:
            need(samples == references[split], 'cross-model prompt bytes or token IDs differ')
        else:
            references[split] = samples
        counts[job['id']] = len(rows)
    need(sum(counts.values()) == 228 and len(counts) == 6, 'incomplete evaluation comparison')
    return dict(status='pass', generation_calls=228, jobs=counts,
                unique_prompts={split: len(rows) for split, rows in references.items()})


def execute(archive, prepared, output, *, collector=collect):
    output = Path(output).resolve()
    need(not output.exists(), 'evaluation destination must be new')
    output.mkdir(parents=True)
    save(output / 'plan.json', prepared)
    inputs = {'plan.json': output / 'plan.json'}
    plan_sha256 = digest(output / 'plan.json')
    tracked = {output / 'plan.json': identity(output / 'plan.json')}
    for item in prepared['bindings']:
        source = local(item['path']); tracked[source] = check_binding(source, item)
        if item['path'] == 'models/base-qwen.gguf':
            continue
        target = output / 'inputs' / item['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        check_binding(target, item)
        inputs[str(target.relative_to(output))] = target
    receipt = archive.sync_unit('bootstrap', inputs, sequence=0)
    need(digest(output / 'plan.json') == plan_sha256, 'evaluation manifest changed during bootstrap')
    save(output / '_receipts/bootstrap.json', receipt)
    contract, parameters = prepared['contract'], dict(prepared['parameters'])
    environment = native_environment(contract['native_environment'])
    phases = [dict(id='training-remote-check', kind='verify_training', outputs=['training-remote-verification.json'])]
    for arm in ('before', 'after'):
        phases.append(dict(id=arm + '-teacher-forced-diagnostics', kind='command',
                           argv=['python3', 'training/score_decisions.py',
                                 prepared['training'][arm]['directory'] + '/metrics.jsonl',
                                 '--sft', 'training/sft_review_v6_' + arm + '.jsonl',
                                 '--output', str(output / 'diagnostics' / (arm + '-teacher-forced.json'))],
                           outputs=['diagnostics/' + arm + '-teacher-forced.json']))
    phases += prepared['export_phases']
    phases += [dict(id='resolve-generation', kind='resolve_generation', outputs=['generation-plan.json'])]
    for index, job in enumerate(contract['collector_jobs']):
        phases.append(dict(id=job['id'] + '-collect', kind='collector', job=index,
                           outputs=['_receipts/' + job['id'] + '.json']))
        phases.append(dict(id=job['id'] + '-score', kind='score', job=index,
                           outputs=['generation/' + job['id'] + '/structural-score.json']))
    phases.append(dict(id='cross-model-prompts', kind='compare_prompts', outputs=['prompt-comparison.json']))

    def guard():
        need(all(identity(path) == signature for path, signature in tracked.items()),
             'bound evaluation input changed')

    def command(unit, directory):
        guard()
        print(json.dumps(dict(unit=unit['id'], status='intent_remotely_verified', started_utc=now())),
              file=sys.stderr, flush=True)
        for name in unit.get('outputs', []):
            (directory / name).parent.mkdir(parents=True, exist_ok=True)
        _, _, default_stdout, default_stderr = unit_paths(unit, directory)
        commands = []
        kind = unit['kind']
        if kind == 'verify_training':
            with tempfile.TemporaryDirectory(prefix='evaluation-remote-check-') as tmp:
                verified = verify_training_receipts(archive, prepared['training_receipts'], Path(tmp))
            save(directory / unit['outputs'][0], verified)
        elif kind == 'resolve_generation':
            for arm in ('before', 'after'):
                model = directory / 'exports' / arm / 'jovovich.gguf'
                audit = read(model.parent / 'export-audit.json')
                need(audit.get('valid') is True and audit['adapted'] == 3 and audit['metadata_equal'] is True and
                     audit['model']['sha256'] == digest(model), 'export audit/model binding failed')
                parameters[arm.upper() + '_UPDATE100_SHA256'] = audit['model']['sha256']
                tracked[model] = identity(model)
            jobs = resolve(contract['collector_jobs'], parameters)
            save(directory / 'generation-plan.json', dict(jobs=jobs, parameters=parameters))
        elif kind == 'collector':
            job = read(directory / 'generation-plan.json')['jobs'][unit['job']]
            args = argument_map(job['argv'])
            journal = DurableArchive(archive.transport, args['--run-id'], args['--remote-prefix'])
            with credential_free_parent_environment():
                result = collector(journal, corpus=Path(args['--sft']), split=args['--split'],
                                   model=Path(args['--model']), executable=Path(args['--infer']),
                                   output=Path(args['--output']), run_id=args['--run-id'],
                                   expected_model_sha256=args['--model-sha256'],
                                   expected_infer_sha256=args['--infer-sha256'])
            remote = result.get('remote_verification', {})
            need(result.get('status') == 'completed' and result.get('archive_status') == 'verified' and
                 result.get('cases') == job['rows'] and result.get('run_id') == args['--run-id'] and
                 remote.get('verified_remote_bytes') is True and remote.get('run_id') == args['--run-id'] and
                 remote.get('unit_id') == 'completion',
                 'collector did not finish with verified remote evidence')
            collected = Path(args['--output'])
            entries = {entry['name']: entry for entry in remote['files']}
            need(result.get('generations_sha256') == digest(collected / 'generations.jsonl') ==
                 entries['generations.jsonl']['sha256'], 'generation output differs from its pinned receipt')
            for name, entry in entries.items():
                path = collected / name
                need(path.resolve().is_relative_to(collected.resolve()) and not path.is_symlink() and
                     path.stat().st_size == entry['size'] and digest(path) == entry['sha256'],
                     'collector completion artifact differs from its pinned receipt')
            for path in collected.rglob('*'):
                if path.is_file():
                    need(not path.is_symlink(), 'collector artifact must be a regular file')
                    tracked[path] = identity(path)
            save(directory / unit['outputs'][0], dict(argv=job['argv'], result=result))
        elif kind == 'compare_prompts':
            save(directory / unit['outputs'][0], compare_prompts(read(directory / 'generation-plan.json')['jobs']))
        else:
            if kind == 'score':
                job = read(directory / 'generation-plan.json')['jobs'][unit['job']]
                invocations = [(job['score_argv'], default_stdout, default_stderr)]
            else:
                invocations = [(unit['argv'], directory / unit.get('stdout', str(default_stdout.relative_to(directory))),
                                directory / unit.get('stderr', str(default_stderr.relative_to(directory))))]
                if 'check_argv' in unit:
                    invocations.append((unit['check_argv'], directory / '_units' / (unit['id'] + '.check.stdout'),
                                        directory / '_units' / (unit['id'] + '.check.stderr')))
            for argv, stdout, stderr in invocations:
                record = dict(argv=argv, started_utc=now())
                code = run_command(argv, stdout, stderr, environment)
                commands.append(dict(record, return_code=code, finished_utc=now()))
                if code:
                    return dict(return_code=code, commands=commands)
            if kind == 'score':
                score = read(directory / unit['outputs'][0])
                need(score['status'] == 'complete' and score['summary']['received_reviews'] == job['rows'],
                     'structural scorer has incomplete coverage')
        guard()
        # Closed artifacts become immutable inputs to subsequent phases.
        for name in unit.get('outputs', []) + [unit[key] for key in ('stdout', 'stderr') if key in unit]:
            path = directory / name
            need(path.is_file() and not path.is_symlink(), 'phase output missing or invalid')
            tracked[path] = identity(path)
        return dict(return_code=0, commands=commands)

    sequence = run_work_units(archive, phases, command, run_dir=output, next_sequence=1)
    guard()
    need(digest(output / 'plan.json') == plan_sha256, 'evaluation manifest changed')
    for item in prepared['bindings']:
        check_binding(local(item['path']), item)
    completion = dict(status='native_evaluation_completed', semantic_audit='pending',
                      run_id=prepared['run_id'], generation_calls=228, parity_rows_per_arm=5,
                      structural_reports=6, teacher_forced_reports=2,
                      checkpoint_policy='Export update100 only; selected_update in diagnostics is informational.',
                      plan_sha256=plan_sha256, finished_utc=now(), bindings=prepared['bindings'])
    save(output / 'completion.json', completion)
    receipt = archive.sync_unit('completion', {'completion.json': output / 'completion.json'}, sequence=sequence)
    result = dict(completion, archive_status='verified', remote_verification=receipt)
    save(output / '_receipts/completion.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('preflight', 'run'))
    parser.add_argument('--plan', type=Path, default=ROOT / 'training/explanations/evaluation_plan.json')
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--token-file', type=Path)
    args = parser.parse_args()
    try:
        prepared = prepare(args.plan, args.before, args.after, args.output, args.run_id)
        if args.mode == 'preflight':
            print(json.dumps(dict(status='preflight_passed', bindings=len(prepared['bindings']),
                                  parity_rows=[0, 1, 2, 3, 51], generation_calls=228)))
            return
        token = args.token_file.read_text().strip() if args.token_file else os.environ.get('HF_TOKEN', '')
        archive = DurableArchive(HFTransport('ataeff/jovovich', token), args.run_id,
                                 'experiments/explanation-order')
        print(json.dumps(execute(archive, prepared, local(args.output, existing=False))))
    except (RuntimeError, OSError, ValueError, ArchiveError) as error:
        # Never propagate transport text or credential-bearing environment state.
        print('execute_evaluation: stopped; inspect closed phase evidence (' + type(error).__name__ + ')', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
