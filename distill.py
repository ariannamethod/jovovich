"""Distill complete, checked reviews from a pinned Qwen3.5 teacher."""
import argparse
import ast
import hashlib
import json
import re
from pathlib import Path
from fixture_quality import require_usable

INSTRUCTION = '''Write one complete advisory review for the supplied code and repository contract.
A verified reference review and computed observations are provided as supervision.
Explain WHY the implementation satisfies or breaks the contract, using the actual code.
Return one concise review, at most 180 words. Do not concatenate two reviews.
For a defective function, preserve this sentence from the reference verbatim:
The expression `...` breaks the required behavior: `assert ...` fails. Replacing it with `...` restores the supplied examples.
Add a short explanation of the operation and its consequence, without repeating that sentence.
For correct code, explain concretely why it meets the requirements.
End with exactly the reference's Verdict: CLEAN or Verdict: CONCERN line.
Do not invent additional requirements, defects, dependencies, or execution results.
Do not claim to have run code. Never mention the reference, gold answer, teacher,
training data or supervision: these are not part of the deployed reviewer's context.
Preserve Arianna Method ontology, identity and terminology. Review is advisory;
maintainers decide whether to merge. Return only the review, with no wrapper.'''


def validate_review(row, answer, stopped):
    if not stopped:
        return 'incomplete'
    if not answer or len(answer.split()) > 220:
        return 'length'
    if re.search(r'\breference\b|\bgold\b|\bteacher\b|\btraining (example|data)\b|\bsupervis', answer, re.I):
        return 'supervisor_leak'
    if '<think>' in answer or '</think>' in answer:
        return 'reasoning_markup'
    if re.findall(r'Verdict:\s*(CLEAN|CONCERN)', answer) != [row['expected']]:
        return 'verdict'
    if not answer.rstrip().endswith('Verdict: ' + row['expected']):
        return 'verdict_position'
    if row['expected'] == 'CONCERN':
        pattern = r'The expression `[^`]+` breaks the required behavior: `assert[^`]+` fails\. Replacing it with `[^`]+` restores the supplied examples\.'
        sentence = re.search(pattern, row['messages'][-1]['content'])
        if not sentence or answer.count(sentence.group()) != 1:
            return 'changed_verified_repair'
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model', default='Qwen/Qwen3.5-27B-FP8')
    p.add_argument('--revision', default='97f5941bf617e31c5e237364a8602ce3f03a551a')
    p.add_argument('--input', default='data/train.jsonl')
    p.add_argument('--output', default='data/train_distilled.jsonl')
    p.add_argument('--batch-size', type=int, default=16)
    args = p.parse_args()
    rows = [json.loads(line) for line in Path(args.input).read_text().splitlines() if line.strip()]
    require_usable(rows)
    from transformers import AutoTokenizer
    from vllm import LLM, SamplingParams
    held_out = set()
    for name in ('validation', 'test', 'acceptance'):
        for line in Path('data/' + name + '.jsonl').read_text().splitlines():
            r = json.loads(line)
            held_out.add(r.get('group', r['id']))
    if any(r['group'] in held_out for r in rows):
        raise ValueError('Held-out source group entered teacher input')
    output = Path(args.output)
    if output.exists():
        raise FileExistsError('Use a fresh output path; completed distillation is not overwritten')
    partial = output.with_suffix('.partial')
    metadata = output.with_suffix('.provenance.json')
    provenance = {'model': args.model, 'revision': args.revision,
                  'input_sha256': hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),
                  'instruction_sha256': hashlib.sha256(INSTRUCTION.encode()).hexdigest(),
                  'format': 'single_complete_review', 'thinking': False}
    completed = []
    if partial.exists():
        if not metadata.exists() or json.loads(metadata.read_text()) != provenance:
            raise ValueError('Partial corpus belongs to another teacher or recipe')
        completed = [json.loads(line) for line in partial.read_text().splitlines()]
        if len(completed) > len(rows):
            raise ValueError('Extra rows in partial corpus')
        for previous, original in zip(completed, rows):
            old, new = dict(previous), dict(original)
            old.pop('messages'); new.pop('messages')
            if old != new or previous['messages'][:-1] != original['messages'][:-1]:
                raise ValueError('Partial corpus does not match source')
    metadata.write_text(json.dumps(provenance))
    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.revision)
    model = LLM(model=args.model, revision=args.revision, dtype='auto',
                max_model_len=8192, max_num_seqs=args.batch_size,
                gpu_memory_utilization=0.85, enforce_eager=True,
                enable_prefix_caching=False, limit_mm_per_prompt={'image': 0, 'video': 0})
    params = SamplingParams(temperature=0, max_tokens=768, seed=42)
    accepted = rejected = 0
    with partial.open('a', buffering=1) as out:
        for start in range(len(completed), len(rows), args.batch_size):
            batch = rows[start:start + args.batch_size]
            functions = [r for r in batch if r['group'].startswith('mbpp-')]
            prompts = [tokenizer.apply_chat_template([
                {'role': 'system', 'content': INSTRUCTION},
                {'role': 'user', 'content': r['context'] + '\n\nVerified reference:\n' + r['messages'][-1]['content']}],
                tokenize=False, add_generation_prompt=True, enable_thinking=False) for r in functions]
            answers = {}
            if prompts:
                results = model.generate(prompts, params, use_tqdm=False)
                for row, result in zip(functions, results):
                    completion = result.outputs[0]
                    answer = completion.text.strip()
                    reason = validate_review(row, answer, completion.finish_reason == 'stop')
                    if reason:
                        rejected += 1
                        print('JOVOVICH_REJECT ' + json.dumps({'id': row['id'], 'reason': reason, 'answer': answer}), flush=True)
                    else:
                        accepted += 1
                        answers[row['id']] = answer
            for row in batch:
                if row['id'] in answers:
                    row['messages'][-1]['content'] = answers[row['id']]
                line = json.dumps(row, ensure_ascii=False)
                out.write(line + '\n')
                print('JOVOVICH_DATA ' + line, flush=True)
            print(json.dumps({'status': 'distilling', 'rows_completed': min(start + len(batch), len(rows)),
                              'total': len(rows), 'accepted': accepted, 'rejected': rejected}), flush=True)
    partial.replace(output)
    print(json.dumps({'status': 'distilled', 'path': str(output), 'rows': len(rows),
                      'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), **provenance}), flush=True)


if __name__ == '__main__':
    main()
