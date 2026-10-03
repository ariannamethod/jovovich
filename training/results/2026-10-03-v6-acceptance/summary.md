# v6 acceptance

Target: `training/sft_review_v6_before.jsonl` (`a2f22e78…`) and
`training/sft_review_v6_after.jsonl` (`d5f3e06e…`), built from
`training/explanations/reasons.json` (`c2269304…`) over
`training/sft_review_v5.jsonl` (`a677211e…`). The acceptance criteria were
fixed before the checker ran; H8v2 is the one declared afterwards, below.

## Checker

`node training/acceptance/v6_check.mjs --out REPORT` → rc 0
(`checker-report.json`).

| Check | Result |
| --- | --- |
| H1 input hashes, reasons bound to v5 | PASS |
| H2 76/76/76 rows, ids, kinds, pairs, order; 52 reasons rows | PASS |
| H3 24 nonreview rows byte-identical to v5 in both arms | PASS |
| H4 strict: review inputs byte-identical to v5 | DEVIATION, 104/104 |
| H4 suffix: system identical, user = v5 user + one shared suffix | PASS, 1 unique delta ×104 |
| H5 findings deep-equal and byte-present; compact JVPR2 markers; class per row; one concern per pair | PASS, 26 pairs |
| H6 key order per arm; analysis equal to reasons and across arms | PASS |
| H7 2–4 sentences | PASS, all 52 have 2 |
| H8 as declared: equal sentence count and equal `[n]` sets | **FAIL, 24/26** — superseded |
| H8v2: per-pair-type parallelism | PASS, same_diff 18/18, mirrored 8/8, sentences 26/26 |
| H9 forbidden shape justifications | PASS, 0 hits |

**H4.** Every review prompt in both arms ends with
`" Include a concise analysis string connecting the relevant rule, changed line and consequence."`
The held-out generation path appends the same text; the production renderer
(`bin/jovovich.mjs`, `promptFor`) does not. If the explanation-first arm is
adopted, the suffix ships into `promptFor` in the same change as its weights.

**H8.** Both failures are introduced/repaired pairs, whose two members review
mirrored diffs: `[4]` is `atoi` in `validated-port-conversion-introduced` and
the validated cast in `-repaired`. Equal numbers in such a pair do not name
equal lines, so the measure was wrong for 8 of 26 pairs. The number stays in
the record. H8v2, declared after this defect by the auditor's ruling, keeps
number-set equality for the 18 pairs whose members share one changed-line
block, and for the 8 mirrored pairs requires every citation to exist in the
member's own changed lines and both members to cite the same diff sides
(all 8 cite ADDED lines only). The two failing pairs differ because the repair
adds more lines than the breakage; no explanation was edited.

**H9.** The fixed pattern list found nothing. Read by eye as the brief asked:
"larger count" in both `allocation-product-overflow-*-concern` rows refers to
the numeric range of `count` admitted by a `uint32_t` limit but unsafe for
`uint64_t` elements. That is the protective property itself, not diff shape;
the paired clean rows argue the type equality symmetrically.

## Red run

Each mutated copy must fail its target check with rc 1. First pass 7/8: the
system-byte mutation replaced a substring absent from review system prompts and
changed nothing; the corrected mutation fails as intended (`red-run-v1.txt`).
After H8v2, ten mutations including a REMOVED-side citation and a nonexistent
line id: 10/10 (`red-run-v2.txt`). H9 adjudication: `content` passes, `shape`
and a stale key fail.

**Evidence correction, 2026-10-03:** neither referenced original red-run log
was included in the published tree or found in the available Git history.
The 7/8 and 10/10 numbers above remain the author's historical report and are
not independently verifiable from this archive. A new, separately timestamped
[acceptance audit](../2026-10-03-runpod-launch/acceptance-audit.md) publishes its
runner, mutations and target-check results. It does not reconstruct or certify
those missing original runs.

## Native JVPR2

`make probe-pairs`, `training/prepare.py --pair-format 2`, and
`build/jovovich-probe-pairs` on the pinned base (`e1a77721…`): both arms
`pair_completion pass`, 52 review rows; decision positions 40–58 before, 3
after. Probe output and pair maps are byte-identical to
`training/results/2026-10-03-explanation-order/native-normalized/`, an
independent reproduction (`jvpr2.json`, two examples per arm).

## Blind readout

Eight pairs by declared hash seed, sixteen rows, a reader with no session
context (`blind/`). Before seeing any analysis the reader's own verdict matched
v5 on 16/16. Given the analyses without findings: 16/16 derivable from the
prompt, 60 premises, 0 unsupported, no reliance on diff size.

## Gate

Declared gate passes with H8v2 in place of H8, both numbers recorded. Training
on these corpora still requires the six-point launch brief.
