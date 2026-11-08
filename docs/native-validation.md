# Native baseline — 2026-11-06

The live executable runs the original OneJev checkpoint pinned in the model
manifest. NoTorch prefills in chunks of 32 and returns the A and B logits
at vocabulary IDs 32 and 33. AML assembles the question, applies the two-way
softmax, selects the verdict and constructs its timestamp.
[Manifest](../models/onejev-0.8b.json) · [Prompt](../aml/prepare.aml) · [Readout](../aml/score-choices.aml) · [Answer](../aml/answer.aml)

## Independent reference

Transformers 5.15.0 / Torch 2.13.0 CPU, F32 with eager attention, four threads.
Reference generation was an exploratory step outside this repository.
[The frozen F32 probabilities](../examples/native-f32/reference.jsonl) are
separate from the original [BF16 measurements](../examples/onejev-20261106/).

NoTorch compared all 24 layer residuals for every input token and all 248,320
final logits on all 14 review prompts. Pre-recorded limits were residual
relative L2 2e-4, full-logit max absolute error 2e-3, and choice probability
absolute error 2e-4. Observed maxima were respectively 1.7839233768302967e-6,
1.811981201171875e-5 and 1.3450441778140032e-6. All token IDs and all choices
matched. The native C converter produced the same 321-tensor file as the
independent reference pack, byte for byte.

The live AML + C tokenizer + NoTorch pipeline then passed all 14 prompts with
the same 2e-4 probability tolerance. The score is 12/14: 5/7 defect cases and
7/7 clean cases. `accept-boundary-False` and `accept-disabled-False` remain the
two measured misses. Both references and the renderer preserve them.

The subsequent [38-case quality experiment](review-quality.md) retains these
14 cases and adds 24 transfer cases. It records a comparison of two AML
questions, every native answer and the measured semantic errors.

## Reproduce the consumer gates

```sh
make check
./build/jovovich model.gguf tokenizer.gguf --json < examples/reviews.jsonl > live-answers.jsonl
./build/check-pipeline --live live-answers.jsonl
```

The first command checks all 14 saved choices/probabilities exactly, builds
all 14 prompts in AML and compares the entire prompt bytes to the independent
records. It also checks quote round trips, calendar milliseconds and pre-epoch
days, probability rejection and tie policy. The live gate verifies the actual
output probabilities, choices, provenance hashes and execution timestamps.

On this run: 941 saved/AML checks and 1,340 live checks passed, alongside the
formatter's rejection/escaping checks. NoTorch's synthetic gate passed 1,214
checks, and its tokenizer gate passed 15. Disabling recurrent decay in a
temporary NoTorch copy made 968 synthetic checks fail. NoTorch's full
`make -j4 test` suite passed.

Native execution used x86_64 Linux / AMD EPYC 9V74, OpenBLAS via
`libcasadi-tp-openblas`, four BLAS threads and four attention threads. This is a
correctness record. A speed comparison with llama.cpp is scheduled as a later
engineering stage with matched model, dtype, context and hardware.
