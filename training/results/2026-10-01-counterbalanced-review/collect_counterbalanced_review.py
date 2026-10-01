"""Collect the completed counterbalanced experiment without changing evidence bytes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from archive_counterbalanced_weights import (
    ARMS, COHORTS, CONTROL_SHA256, FileHashes, STEM,
    collect as validate_weights, require, validate_completed_evaluation,
)


RESULTS = 'training/results/2026-10-01-counterbalanced-review'
MODEL_FILES = (
    'plan.json', 'metrics.jsonl', 'scores.json', 'resource.json', 'training-source.json',
    'selected-model.json', 'export-audit.json', 'parity.jsonl', 'generation-summary.json',
    'semantic-assessment.json', 'trajectory-assessment.json', 'initial-comparison.json',
    'control-replay.json', 'hf-weights.json',
)
REFERENCE_FILES = (
    'corpus-audit.json', 'fresh-transfer.jsonl', 'fresh-transfer-audit.json',
    'build_fresh_transfer.py', 'audit_fresh_transfer_independent.py', 'finalize_fresh_transfer.mjs',
    'fresh-transfer-independent-audit.json', 'protocol-audit.json', 'orchestration-audit.json',
    'native-preflight.json', 'summarize_native_preflight.py', 'assess_counterbalanced_trajectory.py',
    'assess_counterbalanced_replay.py', 'control-train-semantic-audit.json', 'semantic-aggregation-audit.json',
    'probe_counterbalanced.c', 'counterbalanced-manual-judgments.json',
    'prepare_counterbalanced_run.py', 'run_counterbalanced_review.py',
    'run_counterbalanced_evaluation.py', 'evaluate_counterbalanced_reviews.mjs',
    'summarize_counterbalanced_reviews.mjs', 'assess_counterbalanced_semantics.py',
    'archive_counterbalanced_weights.py', 'collect_counterbalanced_review.py',
    'archive_counterbalanced_evidence.py', 'nuisance-cue-audit.json',
    'finish_counterbalanced_generation.py', 'archival-reproduction-audit.json',
)
SOURCE_FILES = (
    'training/train_mlp.c', 'training/score_decisions.py', 'training/score_training.py',
    'training/prepare.py', 'training/merge_mlp.c', 'training/probe_mlp.c',
    'training/probe_tokenization.c', 'training/export_adapter.c',
    'training/evaluate.py', 'training/evaluate_review.mjs', 'training/train_head.c',
    'training/sft_review_v2.jsonl', 'training/sft_review_v3.jsonl',
    'training/sft_review_v4.jsonl', 'training/build_review_v4.mjs',
    'training/review_holdout_v2.jsonl', 'prompts/identity.txt',
    'bin/jovovich.mjs', 'src/infer.c', 'model.json', 'Makefile',
    'test/joint.c', 'test/weighting.c', 'test/optimizer.c', 'test/mlp.c', 'test/head.c',
    'test/runner.test.mjs', 'test/decision_score.test.mjs', 'test/training_score.test.mjs',
    'test/prepare_pairs.test.mjs', 'test/chatml.test.mjs', 'test/review_v4.test.mjs',
    'training/results/2026-09-29-small-step/probe_shared_prefix.mjs',
    'training/results/2026-09-29-verdict-balance/verify_verdict_export.py',
    'training/results/2026-09-29-convergence/check_convergence_export.py',
    'training/results/2026-10-01-joint-review/joint-next-control.json',
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def checked_bytes(path):
    require(path.is_file(), f'missing required evidence: {path}')
    data = path.read_bytes()
    require(not re.search(rb'hf_[A-Za-z0-9]{20,}', data), f'credential-like content in archive input: {path}')
    require(not re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', data),
            f'private-key-like content in archive input: {path}')
    return data


def test_counts(data):
    text = data.decode('utf-8')
    values = {key: re.findall(r'(?:^|\n)(?:ℹ|#) ' + key + r' (\d+)(?:\n|$)', text)
              for key in ('tests', 'pass', 'fail')}
    require(all(len(v) == 1 for v in values.values()), 'test log lacks one complete Node summary')
    counts = {key: int(value[0]) for key, value in values.items()}
    require(counts['tests'] == counts['pass'] and counts['fail'] == 0,
            'test log reports incomplete or failed tests')
    native = ('head', 'mlp', 'optimizer', 'weighting', 'joint')
    require(all(f'./build/test-{name}\n' in text for name in native),
            'test log omits a required native test command')
    return dict(native_tests=len(native), node_tests=counts['tests'], node_failures=counts['fail'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-file', action='append', default=[],
                        help='additional explicit evidence basename beside this helper')
    args = parser.parse_args()
    root = Path.cwd().resolve()
    ref = Path(__file__).resolve().parent
    out = root / RESULTS
    require(not out.exists(), 'results directory already exists')
    # Replay all native completion, frozen-source, score, selection, adapter,
    # export, parity and complete-evaluation gates before creating an archive.
    hashes = FileHashes()
    _, expected_weights, weight_provenance = validate_weights(hashes)
    evidence, origins = {}, {}

    def collect(source, name):
        require(Path(name).name == name and name not in ('', '.', '..'), 'evidence name must be a basename')
        require(name not in evidence, f'duplicate evidence name: {name}')
        evidence[name] = checked_bytes(source)
        try:
            runtime = str(source.relative_to(root))
        except ValueError:
            runtime = str(source)
        origins[name] = dict(runtime_path=runtime, absolute_runtime_path=str(source.resolve()),
                             archived_path=RESULTS + '/' + name)

    for name in MODEL_FILES:
        collect(root / (STEM + '-' + name), name)
    for arm in ARMS:
        for name in ('evaluation-jobs.json', 'evaluation-model-check.json'):
            collect(root / f'{STEM}-{arm}-{name}', f'{arm}-{name}')
        for mode in COHORTS:
            collect(root / f'{STEM}-{arm}-{mode}.jsonl', f'{arm}-{mode}.jsonl')
        # Preserve the exact shard files bound by the job receipts as well as the
        # corpus-ordered concatenation used for aggregate measurements.
        for shard in (0, 1):
            name = f'{arm}-train-natural-{shard}.jsonl'
            collect(root / f'{STEM}-{name}', name)
    for name in REFERENCE_FILES + tuple(args.reference_file):
        collect(ref / name, name)
    collect(root / 'src/infer.c', 'infer-experiment.c')
    collect(root / 'models/counterbalanced-tokenization.json', 'tokenization.json')
    collect(root / 'models/counterbalanced-review-preflight.jsonl', 'native-preflight-raw.jsonl')
    collect(root / 'models/counterbalanced-build.txt', 'build.txt')
    collect(root / 'models/counterbalanced-tests.txt', 'tests-before.txt')
    final_tests = root / 'models/counterbalanced-tests-final.txt'
    if final_tests.is_file():
        collect(final_tests, 'tests-after.txt')
    parsed = {}
    for name, data in evidence.items():
        if name.endswith('.json'):
            parsed[name] = json.loads(data)
        elif name.endswith('.jsonl'):
            require(data.endswith(b'\n'), f'incomplete JSONL: {name}')
            parsed[name] = [json.loads(line) for line in data.splitlines()]
    plan, selected, scores = (parsed[name] for name in ('plan.json', 'selected-model.json', 'scores.json'))
    summary, semantics = validate_completed_evaluation(plan, selected, hashes)
    sources = set(SOURCE_FILES)
    # Capture comparator evidence and any additional plan-bound text dependency;
    # binaries/weights are separately represented by frozen hashes and receipts.
    def capture_bound(item):
        require(isinstance(item, dict) and 'path' in item and 'sha256' in item, 'invalid frozen file binding')
        lexical = Path(os.path.abspath(root / item['path']))
        hashes.verify(lexical, item['sha256'])
        if lexical.is_relative_to(root) and lexical.relative_to(root).as_posix().startswith(('build/', 'models/')):
            return
        source = lexical.resolve()
        if source.is_relative_to(root):
            name = source.relative_to(root).as_posix()
            sources.add(name)
        elif source.is_relative_to(ref):
            name = source.name
            if name not in evidence:
                collect(source, name)
            require(sha(evidence[name]) == item['sha256'], f'frozen evidence changed: {name}')
        else:
            raise ValueError(f'frozen source lies outside the experiment roots: {item["path"]}')
    for group in ('frozen_training', 'frozen_evaluation', 'preflight'):
        for item in plan[group].values():
            capture_bound(item)
    capture_bound(plan['training_runner'])
    capture_bound(plan['approved_design'])
    for key in ('selection', 'scores', 'metrics', 'corpus'):
        capture_bound(plan['comparator'][key])
    for item in plan['comparator']['previous_generations'].values():
        capture_bound(item)
    for item in parsed['native-preflight.json']['sources'] + parsed['native-preflight.json']['artifacts']:
        capture_bound(item)
    for document in (summary, semantics):
        for path, binding in document['sources'].items():
            capture_bound({'path': path, **binding})
    source_hashes = {name: sha(checked_bytes(root / name)) for name in sorted(sources)}
    require(scores['metrics_sha256'] == sha(evidence['metrics.jsonl']), 'scores refer to different metrics')
    require(scores['sft_sha256'] == source_hashes['training/sft_review_v4.jsonl'], 'scores refer to a different corpus')
    require(parsed['training-source.json']['plan_sha256'] == sha(evidence['plan.json']), 'training plan hash changed')
    frozen = plan['frozen_evaluation']
    require(sha(evidence['infer-experiment.c']) == frozen['infer']['sha256'] == source_hashes['src/infer.c'],
            'inference source changed')
    cohort_counts = {}
    for arm in ARMS:
        model_hash = selected['sha256'] if arm == 'counterbalanced' else CONTROL_SHA256
        for mode, count in COHORTS.items():
            name = f'{arm}-{mode}.jsonl'
            rows = parsed[name]
            require(len(rows) == len({row['name'] for row in rows}) == count, f'incomplete cohort: {name}')
            require(all(row['model_sha256'] == model_hash and row['returncode'] == 0 and
                        row.get('signal') is None and row['mode'] == 'natural' and
                        row['infer_source_sha256'] == frozen['infer']['sha256'] and
                        row['runner_sha256'] == frozen['runner']['sha256'] for row in rows),
                    f'cohort provenance mismatch: {name}')
            cohort_counts[name] = count
        full = {row['name']: row for row in parsed[f'{arm}-train-natural.jsonl']}
        shard_rows = parsed[f'{arm}-train-natural-0.jsonl'] + parsed[f'{arm}-train-natural-1.jsonl']
        require(len(shard_rows) == len({row['name'] for row in shard_rows}) == 52 and
                all(full.get(row['name']) == row for row in shard_rows), f'shard receipts disagree: {arm}')
    require(sum(cohort_counts.values()) == 176, 'generation count disagrees')
    weight_receipt = parsed['hf-weights.json']
    require(weight_receipt['repo'] == 'ataeff/jovovich' and weight_receipt['private'] is True and
            weight_receipt['selected_model']['sha256'] == selected['sha256'] and
            len(weight_receipt['verified_by_download']) == len(expected_weights) == 16,
            'private weight archive receipt disagrees')
    require({row['file']: {key: row[key] for key in ('bytes', 'sha256')}
             for row in weight_receipt['verified_by_download']} == expected_weights,
            'weight archive download hashes disagree')
    model_lock = json.loads((root / 'model.json').read_bytes())
    require(model_lock['stage'] == 'base' and model_lock['sha256'] == plan['fixed_training']['base_sha256'],
            'runtime base lock changed')
    manifest = dict(
        schema_version=1, parent_commit=plan['parent_commit'],
        notorch_commit=plan['fixed_training']['notorch_pin'], base_model=model_lock,
        training={**plan['fixed_training'], 'objective': 'joint',
                  'objective_definition': plan['fixed_training']['objective'],
                  'checkpoint_selection': plan['checkpoint_selection']},
        source_sha256=source_hashes, evidence_sha256={name: sha(data) for name, data in evidence.items()},
        selected_model=selected, training_source=parsed['training-source.json'],
        comparator_sha256=CONTROL_SHA256, weight_archive=weight_provenance,
        experiment_inference=dict(source='src/infer.c', evidence='infer-experiment.c', sha256=frozen['infer']['sha256'],
                                  runner_sha256=frozen['runner']['sha256']),
        evidence_bytes='All evidence files are copied byte-for-byte. Embedded paths and source hashes remain exactly as recorded.',
        runtime_path_prefix_mapping={str(root) + '/': './', str(ref) + '/': RESULTS + '/'},
        evidence_origins=origins,
        trace_storage='Each cohort record embeds its complete native trace and original trace SHA. Standalone traces can be restored with JSON.stringify(trace) plus one newline.',
        manual_aggregation=dict(helper='assess_counterbalanced_semantics.py', judgments='counterbalanced-manual-judgments.json',
            scope='Reaggregates these complete responses with their hash-bound manual judgments. Fresh responses need fresh judgments; these labels are not an automatic evaluator.'),
        validation=dict(tests=test_counts(evidence['tests-before.txt']),
                        repeated_tests=test_counts(evidence['tests-after.txt']) if 'tests-after.txt' in evidence else None,
                        export_audit=parsed['export-audit.json'], parity_rows=[row['row'] for row in parsed['parity.jsonl']]),
        result_counts=dict(cohorts=cohort_counts, generated_responses=176,
                           decision_readouts=101, full_readouts=5),
        semantic_counts={arm: {name: cohort['counts'] for name, cohort in cohorts.items()}
                         for arm, cohorts in semantics['cohorts'].items()},
        runtime_model_promoted=False,
        archive_receipt='hf-evidence.json is created after remote verification and excluded from this frozen manifest.',
        reproduction=[
            'This is a fresh experimental rerun recipe, not a command to overwrite the archived run. Use an isolated checkout containing these archived helpers, v4 source changes and historical comparator evidence. Run every command below from that checkout root. The selected output /tmp/jovovich-counterbalanced-review-selected-12f3555.gguf and models/counterbalanced-* outputs must be unused.',
            'unset JOVOVICH_CHAT_TEMPLATE JOVOVICH_INFER',
            'git submodule update --init deps/notorch',
            'Verify notorch HEAD equals the recorded pin. Restore the SHA256-pinned Qwen base at models/base-qwen.gguf and prior joint-selected comparator at models/joint-review-selected.gguf; access to the private comparator archive is required.',
            f'JOVOVICH_REPRO_ARCHIVE="{RESULTS}"',
            'JOVOVICH_REPRO_REF="$(mktemp -d /tmp/jovovich-counterbalanced-reference.XXXXXX)"',
            'cp "$JOVOVICH_REPRO_ARCHIVE"/*.py "$JOVOVICH_REPRO_ARCHIVE"/*.mjs "$JOVOVICH_REPRO_ARCHIVE"/*.c "$JOVOVICH_REPRO_REF"/',
            'cp "$JOVOVICH_REPRO_ARCHIVE/fresh-transfer.jsonl" "$JOVOVICH_REPRO_ARCHIVE/protocol-audit.json" "$JOVOVICH_REPRO_ARCHIVE/orchestration-audit.json" "$JOVOVICH_REPRO_REF"/',
            'The two copied protocol/orchestration reports are historical review records with their original paths and source versions, not newly executed audits. Retain that distinction. The following corpus, transfer and native preflight checks create fresh receipts in the scratch reference directory. Do not copy native-preflight.json or corpus-audit.json into that directory: their writers reserve new files exclusively.',
            'make harness train-mlp merge-mlp probe-mlp probe-tokenization',
            'node training/build_review_v4.mjs --output "$JOVOVICH_REPRO_REF/sft_review_v4.jsonl" --audit "$JOVOVICH_REPRO_REF/corpus-audit.json"',
            'cmp training/sft_review_v4.jsonl "$JOVOVICH_REPRO_REF/sft_review_v4.jsonl"',
            'python3 "$JOVOVICH_REPRO_REF/build_fresh_transfer.py"',
            'cmp "$JOVOVICH_REPRO_ARCHIVE/fresh-transfer.jsonl" "$JOVOVICH_REPRO_REF/fresh-transfer.jsonl"',
            'python3 "$JOVOVICH_REPRO_REF/audit_fresh_transfer_independent.py"',
            'node "$JOVOVICH_REPRO_REF/finalize_fresh_transfer.mjs"',
            'python3 training/prepare.py models/counterbalanced-review.bin --sft training/sft_review_v4.jsonl --sft-only --review-pairs models/counterbalanced-review.pairs',
            'build/jovovich-probe-tokenization models/base-qwen.gguf models/counterbalanced-review.bin > models/counterbalanced-tokenization.json 2> models/counterbalanced-tokenization.stderr',
            'cc -Ideps/notorch -Itraining -O2 -Wall -Wextra -std=gnu11 -march=native -DUSE_SIMD -o build/jovovich-probe-counterbalanced "$JOVOVICH_REPRO_REF/probe_counterbalanced.c" deps/notorch/notorch.c deps/notorch/gguf.c deps/notorch/harness/runtime.c deps/notorch/harness/arch_llama.c deps/notorch/examples/bpe.c -lm -pthread',
            'The explicit preflight compile flags describe the recorded AVX2/SIMD build. On another architecture/toolchain, review the supported native flags and record that new build; identical binary hashes and floating-point results are not promised. The moved probe source resolves train_mlp.c and ../src/infer.c through -Itraining when invoked from the repository root.',
            'build/jovovich-probe-counterbalanced models/base-qwen.gguf models/counterbalanced-review.bin models/counterbalanced-review.pairs 40 > models/counterbalanced-review-preflight.jsonl 2> models/counterbalanced-review-preflight.stderr',
            'python3 "$JOVOVICH_REPRO_REF/summarize_native_preflight.py"',
            'python3 "$JOVOVICH_REPRO_REF/prepare_counterbalanced_run.py"',
            'This freezes new paths, executable/source hashes and newly regenerated preflight receipts. Preserve the archived original plan separately. Do not change any newly frozen helper or input after this step.',
            'python3 "$JOVOVICH_REPRO_REF/run_counterbalanced_review.py"',
            'python3 "$JOVOVICH_REPRO_REF/run_counterbalanced_evaluation.py" control',
            'python3 "$JOVOVICH_REPRO_REF/run_counterbalanced_evaluation.py" counterbalanced',
            'node "$JOVOVICH_REPRO_REF/summarize_counterbalanced_reviews.mjs"',
            'finish_counterbalanced_generation.py is an optional one-shot watcher for training completion followed by new-arm evaluation; never run it in addition to the explicit new-arm evaluation command for the same outputs.',
            'Posthoc helpers are diagnostic gates with recorded-run assumptions. assess_counterbalanced_trajectory.py --initial-only requires the original training binary SHA and its specific SIMD tile comparison; full trajectory aggregation also requires that fresh initial-comparison receipt. assess_counterbalanced_replay.py demands exact replay against historical outputs. On a different build, inspect and justify a new comparison protocol rather than relabeling old evidence or weakening those guards silently.',
            'Fresh semantic assessment requires reading all newly generated complete responses and writing new model/prompt/response/trace-hash-bound judgments, including their source fragments, before assess_counterbalanced_semantics.py. Archived manual judgments cannot be assumed valid for new outputs.',
            'Archival collectors/uploaders reserve the original fixed result directory and remote experiment prefix. A later rerun needs a separately reviewed new archive destination and expected private HF head; the commands above recreate the experiment, not a second upload over this archive.',
        ])
    out.mkdir()
    for name, data in evidence.items():
        with (out / name).open('xb') as target:
            target.write(data)
    with (out / 'manifest.json').open('x') as target:
        json.dump(manifest, target, indent=2)
        target.write('\n')
    print(json.dumps(dict(path=str(out), evidence_files=len(evidence), source_files=len(source_hashes),
                         byte_preserving=True, generated_responses=176)))


if __name__ == '__main__':
    main()
