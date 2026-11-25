# JOVOVICHLOG

A fresh engineering log. Newest entries first. Earlier work remains in Git history.

## 2026-11-25 — Compare exact mixed-review observations

`jovovich-replay reviews` indexes mixed reviews by evidence digest and original
journal ordinal. `--compare BEFORE_ID AFTER_ID` selects two observations in
that PR's insertion order and retains both full records. Exact paths align the
files; AML classifies four verdict transitions, first reviews, absent paths
and changed rule/model/policy identities. Renames keep both path histories.
The index validates each evidence digest before filtering legacy entries;
selected comparisons reject unknown, reversed or duplicate identities before
publishing. Both queries work offline and leave the checkpoint intact.

Twelve native reviews from PR #79, retained in PR #80's AML journals, produce
18 checked comparisons and 36 file transitions. Twelve pairs keep the visual
option order; six pairs change it and report that policy change separately.
Full original observations and fresh-process output bytes match. Both legacy
history outputs remain byte-identical, and all original checkpoints are intact.

The complete repository checks pass. Synthetic comparison gates cover both Git
object formats, all transition classes, rule corrections, text/vision model
changes, policy changes, same-head repeats, future appends, foreign namespaces,
legacy entries, valid-container corruption, and the 64-file/128-path boundary.
Replay gates pass ASan/UBSan with AML uninstrumented and leak detection disabled.
Four mutation runs are rejected: bypassed compatibility, bypassed evidence
digest, reversed journal order and an absent path misclassified as unchanged clean.

## 2026-11-25 — Keep mixed reviews in the PR history

Mixed reports accept `--memory` with `--record-pr` after validating the complete
batch and every answer. Each repository/PR journal retains ordered input and
answer pairs in `evidence.review`, including complete HTML, visual receipts,
model hashes, raw logits and their original clocks. The named rule remains in
the rule journal; deterministic findings and snapshot coverage keep their own
fields. Model-review histories use `reviewed`. Exact publication retries keep
the first observation and clock; reading after restart needs no Git or model.

All twelve native mixed reviews captured for PR #79 were recorded and read back:
24 exact answers and 24 byte-identical JSON/Markdown reports. Rule and visual
checkpoints stayed unchanged. Ten earlier text-report variants also match their
previous bytes. This step reuses those native answers and changes persistence.

Full `make all check` passes. New gates cover both Git object formats, image-only
reviews, concurrent retries, repository/PR/head isolation, failed writes,
oversized observations and offline/corrupted history. Report/replay gates pass
ASan/UBSan with AML uninstrumented and leak detection disabled. Mutation checks
catch disabled PR binding and evidence-digest validation. Those checks required
fixtures with a consistent foreign PR URL/number and a repaired container CRC
to reach the intended guards. README now shows two actual native review
excerpts and credits LALO's memory ideas while identifying AML as her journal.

## 2026-11-25 — Read committed HTML in both option orders

The mixed review now captures complete regular `.html`/`.htm` files at HEAD.
AML asks whether the after-file satisfies the base rule; NoTorch evaluates
CONCERN/CLEAN and CLEAN/CONCERN with fresh caches. AML averages logits by
meaning before the existing softmax and 0.5 decision boundary. The manifest
binds the complete HTML, and `html-head-paired/1` receipts retain both prompt
hashes and all four logits. Reporting rereads the Git blob and recomputes
both frames and scores. Original diff evidence and rule memory remain visible.
This costs two forwards per HTML decision in newly packed mixed reviews.

The original pinned OneJev artifacts were used throughout. Full-head-only
and paired base/head views each scored 4/6 discovery cases. Changing only the
question scored 5/6. Full head plus the after-file question scored 6/6, but
one of eight new Apply/Reset cases still depended on option order. Semantic
logit averaging passed those fourteen cases. With that rule frozen, eight
fresh Publish/Archive cases all passed: 22/22 across the three groups, each
measured in both option orders. The failed variants remain in the raw study.

The production CLI then ran all twelve original mixed batches: all twelve
HTML votes match their expected state, and all twelve visual answers remain
identical to the previous run. Both HTML prompt hashes and each raw logit
match the diagnostic forwards. The three original false CONCERN cases are
CLEAN; all three violating cases remain CONCERN. The twelve complete reports
are six CLEAN and six CONCERN, verified in JSON and Markdown. Visual memory
is byte-identical before and after the run. No model weights were changed.

