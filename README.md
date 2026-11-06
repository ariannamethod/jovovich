# jovovich
Juror Of Versioned Ontology, Vigilance, Integrity, Code &amp; Heresy

JOVOVICH reviews a change against the repository's stated rules. Its English
answer starts with **CONCERN** or **CLEAN**, quotes the exact rule and changed
code, and shows both choice probabilities. JOVOVICH reviews. JOVOVICH does not rule.

The live path runs original **OmniJev/OneJev-0.8B** through **NoTorch**, with
**Arianna Method Language (AML)** assembling the question, selecting the answer
and recording its time through JANUS.CALENDAR. C handles model I/O and output
serialization. There is no Python dependency in JOVOVICH's build, tests or runtime.

```sh
git submodule update --init
make
make check
```

The two dependencies are pinned in `deps/notorch` and `deps/aml`. Existing
checkouts can be used with `NOTORCH_ROOT=/path/to/notorch AML_ROOT=/path/to/aml`.
The dependency-free recorded demo is available with `make build/review-demo`.

## Live review

Download `config.json`, `model.safetensors` and `tokenizer.json` from
[`OmniJev/OneJev-0.8B` at c02e305](https://huggingface.co/OmniJev/OneJev-0.8B/tree/c02e305b430b56c1e82f9675ba8c293a22646891)
into a local snapshot directory. Convert the original text tensors and tokenizer
using NoTorch's C tools:

```sh
make -C deps/notorch qwen35_to_gguf
./deps/notorch/qwen35_to_gguf /path/to/snapshot model.gguf
./deps/notorch/qwen35_to_gguf --tokenizer /path/to/snapshot/tokenizer.json tokenizer.gguf
./build/jovovich model.gguf tokenizer.gguf --json < examples/reviews.jsonl
```

Run from this repository's root so AML scripts and the model manifest can be
found. Omit `--json` for Markdown output. Inputs are JSONL with `id`, `file`,
`context`, `rule_excerpt` and `change_excerpt`; the supplied excerpts and file
must occur in the context. The example file contains all 14 review cases.
Model and tokenizer bytes must match [the pinned manifest](models/onejev-0.8b.json).
All diagnostics go to stderr; consumers must check the exit code.

The first native path uses F32 CPU arithmetic and ASCII English input. It
prefills in chunks of 32, reads the A/B logits and generates zero tokens. The
chat template closes the thinking section before scoring. The original model
is unabliterated and has had zero training updates in this restart. Its source
checkpoint retains vision components; the current executable consumes text.

An optional BLAS backend is selected with `BLAS_FLAGS` and `BLAS_LIBS` at build
time. Build the dependencies with the same flags; when switching backends,
clean their compiled objects first. The first implementation expands matrix
weights to F32. Speed and memory optimization come after this parity baseline.

## Recorded decisions and verification

```sh
./build/review-demo
./build/review-demo --json all
./build/check-pipeline --live live-answers.jsonl
```

The demo preserves the original BF16 reference answers, while the live pipeline
uses the separately recorded F32 reference. Both selected 12/14 correct
verdicts: 5/7 concerns, 7/7 clean changes. Both missed the index boundary and
disabled writer. Every live choice matches its reference; probabilities meet
the 2e-4 gate. NoTorch additionally passed all-layer and full-vocabulary logit
comparisons. [Validation details](docs/native-validation.md).

`make check` verifies saved answers, exact AML prompts, calendar fields, ties,
invalid probabilities, literal evidence and output escaping in C + AML.
JSON output includes the input/model/tokenizer hashes and a split POSIX
`janus.instant/1` execution timestamp. This follows the provenance discipline
used by LALO and Amos 2. A review timestamp records when the review ran.

The [answer contract](docs/review-output.md) describes the English output.
The new [JOVOVICHLOG](JOVOVICHLOG.md) starts from measured behavior. Next stages
are JOVOVICH's own voice, training, the vision path and matched llama.cpp speed
measurements. The model repository [`ataeff/jovovich`](https://huggingface.co/ataeff/jovovich)
remains private.
