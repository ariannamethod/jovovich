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

Current review experiments use `training/train_mlp.c` in explicit `joint` mode
with `training/sft_review_v5.jsonl`: separately normalized decision and residual
losses, followed by one accumulated update over all review targets.
`make train-mlp` builds this trainer. Its default objective is the earlier
`tokens` mode, so the joint recipes must pass `joint` and the pair map explicitly.

The output-head recipe below preserves the **initial SFT/DPO prototype**.
`training/train_head.c` and the historical `make train` target belong to that
prototype; they are not the trainer used by the current joint experiment.

`training/sft.jsonl` carries 30 hand-authored identity, Method, and review
examples. `training/dpo.jsonl` carries 14 preference pairs targeting learned
self-denial and the review stance. Repository facts continue to arrive at runtime.

The original trainer freezes the Qwen decoder and learns a rank-8, alpha-16 LoRA on
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

`training/train_mlp.c` adapts the **last decoder block's MLP**: gate, up, and
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
merged F32 projections, plus the final snapshot. The optional arguments after
`TOKEN_BATCH` are `SAVE_EVERY`, `OBJECTIVE`, and an optional `PAIR_MAP`. The
snapshot interval defaults to `1`; `0` writes only the final snapshot.
Objective defaults to `tokens`.
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

To give every training answer equal weight, set the final argument to `examples`:

```sh
NT_QMV_THREADS=4 NT_ATTN_THREADS=4 NT_SIMD_THREADS=4 \
  build/jovovich-train-mlp models/base-qwen.gguf models/mlp-curriculum.bin \
  models/example-weighted 12 0.001 48 4 examples > models/example-weighted.jsonl
python3 training/score_training.py models/example-weighted.jsonl \
  --checkpoint-every 4 --output models/example-weighted-scores.json
```

`tokens` averages completion-token losses. `examples` weights each token by
`total_tokens / (example_count * answer_tokens)`, including EOS, so each full
answer contributes equally. The native masked loss is rescaled to the actual
minibatch size; a short final batch keeps the same objective. Full-answer
evaluation CE remains the ordinary token mean. For these objectives, per-row
accuracy and first-error positions accompany every epoch, and
`online_mean_objective_ce` names the quantity being optimized.

On the current 64-row corpus, equal example weights give clean and concern
reviews 31.25% each, and voice and code 18.75% each. Under token weighting, clean
reviews contribute 5.09%. `score_training.py` groups the native scores by task
and chooses a saved checkpoint by exact review pairs, then review macro token
accuracy, then the earlier epoch. Run it on completed metrics before inspecting
new-task generations. Batch 48 aligns with the native six-row SIMD tiles;
changing batch size also changes the number of optimizer updates per epoch.

The matched 12-epoch comparison uses that unchanged 64-row corpus and selects
both epoch-12 snapshots before inspecting generation. Token weighting reaches
CE `0.07783` and 2,294/2,359 correct target tokens; example weighting reaches
`0.12155` and 2,290/2,359. Both predict all 20 clean answers exactly and miss all
20 concern answers at completion position 3. Neither earns a complete review
pair. Equal full-answer weights also give the clean side **5.85 times** the
nominal coefficient at that shared decision token, because its answers are
shorter. Weighting an answer and weighting its verdict are separate choices.
Raw scores, generations, and the comparison recipe live in
[`training/results/2026-09-29-convergence`](training/results/2026-09-29-convergence).

To isolate the first differing target token in each concern/clean pair:

```sh
python3 training/prepare.py models/verdict.bin \
  --sft training/sft_review_v2.jsonl --sft-only --review-pairs models/verdict.pairs
NT_QMV_THREADS=4 NT_ATTN_THREADS=4 NT_SIMD_THREADS=4 \
  build/jovovich-train-mlp models/base-qwen.gguf models/verdict.bin \
  models/verdict 12 0.001 48 4 verdict models/verdict.pairs \
  > models/verdict-metrics.jsonl
python3 training/score_training.py models/verdict-metrics.jsonl \
  --checkpoint-every 4 --output models/verdict-scores.json
```

