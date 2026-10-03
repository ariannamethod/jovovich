# Quote-first arm: preregistration

Frozen 2026-10-03, about 18:55 UTC. At that moment this arm had neither trained
nor generated anything, and the explanation-order experiment had no
evaluation result. The visible state of that experiment was the before arm
archived through update 36
(`training/results/2026-10-03-diagnostic-binding/latest-training-receipt.json`
at `7b03bc7`), with no generation and no score. Its training metrics were not
read before this freeze.

## Question

With the same prompts, explanations and findings as the explanation-first arm
(`before`), does opening the analysis with a verbatim copy of the applicable
rule raise the number of fully grounded complete review pairs?

## Mechanism

The per-layer readout found no depth of the frozen stack where concern and
clean separate at the decision position, so the judgment has to be carried by
generated tokens. Copying a span from context is something a 0.5B model does
reliably. A verbatim copy of the rule puts the protective property directly in
front of the tokens that decide. In 6 of the 26 pairs the two members' nearest
rules differ, and the copy itself carries the distinction. In the other 20 the
rule is shared and the distinction stays in the explanation that follows.

## The arm

Exactly one variable against `before`:
`analysis = "Rule: " + evidence.rule + " " + <before analysis>`.

| Input | SHA-256 |
| --- | --- |
| `training/sft_review_v6_before.jsonl` | `a2f22e789b176b1f23ed1262b3e94449819a1484ed31ddb87c3dbedbb8574250` |
| `training/explanations/reasons.json` | `c2269304dea5dbe65a42308116a51b383d9a535ec47fca7cedd122136c670e45` |
| `training/quote/build.mjs` | `7d4ea2087f9a187b2faf2b6d9afb99c1134636a2151da78e7d60b0a015fecd16` |
| `training/sft_review_v7_quote.jsonl` (76 rows, 186132 bytes) | `43d85910640550abc48685347f11644a9c3e086dbb083de1e16f1fbbd59d60f7` |

`evidence.rule` occurs once in each prompt, inside the rules block, in all 52
review rows. It is 68 to 136 characters and needs no JSON escaping. Rebuilt
without the transform, `build.mjs` reproduces `sft_review_v6_before.jsonl`
byte for byte. The quote corpus keeps 24 rows identical, and the other 52
differ only in analysis, by the exact prefix.

Native preflight (`preflight.json`, pinned base `e1a77721…`):

- JVPR2 passes on all 52 rows, with the same prompt token counts and the same
  verdict target and alternative IDs as `before` (66582/8899).
- Decision positions are 55–88, against 40–58 for `before`.
- Residual tokens are 4412 against 3411. The extra 1001 are the copied rules,
  29% more residual tokens; this is the manipulation. The joint objective
  averages decision and residual cross-entropy separately, so the weight of
  the decision term does not change.
- The longest answer is 123 tokens including EOS, and the longest sequence is
  693 tokens. The trainer cap is 4096 and the generation budget is 512.

## Training

The arm uses `training` from `training/explanations/plan.json` (`70ccfe23…`)
unchanged, with only the dataset replaced:

- Base: Qwen2.5-Coder-0.5B-Instruct Q8_0 (`e1a77721…`).
- Trainer: `train_mlp.c` in joint mode with λ = 1, optimized with
  `nt_tape_chuck_step` for 100 updates at lr 1e-4, with gradient clip 1 and
  40-token microbatches.
- Adapter: rank 16, alpha 32, on the final MLP's gate, up and down projections
  (276,480 parameters), seed 20260929.
- Environment, saved updates and checkpoint: the frozen native environment,
  saved updates 25/50/75/100, and update 100 as the primary checkpoint.

Initialization binds to the before arm's gate0 LoRA hashes, exactly as the
after arm does. One training process runs at a time, after the two existing
arms. The archived launcher prepares two arms (`prepare_launches.py`).
Extending it to a third is a separate declared step, and that step may not
change any setting listed here.

## Evaluation

The arm uses `primary_evaluation` from `plan.json` and
`training/explanations/evaluation_plan.json` (`84c547e6…` at `7b03bc7`)
unchanged:

- Prompts: the common v6 prompt extension, decoded at temperature 0 with 512
  continuation tokens.
- Splits: train has 52 rows and 26 pairs. `training/review_holdout_v5.jsonl`
  (`e066e033…`) has 24 rows and 12 pairs.
- Scoring: the full-review rubric and every separate count.

`quote_update100` is compared with `before_update100` in one judging pass over
both models' responses and the base, under opaque labels. The mapping is
revealed only after adjudication. The before responses are the archived ones
in `ataeff/jovovich`. If they are regenerated, they must match byte for byte.

## Decision rule

The primary measure is fully grounded complete pairs on heldout_v5, out of 12,
counted paired as quote-only, before-only, both and neither.

- **Supports:** quote-only − before-only ≥ 2 and a manipulation check of at
  least 20/24 on heldout.
- **Against:** before-only − quote-only ≥ 2.
- **Unresolved at n = 12:** any other outcome, reported in those words.
- **Manipulation failed:** fewer than 20/24 heldout generations pass the
  manipulation check. That outcome is reported as such and is not evidence
  about quoting either way.

The train split is reported but does not decide, because it measures
memorized rows.

**Manipulation check.** The generated analysis begins with `Rule: `, followed
by a verbatim substring of at least 40 characters from its own prompt's rules
block. Reported separately: whether the copied span lies in the decisive scope
(train: inside `evidence.rule`; heldout: read by the judges).

**Secondary.** The `separate_counts` of `plan.json` unchanged, plus decision
position and generated length per response.

## Launch brief

1. Organism: JOVOVICH.
2. Dataset: `training/sft_review_v7_quote.jsonl`, 76 rows (52 review, 24
   nonreview), 186132 bytes, `43d85910…`.
3. Steps: 100 Chuck updates. Each update accumulates the full set: 52 decision
   and 4412 residual positions. lr 1e-4.
4. Architecture: Qwen2.5-Coder-0.5B-Instruct Q8_0, frozen, with its
   151,936-token BPE vocabulary. LoRA r16/α32 on the final decoder MLP (gate,
   up, down), 276,480 trainable parameters.
5. Tokenizer: the GGUF's own BPE through notorch, the same in trainer and
   runtime; the native preflight compares both.
6. Script: `training/train_mlp.c` through the archived launcher. The
   three-arm launcher change must be pushed before launch.
