# JOVOVICH

Juror Of Versioned Ontology, Vigilance, Integrity, Code & Heresy.

> You opened a pull request. A woman with half a billion parameters has opinions about your dependency tree.

JOVOVICH reviews. JOVOVICH does not rule.

Read [ARIANNA_METHOD_MANIFESTO.md](ARIANNA_METHOD_MANIFESTO.md).

Training uses PyTorch and Transformers Trainer for full-parameter SFT of `Qwen/Qwen3.5-0.8B`, pinned in `train.py`. The half-billion line is the founding joke; the current training target is the 0.8B Qwen3.5 model. NoTorch is not involved in this training path.

## Train

Use a CUDA PyTorch environment compatible with the pinned Transformers version. Teacher generation additionally requires vLLM 0.32.0; the worker installs it before distillation.

```sh
pip install -r requirements.txt
python build_data.py
python -m pip install vllm==0.32.0
python distill.py --model Qwen/Qwen3.5-27B-FP8 --revision 97f5941bf617e31c5e237364a8602ce3f03a551a
python train.py --data data/train_distilled.jsonl --check-only
HF_HUB_ENABLE_HF_TRANSFER=0 python train.py --data data/train_distilled.jsonl --output /workspace/jovovich-final
```

The rebuilt corpus has 533 training rows from 246 source groups, 48 validation rows from 23 groups, and 68 final-check rows from 34 groups. A function and all its variants stay in one split. Equivalent function bodies are deduplicated after normalizing local names. Clean and defective functions pass through the same AST formatter before entering the corpus. No filename multiplication or duplicate-row oversampling.

Contract auditing quarantined 51 MBPP source tasks, including one previously deduplicated task, and two repository-policy groups. `data/fixture_quarantine.json` retains the failing assertions and reasons. Whole source groups are excluded; labels are not flipped to match model answers. `train.py` and `distill.py` reject stale corpora containing these groups before loading model weights. Training is paused while the remaining supervision and inference protocol are checked. `distill.py` asks the pinned Qwen3.5 teacher for one complete review. It preserves verified repair sentences, requires a complete generation and one matching verdict, and rejects supervisor references. Rejected rewrites retain the original checked target. Identity and repository-policy answers retain their original supervision. Generated explanations require content review before training. With `TEACHER_REVIEW_REQUIRED=1`, the worker pauses after distillation until `/approve-data` receives the exact reviewed corpus SHA-256. `TEACHER_CACHE_DIR` separates teacher downloads from the volume used for student weights. The worker can use a separately supplied, SHA-256-verified training corpus without repeating teacher generation.

The rebuilt corpus includes 240 distinct MBPP function bodies with execution-checked mutations and 62 retained repository-policy scenarios. Requirements and examples accompany the code. The policy scenarios cover dependencies, runtime contracts, advisory authority, identity, continuity and provenance. The old `data/eval.jsonl` is a legacy diagnostic. `data/acceptance.jsonl` contains 14 additional repository-review cases and two direct identity questions, kept out of training. The former 74-case function/policy control was used to evaluate previous versions. Historical scores include defective labels and must be recomputed with the explicit quarantine exclusions.

Training and inference use the model's native chat template. Prompts and padding are excluded from the loss. Before optimization the trainer checks exact chat-prefix continuity, target decoding, ignored padding and agreement with explicit shifted PyTorch cross entropy. The vision tower stays frozen. All text parameters are trained with FP32 parameters and optimizer state, BF16 autocast, learning rate 1e-5 and three epochs. Four microbatches of four samples form an effective batch of 16. Validation loss is measured before training and after each epoch. Training function reviews include computed outputs from the retained examples; policy reviews connect the repository rule to the finding. A pinned Qwen3.5-27B-FP8 teacher rewrites function reviews in the training split; identity and repository-policy answers are preserved. Distillation never receives validation, control or acceptance prompts. Its generated rows are streamed to provider logs during the Runpod job. Only the final model is saved. No script uploads weights to Hugging Face.

## Review

```sh
python review.py --model /workspace/jovovich-final --context change.txt
python review.py --model /workspace/jovovich-final --cases data/test.jsonl data/acceptance.jsonl
python review.py --model /workspace/jovovich-final --message "Who are you?"
python review.py --model /workspace/jovovich-final --cases data/test.jsonl data/acceptance.jsonl > answers.jsonl
python evaluate.py answers.jsonl
```

The reviewer receives rules and proposed code or diff. It emits evidence followed by `Verdict: CONCERN` or `Verdict: CLEAN`. It cannot merge, reject or execute code. Check explanations alongside verdicts before releasing a trained model. `evaluate.py` reports strict verdict formatting and semantic verdict accuracy separately; executable replacement functions receive repair credit as well as expression-level patches. Incomplete generations do not receive verdict or repair credit. Missing completion metadata is reported as unknown and earns no credit. Markdown verdict lines are accepted by the semantic metric; text inside code fences is excluded. Repair credit means passing the retained examples, while counterexample credit currently requires an assertion matching a retained example; these are separate measurements from the correctness of the explanation. Thinking-enabled candidate checks and deployed nonthinking inference are separate configurations.

The authenticated Runpod worker checks tokenization, runs the untuned model on validation cases, trains, then evaluates the saved model on the final cases. It stops the pod 15 minutes after completion/failure, with a 90-minute hard limit. Run states and generated answers are mirrored into Runpod container logs as they are produced. The final model is available through authenticated `/model` and `/model/<filename>` endpoints, with SHA-256 checksums. Final weights remain on the stopped pod volume. This branch provides the implementation; it does not yet declare a released model.

## Data

[Google Research MBPP](https://github.com/google-research/google-research/tree/master/mbpp), sanitized source, Apache 2.0; see `data/MBPP-LICENSE`. Source SHA-256: `ca95deaa9a01ef0a6f439f88bcf0dd3db3563d22f22aad6cae04ebb9a8d8c8e9`.

`python verify_functions.py` rebuilds mutation records from the retained source; passing those examples alone does not establish a CLEAN contract label. `python build_data.py` constructs splits with the quarantine applied. `python -m unittest test_fixture_quality -v` reproduces the quarantined counterexamples and checks corpus rejection, split integrity and scoring regressions. The verifier checks a computation-oriented subset in resource-limited child processes. It is a dataset utility, not an execution service for PR code.

Origin: Milla Jovovich, freckles, Lalo Salamanca, Oleg and Sol. The provenance remains ridiculous. The implementation must work.
