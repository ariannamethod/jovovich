"""Independent, read-only source/input binding audit; never executes a model."""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path('/workspace/scratch/ec5ba60588d8')
HERE = ROOT / 'matched-external-parity'
REPO = ROOT / 'jovovich'

def require(value, message):
    if not value:
        raise ValueError(message)

def binding(path):
    path = Path(path)
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            size += len(chunk)
            digest.update(chunk)
    return dict(path=str(path), bytes=size, sha256=digest.hexdigest())

def records(value):
    if isinstance(value, dict):
        if {'path', 'bytes', 'sha256'} <= value.keys():
            yield value
        for child in value.values():
            yield from records(child)
    elif isinstance(value, list):
        for child in value:
            yield from records(child)

def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], text=True).strip()

def main():
    protocol = json.loads((HERE / 'protocol.json').read_text())
    fixed = json.loads((HERE / 'fixed-inputs.json').read_text())
    require(protocol['status'] == 'prepared_no_model_forwards' and protocol['execution_authorized'] is False,
            'preparation authority/status changed')
    require(protocol['model_forward_calls'] == fixed['model_forward_calls'] == 0, 'forward claim changed')
    checked = {}
    for record in [*records(protocol), *records(fixed)]:
        path = record['path']
        if path not in checked:
            checked[path] = binding(path)
        require(checked[path] == record, f'binding mismatch: {path}')
    require(git(HERE / 'llama.cpp', 'rev-parse', 'HEAD') == protocol['reference_commit'] ==
            '680a036285273a3ff56032ec5d7f3352609eba4f', 'reference pin changed')
    require(git(HERE / 'llama.cpp', 'status', '--porcelain') == '', 'reference checkout dirty')
    require(git(REPO / 'deps/notorch', 'rev-parse', 'HEAD') == protocol['notorch_pin'] ==
            '7e246e13f9dbbb7e61312b7341fb94ce492bff71', 'native pin changed')
    corpus = [json.loads(line) for line in Path(fixed['source']['path']).read_text().splitlines()]
    reviews = [row for row in corpus if row['kind'] == 'review']
    traces = [json.loads(line) for line in Path(fixed['native_trace']['path']).read_text().splitlines()]
    preflight_path = REPO / 'training/results/2026-10-01-matched-protections/v5-native-v2/phase-1.stdout'
    preflight = [json.loads(line) for line in preflight_path.read_text().splitlines()]
    require(len(reviews) == len(traces) == 52, 'trace coverage differs')
    cases = []
    require(protocol['cases'] == fixed['cases'] and len(protocol['cases']) == 2, 'case bindings differ')
    for case, expected_row, full_row, label, target, alternative in zip(
            protocol['cases'], [20, 21], [38, 39], ['concern', 'clean'], [66582, 788], [788, 66582]):
        row = reviews[expected_row]
        trace = traces[expected_row]
        native = preflight[full_row]
        ids = [int(x) for x in Path(case['ids']['path']).read_text().splitlines()]
        require(row['id'] == case['id'] == 'allocation-null-guard-deletion-' + label, 'case changed')
        require(case['review_row'] == expected_row and corpus[full_row] == row, 'row index changed')
        prompt = ''.join('<|im_start|>' + m['role'] + '\n' + m['content'] + '<|im_end|>\n'
                         for m in row['messages'][:2]) + '<|im_start|>assistant\n'
        require(Path(case['prompt']['path']).read_bytes() == prompt.encode(), 'ChatML bytes differ')
        require(ids == trace['input_ids'] == native['token_ids'][:447], 'exact token sequence differs')
        require(len(ids) == 447 and ids[-3:] == [4913, 3903, 819], 'prefix changed')
        require(trace['row'] == expected_row and trace['tokenize_only'] is True and
                trace['prompt_tokens'] == native['prompt_tokens'] == 444 and
                trace['capture_position'] == 446 and native['capture_start'] == 443,
                'boundary provenance changed')
        require(native['chatml_prompt_equal'] and native['chatml_full_equal'] and
                native['decision_position'] == 3 and native['decision_target_id'] == target and
                native['decision_alternative_id'] == alternative and native['token_ids'][447] == target,
                'decision token provenance changed')
        cases.append(dict(id=case['id'], review_row=expected_row, full_sft_row=full_row,
                          exact_chatml_and_447_archived_ids=True, capture_positions=[443, 446],
                          next_token_after_prefix=target))
    require(protocol['format']['expected_bytes_per_dump'] == 24 + 447*4 + 2*(4 + 151936*4),
            'dump byte extent mismatch')
    result = dict(
        status='prepared_source_and_binding_audit_passed',
        protocol=binding(HERE / 'protocol.json'), audit_source=binding(__file__),
        model_forwards=0, builds=0, test_executions=0, execution_authorized_by_audit=False,
        unique_bindings_verified=len(checked), bindings=list(checked.values()),
        additional_native_preflight=binding(preflight_path), cases=cases,
        source_review=dict(
            capture_indexing='Both engines capture logits after absolute positions 443 and 446; native head_rows=1 selects the final row and llama_get_logits_ith(-1) selects the only flagged final output row.',
            complete_vector='All 151936 logits per capture are checked finite before writing and again while comparing; headers, token IDs, row lengths and final byte extent are checked.',
            comparator='Double accumulators cover every vocabulary ID. Argmax, top margins, top10, relative L2, RMSE, max/mean absolute difference and decision IDs 66582/788 are reported. No correctness classifier is embedded.',
            q8_arithmetic='Pinned ggml CPU traits use quantize_row_q8_0 and ggml_vec_dot_q8_0_q8_0, whereas NT_NO_I8=1 retains float activations. Original Q8 differences therefore do not isolate a forward defect.',
            failure_preservation='Exclusive binary dump creation and fail-fast finite/I/O checks preserve partial dumps. Execution must retain nonzero exit status with partial metric/log artifacts rather than accepting partial stdout.',
            isolation='Only the original e1a777 base and this fixed pair are in scope. No v5 selection inputs, generation prompts, model scores or rubric are altered.'),
        interpretation=dict(
            screening='Prespecified thresholds are acceptable for deciding whether to request F32 alignment, not as numerical proof that either engine is correct or defective. A non-trigger result only bounds disagreement at these four captures.',
            signs='Use a three-way sign convention including exact zero; preserve both unrounded margins. A near-tie flip remains a screening trigger, not a model correctness failure.',
            hard_failures='Nonfinite logits, mismatched token/shape/capture data, incomplete dumps or nonzero child exits invalidate that comparison separately from finite numerical disagreement.',
            f32_gate='Separate authorization is required. Audit exact dequantized values of every tensor and metadata/tie semantics first; then compare native Q8 vs native F32 and native F32 vs reference F32 separately.',
            f32_limits='Aligned F32 differences still permit floating-point operation-order/implementation effects. Their size/location may motivate localization; an arbitrary aggregate tolerance alone cannot assign blame.'),
        execution_requirements=[
            'Before and after execution, verify model, sources, binaries and fixed inputs against this frozen protocol.',
            'Explicitly remove inherited NT_* and apply fixed single-thread environment; no alternate prompts/models or sampling.',
            'Bind each dump embedded input sequence to its particular fixed case, in addition to the comparator engine-to-engine equality check.',
            'Require successful process exits and exact complete four-dump coverage before interpreting aggregate measurements.',
            'Preserve argv, resources, stdout/stderr, partial outputs and any failed attempt; do not silently retry or authorize F32.'])
    output = ROOT / 'matched-training-audit/external-forward-preparation-independent-audit.json'
    with output.open('x') as stream:
        stream.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(status=result['status'], unique_bindings_verified=len(checked),
                          audit=binding(output), model_forwards=0)))

if __name__ == '__main__':
    main()
