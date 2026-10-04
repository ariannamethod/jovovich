#!/usr/bin/env python3
"""Verify the quote-first corpus natively and bind its launch to the recovered before run."""
import argparse
import copy
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'training'))
sys.path.insert(0, str(ROOT / 'training/explanations'))
from prepare import prepare, review_pairs, review_prefixes
from verify_native import binding, save, command, require
from run_training import validate_plan
from evaluate_quote import SCHEMA as QUOTE_SCHEMA, TEMPLATE, check_contract
from durable_archive import DurableArchive, HFTransport
from after_recovery.preflight import INFRASTRUCTURE

ARMS = {'before': 'training/sft_review_v6_before.jsonl', 'quote': 'training/sft_review_v7_quote.jsonl'}


def native(base, out):
    base, out = base.resolve(), out.resolve()
    require(not out.exists(), 'output directory must be new')
    model = json.loads((ROOT / 'model.json').read_text())
    sources = [Path(__file__).resolve(), *[ROOT / p for p in (
        'training/explanations/verify_native.py', 'Makefile', 'training/train_mlp.c',
        'training/probe_pairs.c', 'training/probe_tokenization.c', 'src/infer.c', 'training/prepare.py',
        'training/explanations/build_corpora.py', 'training/explanations/reasons.json',
        'training/quote/build.mjs', 'training/sft_review_v5.jsonl', *ARMS.values(),
        'deps/notorch/examples/bpe.c', 'deps/notorch/examples/bpe.h', 'deps/notorch/notorch.c',
        'deps/notorch/notorch.h', 'deps/notorch/gguf.c', 'deps/notorch/gguf.h',
        'deps/notorch/harness/runtime.c', 'deps/notorch/harness/arch_llama.c')]]
    frozen = [binding(p) for p in [base, *sources]]
    require(frozen[0]['sha256'] == model['sha256'] and frozen[0]['bytes'] == model['bytes'],
            'base differs from pinned model.json')
    out.mkdir(parents=True)
    save(out / 'bindings.json', {'files': frozen, 'notorch_commit': subprocess.check_output(
        ['git', '-C', str(ROOT / 'deps/notorch'), 'rev-parse', 'HEAD'], text=True).strip()})
    command(['make', '-j2', 'probe-pairs', 'probe-tokenization'], out, 'build')
    binaries = [ROOT / 'build/jovovich-probe-pairs', ROOT / 'build/jovovich-probe-tokenization']
    built = [binding(p) for p in binaries]
    save(out / 'binary-bindings.json', {'files': built})
    original = [json.loads(s) for s in (ROOT / 'training/sft_review_v5.jsonl').read_text().splitlines()]
    reasons = {r['id']: r for r in json.loads((ROOT / 'training/explanations/reasons.json').read_text())['rows']}
    corpora, maps, datasets, summaries = {}, {}, [], {}
    for arm, name in ARMS.items():
        source = ROOT / name
        data = [json.loads(s) for s in source.read_text().splitlines()]
        require(len(data) == len(original) == 76, 'wrong corpus length')
        corpora[arm] = data
        dataset, pairs = out / (arm + '.bin'), out / (arm + '.pairs.bin')
        prepare(source, None, dataset, pairs, pair_format=2)
        records = command([binaries[0], base, dataset, pairs], out, arm, jsonl=True)
        require(records[0] == {'stage': 'pair_configuration', 'pair_map_version': 2, 'rows': 76, 'pairs': 26},
                'native pair configuration differs')
        require(records[-1] == {'stage': 'pair_completion', 'pass': True, 'review_rows': 52},
                'native probe incomplete')
        rows = {r['row']: r for r in records[1:-1]}
        require(len(rows) == len(records) - 2 == 52, 'native duplicate/missing review')
        require(set(rows) == {i for pair in review_pairs(data) for i in pair}, 'native review coverage differs')
        prefixes = review_prefixes(data)
        for i, row in rows.items():
            require(row['decision_prefix'] == prefixes[i] and
                    row['decision_prefix_bytes'] == len(prefixes[i].encode()), 'prefix provenance mismatch')
            require(row['total_tokens'] == row['prompt_tokens'] + len(row['answer_ids']), 'token counts differ')
            require(row['prompt_tokens'] + 512 <= 8192, 'generation context capacity exceeded')
            require(row['total_tokens'] < 4096, 'training context capacity exceeded')
            require(len(row['answer_ids']) <= 512, 'gold answer exceeds shared generation budget')
        maps[arm] = rows
        summaries[arm] = {'review_rows': len(rows), 'pairs': len(review_pairs(data)),
                          'decision_tokens': len(rows),
                          'residual_tokens': sum(len(r['answer_ids']) - 1 for r in rows.values()),
                          'max_prompt_tokens': max(r['prompt_tokens'] for r in rows.values()),
                          'max_total_tokens': max(r['total_tokens'] for r in rows.values()),
                          'max_answer_tokens_including_eos': max(len(r['answer_ids']) for r in rows.values()),
                          'verdict_position_min': min(r['decision_position'] for r in rows.values()),
                          'verdict_position_max': max(r['decision_position'] for r in rows.values())}
        datasets.append(dataset)
    comparisons, unchanged = [], 0
    for i, old in enumerate(original):
        before, quote = corpora['before'][i], corpora['quote'][i]
        if old['kind'] != 'review':
            require(before == quote == old, 'nonreview row changed')
            unchanged += 1
            continue
        require(before['messages'][:2] == quote['messages'][:2], 'arm prompts differ')
        a = json.loads(before['messages'][2]['content']); b = json.loads(quote['messages'][2]['content'])
        require(list(a) == list(b) == ['analysis', 'findings'], 'wrong key order')
        require(b['findings'] == a['findings'], 'arm findings differ')
        require(before['id'] in reasons and
                b['analysis'] == 'Rule: ' + reasons[before['id']]['evidence']['rule'] + ' ' + a['analysis'],
                'quote analysis is not the rule-prefixed before analysis')
        ra, rq = maps['before'][i], maps['quote'][i]
        require(ra['prompt_tokens'] == rq['prompt_tokens'], 'native prompt counts differ')
        require(rq['decision_position'] > ra['decision_position'], 'quote verdict did not move after the rule')
        require((ra['decision_target_id'], ra['decision_alternative_id']) ==
                (rq['decision_target_id'], rq['decision_alternative_id']), 'arm verdict target IDs differ')
        comparisons.append({'id': old['id'], 'row': i, 'before_position': ra['decision_position'],
                            'quote_position': rq['decision_position'],
                            'before_answer_tokens': len(ra['answer_ids']), 'quote_answer_tokens': len(rq['answer_ids']),
                            'target_id': ra['decision_target_id'], 'alternative_id': ra['decision_alternative_id']})
    alignment = command([binaries[1], base, *datasets], out, 'chatml', jsonl=True)
    require(len(alignment) == 2 and all(r['pass'] and r['failures'] == 0 for r in alignment), 'ChatML mismatch')
    require(frozen == [binding(Path(f['path'])) for f in frozen], 'source/input changed during verification')
    require(built == [binding(Path(f['path'])) for f in built], 'binary changed during verification')
    report = {'status': 'pass', 'arms': summaries, 'identical_prompt_rows': len(comparisons),
              'unchanged_nonreview_rows': unchanged,
              'native_chatml_comparisons': sum(r['comparisons'] for r in alignment),
              'comparisons': comparisons, 'inference_calls': 0, 'training_updates': 0}
    save(out / 'verification.json', report)
    print(json.dumps({k: v for k, v in report.items() if k != 'comparisons'}))


