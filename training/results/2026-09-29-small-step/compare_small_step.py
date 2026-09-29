#!/usr/bin/env python3
"""Validate and compare the fixed 100-update decision-only score summaries."""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path


ELIGIBLE = [25, 50, 100]
SAVED = [25, 50, 75, 100]
ABS_TOL, REL_TOL = 2e-5, 1e-5
NOTE = (
    "Margins contrast the two target-template tokens. Full-vocabulary correctness is "
    "recorded separately as target hits. Shared mean preference is "
    "(concern mean margin - clean mean margin)/2; "
    "mean pair separation is their sum. One-sided target correctness means exactly "
    "concern=20, clean=0 or concern=0, clean=20 and correct_targets=20. Score summaries "
    "provide these hit counts; raw per-row metrics provide the argmax token IDs."
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def count(value, name, maximum=None):
    require(type(value) is int and value >= 0 and
            (maximum is None or value <= maximum), f"invalid count: {name}={value!r}")
    return value


def finite(value, name, nonnegative=False):
    require(type(value) in (int, float) and math.isfinite(value) and
            (not nonnegative or value >= 0), f"invalid number: {name}={value!r}")
    return value


def close(a, b):
    return math.isclose(a, b, abs_tol=ABS_TOL, rel_tol=REL_TOL)


def select_key(row):
    return row['complete_decision_pairs'], row['correct_targets'], -row['update']


def bounds(pairs, a, b, name):
    require(max(0, a + b - 20) <= pairs <= min(a, b), f"inconsistent pair counts: {name}")


def load_scores(path):
    raw = path.read_bytes()
    data = json.loads(raw)
    require(isinstance(data, dict) and data.get('objective') == 'decisions',
            f"{path}: expected decisions score object")
    require(data.get('eligible_updates') == ELIGIBLE, f"{path}: eligible updates must be {ELIGIBLE}")
    rows = data.get('trajectory')
    require(isinstance(rows, list) and len(rows) == 101, f"{path}: require 101 trajectory rows")
    for update, row in enumerate(rows):
        label = f"{path}: update {update}"
        require(isinstance(row, dict) and type(row.get('update')) is int and
                row['update'] == update, f"{label}: updates must be ordered exactly 0..100")
        finite(row.get('mean_decision_ce'), label + ' CE', True)
        for key, expected in [('snapshot_saved', update in SAVED), ('eligible', update in ELIGIBLE)]:
            require(type(row.get(key)) is bool and row[key] == expected, f"{label}: invalid {key}")
        groups = row.get('groups')
        require(isinstance(groups, dict) and set(groups) == {'concern', 'clean'},
                f"{label}: require concern/clean groups")
        for kind, group in groups.items():
            require(isinstance(group, dict) and count(group.get('examples'), label + kind) == 20,
                    f"{label}: {kind} must contain 20 examples")
            count(group.get('correct'), label + kind + ' correct', 20)
            count(group.get('positive_margin'), label + kind + ' positive_margin', 20)
            mean = finite(group.get('mean_margin'), label + kind + ' mean_margin')
            low = finite(group.get('min_margin'), label + kind + ' min_margin')
            require(low <= mean or close(low, mean), f"{label}: minimum exceeds mean margin")
            if low > 0:
                require(group['positive_margin'] == 20, f"{label}: positive margin count inconsistent")
            if group['positive_margin'] == 0:
                require(mean <= 0, f"{label}: zero positive margins with positive mean")
        a, b = (groups[k]['correct'] for k in ('concern', 'clean'))
        require(count(row.get('correct_targets'), label + ' correct_targets', 40) == a + b,
                f"{label}: correct_targets disagrees with groups")
        pairs = count(row.get('complete_decision_pairs'), label + ' pairs', 20)
        bounds(pairs, a, b, label)
        separation = groups['concern']['mean_margin'] + groups['clean']['mean_margin']
        recorded = finite(row.get('mean_pair_context_separation'), label + ' recorded separation')
        require(close(recorded, separation), f"{label}: recorded mean_pair_context_separation disagrees")
        low = finite(row.get('min_pair_context_separation'), label + ' min separation')
        require(low <= recorded or close(low, recorded), f"{label}: minimum exceeds mean separation")
    selected = max((rows[u] for u in ELIGIBLE), key=select_key)
    require(type(data.get('selected_update')) is int and data['selected_update'] == selected['update'] and
            type(data.get('selected_epoch')) is int and data['selected_epoch'] == selected['update'],
            f"{path}: selected update violates pairs/hits/earlier selection")
    require(data.get('selected') == selected, f"{path}: selected record disagrees with trajectory")
    full = data.get('full_readouts')
    require(isinstance(full, list) and len(full) == 5, f"{path}: require five full readouts")
    for row, update in zip(full, [0, *SAVED]):
        label = f"{path}: full readout {update}"
        require(isinstance(row, dict) and type(row.get('update')) is int and row['update'] == update and
                type(row.get('epoch')) is int and row['epoch'] == update, f"{label}: invalid order/update/epoch")
        finite(row.get('mean_token_ce'), label + ' CE', True)
        groups = row.get('groups')
        require(isinstance(groups, dict) and set(groups) == {'concern', 'clean', 'voice', 'code'},
                f"{label}: require all four corpus groups")
        for kind, group in groups.items():
            expected = 20 if kind in ('concern', 'clean') else 12
            require(isinstance(group, dict) and count(group.get('examples'), label + kind) == expected,
                    f"{label}: unexpected {kind} example count")
            exact = count(group.get('exact_examples'), label + kind + ' exact', expected)
            tokens = count(group.get('tokens'), label + kind + ' tokens')
            correct = count(group.get('correct_tokens'), label + kind + ' correct tokens', tokens)
            require(tokens >= expected and (exact != expected or correct == tokens),
                    f"{label}: inconsistent {kind} token/exact counts")
            acc = finite(group.get('example_mean_token_accuracy'), label + kind + ' accuracy')
            require(0 <= acc <= 1 and acc >= exact / expected,
                    f"{label}: inconsistent {kind} accuracy")
            if kind in ('concern', 'clean'):
                reference = rows[update]['groups'][kind]
                require(count(group.get('decision_examples'), label + kind + ' decisions') == 20,
                        f"{label}: incomplete decision coverage")
                require(count(group.get('decision_correct'), label + kind + ' hits', 20) == reference['correct'] and
                        count(group.get('decision_positive_margin'), label + kind + ' positives', 20) == reference['positive_margin'],
                        f"{label}: decision counts disagree with trajectory")
                margin = finite(group.get('decision_mean_margin'), label + kind + ' margin')
                require(close(margin, reference['mean_margin']), f"{label}: decision margin disagrees with trajectory")
                require(exact <= group['decision_correct'] <= correct, f"{label}: incompatible exact/decision/token counts")
        require(count(row.get('review_pairs'), label + ' review pairs') == 20 and
                count(row.get('review_decision_pairs'), label + ' decision pairs') == 20,
                f"{label}: incomplete pair coverage")
        pairs = count(row.get('review_pairs_exact'), label + ' exact pairs', 20)
        bounds(pairs, groups['concern']['exact_examples'], groups['clean']['exact_examples'], label)
        decision_pairs = count(row.get('review_decision_pairs_exact'), label + ' exact decision pairs', 20)
        require(decision_pairs == rows[update]['complete_decision_pairs'] and pairs <= decision_pairs,
                f"{label}: exact decision pairs disagree")
    provenance = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}
    for key in ('metrics', 'sft'):
        digest = data.get(key + '_sha256')
        require(isinstance(data.get(key), str) and isinstance(digest, str) and len(digest) == 64 and
                all(c in '0123456789abcdef' for c in digest), f"{path}: invalid {key} provenance")
        provenance['declared_' + key] = data[key]
        provenance['declared_' + key + '_sha256'] = digest
    return data, provenance


