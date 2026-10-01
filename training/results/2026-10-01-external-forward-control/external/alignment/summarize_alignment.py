"""Aggregate saved native scalar measurements; no tensor or model computation."""
import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def record(path):
    path = Path(path).resolve()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return dict(path=str(path), bytes=path.stat().st_size, sha256=digest.hexdigest())


def sign(value):
    return 1 if value > 0 else -1 if value < 0 else 0


def main():
    plan_path = HERE / 'execution-plan.json'
    receipt_path = HERE / 'run-1/receipt.json'
    plan = json.loads(plan_path.read_text())
    receipt = json.loads(receipt_path.read_text())
    require(receipt['status'] == 'completed' and receipt['sources_unchanged'] is True
            and receipt['dynamic_unchanged'] is True and receipt['plan_unchanged'] is True,
            'alignment execution did not complete with unchanged inputs')
    require(receipt['plan_before'] == receipt['plan_after'] == record(plan_path), 'receipt plan differs')
    require(len(receipt['phases']) == len(plan['phases']) == 10
            and [item['name'] for item in receipt['phases']] == [item['name'] for item in plan['phases']]
            and all(item['status'] == 'completed' and item['exit_code'] == 0
                    and item['sources_unchanged'] is True and item['dynamic_unchanged'] is True
                    for item in receipt['phases']), 'incomplete alignment phases')
    require(receipt['model_forward_processes_started'] == 4 and receipt['conversion_processes_started'] == 1,
            'unexpected execution count')
    validation_binding = record(plan['validation_receipt'])
    require(receipt['validation_receipt'] == validation_binding, 'conversion proof changed')
    validation = json.loads(Path(plan['validation_receipt']).read_text())
    require(validation['status'] == 'completed' and validation['every_tensor_exact'] is True
            and validation['all_finite'] is True and validation['semantic_metadata_exact'] is True,
            'exact-weight proof incomplete')
    groups = {name: [] for name in ('native-packing', 'aligned-engine')}
    for phase, result in zip(plan['phases'], receipt['phases']):
        if phase['kind'] != 'metric_comparison':
            continue
        binding = record(phase['stdout'])
        require(binding in result['artifacts'], 'scalar metric file changed after comparison')
        rows = [json.loads(line) for line in Path(phase['stdout']).read_text().splitlines()]
        require(len(rows) == 2 and [row['prefix_tokens'] for row in rows] == [444, 447], 'capture pair incomplete')
        for capture, metrics in zip(('assistant_header', 'shared_prefix'), rows):
            require(metrics['vocabulary'] == 151936 and all(math.isfinite(metrics[key]) for key in
                ('max_abs', 'relative_l2', 'first_concern_minus_clean', 'second_concern_minus_clean')),
                'invalid saved metrics')
            first_sign, second_sign = sign(metrics['first_concern_minus_clean']), sign(metrics['second_concern_minus_clean'])
            groups[phase['comparison_kind']].append(dict(case=phase['name'].split('-')[0],
                capture=capture, metrics=metrics, first_decision_margin_sign=first_sign,
                second_decision_margin_sign=second_sign, decision_margin_sign_agree=first_sign == second_sign,
                source_metrics=binding, first_dump=record(phase['comparison_dumps'][0]),
                second_dump=record(phase['comparison_dumps'][1])))
    for key, rows in groups.items():
        require(len(rows) == 4 and {(row['case'], row['capture']) for row in rows} ==
                {(case, capture) for case in ('concern', 'clean') for capture in ('assistant_header', 'shared_prefix')},
                'comparison does not cover fixed pair/boundaries: ' + key)
    aggregate = {}
    for key, rows in groups.items():
        aggregate[key] = dict(capture_count=4, logit_pairs_compared=4 * 151936,
            maximum_absolute_difference=max(row['metrics']['max_abs'] for row in rows),
            maximum_relative_l2=max(row['metrics']['relative_l2'] for row in rows),
            all_argmax_agree=all(row['metrics']['argmax_agree'] for row in rows),
            all_decision_margin_signs_agree=all(row['decision_margin_sign_agree'] for row in rows),
            all_float32_values_bit_identical=all(row['metrics']['different_float32_values'] == 0 for row in rows))
    q8_path = HERE.parent / 'q8-summary.json'
    require(record(q8_path) == plan['screening_evidence'], 'prior original-Q8 summary changed')
    q8 = json.loads(q8_path.read_text())
    aligned_l2 = aggregate['aligned-engine']['maximum_relative_l2']
    aligned_abs = aggregate['aligned-engine']['maximum_absolute_difference']
    result = dict(schema_version=1, status='completed', original_scientific_protocol=plan['scientific_protocol'],
        execution_plan=record(plan_path), controller=plan['controller'], authorization=record(HERE / 'launch-authorization.json'),
        receipt=record(receipt_path), summary_source=record(__file__), original_q8_summary=record(q8_path),
        controller_streams={name:record(HERE / ('controller.' + name)) for name in ('stdout', 'stderr')},
        conversion=dict(original_model=plan['original_model'], exact_f32_model=receipt['converted_model'],
            validation_receipt=validation_binding, independently_checked_tensors=291,
            independently_checked_float32_values=630167424, every_tensor_bitwise_exact=True, all_finite=True,
            metadata_keys_checked=26, metadata_changes=validation['metadata_changes'],
            semantic_metadata_exact=True, exact_file_extent=2526617472),
        comparison_definitions={'native-packing': {'first':'notorch original Q8_0, NT_NO_I8=1',
            'second':'notorch exact expanded F32, NT_NO_I8=1', 'question':'Does native packed-weight arithmetic explain the difference?'},
            'aligned-engine': {'first':'notorch exact expanded F32, NT_NO_I8=1',
            'second':'llama.cpp same exact expanded F32', 'question':'How close are independent forwards with identical verified F32 tensor values?'}},
        aggregates=aggregate, captures=groups,
        original_q8_to_aligned_engine_comparison=dict(
            original_q8_maximum_absolute_difference=q8['max_absolute_difference'],
            original_q8_maximum_relative_l2=q8['max_relative_l2'],
            ratio_of_max_absolute_differences=q8['max_absolute_difference'] / aligned_abs if aligned_abs else None,
            ratio_of_max_relative_l2=q8['max_relative_l2'] / aligned_l2 if aligned_l2 else None,
            note='Ratios compare the two maxima across this fixed four-capture set; not a universal bound or per-token causal attribution.'),
        scope=dict(fixed_cases=['allocation-null-guard-deletion-concern', 'allocation-null-guard-deletion-clean'],
            captured_prefix_lengths=[444,447], vocabulary=151936, new_model_forward_processes=4,
            numerical_comparison_processes=4, changed_selection_inputs=False),
        sources_and_models_unchanged=True,
        resource_measurements=[{key:item.get(key) for key in ('name','kind','exit_code','elapsed_seconds',
            'peak_rss_kib','user_seconds','system_seconds')} for item in receipt['phases']],
        interpretation='These measurements isolate packed-weight/native arithmetic and then compare independent F32 forwards after exact conversion proof. They cover only the two frozen prompts/two boundaries in this original base model. No arbitrary aggregate tolerance proves a defect or full-runtime correctness; ranks/margins and the complete raw vectors are retained. Timings are resource observations during concurrent training, not a performance benchmark.')
    with (HERE / 'summary.json').open('x') as stream:
        stream.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(summary=record(HERE / 'summary.json'), aggregates=aggregate,
                          original_q8_to_aligned=result['original_q8_to_aligned_engine_comparison']), indent=2))


if __name__ == '__main__':
    main()
