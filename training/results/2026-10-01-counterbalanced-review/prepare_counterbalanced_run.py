"""Freeze the counterbalanced corpus intervention before either generation arm."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess

here = Path(__file__).resolve().parent
root = Path.cwd().resolve()
stem = 'models/counterbalanced-review'
def item(path):
    path = Path(path)
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return dict(path=os.path.relpath(path, root), sha256=h.hexdigest(), bytes=path.stat().st_size)
def readl(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines()]
assert not os.environ.get('JOVOVICH_CHAT_TEMPLATE') and not os.environ.get('JOVOVICH_INFER')
base = 'e1a77721fa97d412f121878223eec81fb4ae6f271e18f922d746711f67b344d1'
comparator = '6aaf2f70764de35db1ee13b2c7d974b1064b6dfbd044024b164a2856fdafadd1'
assert item('models/base-qwen.gguf')['sha256'] == base
assert item('models/joint-review-selected.gguf')['sha256'] == comparator
rows = readl('training/sft_review_v4.jsonl')
reviews = [r for r in rows if r['kind'] == 'review']
assert len(rows) == 76 and len(reviews) == 52
assert len({r['pair'] for r in reviews}) == 26
assert len(readl(here / 'fresh-transfer.jsonl')) == 24
assert len(readl('training/review_holdout_v2.jsonl')) == 12
assert item('training/sft_review_v4.jsonl')['sha256'] == '20afaa5692e88625d7152c7634c68e665a7bb165bfdc6dba15fec8c9e01edc1e'
tokenization = readl('models/counterbalanced-tokenization.json')
assert len(tokenization) == 1 and tokenization[0]['pass'] and tokenization[0]['rows'] == 76 and tokenization[0]['comparisons'] == 152
native_rows = readl('models/counterbalanced-review-preflight.jsonl')
native = native_rows[-1]
assert len(native_rows) == 77 and native['pass']
assert (native['examples'], native['review_examples'], native['review_pairs'], native['decision_positions'], native['residual_positions'], native['joint_positions']) == (76, 52, 26, 52, 1012, 1064)
assert (native['microbatch_tokens'], native['microbatches_per_update'], native['last_microbatch_tokens'], native['model_forward_calls']) == (40, 27, 24, 0)
assert native['chatml_comparisons'] == 152
receipt = json.loads((here / 'native-preflight.json').read_text())
assert receipt['summary'] == native
for entry in receipt['sources'] + receipt['artifacts']:
    actual = item(entry['path'])
    assert actual['sha256'] == entry['sha256'] and actual['bytes'] == entry['bytes'], entry['path']
pin = subprocess.check_output(['git', '-C', 'deps/notorch', 'rev-parse', 'HEAD'], text=True).strip()
assert pin == '7e246e13f9dbbb7e61312b7341fb94ce492bff71'
old = Path('training/results/2026-10-01-joint-review')
fixed = dict(initialization='Fresh adapters on the verified Qwen base, same initialization seed as comparator.',
    base_model='Qwen2.5-Coder-0.5B-Instruct Q8_0', base_sha256=base, notorch_pin=pin,
    dataset='training/sft_review_v4.jsonl', dataset_sha256=item('training/sft_review_v4.jsonl')['sha256'],
    training_rows='52 explicitly paired review rows; 12 voice and 12 code rows are diagnostic only.',
    pair_map_sha256=item(stem + '.pairs')['sha256'], seed=20260929, rank=16, alpha=32,
    adapter_targets='Final-layer MLP gate, up and down projections.', trainable_parameters=276480,
    learning_rate=0.0001, optimizer='Adam with unchanged native hyperparameters.',
    optimizer_updates=100, global_gradient_clip=1, microbatch_tokens=40,
    objective='mean decision CE + 1 * mean residual review-token CE, including terminal im_end; independent global denominators.',
    lambda_residual=1, decision_targets_per_update=52, residual_targets_per_update=1012,
    joint_targets_per_update=1064, total_target_visits=106400, microbatches_per_update=27, final_microbatch_targets=24,
    data_phase='Combined v3 wording repairs plus six counterbalanced quartets; causal attribution is to this whole corpus revision.')
paths = dict(infer='src/infer.c', runner='build/jovovich-infer', host='bin/jovovich.mjs',
    corpus_audit=here / 'corpus-audit.json',
    probe=here / 'evaluate_counterbalanced_reviews.mjs', summary=here / 'summarize_counterbalanced_reviews.mjs',
    controller=here / 'run_counterbalanced_evaluation.py', transfer=here / 'fresh-transfer.jsonl',
    corpus='training/sft_review_v4.jsonl', diagnostics='training/review_holdout_v2.jsonl', identity='prompts/identity.txt',
    shared_helper='training/results/2026-09-29-small-step/probe_shared_prefix.mjs', scorer='training/score_decisions.py',
    merger='build/jovovich-merge-mlp', parity='build/jovovich-probe-mlp',
    export_verifier='training/results/2026-09-29-verdict-balance/verify_verdict_export.py')
p = dict(schema_version=1, status='Frozen before training and control generation.',
    created_utc=datetime.now(timezone.utc).isoformat(),
    parent_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
    question='Does explicit semantic/shape counterbalancing improve grounded full reviews on training pairs and new transfer quartets?',
    approved_design=item(old / 'joint-next-control.json'), fixed_training=fixed,
    comparator=dict(model='models/joint-review-selected.gguf', model_sha256=comparator,
        selection=item(old / 'selected-model.json'), scores=item(old / 'scores.json'),
        metrics=item(old / 'metrics.jsonl'), corpus=item('training/sft_review_v2.jsonl'),
        previous_generations={k:item(old / ('joint-' + k + '-natural.jsonl')) for k in ('train', 'diagnostics')}),
    checkpoint_selection=dict(saved_updates=[25, 50, 75, 100], eligible_updates=[25, 50, 100],
        rule='Maximize complete full-vocabulary decision pairs, then target hits, then earlier eligible update.',
        timing='Select once before new-arm free generation; no transfer/generation-based choice.'),
    frozen_training={k:item(v) for k,v in dict(source='training/train_mlp.c', binary='build/jovovich-train-mlp',
        dataset_binary=stem + '.bin', pair_map=stem + '.pairs').items()},
    frozen_evaluation={k:item(v) for k,v in paths.items()}, training_runner=item(here / 'run_counterbalanced_review.py'),
    preflight={k:item(v) for k,v in dict(chatml='models/counterbalanced-tokenization.json',
        native=here / 'native-preflight.json', corpus=here / 'corpus-audit.json',
        transfer=here / 'fresh-transfer-audit.json', protocol=here / 'protocol-audit.json',
        orchestration=here / 'orchestration-audit.json').items()},
    evaluation=dict(new_responses=176, control=dict(train_natural=52, transfer_natural=24, diagnostics_natural=12),
        counterbalanced=dict(train_natural=52, transfer_natural=24, diagnostics_natural=12),
        temperature=0, budget_tokens=192, threads_per_process=2, activation_quantization=False,
        training_threads=4, control_workers=2, counterbalanced_workers=4,
        schedule='Control generation may overlap training; selected new-arm generation follows training/export parity.',
        trace='Native prompt IDs and sampled IDs including terminal EOS retained for every response.',
        shared_prefix='No forced-prefix generation. Compare actual natural decision to teacher only where prompt matches and preceding prefix IDs are exact.'),
    full_answer_judgment=dict(
        method='Read each complete response against its exact prompt, visible code and repository rules. Preserve response/model/prompt hashes and case-specific reasoning.',
        production_usable='Unchanged production parseReview accepts the complete response and available changed-line citations.',
        genuine_issue_detected='At least one supported concrete mechanism with an available causally appropriate citation, even if unsupported extras spoil the complete review.',
        full_review_pass='Concern: production accepted, real cited issue, every material claim/finding supported, no unsupported extra findings. Clean: production accepted empty findings.',
        pairs='Both concern and clean must pass fully; separately report mere presence and token decisions.',
        alternatives='Gold wording and canonical citation are not mandatory; any changed line with a valid causal connection is allowed, including either side of harmful no-op replacements.',
        precision='Awkward but meaningful explanations can pass. Separate detected real issues from inaccurate elaborations; retain explicitly reasoned sensitivity judgments if a claim is ambiguous.'),
    comparisons=dict(retained_pairs=14, counterbalanced_quartet_families=6, training_quartet_rows=24,
        identical_full_diff_pairs=['scoped-python-analysis','approved-binary-decoder','sqlite-build-requirement',
            'background-service-scope','scoped-design-record','checksum-indirection'],
        fresh_transfer='24 new cases in six families with effective vs ineffective differently placed/spelled lookalikes; development diagnostic, not a population benchmark.',
        quartet_contrasts='Report semantic flips within each fixed shape and shape invariance within each fixed label, with full-review correctness alongside raw invariance.',
        exposure='100 full-corpus updates: every target visited 100 times. Total target exposure and corpus weighting change with the revision; exact native counts retained.',
        interpretation='Same model/init/native objective/optimizer/selector; combined corpus revision. One deterministic run per corpus, no uncertainty over seeds.'))
with Path(stem + '-plan.json').open('x') as f:
    f.write(json.dumps(p, indent=2) + '\n')
print(json.dumps(dict(plan=stem + '-plan.json', sha256=item(stem + '-plan.json')['sha256'])))
