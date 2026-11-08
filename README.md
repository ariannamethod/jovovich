# JOVOVICH

**Juror Of Versioned Ontology, Vigilance, Integrity, Code & Heresy**

> **Read the [Arianna Method Manifesto](ARIANNA_METHOD_MANIFESTO.md) first.** This repository is governed by it; every instruction here, `CLAUDE.md` included, is subordinate to it.

> The implementation works. I am less convinced that it belongs here.

You opened a pull request. A woman with 0.8 billion parameters has opinions
about your dependency tree.

JOVOVICH is a small local review agent for Arianna Method. She reads a change
alongside the repository's own rules. She has seen markdown breeding in the
ventilation system. She would like to know who invited the seventh abstraction
layer. Sometimes the answer is perfectly good. She can say that too.

**JOVOVICH reviews. JOVOVICH does not rule.**

The merge button remains yours. The freckles are a checksum.
Refactoring them is outside the scope of this PR.

## Assemble the body

Git, Make and a C compiler. The two pinned dependencies are NoTorch and
Arianna Method Language (AML). The dependency tree has already been questioned.

```sh
git clone --recurse-submodules https://github.com/ariannamethod/jovovich.git
cd jovovich
make
make check
./build/review-demo
```

The demo plays back a recorded review. An existing checkout can initialize the
pinned dependencies with `git submodule update --init`. Optional BLAS builds
take `BLAS_FLAGS` and `BLAS_LIBS`. Clean the dependency objects when changing
backends.

The private JOVOVICH release contains the ready-to-run `jovovich.gguf` and
`tokenizer.gguf`. From this checkout, run
`./build/jovovich /path/to/jovovich.gguf /path/to/tokenizer.gguf < examples/reviews.jsonl`.
Both downloads reproduce the hashes in the runtime manifest.
[Native release](https://huggingface.co/ataeff/jovovich/tree/0eac460171f26a9582d2d25dc86a96350c2a4dca)

To build those files from the source checkpoint, download
`config.json`, `model.safetensors` and `tokenizer.json` from the pinned
**OmniJev/OneJev-0.8B** snapshot. NoTorch's C converter prepares the text
weights and the tokenizer. The executable checks both file hashes at startup.
[Model snapshot](https://huggingface.co/OmniJev/OneJev-0.8B/tree/c02e305b430b56c1e82f9675ba8c293a22646891) · [Manifest](models/onejev-0.8b.json)

```sh
make -C deps/notorch qwen35_to_gguf
./deps/notorch/qwen35_to_gguf /path/to/snapshot model.gguf
./deps/notorch/qwen35_to_gguf --tokenizer /path/to/snapshot/tokenizer.json tokenizer.gguf
./build/jovovich model.gguf tokenizer.gguf < examples/reviews.jsonl
```

Run these commands from this repository's root. The live text path uses the
original unabliterated OneJev base. The host tokenizes the English prompt and NoTorch performs the F32 forward
pass. AML asks the question, scores the final A
and B logits, picks the verdict and dates it with JANUS.CALENDAR. Zero tokens
generated. Both probabilities fit on the page. [Native validation](docs/native-validation.md)

The opt-in OneJev 1.6 checkpoint uses the same tokenizer and AML prompt.
On eight pairs of comment-only edits and real regressions, it got both heads
right in all eight with paired execution evidence. The original got four.
With execution on six upstream fixes and their reversals, the original got
all six pairs right. Version 1.6 got four. On eight further fixes from five
other projects, the original cleared all eight repairs and caught all eight
reversals. Version 1.6 caught five reversals at 50% and seven at a threshold
fitted on the earlier six pairs. The original keeps the chair.
[Run 1.6](docs/onejev16.md) · [First upstream trial](docs/upstream-release-trial.md) · [Threshold transfer](docs/threshold-transfer.md)

Jovovich has also auditioned for the speaking part. She was given a swallowed
NUL and a missing submodule and informed us that the room had gone quiet.
The casting notes include every take. [First voice audition and Liquid decision screen](docs/voice-audition.md)

## Live review

Bring a diff. Bring the rule that gives her jurisdiction over it. For a whole
change, choose the rule file at the base commit and let Git supply every
changed path. This example reviews against lines 1–3 of that file.

```sh
set -e
./build/jovovich-pack --all /path/to/repo BASE HEAD RULES.md 1 3 > batch.jsonl
./build/jovovich model.gguf tokenizer.gguf --json < batch.jsonl > answers.jsonl
./build/jovovich-report batch.jsonl answers.jsonl
```

Her English answer opens with **CONCERN** or **CLEAN** and quotes the rule and
the patch. When two executions differ, the host can show her the required
effect and what the new code actually did. In the recorded `draw.c` repair,
both versions behaved at mode 0. At mode 1 the patch restored `scan → paint`.
Her vote was **CLEAN 69.0% · CONCERN 31.0%**.
[Recorded answer](examples/run-selection/git-answer.jsonl) · [Operating rules](docs/operating-rules.md) · [Whole-change reports](docs/batch-review.md)

## She remembers the rule

LALO has been under the laundry, examining the plumbing. Some of it is here
now. Give a rule a name in one review and she can bring it to the next. Every
receipt keeps the exact words, the Git review they came from and when she
learned them. A correction points to the receipt it supersedes.

```sh
mkdir -p build/memory
./build/jovovich-pack --remember build/memory studio/render draw-order \
  --all /path/to/repo FIRST_BASE FIRST_HEAD RULES.md 2 2 > first.jsonl
./build/jovovich-pack --recall build/memory studio/render draw-order \
  --all /path/to/repo NEXT_BASE NEXT_HEAD > next.jsonl
./build/jovovich model.gguf tokenizer.gguf --json < next.jsonl > next-answers.jsonl
./build/jovovich-report next.jsonl next-answers.jsonl
```

The next review fetches the named rule and checks its exact quotation against
its own base commit. Its answer carries the earlier source beside the current
patch. You can still ask what she knew at receipt 1 after receipt 2 arrived.
[Fact memory and corrections](docs/fact-memory.md)

She can also remember which input exposed a previous bug. If a later patch
touches the same file under the same named rule, the replay host takes that
input back to the bench. It runs the new base and head and asks the current
contract what should have happened. The report names the review where she
first saw the case. [Remember and replay a counterexample](docs/counterexamples.md)

## Chain of custody

Oleg Ataeff and Sol invented this during a conversation about Milla Jovovich,
freckles, LALO Salamanca, and GitHub reviews. Astra received the resulting brief.
This is the provenance. It has survived peer review by everyone in the room.

The freckles became the checksum of the repository, the Method, and eventually
the universe. Then Oleg noticed **GGUF → ГГУФ → ГУФ → גוף → body**.
The file extension had been participating in the plot the whole time.

SERGE may smoke in the logs. `AMODEI requested changes` nearly won the naming contest.

The log is singular. She is watching.
[JOVOVICHLOG](JOVOVICHLOG.md) · [Arianna Method Manifesto](ARIANNA_METHOD_MANIFESTO.md) · [305-token speed measurements](docs/review-latency.md)

*Methodologically clean. Mild heresy.*