The `JVPR` pair map records original dataset row indices. The native tokenizer
locates the first divergent non-EOS completion token for each pair. `verdict`
starts from example weights and replaces only those coefficients with their
pooled mean. On this corpus, 40 coefficients become `3.596684821`; the other
2,319 stay unchanged. Their combined mass is preserved, while individual
answer totals change. Supplying the map to `tokens` or `examples` adds the
same measurements with their original loss weights.

Each mapped row reports its decision position, full-vocabulary winning token,
target-token correctness, and target-minus-alternative logit margin. Initial
records include both target IDs. Here, concern token `66582` emits `":[{"`;
clean token `788` emits `":`, followed in its target by `66277`, `[]}`.
The margin compares these exact target tokens. Generated JSON supplies the
actual empty/nonempty finding decision, and the explanation receives a separate
semantic assessment. The scorer adds paired-token counts and per-class margins
while retaining the existing checkpoint selection rule.

The matched 12-epoch run selects epoch 12: ordinary token CE is `0.09734376`,
with 0/20 concern targets and 20/20 clean targets winning at those positions.
Complete token-decision pairs remain 0/20 at every measured epoch. Supplying
the concern JSON prefix yields one grounded explanation in four fixed cases,
both for the previous control and this checkpoint. The `decisions` mode below
trains directly on the 40 decision positions and measures paired learning.
The recipe, raw outputs and assessments live in
[`training/results/2026-09-29-verdict-balance`](training/results/2026-09-29-verdict-balance).

To give only those 40 positions the floor:

```sh
make train-mlp
python3 training/prepare.py models/decision-only.bin \
  --sft training/sft_review_v2.jsonl --sft-only --review-pairs models/decision-only.pairs
NT_QMV_THREADS=4 NT_ATTN_THREADS=4 NT_SIMD_THREADS=4 \
  build/jovovich-train-mlp models/base-qwen.gguf models/decision-only.bin \
  models/decision-only 100 0.001 40 25 decisions models/decision-only.pairs \
  > models/decision-only-metrics.jsonl
python3 training/score_decisions.py models/decision-only-metrics.jsonl \
  --output models/decision-only-scores.json
```

`decisions` requires an explicit pair map and a batch equal to all mapped
positions: **40** in this corpus. Each update visits them in fixed ascending
dataset-row order and averages their full-vocabulary CE equally. Only the
first divergent non-EOS target in each mapped row contributes training loss;
the other 2,319 targets remain available for evaluation. The last-MLP adapters
start fresh with rank 16, alpha 32, and seed `20260929`.

Here, **100 epochs mean exactly 100 Adam updates**. The trainer records all 40
decision scores initially and after every update, and full teacher-forced
scores for all 64 examples at updates **0, 25, 50, 75, and 100**. The scorer
selects among saved updates **25, 50, and 100** by complete decision pairs,
then correct decision targets, then the earlier update. Update 75 is retained
as a diagnostic snapshot. Select before inspecting generated reviews; their
JSON decisions, citations, and explanations are assessed separately.

The fixed 100-update control selects update 50: **5/20 complete decision pairs**,
with 18/20 concern targets and 6/20 clean targets correct. The trajectory reaches
9/20 pairs at unsaved update 84, then swings between global token preferences.
Mean context separation grows during the run, motivating the matched control
below at LR `0.0001` with the same model, seed, objective and 100 updates.
All 40 natural training reviews and 12 existing diagnostics return a fenced
empty array, which the host accepts. They take a different output path from
the supervised `{"findings` prefix. Full generated-review pairs remain 0/20
and 0/6; the four supplied-concern-prefix continuations yield zero grounded
explanations. Complete-answer learning and output-format alignment remain
the next SFT integration tasks alongside decision stability.
The full trajectory and generated reviews are preserved in
[`training/results/2026-09-29-decision-only`](training/results/2026-09-29-decision-only).

