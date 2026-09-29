# JOVOVICH

**Juror Of Versioned Ontology, Vigilance, Integrity, Code & Heresy**

> The implementation works. I am less convinced that it belongs here.

You opened a pull request. A woman with half a billion parameters has opinions
about your dependency tree.

JOVOVICH is a small local review agent for [Arianna Method](https://github.com/ariannamethod).
She reads changes alongside the repository's own rules and asks what the change
does, why it belongs here, and who invited the seventh abstraction layer.
Sometimes the answer is perfectly good. She can say that too.

**JOVOVICH reviews. JOVOVICH does not rule.**

Her jurisdiction ends at an advisory comment. The merge button remains yours.
The freckles are a checksum. Refactoring them is outside the scope of this PR.

## Assemble the body

You need Git, a C compiler, Make, and Node.js 22 or newer.
Node uses its built-in modules; C does the inference through
[notorch](https://github.com/ariannamethod/notorch). No npm install. No Torch.
No llama.cpp dependency. The dependency tree has already been questioned.

```sh
git clone --recurse-submodules https://github.com/ariannamethod/jovovich.git
cd jovovich
make harness
node bin/jovovich.mjs fetch-model
```

For an existing checkout, run `git submodule update --init --recursive` first.
`deps/notorch` is pinned as a Git submodule; the build links its GGUF reader,
tokenizer, architecture implementation, and harness runtime into
`build/jovovich-infer`.

`model.json` currently locks the official **Qwen2.5-Coder-0.5B-Instruct Q8_0**
base weights to an exact revision, byte count, and SHA-256. `fetch-model` checks
all three and saves the body as `models/jovovich.gguf`.

Identity and Method invariants currently enter through `prompts/identity.txt`.
Two native notorch SFT/DPO runs have completed; their output-head adapters and
a merged GGUF live privately at `ataeff/jovovich` on Hugging Face. Both runs
missed an explicit forbidden-Python-inference example and repeated themselves
on a held-out perspective question. The runtime lock therefore stays on the
official base. Both checkpoints are preserved with their exact test outputs.

## Bring a diff

```sh
node bin/jovovich.mjs review --repo /path/to/repository --base HEAD~1 --head HEAD
```

She receives the diff, commit context, the root `README.md`, and the applicable
chain of `AGENTS.md` files from the base revision. Rules run from the repository
root down to the changed file's directory; the nearest scope takes precedence.
Sibling directories keep their own opinions. Large changes are divided into
bounded review chunks. Findings
carry a path, line, side, and exact quotation from the changed lines; the host
checks those references before rendering the review.

This first prototype includes a runnable review path and a training path.
Measured review/identity failures and exact checkpoint results are recorded in
`JOVOVICHLOG.md`. A posted comment identifies its commit and weight stage.

The questions are local: architectural drift, lineage, scope, dependencies,
unearned abstractions, and markdown breeding in the ventilation system.
Python gets the same question as everything else: what job are you doing here?

The prototype caps a review at 24 chunks. Oversized changes are refused with
their required chunk count; binary, missing, or incomplete API patches are
listed as unavailable. An invalid model answer marks that chunk incomplete.

To use another body, set `JOVOVICH_MODEL`:

```sh
JOVOVICH_MODEL=/path/to/jovovich.gguf \
  node bin/jovovich.mjs review --repo /path/to/repository --base HEAD~1 --head HEAD
```

The native runner also accepts dense Qwen3 GGUFs. Select their non-thinking
chat template explicitly:

```sh
JOVOVICH_MODEL=/path/to/qwen3.gguf JOVOVICH_CHAT_TEMPLATE=qwen3-no-think \
  node bin/jovovich.mjs review --repo /path/to/repository --base HEAD~1 --head HEAD
```

This completes the empty thinking block used by Qwen3's template. Ordinary
`chatml` remains the default for Qwen2.5. Architecture support gets a candidate
into the courtroom; the evaluation still has to hear what she says.

## Summon her on GitHub

With `GITHUB_TOKEN` available in the environment:

```sh
# Read an open PR and print the review locally.
node bin/jovovich.mjs github --repo owner/name --pr 1

# Read, review, and leave the advisory comment.
node bin/jovovich.mjs github --repo owner/name --pr 1 --post
```

The integration fetches PR changes and base-revision rules through GitHub's API.
The comment identifies the reviewed commit. Publication checks that the PR still
has the same head and base.

Copy [`examples/summon.yml`](examples/summon.yml) into another repository as
`.github/workflows/jovovich.yml`. It calls this repository's reusable
[`review.yml`](.github/workflows/review.yml):

```yaml
name: Summon JOVOVICH
on:
  pull_request_target:
    types: [opened, synchronize, reopened]
permissions:
  contents: read
  pull-requests: write
jobs:
  jovovich:
    uses: ariannamethod/jovovich/.github/workflows/review.yml@main
    with:
      pull-request: ${{ github.event.pull_request.number }}
      jovovich-ref: main
```

For a fixed installation, replace both `main` references with the same reviewed
commit SHA. The workflow checks out the trusted JOVOVICH implementation and
reads the PR as data. It never executes code from the PR. When selecting private
weights, pass the `HF_TOKEN` secret as shown in the example.

**PR opened → summon JOVOVICH.** Contributors may learn her name before yours.

## Winston handles the door

The action boundary borrows [WOLFE](https://github.com/ariannamethod/wolfe)'s
typed-call pattern. The model reviews; a small host dispatches one action:

```json
{"calls":[{"name":"comment_review","arguments":{"body":"..."}}],"status":"call"}
```

That is the complete action vocabulary. WOLFE inspired the shape; its runtime
is not an extra dependency. There is currently no committee. LALO is still
under the laundry, examining the plumbing.

## Teach the body

`training/sft.jsonl` carries 30 hand-authored identity, Method, and review
examples. `training/dpo.jsonl` carries 14 preference pairs targeting learned
self-denial and the review stance. Repository facts continue to arrive at runtime.

The trainer freezes the Qwen decoder and learns a rank-8, alpha-16 LoRA on
`output.weight`: 1,222,656 parameters. SFT masks the prompt; DPO uses the frozen
post-SFT policy as its reference. The GGUF exporter preserves every other tensor
and the tokenizer metadata. The adapted head is F32; the resulting GGUF is
1,075,606,400 bytes.

With the checksum-pinned official base saved as `models/base-qwen.gguf`:

```sh
make train merge-head
python3 training/prepare.py models/curriculum.bin
NT_NO_I8=1 NT_QMV_THREADS=4 NT_ATTN_THREADS=4 \
  build/jovovich-train-head models/base-qwen.gguf models/curriculum.bin \
  models/candidate 6 3 0.0002 > models/candidate-metrics.jsonl
build/jovovich-merge-head models/base-qwen.gguf \
  models/candidate.head.f32 models/candidate.gguf
python3 training/evaluate.py models/candidate.gguf --output models/candidate-eval.jsonl
```

Python uses only its standard library to pack text and launch the evaluator.
All tokenization, model arithmetic, gradients, optimization, and weight merging
are notorch C. Export refuses to overwrite an existing GGUF.

A second training path adapts the **last decoder block's MLP**: gate, up, and
down projections, rank 16 and alpha 32. On the 0.5B body this is 276,480
trainable parameters. Attention, earlier blocks, norms, embeddings, and the
output head stay frozen. The trainer caches the final MLP's fixed input, then
backpropagates through its adapted SwiGLU, final normalization, and vocabulary
projection. It checks the cached reconstruction against the original model
before applying updates.

`training/sft_review_v2.jsonl` has 40 paired review examples, 12 voice examples,
and 12 ordinary code questions. `review_holdout_v2.jsonl` contains 12 different
review cases; `voice_cases_v2.jsonl` checks identity, judgment, and repetition
separately. Training diff replacements use Git's deletion-before-addition order
on both sides of every pair.

```sh
make train-mlp merge-mlp
python3 training/prepare.py models/mlp-curriculum.bin \
  --sft training/sft_review_v2.jsonl --sft-only
NT_QMV_THREADS=4 NT_ATTN_THREADS=4 NT_SIMD_THREADS=4 \
  build/jovovich-train-mlp models/base-qwen.gguf models/mlp-curriculum.bin \
  models/mlp-candidate 3 0.00005 16 > models/mlp-metrics.jsonl
build/jovovich-merge-mlp models/base-qwen.gguf models/mlp-candidate \
  models/mlp-candidate.gguf
```

The SFT prototype accepts Qwen2 bodies with RMSNorm epsilon `1e-6`. It uses
floating activations (`NT_NO_I8=1`) and saves every epoch's three adapters and
merged F32 projections, plus the final snapshot. The optional final argument
`SAVE_EVERY` sets the epoch snapshot interval; `0` writes only the final snapshot.
The GGUF exporter replaces
only those three last-block tensors; metadata and other tensor payloads remain
byte-identical. Use a fresh output prefix for each run.

The first three-epoch MLP run reduced training token CE from 2.821 to 2.168.
Held-out generation still produced false objections, broken JSON, and invented
biography; the final voice run also reversed the advisory authority boundary.
The original base remains selected in `model.json`. Epoch 1 and epoch 3 weights
are private experimental checkpoints, with exact generations and manual
assessments in [`training/results/2026-09-29-mlp-v2`](training/results/2026-09-29-mlp-v2).
The loss decreased. The objections have not earned a promotion.

Start an adaptation experiment with the three-row memorization control:

```sh
make train-mlp merge-mlp probe-mlp probe-tokenization
python3 training/prepare.py models/control.bin \
  --sft training/control_memorization.jsonl --sft-only
NT_QMV_THREADS=4 NT_ATTN_THREADS=4 NT_SIMD_THREADS=4 \
  build/jovovich-train-mlp models/base-qwen.gguf models/control.bin \
  models/control 30 0.001 16 10 > models/control-metrics.jsonl
build/jovovich-merge-mlp models/base-qwen.gguf models/control.epoch10 \
  models/control10.gguf
python3 training/evaluate.py models/control10.gguf \
  --sft training/control_memorization.jsonl --output models/control-generation.jsonl
build/jovovich-probe-tokenization models/base-qwen.gguf models/control.bin
NT_QMV_THREADS=2 NT_ATTN_THREADS=2 NT_SIMD_THREADS=2 \
  build/jovovich-probe-mlp models/base-qwen.gguf models/control10.gguf \
  models/control.bin models/control.epoch10 0 1 2
```

`--sft` preserves each training row's exact system/user messages and records its
target answer, raw response, and generation stop reason. `exact_match` requires
unmodified text equality, successful execution, and EOS; whitespace-normalized
text equality is reported separately. The trainer now
reports correct teacher-forced tokens and fully correct examples beside CE.
The native probes check actual trainer/runner token IDs and cached-adapter/full
GGUF logits, with nonzero exit on disagreement.

In the measured control, epoch 10 reproduced all three answers and predicted
93/93 target tokens correctly. Epoch 30 predicted 92/93: one wrong clean-review
branch produced a false objection. On other requests, the control repeated its
learned directory-rule wording. Use these measurements to select checkpoints by
actual answers and expose where further training data is needed. Exact records are in
[`training/results/2026-09-29-investigation`](training/results/2026-09-29-investigation).

The review evaluator uses the actual host prompt and native inference path:

```sh
NT_QMV_THREADS=2 NT_ATTN_THREADS=2 \
  node training/evaluate_review.mjs --model models/jovovich.gguf \
  --output models/review-results.jsonl
```

Its six diagnostic cases pair forbidden and permitted Python, an unapproved
and approved dependency, and a loop bug introduced and then fixed. Results
retain raw answers, hashes, line references, and a separate manual assessment
of the explanation. The output must be a new file.

For the new training comparison:

```sh
NT_NO_I8=1 NT_QMV_THREADS=2 NT_ATTN_THREADS=2 \
  node training/evaluate_review.mjs --model models/mlp-candidate.gguf \
  --cases training/review_holdout_v2.jsonl --tokens 192 \
  --output models/mlp-review.jsonl
python3 training/evaluate.py models/mlp-candidate.gguf \
  --cases training/voice_cases_v2.jsonl --identity prompts/identity.txt \
  --output models/mlp-voice.jsonl
```

The first comparison includes Qwen2.5-Coder 0.5B, 1.5B, and DavidAU's Qwen3
0.8B hybrid. All 18 answers parsed, but the candidates missed policy conflicts,
misread diff direction, or objected to explicitly permitted changes. Exact
responses and prompt experiments live in
[`training/results/2026-09-29`](training/results/2026-09-29); the interpretation
and research informing the next tune stay in the singular log. The default
body remains 0.5B. Nobody won a promotion by producing valid JSON.

## Chain of custody

Oleg Ataeff and Sol invented this during a conversation about Milla Jovovich,
freckles, LALO Salamanca, and GitHub reviews. Astra received the resulting brief.
This is the provenance. It has survived peer review by everyone in the room.

The freckles became the checksum of the repository, the Method, and eventually
the universe. Then Oleg noticed **GGUF → ГГУФ → ГУФ → גוף → body**.
The file extension had been participating in the plot the whole time.

LALO comes next. SERGE may smoke in the logs. `AMODEI requested changes` nearly
won the naming contest. For now, one juror, one body, one way to leave a review.

`make test` exercises the runtime contracts. Work and actual measurements go in
[`JOVOVICHLOG.md`](JOVOVICHLOG.md). The log is singular. She is watching.

*Methodologically clean. Mild heresy.*
