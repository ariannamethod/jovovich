"""Extract a fixed pair and archived native IDs; no model math or model outputs."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent / 'jovovich'
CORPUS = REPO / 'training/sft_review_v5.jsonl'
TRACE = REPO / 'training/results/2026-10-01-matched-protections/v5-token-final/token-trace.jsonl'
EXPECTED_CORPUS = 'a677211e90576dea45ad4fa534fc97a3a6496944d63df99315ed934505936417'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def record(path):
    path = Path(path)
    data = path.read_bytes()
    return dict(path=str(path.resolve()), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def save(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, indent=2)+'\n')


def main():
    require(record(CORPUS)['sha256'] == EXPECTED_CORPUS, 'corpus changed')
    reviews = [row for row in map(json.loads, CORPUS.read_text().splitlines()) if row['kind'] == 'review']
    traces = list(map(json.loads, TRACE.read_text().splitlines()))
    require(len(reviews) == len(traces) == 52, 'native trace coverage changed')
    cases = []
    for index, label in [(20, 'concern'), (21, 'clean')]:
        row, trace = reviews[index], traces[index]
        require(row['id'] == 'allocation-null-guard-deletion-'+label, 'fixed case changed')
        require(row['pair'] == 'allocation-null-guard-deletion' and trace['row'] == index, 'pair/trace order mismatch')
        require(trace['prompt_tokens'] == 444 and trace['input_tokens'] == 447 and trace['capture_position'] == 446, 'native length mismatch')
        require(trace['prefix_ids'] == [4913,3903,819] and trace['input_ids'][-3:] == trace['prefix_ids'], 'native prefix mismatch')
        require(len(trace['input_ids']) == 447 and trace['tokenize_only'] is True, 'trace was not native tokenizer-only evidence')
        require([m['role'] for m in row['messages']] == ['system','user','assistant'], 'message roles changed')
        system,user = [m['content'] for m in row['messages'][:2]]
        prompt = f'<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n'
        prompt_path, ids_path = HERE/(label+'.prompt.txt'), HERE/(label+'.ids.txt')
        with prompt_path.open('x') as stream:
            stream.write(prompt)
        with ids_path.open('x') as stream:
            stream.write(''.join(str(token)+'\n' for token in trace['input_ids']))
        cases.append(dict(id=row['id'], pair=row['pair'], review_row=index, expected_concern=label=='concern',
            prompt=record(prompt_path), ids=record(ids_path), prompt_tokens=444, total_input_tokens=447,
            captured_prefix_lengths=[444,447], captured_positions_zero_based=[443,446],
            supplied_prefix='{"findings', supplied_prefix_ids=[4913,3903,819]))
    save(HERE/'fixed-inputs.json', dict(status='fixed_before_new_v5_generation', source=record(CORPUS),
        native_trace=record(TRACE), generator=record(__file__), cases=cases, model_forward_calls=0,
        selection='Preselected first allocation NULL-guard deletion quartet pair, fixed by case IDs before reading any new v5 output.'))
    print(json.dumps(dict(cases=2, captures=4, prompt_tokens_per_case=444, model_forward_calls=0)))


if __name__ == '__main__':
    main()
