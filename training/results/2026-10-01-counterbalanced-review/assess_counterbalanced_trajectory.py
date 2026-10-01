"""Compare completed v2/v4 joint trajectories by complete messages, not row indices."""
import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def readl(path):
    text = Path(path).read_text()
    assert text.endswith('\n'), f'incomplete JSONL: {path}'
    return [json.loads(line) for line in text.splitlines()]


def message_bytes(row):
    messages = row['messages']
    assert [m['role'] for m in messages] == ['system', 'user', 'assistant']
    assert all(set(m) == {'role', 'content'} for m in messages)
    return json.dumps(messages, ensure_ascii=False, separators=(',', ':')).encode('utf8')


def stable_values(row):
    # The data intervention shifts source-row and pair ordinals. Every numerical
    # measurement and every other emitted field must still compare exactly.
    return {key: value for key, value in row.items() if key not in ('row', 'pair_index')}


MARGIN_ABSOLUTE_TOLERANCE = 1e-5


def tile_position(metrics, row_index, decision_only=False):
    initial = metrics[0]
    if decision_only:
        decisions = next(r for r in metrics if r['stage'] == 'decision_train' and r['update'] == 0)['decision_rows']
        ordinal = next(i for i, r in enumerate(decisions) if r['row'] == row_index)
        batch_size, batch_index, token_index, global_position = len(decisions), 0, ordinal, ordinal
    else:
        rows = initial['teacher_forced_rows']
        row = next(r for r in rows if r['row'] == row_index)
        global_position = sum(r['tokens'] for r in rows if r['row'] < row_index) + row['decision_position']
        batch = initial['microbatch_tokens']
        batch_index, token_index = divmod(global_position, batch)
        batch_size = min(batch, initial['tokens'] - batch_index * batch)
    # The native SIMD worker partitions start at multiples of MR=6. Consequently
    # the final incomplete group uses the scalar edge path even with four workers.
    full_rows = (batch_size // 6) * 6
    return dict(global_position=global_position, batch_index=batch_index, token_index=token_index,
                batch_size=batch_size, full_tile_rows=full_rows,
                kernel='fma_6x16' if token_index < full_rows else 'scalar_edge')


def compare_initial_row(old, new, old_tile, new_tile, name):
    left, right = stable_values(old), stable_values(new)
    assert left.keys() == right.keys(), (name, 'field set changed')
    differences = {}
    for key, value in left.items():
        if key == 'decision_margin':
            assert type(value) in (int, float) and type(right[key]) in (int, float)
            assert math.isfinite(value) and math.isfinite(right[key]), (name, 'nonfinite margin')
        if value == right[key]:
            continue
        assert key == 'decision_margin', (name, key, value, right[key])
        delta = right[key] - value
        assert old_tile and new_tile and old_tile['kernel'] != new_tile['kernel'], (name, 'margin changed on same kernel')
        assert abs(delta) <= MARGIN_ABSOLUTE_TOLERANCE, (name, 'margin exceeds diagnostic tolerance', delta)
        differences[key] = dict(old=value, new=right[key], delta=delta, absolute_delta=abs(delta))
    return dict(exact=not differences, all_other_fields_exact=True, within_diagnostic_tolerance=True,
                differences=differences, old_tile=old_tile, new_tile=new_tile)


def assess_initial(corpora, metrics):
    old0, new0 = (metrics[arm][0] for arm in ('control', 'counterbalanced'))
    assert old0['stage'] == new0['stage'] == 'sft_initial'
    fixed = ['objective', 'rank', 'alpha', 'layer', 'trainable_parameters', 'seed',
             'residual_lambda', 'clip_limit', 'microbatch_tokens']
    for key in fixed:
        assert old0[key] == new0[key], key
    initial_decisions = {
        arm: next(row for row in records if row['stage'] == 'decision_train' and row['update'] == 0)
        for arm, records in metrics.items()
    }
    teacher = {}
    decisions = {}
    encoded = {}
    for arm in ('control', 'counterbalanced'):
        initial = metrics[arm][0]
        teacher[arm] = {row['row']: row for row in initial['teacher_forced_rows']}
        decisions[arm] = {row['row']: row for row in initial_decisions[arm]['decision_rows']}
        assert len(teacher[arm]) == len(corpora[arm]) == initial['examples']
        assert set(teacher[arm]) == set(range(len(corpora[arm])))
        encoded[arm] = {message_bytes(row): index for index, row in enumerate(corpora[arm])}
        assert len(encoded[arm]) == len(corpora[arm]), 'complete message triples must be unique'
    matched, changed = [], []
    for new_index, row in enumerate(corpora['counterbalanced']):
        content = message_bytes(row)
        old_index = encoded['control'].get(content)
        if old_index is None:
            changed.append(dict(id=row['id'], row=new_index, kind=row['kind'],
                                messages_sha256=hashlib.sha256(content).hexdigest()))
            continue
        old_row = corpora['control'][old_index]
        assert old_row['messages'] == row['messages']
        assert old_row['kind'] == row['kind']
        review = row['kind'] == 'review'
        teacher_comparison = compare_initial_row(teacher['control'][old_index], teacher['counterbalanced'][new_index],
                                                tile_position(metrics['control'], old_index) if review else None,
                                                tile_position(metrics['counterbalanced'], new_index) if review else None, row['id'])
        assert (old_index in decisions['control']) == (new_index in decisions['counterbalanced'])
        decision_comparison = None
        if old_index in decisions['control']:
            decision_comparison = compare_initial_row(decisions['control'][old_index], decisions['counterbalanced'][new_index],
                                                     tile_position(metrics['control'], old_index, True),
                                                     tile_position(metrics['counterbalanced'], new_index, True), row['id'])
        matched.append(dict(control_id=old_row['id'], counterbalanced_id=row['id'],
                            control_row=old_index, counterbalanced_row=new_index, kind=row['kind'],
                            messages_sha256=hashlib.sha256(content).hexdigest(),
                            teacher_values_exact=teacher_comparison['exact'],
                            decision_values_exact=decision_comparison['exact'] if decision_comparison else None,
                            teacher_comparison=teacher_comparison, decision_comparison=decision_comparison))
    assert matched and changed
    comparisons = [r[key] for r in matched for key in ('teacher_comparison', 'decision_comparison') if r[key]]
    deltas = [c['differences']['decision_margin']['absolute_delta'] for c in comparisons if c['differences']]
    return dict(method='Match complete system/user/assistant content bytes. Compare every field exactly except row/pair_index ordinals and finite decision_margin differences at mapped full/edge SIMD switches. Preserve raw deltas and exact=false. Changed message triples are listed without equality assertions.',
                identical_fixed_fields=fixed, compared_rows=len(matched),
                compared_by_kind=dict(Counter(row['kind'] for row in matched)),
                numerical_policy=dict(allowed_field='decision_margin', absolute_tolerance=MARGIN_ABSOLUTE_TOLERANCE,
                                      category='Explicit diagnostic comparison tolerance; no relative tolerance.',
                                      additional_requirement='The source-derived full 6x16 FMA versus scalar edge mapping must switch.',
                                      all_other_values_must_be_exact=True,
                                      calibration='Observed maximum margin delta is 5.72e-6. The independently measured zero-adapter reconstruction logit maximum is 3.0517578e-5; this sample is contextual calibration, not a universal bound for these logits.'),
                arithmetic_evidence=dict(source='deps/notorch/notorch_simd.h',
                                         trainer_binary_sha256='aedc1b9ed14f4a98c243c57b63f0aa65e0ee24ec4ea35dc30a3057fb387dc46f',
                                         full_tile='nt_simd_sgemm_block uses vfmadd231ps for full 6x16 tiles.',
                                         edge_tile='The same binary at 0xde45 uses vmulss, followed at 0xde52 by vaddss.',
                                         teacher_batch='40 tokens: full rows 0..35 and scalar rows 36..39, with final short batch handled from its actual size.',
                                         decision_batch='Control has 40 rows (edge36..39); counterbalanced has 52 rows (edge48..51).',
                                         independent_review='counterbalanced_protocol independently confirmed source partitioning and binary fused-versus-separate arithmetic.'),
                teacher_rows_exact=sum(r['teacher_values_exact'] for r in matched),
                decision_rows_compared=sum(r['decision_comparison'] is not None for r in matched),
                decision_rows_exact=sum(r['decision_values_exact'] is True for r in matched),
                nonexact_teacher_margins=sum(not r['teacher_values_exact'] for r in matched),
                nonexact_decision_margins=sum(r['decision_values_exact'] is False for r in matched),
                max_absolute_margin_delta=max(deltas, default=0),
                matched_rows=matched, unmatched_new_rows=changed,
                unmatched_control_rows=[dict(id=row['id'], row=i, kind=row['kind'])
                                        for i, row in enumerate(corpora['control'])
                                        if message_bytes(row) not in encoded['counterbalanced']],
                matched_initial_readouts_identical=all(c['exact'] for c in comparisons),
                all_discrete_and_nonmargin_values_exact=True,
                all_margin_deltas_within_diagnostic_tolerance=True,
                all_nonzero_margin_deltas_have_kernel_switch=True)


def describe_arm(corpus, metrics, scores):
    reviews = [row for row in corpus if row['kind'] == 'review']
    pairs = {}
    for row in reviews:
        concern = bool(json.loads(row['messages'][2]['content'])['findings'])
        pairs.setdefault(row['pair'], []).append(concern)
    assert all(sorted(values) == [False, True] for values in pairs.values())
    n_pairs, n_reviews = len(pairs), len(reviews)
    raw = [row for row in metrics if row['stage'] == 'decision_train']
    trajectory = scores['trajectory']
    assert [r['update'] for r in raw] == list(range(101))
    assert [r['update'] for r in trajectory] == list(range(101))
    assert scores['objective'] == 'joint' and scores['eligible_updates'] == [25, 50, 100]
    assert all(r['decision_positions'] == n_reviews and r['decision_pairs'] == n_pairs for r in raw)
    assert all(r['groups'][group]['examples'] == n_pairs for r in trajectory for group in ('concern', 'clean'))
    config = scores['joint_normalization']
    assert config['decision_positions'] == n_reviews
    assert config['joint_positions'] == config['decision_positions'] + config['residual_positions']
    assert config['joint_positions'] == sum(row['tokens'] for row in metrics[0]['teacher_forced_rows']
                                           if corpus[row['row']]['kind'] == 'review')
    selected_update = scores['selected_update']
    selected = next(row for row in raw if row['update'] == selected_update)
    best = max(trajectory[1:], key=lambda r: (r['complete_decision_pairs'], r['correct_targets'], -r['update']))
    full = [row for row in metrics if row['stage'] in ('sft_initial', 'sft')]
    assert [r.get('epoch', 0) for r in full] == [0, 25, 50, 75, 100]
    norms = [r['gradient_norm'] for r in raw[1:]]
    selected_counts = dict(complete_decision_pairs=scores['selected']['complete_decision_pairs'],
                           pair_denominator=n_pairs, decision_target_hits=scores['selected']['correct_targets'],
                           decision_denominator=n_reviews,
                           concern_hits=scores['selected']['groups']['concern']['correct'],
                           clean_hits=scores['selected']['groups']['clean']['correct'], label_denominator=n_pairs)
    return dict(selected_update=selected_update, selected_counts=selected_counts,
                selected=scores['selected'],
                one_sided_updates=sum((r['groups']['concern']['correct'], r['groups']['clean']['correct'])
                                      in ((n_pairs, 0), (0, n_pairs)) for r in trajectory[1:]),
                best_observed=best, full_readouts=scores['full_readouts'],
                clipped_updates=sum(r['clipped'] for r in raw[1:]),
                gradient_norm_min=min(norms), gradient_norm_max=max(norms),
                clip_scale_min=min(r['clip_scale'] for r in raw[1:]),
                initial_components={key: raw[0][key] for key in ('mean_decision_ce', 'mean_residual_ce', 'mean_joint_ce')},
                selected_components={key: selected[key] for key in ('mean_decision_ce', 'mean_residual_ce', 'mean_joint_ce')},
                prefix_readouts=[dict(update=r.get('epoch', 0), positions=r['prefix_positions'], correct=r['prefix_correct'],
                                      exact_examples=r['prefix_exact_examples'], examples=r['prefix_examples']) for r in full],
                exposure=dict(optimizer_updates=len(raw) - 1, examples=len(corpus), review_rows=n_reviews,
                              review_pairs=n_pairs, decision_targets_per_update=config['decision_positions'],
                              residual_targets_per_update=config['residual_positions'],
                              total_targets_per_update=config['joint_positions'],
                              decision_target_visits=config['decision_positions'] * (len(raw) - 1),
                              residual_target_visits=config['residual_positions'] * (len(raw) - 1),
                              total_target_visits=config['joint_positions'] * (len(raw) - 1),
                              terminal_im_end_included=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--initial-only', action='store_true', help='Save the initial comparison while training continues.')
    args = parser.parse_args()
    stem = 'models/counterbalanced-review'
    plan_path = Path(stem + '-plan.json')
    plan = read(plan_path)
    paths = dict(control_scores=Path(plan['comparator']['scores']['path']),
                 control_metrics=Path(plan['comparator']['metrics']['path']),
                 control_corpus=Path(plan['comparator']['corpus']['path']),
                 counterbalanced_scores=Path(stem + '-scores.json'),
                 counterbalanced_metrics=Path(stem + '-metrics.jsonl'),
                 counterbalanced_corpus=Path(plan['fixed_training']['dataset']), plan=plan_path)
    for kind in ('scores', 'metrics', 'corpus'):
        assert sha(paths['control_' + kind]) == plan['comparator'][kind]['sha256']
    assert sha(paths['counterbalanced_corpus']) == plan['fixed_training']['dataset_sha256']
    corpora = {arm: readl(paths[arm + '_corpus']) for arm in ('control', 'counterbalanced')}
    if args.initial_only:
        metrics, bindings = {}, {}
        for arm in corpora:
            with paths[arm + '_metrics'].open('rb') as source:
                lines = [source.readline(), source.readline()]
            assert all(line.endswith(b'\n') for line in lines)
            metrics[arm] = [json.loads(line) for line in lines]
            assert metrics[arm][1]['stage'] == 'decision_train' and metrics[arm][1]['update'] == 0
            bindings[arm] = dict(path=str(paths[arm + '_metrics']), prefix_records=2,
                                 prefix_sha256=hashlib.sha256(b''.join(lines)).hexdigest())
        assert plan['frozen_training']['binary']['sha256'] == 'aedc1b9ed14f4a98c243c57b63f0aa65e0ee24ec4ea35dc30a3057fb387dc46f'
        result = dict(schema_version=1, assessor_sha256=sha(__file__),
                      sources={key: dict(path=str(paths[key]), sha256=sha(paths[key]))
                               for key in ('plan', 'control_corpus', 'counterbalanced_corpus')},
                      metric_prefixes=bindings, initial_comparison=assess_initial(corpora, metrics))
        output = Path(stem + '-initial-comparison.json')
        with output.open('x') as target:
            json.dump(result, target, indent=2)
            target.write('\n')
        print(json.dumps(dict(output=str(output), compared_rows=result['initial_comparison']['compared_rows'],
                              exact=result['initial_comparison']['matched_initial_readouts_identical'],
                              max_margin_delta=result['initial_comparison']['max_absolute_margin_delta'])))
        return
    scores = {arm: read(paths[arm + '_scores']) for arm in ('control', 'counterbalanced')}
    metrics = {arm: readl(paths[arm + '_metrics']) for arm in scores}
    for arm, score in scores.items():
        assert score['metrics_sha256'] == sha(paths[arm + '_metrics'])
        assert score['sft_sha256'] == sha(paths[arm + '_corpus'])
    assert scores['control']['selection'] == scores['counterbalanced']['selection']
    result = dict(schema_version=1, sources={key: dict(path=str(p), sha256=sha(p)) for key, p in paths.items()},
                  assessor_sha256=sha(__file__), initial_comparison=assess_initial(corpora, metrics),
                  selection_rule=scores['counterbalanced']['selection'],
                  arms={arm: describe_arm(corpora[arm], metrics[arm], score) for arm, score in scores.items()},
                  interpretation=plan['fixed_training']['data_phase'],
                  exposure_comparison='Both runs use 100 full-corpus updates. Native target counts and target visits are reported per arm; the corpus revision changes both coverage and relative example weights.')
    initial_path = Path(stem + '-initial-comparison.json')
    assert result['initial_comparison'] == read(initial_path)['initial_comparison']
    result['sources']['initial_comparison'] = dict(path=str(initial_path), sha256=sha(initial_path))
    output = Path(stem + '-trajectory-assessment.json')
    with output.open('x') as target:
        json.dump(result, target, indent=2)
        target.write('\n')
    print(json.dumps(dict(output=str(output), compared_initial_rows=result['initial_comparison']['compared_rows'],
                          matched_initial_readouts_identical=result['initial_comparison']['matched_initial_readouts_identical'],
                          selected_update=scores['counterbalanced']['selected_update'])))


if __name__ == '__main__':
    main()
