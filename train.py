"""PyTorch Transformers Trainer SFT. One final model, no Hub writes."""
import argparse
import json
import math
from pathlib import Path
import torch
from transformers import (AutoTokenizer, AutoModelForCausalLM, AutoModelForImageTextToText, AutoConfig, Trainer,
                          TrainingArguments, DataCollatorForSeq2Seq, set_seed)

MODEL = 'Qwen/Qwen3.5-0.8B'
REVISION = '2fc06364715b967f1860aea9cf38778875588b17'

def encode(tokenizer, row, max_length):
    messages = row['messages']
    if messages[-1]['role'] != 'assistant':
        raise ValueError('Training row must end with an assistant answer')
    prefix = tokenizer.apply_chat_template(messages[:-1], tokenize=True, add_generation_prompt=True, return_dict=False, enable_thinking=False)
    complete = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False, return_dict=False, enable_thinking=False)
    if complete[:len(prefix)] != prefix:
        raise ValueError('Training chat is not an exact continuation of the inference prefix')
    target = complete[len(prefix):]
    if not target or tokenizer.eos_token_id not in target:
        raise ValueError('Assistant target has no end-of-turn token')
    if tokenizer.decode(target, skip_special_tokens=True).strip() != messages[-1]['content'].strip():
        raise ValueError('Assistant target failed tokenizer round trip')
    if len(complete) > max_length:
        raise ValueError(f"Overlong row {row.get('id')}: {len(complete)} > {max_length}")
    return {'input_ids': complete, 'attention_mask': [1] * len(complete),
            'labels': [-100] * len(prefix) + target}

def read_rows(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default=MODEL)
    parser.add_argument('--revision', default=REVISION)
    parser.add_argument('--data', default='data/train.jsonl')
    parser.add_argument('--validation', default='data/validation.jsonl')
    parser.add_argument('--output', default='/workspace/jovovich-final')
    parser.add_argument('--epochs', type=int, default=3)
    parser.add_argument('--lr', type=float, default=1e-5)
    parser.add_argument('--batch-size', type=int, default=4)
    parser.add_argument('--gradient-accumulation', type=int, default=4)
    parser.add_argument('--max-length', type=int, default=2048)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    set_seed(42)
    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.revision)
    tokenizer.padding_side = 'right'
    train_rows, valid_rows = read_rows(args.data), read_rows(args.validation)
    if {r['group'] for r in train_rows} & {r['group'] for r in valid_rows}:
        raise ValueError('Training and validation source tasks overlap')
    train = [encode(tokenizer, r, args.max_length) for r in train_rows]
    valid = [encode(tokenizer, r, args.max_length) for r in valid_rows]
    collator = DataCollatorForSeq2Seq(tokenizer, padding=True, label_pad_token_id=-100)
    sample = collator([train[0], train[-1]])
    if not torch.all(sample['labels'][sample['attention_mask'] == 0] == -100):
        raise ValueError('Padding contributes to loss')
    print(json.dumps({'status': 'data_checked', 'train': len(train), 'validation': len(valid),
                      'maximum_tokens': max(len(r['input_ids']) for r in train + valid),
                      'supervised_tokens': sum(sum(v != -100 for v in r['labels']) for r in train)}), flush=True)
    if args.check_only:
        return
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA required')
    config = AutoConfig.from_pretrained(args.model, revision=args.revision)
    model_class = AutoModelForImageTextToText if config.model_type == 'qwen3_5' else AutoModelForCausalLM
    model = model_class.from_pretrained(args.model, revision=args.revision,
                    dtype=torch.float32, attn_implementation='sdpa')
    for name, parameter in model.named_parameters():
        if '.visual.' in name or '.vision_' in name:
            parameter.requires_grad_(False)
    model.enable_input_require_grads()
    print(json.dumps({'status': 'parameters_checked', 'model': args.model,
                      'revision': args.revision, 'method': 'full_sft',
                      'trainable_parameters': sum(p.numel() for p in model.parameters() if p.requires_grad),
                      'total_parameters': sum(p.numel() for p in model.parameters()),
                      'parameter_dtypes': sorted({str(p.dtype) for p in model.parameters() if p.requires_grad})}), flush=True)
    model.config.use_cache = False
    if hasattr(model.config, 'text_config'): model.config.text_config.use_cache = False
    training = TrainingArguments(
        output_dir=args.output + '-trainer', num_train_epochs=args.epochs,
        learning_rate=args.lr, per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size, gradient_accumulation_steps=args.gradient_accumulation,
        bf16=True, gradient_checkpointing=True, optim='adamw_torch',
        lr_scheduler_type='cosine', warmup_steps=max(1, int(args.epochs * math.ceil(len(train) / (args.batch_size * args.gradient_accumulation)) * 0.1)), weight_decay=0.01,
        max_grad_norm=1.0, eval_strategy='epoch', save_strategy='no',
        logging_steps=10, report_to='none', seed=42, data_seed=42,
        remove_unused_columns=False, prediction_loss_only=True)
    trainer = Trainer(model=model, args=training, train_dataset=train,
                      eval_dataset=valid, data_collator=collator, processing_class=tokenizer)
    # Verify the model's causal shift and masked cross entropy against PyTorch directly.
    batch = {k: v.to(trainer.model.device) for k, v in sample.items()}
    model.eval()
    with torch.no_grad(), torch.autocast('cuda', dtype=torch.bfloat16):
        output = model(**batch)
    manual = torch.nn.functional.cross_entropy(
        output.logits[:, :-1].float().reshape(-1, output.logits.shape[-1]),
        batch['labels'][:, 1:].reshape(-1), ignore_index=-100)
    if not torch.allclose(output.loss.float(), manual, rtol=1e-4, atol=1e-4):
        raise RuntimeError('Model loss does not match shifted assistant-only cross entropy')
    print(json.dumps({'status': 'loss_checked', 'loss': float(manual)}), flush=True)
    del output, manual, batch
    print(json.dumps({'before_training': trainer.evaluate()}), flush=True)
    trainer.train()
    model.eval()
    model.config.use_cache = True
    if hasattr(model.config, 'text_config'): model.config.text_config.use_cache = True
    model.to(dtype=torch.bfloat16).save_pretrained(args.output, safe_serialization=True)
    tokenizer.save_pretrained(args.output)
    print(json.dumps({'status': 'saved', 'path': args.output}), flush=True)

if __name__ == '__main__':
    main()
