#!/usr/bin/env python3
"""Validate fixed 100-update decisions/joint controls and select before generation."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from prepare import review_pairs, review_prefixes
from score_training import summarize


ELIGIBLE = (25, 50, 100)
SNAPSHOTS = (25, 50, 75, 100)
DECISION_FIELDS = {'decision_position', 'decision_correct', 'decision_margin',
                   'decision_predicted_id', 'decision_target_id', 'decision_alternative_id'}
PREFIX_FIELDS = {'prefix_tokens', 'prefix_correct', 'prefix_exact'}
PREFIX_EVIDENCE_FIELDS = {'decision_prefix', 'decision_prefix_bytes'}
GRADIENT_FIELDS = {'gradient_norm', 'clip_scale', 'clipped', 'gradient_measurement', 'online_joint_ce'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, name, minimum=0):
    require(type(value) is int and value >= minimum, f'invalid {name}')
    return value


def finite(value, name, nonnegative=False):
    require(type(value) in (int, float) and math.isfinite(value) and
            (not nonnegative or value >= 0), f'invalid {name}')
    return value


def indexed(rows, expected, name):
    require(isinstance(rows, list), f'{name} must be a list')
    result = {}
    for row in rows:
        require(isinstance(row, dict), f'invalid {name} row')
        index = integer(row.get('row'), f'{name} row index')
        require(index not in result, f'duplicate {name} row {index}')
        result[index] = row
    require(set(result) == set(expected), f'{name} must cover every expected row exactly once')
    return result


def corpus_map(data):
    require(isinstance(data, list) and data, 'decision control requires a nonempty corpus')
    for row in data:
        require(isinstance(row, dict), 'corpus rows must be objects')
        require(row.get('kind') in ('review', 'voice', 'code'), 'unknown corpus task kind')
        messages = row.get('messages')
        require(isinstance(messages, list) and len(messages) == 3 and
                all(isinstance(m, dict) for m in messages) and
                [m.get('role') for m in messages] == ['system', 'user', 'assistant'] and
                all(isinstance(m.get('content'), str) for m in messages),
                'corpus messages must be system/user/assistant string triples')
    ids = [r.get('id') for r in data]
    require(all(isinstance(i, str) and i for i in ids) and len(set(ids)) == len(ids),
            'corpus IDs must be nonempty and unique')
    pairs = review_pairs(data)
    mapping = {}
    for number, (concern, clean) in enumerate(pairs):
        for index, kind in ((concern, 'concern'), (clean, 'clean')):
            mapping[index] = dict(pair_index=number, pair=data[index]['pair'], kind=kind)
    return pairs, mapping


def validate_decision(score, reference=None, tokens=None):
    require(DECISION_FIELDS <= score.keys(), 'incomplete decision token fields')
    position = integer(score['decision_position'], 'decision position')
    if tokens is not None:
        require(position < tokens - 1, 'decision cannot be EOS or outside completion')
    target, alternative, predicted = [integer(score[k], k) for k in
        ('decision_target_id', 'decision_alternative_id', 'decision_predicted_id')]
    require(target != alternative, 'decision target and alternative must differ')
    hit, margin = score['decision_correct'], finite(score['decision_margin'], 'decision margin')
    require(type(hit) is bool and hit == (predicted == target),
            'decision correctness disagrees with predicted ID')
    require(not (predicted == target and margin < 0) and
            not (predicted == alternative and margin > 0), 'decision margin contradicts argmax')
    # Native full-vocabulary argmax keeps the lower ID when logits tie.
    if margin == 0:
        require(not (predicted == target and target > alternative) and
                not (predicted == alternative and alternative > target),
                'decision tie contradicts native argmax ordering')
    if reference:
        for field in ('decision_position', 'decision_target_id', 'decision_alternative_id'):
            require(score[field] == reference[field], f'{field} changed from initial metadata')


def validate_prefix_evidence(score, reference):
    """Optional later readouts must preserve the initial source-bound boundary."""
    if 'decision_prefix' in score:
        require(isinstance(score['decision_prefix'], str), 'invalid decision prefix')
        require('decision_prefix' in reference and score['decision_prefix'] == reference['decision_prefix'],
                'decision prefix changed from initial metadata')
    if 'decision_prefix_bytes' in score:
        size = integer(score['decision_prefix_bytes'], 'decision prefix bytes', 1)
        require('decision_prefix_bytes' in reference and size == reference['decision_prefix_bytes'],
                'decision prefix bytes changed from initial metadata')


def references(initial, mapping, pairs, data, version):
    require(initial.get('objective') in ('decisions', 'joint'), 'initial objective must be decisions or joint')
    example_count = len(data)
    require(initial.get('examples') == example_count and type(initial.get('examples')) is int,
            'initial example count disagrees')
    require(integer(initial.get('decision_pairs'), 'initial decision pairs') == len(pairs),
            'initial decision pair count disagrees')
    scores = indexed(initial.get('teacher_forced_rows'), range(example_count), 'initial full scores')
    prefixes = review_prefixes(data) if version == 2 else {}
    if version == 2:
        require(set(prefixes) == set(mapping), 'verdict prefixes must cover every mapped review row')
    result = {}
    for index, score in scores.items():
        n = integer(score.get('tokens'), 'initial completion tokens', 1)
        result[index] = {'tokens': n}
        if index in mapping:
            validate_decision(score, tokens=n)
            result[index].update({key: score[key] for key in DECISION_FIELDS})
            if version == 2:
                require(isinstance(score.get('decision_prefix'), str), 'invalid decision prefix')
                require(score['decision_prefix'] == prefixes[index],
                        'decision prefix disagrees with corpus verdict prefix')
                encoded = prefixes[index].encode('utf-8')
                size = integer(score.get('decision_prefix_bytes'), 'decision prefix bytes', 1)
                require(size == len(encoded), 'decision prefix bytes disagree with corpus verdict prefix')
                result[index].update(decision_prefix=score['decision_prefix'], decision_prefix_bytes=size,
                                     decision_prefix_sha256=hashlib.sha256(encoded).hexdigest())
            else:
                require(not PREFIX_EVIDENCE_FIELDS.intersection(score),
                        'decision prefix evidence requires pair map version 2')
        else:
            require(not DECISION_FIELDS.intersection(score), 'decision fields on a non-review row')
            require(not PREFIX_EVIDENCE_FIELDS.intersection(score), 'decision prefix evidence on a non-review row')
    require(integer(initial.get('tokens'), 'initial total tokens', 1) ==
            sum(r['tokens'] for r in result.values()), 'initial token total disagrees')
    for a, b in pairs:
        require((version == 2 or result[a]['decision_position'] == result[b]['decision_position']) and
                result[a]['decision_target_id'] == result[b]['decision_alternative_id'] and
                result[b]['decision_target_id'] == result[a]['decision_alternative_id'],
                'paired decision positions or target/alternative IDs are not reciprocal')
    return result


def joint_config(initial, refs, mapping, microbatch_tokens):
    integer(microbatch_tokens, 'expected joint microbatch tokens', 1)
    positions = sum(refs[index]['tokens'] for index in mapping)
    counts = dict(decision_positions=len(mapping), residual_positions=positions-len(mapping),
                  joint_positions=positions)
    require(counts['residual_positions'] > 0, 'joint objective requires residual answer targets')
    for key, expected in counts.items():
        require(integer(initial.get(key), key, 1) == expected,
                f'{key} disagrees with mapped corpus token counts')
    require(finite(initial.get('residual_lambda'), 'residual lambda') == 1,
            'joint residual lambda must be one')
    require(finite(initial.get('clip_limit'), 'clip limit') == 1, 'joint clip limit must be one')
    require(integer(initial.get('microbatch_tokens'), 'microbatch tokens', 1) == microbatch_tokens,
            'joint microbatch disagrees with declared run configuration')
    return dict(**counts, residual_lambda=1, clip_limit=1, microbatch_tokens=microbatch_tokens)


def joint_summary(metric, config, previous):
    for key in ('residual_positions', 'joint_positions'):
        require(integer(metric.get(key), key, 1) == config[key],
                f'{key} changed from joint normalization')
    require(finite(metric.get('residual_lambda'), 'residual lambda') == config['residual_lambda'],
            'joint residual lambda changed')
    residual = finite(metric.get('mean_residual_ce'), 'residual CE', nonnegative=True)
    loss = finite(metric.get('mean_joint_ce'), 'joint CE', nonnegative=True)
    require(math.isclose(loss, metric['mean_decision_ce'] + config['residual_lambda'] * residual,
                         rel_tol=1e-5, abs_tol=2e-5), 'joint CE disagrees with its component means')
    require(GRADIENT_FIELDS <= metric.keys(), 'incomplete joint gradient diagnostics')
    if previous is None:
        require(all(metric[key] is None for key in GRADIENT_FIELDS),
                'initial joint gradient diagnostics must be null')
    else:
        require(metric['gradient_measurement'] == 'pre_update', 'joint gradient measurement must be pre_update')
        norm = finite(metric['gradient_norm'], 'gradient norm', nonnegative=True)
        scale = finite(metric['clip_scale'], 'clip scale', nonnegative=True)
        clipped = norm > config['clip_limit']
        expected_scale = config['clip_limit'] / (norm + 1e-6) if clipped else 1.0
        require(0 < scale <= 1 and math.isclose(scale, expected_scale, rel_tol=1e-5, abs_tol=0.0),
                'clip scale disagrees with native gradient norm')
        require(type(metric['clipped']) is bool and metric['clipped'] == clipped,
                'clipped flag disagrees with gradient norm')
        online = finite(metric['online_joint_ce'], 'online joint CE', nonnegative=True)
        require(math.isclose(online, previous['mean_joint_ce'], rel_tol=1e-5, abs_tol=2e-5),
                'online joint CE must measure the preceding parameter state')
    return dict(mean_residual_ce=residual, mean_joint_ce=loss,
                residual_positions=config['residual_positions'], joint_positions=config['joint_positions'],
                residual_lambda=config['residual_lambda'], **{key: metric[key] for key in sorted(GRADIENT_FIELDS)})


def prefix_summary(metric, scores, mapping, refs, required):
    aggregate = {'prefix_positions', 'prefix_correct', 'prefix_exact_examples', 'prefix_examples'}
    present = bool(aggregate.intersection(metric)) or any(PREFIX_FIELDS.intersection(r) for r in scores.values())
    if not required and not present:
        return None
    totals = dict(prefix_positions=0, prefix_correct=0, prefix_exact_examples=0, prefix_examples=len(mapping))
    for index, row in scores.items():
        if index not in mapping:
            require(not PREFIX_FIELDS.intersection(row), 'prefix fields on a non-review row')
            continue
        require(PREFIX_FIELDS <= row.keys(), 'incomplete prefix token fields')
        n = integer(row['prefix_tokens'], 'prefix tokens')
        correct = integer(row['prefix_correct'], 'prefix correct')
        require(n == refs[index]['decision_position'] and correct <= n,
                'prefix counts disagree with decision position')
        require(type(row['prefix_exact']) is bool and row['prefix_exact'] == (correct == n),
                'prefix exact disagrees with prefix correct')
        require(correct <= row['correct'] <= correct + row['tokens'] - n,
                'prefix correct contradicts full token count')
        first = row['first_error_position']
        require((first == -1 or first >= n) and correct == n or
                0 <= first < n and first <= correct < n,
                'prefix correctness contradicts first-error position')
        totals['prefix_positions'] += n
        totals['prefix_correct'] += correct
        totals['prefix_exact_examples'] += row['prefix_exact']
    for key, expected in totals.items():
        require(integer(metric.get(key), key) == expected, f'{key} aggregate disagrees with row scores')
    return totals


def decision_summary(metric, mapping, pairs, refs):
    update = integer(metric.get('update'), 'decision update')
    require(type(metric.get('epoch')) is int and metric['epoch'] == update, 'epoch/update mismatch')
    require(metric.get('measurement') == ('initial' if update == 0 else 'post_update'),
            'decision readout is not the declared initial/post-update measurement')
    require(type(metric.get('snapshot_saved')) is bool and
            metric['snapshot_saved'] == (update in SNAPSHOTS), 'snapshot_saved disagrees with fixed schedule')
    require(integer(metric.get('decision_positions'), 'decision positions') == len(mapping) and
            integer(metric.get('decision_pairs'), 'decision pairs') == len(pairs), 'decision coverage counts disagree')
    ce = finite(metric.get('mean_decision_ce'), 'decision CE', nonnegative=True)
    scores = indexed(metric.get('decision_rows'), mapping, 'decision scores')
    groups = {k: dict(examples=len(pairs), correct=0, positive_margin=0, mean_margin=0.0,
                     min_margin=math.inf) for k in ('concern', 'clean')}
    for index, score in scores.items():
        require(integer(score.get('pair_index'), 'pair index') == mapping[index]['pair_index'],
                'decision pair index disagrees with explicit corpus map')
        validate_decision(score, refs[index], refs[index]['tokens'])
        validate_prefix_evidence(score, refs[index])
        group = groups[mapping[index]['kind']]
        group['correct'] += score['decision_correct']
        group['positive_margin'] += score['decision_margin'] > 0
        group['mean_margin'] += score['decision_margin'] / len(pairs)
        group['min_margin'] = min(group['min_margin'], score['decision_margin'])
    correct = sum(s['decision_correct'] for s in scores.values())
    exact = sum(scores[a]['decision_correct'] and scores[b]['decision_correct'] for a, b in pairs)
    require(integer(metric.get('decision_correct'), 'aggregate decision correct') == correct,
            'decision aggregate correct count disagrees')
    require(integer(metric.get('decision_pairs_exact'), 'aggregate decision pairs exact') == exact,
            'decision aggregate pair count disagrees')
    separation = [scores[a]['decision_margin'] + scores[b]['decision_margin'] for a, b in pairs]
    return dict(update=update, mean_decision_ce=ce, snapshot_saved=metric['snapshot_saved'],
                eligible=update in ELIGIBLE and metric['snapshot_saved'], correct_targets=correct,
                complete_decision_pairs=exact, groups=groups,
                mean_pair_context_separation=sum(separation) / len(pairs),
                min_pair_context_separation=min(separation)), scores


def full_summary(data, metric, update, decision_rows, refs, mapping, joint=False):
    # Native snapshots omit these totals; validate them whenever a record declares them.
    if 'examples' in metric:
        require(integer(metric['examples'], 'full examples', 1) == len(data),
                'full example count disagrees with corpus')
    if 'tokens' in metric:
        require(integer(metric['tokens'], 'full total tokens', 1) ==
                sum(ref['tokens'] for ref in refs.values()), 'full token total disagrees')
    scores = indexed(metric.get('teacher_forced_rows'), range(len(data)), 'full scores')
    for index, score in scores.items():
        n = integer(score.get('tokens'), 'completion tokens', 1)
        correct = integer(score.get('correct'), 'correct tokens')
        require(n == refs[index]['tokens'] and correct <= n, 'full token counts changed or invalid')
        first = score.get('first_error_position')
        require(type(first) is int and ((correct == n and first == -1) or
                (correct < n and 0 <= first < n and first <= correct)),
                'first-error position contradicts token counts')
        if index in mapping:
            normalized = dict(score)
            id_fields = {'decision_target_id', 'decision_alternative_id'}
            require(not id_fields.intersection(score) or id_fields <= score.keys(),
                    'partial target/alternative IDs in full readout')
            for field in id_fields:
                normalized.setdefault(field, refs[index][field])
            validate_decision(normalized, refs[index], n)
            validate_prefix_evidence(score, refs[index])
            reference = decision_rows[index]
            for field in DECISION_FIELDS - {'decision_margin'}:
                require(normalized[field] == reference[field], 'full/decision readout disagreement')
            require(math.isclose(normalized['decision_margin'], reference['decision_margin'],
                                 rel_tol=1e-5, abs_tol=2e-5), 'full/decision margin disagreement')
            hit, position = normalized['decision_correct'], normalized['decision_position']
            require((hit and correct > 0 and first != position) or
                    (not hit and correct < n and first <= position),
                    'full decision correctness contradicts first error or token counts')
        else:
            require(not DECISION_FIELDS.intersection(score), 'decision fields on a non-review row')
            require(not PREFIX_EVIDENCE_FIELDS.intersection(score), 'decision prefix evidence on a non-review row')
    finite(metric.get('mean_token_ce'), 'full token CE', nonnegative=True)
    for field in ('teacher_forced_correct_tokens', 'teacher_forced_exact_examples'):
        integer(metric.get(field), field)
    result = summarize(data, metric)
    require(result.get('review_decision_pairs') == len(mapping) // 2,
            'full readout must cover all corpus decision pairs')
    prefix = prefix_summary(metric, scores, mapping, refs, joint)
    if prefix is not None:
        result.update(prefix)
    result['update'] = update
    return result


def selection_key(summary):
    return summary['complete_decision_pairs'], summary['correct_targets'], -summary['update']


def score_run(data, metrics, *, joint_microbatch_tokens=40):
    pairs, mapping = corpus_map(data)
    require(isinstance(metrics, list) and metrics and metrics[0].get('stage') == 'sft_initial',
            'first metric must be full sft_initial')
    initial = metrics[0]
    version = initial.get('pair_map_version', 1)
    require(type(version) is int and version in (1, 2), 'invalid pair map version')
    refs = references(initial, mapping, pairs, data, version)
    objective = initial['objective']
    config = joint_config(initial, refs, mapping, joint_microbatch_tokens) if objective == 'joint' else None
    decisions, full, trajectory = {}, {0: initial}, []
    sequence = [('sft_initial', 0)]
    for update in range(101):
        sequence.append(('decision_train', update))
        if update in SNAPSHOTS:
            sequence.append(('sft', update))
    require(len(metrics) == len(sequence), 'incomplete run: require updates 0..100 and all full snapshots')
    for metric, (stage, update) in zip(metrics, sequence):
        require(metric.get('stage') == stage, 'unexpected metric stage/order')
        if 'pair_map_version' in metric:
            require(type(metric['pair_map_version']) is int and metric['pair_map_version'] == version,
                    'pair map version changed within decision run')
        if 'objective' in metric:
            require(metric['objective'] == objective, 'objective changed within decision run')
        if config is not None and 'microbatch_tokens' in metric:
            require(integer(metric['microbatch_tokens'], 'microbatch tokens', 1) == config['microbatch_tokens'],
                    'joint microbatch changed from declared run configuration')
        if stage == 'decision_train':
            require(metric.get('update') == update, 'decision updates must be exactly 0..100 in order')
            summary, rows = decision_summary(metric, mapping, pairs, refs)
            if config is not None:
                summary.update(joint_summary(metric, config, trajectory[-1] if trajectory else None))
            trajectory.append(summary)
            decisions[update] = rows
        elif stage == 'sft':
            require(type(metric.get('epoch')) is int and metric['epoch'] == update,
                    'full snapshot epoch disagrees with fixed schedule')
            if 'update' in metric:
                require(type(metric['update']) is int and metric['update'] == update, 'full update/epoch mismatch')
            if config is not None and 'online_mean_objective_ce' in metric:
                online = finite(metric['online_mean_objective_ce'], 'full online joint CE', nonnegative=True)
                require(math.isclose(online, trajectory[-1]['online_joint_ce'], rel_tol=1e-5, abs_tol=2e-5),
                        'full online joint CE disagrees with the update diagnostic')
            full[update] = metric
    readouts = [full_summary(data, full[u], u, decisions[u], refs, mapping, config is not None)
                for u in (0, *SNAPSHOTS)]
    candidates = [s for s in trajectory if s['eligible']]
    require([s['update'] for s in candidates] == list(ELIGIBLE), 'missing eligible saved checkpoint')
    selected = max(candidates, key=selection_key)
    result = dict(objective=objective, selection='maximize complete full-vocabulary decision pairs, then correct decision targets, then earlier update',
                eligible_updates=list(ELIGIBLE), selected_update=selected['update'], selected_epoch=selected['update'],
                selected=selected, trajectory=trajectory, full_readouts=readouts,
                interpretation='Decision margins compare two target-template tokens. Full-vocabulary hits govern selection; positive margins alone do not. Generated JSON and reasons must be assessed separately.')
    if config is not None:
        result['joint_normalization'] = config
    if version == 2:
        result.update(pair_map_version=version, decision_metadata=[
            dict(row=index, id=data[index]['id'], **mapping[index],
                 **{key: refs[index][key] for key in ('decision_position', 'decision_target_id',
                    'decision_alternative_id', 'decision_prefix_bytes', 'decision_prefix_sha256')})
            for index in sorted(mapping)])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('metrics', type=Path)
    parser.add_argument('--sft', type=Path, default=Path(__file__).with_name('sft_review_v2.jsonl'))
    parser.add_argument('--joint-microbatch-tokens', type=int, default=40,
                        help='expected joint training microbatch size (default: 40)')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    def read(path):
        text = path.read_text()
        require(text.endswith('\n'), f'incomplete final JSONL record: {path}')
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    result = score_run(read(args.sft), read(args.metrics), joint_microbatch_tokens=args.joint_microbatch_tokens)
    result.update(metrics=str(args.metrics), metrics_sha256=hashlib.sha256(args.metrics.read_bytes()).hexdigest(),
                  sft=str(args.sft), sft_sha256=hashlib.sha256(args.sft.read_bytes()).hexdigest())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as target:
        json.dump(result, target, indent=2)
        target.write('\n')


if __name__ == '__main__':
    main()
