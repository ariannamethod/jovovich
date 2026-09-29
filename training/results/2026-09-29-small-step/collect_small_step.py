"""Collect the completed matched run and shared-prefix experiment."""
import hashlib
import json
from pathlib import Path

root = Path.cwd()
ref = root.parent / 'reference'
relative = 'training/results/2026-09-29-small-step'
out = root / relative
out.mkdir(exist_ok=False)
original_hashes = {}

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def copy(p, name):
    original_hashes[name] = digest(p)
    s = p.read_text()
    if p.suffix not in ('.py', '.mjs'):
        s = s.replace('/tmp/jovovich-decision-small-step-selected-e655134.gguf',
                      'models/decision-small-step-selected.gguf')
        s = s.replace(str(root) + '/', '').replace(str(ref) + '/', relative + '/')
    (out / name).write_text(s)

for suffix in ('plan.json', 'metrics.jsonl', 'scores.json', 'resource.json',
               'training-source.json', 'selected-model.json', 'export-audit.json',
               'parity.jsonl', 'evaluation-jobs.json', 'evaluation-model-check.json',
               'train-generation.jsonl', 'review.jsonl', 'prefix.jsonl',
               'hf-weights.json', 'checks.txt', 'tests.txt',
               'generation-summary.json', 'trajectory-comparison.json'):
    copy(root / ('models/decision-small-step-' + suffix), suffix)
for suffix in ('preflight.json', 'jobs.json', 'verification.json', 'control.jsonl',
               'new.jsonl', 'summary.json', 'tests.txt'):
    copy(root / ('models/shared-prefix-' + suffix), 'shared-prefix-' + suffix)
for name in ('procedure-audit.json', 'dataset-repairs.json', 'small-step-semantic-assessment.json',
             'shared-control-semantic-assessment.json', 'shared-new-semantic-assessment.json',
             'small-step-next-control.json', 'shared-prefix-plan.json',
             'run_decision_small_step.py', 'evaluate_decision_small_step.py',
             'probe_shared_prefix.mjs', 'probe_shared_prefix.test.mjs', 'run_shared_prefix.py',
             'summarize_small_step_generation.mjs', 'summarize_shared_prefix.mjs',
             'compare_small_step.py', 'trajectory-assessment.json',
             'assess_small_step_natural.mjs', 'assess_shared_new_semantics.mjs',
             'shared-new-judgments.json', 'collect_small_step.py',
             'archive_small_step_evidence.py'):
    copy(ref / name, name)

source_files = [
    'training/train_mlp.c', 'training/score_decisions.py', 'training/score_training.py',
    'training/prepare.py', 'training/merge_mlp.c', 'training/probe_mlp.c',
    'training/evaluate.py', 'training/evaluate_review.mjs',
    'training/sft_review_v2.jsonl', 'training/sft_review_v3.jsonl',
    'training/review_holdout_v2.jsonl', 'prompts/identity.txt', 'bin/jovovich.mjs',
    'src/infer.c', 'model.json', 'test/weighting.c', 'test/decision_score.test.mjs', 'Makefile',
    'training/results/2026-09-29-verdict-balance/verify_verdict_export.py',
    'training/results/2026-09-29-verdict-balance/probe_verdict_prefix.mjs',
    'training/results/2026-09-29-convergence/check_convergence_export.py',
]
plan = json.loads((out / 'plan.json').read_text())
manifest = dict(
    parent_commit=plan['parent_commit'], notorch_commit=plan['notorch_commit'],
    base_model=plan['base_model'], source_sha256={name: digest(root / name) for name in source_files},
    training_source=json.loads((out / 'training-source.json').read_text()),
    selected_model=json.loads((out / 'selected-model.json').read_text()),
    training={key: plan[key] for key in ('objective', 'updates', 'learning_rate', 'batch',
              'ordering', 'seed', 'rank', 'alpha', 'threads', 'trainable_parameters',
              'saved_updates', 'eligible_updates', 'checkpoint_selection')},
    comparison=plan['comparator'],
    validation=dict(native_tests=4, node_tests=31, shared_prefix_tests=5,
                    expected_unchanged_tensors=288, expected_adapted_tensors=3,
                    parity_rows=[0, 1, 2], shared_native_boundaries=80),
    result_counts=dict(exact_training_reviews=40, existing_review_diagnostics=12,
                       forced_positive_prefix=4, shared_prefix_per_model=40,
                       shared_prefix_models=2, new_generated_responses=136,
                       decision_readouts=101, full_readouts=5),
    corpus_followup='training/sft_review_v3.jsonl contains three documented wording repairs for subsequent SFT. This experiment uses v2 throughout.',
    runtime_model_promoted=False,
    path_normalization='Workspace prefixes and the temporary selected-model path are normalized in metadata. '
                       'original_evidence_sha256 preserves source-file hashes before normalization; '
                       'evidence_sha256 covers the committed copies. Summary source hashes refer to the original '
                       'files and match original_evidence_sha256. Reproduction source is copied unchanged.',
    archive_receipt='hf-evidence.json is written after remote verification and is excluded from the frozen manifest.',
    replay='The commands below reproduce a full run into fresh models/ outputs. Summaries read those outputs '
           'and validate their current provenance, including the inference binary SHA for shared-prefix results. '
           'Committed evidence is read directly with the two hash maps above.',
    original_evidence_sha256=original_hashes,
    reproduction=[
        'Run in a fresh repository workspace with the checksum-pinned base model and unused output paths.',
        'unset JOVOVICH_CHAT_TEMPLATE JOVOVICH_INFER',
        'Require /tmp/jovovich-decision-small-step-selected-e655134.gguf to be unused; the exporter creates this physical file.',
        'Retrieve the previous selected model identified by training/results/2026-09-29-decision-only/hf-weights.json as models/decision-only-selected.gguf.',
        'git submodule update --init deps/notorch',
        'make harness train-mlp merge-mlp probe-mlp test',
        'python3 training/prepare.py models/decision-small-step.bin --sft training/sft_review_v2.jsonl --sft-only --review-pairs models/decision-small-step.pairs',
        f'Copy {relative}/plan.json to models/decision-small-step-plan.json.',
        f'python3 {relative}/run_decision_small_step.py',
        f'python3 {relative}/evaluate_decision_small_step.py',
        f'python3 {relative}/run_shared_prefix.py',
        f'python3 {relative}/compare_small_step.py',
        f'node {relative}/summarize_small_step_generation.mjs',
        f'node {relative}/summarize_shared_prefix.mjs',
        f'node --test {relative}/probe_shared_prefix.test.mjs',
        'Manual assessments read complete generated responses against the actual diff, applicable rules and paired target.',
    ],
)
manifest['evidence_sha256'] = {str(p.relative_to(out)): digest(p) for p in sorted(out.iterdir()) if p.is_file()}
(out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(dict(path=str(out), evidence_files=len(manifest['evidence_sha256']))))
