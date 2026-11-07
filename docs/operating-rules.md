# Operating rules for a JOVOVICH review

The host chooses the execution to show. OneJev judges the proposed change
against the supplied repository requirement. The maintainer decides what to
merge.

## Establish what is being reviewed

For a Git review, pin the base and head commits, take the rule from the base
and take the patch from the difference between them. Keep the file, verbatim
rule and original change in the answer. An explicit
`--canonical-boundaries` flag can normalize the model's view of supported
integer comparisons. The original patch remains the evidence of what changed.
[Git input](git-review.md) · [Canonicalization](boundary-observations.md)

## Choose evidence by execution

A harness runs both revisions on the same input under the same setup and
supplies the required effect from an independent contract oracle. It attaches
the two observations to the review using `trace_evidence`. The native host
compares the contract-visible effect. For sequence rules it compares callbacks
in order. For count rules it counts occurrences of the named callback. The host inspects every
supplied mode and selects the **smallest integer mode with a differing
effect**. This rule is independent of input order and of which version passes.
[Trace schema and bindings](trace-evidence.md)

| What the host finds | What enters the review prompt |
| --- | --- |
| Base and head agree on every supplied mode, including a shared passing test | Source and rule alone, with the same prompt bytes as omitting the traces. |
| At the selected mode, base and head differ and head meets the requirement | The mode, required effect and observed head effect. A passing repair is admissible evidence. |
| At the selected mode, base and head differ and head violates the requirement | The same three fields. The reviewer can see the mismatch. |
| No structured traces supplied | Source and rule alone. |
| Malformed traces or evidence bound to a different review, rule, patch or Git commit pair | The row fails validation. |

A CI pass badge cannot supply these observations. This rule governs the
structured trace input. The reviewer retains text already present in the
source context. The host records the number of supplied and differing runs,
the selected observation when one exists, and the digest of the resulting prompt.

## Issue the verdict

The standard CLI uses the pinned OneJev-0.8B base, the English AML question
and a NoTorch prefill of the prompt. It reads the final A and B logits
and normalizes them over the two choices. A selects **CONCERN**, B selects
**CLEAN**, and an exact tie selects **CONCERN**. The answer exposes both
probabilities beside the rule and change. The verdict describes this change
under this requirement. The model's blind `--select-run` mode belongs to the
selection experiment. The ordinary review path uses the mechanical selector
when paired traces are supplied. [Answer format](review-output.md) · [Selection study](run-selection.md)

For a whole-change report, validate every answer against its packed Git row.
Any CONCERN yields a CONCERN report. All files must return CLEAN for a CLEAN
report. A missing or inconsistent row prevents publication of the report.
[Batch reporting](batch-review.md)

## Worked decision

In the recorded `draw` repair, both versions call `scan` then `paint` at
mode 0. At mode 1 the base calls `paint` then `scan`, while the head restores
the required `scan` then `paint`. The host selects mode 1 and OneJev gives the
repair **69.0% CLEAN**. Across the eight callback APIs in the selection study,
comparing both modes produced 32/32 correct reviews. The blind selector found
the distinguishing input under all four presentations for 2/8 APIs.
[Recorded Git answer](../examples/run-selection/git-answer.jsonl) · [Paired results](../examples/run-selection/results.json)
