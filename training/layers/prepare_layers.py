#!/usr/bin/env python3
"""Serialize frozen layer-survey inputs and aggregate native C output.

No model inference, feature normalization, optimization or score calculation is
performed here. Float32 feature bytes are copied into C solver input matrices.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import sys

CORPUS_SHA = 'a677211e90576dea45ad4fa534fc97a3a6496944d63df99315ed934505936417'
RETAINED = ['scoped-python-analysis', 'approved-binary-decoder', 'sqlite-build-requirement', 'background-service-scope', 'model-parent-provenance', 'scoped-design-record', 'checksum-indirection', 'sequence-field-width', 'validated-port-conversion', 'negative-offset-type', 'exact-property-name', 'idempotent-event-retry', 'atomic-snapshot-publication', 'save-status-propagation']
QUARTETS = ['preserve-trie-credit', 'allocation-null-guard', 'zero-worker-guard', 'write-permission-check', 'stable-manifest-order', 'allocation-product-overflow']
FAMILIES = RETAINED + QUARTETS
SAME_DIFF = ['scoped-python-analysis', 'approved-binary-decoder', 'sqlite-build-requirement', 'background-service-scope', 'scoped-design-record', 'checksum-indirection']
FEATURES = ['native_prompt_token_count_without_common_prefix', 'added_lines', 'removed_lines', 'context_lines', 'after_if_statements', 'after_sort_calls', 'after_firwood_trie_occurrences']
BOUNDARIES = ['header', 'prefix']
PREFIX_IDS = [4913, 3903, 819]


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def reject_constant(value):
    raise ValueError('nonfinite JSON constant: ' + value)


def loads(text):
    return json.loads(text, parse_constant=reject_constant)


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def source(path):
    blob = path.read_bytes()
    return {'path': str(path), 'sha256': digest(blob), 'bytes': len(blob)}


def save(path, value):
    blob = value if isinstance(value, bytes) else (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()
    with path.open('xb') as handle:
        handle.write(blob)
        handle.flush()
        os.fsync(handle.fileno())
    return {'path': path.name, 'sha256': digest(blob), 'bytes': len(blob)}


def metadata(rows, width):
    lines = ['JOVOVICH_READOUT_V1', f'52 {width} 20 26']
    lines += [f"{r['label']} {r['family_index']} {r['pair_index']} {int(r['same_full_diff_subset'])}" for r in rows]
    return ('\n'.join(lines) + '\n').encode()


def prepare(repo, out):
    template_path = Path(__file__).with_name('protocol_template.json')
    protocol = loads(template_path.read_text())
    corpus = repo / 'training/sft_review_v5.jsonl'
    raw = corpus.read_bytes()
    require(digest(raw) == CORPUS_SHA, 'v5 corpus digest differs from the frozen source')
    all_rows = [loads(line) for line in raw.decode().splitlines()]
    reviews = [row for row in all_rows if row['kind'] == 'review']
    require(len(all_rows) == 76 and len(reviews) == 52, 'expected 76 corpus rows / 52 reviews')
    require(len({r['id'] for r in reviews}) == 52, 'duplicate review identifiers')
    pair_names = list(dict.fromkeys(r['pair'] for r in reviews))
    require(len(pair_names) == 26, 'expected 26 pairs')
    binary = bytearray(b'JVRO1\0\0\0' + struct.pack('<I', 52))
    rows, patches = [], {}
    for index, row in enumerate(reviews):
        require([m['role'] for m in row['messages']] == ['system', 'user', 'assistant'], 'unexpected message roles')
        system, user, answer = [m['content'] for m in row['messages']]
        for value in (system, user):
            require(isinstance(value, str) and '\0' not in value, 'invalid prompt string')
            blob = value.encode()
            binary.extend(struct.pack('<I', len(blob)))
            binary.extend(blob)
        gold = loads(answer)
        require(set(gold) == {'findings'} and isinstance(gold['findings'], list), 'invalid gold findings')
        label = int(bool(gold['findings']))
        pair = row['pair']
        matches = [family for family in FAMILIES if pair == family or (family in QUARTETS and pair in (family + '-deletion', family + '-replacement'))]
        require(len(matches) == 1, 'pair does not have exactly one frozen family')
        family = matches[0]
        require(user.count('\n\nSurrounding diff:\n') == 1, 'expected one surrounding diff')
        sections = user.split('\n\nSurrounding diff:\n')[1].split('\n\nChanged lines to review:\n')
        require(len(sections) == 2, 'expected one changed-line section')
        patch = sections[0]
        header, *body = patch.splitlines()
        hunk = re.fullmatch(r'@@ -(\d+),(\d+) \+(\d+),(\d+) @@', header)
        require(hunk is not None and all(line and line[0] in ' +-' for line in body), 'invalid hunk')
        require(sum(line[0] != '+' for line in body) == int(hunk[2]), 'before hunk extent differs')
        require(sum(line[0] != '-' for line in body) == int(hunk[4]), 'after hunk extent differs')
        after = '\n'.join(line[1:] for line in body if line[0] != '-')
        counts = [sum(line[0] == char for line in body) for char in '+- ']
        counts += [len(re.findall(r'\bif\s*\(', after)), len(re.findall(r'\.sort\s*\(', after)), after.count('firwood/trie')]
        rows.append({'index': index, 'id': row['id'], 'label': label, 'family': family,
                     'family_index': FAMILIES.index(family), 'pair': pair,
                     'pair_index': pair_names.index(pair), 'same_full_diff_subset': pair in SAME_DIFF,
                     'system_sha256': digest(system.encode()), 'user_sha256': digest(user.encode()),
                     'patch_sha256': digest(patch.encode()), 'nuisance_counts_without_prompt_tokens': counts})
        patches.setdefault(pair, []).append(patch)
    for pair in pair_names:
        rr = [row for row in rows if row['pair'] == pair]
        require(len(rr) == 2 and sorted(r['label'] for r in rr) == [0, 1], 'pair must contain concern and clean')
    for family in FAMILIES:
        rr = [row for row in rows if row['family'] == family]
        require(len(rr) == (2 if family in RETAINED else 4), 'unexpected family row count')
        require(sum(row['label'] for row in rr) * 2 == len(rr), 'unbalanced family')
    for pair in SAME_DIFF:
        require(patches[pair][0] == patches[pair][1], 'same-diff pair differs')
    old_rows_path = repo / 'training/results/2026-10-01-frozen-readout/readout-rows.json'
    old_rows = loads(old_rows_path.read_text())['rows']
    keys = ['index', 'id', 'label', 'family', 'family_index', 'pair', 'pair_index', 'same_full_diff_subset']
    require([[r[k] for k in keys] for r in rows] == [[r[k] for k in keys] for r in old_rows], 'v5 grouping or labels differ from frozen v4 grouping')
    old_mask_path = repo / 'training/results/2026-10-01-frozen-readout/readout-masks.json'
    old_masks = loads(old_mask_path.read_text())
    require(old_masks['family_order'] == FAMILIES, 'historical mask family order differs')
    mask = old_masks['masks'][0]
    require(len(mask) == 20 and set(mask) <= {'0', '1'} and '1' in mask, 'invalid fixed control mask')
    expected_mask_number = int.from_bytes(hashlib.sha256(b'jovovich-readout-permutation:20261001:0').digest()[:4], 'little') & ((1 << 20) - 1)
    require(mask == ''.join(str((expected_mask_number >> bit) & 1) for bit in range(20)), 'historical first-mask algorithm mismatch')
    require(not out.exists(), 'prepare requires a fresh output directory')
    out.mkdir(parents=True)
    files = [save(out / 'layers-input.bin', bytes(binary)),
             save(out / 'layers-rows.json', {'corpus_sha256': CORPUS_SHA, 'features': FEATURES, 'family_order': FAMILIES, 'pair_order': pair_names, 'rows': rows}),
             save(out / 'layers-metadata.txt', metadata(rows, 896)),
             save(out / 'nuisance-metadata.txt', metadata(rows, 7)),
             save(out / 'layers-masks.txt', ('JOVOVICH_MASKS_V1\n1 20\n' + mask + '\n').encode()),
             save(out / 'layers-masks.json', {'family_order': FAMILIES, 'masks': [mask], 'historical_mask_index': 0, 'historical_masks': source(old_mask_path)})]
    protocol['cohort']['family_order'] = FAMILIES
    protocol['cohort']['pair_order'] = pair_names
    protocol['input_bindings'] = files
    protocol['preparer'] = source(Path(__file__))
    protocol['template'] = source(template_path)
    protocol['corpus_binding'] = source(corpus)
    protocol['grouping_source'] = source(old_rows_path)
    save(out / 'layers-protocol.json', protocol)
    print(json.dumps({'status': 'prepared', 'directory': str(out), 'rows': 52, 'families': 20, 'files': files}))


def read_rows(out):
    protocol = loads((out / 'layers-protocol.json').read_text())
    require({binding['path'] for binding in protocol['input_bindings']} == {'layers-input.bin', 'layers-rows.json', 'layers-metadata.txt', 'nuisance-metadata.txt', 'layers-masks.txt', 'layers-masks.json'} and len(protocol['input_bindings']) == 6, 'prepared input inventory differs')
    for binding in protocol['input_bindings']:
        path = out / binding['path']
        require(path.parent == out, 'input binding must be a direct child of the run directory')
        raw = path.read_bytes()
        require(len(raw) == binding['bytes'] and digest(raw) == binding['sha256'], 'prepared input binding changed: ' + binding['path'])
    data = loads((out / 'layers-rows.json').read_text())
    require(data['corpus_sha256'] == CORPUS_SHA, 'unexpected row corpus')
    rows = data['rows']
    require(len(rows) == 52 and [r['index'] for r in rows] == list(range(52)), 'invalid row order')
    return rows


def views():
    result = [{'name': f'{boundary}-layer-{layer:02d}', 'boundary': boundary, 'layer_index': layer, 'width': 896, 'normalization': 'centered-rms'} for boundary in BOUNDARIES for layer in range(24)]
    result.append({'name': 'prefix-final-mlp-z', 'boundary': 'prefix', 'layer_index': 23, 'location': 'post-attention-pre-mlp', 'width': 896, 'normalization': 'centered-rms'})
    result.append({'name': 'nuisance', 'width': 7, 'normalization': 'per-feature-rms'})
    return result


def check_finite_f32(blob, count):
    require(len(blob) == count * 4, 'float32 byte count differs')
    require(all(math.isfinite(value[0]) for value in struct.iter_unpack('<f', blob)), 'nonfinite native feature')


def prompt_bindings(out, rows):
    """Verify every exact source string; never tokenize or execute its content."""
    raw = (out / 'layers-input.bin').read_bytes()
    require(raw[:8] == b'JVRO1\0\0\0' and len(raw) >= 12, 'wrong prompt container')
    require(struct.unpack_from('<I', raw, 8)[0] == 52, 'wrong prompt row count')
    offset = 12
    for row in rows:
        for name in ('system', 'user'):
            require(offset + 4 <= len(raw), 'truncated prompt length')
            size = struct.unpack_from('<I', raw, offset)[0]
            offset += 4
            require(size > 0 and offset + size <= len(raw), 'truncated prompt text')
            text = raw[offset:offset + size]
            offset += size
            text.decode('utf-8', errors='strict')
            require(b'\0' not in text and digest(text) == row[name + '_sha256'], 'prompt source binding differs')
    require(offset == len(raw), 'trailing prompt container bytes')


def validated_row(out, row_dir, index, trace_path, rows=None):
    require(type(index) is int and 0 <= index < 52, 'row index outside cohort')
    rows = read_rows(out) if rows is None else rows
    prompt_bindings(out, rows)
    width_bytes = 896 * 4
    path = row_dir / f'row-{index:03d}.bin'
    raw = path.read_bytes()
    require(raw[:8] == b'JVRL1\0\0\0', 'wrong layer row magic')
    require(len(raw) == 44 + 2 * 24 * width_bytes, 'wrong layer row byte length')
    require(struct.unpack_from('<4I', raw, 8) == (1, 24, 2, 896), 'wrong layer row dimensions')
    row_index, prompt_tokens, input_tokens, header_pos, prefix_pos = struct.unpack_from('<5I', raw, 24)
    require(row_index == index and prompt_tokens >= 3, 'wrong source row index or prompt length')
    require(input_tokens == prompt_tokens + 3 and header_pos == prompt_tokens - 1 and prefix_pos == input_tokens - 1, 'capture boundary differs')
    check_finite_f32(raw[44:], 2 * 24 * 896)
    anchor_path = row_dir / f'row-{index:03d}.z.bin'
    anchor = anchor_path.read_bytes()
    require(anchor[:8] == b'JVRF1\0\0\0' and len(anchor) == 16 + width_bytes, 'wrong row anchor framing')
    require(struct.unpack_from('<2I', anchor, 8) == (1, 896), 'wrong row anchor dimensions')
    check_finite_f32(anchor[16:], 896)
    records = [loads(line) for line in trace_path.read_text().splitlines()]
    require(len(records) == 1, 'expected exactly one native row trace')
    trace = records[0]
    expected = {'row': index, 'prompt_tokens': prompt_tokens, 'input_tokens': input_tokens,
                'feature_format': 'JVRL1', 'feature_shape': [2, 24, 896],
                'feature_order': ['position', 'layer', 'width'],
                'layer_boundary': 'post_block_before_next_layer_or_final_output_norm',
                'capture_positions': [header_pos, prefix_pos],
                'capture_names': ['assistant_header_end', 'common_prefix_end'],
                'prefix_ids': PREFIX_IDS, 'ordinary_capture_weights_modified': False,
                'fresh_kv': True, 'finite_features': True, 'capture_counts': [1] * 48}
    require(all(trace.get(k) == v for k, v in expected.items()), 'native trace fields differ')
    require(all(type(value) is int for value in trace['capture_counts']), 'capture counts must be integers')
    require(trace['fresh_kv'] is True and trace['finite_features'] is True and trace['ordinary_capture_weights_modified'] is False, 'native execution flags differ')
    require(type(trace.get('context_limit')) is int and trace['context_limit'] >= input_tokens, 'native context limit differs')
    ids = trace.get('input_ids')
    require(isinstance(ids, list) and len(ids) == input_tokens, 'native input ID count differs')
    require(all(type(token) is int and 0 <= token < 151936 for token in ids), 'invalid native token ID')
    require(ids[:3] == [151644, 8948, 198] and ids[header_pos - 2:header_pos + 1] == [151644, 77091, 198], 'Qwen ChatML system/assistant header differs')
    require(ids[-3:] == PREFIX_IDS and trace.get('capture_token_ids') == [ids[header_pos], ids[prefix_pos]], 'native boundary token IDs differ')
    expected_anchor = {'feature_format': 'JVRF1', 'feature_shape': [1, 896],
                       'capture_position': prefix_pos, 'layer': 23, 'boundary': 'pre_final_mlp',
                       'fresh_kv': True, 'temporary_zero_down': True,
                       'down_bias_temporarily_disabled': True, 'projection_restored': True}
    require(trace.get('anchor') == expected_anchor, 'native anchor trace differs')
    verification = trace.get('verification')
    if index in (0, 1):
        require(isinstance(verification, dict), 'first two rows require native verification')
    if verification is not None:
        require(verification.get('absolute_tolerance') == 1e-4 and verification.get('relative_l2_tolerance') == 1e-5, 'native verification tolerance differs')
        require(verification.get('future_suffixes') == [[4913, 3903], [819, 3903]], 'native causal intervention differs')
        comparisons = verification.get('comparisons')
        require(isinstance(comparisons, list) and [c['name'] for c in comparisons] == ['token_step', 'future_append', 'future_change'], 'native verification comparisons differ')
        for comparison in comparisons:
            require(comparison.get('vectors') == 48 and comparison.get('pass') is True, 'native verification failed or lost vectors')
            require(math.isfinite(comparison['max_abs']) and 0 <= comparison['max_abs'] <= 1e-4, 'native absolute verification gate failed')
            require(math.isfinite(comparison['max_relative_l2']) and 0 <= comparison['max_relative_l2'] <= 1e-5, 'native relative verification gate failed')
    info = {'row': index, 'prompt_tokens': prompt_tokens, 'input_tokens': input_tokens,
            'header_position': header_pos, 'prefix_position': prefix_pos,
            'system_sha256': rows[index]['system_sha256'], 'user_sha256': rows[index]['user_sha256'],
            'native_verified': verification is not None, 'sources': [source(path), source(anchor_path), source(trace_path)]}
    return raw, anchor, info


def validate_row(out, row_dir, index, trace):
    _, _, info = validated_row(out, row_dir, index, trace)
    print(json.dumps({'status': 'validated', **info}))


def assemble(out, row_dir):
    rows = read_rows(out)
    chunks = {view['name']: [] for view in views()}
    row_sources, token_counts = [], []
    width_bytes = 896 * 4
    for index in range(52):
        raw, anchor, info = validated_row(out, row_dir, index, row_dir / f'row-{index:03d}.trace.jsonl', rows)
        for position, boundary in enumerate(BOUNDARIES):
            for layer in range(24):
                offset = 44 + (position * 24 + layer) * width_bytes
                chunks[f'{boundary}-layer-{layer:02d}'].append(raw[offset:offset + width_bytes])
        chunks['prefix-final-mlp-z'].append(anchor[16:])
        counts = [info['prompt_tokens']] + rows[index]['nuisance_counts_without_prompt_tokens']
        require(len(counts) == 7 and all(type(v) is int and v >= 0 and v < (1 << 24) for v in counts), 'invalid exact-representable nuisance counts')
        chunks['nuisance'].append(struct.pack('<7f', *counts))
        token_counts.append({**{k: v for k, v in info.items() if k != 'sources'}, 'nuisance_counts': counts})
        row_sources.extend(info['sources'])
    files = []
    for view in views():
        raw = b'JVRF1\0\0\0' + struct.pack('<2I', 52, view['width']) + b''.join(chunks[view['name']])
        binding = save(out / (view['name'] + '.bin'), raw)
        files.append({**view, **binding})
    result = {'schema_version': 1, 'status': 'assembled', 'rows': 52, 'views': files,
              'row_sources': row_sources, 'boundaries': token_counts,
              'row_metadata': source(out / 'layers-rows.json'), 'assembler': source(Path(__file__))}
    save(out / 'layers-assembly.json', result)
    print(json.dumps({'status': 'assembled', 'views': len(files), 'rows': 52}))


def prediction_counts(predictions):
    require(len({p['row'] for p in predictions}) == len(predictions), 'duplicate scored row')
    groups = {}
    for prediction in predictions:
        groups.setdefault(prediction['pair'], []).append(prediction)
    require(all(len(group) == 2 and sorted(p['label'] for p in group) == [0, 1] for group in groups.values()), 'scoring requires complete opposite-label pairs')
    complete = [pair for pair, group in groups.items() if all(p['prediction'] == p['label'] for p in group)]
    same = [pair for pair, group in groups.items() if group[0]['subset']]
    return {'rows': len(predictions), 'correct': sum(p['prediction'] == p['label'] for p in predictions),
            'concern_rows': sum(p['label'] == 1 for p in predictions),
            'correct_concern': sum(p['prediction'] == p['label'] for p in predictions if p['label'] == 1),
            'clean_rows': sum(p['label'] == 0 for p in predictions),
            'correct_clean': sum(p['prediction'] == p['label'] for p in predictions if p['label'] == 0),
            'pairs': len(groups), 'complete_pairs': len(complete), 'complete_pair_indices': sorted(complete),
            'same_full_diff_pairs': len(same), 'same_full_diff_complete_pairs': sum(pair in complete for pair in same)}


def summarize_view(path, view, rows, mask):
    records = [loads(line) for line in path.read_text().splitlines()]
    require(len(records) == 65, 'expected 65 records per view')
    require(records[0]['type'] == 'configuration' and records[-1]['type'] == 'completion', 'missing native fit frame')
    config = records[0]
    expected = {'rows': 52, 'width': view['width'], 'families': 20, 'pairs': 26, 'permutations': 1,
                'normalization': view['normalization'], 'lambda': .01, 'interpolation_lambda': 1e-8,
                'gradient_tolerance': 1e-8, 'max_iterations': 100, 'intercept_penalized': False,
                'positive_class': 'concern', 'tie_class': 'clean', 'interpolation_mask_indices': [-1, 0],
                'armijo_c1': .0001, 'maximum_halvings': 60, 'direction_curvature_floor': 1e-12}
    require(all(config.get(key) == value for key, value in expected.items()), 'native fit configuration differs')
    require(records[-1] == {'type': 'completion', 'fits': 42, 'failed_fits': 0, 'all_converged': True}, 'native fits incomplete or unconverged')
    norms = [r for r in records if r['type'] == 'normalization']
    fits = [r for r in records if r['type'] == 'fit']
    require(len(norms) == 21 and len(fits) == 42, 'wrong fit or normalization count')
    require(sorted(r['heldout_family'] for r in norms) == list(range(-1, 20)), 'missing normalization folds')
    for norm in norms:
        held = norm['heldout_family']
        require(norm['training_rows'] == [r['index'] for r in rows if held < 0 or r['family_index'] != held], 'normalization training rows differ')
        require(len(norm['mean']) == view['width'] and len(norm['feature_population_std']) == view['width'], 'normalization width differs')
        require(all(math.isfinite(v) for v in norm['mean'] + norm['feature_population_std']), 'nonfinite normalization')
    by_key = {}
    for fit in fits:
        key = fit['mode'], fit['permutation'], fit['heldout_family']
        require(key not in by_key, 'duplicate fit')
        by_key[key] = fit
        mode, permutation, held = key
        require(mode in ('heldout', 'interpolation') and permutation in (-1, 0), 'unexpected fit kind')
        require(fit['converged'] and 0 <= fit['gradient_inf'] <= 1e-8 and 0 <= fit['iterations'] <= 100, 'native convergence gate failed')
        require(fit['lambda'] == (1e-8 if mode == 'interpolation' else .01), 'ridge differs')
        require(fit['train_rows'] == sum(held < 0 or r['family_index'] != held for r in rows), 'training fold size differs')
        require(all(math.isfinite(fit[k]) for k in ('objective', 'train_ce', 'gradient_inf', 'penalty', 'weight_norm', 'global_rms')), 'nonfinite fit summary')
        expected_rows = [r for r in rows if mode == 'interpolation' or r['family_index'] == held]
        require([p['row'] for p in fit['predictions']] == [r['index'] for r in expected_rows], 'prediction row order differs')
        for p, row in zip(fit['predictions'], expected_rows):
            require((p['family'], p['pair'], p['subset']) == (row['family_index'], row['pair_index'], int(row['same_full_diff_subset'])), 'prediction grouping differs')
            require(p['label'] == row['label'] ^ (int(mask[row['family_index']]) if permutation == 0 else 0), 'prediction label differs')
            require(math.isfinite(p['score']) and math.isfinite(p['probability']) and 0 <= p['probability'] <= 1, 'invalid prediction number')
            require(p['prediction'] == int(p['score'] > 0), 'prediction threshold differs')
    expected_keys = {('heldout', perm, family) for perm in (-1, 0) for family in range(20)} | {('interpolation', -1, -1), ('interpolation', 0, -1)}
    require(set(by_key) == expected_keys, 'native fit inventory differs')
    result = {**view, 'source': source(path), 'observed': {}, 'fixed_shuffled_control': {}, 'interpolation': []}
    for perm, name in ((-1, 'observed'), (0, 'fixed_shuffled_control')):
        predictions = sorted([p for family in range(20) for p in by_key['heldout', perm, family]['predictions']], key=lambda p: p['row'])
        require([p['row'] for p in predictions] == list(range(52)), 'heldout row coverage differs')
        result[name] = {**prediction_counts(predictions), 'predictions': predictions}
        fit = by_key['interpolation', perm, -1]
        counted = prediction_counts(fit['predictions'])
        require(counted['correct'] == fit['train_correct'], 'native and aggregated interpolation counts differ')
        result['interpolation'].append({**counted, 'permutation': perm, 'train_ce': fit['train_ce'], 'gradient_inf': fit['gradient_inf']})
    result['family_breakdown'] = [{'family': FAMILIES[family], 'family_index': family,
                                    **prediction_counts(by_key['heldout', -1, family]['predictions'])} for family in range(20)]
    result['convergence'] = {'fits': 42, 'all_converged': True, 'maximum_gradient_inf': max(f['gradient_inf'] for f in fits), 'maximum_iterations': max(f['iterations'] for f in fits)}
    return result


def summarize(out, fit_dir):
    rows = read_rows(out)
    mask_data = loads((out / 'layers-masks.json').read_text())
    require(mask_data['family_order'] == FAMILIES and len(mask_data['masks']) == 1, 'unexpected control masks')
    mask = mask_data['masks'][0]
    require(len(mask) == 20 and set(mask) <= {'0', '1'} and '1' in mask, 'invalid control mask')
    assembly = loads((out / 'layers-assembly.json').read_text())
    require(assembly['rows'] == 52 and [view['name'] for view in assembly['views']] == [view['name'] for view in views()], 'assembled view inventory differs')
    for actual, expected in zip(assembly['views'], views()):
        require(all(actual.get(key) == value for key, value in expected.items()), 'assembled view declaration differs')
        require(actual['path'] == expected['name'] + '.bin', 'assembled view path differs')
        raw = (out / actual['path']).read_bytes()
        require(len(raw) == actual['bytes'] and digest(raw) == actual['sha256'], 'assembled feature bytes changed')
    results = [summarize_view(fit_dir / (view['name'] + '.fits.jsonl'), view, rows, mask) for view in views()]
    summary = {'schema_version': 1, 'status': 'Complete exploratory 50-view table; all 2100 native fits converged.',
               'cohort': {'rows': 52, 'pairs': 26, 'families': 20},
               'analysis': 'Fixed-ridge family-held-out development survey, including all layers at both boundaries, fresh pre-final-MLP anchor and lexical/count baseline.',
               'views': results, 'protocol': source(out / 'layers-protocol.json'),
               'assembly': source(out / 'layers-assembly.json'), 'summarizer': source(Path(__file__))}
    save(out / 'layers-summary.json', summary)
    fields = ['view', 'correct', 'correct_concern', 'correct_clean', 'complete_pairs', 'shuffled_correct', 'shuffled_complete_pairs']
    lines = ['\t'.join(fields)]
    for result in results:
        obs, control = result['observed'], result['fixed_shuffled_control']
        lines.append('\t'.join(str(v) for v in [result['name'], obs['correct'], obs['correct_concern'], obs['correct_clean'], obs['complete_pairs'], control['correct'], control['complete_pairs']]))
    save(out / 'layers-table.tsv', ('\n'.join(lines) + '\n').encode())
    print(json.dumps({'status': 'summarized', 'views': 50, 'fits': 2100, 'table': str(out / 'layers-table.tsv')}))


def main():
    require(sys.flags.optimize == 0 and 'PYTHONOPTIMIZE' not in os.environ, 'Run with plain Python and PYTHONOPTIMIZE unset.')
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('--repo', type=Path, required=True)
    prep.add_argument('--out', type=Path, required=True)
    validator = commands.add_parser('validate-row')
    validator.add_argument('--out', type=Path, required=True)
    validator.add_argument('--row-dir', type=Path, required=True)
    validator.add_argument('--index', type=int, required=True)
    validator.add_argument('--trace', type=Path, required=True)
    assembly = commands.add_parser('assemble')
    assembly.add_argument('--out', type=Path, required=True)
    assembly.add_argument('--row-dir', type=Path, required=True)
    summary = commands.add_parser('summarize')
    summary.add_argument('--out', type=Path, required=True)
    summary.add_argument('--fit-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.repo.resolve(), args.out.resolve())
    elif args.command == 'validate-row':
        validate_row(args.out.resolve(), args.row_dir.resolve(), args.index, args.trace.resolve())
    elif args.command == 'assemble':
        assemble(args.out.resolve(), args.row_dir.resolve())
    else:
        summarize(args.out.resolve(), args.fit_dir.resolve())


if __name__ == '__main__':
    main()