def matches(path, item):
    if path.is_symlink() or not path.is_file():
        return False
    found = binding(path)
    return (found['bytes'], found['sha256']) == (item['bytes'], item['sha256'])


def bind(recovered, native_dir, prefix, output, repo, contract, infrastructure):
    repo, recovered, native_dir, output, contract, infrastructure = (
        p.resolve() for p in (repo, recovered, native_dir, output, contract, infrastructure))
    require(not output.exists(), 'output plan already exists')
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', prefix), 'invalid run prefix')

    def inside(path):
        path = path.resolve()
        require(path.is_relative_to(repo), 'quote input must be inside the repository: ' + str(path))
        item = binding(path)
        item['path'] = str(path.relative_to(repo))
        return item

    evaluation = inside(contract)
    require(json.loads(contract.read_text()).get('schema') == QUOTE_SCHEMA, 'evaluation contract is not the quote contract')
    check_contract(contract, repo / TEMPLATE)
    receipt =json.loads((recovered / '_durable-recovery.json').read_text())
    require(receipt.get('verified_remote_bytes') is True, 'recovery receipt does not verify remote bytes')
    units = [u for u in receipt['units'] if u['unit_id'] == 'completion']
    require(len(units) == 1 and any(f['name'] == 'completion.json' for f in units[0]['files']),
            'recovered archive has no completion unit')
    archived = {f['name']: {'bytes': f['size'], 'sha256': f['sha256']} for u in receipt['units'] for f in u['files']}
    for name in ('plan.json', 'completion.json'):
        require(name in archived and matches(recovered / name, archived[name]),
                'recovered file differs from its archive receipt: ' + name)
    completion = json.loads((recovered / 'completion.json').read_text())
    before = json.loads((recovered / 'plan.json').read_text())
    require(completion.get('acknowledged_updates') == 100, 'before completion did not acknowledge 100 updates')
    require(completion.get('return_code') == 0, 'before completion return code is not 0')
    require(completion.get('plan_sha256') == archived['plan.json']['sha256'],
            'completion plan_sha256 differs from recovered plan.json')
    require(completion.get('bindings') == before['bindings'], 'completion bindings differ from recovered plan')
    require(before.get('arm') == 'before', 'recovered plan is not the before arm')
    require(receipt.get('run_id') == before.get('run_id'), 'recovery receipt belongs to another run')
    spec_path = repo / 'training/explanations/plan.json'
    spec = json.loads(spec_path.read_text())['training']
    require(before.get('scientific_plan_sha256') == binding(spec_path)['sha256'],
            'before scientific plan differs from this checkout')
    # A copied plan equals itself; the frozen scientific plan is the independent reference.
    argv, template = before['argv'], spec['argv_template']
    require(len(argv) == len(template) and all(argv[i] == template[i] for i in (0, 4, 5, 6, 7, 8)),
            'before argv differs from the frozen training argv')
    require(before.get('environment') == spec['native_environment'],
            'before environment differs from the frozen native environment')
    bound = {b['path']: b for b in before['bindings']}
    trainer, base = bound[argv[0]], bound[argv[1]]
    require(matches(repo / argv[0], trainer), 'trainer binary differs from the before run: ' + argv[0])
    require(matches(repo / argv[1], base) and base['sha256'] == spec['base_expected_sha256'],
            'base model differs from the before run: ' + argv[1])
    artifact = lambda path: Path(path).parts[0] == 'models'
    record = json.loads(infrastructure.read_text())
    require(isinstance(record, dict) and isinstance(record.get('infrastructure_changes'), list),
            'infrastructure record has no infrastructure_changes list')
    pending = {}
    for entry in record['infrastructure_changes']:
        require(isinstance(entry, dict) and set(entry) == {'path', 'original', 'candidate'} and
                isinstance(entry['path'], str) and entry['path'] not in pending, 'malformed infrastructure record entry')
        pending[entry['path']] = entry
    # Only the preflight's infrastructure files may differ, each exactly as one record pair states.
    changes = []
    for item in before['bindings']:
        name = item['path']
        if name in (argv[0], argv[1]) or artifact(name) or matches(repo / name, item):
            continue
        require(name in INFRASTRUCTURE, 'before source differs in this checkout: ' + name)
        entry = pending.pop(name, None)
        require(entry is not None, 'changed infrastructure has no record entry: ' + name)
        require(entry['original'] == item, 'infrastructure record original differs from the before binding: ' + name)
        require(entry['candidate'] == inside(repo / name),
                'infrastructure record candidate differs from this checkout: ' + name)
        changes.append(entry)
    for name in sorted(pending):
        require(name in INFRASTRUCTURE, 'infrastructure record path is not admitted: ' + name)
    require(not pending, 'infrastructure record entry matches no observed change: ' + ', '.join(sorted(pending)))
    # The before evaluation plan belongs to the before arm; it moves into before_artifacts.
    own = (argv[2], argv[9], before.get('evaluation_plan'))
    carried = [b for b in before['bindings'] if b['path'] not in own and
               (b['path'] in (argv[0], argv[1]) or not artifact(b['path']))]
    artifacts = [{'path': b['path'], 'sha256': b['sha256']} for b in before['bindings'] if b not in carried]
    candidates = {c['path']: c['candidate'] for c in changes}
    carried = [candidates.get(b['path'], b) for b in carried]

    report = json.loads((native_dir / 'verification.json').read_text())
    require(report.get('status') == 'pass' and report.get('identical_prompt_rows') == 52 and
            report.get('unchanged_nonreview_rows') == 24, 'quote native verification did not pass')
    recorded = json.loads((native_dir / 'bindings.json').read_text())['files']
    roots = [Path(f['path']).parents[2] for f in recorded if f['path'].endswith('/training/quote/bind_quote.py')]
    require(len(roots) == 1, 'quote native verifier binding missing or ambiguous')
    require((recorded[0]['bytes'], recorded[0]['sha256']) == (base['bytes'], base['sha256']),
            'quote native base differs from the before base')
    for item in recorded[1:]:
        path = Path(item['path'])
        require(path.is_relative_to(roots[0]), 'quote native binding escapes its recorded repository')
        name = str(path.relative_to(roots[0]))
        require(matches(repo / name, item), 'quote native source changed since verification: ' + name)

    data, pairs = native_dir / 'quote.bin', native_dir / 'quote.pairs.bin'
    added = [data, pairs, native_dir / 'verification.json', native_dir / 'bindings.json', contract, repo / TEMPLATE,
             infrastructure, *sorted(p for p in (repo / 'training/quote').iterdir() if p.is_file()),
             repo / 'training/sft_review_v7_quote.jsonl', *sorted((repo / 'test').glob('quote_*.test.mjs'))]
    paths = {b['path'] for b in carried}
    for path in added:
        item = inside(path)
        if item['path'] not in paths:
            carried.append(item)
            paths.add(item['path'])
    plan = copy.deepcopy(before)
    plan['argv'][2], plan['argv'][9] = inside(data)['path'], inside(pairs)['path']
    plan.update(run_id=prefix + '-quote', arm='quote', bindings=carried, before_artifacts=artifacts,
                evaluation_plan=evaluation['path'], infrastructure_changes=changes,
                expected_initial_lora_sha256=completion['initial_lora_sha256'],
                before_completion={'run_id': before['run_id'], 'revision': receipt['revision'],
                                   'manifest_sha256': units[0]['manifest_sha256'],
                                   'completion_sha256': archived['completion.json']['sha256']})
    validate_plan(plan, repo)
    save(output, plan)
    print(json.dumps({'status': 'quote-bound', 'output': str(output), 'run_id': plan['run_id'],
                      'bindings': len(carried), 'before_artifacts': len(artifacts),
                      'infrastructure_changes': len(changes)}))


