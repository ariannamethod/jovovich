"""PyTorch full SFT. Only the final model is saved; no Hub writes."""
import argparse,json,math,random
from pathlib import Path
import torch
from transformers import AutoTokenizer,AutoModelForImageTextToText,get_cosine_schedule_with_warmup

def encode(tokenizer,row,max_length):
    messages=row['messages']
    assert messages[-1]['role']=='assistant'
    prompt=tokenizer.apply_chat_template(messages[:-1],tokenize=False,add_generation_prompt=True,enable_thinking=False)
    # Tokenize the exact inference prefix once; the continuation includes EOS.
    prefix=tokenizer.encode(prompt,add_special_tokens=False)
    answer=tokenizer.encode(messages[-1]['content'],add_special_tokens=False)+[tokenizer.eos_token_id]
    if len(prefix)+len(answer)>max_length:
        raise ValueError(f"Example exceeds {max_length} tokens; refusing silent truncation")
    return prefix+answer,[-100]*len(prefix)+answer

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--model',default='Qwen/Qwen3.5-0.8B')
    p.add_argument('--revision',default='2fc06364715b967f1860aea9cf38778875588b17')
    p.add_argument('--data',default='data/train.jsonl')
    p.add_argument('--output',default='/workspace/jovovich-final')
    p.add_argument('--epochs',type=int,default=3)
    p.add_argument('--lr',type=float,default=2e-6)
    p.add_argument('--accumulation',type=int,default=8)
    p.add_argument('--max-length',type=int,default=2048)
    a=p.parse_args()
    random.seed(42);torch.manual_seed(42)
    if not torch.cuda.is_available(): raise RuntimeError('CUDA required')
    tok=AutoTokenizer.from_pretrained(a.model,revision=a.revision,trust_remote_code=False)
    rows=[json.loads(s) for s in Path(a.data).read_text().splitlines() if s.strip()]
    encoded=[encode(tok,r,a.max_length) for r in rows]
    model=AutoModelForImageTextToText.from_pretrained(a.model,revision=a.revision,dtype=torch.float32,attn_implementation='sdpa',trust_remote_code=False).cuda()
    model.gradient_checkpointing_enable();model.config.text_config.use_cache=False
    model.generation_config.eos_token_id=tok.eos_token_id
    model.generation_config.pad_token_id=tok.eos_token_id
    optimizer=torch.optim.AdamW(model.parameters(),lr=a.lr,weight_decay=.01)
    total=a.epochs*math.ceil(len(encoded)/a.accumulation)
    scheduler=get_cosine_schedule_with_warmup(optimizer,max(1,total//10),total)
    print(json.dumps({'status':'training','model':a.model,'examples':len(rows),'updates':total,'parameters':sum(p.numel() for p in model.parameters())}),flush=True)
    step=0
    model.train()
    for epoch in range(a.epochs):
        random.shuffle(encoded)
        for start in range(0,len(encoded),a.accumulation):
            group=encoded[start:start+a.accumulation]
            optimizer.zero_grad(set_to_none=True);loss_sum=0.
            for ids,labels in group:
                x=torch.tensor([ids],device='cuda'); y=torch.tensor([labels],device='cuda')
                with torch.autocast('cuda',dtype=torch.bfloat16):
                    loss=model(input_ids=x,attention_mask=torch.ones_like(x),labels=y).loss
                if not torch.isfinite(loss):raise RuntimeError('Nonfinite loss')
                (loss/len(group)).backward();loss_sum+=loss.item()
            norm=torch.nn.utils.clip_grad_norm_(model.parameters(),1.0,error_if_nonfinite=True)
            optimizer.step();scheduler.step();step+=1
            print(json.dumps({'step':step,'total':total,'epoch':epoch+1,'loss':loss_sum/len(group),'grad_norm':float(norm)}),flush=True)
    model.eval();model.config.text_config.use_cache=True
    model.to(dtype=torch.bfloat16).save_pretrained(a.output,safe_serialization=True)
    tok.save_pretrained(a.output)
    print(json.dumps({'status':'saved','path':a.output}),flush=True)
if __name__=='__main__':main()