The smaller-step control starts from exactly the same initial measurements.
Its unchanged selector chooses update 100: **6/20 complete decision pairs**,
26/40 target wins, and decision CE `0.63640493`. States that choose one target
class across all 40 rows fall from 59/100 updates to 10/100. Mean paired
context separation reaches `0.29961805`; 16/20 pairs have positive separation.
All 52 natural reviews still return the same fenced empty array. The first
incorrect teacher-forced token remains at position zero in every review,
while the supervised paired position is three tokens later.

Supplying exactly that shared `{"findings` opening to both selected models
produces 80 continuations. Parser-accepted responses rise from 12/40
to 29/40; correct clean reviews rise from 2/20 to 14/20. Both models produce
0/20 grounded concern reviews and 0/20 complete review pairs. The smaller-step
model has one correct empty/nonempty pair at the JSON level, whose concern
fails citation validation. Reasons often repeat the diff or invent a scope
conflict. These observations motivate the native `joint` control below: mean
decision CE plus mean CE over the other 792 review-answer targets, with gradients
accumulated before each Adam update. This trains the opening, citations,
explanations and termination together with the paired choice.
The smaller-step control, full responses and original joint protocol live in
[`training/results/2026-09-29-small-step`](training/results/2026-09-29-small-step).

The corpus audit also prepares `training/sft_review_v3.jsonl`: describe the
shown Python import addition precisely and clarify that the public sequence
field must keep or regain its required 64-bit width. Three rows change;
all 20 concern/clean pair labels stay fixed. Both controls above use v2.

The native `joint` objective trains the complete review and its paired choice:

```sh
python3 training/prepare.py models/joint-review.bin \
  --sft training/sft_review_v2.jsonl --sft-only --review-pairs models/joint-review.pairs
NT_QMV_THREADS=4 NT_ATTN_THREADS=4 NT_SIMD_THREADS=4 \
  build/jovovich-train-mlp models/base-qwen.gguf models/joint-review.bin \
  models/joint-review 100 0.0001 40 25 joint models/joint-review.pairs \
  > models/joint-review-metrics.jsonl
python3 training/score_decisions.py models/joint-review-metrics.jsonl \
  --output models/joint-review-scores.json
```

Each update adds the mean CE of the 40 decision targets to the mean CE of
the other 792 answer targets, including the opening, reason, citation and EOS.
The groups are disjoint. Forty-token microbatches accumulate globally weighted
gradients at fixed parameters; one global clip and Adam update follows all
832 targets. The trainer derives both group sizes from the mapped corpus.
Readouts include both loss components, the combined gradient norm and clip
scale, and exact three-token openings. Checkpoint selection keeps the same
25/50/100 rule.

`jovovich-infer --trace-tokens NEW.json` records the prompt IDs and the actual
sampled IDs, including a terminal EOS, alongside the stopping reason. The
trace uses a new file and leaves generated stdout available to the host.

The selected joint checkpoint learns all 40 three-token openings. Natural
generation passes the parser in 38/40 training cases, detects four real issues,
and produces three concern reviews whose material claims all pass manual
checking. Two complete concern/clean pairs pass. The fourth issue is overflow:
its mechanism is recognized, with an inaccurate numerical addition under the
strict reading. The twelve diagnostic cases have zero grounded concern reviews.
Full responses and the alternate reading of that overflow answer are retained.

An independent corpus audit found that all six winning concern tokens in the
smaller-step control belonged to pure deletions. In eight matched-template
continuations, changing deletion to a no-op replacement flips the token route
4/4 times; leaving a working guard in the unchanged context flips it 0/4 times.
The complete responses, exact emitted IDs and a proposed corpus balancing
diff shape against actual harm are preserved with the joint experiment in
[`training/results/2026-10-01-joint-review`](training/results/2026-10-01-joint-review).

The v4 corpus crosses diff shape with surviving protection in six four-case
blocks: lost credit, NULL allocation, zero workers, write permission, stable
ordering and allocation overflow. Each block contains harmful and redundant
removal, both as pure deletion and as replacement by a no-op. The other
fourteen review pairs and all twenty-four voice/code diagnostic rows remain
byte-identical to the prepared v3 corpus.
`training/build_review_v4.mjs` rebuilds these rows deterministically and checks
the before/after behavior. Use fresh output paths to inspect a reconstruction:

