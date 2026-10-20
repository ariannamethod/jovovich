# JOVOVICH

Juror Of Versioned Ontology, Vigilance, Integrity, Code & Heresy.

> You opened a pull request. A woman with half a billion parameters has opinions about your dependency tree.

JOVOVICH reviews. JOVOVICH does not rule.

Read [ARIANNA_METHOD_MANIFESTO.md](ARIANNA_METHOD_MANIFESTO.md).

Training uses PyTorch and Transformers Trainer for full-parameter SFT of `Qwen/Qwen2.5-Coder-1.5B-Instruct`, pinned in `train.py`. The half-billion line is the founding joke; the current training target has 1.5 billion parameters. NoTorch is not involved in this training path.

## Train

Use CUDA PyTorch (the runner uses PyTorch 2.8.0 / CUDA 12.8).

```sh
pip install -r requirements.txt
python build_data.py
python train.py --check-only
HF_HUB_ENABLE_HF_TRANSFER=0 python train.py --output /workspace/jovovich-final
```

There are 608 training rows from 289 source groups, 60 validation rows from 29 groups, and 74 final-check rows from 37 groups. A function and all its variants stay in one split. Equivalent function bodies are deduplicated after normalizing local names. Clean and defective functions pass through the same AST formatter before entering the corpus. No filename multiplication or duplicate-row oversampling.

The corpus includes 290 distinct MBPP function bodies with execution-checked mutations and 64 authored repository-policy scenarios. Requirements and examples accompany the code. The policy scenarios cover dependencies, runtime contracts, advisory authority, identity, continuity and provenance. The old 16-case file is a legacy diagnostic, not the final check.

Training and inference use the model's native chat template. Prompts and padding are excluded from the loss. Before optimization the trainer checks exact chat-prefix continuity, target decoding, ignored padding and agreement with explicit shifted PyTorch cross entropy. All text parameters are trained with FP32 parameters and optimizer state, BF16 autocast, learning rate 1e-5 and three epochs. Four microbatches of four samples form an effective batch of 16. Validation loss is measured before training and after each epoch. Only the final model is saved. No script uploads weights to Hugging Face.

## Review

```sh
python review.py --model /workspace/jovovich-final --context change.txt
python review.py --model /workspace/jovovich-final --cases data/test.jsonl
```

The reviewer receives rules and proposed code or diff. It emits evidence followed by `Verdict: CONCERN` or `Verdict: CLEAN`. It cannot merge, reject or execute code. Check explanations alongside verdicts before releasing a trained model.

The authenticated Runpod worker checks tokenization, runs the untuned model on validation cases, trains, then evaluates the saved model on the final cases. It stops the pod 15 minutes after completion/failure, with a 90-minute hard limit. Run states and generated answers are mirrored into Runpod container logs as they are produced. The final model is available through authenticated `/model` and `/model/<filename>` endpoints, with SHA-256 checksums. Final weights remain on the stopped pod volume. This branch provides the implementation; it does not yet declare a released model.

## Data

[Google Research MBPP](https://github.com/google-research/google-research/tree/master/mbpp), sanitized source, Apache 2.0; see `data/MBPP-LICENSE`. Source SHA-256: `ca95deaa9a01ef0a6f439f88bcf0dd3db3563d22f22aad6cae04ebb9a8d8c8e9`.

`python verify_functions.py` rebuilds mutation records from the retained source; `python build_data.py` constructs splits. The verifier checks a computation-oriented subset in resource-limited child processes. It is a dataset utility, not an execution service for PR code.

Origin: Milla Jovovich, freckles, Lalo Salamanca, Oleg and Sol. The provenance remains ridiculous. The implementation must work.
