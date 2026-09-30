"""Collect the completed joint-review experiment without changing evidence bytes."""
import hashlib
import json
from pathlib import Path
import re


RESULTS = 'training/results/2026-10-01-joint-review'
MODEL_FILES = (
    'plan.json', 'metrics.jsonl', 'scores.json', 'resource.json', 'training-source.json',
    'selected-model.json', 'export-audit.json', 'parity.jsonl',
    'control-evaluation-jobs.json', 'control-evaluation-model-check.json',
    'joint-evaluation-jobs.json', 'joint-evaluation-model-check.json',
    'control-train-shared.jsonl', 'control-audit-natural.jsonl', 'control-audit-shared.jsonl',
    'joint-train-natural.jsonl', 'joint-train-shared.jsonl', 'joint-diagnostics-natural.jsonl',
    'joint-audit-natural.jsonl', 'joint-audit-shared.jsonl', 'generation-summary.json',
    'semantic-assessment.json', 'trajectory-assessment.json', 'hf-weights.json',
)
REFERENCE_FILES = (
    'infer-experiment.c', 'independent-jovovich-audit.json', 'diff-shape-audit.jsonl',
    'control-diff-shape-assessment.json',
    'joint-train-manual-judgments.json', 'joint-eval-manual-judgments.json',
    'assess_joint_semantics.py',
    'shape-control-scope.json', 'matched-shape-cases.jsonl', 'matched-shape-plan.json',
    'probe_matched_shape.mjs', 'prepare_matched_shape.py',
    'run_joint_review.py', 'run_joint_evaluation.py', 'evaluate_joint_reviews.mjs',
    'summarize_joint_reviews.mjs', 'prepare_joint_run.py', 'assess_joint_trajectory.py',
    'representation-next-probe.json', 'trace-sigpipe.patch', 'trace-sigpipe-test.patch',
    'archive_joint_weights.py', 'collect_joint_review.py', 'archive_joint_evidence.py',
)
SOURCE_FILES = (
    'training/train_mlp.c', 'training/score_decisions.py', 'training/score_training.py',
    'training/prepare.py', 'training/merge_mlp.c', 'training/probe_mlp.c',
    'training/probe_tokenization.c', 'training/export_adapter.c',
    'training/evaluate.py', 'training/evaluate_review.mjs', 'training/train_head.c',
    'training/sft_review_v2.jsonl', 'training/sft_review_v3.jsonl', 'training/review_holdout_v2.jsonl',
    'prompts/identity.txt', 'bin/jovovich.mjs', 'src/infer.c', 'model.json', 'Makefile',
    'test/joint.c', 'test/weighting.c', 'test/optimizer.c', 'test/mlp.c', 'test/head.c',
    'test/runner.test.mjs', 'test/decision_score.test.mjs', 'test/training_score.test.mjs',
    'test/prepare_pairs.test.mjs', 'test/chatml.test.mjs',
    'training/results/2026-09-29-small-step/probe_shared_prefix.mjs',
    'training/results/2026-09-29-verdict-balance/verify_verdict_export.py',
    'training/results/2026-09-29-convergence/check_convergence_export.py',
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def test_counts(data):
    text = data.decode('utf-8')
    values = {key: re.findall(r'(?:^|\n)(?:ℹ|#) ' + key + r' (\d+)(?:\n|$)', text)
              for key in ('tests', 'pass', 'fail')}
    require(all(len(v) == 1 for v in values.values()), 'test log lacks one complete Node summary')
    counts = {key: int(value[0]) for key, value in values.items()}
    require(counts['tests'] == counts['pass'] and counts['fail'] == 0, 'test log reports incomplete or failed tests')
    native = ('head', 'mlp', 'optimizer', 'weighting', 'joint')
    require(all(f'./build/test-{name}\n' in text for name in native), 'test log omits a required native test command')
    return dict(native_tests=len(native), node_tests=counts['tests'], node_failures=counts['fail'])


def main():
    root = Path.cwd().resolve()
    ref = Path(__file__).resolve().parent
    out = root / RESULTS
    require(not out.exists(), 'results directory already exists')
    evidence, origins = {}, {}

    def collect(source, name):
        require(name not in evidence, f'duplicate evidence name: {name}')
        require(source.is_file(), f'missing required evidence: {source}')
        evidence[name] = source.read_bytes()
        try:
            runtime = str(source.relative_to(root))
        except ValueError:
            runtime = str(source)
        origins[name] = dict(runtime_path=runtime, absolute_runtime_path=str(source.resolve()),
                             archived_path=RESULTS + '/' + name)

    for name in MODEL_FILES:
        collect(root / 'models' / ('joint-review-' + name), name)
    for name in REFERENCE_FILES:
        collect(ref / name, name)
    for name in ('matched-shape-control.jsonl', 'matched-shape-summary.json'):
        collect(root / 'models' / name, name)
    collect(root / 'models/joint-tests.txt', 'tests-before.txt')
    collect(root / 'models/joint-tests-final.txt', 'tests-after.txt')
    optional = ref / 'joint-next-control.json'
    if optional.is_file():
        collect(optional, optional.name)
    source_hashes = {name: sha((root / name).read_bytes()) for name in SOURCE_FILES}
    parsed = {}
    for name, data in evidence.items():
        if name.endswith('.json'):
            parsed[name] = json.loads(data)
        elif name.endswith('.jsonl'):
            require(data.endswith(b'\n'), f'incomplete JSONL: {name}')
            parsed[name] = [json.loads(line) for line in data.splitlines()]
    plan, selected, scores = (parsed[name] for name in ('plan.json', 'selected-model.json', 'scores.json'))
    require(scores['objective'] == 'joint' and selected['update'] == scores['selected_update'], 'joint selection disagrees')
    require(scores['selected_update'] in (25, 50, 100), 'joint selection is outside the declared saved updates')
    require(scores['metrics_sha256'] == sha(evidence['metrics.jsonl']), 'scores refer to different metrics')
    require(scores['sft_sha256'] == source_hashes['training/sft_review_v2.jsonl'], 'scores refer to a different corpus')
    require(parsed['resource.json']['exit_code'] == 0 and parsed['resource.json']['sources_unchanged'], 'training did not complete unchanged')
    audit = parsed['export-audit.json']
    require(audit['valid'] and audit['metadata_equal'] and audit['unchanged'] == 288 and audit['adapted'] == 3,
            'selected export failed its byte audit')
    require(audit['model']['sha256'] == selected['sha256'], 'export audit refers to a different selected model')
    require(all(row['pass'] and row['argmax_agree'] == row['completion_tokens'] for row in parsed['parity.jsonl']),
            'cached/exported parity did not pass')
    require(parsed['training-source.json']['plan_sha256'] == sha(evidence['plan.json']), 'training plan hash changed')
    require(source_hashes['training/train_mlp.c'] == plan['frozen_training']['source']['sha256'], 'training source changed')
    frozen = plan['frozen_evaluation']
    require(sha(evidence['infer-experiment.c']) == frozen['infer']['sha256'], 'inference experiment snapshot hash changed')
    for key in ('host', 'corpus', 'diagnostics', 'identity', 'scorer', 'shared_helper'):
        require(source_hashes[frozen[key]['path']] == frozen[key]['sha256'], f'frozen source changed: {key}')
    for key, name in [('probe', 'evaluate_joint_reviews.mjs'), ('controller', 'run_joint_evaluation.py'), ('audit_cases', 'diff-shape-audit.jsonl')]:
        require(sha(evidence[name]) == frozen[key]['sha256'], f'frozen evidence changed: {key}')
    require(sha(evidence['run_joint_review.py']) == plan['training_runner']['sha256'], 'training runner changed')
    cohort_counts = {}
    for arm, modes in [('control', [('train-shared', 40), ('audit-natural', 8), ('audit-shared', 8)]),
                       ('joint', [('train-natural', 40), ('train-shared', 40), ('diagnostics-natural', 12), ('audit-natural', 8), ('audit-shared', 8)])]:
        model_hash = selected['sha256'] if arm == 'joint' else plan['comparator']['model_sha256']
        check = parsed[arm + '-evaluation-model-check.json']
        require(check['unchanged'] and check['sha256'] == model_hash, f'model changed: {arm}')
        require(all(job['exit_code'] == 0 for job in parsed[arm + '-evaluation-jobs.json']), f'evaluation job failed: {arm}')
        for mode, count in modes:
            name = f'{arm}-{mode}.jsonl'
            rows = parsed[name]
            require(len(rows) == len({row['name'] for row in rows}) == count, f'incomplete cohort: {name}')
            require(all(row['model_sha256'] == model_hash and row['returncode'] == 0 and
                        row['infer_source_sha256'] == frozen['infer']['sha256'] and
                        row['runner_sha256'] == frozen['runner']['sha256'] for row in rows), f'cohort provenance mismatch: {name}')
            cohort_counts[name] = count
    require(sum(cohort_counts.values()) == 164, 'generation count disagrees')
    summary = parsed['generation-summary.json']
    require(summary['protocol']['generated_responses'] == 164, 'generation summary count disagrees')
    for arm, cohorts in summary['cohorts'].items():
        for name, cohort in cohorts.items():
            require(cohort['counts']['cases'] == cohort_counts[f'{arm}-{name}.jsonl'], 'summary cohort count disagrees')
    matched_plan, matched_rows = parsed['matched-shape-plan.json'], parsed['matched-shape-control.jsonl']
    require(matched_plan['model']['sha256'] == plan['comparator']['model_sha256'], 'matched probe used a different control model')
    for key in ('runner', 'infer', 'host'):
        require(matched_plan['sources'][key]['sha256'] == frozen[key]['sha256'], f'matched probe changed the main {key}')
    for key, name in [('cases', 'matched-shape-cases.jsonl'), ('wrapper', 'probe_matched_shape.mjs'),
                      ('scope_assessment', 'shape-control-scope.json'), ('baseline_receipts', 'control-train-shared.jsonl')]:
        require(matched_plan['sources'][key]['sha256'] == sha(evidence[name]), f'matched source changed: {key}')
    require(len(matched_rows) == len({row['name'] for row in matched_rows}) == 8, 'incomplete matched-shape cohort')
    require([row['name'] for row in matched_rows] == matched_plan['case_ids'] ==
            [row['name'] for row in parsed['matched-shape-cases.jsonl']], 'matched case IDs/order changed')
    require(all(row['model_sha256'] == plan['comparator']['model_sha256'] and
                row['kind'] == 'matched-shape' and row['mode'] == 'shared' and
                row['returncode'] == 0 and row.get('signal') is None and
                row['plan_sha256'] == sha(evidence['matched-shape-plan.json']) and
                row['source_sha256'] == sha(evidence['matched-shape-cases.jsonl']) and
                row['probe_source_sha256'] == sha(evidence['probe_matched_shape.mjs']) and
                row['infer_source_sha256'] == frozen['infer']['sha256'] and
                row['runner_sha256'] == frozen['runner']['sha256'] and
                row['host_sha256'] == frozen['host']['sha256'] for row in matched_rows),
            'matched-shape cohort provenance mismatch')
    model_lock = json.loads((root / 'model.json').read_bytes())
    require(model_lock['stage'] == 'base' and model_lock['sha256'] == plan['fixed_training']['base_sha256'], 'runtime base lock changed')
    manifest = dict(
        parent_commit=plan['parent_commit'], notorch_commit=plan['fixed_training']['notorch_pin'], base_model=model_lock,
        training=dict(objective='joint', **plan['fixed_training'], normalization=plan['objective'],
                      checkpoint_selection=plan['checkpoint_selection']),
        source_sha256=source_hashes, evidence_sha256={name: sha(data) for name, data in evidence.items()},
        selected_model=selected, training_source=parsed['training-source.json'],
        experiment_inference=dict(source='src/infer.c', evidence='infer-experiment.c', sha256=frozen['infer']['sha256'],
                                  runner_sha256=frozen['runner']['sha256'], current_source_sha256=source_hashes['src/infer.c'],
                                  distinction='The experiment used the preserved source snapshot. The current source records the subsequent SIGPIPE/output-error cleanup.'),
        evidence_bytes='All evidence files are copied byte-for-byte. Embedded paths and source hashes remain exactly as recorded.',
        runtime_path_prefix_mapping={str(root) + '/': './', str(ref) + '/': RESULTS + '/'},
        evidence_origins=origins, trace_storage='Every cohort record embeds the complete native trace object, sampled IDs and original trace SHA; standalone trace files are recoverable with JSON.stringify(trace) plus one newline.',
        manual_aggregation=dict(helper='assess_joint_semantics.py',
            scope='Reaggregates the recorded run with its hash-bound manual judgments. Restore its models/ evidence and standalone traces from the embedded objects first. Fresh generations require fresh human judgments and updated bindings; these historical labels are not an automatic evaluator.'),
        validation=dict(before=test_counts(evidence['tests-before.txt']), after=test_counts(evidence['tests-after.txt']),
                        export_audit=parsed['export-audit.json'], parity_rows=[row['row'] for row in parsed['parity.jsonl']]),
        result_counts=dict(cohorts=cohort_counts, main_generated_responses=164, matched_generated_responses=8,
                           generated_responses=172, decision_readouts=101, full_readouts=5),
        runtime_model_promoted=False, optional_evidence={'joint-next-control.json': optional.is_file()},
        archive_receipt='hf-evidence.json is created after remote verification and excluded from this frozen manifest.',
        reproduction=[
            'Run from the repository root in an isolated checkout with unused models/ outputs and an unused /tmp/jovovich-joint-review-selected-2948c91.gguf.',
            'unset JOVOVICH_CHAT_TEMPLATE JOVOVICH_INFER',
            'git submodule update --init deps/notorch',
            'Restore the checksum-pinned base as models/base-qwen.gguf and the selected smaller-step comparator as models/decision-small-step-selected.gguf.',
            f'For the recorded inference source, copy {RESULTS}/infer-experiment.c to src/infer.c in the isolated checkout before building.',
            'make harness train-mlp merge-mlp probe-mlp',
            'python3 training/prepare.py models/joint-review.bin --sft training/sft_review_v2.jsonl --sft-only --review-pairs models/joint-review.pairs',
            f'python3 {RESULTS}/prepare_joint_run.py',
            'The preparer reconstructs a fresh plan bound to the current build and copied helpers; retain its hashes separately from the archived original plan.',
            f'python3 {RESULTS}/run_joint_review.py',
            f'python3 {RESULTS}/run_joint_evaluation.py control',
            f'python3 {RESULTS}/prepare_matched_shape.py --template {RESULTS}/matched-shape-plan.json --output models/matched-shape-plan.json',
            f'node {RESULTS}/probe_matched_shape.mjs --output models/matched-shape-control.jsonl --trace-dir models/matched-shape-control-traces --plan models/matched-shape-plan.json',
            'Assess the eight matched-template responses against their exact cases and record the separate models/matched-shape-summary.json; the main generation summary retains 164 responses.',
            f'python3 {RESULTS}/run_joint_evaluation.py joint',
            f'node {RESULTS}/summarize_joint_reviews.mjs',
            f'python3 {RESULTS}/assess_joint_trajectory.py',
            'Review complete generated responses against their exact diff and rules to produce the separate semantic assessment.',
        ])
    out.mkdir()
    for name, data in evidence.items():
        with (out / name).open('xb') as target:
            target.write(data)
    with (out / 'manifest.json').open('x') as target:
        json.dump(manifest, target, indent=2)
        target.write('\n')
    print(json.dumps(dict(path=str(out), evidence_files=len(evidence), source_files=len(source_hashes), byte_preserving=True)))


if __name__ == '__main__':
    main()
