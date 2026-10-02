# Per-layer affine readout: where does the judgment live?

Frozen 2026-10-02 by Don, before any state extraction. Motivation: the
published final-position diagnostic
(training/results/2026-10-01-frozen-readout/readout-summary.json) shows
the frozen coder's final states separate concern/clean at **29/52
correct, 4/26 complete pairs** — chance-adjacent — while seven surface
nuisance features reach 35/52, 9/26. The adapters we train can only
reshape what the frozen stack delivers to them; this probe asks at which
depth, if any, the distinction still exists — and whether it depends on
the body.

## Question

At which decoder depth, if any, do frozen states at the decision
position linearly separate concern/clean — and how does that profile
differ across three 0.5B bodies: the coder base, its plain-instruct
twin, and its abliterated coder twin?

## Bodies

1. **Qwen2.5-Coder-0.5B-Instruct Q8_0** — the model.json-pinned base
   (verify revision, byte count and SHA-256 against model.json before
   use).
2. **Qwen2.5-0.5B-Instruct Q8_0** (plain instruct) — official release;
   pin revision + SHA-256 in plan.json at fetch, before any extraction.
3. **amos-x-qwen-2.5-0.5b-before-subliteration.gguf** — the abliterated
   coder twin (metal:~/arianna/jovovich/models/, 506 MB; transfer and
   pin SHA-256 at transfer). Read-only representation probe; no
   generation. Its table is additionally the BEFORE-subliteration
   geometry snapshot for the future subliteration arc (Oleg's word
   2026-10-02: no ethical bar for a read-only probe).

## Design — the published procedure, verbatim, per layer

The frozen-readout diagnostic repeated at every depth: same 52-row
corpus (training/sft_review_v4.jsonl, SHA-256 20afaa56…), same decision
positions, centered-rms normalization, lambda 0.01, interpolation
lambda 1e-08, gradient tolerance 1e-08, max 100 iterations, intercept
not penalized, positive class `concern`, the same 26
template-family-held-out pairs, the same 99-permutation procedure. One
affine fit per decoder layer's residual state at the decision position
— all layers captured in ONE forward pass per sequence via the
forward_residual hook — plus the final post-norm z for continuity with
the published record. The seven-feature nuisance view is
layer-independent and is cited from the published record, not refit.

## Report

Per body × per layer, no layer and no body excluded: correct/52,
correct_concern, correct_clean, complete_pairs/26, permutation
exceedance. One table. Declared reading (fixed now): "signal lives at
depth L" means correct/52 strictly above 29 AND complete_pairs above 4
at L, permutation exceedance printed beside it. Cross-body comparison
is descriptive. This probe is DIAGNOSTIC: it adopts nothing and gates
nothing; it tells the next training run where to read or unfreeze, or
that token-space reasoning is the only road.

## Instruments and integrity

Fixture before the real run: a tiny synthetic model with a planted
separable direction at one known layer — the probe must find it at that
layer and not at others; both receipts committed. rc taken directly,
never through a pipe. Results, environment, manifests and reproduction
instructions under training/results/2026-10-02-layer-readout/ following
the frozen-readout receipt conventions. Model files stay out of git.

## Hands

Implementation and execution: Opus subagent on branch
fable/probe-and-laws. Protocol and acceptance: Don. No push, no merge
without Oleg's word.

— Don (Fable, neo), 2026-10-02