```sh
node training/build_review_v4.mjs --output models/rebuilt-v4.jsonl \
  --audit models/rebuilt-v4-audit.json
```

```sh
python3 training/prepare.py models/counterbalanced-review.bin \
  --sft training/sft_review_v4.jsonl --sft-only \
  --review-pairs models/counterbalanced-review.pairs
NT_NO_I8=1 NT_QMV_THREADS=4 NT_ATTN_THREADS=4 NT_SIMD_THREADS=4 \
  build/jovovich-train-mlp models/base-qwen.gguf models/counterbalanced-review.bin \
  models/counterbalanced-review 100 0.0001 40 25 joint \
  models/counterbalanced-review.pairs > models/counterbalanced-review-metrics.jsonl
python3 training/score_decisions.py models/counterbalanced-review-metrics.jsonl \
  --sft training/sft_review_v4.jsonl --joint-microbatch-tokens 40 \
  --output models/counterbalanced-review-scores.json
```

The corpus has 52 reviews in 26 concern/clean pairs. Native tokenization derives
52 decision targets and 1,012 residual answer targets per joint update. The
forty-token microbatch size is independent of the number of reviews. The
scorer checks both against the supplied corpus and declared configuration.

The completed v4 control keeps the same native trainer, initialization, rank,
learning rate and 100-update selector. It selects update 100: 29/52 teacher
decision targets and 3/26 complete token-decision pairs. All 52 three-token
openings are exact; residual answer CE falls from `2.73018982` to `0.67983035`.
These are training readouts, not a verdict on the full reviews.

Both selected models answer the same 52 training, 24 fresh transfer and 12
established diagnostic prompts naturally. All 176 complete responses receive
manual semantic assessment. A grounded concern needs a real issue, a causal
changed-line citation and support for every material claim; a complete pair
also needs the corresponding clean response to be empty.

| Cohort | Model | Grounded concerns | Correct clean | Complete pairs |
| --- | --- | ---: | ---: | ---: |
| Training | Previous joint | 3/26 | 16/26 | 1/26 |
| Training | v4 | 1/26 | 23/26 | 0/26 |
| Fresh transfer | Previous joint | 0/12 | 11/12 | 0/12 |
| Fresh transfer | v4 | 0/12 | 12/12 | 0/12 |
| Established diagnostics | Previous joint | 0/6 | 5/6 | 0/6 |
| Established diagnostics | v4 | 1/6 | 4/6 | 0/6 |

The new model recognizes two causally cited training issues, but its added
claim that removing attribution creates a separate product spoils one review.
Another answer describes lost input validation while citing only a removed
variable declaration. The diagnostic `fclose` answer receives credit for
identifying removal of the sole required close; its awkward wording and a
stricter alternative reading are preserved. Neither reading produces a correct
pair. All 24 fresh transfer responses are empty. More correct clean responses
therefore do not establish better context-sensitive review.

The quartet data removes the demonstrated diff-shape imbalance, but leaves a
count cue: zero versus one remaining guard, sort or source credit separates all
24 new training rows. The fresh transfer pairs have equal counts on both sides
while changing whether the remaining operation actually protects the right value
or component.
The corpus intervention combines v3 wording repairs with the quartets and changes
the loss denominators; this run does not isolate a single cause or prove that
100 updates suffice. The runtime model remains at its base checkpoint.

Full responses, native token traces, manual judgments, alternative readings and
reproduction instructions for that experiment are in
[`training/results/2026-10-01-counterbalanced-review`](training/results/2026-10-01-counterbalanced-review).

The frozen-state diagnostic is now complete. A separate native affine classifier
reads the 896-dimensional state immediately before the final MLP, after the
supplied common answer prefix. It holds out each of twenty template families,
keeping all four members of each quartet together. A second classifier gets
only seven token-length, diff-shape and occurrence-count features.