def recover(run_id, revision, out, prefix, connect):
    """Restore one archived run at a pinned revision; connect() is called only after local checks."""
    require(re.fullmatch(r'[0-9a-f]{40}', revision), 'recovery revision must be a full lowercase commit SHA')
    require(not out.exists() and not out.is_symlink(), 'recovery destination already exists')
    result = DurableArchive(connect(), run_id, prefix).recover(out, revision)
    print(json.dumps({'status': 'recovered', 'run_id': run_id, 'revision': result['revision'],
                      'units': len(result['units']), 'out': str(out)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    nat = sub.add_parser('native')
    nat.add_argument('--base', type=Path, required=True)
    nat.add_argument('--out', type=Path, required=True)
    bnd = sub.add_parser('bind')
    bnd.add_argument('--before-recovered', type=Path, required=True)
    bnd.add_argument('--native', type=Path, required=True)
    bnd.add_argument('--run-prefix', required=True)
    bnd.add_argument('--out', type=Path, required=True)
    bnd.add_argument('--repo', type=Path, default=ROOT)
    bnd.add_argument('--evaluation-contract', type=Path, required=True)
    bnd.add_argument('--infrastructure-record', type=Path, required=True)
    rec = sub.add_parser('recover')
    rec.add_argument('--run-id', required=True)
    rec.add_argument('--revision', required=True)
    rec.add_argument('--out', type=Path, required=True)
    rec.add_argument('--token-file', type=Path, required=True)
    rec.add_argument('--prefix', default='experiments/explanation-order')
    args = parser.parse_args()
    try:
        if args.mode == 'native':
            native(args.base, args.out)
        elif args.mode == 'recover':
            # The credential is read by this process only, after the local checks.
            recover(args.run_id, args.revision, args.out, args.prefix,
                    lambda: HFTransport('ataeff/jovovich', args.token_file.read_text().strip()))
        else:
            bind(args.before_recovered, args.native, args.run_prefix, args.out, args.repo, args.evaluation_contract,
                 args.infrastructure_record)
    except (RuntimeError, ValueError) as error:
        print('bind_quote: ' + str(error), file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
