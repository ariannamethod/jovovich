#!/usr/bin/env python3
"""Evaluate the quote arm under a contract derived from the before branch of the frozen evaluation plan."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'explanations'))
import execute_evaluation as ev
from execute_evaluation import (ArchiveError, DurableArchive, HFTransport, argument_map, binding, check_binding,
                                collect, credential_free_parent_environment, digest, export_unit, identity, local,
                                native_environment, need, now, read, resolve, run_command, run_work_units, save,
                                unit_paths, verify_training_receipts)

SCHEMA = 'jovovich.quote.evaluation.v1'
TEMPLATE = 'training/explanations/evaluation_plan.json'
CONTRACT = 'training/quote/evaluation_contract.json'
SCIENTIFIC = 'training/explanations/plan.json'
REMOTE = {'repo': 'ataeff/jovovich', 'prefix': 'experiments/explanation-order', 'private': True}
SPLITS = [('train', 52), ('holdout', 24)]
# quote = before + one variable. Token-exact: the bare word "before" in --order, expected_order and
# sft_review_v6_before.jsonl stays; the export arm label is replaced only as a named field.
SUBSTITUTIONS = [
    ['before-endpoint-binding', 'quote-endpoint-binding'],
    ['before-merge', 'quote-merge'],
    ['before-byte-export-audit', 'quote-byte-export-audit'],
    ['before-native-export-parity', 'quote-native-export-parity'],
    ['@BEFORE_RUN@', '@QUOTE_RUN@'],
    ['/exports/before/', '/exports/quote/'],
    ['training/results/2026-10-03-explanation-order-run/native/before.bin', '@QUOTE_NATIVE@/quote.bin'],
    ['before_update100', 'quote_update100'],
    ['@BEFORE_UPDATE100_SHA256@', '@QUOTE_UPDATE100_SHA256@'],
]
FIELD_SUBSTITUTIONS = [{'path': ['export', 'arm'], 'from': 'before', 'to': 'quote'}]


def substitute(value, pairs):
    if isinstance(value, str):
        for old, new in pairs:
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [substitute(item, pairs) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item, pairs) for key, item in value.items()}
    return value


def derive(template):
    raw = Path(template).read_bytes()
    plan = json.loads(raw)
    need(plan.get('schema') == 'jovovich.explanation-order.evaluation.v1', 'unsupported evaluation template')
    branch = dict(export=next(item for item in plan['exports'] if item['arm'] == 'before'),
                  collector_jobs=[job for job in plan['collector_jobs'] if job['model'] == 'before_update100'])
    text = json.dumps(branch)
    # The inverse list restores the branch exactly only if every source token occurs and no target preexists.
    need(all(old in text and new not in text for old, new in SUBSTITUTIONS),
         'substitution list does not invert on the before branch')
    derived = substitute(branch, SUBSTITUTIONS)
    need(not any(old in json.dumps(derived) for old, _ in SUBSTITUTIONS), 'before tokens survived substitution')
    for field in FIELD_SUBSTITUTIONS:
        parent, key = derived[field['path'][0]], field['path'][1]
        need(parent[key] == field['from'], 'field substitution source differs')
        parent[key] = field['to']
    return {'schema': SCHEMA,
            'derived_from': {'path': TEMPLATE, 'sha256': hashlib.sha256(raw).hexdigest(), 'export_arm': 'before',
                             'collector_jobs': [job['id'] for job in branch['collector_jobs']]},
            'substitutions': SUBSTITUTIONS, 'field_substitutions': FIELD_SUBSTITUTIONS,
            'resolution': {key: plan['resolution'][key] for key in ('INFER_SHA256', 'SHARED_BASE_UPDATE0_SHA256')},
            'native_environment': plan['native_environment'], 'generation': plan['generation'],
            'parity': plan['parity'], **derived}


def render(contract):
    return (json.dumps(contract, indent=2, ensure_ascii=False) + '\n').encode()


def check_contract(path, template):
    need(Path(path).read_bytes() == render(derive(template)), 'quote evaluation contract differs from its derivation')


def prepare(contract_path, quote_run, before_collectors, output, run_id):
    need(not sys.flags.optimize and not os.environ.get('PYTHONOPTIMIZE'),
         'optimized Python execution is unsupported')
    need(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,49}', run_id), 'invalid evaluation run ID')
    contract_path = local(contract_path)
    output = local(output, existing=False)
    need(not output.exists(), 'evaluation destination must be new')
    contract = read(contract_path)
    need(contract.get('schema') == SCHEMA, 'unsupported quote evaluation contract')
    template = local(TEMPLATE)
    check_contract(contract_path, template)
    scientific = read(local(SCIENTIFIC))
    directory = local(quote_run, existing=False)
    launch_path = local(directory / 'plan.json')
    completion_path = local(directory / '_units/completion.ack.json')
    checkpoint_path = local(directory / '_units/update-100.ack.json')
    launch, completed, checkpoint = read(launch_path), read(completion_path), read(checkpoint_path)
    need(launch.get('arm') == 'quote', 'supplied training directory is not the quote arm')
    dataset = launch['argv'][2]
    pairs = dataset[:-4] + '.pairs.bin'
    expected_argv = list(scientific['training']['argv_template'])
    for name, value in {'BASE': 'models/base-qwen.gguf', 'ARM_DATASET': dataset,
                        'ARM_PREFIX': '@RUN@/adapter', 'ARM_PAIR_MAP': pairs}.items():
        expected_argv = [argument.replace('@' + name + '@', value) for argument in expected_argv]
    need(launch['argv'] == expected_argv and launch['environment'] == scientific['training']['native_environment'],
         'training arguments or environment differ from the scientific contract')
    need(completed.get('status') == 'completed' and completed.get('archive_status') == 'verified' and
         completed.get('acknowledged_updates') == 100 and completed.get('return_code') == 0 and
         completed.get('plan_sha256') == digest(launch_path) and
         completed.get('bindings') == launch.get('bindings'), 'training completion is incomplete or unbound')
    need(launch['argv'][3] == '@RUN@/adapter' and launch['argv'][4] == '100' and launch['remote'] == REMOTE,
         'training endpoint or archive differs from frozen contract')
    bindings, receipts = {}, []
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
    need(dataset in frozen and pairs in frozen, 'quote packed inputs were not frozen before training')
    source = str(contract_path.relative_to(ev.ROOT))
    need(launch.get('evaluation_plan') == source and source in frozen and
         frozen[source]['sha256'] == digest(contract_path), 'quote evaluation contract was not frozen before training')
    for name, item in frozen.items():
        check_binding(local(name), item)
        need(name not in bindings or bindings[name] == item, 'training source bindings disagree')
        bindings[name] = item
    for path in (launch_path, completion_path, checkpoint_path, directory / 'completion.json'):
        item = binding(path); bindings[item['path']] = item
    for suffix in ('gate', 'up', 'down'):
        for extension in ('f32', 'lora'):
            for epoch in ('', '.epoch100'):
                item = binding(directory / f'adapter{epoch}.{suffix}.{extension}')
                bindings[item['path']] = item
    need(completed['initial_lora_sha256'] == launch.get('expected_initial_lora_sha256'),
         'quote initialization differs from the before arm')
    required = {path for path in read(template)['required_pretraining_launch_bindings'] if '/native/' not in path}
    required |= {'training/sft_review_v7_quote.jsonl', 'training/explanations/reasons.json',
                 'training/quote/manipulation.mjs', 'training/quote/evaluate_quote.py',
                 'training/explanations/execute_evaluation.py'}
    need(required <= set(frozen), 'quote evaluation source was not frozen in the training launch')
    before = {}
    for (split, rows), collected in zip(SPLITS, before_collectors):
        collected = local(collected, existing=False)
        manifest_path, generations = local(collected / 'manifest.json'), local(collected / 'generations.jsonl')
        manifest = read(manifest_path)
        need(manifest.get('split') == split and str(manifest.get('run_id')).endswith('-before_update100-' + split),
             'before collector is not the archived before_update100 run for its split')
        need(len(manifest['cases']) == len(generations.read_text().splitlines()) == rows,
             'before collector coverage differs from its split')
        for path in (manifest_path, generations, *(collected / case['prompt_path'] for case in manifest['cases'])):
            item = binding(path); bindings[item['path']] = item
        before[split] = str(collected)
    parameters = {'QUOTE_RUN': str(directory), 'QUOTE_NATIVE': str(Path(dataset).parent),
                  'EVALUATION_RUN': str(output), 'EVALUATION_RUN_ID': run_id,
                  'INFER_SHA256': bindings['build/jovovich-infer']['sha256'],
                  'SHARED_BASE_UPDATE0_SHA256': bindings['models/base-qwen.gguf']['sha256']}
    need(parameters['SHARED_BASE_UPDATE0_SHA256'] == contract['resolution']['SHARED_BASE_UPDATE0_SHA256'],
         'base model differs from frozen Qwen')
    exports = [export_unit(step, parameters, output) for step in contract['export']['steps']]
    need(len(exports) == 4 and exports[-1]['argv'][3] == dataset, 'expected the quote export sequence on its dataset')
    need([row['index'] for row in contract['parity']['rows']] == [0, 1, 2, 3, 51], 'parity rows changed')
    need([(job['split'], job['rows']) for job in contract['collector_jobs']] == SPLITS,
         'expected two fixed quote collector jobs')
    native_environment(contract['native_environment'])
    return dict(schema_version=1, arm='quote', run_id=run_id, parameters=parameters,
                training=dict(directory=str(directory), run_id=launch['run_id'],
                              initial_lora_sha256=completed['initial_lora_sha256']),
                before_collectors=before, contract=contract, contract_source=source,
                bindings=list(bindings.values()), training_receipts=receipts, export_phases=exports)


def samples(directory, rows, model_sha256=None):
    manifest = read(directory / 'manifest.json')
    records = [json.loads(line) for line in (directory / 'generations.jsonl').read_text().splitlines()]
    need(len(records) == rows == len(manifest['cases']), 'collector coverage mismatch')
    model_sha256 = model_sha256 or manifest['model']['sha256']
    result = []
    for row, case in zip(records, manifest['cases']):
        raw = (directory / case['prompt_path']).read_bytes()
        need(row['case_id'] == case['case_id'] and row['finish_reason'] in ('eos', 'length'),
             'collector case order or completion mismatch')
        need(row['metadata']['prompt_sha256'] == case['prompt_sha256'] == hashlib.sha256(raw).hexdigest(),
             'prompt bytes changed')
        need(row['metadata']['model_sha256'] == model_sha256 and isinstance(row['raw_response'], str),
             'generated model or literal response is unbound')
        need(hashlib.sha256(row['raw_response'].encode()).hexdigest() == row['raw_response_sha256'],
             'generated response hash mismatch')
        result.append((row['case_id'], raw, row['metadata']['prompt_token_ids']))
    return result


def compare_prompts(jobs, before):
    counts = {}
    for job in jobs:
        args = argument_map(job['argv'])
        quote = samples(Path(args['--output']), job['rows'], args['--model-sha256'])
        need(quote == samples(Path(before[job['split']]), job['rows']),
             'quote prompt bytes or token IDs differ from the before collector')
        counts[job['id']] = len(quote)
    need(sum(counts.values()) == 76 and len(counts) == 2, 'incomplete quote prompt comparison')
    return dict(status='pass', generation_calls=76, jobs=counts,
                unique_prompts={job['split']: job['rows'] for job in jobs})


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
    jobs = contract['collector_jobs']
    phases = [dict(id='training-remote-check', kind='verify_training', outputs=['training-remote-verification.json']),
              dict(id='quote-teacher-forced-diagnostics', kind='command',
                   argv=['python3', 'training/score_decisions.py',
                         prepared['training']['directory'] + '/metrics.jsonl',
                         '--sft', 'training/sft_review_v7_quote.jsonl',
                         '--output', str(output / 'diagnostics/quote-teacher-forced.json')],
                   outputs=['diagnostics/quote-teacher-forced.json'])]
    phases += prepared['export_phases']
    phases.append(dict(id='resolve-generation', kind='resolve_generation', outputs=['generation-plan.json']))
    for index, job in enumerate(jobs):
        phases.append(dict(id=job['id'] + '-collect', kind='collector', job=index,
                           outputs=['_receipts/' + job['id'] + '.json']))
        phases.append(dict(id=job['id'] + '-score', kind='score', job=index,
                           outputs=['generation/' + job['id'] + '/structural-score.json']))
    phases.append(dict(id='before-prompts', kind='compare_prompts', outputs=['prompt-comparison.json']))
    for index, job in enumerate(jobs):
        # The collector names the split holdout; the manipulation instrument names it heldout.
        split = {'train': 'train', 'holdout': 'heldout'}[job['split']]
        report = 'manipulation/' + job['split'] + '.json'
        argv = ['node', 'training/quote/manipulation.mjs', '--run',
                resolve(argument_map(job['argv'])['--output'], parameters), '--split', split]
        if split == 'train':
            argv += ['--reasons', 'training/explanations/reasons.json']
        phases.append(dict(id=job['id'] + '-manipulation', kind='manipulation', job=index,
                           argv=argv + ['--out', str(output / report)], outputs=[report]))

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
            with tempfile.TemporaryDirectory(prefix='quote-remote-check-') as tmp:
                verified = verify_training_receipts(archive, prepared['training_receipts'], Path(tmp))
            save(directory / unit['outputs'][0], verified)
        elif kind == 'resolve_generation':
            model = directory / 'exports/quote/jovovich.gguf'
            audit = read(model.parent / 'export-audit.json')
            need(audit.get('valid') is True and audit['adapted'] == 3 and audit['metadata_equal'] is True and
                 audit['model']['sha256'] == digest(model), 'export audit/model binding failed')
            parameters['QUOTE_UPDATE100_SHA256'] = audit['model']['sha256']
            tracked[model] = identity(model)
            save(directory / 'generation-plan.json', dict(jobs=resolve(jobs, parameters), parameters=parameters))
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
            save(directory / unit['outputs'][0],
                 compare_prompts(read(directory / 'generation-plan.json')['jobs'], prepared['before_collectors']))
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
            if kind == 'manipulation':
                job = read(directory / 'generation-plan.json')['jobs'][unit['job']]
                report = read(directory / unit['outputs'][0])
                collected = Path(argument_map(job['argv'])['--output'])
                need(report['coverage']['source_order_verified'] is True and
                     report['totals']['cases'] == job['rows'] and
                     report['run']['generations_sha256'] == digest(collected / 'generations.jsonl'),
                     'manipulation report does not cover the archived quote generations')
        guard()
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
    completion = dict(status='native_evaluation_completed', semantic_audit='pending', arm='quote',
                      run_id=prepared['run_id'], generation_calls=76, parity_rows=5, structural_reports=2,
                      teacher_forced_reports=1, manipulation_reports=2,
                      checkpoint_policy='Export update100 only; selected_update in diagnostics is informational.',
                      plan_sha256=plan_sha256, finished_utc=now(), bindings=prepared['bindings'])
    save(output / 'completion.json', completion)
    receipt = archive.sync_unit('completion', {'completion.json': output / 'completion.json'}, sequence=sequence)
    result = dict(completion, archive_status='verified', remote_verification=receipt)
    save(output / '_receipts/completion.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    sub.add_parser('derive').add_argument('--check', action='store_true')
    for mode in ('preflight', 'run'):
        command = sub.add_parser(mode)
        command.add_argument('--quote-run', type=Path, required=True)
        command.add_argument('--contract', type=Path, required=True)
        command.add_argument('--before-collectors', type=Path, nargs=2, required=True,
                             metavar=('TRAIN_DIR', 'HOLDOUT_DIR'))
        command.add_argument('--output', type=Path, required=True)
        command.add_argument('--run-id', required=True)
        if mode == 'run':
            command.add_argument('--token-file', type=Path)
    args = parser.parse_args()
    try:
        if args.mode == 'derive':
            template, contract = local(TEMPLATE), local(CONTRACT, existing=False)
            if args.check:
                check_contract(contract, template)
            else:
                with contract.open('xb') as stream:
                    stream.write(render(derive(template)))
            print(json.dumps(dict(status='matches' if args.check else 'derived', contract=CONTRACT)))
            return
        prepared = prepare(args.contract, args.quote_run, args.before_collectors, args.output, args.run_id)
        if args.mode == 'preflight':
            print(json.dumps(dict(status='preflight_passed', bindings=len(prepared['bindings']),
                                  parity_rows=[0, 1, 2, 3, 51], generation_calls=76)))
            return
        token = args.token_file.read_text().strip() if args.token_file else os.environ.get('HF_TOKEN', '')
        archive = DurableArchive(HFTransport('ataeff/jovovich', token), args.run_id,
                                 'experiments/explanation-order')
        print(json.dumps(execute(archive, prepared, local(args.output, existing=False))))
    except (RuntimeError, OSError, ValueError, ArchiveError) as error:
        # Run mode holds a credential; never propagate transport text from it.
        detail = str(error) if args.mode != 'run' else (
            'stopped; inspect closed phase evidence (' + type(error).__name__ + ')')
        print('evaluate_quote: ' + detail, file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