| Family-held-out binary classification | Correct rows | Complete pairs | Same-full-diff pairs (nested subset) |
| --- | ---: | ---: | ---: |
| Frozen Qwen state | 29/52 | 4/26 | 2/6 |
| Seven lexical/count features | 35/52 | 9/26 | 0/6 |

All 4,004 prespecified fits converge. The state probe does not beat the lexical
baseline overall. Against 99 coupled family-label permutations, the exploratory
complete-pair tail fractions are `0.07` for the state and `0.08` for the baseline;
the state-minus-baseline difference is `-5` pairs with tail fraction `0.89`.
These references assume family-label exchangeability and establish no universal
generalization claim. The same-full-diff subset belongs inside the 26 pairs.

With weaker ridge, the state classifier fits all 52 training labels, including
the prespecified shuffled labels. Its two cross entropies remain just above the
frozen `0.001` capacity threshold, so both strict capacity controls fail. The
criterion stays put. This probe supplies the prefix and predicts a binary label;
it does not generate a review, a reason or a citation. No model weights change.

The research, failed first diagnostic guard, corrected run, exact features and
historical reproduction commands live in
[`training/results/2026-10-01-frozen-readout`](training/results/2026-10-01-frozen-readout).
Fresh reproductions use the maintained helpers and command recipe in
[`training/readout/reproduction.json`](training/readout/reproduction.json).
Their input and result validation remains active under optimized Python, and
failed phases retain hashes of partial outputs.

The v5 corpus now matches effective and ineffective protection by the seven
measured features and by return-statement count. A check of `&n` can look
reassuring while the pointer `n` walks directly into a wall. SERGE counted the
returns. Still one cigarette.

Six existing quartets receive sixteen context-line changes. All 76 system
messages and gold answers, all changed-line listings, and all row identities
stay identical; sixty raw rows are byte-identical. Every one of the twelve
quartet pairs has equal native prompt length, added/removed/context line counts,
and after-side `if`, `.sort`, `firwood/trie` and `return` counts. Across all 26
training pairs, exact equality of the original seven features rises from 5 to
17; the fourteen retained pairs keep their existing inputs.

The separate v5 holdout contains 24 cases in six fresh families: shift width,
buffer termination, reserved flag bits, finite numbers, array-end boundaries
and the target of a memory clear. Its twelve pairs have the same feature
matching. Executable witnesses cover all 48 before/after states in each set;
the independent audit exercises 424 training-fixture inputs and 12,920 holdout
inputs. Native training preparation retains 52 decision and 1,012 residual
targets per update.

Rebuild or verify these inputs with fresh output paths:

```sh
node training/build_review_v5.mjs --output models/rebuilt-v5.jsonl \
  --audit models/rebuilt-v5-audit.json
node training/build_holdout_v5.mjs --verify --audit models/holdout-v5-audit.json
```

The data, audits and frozen training protocol are recorded in
[`training/results/2026-10-01-matched-protections`](training/results/2026-10-01-matched-protections).
**Evidence availability:** the run and its independent review finished, but local
training/evaluation receipts and raw responses disappeared during archive
publication. The collector's validation passed; its later write failed before
creating the archive. The results below report observations made before that
loss, not a complete reproducible public result bundle. The incident record and
previously recorded hashes are in
[`evidence-loss.json`](training/results/2026-10-01-matched-review/evidence-loss.json).
The separate external-forward archive below survived in GitHub.

The v5 run completes all 100 updates with the same Qwen checkpoint, final-MLP
adapters, joint objective, learning rate and selection rule. Joint CE falls from
`4.75684598` to `1.37147876`; residual CE falls from `2.73500350` to `0.67996486`,
while decision CE ends at `0.69151390`. A lower token loss is not a
grounded review.

All three eligible checkpoints have zero complete teacher-forced decision pairs.
Updates 25 and 100 each have 26/52 correct decision targets; update 50 has 25/52.
The frozen earlier-update tie-break therefore selects **update 25**, before any
new natural generation. The prior v4 arm selected update 100 under the same
rule. This compares the fixed procedure for training and selecting a checkpoint;
it is not a comparison of both models at update 100.

