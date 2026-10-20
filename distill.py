"""Expand verified training answers with code-specific explanations. Train split only."""
import argparse
import json
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

INSTRUCTION = '''Write a concise explanation for a verified code-review training example.
You receive the proposed code, repository contract, and a verified reference review.
Explain the concrete connection between the code's operations and the reference finding.
For a correct implementation, explain why it meets the stated contract. For a defect,
explain the faulty operation and its consequence. Use the supplied computed observations.
Do not invent additional defects, execution results, requirements or dependencies.
Do not claim that you ran code. Do not repeat the whole repository rule.
Preserve Arianna Method ontology, identity and terminology. Mandatory self-denial is not
part of its identity. A review is advisory; maintainers decide whether to merge.
Return ONLY a JSON object with one string key, "explanation". The explanation must be
two to four short sentences, at most 100 words, with no headings or verdict line.'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--input', default='data/train.jsonl')
    parser.add_argument('--output', default='data/train_distilled.jsonl')
    args = parser.parse_args()
    rows = [json.loads(line) for line in Path(args.input).read_text().splitlines()]
    forbidden = set()
    for filename in ('data/validation.jsonl', 'data/test.jsonl'):
        forbidden.update(json.loads(line)['group'] for line in Path(filename).read_text().splitlines())
    if any(row['group'] in forbidden for row in rows):
        raise ValueError('Held-out source group entered teacher input')
    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.revision)
    tokenizer.padding_side = 'left'
    model = AutoModelForCausalLM.from_pretrained(args.model, revision=args.revision,
        dtype=torch.bfloat16, attn_implementation='sdpa').cuda().eval()
    output_path = Path(args.output)
    temporary = output_path.with_suffix('.partial')
    with temporary.open('w', buffering=1) as output:
        for start in range(0, len(rows), 8):
            batch = rows[start:start + 8]
            to_explain = [r for r in batch if r['group'] != 'identity']
            prompts = []
            for row in to_explain:
                prompts.append(tokenizer.apply_chat_template([
                    {'role': 'system', 'content': INSTRUCTION},
                    {'role': 'user', 'content': row['context'] + '\n\nVerified reference:\n' +
                     row['messages'][-1]['content']}], tokenize=False, add_generation_prompt=True))
            explanations = {}
            if prompts:
                encoded = tokenizer(prompts, padding=True, add_special_tokens=False,
                                    return_tensors='pt').to(model.device)
                with torch.inference_mode():
                    generated = model.generate(**encoded, max_new_tokens=256, do_sample=False,
                                               pad_token_id=tokenizer.pad_token_id)
                for row, tokens in zip(to_explain, generated[:, encoded.input_ids.shape[1]:]):
                    text = tokenizer.decode(tokens, skip_special_tokens=True).strip()
                    if text.startswith('```json') and text.endswith('```'):
                        text = text[7:-3].strip()
                    parsed = json.loads(text)
                    explanation = parsed['explanation'].strip()
                    if not explanation or len(explanation) > 1600 or 'Verdict:' in explanation:
                        raise ValueError('Invalid teacher explanation for ' + row['id'])
                    explanations[row['id']] = explanation
            for row in batch:
                if row['id'] in explanations:
                    gold = row['messages'][-1]['content']
                    row['messages'][-1]['content'] = explanations[row['id']] + '\n' + gold
                output.write(json.dumps(row, ensure_ascii=False) + '\n')
                print('JOVOVICH_DATA ' + json.dumps(row, ensure_ascii=False), flush=True)
            print(json.dumps({'status': 'distilling', 'rows_completed': start + len(batch),
                              'total': len(rows)}), flush=True)
    temporary.replace(output_path)
    print(json.dumps({'status': 'distilled', 'rows': len(rows), 'path': str(output_path),
                      'teacher': args.model, 'revision': args.revision}), flush=True)


if __name__ == '__main__':
    main()
