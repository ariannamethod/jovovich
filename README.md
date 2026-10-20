# JOVOVICH

Juror Of Versioned Ontology, Vigilance, Integrity, Code & Heresy.

> You opened a pull request. A woman with half a billion parameters has opinions about your dependency tree.

Read [ARIANNA_METHOD_MANIFESTO.md](ARIANNA_METHOD_MANIFESTO.md).

JOVOVICH reviews. JOVOVICH does not rule.

The fresh implementation uses PyTorch and Transformers, as explicitly requested by the maintainer. Its initial training source is `Qwen/Qwen3.5-0.8B`, pinned in `train.py`. NoTorch is no longer required for training.

## Train

Use a CUDA PyTorch environment (the current runner uses PyTorch 2.8.0, CUDA 12.8).

```sh
pip install -r requirements.txt
python build_data.py
HF_HUB_ENABLE_HF_TRANSFER=0 python train.py --epochs 6 --output /workspace/jovovich-final
```

Full-parameter identity tuning uses the model's chat template, assistant-only loss, FP32 optimizer parameters and BF16 autocast. Overlong examples fail explicitly. Only the final model is saved. Nothing is uploaded to Hugging Face by these scripts.

The curriculum contains 10 identity and voice examples. Repository rules and diffs arrive at runtime. A separate 16-case review check exercises clean changes and concrete violations.

## Review

Put repository rules and a diff in a text file, then:

```sh
python review.py --model /workspace/jovovich-final --context change.txt
python review.py --model /workspace/jovovich-final --cases data/eval.jsonl
```

The reviewer emits `Verdict: CONCERN` or `Verdict: CLEAN` followed by a short explanation. It does not execute repository text or perform GitHub actions. The supplied repository rules decide whether a dependency or language belongs here.

`worker.py` runs the training and evaluation on Runpod behind a bearer-authenticated HTTP endpoint. It stops the pod 15 minutes after completion or failure, with a 90-minute total limit. Final weights remain on the pod volume; stopping does not terminate the pod or delete that volume.

Origin: Milla Jovovich, freckles, Lalo Salamanca, Oleg and Sol. The provenance remains ridiculous. The implementation must work.