def compact(row):
    concern, clean = (row['groups'][k] for k in ('concern', 'clean'))
    return {'update': row['update'], 'mean_decision_ce': row['mean_decision_ce'],
            'correct_targets': row['correct_targets'], 'complete_decision_pairs': row['complete_decision_pairs'],
            'concern_correct': concern['correct'], 'clean_correct': clean['correct'],
            'shared_mean_preference': (concern['mean_margin'] - clean['mean_margin']) / 2,
            'mean_pair_separation': concern['mean_margin'] + clean['mean_margin']}


def summarize(data):
    rows = data['trajectory']
    one_sided = {kind: [r['update'] for r in rows[1:] if r['correct_targets'] == 20 and
                       r['groups'][kind]['correct'] == 20 and
                       r['groups']['clean' if kind == 'concern' else 'concern']['correct'] == 0]
                 for kind in ('concern', 'clean')}
    updates = sorted(one_sided['concern'] + one_sided['clean'])
    return {'validated_updates': 101, 'post_update_count': 100, 'groups': {'concern': 20, 'clean': 20},
            'selection_rule': 'complete decision pairs, then correct targets, then earlier update',
            'selected': compact(data['selected']),
            'best_observed': compact(max(rows, key=select_key)),
            'minimum_ce': compact(min(rows, key=lambda r: (r['mean_decision_ce'], r['update']))),
            'eligible_checkpoints': [compact(rows[u]) for u in ELIGIBLE],
            'one_sided_target_correctness': {'scope': 'post-update 1..100', 'count': len(updates),
                'updates': updates, 'concern_only_count': len(one_sided['concern']),
                'concern_only_updates': one_sided['concern'], 'clean_only_count': len(one_sided['clean']),
                'clean_only_updates': one_sided['clean']}}