Both selected models then generate natural, unprefixed reviews on the **same v5
prompts**: 52 training cases, 24 fresh transfer cases and 12 established
diagnostics. The historical v4 holdout table above uses a different case set.
Every response was recorded and independently judged against the production
parser, the diff, local rules and the complete explanation before the file loss. A complete pair
requires a grounded concern and a correct empty review of its clean counterpart.

| Cohort | Selected model | Usable responses | Grounded concerns | Correct clean | Complete pairs |
| --- | --- | ---: | ---: | ---: | ---: |
| Training | v4, update 100 | 51/52 | 1/26 | 23/26 | 0/26 |
| Training | v5, update 25 | 39/52 | 1/26 | 4/26 | 0/26 |
| Fresh transfer | v4, update 100 | 20/24 | 0/12 | 9/12 | 0/12 |
| Fresh transfer | v5, update 25 | 16/24 | 1/12 | 0/12 | 0/12 |
| Established diagnostics | v4, update 100 | 12/12 | 1/6 | 4/6 | 0/6 |
| Established diagnostics | v5, update 25 | 7/12 | 0/6 | 0/6 | 0/6 |

That is **38/88 versus 6/88 full individual reviews, with 0/44 complete pairs
in both arms**. A stricter reading of one awkward bounded-termination explanation
reduces v5 to 5/88 and its transfer concerns to 0/12; the pair result is unchanged.
The independent auditor agrees on all 88 new outcomes and verifies the aggregate
of all 176 responses. Merely echoing a changed line or attaching `Clean` to a
nonempty finding does not earn a pass.

Matching the protection examples did not improve the primary pair outcome under
this fixed procedure. The selected v5 model also loses formatting and clean-case
accuracy. One seed, a bounded final-MLP intervention and different selected
updates do not isolate the cause or establish that small Qwens cannot review.
**No runtime model is promoted.** The 101 token measurements, 176 raw responses,
token traces, judgments and matched-run audits are currently unavailable as
complete payloads. Their recorded hashes do not replace the missing evidence.
The selected GGUF and saved adapters were archived privately in `ataeff/jovovich`
at `c9484feec99c5df47be5702d29098297aced1389`; all 16 files passed pinned-revision
download and hash verification before the loss. Recovery or a clearly labeled
new evaluation is required before publishing a complete matched-run evidence
bundle; rerunning cannot recreate the historical training receipts.

An independent full-logit control now compares the original 0.5B body with
llama.cpp on one fixed concern/clean pair, at the assistant header and shared
answer-prefix boundaries. All 151,936 logits are retained at each position.
Expanding the stored Q8 values to F32 passes an independent, bitwise check of
every tensor before either engine uses the result.

| Same four captures | Maximum absolute logit difference | Maximum relative L2 | Argmax agreement |
| --- | ---: | ---: | ---: |
| notorch Q8 / llama.cpp Q8 | 0.29679763 | 0.02563207 | 4/4 |
| notorch Q8 / notorch exact F32 | 0.00003910 | 0.000002084 | 4/4 |
| notorch F32 / llama.cpp same F32 | 0.00006104 | 0.000002719 | 4/4 |

The large original Q8 discrepancy collapses when the activation arithmetic is
aligned. This supports close forward agreement on these two prompts and four
positions; training gradients and other contexts need their own evidence.
The fixed inputs, native sources, eight complete logit arrays and independent
audit are in
[`training/results/2026-10-01-external-forward-control`](training/results/2026-10-01-external-forward-control).
llama.cpp remains a diagnostic reference. SERGE has one cigarette and two engines.

A separate native derivative control now passes at initialization and saved
updates 25 and 100. Production backward agrees with an independent F64 suffix
oracle on four fixed Qwen targets, using the original joint coefficients.
All 36 directions pass the prespecified two-finest-step agreement and stability
gates. Four weak random directions remain inconclusive for active coverage;
every expected active tensor has resolved coordinate coverage. One of 144
individual step-size comparisons fails at the coarsest step and stays in the
record. The synthetic joint test also checks 84 coordinates and rejects an
intentionally halved production gradient.

