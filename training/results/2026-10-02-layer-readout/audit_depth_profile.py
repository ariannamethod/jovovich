#!/usr/bin/env python3
"""Independent depth-profile recount from corpus labels and native records."""
import argparse
import collections
import datetime
import hashlib
import json
import math
from pathlib import Path
import re


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def binding(path):
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def read_json(path):
    return json.loads(path.read_text(), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def cohort(run):
    source = run / 'snapshot/training/sft_review_v5.jsonl'
    require(binding(source)['sha256'] == 'a677211e90576dea45ad4fa534fc97a3a6496944d63df99315ed934505936417', 'corpus changed')
    reviews = [json.loads(line) for line in source.read_text().splitlines() if json.loads(line)['kind'] == 'review']
    metadata = [tuple(map(int, line.split())) for line in (run / 'layers-metadata.txt').read_text().splitlines()[2:]]
    require(len(reviews) == len(metadata) == 52, 'row coverage')
    pairs, families, patches, labels = {}, {}, {}, []
    row_pairs, row_families = [], []
    pair_members = collections.defaultdict(list)
    for index, (review, native) in enumerate(zip(reviews, metadata)):
        label, family_index, pair_index, subset = native
        gold = json.loads(review['messages'][2]['content'])
        wanted = int(bool(gold['findings']))
        require(label == wanted, 'native label differs from source gold')
        pair = review['pair']
        family = re.sub(r'-(?:deletion|replacement)$', '', pair)
        require(pairs.setdefault(pair_index, pair) == pair, 'pair slot changed')
        require(families.setdefault(family_index, family) == family, 'family slot split or combined')
        patches[index] = review['messages'][1]['content'].split('\n\nSurrounding diff:\n')[1].split('\n\nChanged lines to review:\n')[0]
        labels.append(wanted)
        row_pairs.append(pair)
        row_families.append(family)
        pair_members[pair].append(index)
    require(set(pairs) == set(range(26)) and len(set(pairs.values())) == 26, 'pair inventory')
    require(set(families) == set(range(20)) and len(set(families.values())) == 20, 'family inventory')
    require(all(len(rows) == 2 and sorted(labels[i] for i in rows) == [0, 1] for rows in pair_members.values()), 'source pair balance')
    same = {pair for pair, members in pair_members.items() if patches[members[0]] == patches[members[1]]}
    require(len(same) == 6 and all(native[3] == int(row_pairs[i] in same) for i, native in enumerate(metadata)), 'same-diff membership')
    return {'source': source, 'metadata': metadata, 'labels': labels, 'pairs': pairs, 'families': families,
            'row_pairs': row_pairs, 'row_families': row_families, 'pair_members': pair_members, 'same': same}


def count(predictions, labels, data):
    correct = [predictions[i] == labels[i] for i in range(52)]
    complete = [pair for pair, members in data['pair_members'].items() if all(correct[i] for i in members)]
    per_family = {}
    for family in data['families'].values():
        members = [i for i, value in enumerate(data['row_families']) if value == family]
        family_pairs = {data['row_pairs'][i] for i in members}
        per_family[family] = {'correct': sum(correct[i] for i in members), 'rows': len(members),
                              'complete_pairs': sum(pair in complete for pair in family_pairs), 'pairs': len(family_pairs)}
    return {'correct': sum(correct), 'correct_concern': sum(correct[i] for i in range(52) if labels[i]),
            'correct_clean': sum(correct[i] for i in range(52) if not labels[i]),
            'complete_pairs': len(complete), 'complete_pair_names': complete,
            'same_full_diff_complete_pairs': len(set(complete) & data['same']),
            'same_full_diff_complete_pair_names': sorted(set(complete) & data['same']),
            'per_family': per_family}


def extrema(views, field):
    low, high = min(v['observed'][field] for v in views), max(v['observed'][field] for v in views)
    return {'minimum': low, 'maximum': high,
            'minimum_views': [v['name'] for v in views if v['observed'][field] == low],
            'maximum_views': [v['name'] for v in views if v['observed'][field] == high]}


def audit(run, output):
    require(not output.exists(), 'output must be new')
    require((run / '_units/summarize.result.json').exists(), 'wait for closed summary result')
    require(read_json(run / '_units/summarize.result.json')['status'] == 'completed', 'summary not completed')
    data = cohort(run)
    mask = (run / 'layers-masks.txt').read_text().splitlines()[-1]
    require(mask == '01110011100010100010', 'mask0 changed')
    names = [f'{boundary}-layer-{layer:02d}' for boundary in ('header', 'prefix') for layer in range(24)] + ['prefix-final-mlp-z', 'nuisance']
    declared = read_json(run / 'layers-summary.json')['views']
    require([view['name'] for view in declared] == names, 'summary view order')
    all_views, sources = [], []
    fit_count = prediction_count = normalization_count = 0
    max_gradient = 0.0
    max_iterations = 0
    for view_number, name in enumerate(names):
        path = run / 'fits' / (name + '.fits.jsonl')
        records = [json.loads(line) for line in path.read_text().splitlines()]
        require(len(records) == 65, 'native record count')
        fit_map = {}
        normalizations = {}
        for record in records:
            if record['type'] == 'normalization':
                fold = record['heldout_family']
                require(fold not in normalizations, 'duplicate normalization')
                normalizations[fold] = record
                expected_train = [i for i, meta in enumerate(data['metadata']) if fold == -1 or meta[1] != fold]
                require(record['training_rows'] == expected_train, 'normalization membership')
                normalization_count += 1
            if record['type'] != 'fit':
                continue
            key = (record['mode'], record['permutation'], record['heldout_family'])
            require(key not in fit_map, 'duplicate fit')
            fit_map[key] = record
            require(record['converged'] is True and record['status'] == 'gradient_tolerance', 'unconverged fit')
            require(math.isfinite(record['gradient_inf']) and 0 <= record['gradient_inf'] <= 1e-8, 'gradient gate')
            require(type(record['iterations']) is int and 0 <= record['iterations'] <= 100, 'iteration gate')
            max_gradient = max(max_gradient, record['gradient_inf'])
            max_iterations = max(max_iterations, record['iterations'])
            fit_count += 1
            mode, perm, fold = key
            require(record['lambda'] == (1e-8 if mode == 'interpolation' else .01), 'ridge changed')
            expected_rows = [i for i, meta in enumerate(data['metadata']) if mode == 'interpolation' or meta[1] == fold]
            require([p['row'] for p in record['predictions']] == expected_rows, 'prediction membership')
            for p in record['predictions']:
                index = p['row']
                _, family, pair, subset = data['metadata'][index]
                expected_label = data['labels'][index] ^ (int(mask[family]) if perm == 0 else 0)
                require((p['family'], p['pair'], p['subset'], p['label']) == (family, pair, subset, expected_label), 'prediction source identity')
                require(math.isfinite(p['score']) and p['prediction'] == int(p['score'] > 0), 'score or tie threshold')
                prediction_count += 1
        expected_fits = {('heldout', perm, family) for perm in (-1, 0) for family in range(20)} | {('interpolation', perm, -1) for perm in (-1, 0)}
        require(set(fit_map) == expected_fits and set(normalizations) == set(range(-1, 20)), 'fit/fold inventory')
        require(records[-1] == {'type': 'completion', 'fits': 42, 'failed_fits': 0, 'all_converged': True}, 'fit completion')
        view = {'name': name}
        for permutation, field in ((-1, 'observed'), (0, 'fixed_mask0')):
            predictions = {}
            for fold in range(20):
                for p in fit_map['heldout', permutation, fold]['predictions']:
                    require(p['row'] not in predictions, 'duplicate heldout row')
                    predictions[p['row']] = p['prediction']
            require(set(predictions) == set(range(52)), 'heldout coverage')
            labels = [label ^ (int(mask[data['metadata'][i][1]]) if permutation == 0 else 0) for i, label in enumerate(data['labels'])]
            counted = count(predictions, labels, data)
            destination = declared[view_number]['observed' if permutation == -1 else 'fixed_shuffled_control']
            for metric in ('correct', 'correct_concern', 'correct_clean', 'complete_pairs', 'same_full_diff_complete_pairs'):
                require(counted[metric] == destination[metric], 'summary differs: ' + name + '/' + metric)
            view[field] = counted
        view['interpolation'] = []
        for perm in (-1, 0):
            record = fit_map['interpolation', perm, -1]
            correct = sum(p['prediction'] == p['label'] for p in record['predictions'])
            require(correct == record['train_correct'], 'interpolation recount')
            view['interpolation'].append({'permutation': perm, 'correct': correct, 'train_ce': record['train_ce']})
        all_views.append(view)
        sources.append(binding(path))
    require((fit_count, normalization_count, prediction_count) == (2100, 1050, 10400), 'full native coverage')
    by_name = {view['name']: view for view in all_views}
    profile = {boundary: {field: extrema(all_views[start:start+24], field) for field in ('correct', 'complete_pairs', 'same_full_diff_complete_pairs')}
               for boundary, start in (('header', 0), ('prefix', 24))}
    comparison = {name: by_name[name] for name in ('header-layer-23', 'prefix-layer-23', 'prefix-final-mlp-z', 'nuisance')}
    state_views = all_views[:49]
    null_comparison = {}
    for metric in ('correct', 'complete_pairs', 'same_full_diff_complete_pairs'):
        differences = [view['observed'][metric] - view['fixed_mask0'][metric] for view in state_views]
        null_comparison[metric] = {'observed_greater': sum(d > 0 for d in differences), 'equal': sum(d == 0 for d in differences),
                                   'observed_less': sum(d < 0 for d in differences), 'difference_range': [min(differences), max(differences)]}
    report = {'schema_version': 1, 'status': 'pass', 'auditor': 'independent layer_auditor agent',
              'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'method': 'Native prediction recount using labels from v5 gold, family names independently derived from pair suffixes, and same-full-diff membership derived by literal source diff equality. No experiment helper or other audit module is imported.',
              'native_fits': fit_count, 'normalization_memberships_checked': normalization_count, 'predictions_checked': prediction_count,
              'all_fits_converged': True, 'maximum_gradient_inf': max_gradient, 'maximum_iterations': max_iterations,
              'profile': profile, 'final_boundary_anchor_lexical_comparison': comparison, 'state_views_vs_fixed_mask0': null_comparison,
              'views': all_views, 'fit_sources': sources, 'source_corpus': binding(data['source']),
              'summary': binding(run / 'layers-summary.json'), 'audit_source': binding(Path(__file__)),
              'additional_model_calls': 0, 'bound_files_modified': False}
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({key: report[key] for key in ('status', 'native_fits', 'maximum_gradient_inf', 'maximum_iterations', 'profile', 'state_views_vs_fixed_mask0')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    audit(args.run.resolve(), args.output.resolve())