def equivalence(previous, current):
    differences, numeric_differences = [], []
    numeric_fields, max_absolute_difference = 0, 0.0

    def visit(a, b, path):
        nonlocal numeric_fields, max_absolute_difference
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                if key not in a or key not in b:
                    differences.append({'field': path + '.' + key, 'reason': 'missing field', 'within_tolerance': False})
                else:
                    visit(a[key], b[key], path + '.' + key)
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                differences.append({'field': path, 'reason': 'list length mismatch', 'within_tolerance': False})
            for i, (av, bv) in enumerate(zip(a, b)):
                visit(av, bv, f'{path}[{i}]')
        elif type(a) in (int, float) and type(b) in (int, float):
            numeric_fields += 1
            delta = abs(a - b)
            max_absolute_difference = max(max_absolute_difference, delta)
            if a != b:
                difference = {'field': path, 'previous': a, 'current': b, 'absolute_difference': delta,
                              'within_tolerance': close(a, b) if type(a) is float and type(b) is float else False}
                differences.append(difference)
                numeric_differences.append(difference)
        elif type(a) is not type(b) or a != b:
            differences.append({'field': path, 'previous': a, 'current': b, 'within_tolerance': False})

    visit(previous, current, 'initial')
    return {'exact': not differences, 'numerically_exact': not numeric_differences,
            'within_tolerance': all(d['within_tolerance'] for d in differences),
            'absolute_tolerance': ABS_TOL, 'relative_tolerance': REL_TOL,
            'numeric_fields_compared': numeric_fields, 'max_absolute_difference': max_absolute_difference,
            'discrepancies': differences}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous', type=Path, default=Path('training/results/2026-09-29-decision-only/scores.json'))
    parser.add_argument('--current', type=Path, default=Path('models/decision-small-step-scores.json'))
    parser.add_argument('--output', type=Path, default=Path('models/decision-small-step-trajectory-comparison.json'))
    parser.add_argument('--check-previous', action='store_true', help='validate previous scores only; write no file')
    args = parser.parse_args()
    previous, previous_source = load_scores(args.previous)
    previous_summary = summarize(previous)
    if args.check_previous:
        print(json.dumps({'status': 'previous_validated', 'source': previous_source,
                          'summary': previous_summary, 'interpretation': NOTE}, separators=(',', ':'), allow_nan=False))
        return 0
    require(args.current.exists(), f'current scores are not available: {args.current}; wait for the completed scorer output')
    current, current_source = load_scores(args.current)
    initial = {key: equivalence(previous[key][0], current[key][0]) for key in ('trajectory', 'full_readouts')}
    same_sft = previous['sft_sha256'] == current['sft_sha256']
    valid = same_sft and all(value['within_tolerance'] for value in initial.values())
    fields = ['mean_decision_ce', 'complete_decision_pairs', 'correct_targets', 'concern_correct',
              'clean_correct', 'shared_mean_preference', 'mean_pair_separation']
    comparison = []
    for a, b in zip(previous['trajectory'], current['trajectory']):
        old, new = compact(a), compact(b)
        comparison.append([a['update'], *[v for key in fields for v in (old[key], new[key])]])
    result = {'comparison_valid': valid, 'sources': {'previous': previous_source, 'current': current_source},
              'same_declared_sft_sha256': same_sft, 'initial_equivalence': initial,
              'previous': previous_summary, 'current': summarize(current),
              'trajectory_comparison': {'columns': ['update', *[f'{side}_{key}' for key in fields for side in ('previous', 'current')]],
                                        'rows': comparison}, 'interpretation': NOTE,
              'provenance_note': 'Score-file hashes are computed here. Embedded metrics/SFT hashes are reported as declared; their files are not re-read.'}
    require(args.output.resolve() not in (args.previous.resolve(), args.current.resolve()), 'output must not overwrite a score input')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'status': 'compared' if valid else 'initial_or_dataset_mismatch', 'output': str(args.output),
                      'comparison_valid': valid, 'initial_exact': {k: v['exact'] for k, v in initial.items()},
                      'previous_selected': previous['selected_update'], 'current_selected': current['selected_update']}, separators=(',', ':')))
    return 0 if valid else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({'status': 'error', 'error': str(error)}, separators=(',', ':')), file=sys.stderr)
        sys.exit(1)
