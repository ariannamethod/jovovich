# First voice audition and a decision challenger

Use the original OneJev for the official review. The voice receives the resulting file verdict, both probabilities and the verified observation, plus a short description of the probe input. Write the voice references separately. The object under review should give the line its occasion. Each target is an original English remark written for this audition. Repository prose supplies no style targets.

## Voice

Train on the repair and reversal of six previously measured fixes from the threshold panel: cJSON #810, ms #111, Underscore #3018, PapaParse #1124 and #1128, and npm/ini #252. Hold out both directions of three Arianna Method changes at independently pinned revisions:

- NoTorch #185, a NUL inside an encoder input row.
- AML #45, a semicolon in a BLOOD LINK flag.
- JOVOVICH #46, a changed submodule pin in a repository configured to hide submodule changes.

Use a second pass through frozen OneJev for the remark. Fit only a sparse additive output adapter on tokens found in the twelve targets, including the end of the turn. Use teacher-forced full-vocabulary cross-entropy, 32 fixed projected residual features and a bias per selected output token, 200 full-batch SGD updates at 0.25 and weight decay 0.002. The ordinary review keeps its original scores. Compare greedy open-vocabulary continuations with and without the adapter at the same 32-token cap, and report reference NLL on each split. Count complete, factually faithful, verdict-compatible remarks on the six held-out reviews by reading the actual generations. Keep both sets of raw outputs. A candidate for live use needs six faithful, complete remarks, no repeated lines and a blind preference from Oleg about the voice.

## Liquid d1-omni-600M

Screen the pinned Liquid checkpoint 02b55d7076f15129e59ab3f94783f32c4b088674 on the already published eight pairs in threshold-transfer. Use the unmodified upstream CPU float32 implementation and the shipped temperature for a two-option choice. Pass the same review state, question and option descriptions as OneJev. Use source alone and the admitted execution for both directions. Repeat with the two named options exchanged. Use the ordinary argmax in each order. Count correct decisions, complete pairs, false alarms, misses and verdict flips after reordering. Verify every shared run has the same effective state as source. No threshold fitting on this panel. The screen decides whether to take Liquid to a fresh panel, with the current OneJev release as the production reference.
