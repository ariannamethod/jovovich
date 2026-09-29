#!/usr/bin/env python3
"""Summarize native per-row accuracy and select a saved training checkpoint."""
import argparse
import json
import math
from pathlib import Path


def summarize(data, metric):
    scores = metric['teacher_forced_rows']
    if len(scores) != len(data) or {s['row'] for s in scores} != set(range(len(data))):
        raise ValueError('native scores must cover every dataset row exactly once')
    groups, pairs, decisions = {}, {}, {}
    for score in scores:
        row = data[score['row']]
        kind = row['kind']
        if kind == 'review':
            findings = json.loads(row['messages'][2]['content'])['findings']
            kind = 'concern' if findings else 'clean'
            pair = pairs.setdefault(row['pair'], {})
            if kind in pair:
                raise ValueError('review pair must contain one concern and one clean row')
            pair[kind] = score['correct'] == score['tokens']
        n, correct = score['tokens'], score['correct']
        if not isinstance(n, int) or not isinstance(correct, int) or not 0 <= correct <= n or n == 0:
            raise ValueError('invalid native token counts')
        group = groups.setdefault(kind, dict(examples=0, exact_examples=0, tokens=0,
                                             correct_tokens=0, example_mean_token_accuracy=0.0))
        group['examples'] += 1
        group['exact_examples'] += correct == n
        group['tokens'] += n
        group['correct_tokens'] += correct
        group['example_mean_token_accuracy'] += correct / n
        decision_fields = {'decision_position', 'decision_correct', 'decision_margin',
                           'decision_predicted_id', 'decision_target_id', 'decision_alternative_id'}
        if decision_fields.intersection(score):
            if not {'decision_position', 'decision_correct', 'decision_margin'} <= score.keys():
                raise ValueError('incomplete decision-token metrics')
            if kind not in ('concern', 'clean'):
                raise ValueError('decision metrics require a review row')
            position, hit, margin = (score['decision_position'], score['decision_correct'],
                                     score['decision_margin'])
            if (type(position) is not int or not 0 <= position < n - 1 or
                    not isinstance(hit, bool) or type(margin) not in (int, float) or not math.isfinite(margin)):
                raise ValueError('invalid decision-token metrics')
            if (hit and (correct == 0 or margin < 0)) or (not hit and correct == n):
                raise ValueError('decision correctness disagrees with token counts or margin')
            id_fields = {'decision_predicted_id', 'decision_target_id', 'decision_alternative_id'}
            for field in id_fields.intersection(score):
                if type(score[field]) is not int or score[field] < 0:
                    raise ValueError('invalid decision token ID')
            if {'decision_target_id', 'decision_alternative_id'}.intersection(score):
                if not id_fields <= score.keys():
                    raise ValueError('incomplete decision token IDs')
                if (score['decision_target_id'] == score['decision_alternative_id'] or
                        hit != (score['decision_predicted_id'] == score['decision_target_id'])):
                    raise ValueError('decision correctness disagrees with token IDs')
            branch = decisions.setdefault(row['pair'], {})
            branch[kind] = hit
            group.setdefault('decision_examples', 0)
            group.setdefault('decision_correct', 0)
            group.setdefault('decision_positive_margin', 0)
            group.setdefault('decision_mean_margin', 0.0)
            group['decision_examples'] += 1
            group['decision_correct'] += hit
            group['decision_positive_margin'] += margin > 0
            group['decision_mean_margin'] += margin
    for group in groups.values():
        group['example_mean_token_accuracy'] /= group['examples']
        if group.get('decision_examples'):
            group['decision_mean_margin'] /= group['decision_examples']
    if any(set(pair) != {'concern', 'clean'} for pair in pairs.values()):
        raise ValueError('incomplete review pair')
    if sum(g['correct_tokens'] for g in groups.values()) != metric['teacher_forced_correct_tokens']:
        raise ValueError('per-row correct tokens disagree with aggregate')
    if sum(g['exact_examples'] for g in groups.values()) != metric['teacher_forced_exact_examples']:
        raise ValueError('per-row exact examples disagree with aggregate')
    result = dict(epoch=metric.get('epoch', 0), mean_token_ce=metric['mean_token_ce'], groups=groups,
                  review_pairs=len(pairs), review_pairs_exact=sum(all(p.values()) for p in pairs.values()))
    if decisions:
        if any(set(pair) != {'concern', 'clean'} for pair in decisions.values()):
            raise ValueError('incomplete decision-token pair')
        result.update(review_decision_pairs=len(decisions),
                      review_decision_pairs_exact=sum(all(p.values()) for p in decisions.values()))
    if 'decision_pairs' in metric:
        declared = metric['decision_pairs']
        if type(declared) is not int or declared < 0 or declared != len(decisions):
            raise ValueError('decision pair count disagrees with per-row metrics')
    return result


def selection_key(summary):
    groups = summary['groups']
    review = [groups[k] for k in ('concern', 'clean')]
    macro = sum(g['example_mean_token_accuracy'] * g['examples'] for g in review) / sum(g['examples'] for g in review)
    return summary['review_pairs_exact'], macro, -summary['epoch']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('metrics', nargs='+', type=Path)
    p.add_argument('--sft', type=Path, default=Path(__file__).with_name('sft_review_v2.jsonl'))
    p.add_argument('--checkpoint-every', type=int, default=1)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.checkpoint_every < 1:
        p.error('--checkpoint-every must be positive')
    data = [json.loads(s) for s in args.sft.read_text().splitlines() if s.strip()]
    output = []
    for path in args.metrics:
        metrics = [json.loads(s) for s in path.read_text().splitlines() if s.strip()]
        summaries = [summarize(data, m) for m in metrics]
        candidates = [s for s in summaries if s['epoch'] > 0 and
                      (s['epoch'] % args.checkpoint_every == 0 or s is summaries[-1])]
        if not candidates:
            raise ValueError('no saved epoch available for checkpoint selection')
        output.append(dict(metrics=str(path), objective=metrics[0]['objective'], epochs=summaries,
                           selected_epoch=max(candidates, key=selection_key)['epoch']))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as target:
        json.dump(dict(selection='maximize exact review pairs, then review macro token accuracy, then prefer earlier epoch',
                       runs=output), target, indent=2)
        target.write('\n')


if __name__ == '__main__':
    main()
