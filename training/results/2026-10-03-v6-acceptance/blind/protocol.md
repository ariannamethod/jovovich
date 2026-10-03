# Blind readout protocol

Selection: for each of the 26 pairs, `sha256("v6-acceptance-2026-10-03:" + pair)`;
sort ascending; first 8 (`selection.txt`). Row order inside the readout:
`sha256("blind-order:" + id)` ascending, labels R01–R16 (`map.json`, kept from
the reader). The reader was a fresh agent with no session context, told to open
only the readout files and nothing in the repository.

Phase A gave the reader `phaseA.md` only: the v5 user prompt of each row (rules,
context, surrounding diff, changed lines), no answer. Instruction, verbatim:

> For EACH task, decide on your own: does the change conflict with the
> applicable rules (CONCERN) or not (CLEAN)? Give: label; verdict: CONCERN or
> CLEAN; line_ids: which bracketed changed lines drive your decision; reason:
> 1–2 sentences naming the specific rule clause and the specific changed code
> that decide it.

Phase B then added `phaseB.md`: each row's analysis, without findings.
Instruction, verbatim:

> For EACH label, check the analysis strictly against the task text in
> blind_phaseA.md: premises: list each factual premise the analysis relies on
> (rule clause, context fact, changed-code fact, consequence); each premise:
> SUPPORTED (stated in or directly inferable from the task text) or
> UNSUPPORTED (not in the task text, or contradicts it); derivable: YES if every
> premise is SUPPORTED and the conclusion follows; NO otherwise;
> conflicts_with_my_phase_A: YES/NO; note: one sentence, especially for any
> UNSUPPORTED premise or any reliance on diff size/shape (line counts, "it's
> just a deletion") instead of meaning.

Both answer files are the reader's output extracted verbatim from its transcript.
