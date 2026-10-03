#!/usr/bin/env python3
"""Score full free-generated explanation reviews, with literal artifact binding.

Each generation JSONL record contains case_id, corpus_sha256, raw_response,
raw_response_sha256 and finish_reason (eos, length, error). Error records also
contain a nonempty error string; null raw text has a null hash. Optional metadata
is retained as supplied provenance, separately from verified file hashes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


class NonstandardJSON(ValueError):
    pass


def unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise NonstandardJSON(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def invalid_constant(value):
    raise NonstandardJSON(f'nonstandard JSON constant: {value}')


def strict_json(text):
    return json.loads(text, object_pairs_hook=unique_object,
                      parse_constant=invalid_constant)


def read_jsonl(path):
    raw = path.read_bytes()
    records = []
    for line_number, line in enumerate(raw.splitlines(keepends=True), 1):
        require(bool(line.strip()), f'{path}:{line_number}: blank JSONL row')
        value = strict_json(line.decode('utf-8'))
        require(isinstance(value, dict), f'{path}:{line_number}: expected object')
        records.append((value, {'line': line_number, 'sha256': sha256(line)}))
    return records, {'path': str(path.resolve()), 'bytes': len(raw), 'sha256': sha256(raw)}


def changed_line_ids(user):
    marker = '\nChanged lines to review:\n'
    require(user.count(marker) == 1, 'corpus prompt requires one changed-line section')
    section = user.split(marker, 1)[1].split('\n\n', 1)[0]
    lines = section.splitlines()
    ids = []
    for line in lines:
        match = re.match(r'^\[([1-9][0-9]*)\] (?:ADDED|REMOVED) .+:\d+:', line)
        require(match is not None, 'invalid corpus changed-line entry')
        ids.append(int(match.group(1)))
    require(ids and len(set(ids)) == len(ids), 'corpus changed-line IDs must be unique')
    return set(ids)


def findings_schema(value, allowed_ids):
    require(isinstance(value, dict) and 'findings' in value and
            set(value) <= {'analysis', 'findings'},
            'review requires findings and only known top-level keys')
    findings = value['findings']
    require(isinstance(findings, list) and len(findings) <= 2,
            'findings must be an array of at most two findings')
    returned_ids = []
    for finding in findings:
        require(isinstance(finding, dict) and set(finding) == {'line_id', 'reason'},
                'finding must contain exactly line_id and reason')
        line_id = finding['line_id']
        # Match the host's canonical decimal string IDs and integral JSON
        # numbers. Python bool is an int subclass but is not a line number.
        if isinstance(line_id, str) and re.fullmatch(r'[1-9][0-9]*', line_id):
            line_id = int(line_id)
        if type(line_id) is float and line_id.is_integer():
            line_id = int(line_id)
        require(type(line_id) is int and line_id in allowed_ids,
                'finding requires an exact changed-line ID')
        reason = finding['reason']
        require(isinstance(reason, str) and bool(reason.strip()) and
                len(reason.encode('utf-16-le')) // 2 <= 1500,
                'finding reason must contain 1..1500 UTF-16 units of text')
        returned_ids.append(line_id)
    return returned_ids


def review_schema(value, allowed_ids):
    returned_ids = findings_schema(value, allowed_ids)
    require(set(value) == {'analysis', 'findings'},
            'review must contain exactly analysis and findings')
    require(isinstance(value['analysis'], str), 'analysis must be a string')
    return returned_ids


def corpus_cases(records, order):
    cases, pairs, seen = {}, {}, set()
    keys = ['analysis', 'findings'] if order == 'before' else ['findings', 'analysis']
    for row_index, (row, binding) in enumerate(records):
        case_id = row.get('id')
        require(isinstance(case_id, str) and bool(case_id) and case_id not in seen,
                'corpus IDs must be nonempty and unique')
        seen.add(case_id)
        require(row.get('kind') in ('review', 'voice', 'code'), 'unknown corpus kind')
        messages = row.get('messages')
        require(isinstance(messages, list) and len(messages) == 3 and
                all(isinstance(m, dict) and isinstance(m.get('content'), str)
                    for m in messages) and
                [m.get('role') for m in messages] == ['system', 'user', 'assistant'],
                'corpus requires system/user/assistant messages')
        if row['kind'] != 'review':
            continue
        pair = row.get('pair')
        require(isinstance(pair, str) and bool(pair), 'review requires a pair ID')
        allowed_ids = changed_line_ids(messages[1]['content'])
        answer = strict_json(messages[2]['content'])
        expected_ids = review_schema(answer, allowed_ids)
        require(list(answer) == keys, 'corpus answer key order disagrees with --order')
        require(bool(answer['analysis'].strip()), 'corpus analysis must be nonempty')
        expected_concern = bool(expected_ids)
        role = 'concern' if expected_concern else 'clean'
        pair_rows = pairs.setdefault(pair, {})
        require(role not in pair_rows, 'pair must contain one concern and one clean')
        pair_rows[role] = case_id
        prompt = (f"<|im_start|>system\n{messages[0]['content']}<|im_end|>\n"
                  f"<|im_start|>user\n{messages[1]['content']}<|im_end|>\n"
                  '<|im_start|>assistant\n')
        cases[case_id] = dict(row=row_index, pair=pair, allowed_ids=allowed_ids,
                              expected_ids=expected_ids, expected_concern=expected_concern,
                              prompt_sha256=sha256(prompt.encode('utf-8')),
                              corpus_record=binding)
    require(cases and all(set(p) == {'concern', 'clean'} for p in pairs.values()),
            'corpus requires complete concern/clean pairs')
    return cases, pairs


def holdout_cases(records, raw):
    # Use the same production renderer as collection. The collector strips gold
    # fields before rendering source context; no assistant answer is fabricated.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from collect_generation import review_cases
    rendered = review_cases(raw, split='holdout')
    require(len(rendered) == len(records), 'heldout renderer coverage mismatch')
    cases, pairs = {}, {}
    for row_index, ((row, binding), prompt) in enumerate(zip(records, rendered)):
        case_id, pair = row.get('id'), row.get('pair')
        require(isinstance(case_id, str) and case_id not in cases and
                isinstance(pair, str) and bool(pair), 'invalid heldout case/pair ID')
        require(prompt['case_id'] == case_id and prompt['raw_row_sha256'] == binding['sha256'],
                'heldout rendered case binding mismatch')
        allowed_ids = changed_line_ids(prompt['prompt'].decode('utf-8'))
        expected_ids = findings_schema(row.get('gold'), allowed_ids)
        expected_concern = row.get('expected_concern')
        require(type(expected_concern) is bool and expected_concern == bool(expected_ids),
                'heldout label disagrees with gold findings')
        candidate_ids = row.get('expected_line_ids')
        require(isinstance(candidate_ids, list) and
                all(type(i) is int and i in allowed_ids for i in candidate_ids) and
                len(set(candidate_ids)) == len(candidate_ids) and
                bool(candidate_ids) == expected_concern and set(expected_ids) <= set(candidate_ids),
                'invalid heldout reference line IDs')
        role = 'concern' if expected_concern else 'clean'
        members = pairs.setdefault(pair, {})
        require(role not in members, 'heldout pair has duplicate roles')
        members[role] = case_id
        cases[case_id] = dict(row=row_index, pair=pair, allowed_ids=allowed_ids,
                              expected_ids=expected_ids, expected_concern=expected_concern,
                              supplied_candidate_line_ids=candidate_ids,
                              expected_reason_concept=row.get('expected_reason_concept'),
                              prompt_sha256=prompt['prompt_sha256'], corpus_record=binding)
    require(cases and all(set(pair) == {'concern', 'clean'} for pair in pairs.values()),
            'heldout requires complete concern/clean pairs')
    return cases, pairs


def validate_metadata(metadata):
    allowed = {'model_path', 'model_sha256', 'prompt_sha256', 'prompt_token_ids',
               'generated_token_ids', 'requested_limit'}
    require(isinstance(metadata, dict) and set(metadata) <= allowed,
            'invalid generation metadata keys')
    for key, value in metadata.items():
        if key.endswith('_sha256'):
            require(isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value),
                    f'invalid metadata {key}')
        elif key.endswith('_token_ids'):
            require(isinstance(value, list) and all(type(i) is int and i >= 0 for i in value),
                    f'invalid metadata {key}')
        elif key == 'requested_limit':
            require(type(value) is int and value > 0, 'invalid requested_limit')
        else:
            require(isinstance(value, str) and bool(value), 'invalid model_path')


def validate_record(record, corpus_sha):
    required = {'case_id', 'corpus_sha256', 'raw_response',
                'raw_response_sha256', 'finish_reason'}
    require(required <= set(record) <= required | {'error', 'metadata'},
            'invalid generation record keys')
    require(isinstance(record['case_id'], str), 'case_id must be a string')
    require(record['corpus_sha256'] == corpus_sha, 'generation corpus hash mismatch')
    finish = record['finish_reason']
    require(finish in ('eos', 'length', 'error'), 'invalid finish_reason')
    if finish == 'error':
        require(isinstance(record.get('error'), str) and bool(record['error'].strip()),
                'error completion requires an error message')
    else:
        require(record.get('error') is None, 'successful completion has an error message')
    raw = record['raw_response']
    require(isinstance(raw, str) or (finish == 'error' and raw is None),
            'raw_response must be literal text (or null for an error)')
    expected = None if raw is None else sha256(raw.encode('utf-8'))
    require(record['raw_response_sha256'] == expected, 'raw response hash mismatch')
    if 'metadata' in record:
        validate_metadata(record['metadata'])


def score_files(corpus_path, generation_path, order, split='train'):
    require(order in ('before', 'after'), 'order must be before or after')
    require(split in ('train', 'holdout'), 'invalid corpus split')
    corpus, corpus_binding = read_jsonl(Path(corpus_path))
    generations, generation_binding = read_jsonl(Path(generation_path))
    if split == 'holdout':
        raw = Path(corpus_path).read_bytes()
        require(sha256(raw) == corpus_binding['sha256'], 'heldout source changed while loading')
        cases, pairs = holdout_cases(corpus, raw)
    else:
        cases, pairs = corpus_cases(corpus, order)
    records = {}
    for record, binding in generations:
        validate_record(record, corpus_binding['sha256'])
        case_id = record['case_id']
        require(case_id in cases, f'unknown/non-review generation case: {case_id}')
        require(case_id not in records, f'duplicate generation case: {case_id}')
        if 'prompt_sha256' in record.get('metadata', {}):
            require(record['metadata']['prompt_sha256'] == cases[case_id]['prompt_sha256'],
                    'generation prompt hash mismatch')
        records[case_id] = (record, binding)

    rows = []
    wanted_keys = ['analysis', 'findings'] if order == 'before' else ['findings', 'analysis']
    for case_id, case in cases.items():
        result = dict(case_id=case_id, row=case['row'], pair=case['pair'],
                      corpus_record=case['corpus_record'],
                      prompt_sha256=case['prompt_sha256'],
                      expected_concern=case['expected_concern'],
                      expected_line_ids=case['expected_ids'], status='missing',
                      generation_record=None, raw_response_sha256=None, finish_reason=None,
                      json_valid=False, schema_valid=False, findings_schema_valid=False, output_order=None,
                      order_adherent=False, empty_analysis=None, predicted_concern=None,
                      returned_line_ids=None, classification_correct=False,
                      exact_gold_line_ids=False, format_pass=False, strict_output_pass=False,
                      semantic_assessment=None, parse_error=None)
        if split == 'holdout':
            result.update(supplied_candidate_line_ids=case['supplied_candidate_line_ids'],
                          expected_reason_concept=case['expected_reason_concept'])
        if case_id not in records:
            rows.append(result)
            continue
        record, binding = records[case_id]
        result.update(generation_record=binding, raw_response_sha256=record['raw_response_sha256'],
                      finish_reason=record['finish_reason'], metadata=record.get('metadata'))
        if record['finish_reason'] == 'error':
            result.update(status='generation_error', error=record['error'])
            rows.append(result)
            continue
        try:
            value = strict_json(record['raw_response'])
        except (ValueError, RecursionError) as error:
            result.update(status='invalid_json', parse_error=str(error))
        else:
            result['json_valid'] = True
            if isinstance(value, dict):
                result['output_order'] = list(value)
                result['order_adherent'] = list(value) == wanted_keys
                if isinstance(value.get('analysis'), str):
                    result['empty_analysis'] = not bool(value['analysis'].strip())
            try:
                returned_ids = findings_schema(value, case['allowed_ids'])
            except (ValueError, UnicodeError) as error:
                result.update(status='invalid_schema', parse_error=str(error))
            else:
                result.update(findings_schema_valid=True, returned_line_ids=returned_ids,
                              predicted_concern=bool(returned_ids))
                if record['finish_reason'] == 'eos':
                    result['classification_correct'] = bool(returned_ids) == case['expected_concern']
                    result['exact_gold_line_ids'] = set(returned_ids) == set(case['expected_ids'])
                try:
                    review_schema(value, case['allowed_ids'])
                except (ValueError, UnicodeError) as error:
                    result.update(status='invalid_schema', parse_error=str(error))
                else:
                    result.update(schema_valid=True, status='scored')
                    if record['finish_reason'] == 'eos':
                        result['format_pass'] = result['order_adherent'] and not result['empty_analysis']
                        result['strict_output_pass'] = result['format_pass'] and result['exact_gold_line_ids']
        if record['finish_reason'] == 'length':
            result['status'] = 'truncated'
        rows.append(result)

    by_id = {r['case_id']: r for r in rows}
    pair_results = []
    for pair_id, members in pairs.items():
        member_rows = [by_id[members[role]] for role in ('concern', 'clean')]
        pair_results.append(dict(pair=pair_id, case_ids=[r['case_id'] for r in member_rows],
                                 both_present=all(r['status'] != 'missing' for r in member_rows),
                                 classification_correct=all(r['classification_correct'] for r in member_rows),
                                 exact_gold_line_ids=all(r['exact_gold_line_ids'] for r in member_rows),
                                 format_pass=all(r['format_pass'] for r in member_rows),
                                 strict_output_pass=all(r['strict_output_pass'] for r in member_rows)))
    count = lambda field: sum(r[field] is True for r in rows)
    summary = dict(expected_reviews=len(rows), expected_pairs=len(pairs),
                   received_reviews=len(records), missing_reviews=len(rows) - len(records),
                   json_valid=count('json_valid'), schema_valid=count('schema_valid'),
                   findings_schema_valid=count('findings_schema_valid'),
                   order_adherent=count('order_adherent'), empty_analysis=count('empty_analysis'),
                   eos_reviews=sum(r['finish_reason'] == 'eos' for r in rows),
                   truncated_reviews=sum(r['finish_reason'] == 'length' for r in rows),
                   generation_errors=sum(r['status'] == 'generation_error' for r in rows),
                   invalid_json=sum(r['finish_reason'] != 'error' and r['status'] != 'missing' and
                                    not r['json_valid'] for r in rows),
                   invalid_schema=sum(r['json_valid'] and not r['schema_valid'] for r in rows),
                   classification_correct=count('classification_correct'),
                   exact_gold_line_ids=count('exact_gold_line_ids'), format_pass=count('format_pass'),
                   strict_output_pass=count('strict_output_pass'),
                   complete_classification_pairs=sum(p['classification_correct'] for p in pair_results),
                   complete_exact_gold_line_pairs=sum(p['exact_gold_line_ids'] for p in pair_results),
                   complete_format_pairs=sum(p['format_pass'] for p in pair_results),
                   complete_strict_output_pairs=sum(p['strict_output_pass'] for p in pair_results))
    return dict(schema_version=1, status='complete' if len(records) == len(cases) else 'incomplete',
                measurement='free_generation_json_structure', expected_order=order, split=split,
                classification_basis='full_json_known_keys_valid_findings',
                exact_gold_line_ids_basis='exact_canonical_id_set',
                production_acceptance=None,
                corpus=corpus_binding, generations=generation_binding,
                scorer={'path': str(Path(__file__).resolve()),
                        'sha256': sha256(Path(__file__).read_bytes())},
                summary=summary, rows=rows, pairs=pair_results, semantic_assessment=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('generations', type=Path)
    parser.add_argument('--sft', type=Path, required=True)
    parser.add_argument('--order', choices=('before', 'after'), required=True)
    parser.add_argument('--split', choices=('train', 'holdout'), default='train')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = score_files(args.sft, args.generations, args.order, args.split)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
        return 0 if result['status'] == 'complete' else 2
    except (ValueError, OSError, RecursionError) as error:
        print(f'score_generation: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
