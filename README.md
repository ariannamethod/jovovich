# JOVOVICH

Juror Of Versioned Ontology, Vigilance, Integrity, Code & Heresy.

> You opened a pull request. A woman with half a billion parameters has opinions about your dependency tree.

Read [ARIANNA_METHOD_MANIFESTO.md](ARIANNA_METHOD_MANIFESTO.md).

JOVOVICH reviews. JOVOVICH does not rule.

The fresh implementation uses PyTorch and Transformers, as explicitly requested by the maintainer. Its initial training source is `Qwen/Qwen2.5-Coder-1.5B-Instruct`, pinned in `train.py`. NoTorch is no longer required for training.

## Train

Use a CUDA PyTorch environment (the current runner uses PyTorch 2.8.0, CUDA 12.8).

```sh
pip install -r requirements.txt
python build_data.py
HF_HUB_ENABLE_HF_TRANSFER=0 python train.py --epochs 6 --output /workspace/jovovich-final
```

PEFT LoRA tuning (rank 16, alpha 32, all linear layers) uses the model's chat template, assistant-only loss, a BF16 base model and BF16 autocast. Overlong examples fail explicitly. Only the final model is saved. Nothing is uploaded to Hugging Face by these scripts.

The curriculum contains 24 review situations in four path variants, with policy controls and corrected-code controls. Concern rows are sampled twice to balance the two clean controls: 384 review rows plus 10 identity examples (394 total, 298 unique prompts). Training uses the same context formatter and chat messages as inference. The separate 16-case review check includes different snippets.

## Review

Put repository rules and a diff in a text file, then:

```sh
python review.py --model /workspace/jovovich-final --context change.txt
python review.py --model /workspace/jovovich-final --cases data/eval.jsonl
```

The reviewer emits a short explanation followed by `Verdict: CONCERN` or `Verdict: CLEAN`. It does not execute repository text or perform GitHub actions. The supplied repository rules decide whether a dependency or language belongs here.

`worker.py` runs the training and evaluation on Runpod behind a bearer-authenticated HTTP endpoint. It stops the pod 15 minutes after completion or failure, with a 90-minute total limit. Final weights remain on the pod volume; stopping does not terminate the pod or delete that volume.

Origin: Milla Jovovich, freckles, Lalo Salamanca, Oleg and Sol. The provenance remains ridiculous. The implementation must work.
