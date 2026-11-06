# JOVOVICHLOG

A fresh engineering log. Newest entries first. Earlier work remains in Git history.

## 2026-11-06 — Dependency coverage and paired decision quality

Reproduced the PR #45 finding: `diff.ignoreSubmodules=all` made a two-path
change produce a one-file batch. All diff reads now force submodule inclusion;
patches use the short format with full old/new commit IDs. The new regression
test fails on the preceding packer and passes with this fix in both Git object
formats, with 40 evidence assertions per run. It covers batch and single-path
input under global and per-submodule ignore settings and log-style formatting.

Expanded decision measurement to 38 cases: the existing 14 plus 24 fixed,
paired transfer cases. Both native runs use original OneJev with NoTorch and
AML, zero generated tokens and zero training updates. The current question
scores 12/14 + 18/24 = 30/38. A candidate asking for condition-by-condition and
counterexample checks scores 12/14 + 16/24 = 28/38. It repairs no decisions and
introduces two false concerns, so it is not promoted.

Added a C scorer, a shell live runner and both complete measured runs. The
scorer checks correspondence, provenance, probabilities and the exact AML
question, then reports per-case results and separate error counts. Stored
scores replay exactly; incomplete answers, swapped expectations and altered
verdicts are rejected. Details and the eight current error cases are in
[docs/review-quality.md](docs/review-quality.md).

## 2026-11-06 — Complete multi-file review

Added `jovovich-pack --all` to capture every changed path between two commits
and `jovovich-report` to validate the complete result before emitting Markdown
or JSON. The ordered batch digest, indexes, counts, source fields and exact
input-row hashes bind every answer to its packed input. Duplicate JSON keys
are rejected: a regression fixture reproduced a conflicting duplicate `choice`
that the original narrow lookup read differently from last-key-wins consumers.

AML now owns the aggregate rule: any CONCERN makes the report CONCERN; all CLEAN
makes it CLEAN. Per-file probabilities remain intact. A live NoTorch run over
the controlled two-file Git fixture selected CLEAN 77.5977% for the unchanged
square calculation and CONCERN 84.5038% for a prohibited libcurl dependency.
The report contains both answers and a CONCERN summary; all records are in
`examples/batch-20261106`.

The existing 941 saved/AML checks and 80 Git evidence checks pass. New checks
cover three aggregate cases, 14 refused reports, Markdown output, the 64/65-file
boundary and a binary-file batch refusal. The batch checks pass for both Git
object formats. A deliberate AML `> 1` threshold mutation fails the mixed-case
gate. Commands and contracts are in [docs/batch-review.md](docs/batch-review.md).

## 2026-11-06 — Real Git input through AML

Added a native Git packer for one changed path at two resolved commits. It
reads rules from the base commit, captures the literal patch with eight context
lines, and gives both to AML for English context assembly. Live answers retain
commit IDs, the baseline rules blob and selected lines, and rule/patch hashes.
The host verifies those content hashes before inference. Existing saved inputs
remain supported. README's maintainer note about its later literary rewrite
is preserved; commands and the new contract are in [docs/git-review.md](docs/git-review.md).

The real-Git fixture passes 80 evidence assertions and nine rejection cases;
the saved/AML gate still passes 941 checks. A deliberate HEAD-for-BASE rules
substitution fails. The actual NoTorch head-offset fix was packed from its
commits and reviewed live: CLEAN 59.7870%, CONCERN 40.2130%. All 28 live-source
checks pass; an altered patch hash is refused before a second decision.
The exact input, answer and run metadata are in `examples/git-notorch-20261106`.

## 2026-11-06 — Pin the NoTorch head-offset fix

NoTorch PR #188 widens two Qwen3.5 tensor offsets before multiplication,
resolving the CodeQL findings on the original native integration. Pin the
corrected engine commit. The rebuilt engine passes 1,214 frozen-reference
checks; the live AML consumer passes all 1,340 checks over 14 review cases.
Every emitted probability pair is exactly unchanged from the preceding run.

## 2026-11-06 — Original OneJev, NoTorch arithmetic, AML language

The live reviewer now executes original OmniJev/OneJev-0.8B with native
Qwen3.5 arithmetic in NoTorch. AML constructs the exact qev-labels-v2 question
and prompt, selects the verdict and creates its JANUS timestamp. The C host
validates supplied evidence, checks pinned model/tokenizer hashes and emits
English Markdown or JSON. The repository's former Python check is replaced by
C + AML checks. Both source dependencies are pinned.

A/B logits determine CONCERN/CLEAN without generated tokens. All 14 live
choices match the independent F32 reference within the recorded probability
gate. The original BF16 demo is preserved as a separate record. Task accuracy
is 12/14, including the index-boundary and disabled-writer misses. Full-layer
NoTorch parity, consumer checks, test counts and commands are recorded in
[docs/native-validation.md](docs/native-validation.md).

The first connection exposed two host-integration mistakes: an AML template
line exceeded the interpreter's 256-byte limit, and the host injected globals
before explicit initialization. Splitting the template and initializing AML
before injection fixed them; the exact-prompt and end-to-end checks now cover
this connection. No AML core changes were required.

LALO and Amos 2 informed the provenance boundary: retain the input, model
revision, hashes and a dated execution result. No event date or origin is
invented from the time of review. The first text path accepts ASCII English
and uses F32 CPU matrices. Vision, personality training and speed optimization
are the next implementation stages. The Hugging Face repository ataeff/jovovich
was verified private; no weights were uploaded and RunPod was not used.
