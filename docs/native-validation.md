# Native baseline — 2026-11-06

The live executable runs the original OneJev checkpoint pinned in
[models/onejev-0.8b.json](../models/onejev-0.8b.json). The question and prompt
live in [AML](../aml/prepare.aml); selection and timestamp construction live in
[answer.aml](../aml/answer.aml). The C host runs NoTorch on chunks of 32 tokens,
then calculates a two-way softmax over output IDs 32 and 33.

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
