# JOVOVICH

Juror Of Versioned Ontology, Vigilance, Integrity, Code & Heresy.

> You opened a pull request. A woman with half a billion parameters has opinions about your dependency tree.

JOVOVICH reviews. JOVOVICH does not rule.

Read [ARIANNA_METHOD_MANIFESTO.md](ARIANNA_METHOD_MANIFESTO.md).

Training uses PyTorch and Transformers Trainer for full-parameter SFT of `Qwen/Qwen3.5-0.8B`, pinned in `train.py`. The half-billion line is the founding joke; the current training target is the 0.8B Qwen3.5 model. NoTorch is not involved in this training path.

## Train

Use CUDA PyTorch (the runner uses PyTorch 2.8.0 / CUDA 12.8).

```sh
pip install -r requirements.txt
python build_data.py
python distill.py --model Qwen/Qwen2.5-Coder-7B-Instruct --revision c03e6d358207e414f1eca0bb1891e29f1db0e242
python train.py --data data/train_distilled.jsonl --check-only
HF_HUB_ENABLE_HF_TRANSFER=0 python train.py --data data/train_distilled.jsonl --output /workspace/jovovich-final
```

There are 620 training rows from 289 source groups, 60 validation rows from 29 groups, and 74 final-check rows from 37 groups. A function and all its variants stay in one split. Equivalent function bodies are deduplicated after normalizing local names. Clean and defective functions pass through the same AST formatter before entering the corpus. No filename multiplication or duplicate-row oversampling.

The corpus includes 290 distinct MBPP function bodies with execution-checked mutations and 64 authored repository-policy scenarios. Requirements and examples accompany the code. The policy scenarios cover dependencies, runtime contracts, advisory authority, identity, continuity and provenance. The old `data/eval.jsonl` is a legacy diagnostic. `data/acceptance.jsonl` contains 14 additional repository-review cases and two direct identity questions, kept out of training. The 74-case function/policy control has already been used to evaluate previous versions.

Training and inference use the model's native chat template. Prompts and padding are excluded from the loss. Before optimization the trainer checks exact chat-prefix continuity, target decoding, ignored padding and agreement with explicit shifted PyTorch cross entropy. The vision tower stays frozen. All text parameters are trained with FP32 parameters and optimizer state, BF16 autocast, learning rate 1e-5 and three epochs. Four microbatches of four samples form an effective batch of 16. Validation loss is measured before training and after each epoch. Training function reviews include computed outputs from the retained examples; policy reviews connect the repository rule to the finding. A pinned Qwen2.5-Coder-7B teacher adds code-specific explanations to the training split; identity answers are preserved. The teacher never receives validation, control or acceptance prompts. Its generated rows are streamed to provider logs during the Runpod job. Only the final model is saved. No script uploads weights to Hugging Face.

## Review

```sh
python review.py --model /workspace/jovovich-final --context change.txt
python review.py --model /workspace/jovovich-final --cases data/test.jsonl data/acceptance.jsonl
python review.py --model /workspace/jovovich-final --message "Who are you?"
python review.py --model /workspace/jovovich-final --cases data/test.jsonl data/acceptance.jsonl > answers.jsonl
python evaluate.py answers.jsonl
```

The reviewer receives rules and proposed code or diff. It emits evidence followed by `Verdict: CONCERN` or `Verdict: CLEAN`. It cannot merge, reject or execute code. Check explanations alongside verdicts before releasing a trained model.

The authenticated Runpod worker checks tokenization, runs the untuned model on validation cases, trains, then evaluates the saved model on the final cases. It stops the pod 15 minutes after completion/failure, with a 90-minute hard limit. Run states and generated answers are mirrored into Runpod container logs as they are produced. The final model is available through authenticated `/model` and `/model/<filename>` endpoints, with SHA-256 checksums. Final weights remain on the stopped pod volume. This branch provides the implementation; it does not yet declare a released model.

## Data

[Google Research MBPP](https://github.com/google-research/google-research/tree/master/mbpp), sanitized source, Apache 2.0; see `data/MBPP-LICENSE`. Source SHA-256: `ca95deaa9a01ef0a6f439f88bcf0dd3db3563d22f22aad6cae04ebb9a8d8c8e9`.

`python verify_functions.py` rebuilds mutation records from the retained source; `python build_data.py` constructs splits. The verifier checks a computation-oriented subset in resource-limited child processes. It is a dataset utility, not an execution service for PR code.

Origin: Milla Jovovich, freckles, Lalo Salamanca, Oleg and Sol. The provenance remains ridiculous. The implementation must work.
