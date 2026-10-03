#!/usr/bin/env python3
"""Fresh independent v6 checker controls; never reconstructs absent old logs.

Run from any directory: python acceptance-audit.py [--repo ROOT] [--out JSON].
Only temporary corpus copies and the requested report are written. No model runs.
"""
import argparse
import copy
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--out', type=Path, default=Path(__file__).with_suffix('.json'))
    args = parser.parse_args()
    repo = args.repo.resolve()
    source = repo / 'training/acceptance/v6_check.mjs'
    paths = {
        'v5': 'training/sft_review_v5.jsonl',
        'before': 'training/sft_review_v6_before.jsonl',
        'after': 'training/sft_review_v6_after.jsonl',
        'reasons': 'training/explanations/reasons.json',
    }
    original = {key: (repo / value).read_bytes() for key, value in paths.items()}
    original_rows = {key: [json.loads(line) for line in original[key].splitlines()]
                     for key in ('v5', 'before', 'after')}
    review = next(i for i, row in enumerate(original_rows['v5']) if row['kind'] == 'review')
    nonreview = next(i for i, row in enumerate(original_rows['v5']) if row['kind'] != 'review')
    mirrored_id = 'model-parent-provenance-introduced'
    mirrored = next(i for i, row in enumerate(original_rows['v5']) if row['id'] == mirrored_id)

    def message(row, role):
        return next(item for item in row['messages'] if item['role'] == role)

    def edit_row(data, arm, index, edit):
        lines = data[arm].splitlines(keepends=True)
        row = json.loads(lines[index])
        edit(row)
        lines[index] = (json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
        data[arm] = b''.join(lines)

    def edit_message(data, arm, index, role, edit):
        def update(row):
            msg = message(row, role)
            msg['content'] = edit(msg['content'])
        edit_row(data, arm, index, update)

    def edit_analysis(data, index, edit):
        row_id = original_rows['v5'][index]['id']
        reasons = json.loads(data['reasons'])
        row = next(row for row in reasons['rows'] if row['id'] == row_id)
        row['analysis'] = edit(row['analysis'])
        data['reasons'] = (json.dumps(reasons, ensure_ascii=False, indent=2) + '\n').encode()
        for arm in ('before', 'after'):
            def update(text):
                answer = json.loads(text)
                answer['analysis'] = row['analysis']
                return json.dumps(answer, ensure_ascii=False, separators=(',', ':'))
            edit_message(data, arm, index, 'assistant', update)

    def bad_findings(data):
        def update(text):
            answer = json.loads(text)
            answer['findings'] = []
            return json.dumps(answer, separators=(',', ':'))
        edit_message(data, 'before', review, 'assistant', update)

    def wrong_order(data):
        def update(text):
            answer = json.loads(text)
            return json.dumps({'findings': answer['findings'], 'analysis': answer['analysis']},
                              separators=(',', ':'))
        edit_message(data, 'before', review, 'assistant', update)

    def h9_mutation(data):
        edit_analysis(data, review, lambda text: text + ' The patch is large.')

    h9_key = original_rows['v5'][review]['id'] + ':8:patch is large'
    cases = [
        ('baseline', None, 'PASS', lambda data: None, None, 0),
        ('hash-only-whitespace', 'H1', 'FAIL',
         lambda data: data.__setitem__('reasons', data['reasons'] + b'\n'), None, 1),
        ('row-id', 'H2', 'FAIL',
         lambda data: edit_row(data, 'before', review, lambda row: row.__setitem__('id', row['id'] + '-mutated')), None, 1),
        ('nonreview-byte-change', 'H3', 'FAIL',
         lambda data: edit_message(data, 'before', nonreview, 'user', lambda text: text + ' changed'), None, 1),
        ('system-byte-change', 'H4_suffix', 'FAIL',
         lambda data: edit_message(data, 'before', review, 'system', lambda text: text + ' changed'), None, 1),
        ('nonuniform-user-suffix', 'H4_suffix', 'FAIL',
         lambda data: edit_message(data, 'before', review, 'user', lambda text: text + ' changed'), None, 1),
        ('concern-to-clean', 'H5', 'FAIL', bad_findings, None, 1),
        ('noncompact-findings', 'H5', 'FAIL',
         lambda data: edit_message(data, 'before', review, 'assistant', lambda text: text.replace('"findings":', '"findings": ', 1)), None, 1),
        ('wrong-answer-key-order', 'H6', 'FAIL', wrong_order, None, 1),
        ('analysis-disagrees-with-reasons', 'H6', 'FAIL',
         lambda data: edit_message(data, 'before', review, 'assistant', lambda text: text.replace('The nearest', 'The changed', 1)), None, 1),
        ('one-sentence-analysis', 'H7', 'FAIL',
         lambda data: edit_analysis(data, review, lambda text: 'The rule forbids the change at [1].'), None, 1),
        ('nonexistent-citation', 'H8v2', 'FAIL',
         lambda data: edit_analysis(data, review, lambda text: text.replace('[1]', '[999]')), None, 1),
        ('mirrored-removed-side-citation', 'H8v2', 'FAIL',
         lambda data: edit_analysis(data, mirrored, lambda text: text.replace('[2]', '[1]')), None, 1),
        ('unequal-pair-sentence-count', 'H8v2', 'FAIL',
         lambda data: edit_analysis(data, review, lambda text: text + ' This applies to the changed code.'), None, 1),
        ('forbidden-shape-unadjudicated', 'H9', 'FAIL', h9_mutation, None, 1),
        ('forbidden-shape-content-adjudication', 'H9', 'PASS', h9_mutation,
         {h9_key: {'verdict': 'content', 'reason': 'Synthetic branch control, not a substantive adjudication.'}}, 1),
        ('forbidden-shape-shape-adjudication', 'H9', 'FAIL', h9_mutation,
         {h9_key: {'verdict': 'shape', 'reason': 'Synthetic branch control.'}}, 1),
        ('stale-adjudication', 'H9', 'FAIL', lambda data: None,
         {'nonexistent:8:patch is large': {'verdict': 'content'}}, 1),
    ]
    results = []
    with tempfile.TemporaryDirectory(prefix='jovovich-v6-audit-') as temp:
        root = Path(temp)
        for name, target, status, mutate, adjudication, expected_rc in cases:
            data = copy.copy(original)
            mutate(data)
            changed_inputs = [key for key in original if data[key] != original[key]]
            if target and name != 'stale-adjudication' and not changed_inputs:
                raise AssertionError(f'{name}: mutation changed no input bytes')
            directory = root / name
            directory.mkdir()
            command = ['node', str(source), '--out', str(directory / 'checker.json')]
            for key, value in data.items():
                path = directory / key
                path.write_bytes(value)
                command.extend(['--' + key, str(path)])
            if adjudication is not None:
                path = directory / 'adjudications.json'
                path.write_text(json.dumps(adjudication) + '\n')
                command.extend(['--adjudications', str(path)])
            process = subprocess.run(command, cwd=repo, capture_output=True, text=True, timeout=30)
            report = json.loads((directory / 'checker.json').read_text())
            checks = {check['id']: check for check in report['checks']}
            target_ok = checks[target]['status'] == status if target else all(
                check['status'] == 'PASS' for check in checks.values() if check['hard'])
            passed = process.returncode == expected_rc and target_ok
            results.append({
                'case': name, 'target_check': target, 'expected_target_status': status,
                'expected_exit_code': expected_rc, 'exit_code': process.returncode,
                'changed_inputs': changed_inputs,
                'input_sha256': {key: sha(value) for key, value in data.items()},
                'adjudication': adjudication,
                'statuses': {key: value['status'] for key, value in checks.items()},
                'target_failure_count': checks[target]['failure_count'] if target else 0,
                'target_failures': checks[target]['failures'] if target else [],
                'stdout': process.stdout, 'stderr': process.stderr, 'passed': passed,
            })
    old_names = ['red-run-v1.log', 'red-run-v2.log']
    tree = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', 'HEAD'], cwd=repo, text=True).splitlines()
    history = subprocess.check_output(['git', 'log', '--all', '--format=%H %s', '--', '**/*red-run*'], cwd=repo, text=True)
    missing = {name: {'tracked_current_matches': [p for p in tree if Path(p).name == name],
                      'expected_path_exists': (repo / 'training/results/2026-10-03-v6-acceptance' / name).exists()}
               for name in old_names}
    output = {
        'schema_version': 1,
        'performed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'repo_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip(),
        'checker': {'path': str(source.relative_to(repo)), 'sha256': sha(source.read_bytes())},
        'input_sha256': {key: sha(value) for key, value in original.items()},
        'historical_evidence': {'files': missing, 'matching_available_git_history': history,
            'conclusion': 'Referenced original red-run logs are absent. This audit is new evidence, not their reconstruction.'},
        'interpretation': [
            'Every semantic mutation must fail its named check; H1 hash rejection alone is insufficient.',
            'The content-adjudication case tests the H9 branch only; full exit remains 1 because inputs changed.',
            'Baseline retains declared soft H4_strict deviation and superseded soft H8 failure.',
            'No model, native probe, training, generation, or cloud resource operation was performed.',
        ],
        'cases': results, 'passed': sum(item['passed'] for item in results),
        'total': len(results), 'all_passed': all(item['passed'] for item in results),
    }
    args.out.write_text(json.dumps(output, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'report': str(args.out), 'passed': output['passed'], 'total': output['total'],
                      'failed_cases': [item['case'] for item in results if not item['passed']]}))
    return 0 if output['all_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
