"""Check exact replay of unchanged prompts against the archived comparator run."""
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(value).hexdigest()


def file_hash(path):
    return digest(Path(path).read_bytes())


def read(path):
    return json.loads(Path(path).read_text())


def readl(path):
    text = Path(path).read_text()
    assert text.endswith('\n'), f'incomplete JSONL: {path}'
    return [json.loads(line) for line in text.splitlines()]


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf8')


def validate_record(row, kind, model_sha):
    assert row['kind'] == kind and row['mode'] == 'natural'
    assert row['model_sha256'] == model_sha and row['returncode'] == 0
    assert row['supplied_prefix'] == '' and row['supplied_prefix_ids'] == []
    assert row['continuation'] == row['assembled_response']
    assert digest(row['prompt'].encode('utf8')) == row['prompt_sha256'] == row['supplied_prompt_sha256']
    assert row['decoding'] == dict(temperature=0, continuation_tokens=192,
                                   context=2048 if kind == 'train' else 8192, threads=2, NT_NO_I8='1')
    trace = row['trace']
    assert trace['schema_version'] == 1
    assert trace['prompt_token_ids'] == row['original_prompt_ids']
    assert all(type(token) is int and token >= 0 for token in trace['prompt_token_ids'])
    assert 0 < len(trace['generated_token_ids']) <= 192
    assert all(type(token) is int and token >= 0 for token in trace['generated_token_ids'])
    assert trace['generated_token_ids'][0] == row['actual_first_token_id']
    assert trace['requested_limit'] == 192
    assert trace['stop_reason'] == row['stop_reason'] and row['stop_reason'] in ('eos', 'token-limit')
    assert len(trace['generated_token_ids']) == trace['emitted_tokens'] + (row['stop_reason'] == 'eos')
    if row['stop_reason'] == 'token-limit':
        assert trace['emitted_tokens'] == 192
    # Native trace serialization is compact JSON in emitted field order plus LF.
    assert digest(compact(trace) + b'\n') == row['trace_sha256']


def compare_cohort(old_rows, new_rows, kind, model_sha):
    assert len({r['name'] for r in old_rows}) == len(old_rows)
    assert len({r['name'] for r in new_rows}) == len(new_rows)
    for row in old_rows + new_rows:
        validate_record(row, kind, model_sha)
    old_by_prompt = {row['prompt_sha256']: row for row in old_rows}
    assert len(old_by_prompt) == len(old_rows), 'archived prompts must be unique'
    matched, unmatched = [], []
    fields = {
        'assembled_response': lambda r: r['assembled_response'],
        'native_prompt_ids': lambda r: r['trace']['prompt_token_ids'],
        'sampled_ids_including_eos': lambda r: r['trace']['generated_token_ids'],
        'stop_reason': lambda r: r['trace']['stop_reason'],
        'emitted_tokens': lambda r: r['trace']['emitted_tokens'],
        'trace_requested_limit': lambda r: r['trace']['requested_limit'],
    }
    for new in new_rows:
        old = old_by_prompt.get(new['prompt_sha256'])
        if old is None:
            unmatched.append(dict(name=new['name'], prompt_sha256=new['prompt_sha256']))
            continue
        assert old['prompt'].encode('utf8') == new['prompt'].encode('utf8'), 'prompt SHA collision'
        equal = {name: getter(old) == getter(new) for name, getter in fields.items()}
        matched.append(dict(old_name=old['name'], new_name=new['name'], prompt_sha256=new['prompt_sha256'],
                            exact=all(equal.values()), equal=equal,
                            gold_response_equal=old['expected_response'] == new['expected_response'],
                            old_response_sha256=digest(old['assembled_response'].encode('utf8')),
                            new_response_sha256=digest(new['assembled_response'].encode('utf8')),
                            old_trace_sha256=old['trace_sha256'], new_trace_sha256=new['trace_sha256'],
                            old_runner_sha256=old['runner_sha256'], new_runner_sha256=new['runner_sha256'],
                            old_infer_source_sha256=old['infer_source_sha256'], new_infer_source_sha256=new['infer_source_sha256'],
                            mismatches={name: dict(old=getter(old), new=getter(new)) for name, getter in fields.items() if not equal[name]}))
    expected = 26 if kind == 'train' else 12
    assert len(matched) == expected, (kind, len(matched), expected)
    return dict(old_rows=len(old_rows), new_rows=len(new_rows), prompt_matched_rows=len(matched),
                exact_replays=sum(row['exact'] for row in matched),
                all_prompt_matches_replayed_exactly=all(row['exact'] for row in matched),
                field_exact_counts={name: sum(row['equal'][name] for row in matched) for name in fields},
                gold_changed_prompt_matches=[row['new_name'] for row in matched if not row['gold_response_equal']],
                matched_rows=matched, new_unmatched_prompts=unmatched)