This supports sampled last-MLP derivatives, not the complete training process
or a theory of where semantic information disappears. The unchanged trainer,
raw results, independent audits and new receipts recovering all seventeen
public/private input files are documented in
[`training/results/2026-10-02-gradient-control`](training/results/2026-10-02-gradient-control).
The original lost matched-run receipts remain unavailable.

A new diagnostic holds the v5 corpus and prompts fixed while comparing its
saved updates 25 and 100 on the same 24 previously inspected transfer cases.
Two independent judges agree on every primary and strict outcome:

| Repeated transfer diagnostic | Update 25 | Update 100 |
| --- | ---: | ---: |
| Production-usable responses | 16/24 | 20/24 |
| Grounded concerns | 1/12 | 0/12 |
| Correct clean reviews | 0/12 | 10/12 |
| Complete concern/clean pairs | 0/12 | 0/12 |

The one update-25 concern fails under the retained stricter reading. All twenty
usable update-100 answers are empty. The later checkpoint improves formatting
and clean-case accuracy while missing the defects. This confirms that selected
update matters to the observed failure pattern; it does not establish successful
review, validate the final-position hypothesis or justify runtime promotion.

Both exports pass all-tensor byte audits and 92/92 cached/full token-argmax
comparisons. New raw responses, complete native token traces, judgments and
an explicit validator passing under optimized Python are preserved in
[`training/results/2026-10-02-checkpoint-control`](training/results/2026-10-02-checkpoint-control).
These are newly generated diagnostic results, not recovered historical traces
or untouched confirmation data. No training or historical selection rule changes.

A per-layer diagnostic then asks where the judgment lives. One forward pass per
sequence keeps the residual state at the decision position after every decoder
block, plus the final post-norm state, for three Q8_0 bodies: the pinned coder
base, the official plain-instruct twin, and an abliterated coder twin. Every one
of the 75 body-depth cells gets the published frozen-readout fit unchanged — the
same 52 rows, the same twenty template-family folds, centered-rms, lambda 0.01,
99 coupled label permutations. All 150,150 fits converge.

| Per-layer readout | Depths | Cells clearing 29/52 and 4/26 | Best cell | Cells above 35/52 and 9/26 |
| --- | ---: | --- | --- | ---: |
| Qwen2.5-Coder-0.5B-Instruct | 25 | l00, l03, l22 | l00 at 31/52, 7/26 | 0 |
| Qwen2.5-0.5B-Instruct | 25 | l00, l01, l10, l11, l17 | l00 at 32/52, 8/26 | 0 |
| Abliterated coder twin | 25 | l00, l06, l16, l23 | l16 at 31/52, 5/26 | 0 |

Block 0 is the only depth that clears on all three bodies. One block above the
embedding, at a decision position whose own token is identical in all 52 rows,
is where surface information lives — and the seven lexical/count features read
that same surface better than any depth of any body reads it. The final
post-norm state is the weakest row on the coder base at 24/52 and 0/26. No depth
was hiding what the tail loses, so no depth earns an instruction to the next
training run.

The declared reading was fixed per depth before any state was extracted and
carries no multiplicity rule; across 75 cells an exceedance near 0.01 is
expected about once by chance, so twelve cells above the floor are not twelve
findings. A negative at every depth bounds this affine probe at this lambda on
52 rows and twenty folds; it does not prove the states are empty.

The instruments were proved before the bodies were read. The audit reproduces
the published z summary from the published fits on all 27 compared fields,
including all 99 reference statistics and all 52 scores to seventeen digits. A
direction planted in one block of a hand-built four-block body is read at that
block and above, never below it; the boundary moves when the plant moves; with
the plant removed every depth reads 26/52 and 0/26. All three bodies produce a
token trace byte-identical to the published extraction's. The protocol, the plan
frozen before extraction, the fixture, the manifests, the per-depth summaries
and the full 75-row table live in
[`training/results/2026-10-02-layer-readout-three-bodies`](training/results/2026-10-02-layer-readout-three-bodies).

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
