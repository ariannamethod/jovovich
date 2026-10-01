#!/usr/bin/env python3
"""Audit native saved predictions and aggregate prespecified descriptive counts.

No fitting, normalization, logits or model arithmetic is performed here.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

def source(path):
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}

def reject_constant(value):
    raise ValueError(f'nonfinite JSON constant: {value}')

def load(path):
    return json.loads(path.read_text(), parse_constant=reject_constant)

def counts(predictions, rows):
    predictions = sorted(predictions, key=lambda p: p['row'])
    indices = [p['row'] for p in predictions]
    assert len(set(indices)) == len(indices)
    correct = {p['row']: p['prediction'] == p['label'] for p in predictions}
    pairs = sorted(set(rows[i]['pair_index'] for i in indices))
    pair_members = {pair: [p for p in predictions if p['pair'] == pair] for pair in pairs}
    assert all(len(rr) == 2 and sorted(p['label'] for p in rr) == [0, 1] for rr in pair_members.values())
    pair_pass = [pair for pair, rr in pair_members.items() if all(correct[p['row']] for p in rr)]
    same_pairs = [pair for pair, rr in pair_members.items() if rr[0]['subset']]
    return {"rows": len(predictions), "correct": sum(correct.values()),
            "concern_rows": sum(p['label'] == 1 for p in predictions),
            "correct_concern": sum(correct[p['row']] for p in predictions if p['label'] == 1),
            "clean_rows": sum(p['label'] == 0 for p in predictions),
            "correct_clean": sum(correct[p['row']] for p in predictions if p['label'] == 0),
            "pairs": len(pairs), "complete_pairs": len(pair_pass), "complete_pair_indices": pair_pass,
            "same_full_diff_pairs": len(same_pairs),
            "same_full_diff_complete_pairs": sum(pair in pair_pass for pair in same_pairs),
            "exact_zero_score_rows": sum(p['score'] == 0 for p in predictions)}

def audit_view(path, rows, masks, normalization, width):
    records = [json.loads(line, parse_constant=reject_constant) for line in path.read_text().splitlines()]
    assert records[0]['type'] == 'configuration' and records[-1]['type'] == 'completion'
    config, completion = records[0], records[-1]
    expected = dict(rows=52, width=width, families=20, pairs=26, permutations=99,
                    normalization=normalization, **{'lambda': 0.01}, interpolation_lambda=1e-8,
                    gradient_tolerance=1e-8, max_iterations=100, intercept_penalized=False,
                    positive_class='concern', tie_class='clean', interpolation_mask_indices=[-1, 0],
                    armijo_c1=0.0001, maximum_halvings=60, direction_curvature_floor=1e-12)
    for key, value in expected.items():
        assert config[key] == value, (key, config.get(key), value)
    assert completion == {'type': 'completion', 'fits': 2002, 'failed_fits': 0, 'all_converged': True}
    fits = [r for r in records if r['type'] == 'fit']
    norms = [r for r in records if r['type'] == 'normalization']
    assert len(records) == 2025 and len(fits) == 2002 and len(norms) == 21
    assert sorted(r['heldout_family'] for r in norms) == list(range(-1, 20))
    for norm in norms:
        held = norm['heldout_family']
        assert norm['training_rows'] == [r['index'] for r in rows if held < 0 or r['family_index'] != held]
        assert len(norm['mean']) == width and len(norm['feature_population_std']) == width
        assert all(math.isfinite(x) for x in norm['mean'] + norm['feature_population_std'])
    by_key = {}
    for fit in fits:
        key = fit['mode'], fit['permutation'], fit['heldout_family']
        assert key not in by_key
        by_key[key] = fit
        mode, permutation, held = key
        assert mode in ('heldout', 'interpolation') and -1 <= permutation < 99
        assert fit['converged'] and fit['gradient_inf'] <= 1e-8
        assert 0 <= fit['iterations'] <= 100
        assert fit['lambda'] == (1e-8 if mode == 'interpolation' else 0.01)
        assert fit['train_rows'] == sum(held < 0 or r['family_index'] != held for r in rows)
        for keynum in ('objective', 'train_ce', 'gradient_inf', 'penalty', 'weight_norm', 'global_rms'):
            assert math.isfinite(fit[keynum])
        wanted = [r for r in rows if mode == 'interpolation' or r['family_index'] == held]
        assert [p['row'] for p in fit['predictions']] == [r['index'] for r in wanted]
        for p, row in zip(fit['predictions'], wanted):
            assert p['family'] == row['family_index'] and p['pair'] == row['pair_index']
            assert p['subset'] == int(row['same_full_diff_subset'])
            expected_label = row['label'] ^ (int(masks[permutation][row['family_index']]) if permutation >= 0 else 0)
            assert p['label'] == expected_label
            assert math.isfinite(p['score']) and 0 <= p['probability'] <= 1
            assert p['prediction'] == int(p['score'] > 0)
    assert set(by_key) == {('heldout', p, f) for p in range(-1, 99) for f in range(20)} | {('interpolation', -1, -1), ('interpolation', 0, -1)}
    scores, observed_predictions = [], []
    for permutation in range(-1, 99):
        predictions = [p for f in range(20) for p in by_key['heldout', permutation, f]['predictions']]
        assert sorted(p['row'] for p in predictions) == list(range(52))
        item = counts(predictions, rows)
        item['permutation'] = permutation
        scores.append(item)
        if permutation == -1:
            observed_predictions = sorted(predictions, key=lambda p: p['row'])
    capacity = []
    for permutation in (-1, 0):
        fit = by_key['interpolation', permutation, -1]
        item = counts(fit['predictions'], rows)
        assert item['correct'] == fit['train_correct']
        item.update(permutation=permutation, train_ce=fit['train_ce'], gradient_inf=fit['gradient_inf'],
                    converged=fit['converged'], capacity_success=item['correct'] == 52 and fit['train_ce'] <= 0.001)
        capacity.append(item)
    families = []
    for family in range(20):
        predictions = by_key['heldout', -1, family]['predictions']
        item = counts(predictions, rows)
        item.update(family_index=family, family=next(r['family'] for r in rows if r['family_index'] == family))
        families.append(item)
    return {'configuration': config, 'completion': completion, 'observed': scores[0],
            'permutations': scores[1:], 'capacity': capacity, 'family_breakdown': families,
            'observed_predictions': observed_predictions,
            'convergence': {'fits': len(fits), 'all_converged': True, 'maximum_gradient_inf': max(f['gradient_inf'] for f in fits),
                            'maximum_iterations': max(f['iterations'] for f in fits), 'total_curvature_floors': sum(f['curvature_floors'] for f in fits),
                            'total_line_search_backtracks': sum(f['backtracks'] for f in fits)}}

def tail(observed, reference):
    assert len(reference) == 99
    exceeds = sum(value >= observed for value in reference)
    return {'observed': observed, 'reference_count': 99, 'reference_at_least_observed': exceeds,
            'plus_one_upper_tail_fraction': (1 + exceeds) / 100,
            'reference_minimum': min(reference), 'reference_maximum': max(reference), 'reference_statistics': reference,
            'interpretation': 'Exploratory conditional family-label permutation reference; not confirmatory significance.'}

def main(args):
    rowdata, maskdata = load(args.rows), load(args.masks_json)
    rows, masks = rowdata['rows'], maskdata['masks']
    assert len(rows) == 52 and [r['index'] for r in rows] == list(range(52))
    assert len(masks) == len(set(masks)) == 99 and all(len(m) == 20 and set(m) <= {'0', '1'} and '1' in m for m in masks)
    assert rowdata['family_order'] == maskdata['family_order']
    z = audit_view(args.z, rows, masks, 'centered-rms', 896)
    nuisance = audit_view(args.nuisance, rows, masks, 'per-feature-rms', 7)
    z_observed, nuisance_observed = z['observed']['complete_pairs'], nuisance['observed']['complete_pairs']
    z_null = [r['complete_pairs'] for r in z['permutations']]
    nuisance_null = [r['complete_pairs'] for r in nuisance['permutations']]
    report = {'schema_version': 1, 'status': 'All 4004 preregistered native fits converged; descriptive prediction aggregation complete.',
              'primary_statistic': 'Complete pairs among 26 template-family-held-out concern/clean pairs for z.',
              'views': {'z': z, 'nuisance': nuisance},
              'permutation_references': {'z_complete_pairs': tail(z_observed, z_null),
                                         'nuisance_complete_pairs': tail(nuisance_observed, nuisance_null),
                                         'paired_z_minus_nuisance_complete_pairs': tail(z_observed-nuisance_observed, [a-b for a,b in zip(z_null,nuisance_null)])},
              'limits': ['Binary classification at supplied common prefix, not natural complete review generation.',
                         'Template-family holdouts are not independent unseen semantic domains.',
                         'The nuisance baseline tests seven prespecified features, not all possible shortcuts.',
                         'Previous 3/26 full-vocabulary training decision pairs and 0/26 complete review pairs are descriptive context; differing tasks and train/heldout evaluation prevent direct causal comparison.',
                         'Accessible information does not identify the sole cause of prior model training failures.',
                         'No confirmatory fresh cases are included; family exchangeability is an assumption.'],
              'sources': [source(p) for p in (args.z, args.nuisance, args.rows, args.masks_json, Path(__file__))]}
    with args.output.open('x') as f:
        json.dump(report, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write('\n')
    print(json.dumps({'output': str(args.output), 'z_complete_pairs': z_observed, 'nuisance_complete_pairs': nuisance_observed,
                      'paired_difference': z_observed-nuisance_observed, 'fits': 4004}))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--z', type=Path, required=True)
    parser.add_argument('--nuisance', type=Path, required=True)
    parser.add_argument('--rows', type=Path, required=True)
    parser.add_argument('--masks-json', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args())