def main():
    stem = 'models/counterbalanced-review'
    plan_path = Path(stem + '-plan.json')
    plan = read(plan_path)
    model_sha = plan['comparator']['model_sha256']
    complete_path = Path(stem + '-control-evaluation-model-check.json')
    complete = read(complete_path)
    assert complete['unchanged'] is True and complete['sha256'] == model_sha
    cohorts, sources = {}, dict(plan=dict(path=str(plan_path), sha256=file_hash(plan_path)),
                                completed_control=dict(path=str(complete_path), sha256=file_hash(complete_path)))
    for kind, new_count in (('train', 52), ('diagnostics', 12)):
        old_binding = plan['comparator']['previous_generations'][kind]
        old_path = Path(old_binding['path'])
        assert file_hash(old_path) == old_binding['sha256']
        new_path = Path(f'{stem}-control-{kind}-natural.jsonl')
        old_rows, new_rows = readl(old_path), readl(new_path)
        assert len(old_rows) == (40 if kind == 'train' else 12)
        assert len(new_rows) == new_count
        for row in new_rows:
            assert row['plan_sha256'] == sources['plan']['sha256']
            assert row['runner_sha256'] == plan['frozen_evaluation']['runner']['sha256']
            assert row['infer_source_sha256'] == plan['frozen_evaluation']['infer']['sha256']
            assert row['source_sha256'] == plan['frozen_evaluation']['corpus' if kind == 'train' else kind]['sha256']
        cohorts[kind] = compare_cohort(old_rows, new_rows, kind, model_sha)
        sources[kind] = dict(old=old_binding, new=dict(path=str(new_path), sha256=file_hash(new_path)))
    result = dict(schema_version=1, helper_sha256=file_hash(__file__), sources=sources, model_sha256=model_sha,
                  method='Compare complete prompt bytes against archived natural generations using the same selected model and decoding. Require exact complete response text, native prompt IDs, sampled IDs including EOS, stop reason and emitted count. Record any mismatch without altering either input.',
                  cohorts=cohorts, prompt_matches=sum(c['prompt_matched_rows'] for c in cohorts.values()),
                  exact_replays=sum(c['exact_replays'] for c in cohorts.values()),
                  all_matches_replayed_exactly=all(c['all_prompt_matches_replayed_exactly'] for c in cohorts.values()),
                  prompt_matching_note='The Python concern has the same inference prompt and revised gold wording. The two sequence-width prompts changed; new quartet prompts also changed. Prompt identity, not row identity or gold text, governs this replay comparison.')
    output = Path(stem + '-control-replay.json')
    with output.open('x') as target:
        json.dump(result, target, indent=2)
        target.write('\n')
    print(json.dumps(dict(output=str(output), prompt_matches=result['prompt_matches'], exact_replays=result['exact_replays'],
                          all_matches_replayed_exactly=result['all_matches_replayed_exactly'])))
    raise SystemExit(0 if result['all_matches_replayed_exactly'] else 1)


if __name__ == '__main__':
    main()