Full `make all check` passes. HTML protocol gates cover both Git object
formats, committed content outside hunks, added/empty/deleted/link paths,
trace composition, and altered Git/prompt/score receipts. All 33 added token
spellings stay literal in both HTML frames. Three mutants disabling Git,
prompt or score binding are caught. Pack/report gates pass ASan/UBSan with
AML uninstrumented and leak detection disabled. Ten original-text report
variants and twelve archived mixed reports in both formats remain byte-identical.
The existing file-backed allocation shim was used for live inference.
[Mixed review contract](docs/batch-review.md#combine-text-and-visual-reviews).

## 2026-11-25 — Include visual decisions in the whole-change report

`--with-visual` packs modified binary images and ordinary text patches into
one `jovovich.git-batch/2` manifest. Every changed binary path needs exactly
one comparison tied to its path, exact base/head commits, logical repository
and PR number. Text paths keep their patch reviews. The batch digest binds
the complete visual comparison receipts and the selected rule-memory fact.
The native CLI dispatches both kinds with fresh inference caches. Reporting
reconstructs the visual receipts from Git and historical memory, checks the
prompt/artifact hashes and AML scores, and includes each visual vote in the
common CLEAN/CONCERN total. JSON and Markdown retain the observations and
their sources. Visual-only changes and recalled text rules are covered.

The live run uses the same original pinned OneJev text/tokenizer artifacts
and the eight actual visual observations archived for PR #77. Twelve mixed
batches yield 24 decisions: 12 HTML reviews and 12 visual comparisons. All
12 visual verdicts match the predeclared expectations; their logits, scores,
prompts and evidence match the previous standalone run exactly apart from
the input hashes changed by nesting the request. All twelve combined reports
validate in JSON and Markdown. The visual journal remains byte-identical to
the PR #77 archive.

This run also exposes three false CONCERN votes in the ordinary HTML path:
it selects CONCERN for all six unique patches, including the three whose
after screens satisfy the rule. A separate native executable rebuilt from
pre-change main `0ee8a12` reproduces all six HTML answers in every field
except the review clock. The combined reports consequently retain CONCERN;
the existing HTML false positives are the next semantic target.

Ten original text reports and an ordinary text pack match their pre-change
executables byte-for-byte. Full `make check` passes, with additional mixed
protocol gates in Git SHA-1 and SHA-256: missing/duplicate/reordered answers,
foreign scopes and PRs, altered evidence and scores, ties in both option
orders, visual-only changes, recalled rules and attached text execution
evidence. Mutants disabling the visual vote, PR binding or score binding
each fail their targeted gate. The new pack/report paths pass ASan/UBSan
with leak detection disabled and the existing AML library uninstrumented.
Live inference uses the previously recorded file-backed allocation shim.
Commands, v2 fields and the supported combinations are in
[docs/batch-review.md](docs/batch-review.md#combine-text-and-visual-reviews).

## 2026-11-24 — Judge the changed screen against its own rule

`--compare-visual DIR` reads two exact image observations from one repository
and key, verifies their regular Git blobs and strict commit ancestry, and
quotes the selected rule from the before commit. AML supplies the requirement
and both observed answer texts to OneJev. The answer retains all source
receipts, the actual AML state, the rule quotation and A/B/CLEAN/CONCERN scores.
`jovovich-replay compare-visual` exposes the same evidence without inference.
Both paths leave the journal unchanged. Incompatible observation questions or
answer sets are refused; reordered choices keep their text identity.

The fixed live test renders a static HTML/CSS settings panel with MuPDF and
commits each HTML/PNG pair, then rerenders the Git HTML to verify the PNG.
Native vision reads eight images: Delete -> Save -> Delete -> Delete in each
of two repositories. The last edit changes only the footer. One repository
requires Save; the other requires Delete. All eight labels are read correctly.
The twelve review presentations (six cases, both option orders) select the
predeclared CLEAN/CONCERN verdicts. The ordinary 0.5 boundary is used.
The fresh-process repeat is byte-identical. The six recall questions retained
from PR #76 also reproduce their previous complete output bytes. Full
`make check` passes, including the new Git SHA-1 and SHA-256 gates. The final
rebuilt native executable has the same SHA-256 as the live-tested executable.

Offline gates reject inexact revisions, wrong repositories and paths, reverse
Git ancestry, and incompatible probes. A changed working-tree rule has no
effect. Replacing the base rule with the head rule, or bypassing ancestry,
each makes its respective negative test fail. The new comparison reader passes
AddressSanitizer/UBSan with leak detection disabled and the existing AML
library uninstrumented. All 33 added token spellings remain literal in the
comparison state and frame. Usage is in [docs/fact-memory.md](docs/fact-memory.md).
Live runs use the original pinned OneJev text/tokenizer/vision artifacts, one
OpenBLAS thread and the temporary file-backed large-allocation setup from the
preceding memory trial. MuPDF 1.26.6 renders the static test panel.

## 2026-11-24 — Remember what she saw, including the correction

The native image path now accepts an explicit `remember` source: repository,
key, PR, full Git commit, regular image blob and predecessor sequence. AML
retains the complete observation in `visual.checkpoint`. Correcting one stream
preserves its earlier receipt; another repository with the same PR number
keeps its own observation. Exact retries preserve the first clock and journal
bytes. The existing writer lock and atomic checkpoint publication serialize
competing writers. Replay reads any available knowledge cutoff.

`--recall-visual` supplies the recorded question and chosen answer text to the
original OneJev in a fresh question. Its output includes the exact source
receipt alongside the new logits and choice. The fixed live test records blue
in two repositories, corrects only one to red, removes the captured images and
asks about both current streams and the earlier version in both option orders.
The expected six letters are A/B/B/A/B/A. The test retains raw inputs, stdout
and stderr and compares the repeated run's complete stdout bytes after restart.
Commands and record formats are in [docs/fact-memory.md](docs/fact-memory.md).

All six live answers match their expected choice, exact recalled receipt and
input hash; the restarted stdout is byte-identical. Two image and two text
review cases also match merged `9c0a139` in every field except their live clocks.
`make check` passes, as does the new writer fixture under AddressSanitizer/UBSan
(leak detection disabled, existing AML library unsanitized). The native GitHub
workflow now runs for application and test changes as well as dependency bumps.

The initial live driver compared parsed JSON values while labelling that check
byte-identical. The driver now captures and compares the original stdout, and
also requires all six answers. Offline checks cover substituted Git bytes,
stale corrections, source/answer binding, 32 intervening observations, twelve
concurrent retries and damaged checkpoints. Disabling the Git image digest
comparison makes the substituted-image test fail. All 33 added token spellings
remain literal in the recalled state, question and options.

Two ordinary F32 runs were killed with SIGKILL during model loading in the
shared test environment. Successful live runs use a temporary allocation
shim that backs large arrays with disk files; model arithmetic and artifacts
are unchanged. Original OneJev `c02e305b...` text, tokenizer and vision hashes
match the existing manifests. NoTorch and AML retain their pinned revisions.

## 2026-11-11 — Original OneJev sees images through NoTorch

The live CLI accepts `--vision VISION.gguf` and JSONL image questions with
explicit A/B choices. The original `c02e305b...` source supplies the encoder;
text weights and tokenizer retain their existing hashes. A separate vision
manifest binds all three artifacts without changing frozen text manifests.
Images and encoder weights use the existing immutable-snapshot hash check.
NoTorch supplies merged image rows and T/H/W positions; AML prepares the
qev-labels-v2 frame, scores choices and records a JANUS instant. Output receipts
include image/model/prompt/input hashes, image geometry, logits and the choice.

Real-weight gate: red/blue images return A/B; reversing the choices returns
B/A. Literal control spellings stay text. Wrong image bytes, wrong vision
weights and image input without vision mode are rejected. All 33 added token
spellings pass both text and image frame checks. `make check` passes.
Commands: `make check-visual MODEL=... VISION=...` and
`build/check-prompt-tokens /path/to/tokenizer.gguf`.

The first prompt put the question and choices inside the state and missed the
blue/reversed case. Independent Transformers reproduced its A/B logits
11.56255/11.92139. Restoring the checkpoint's image-state/question/options
ordering gives 13.21149/8.71213 in C (13.21150/8.71212 in the reference).
The image gate retains the reversed-choice case. New observations carry their
image receipt; journal writes continue through the existing factual-evidence
path. Training weights were unchanged.

## 2026-11-09 — She wakes the second reader herself

A CONCERN now leaves the building on its own. `deploy/notify-on-concern.sh`
reads a `--json` answers stream and drops one tag per CONCERN verdict into a
queue; `deploy/wake-claude.sh`, fired by a launchd WatchPaths job, hands those
ids to a headless `claude -p` for a slower second read and moves the tags aside
so the watch does not loop. The juror stays a juror — Scribe is deliberately out
of this path; jovovich tags, Claude from Claude Code reviews, the tag is the
whole handshake. The wiring is sh and jq; the C core and the pinned weights are
untouched. `deploy/notify-selftest.sh` reports PASS: the recorded CLEAN
`git-answer.jsonl` drops zero tags, a crafted CONCERN drops exactly one carrying
its id and 0.82 concern probability, and the wake dry-run prints the `claude -p`
invocation naming the queue and the PR without spawning a session. Flipping the
verdict filter to CLEAN makes that same clean row drop a tag, so the filter is
load-bearing. `plutil -lint` passes the launchd template, which ships with
placeholder paths and `RunAtLoad` false, loaded only at deploy on neo.

A background security review then flagged the wake prompt as a prompt-injection
surface, and reading it turned up a worse sibling: `notify-on-concern.sh` wrote
`$queue/$id.json` with no check on `id`, so a crafted answers stream could have
escaped the queue directory. The woken reviewer is now locked to read-only tools
(`--allowedTools Read,Grep,Glob --permission-prompts none`) with the PR content
framed as untrusted, the queue is created mode 700, and a non-hex id is refused
before it can become a filename or a prompt token. A second review then flagged
that first attempt's `--allowedTools` as a fail-open pre-approval rather than a
restriction, so the available tool set is now pinned fail-closed with
`--restricted --tools Read,Grep,Glob --strict-mcp-config --permission-prompts
none --add-dir <queue>` — Bash and the other code tools, WebFetch, ambient
settings and MCP servers are gone by construction, and reads are confined to the
queue. (Two review claims did not hold for this binary: `--permission-prompts`
exists and `--permission-mode default` is not a valid choice.) `notify-selftest.sh`
drives a `../../pwned` id — zero tags, nothing written outside the queue — and
asserts the restricted, pinned-tool and MCP-off flags are present and that Bash
is not reachable. The live sandbox behaviour of the flags is validated at deploy.

## 2026-11-08 — The rollback borrowed the repair's voice

The first archive test let two PR answers trade places and still passed.
We ran the upstream code again and had the original OneJev review all twenty
changes. Each of the eight held-out takes is now checked against its own
decoded text and exact token stream. Jovovich still hears the parser report
line two for line one. She still starts her sentence again. The [replay and recorded takes](docs/voice-audition.md#paired-audition-from-executed-git-patches) include the exact token stream for each review.

## 2026-11-08 — Every other update, an entirely different woman

A second voice SFT fitted 66 coefficients on paired authored remarks, with
24 A and 24 B training targets. At step 200 she picked A for all 24 held-out
presentations. At step 199 she had picked B on every one of them. The same
alternation appeared on steps 197 and 198. Reducing the step size from 0.25
to 0.025 stabilized her choices, giving 3/6 factual cases correct in both
orders and 0/6 for taste. The ordinary OneJev got 4/6 and 1/6 respectively.
[Selections, both letter orders and optimizer traces](docs/voice-audition.md#a-second-light-sft)

## 2026-11-08 — A voice audition and a second judge

Eighteen original English lines went into a separate voice experiment. A
3,498-parameter fit on twelve lines taught the original OneJev to end a
remark. On six Method reviews it produced three distinct remarks and zero
grounded ones. The ordinary judge scored five of the six, including a false
alarm on the AML fix. Liquid d1 closed one of eight witnessed upstream
pairs with CONCERN first and zero with CLEAN first. The original closed
all eight. [The audition, raw lines and replay](docs/voice-audition.md)

## 2026-11-08 — Eight more reversals for the original

The original cleared and caught both sides of eight fresh upstream fixes
at 50%. Version 1.6 closed five pairs at 50% and seven at the 39.07% text
threshold fixed on the preceding six pairs. It recovered PapaParse #1124
and npm/ini #123. On npm/ini #252 the reverse returned one string where the
contract wanted two values in an array. Its 36.58% CONCERN still cleared
that reversal. Both checkpoints ranked all eight witnessed reversals above
their repairs. Every common-input prompt and vote reproduced source alone.

The original remains the default. The AML threshold runs in the offline
quality scorer on admitted text witnesses. Each scored row keeps its raw
vote and both probabilities. [Protocol, individual PRs and replay](docs/threshold-transfer.md)

## 2026-11-08 — The original keeps the chair

Six merged changes from inih and node-semver went through the native Git
review in both directions. On the actual program output the original at
0.50 caught all six reversals and cleared all six repairs. Version 1.6
cleared the repairs and missed two inih reversals. Raising the original's
threshold to 0.60 missed three. All three points missed every reversal when
given the source alone. The preregistered release gate keeps the private
`jovovich.gguf` and the default CLI profile on the original checkpoint.

The AML review can now receive a short text result from both revisions
through the differential gate. Counterexample memory remeasures that
result when the case returns. [Trial, observations and replay](docs/upstream-release-trial.md)

## 2026-11-08 — OneJev 1.6 gets the comment back

Eight correct functions each received two Git patches. One added a comment.
The other added the same comment and broke one supported input. With the
paired execution the original release got both heads right in 4/8 pairs and
raised four false alarms. The opt-in 1.6 body got 8/8 pairs and kept 32/32
archived judgments. On source alone it missed six regressions. PR #55's
comment moved from 66.40% CONCERN to 57.99% CLEAN.

Published the converted candidate alongside the original in the private
model repository. The downloaded GGUF and its shared tokenizer reproduced
the 305-token repair. Its native slot logits matched the independent F32
reference within 0.000002. The candidate qualifies for the wider trial.
[Protocol and results](docs/onejev16.md) · [Candidate GGUF](https://huggingface.co/ataeff/jovovich/blob/68cd85536e8d1c46cbf62849d08515d25c97a6ec/candidates/onejev1.6/jovovich.gguf)

## 2026-11-08 — A body on the Hub and a counterexample across reviews

Published the native `jovovich.gguf` (2,013,370,016 bytes) and its tokenizer
(10,927,776 bytes) in the private model repository. Downloaded both from the
release revision and verified their full SHA-256 values against the runtime
manifest. That pair reproduced **68.9538% CLEAN** on the archived Git repair.
The three trained readout candidates are preserved under `experiments/`.
[GGUF release](https://huggingface.co/ataeff/jovovich/tree/0eac460171f26a9582d2d25dc86a96350c2a4dca)

A new AML journal retained mode 1 from a landed callback-order repair. On a
later regression the independent driver ran the new base, head and contract
oracle. Both the recalled and manual probes gave **87.8961% CONCERN**. The
subsequent repair gave **68.9538% CLEAN**. A later comment-only change was a
source-only false alarm at **66.4016% CONCERN**, reproduced with the same
prompt after the remembered probe found equal effects. All six file answers
passed whole-change reporting. [Reproduction and paired votes](docs/counterexamples.md)

## 2026-11-08 — She remembers the agreement

A fresh process packed a second Git review using a rule saved by the first.
The AML journal retained its original base, head, quotation and receipt time.
Correcting `draw-order` created receipt 2. Reopening the prior Git pair at
receipt 1 reproduced its packed bytes. Two competing corrections to the same
receipt produced one successor.

On the pinned OneJev base, the recalled `scan → paint` agreement and manual
selection gave the same **68.9538% CLEAN**. Under the corrected
`paint → scan` agreement, the same patch and callback executions gave
**96.4336% CONCERN**. All three native answers passed whole-change reporting.
AML now normalizes both logits after the NoTorch forward pass. The original
14 reviews reproduced all 14 reference choices and passed the existing F32
probability gate. [Memory and reproduction](docs/fact-memory.md)

The README has its original epigraph, freckles and chain of custody back,
with the commands for the body that actually runs today.

## 2026-11-08 — The 305-token repair on Apple Silicon

On Neo's A18 Pro CPU, the full resident Git review took 1.47 s and 1.50 s
in two five-request medians. Fable measured llama.cpp F16 `pp305` at 4.085 s
on the same CPU and 352 ms with Metal. The Mac mini M4 Pro gave 271 ms on
CPU and 85 ms on Metal. The [benchmark record](docs/review-latency.md#apple-silicon-measurements)
preserves both timed workloads and the **2.72–2.78×** Neo CPU ratio.

Captured all 305 IDs from the real review and replayed them directly through
NoTorch. Last-position logits A = 10.72415 and B = 11.52211 reproduced
68.9538% CLEAN. The [fixture](examples/review-latency/draw-replay.jsonl)
pins the actual input for the next same-token comparison.

## 2026-11-08 — Review operating rules and first-answer latency

The [operating rules](docs/operating-rules.md) specify how the host selects
an execution, how a passing repair enters the prompt, and how OneJev's two
probabilities become a file verdict. The [latency benchmark](docs/review-latency.md)
replayed the archived Git repair six times with the pinned F32 model. On
Linux x86_64 the first answer took 12.952 s and the five resident reviews
had a median of 5.236 s. All six reproduced mode 1 and 69.0% CLEAN.

## 2026-11-07 — Selecting an execution before review

The frozen base chose the distinguishing input across both option orders and
both source orders for 2/8 APIs. The predeclared presentation chose it for
3/8. With that choice, the reviewer scored 22/32. The host compared both
modes on the contract-relevant effect, found all eight distinguishing runs
and scored 32/32. The [experiment](docs/run-selection.md) records 32 blind
choices and 64 downstream reviews. The ordinary CLI now accepts
[paired execution traces](docs/trace-evidence.md) from a harness.

## 2026-11-07 — Reviewing callback order and counts

Frozen OneJev reviewed 32 source/contract combinations across eight APIs.
It scored 17/32 on code and 16/32 with the shared passing execution.
The distinguishing execution alone gave 27/32. Supplying both required
and observed effects gave 32/32 and solved 16/16 same-rule mutation pairs.
The [transfer experiment](docs/execution-traces.md) passed its preregistered
criterion. All four conditions used the ordinary JSON reviewer.

## 2026-11-07 — Showing OneJev the return at equality

The frozen base scored 55/96 on the original comparisons, 51/96 with a
test at the neighboring integer and 86/96 with a test at equality. The
equality run repaired 31 errors and kept every previously correct verdict.
Canonicalizing the code gave 56/96 on its own. With the equality run it
gave 24/24 distinct correct decisions across all four spellings. The
[experiment](docs/boundary-observations.md) includes the paired head,
compiled observations and per-case probabilities. The new native
`--canonical-boundaries` review option retains the original evidence.

## 2026-11-07 — Equivalent boundary forms and operand order

On 96 fresh reviews the base and paired readout both gave 55 correct
verdicts. The paired head agreed across the trained direct/negated rewrite
on 18/24 cases and across direct/reversed operands on 6/24. All 24 direct
reversed comparisons received CONCERN. The earlier review suite scored
27/38 against the base's 30/38. The two new heads are archived privately.
The [experiment](docs/equivalent-boundaries.md) records the executed corpus,
the BCE control, the paired objective and all four systems' decisions.

## 2026-11-07 — First supervised A/B readout on OneJev

Trained 1,025 output parameters on the 128 executed examples with a frozen
OneJev text backbone. Training accuracy rose from 73 to 90 correct. On the
64 held-out examples, both heads answered 34 correctly. On the earlier 38
reviews, accuracy fell from 30 to 27. The learned head found two previously
missed violations and introduced four false alarms. One previously detected
violation received CLEAN.

The checkpoint is archived in the private model repository. Native review
accepts it with `--readout`, and JSON results record its exact digest. The
[experiment](docs/semantic-readout.md) includes the protocol committed before
fitting, the per-case results and instructions for replay. On held-out guards,
the learned head ranked the violation higher in 16/16 pairs. Rewriting the
32 held-out boundary functions from negated to equivalent direct comparisons
raised its accuracy from 16/32 to 23/32. All 544 compiled return values matched.

## 2026-11-07 — Executed semantic training pairs

Added a reproducible C + AML corpus builder targeting comparison boundaries
and the conditions controlling side effects. AML owns the English requirements,
review contexts and A/B training targets. The C builder compiles the exact
candidate bodies and compares their execution with separate bound and Boolean
reference calculations. All 192 functions produced 2,432 native observations.

The corpus contains 128 training rows and 64 evaluation rows, balanced by label.
Both members of each pair stay together. Evaluation uses separate code forms
and bound thresholds; exact code never crosses splits, every context is unique,
and no code/context exactly repeats the existing 38-case suite. Sixty-four
same-code/opposite-contract pairs make the repository rule essential to the
decision. CONCERN records retain an executed counterexample.

The output includes one-token A/B supervision, native evaluation inputs,
separate expected labels, audit receipts and frozen hashes. Full reconstruction
matches the committed manifest. Truncated receipts, reduced domain coverage,
wrong code hashes and two compiled mutations all fail; existing output is
preserved. The complete earlier test suite also passes. Training and new model
measurements follow this corpus stage. Commands and contracts are in
[docs/semantic-corpus.md](docs/semantic-corpus.md).

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
