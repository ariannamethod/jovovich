#!/usr/bin/env python3
"""Independently recount every saved native fit and cross-check the public table.

This audit imports no layer helper, does not invoke the model or fit a classifier,
and uses the corpus gold plus native prediction records as its counting source.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

CORPUS_SHA = 'a677211e90576dea45ad4fa534fc97a3a6496944d63df99315ed934505936417'


def check(condition, detail):
    if not condition:
        raise RuntimeError(detail)


def reject(value):
    raise ValueError('Invalid JSON constant ' + value)


def parse(text):
    return json.loads(text, parse_constant=reject)


def sha(path):
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def finite_tree(item):
    if isinstance(item, float):
        check(math.isfinite(item), 'Nonfinite JSON number')
    elif isinstance(item, dict):
        for value in item.values():
            finite_tree(value)
    elif isinstance(item, list):
        for value in item:
            finite_tree(value)


def recount(predictions):
    by_pair = {}
    by_row = {}
    for prediction in predictions:
        row = prediction['row']
        check(row not in by_row, 'Repeated row in a scoring aggregate')
        by_row[row] = prediction
        by_pair.setdefault(prediction['pair'], []).append(prediction)
    complete, same_diff = [], []
    for pair, members in sorted(by_pair.items()):
        check(len(members) == 2 and {m['label'] for m in members} == {0, 1}, 'Unpaired scoring aggregate')
        if all(m['prediction'] == m['label'] for m in members):
            complete.append(pair)
        if members[0]['subset']:
            same_diff.append(pair)
    return {'rows': len(predictions), 'correct': sum(p['prediction'] == p['label'] for p in predictions),
            'concern_rows': sum(p['label'] == 1 for p in predictions),
            'correct_concern': sum(p['label'] == 1 and p['prediction'] == 1 for p in predictions),
            'clean_rows': sum(p['label'] == 0 for p in predictions),
            'correct_clean': sum(p['label'] == 0 and p['prediction'] == 0 for p in predictions),
            'pairs': len(by_pair), 'complete_pairs': len(complete), 'complete_pair_indices': complete,
            'same_full_diff_pairs': len(same_diff), 'same_full_diff_complete_pairs': len(set(complete) & set(same_diff))}


def equal_fields(expected, actual, detail):
    for key, value in expected.items():
        check(actual.get(key) == value, detail + ': ' + key)


def audit(run, corpus, output):
    check(not output.exists(), 'Audit output must be a fresh file')
    corpus_binding = sha(corpus)
    check(corpus_binding['sha256'] == CORPUS_SHA, 'Unexpected source corpus')
    corpus_rows = [parse(line) for line in corpus.read_text().splitlines()]
    reviews = [row for row in corpus_rows if row['kind'] == 'review']
    check(len(corpus_rows) == 76 and len(reviews) == 52, 'Unexpected corpus counts')
    row_document = parse((run / 'layers-rows.json').read_text())
    families = row_document['family_order']
    pair_order = row_document['pair_order']
    check(len(families) == len(set(families)) == 20 and len(pair_order) == len(set(pair_order)) == 26, 'Invalid family/pair inventory')
    check(len(row_document['rows']) == 52, 'Invalid row sidecar size')
    metadata_lines = (run / 'layers-metadata.txt').read_text().splitlines()
    check(metadata_lines[:2] == ['JOVOVICH_READOUT_V1', '52 896 20 26'] and len(metadata_lines) == 54, 'Invalid state metadata framing')
    metadata = [tuple(map(int, line.split())) for line in metadata_lines[2:]]
    nuisance_lines = (run / 'nuisance-metadata.txt').read_text().splitlines()
    check(nuisance_lines[:2] == ['JOVOVICH_READOUT_V1', '52 7 20 26'] and nuisance_lines[2:] == metadata_lines[2:], 'Nuisance grouping differs')
    for index, (row, meta) in enumerate(zip(reviews, metadata)):
        check(len(meta) == 4, 'Invalid metadata record width')
        label, family, pair, subset = meta
        gold = parse(row['messages'][-1]['content'])
        expected_label = int(len(gold['findings']) > 0)
        check(label == expected_label and pair_order[pair] == row['pair'], 'Corpus label/pair mismatch')
        check(0 <= family < 20 and subset in (0, 1), 'Invalid metadata family/subset')
        recorded = row_document['rows'][index]
        equal_fields({'index': index, 'id': row['id'], 'label': label, 'family_index': family,
                      'family': families[family], 'pair_index': pair, 'pair': row['pair'],
                      'same_full_diff_subset': bool(subset)}, recorded, 'Corpus/row sidecar mismatch')
    masks = (run / 'layers-masks.txt').read_text().splitlines()
    check(len(masks) == 3 and masks[:2] == ['JOVOVICH_MASKS_V1', '1 20'], 'Unexpected control mask framing')
    mask = masks[2]
    check(mask == '01110011100010100010', 'Unexpected prespecified family flip')
    summary = parse((run / 'layers-summary.json').read_text())
    names = [f'{position}-layer-{layer:02d}' for position in ('header', 'prefix') for layer in range(24)] + ['prefix-final-mlp-z', 'nuisance']
    check([v['name'] for v in summary['views']] == names, 'Summary view order/coverage differs')
    summary_views = {view['name']: view for view in summary['views']}
    table = (run / 'layers-table.tsv').read_text().splitlines()
    columns = ['view', 'correct', 'correct_concern', 'correct_clean', 'complete_pairs', 'shuffled_correct', 'shuffled_complete_pairs']
    check(len(table) == 51 and table[0].split('\t') == columns, 'Table layout differs')
    table_rows = [line.split('\t') for line in table[1:]]
    check([r[0] for r in table_rows] == names and all(len(r) == len(columns) for r in table_rows), 'Table view coverage differs')
    fit_sources, result_views = [], []
    outcome_count = normalizations = prediction_count = 0
    maximum_gradient = 0.0
    maximum_iterations = 0
    for view_index, name in enumerate(names):
        path = run / 'fits' / (name + '.fits.jsonl')
        records = [parse(line) for line in path.read_text().splitlines()]
        finite_tree(records)
        check(len(records) == 65, name + ': invalid record count')
        check(records[0]['type'] == 'configuration' and records[-1]['type'] == 'completion', name + ': missing native frame')
        width = 7 if name == 'nuisance' else 896
        normalization = 'per-feature-rms' if name == 'nuisance' else 'centered-rms'
        equal_fields({'rows': 52, 'width': width, 'families': 20, 'pairs': 26, 'permutations': 1,
                      'normalization': normalization, 'lambda': .01, 'interpolation_lambda': 1e-8,
                      'gradient_tolerance': 1e-8, 'max_iterations': 100,
                      'intercept_penalized': False, 'positive_class': 'concern', 'tie_class': 'clean',
                      'interpolation_mask_indices': [-1, 0], 'armijo_c1': .0001,
                      'maximum_halvings': 60, 'direction_curvature_floor': 1e-12}, records[0], name + ': configuration')
        check(records[-1] == {'type': 'completion', 'fits': 42, 'failed_fits': 0, 'all_converged': True}, name + ': completion failed')
        fold_norms, fitted = {}, {}
        for record in records[1:-1]:
            if record['type'] == 'normalization':
                fold = record['heldout_family']
                check(fold not in fold_norms, name + ': duplicate normalization')
                fold_norms[fold] = record
                expected_train = [i for i, row in enumerate(metadata) if fold == -1 or row[1] != fold]
                check(record['training_rows'] == expected_train, name + ': wrong normalization membership')
                check(len(record['mean']) == len(record['feature_population_std']) == width, name + ': normalization width')
                check(all(value >= 0 for value in record['feature_population_std']) and record['global_rms'] >= 0, name + ': invalid normalization scale')
                normalizations += 1
            elif record['type'] == 'fit':
                key = (record['mode'], record['permutation'], record['heldout_family'])
                check(key not in fitted, name + ': duplicate fit key')
                fitted[key] = record
                mode, permutation, held = key
                check(mode in ('heldout', 'interpolation') and permutation in (-1, 0), name + ': unexpected fit kind')
                check(record['converged'] is True and record['status'] == 'gradient_tolerance', name + ': unconverged fit')
                check(0 <= record['gradient_inf'] <= 1e-8 and type(record['iterations']) is int and 0 <= record['iterations'] <= 100, name + ': convergence bounds')
                check(record['lambda'] == (1e-8 if mode == 'interpolation' else .01), name + ': wrong fit ridge')
                train_count = sum(held == -1 or row[1] != held for row in metadata)
                check(record['train_rows'] == train_count and 0 <= record['train_correct'] <= train_count, name + ': invalid training counts')
                check(record['train_ce'] >= 0 and record['penalty'] >= 0 and record['weight_norm'] >= 0, name + ': invalid objective records')
                expected_rows = [i for i, row in enumerate(metadata) if mode == 'interpolation' or row[1] == held]
                check([p['row'] for p in record['predictions']] == expected_rows, name + ': prediction membership')
                for prediction in record['predictions']:
                    row = prediction['row']; label, family, pair, subset = metadata[row]
                    label ^= int(mask[family]) if permutation == 0 else 0
                    equal_fields({'family': family, 'pair': pair, 'subset': subset, 'label': label}, prediction, name + ': prediction label/group')
                    check(type(prediction['prediction']) is int and prediction['prediction'] == int(prediction['score'] > 0), name + ': threshold')
                    check(0 <= prediction['probability'] <= 1, name + ': probability bounds')
                    prediction_count += 1
                outcome_count += 1
                maximum_gradient = max(maximum_gradient, record['gradient_inf'])
                maximum_iterations = max(maximum_iterations, record['iterations'])
            else:
                raise RuntimeError(name + ': unexpected native record type')
        check(set(fold_norms) == set(range(-1, 20)), name + ': missing fold normalizations')
        expected_keys = {('heldout', perm, family) for perm in (-1, 0) for family in range(20)} | {('interpolation', perm, -1) for perm in (-1, 0)}
        check(set(fitted) == expected_keys, name + ': missing or extra fitted outcomes')
        declared = summary_views[name]
        collected = {}
        for perm, field in ((-1, 'observed'), (0, 'fixed_shuffled_control')):
            predictions = sorted([p for family in range(20) for p in fitted['heldout', perm, family]['predictions']], key=lambda p: p['row'])
            check([p['row'] for p in predictions] == list(range(52)), name + ': full heldout coverage')
            counts = recount(predictions)
            equal_fields(counts, declared[field], name + ': summary ' + field)
            check(declared[field]['predictions'] == predictions, name + ': saved score/probability trace differs')
            collected[field] = counts
        for item, perm in zip(declared['interpolation'], (-1, 0)):
            fit = fitted['interpolation', perm, -1]
            counts = recount(fit['predictions'])
            check(counts['correct'] == fit['train_correct'], name + ': interpolation recount differs')
            equal_fields({**counts, 'permutation': perm, 'train_ce': fit['train_ce'], 'gradient_inf': fit['gradient_inf']}, item, name + ': interpolation summary')
        check(len(declared['interpolation']) == 2 and len(declared['family_breakdown']) == 20, name + ': secondary summary coverage')
        for family in range(20):
            expected = {'family': families[family], 'family_index': family, **recount(fitted['heldout', -1, family]['predictions'])}
            equal_fields(expected, declared['family_breakdown'][family], name + ': family summary')
        equal_fields({'fits': 42, 'all_converged': True, 'maximum_gradient_inf': max(f['gradient_inf'] for f in fitted.values()), 'maximum_iterations': max(f['iterations'] for f in fitted.values())}, declared['convergence'], name + ': convergence summary')
        observed, shuffled = collected['observed'], collected['fixed_shuffled_control']
        expected_table = [name, observed['correct'], observed['correct_concern'], observed['correct_clean'], observed['complete_pairs'], shuffled['correct'], shuffled['complete_pairs']]
        check(table_rows[view_index] == [str(value) for value in expected_table], name + ': TSV differs')
        result_views.append({'name': name, **collected})
        fit_sources.append(sha(path))
    check(outcome_count == 2100 and normalizations == 1050 and prediction_count == 10400, 'Final evidence inventory differs')
    profile = []
    for layer in range(24):
        header = result_views[layer]['observed']
        prefix = result_views[layer + 24]['observed']
        profile.append({'layer_index': layer, 'header_correct': header['correct'], 'header_complete_pairs': header['complete_pairs'], 'prefix_correct': prefix['correct'], 'prefix_complete_pairs': prefix['complete_pairs']})
    report = {'schema_version': 1, 'status': 'pass',
              'scope': 'Development-cohort fixed-ridge family-held-out 50-view survey, independently recounted from all native prediction records.',
              'native_fits': outcome_count, 'converged_native_fits': outcome_count,
              'normalizations_checked': normalizations, 'predictions_checked': prediction_count,
              'maximum_gradient_inf': maximum_gradient, 'maximum_iterations': maximum_iterations,
              'all_json_and_tsv_counts_match': True, 'views': result_views, 'depth_profile': profile,
              'source_corpus': corpus_binding, 'fit_sources': fit_sources,
              'summary': sha(run / 'layers-summary.json'), 'table': sha(run / 'layers-table.tsv'),
              'audit_source': sha(Path(__file__))}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({key: report[key] for key in ('status', 'native_fits', 'converged_native_fits', 'normalizations_checked', 'predictions_checked', 'maximum_gradient_inf', 'maximum_iterations')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--corpus', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    audit(args.run.resolve(), (args.corpus or args.run / 'snapshot/training/sft_review_v5.jsonl').resolve(), args.out.resolve())
