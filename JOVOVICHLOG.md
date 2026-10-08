# JOVOVICHLOG

One log. SERGE may smoke here; he may not create `FINAL_FINAL_LOG_2.md`.

## Run preservation rule

Before another training or representation-collection run starts, its launcher
must demonstrate incremental off-workspace persistence. Publish the frozen
protocol, source/input bindings and destination first. Transfer each closed
checkpoint, measurement segment and case result as it becomes available;
build the manifest incrementally. Verify remote byte count and SHA256 before
marking an artifact durable. Keep weights in the private Hugging Face repository;
publish reviewable code and evidence through a Git branch. A local flush or
upload request alone is not remote verification.

An unavailable or mismatching destination blocks advancement to the next
work unit; resume from the last remotely verified unit without overwriting its
evidence. Mark completion only after the complete required manifest is remotely
verified. An interrupted or incomplete run still exists as failure evidence;
it must not be reported as a complete archived run. Record the last verified
unit so the remaining exposure is explicit. Test interrupted uploads and
recovery before trusting the launcher. A paragraph cannot eliminate a failure
window by decree.

`training/durable_archive.py` implements the remote receipts, and
`training/layers/run_layers.py` uses them before every native work unit.
Historical launchers retain their executed bytes. New collection runs use the
verified launcher described below.


## 2026-10-08 — 103 archive receipts. Back to the half-billion woman.

Resumed from merged PR #35 (`42c40a1`). The October 4 after attempt ended at
ACK23/computed24; its exact validation reason was lost by the old diagnostic
schema. All three previous CPU pods were EXITED. Fresh HF recovery authenticated
its 25 closed units/165 logical files and the separate five-file incident record.

Ran an isolated live HF rehearsal with the merged diagnostic archive: original
intent and closed update000..024 bytes, followed by 77 explicitly labelled
repetitions of closed bytes. **103/103 ACKs, zero retries, zero training calls.**
The slowest unit took 54.687 seconds within the unchanged 120-second limit.
Fresh full recovery verified **103 units and 504 logical files**, followed by
another local digest check. The independently archived terminal record is at
`4a3eb7f63a9354984998f2703d7c747f1b8588de`. The original night failure did not
reproduce in this live run.

The independent auditor reproduced two injected service conditions: a stale
branch HEAD stops a warm archive on `previously_verified_unit_missing`, and a
partial inventory ending in EntryNotFound loses its transport classification.
The historical incident remains unattributed. Archive checks and retry policy
stay unchanged. The rehearsal now archives its terminal recovery result
separately; its interim report explicitly records recovery pending. The live
103-unit script and the later terminal helper each retain their own source hash.

NoTorch was audited from pinned `014403f` to `420fa54`: 30 Qwen/harness/GGUF/BPE/
SIMD files are unchanged. Independently compiled legacy CPU Chuck traces match
byte-for-byte over 6000 steps (3,336,000 bytes). New device-coherence and
checked-action fixes concern other paths. Qwen3.5 requires a new backend and
trainer support; the current registered dense paths are Qwen2/Qwen3.

Fresh original recovery (before103 + failed-after11), the 85-binding launch,
native protocol preflight and a 20-file private preflight archive roundtrip all
passed. Targeted suites: **44 archive +47 host/binding/evaluation tests, zero
failures**. Original numerical binaries, packed inputs, base SHA, initialization,
100 updates and the 228-response evaluation contract are preserved.

Started CPU pod `sb0zexiv12aeoe` at 00:02:27 UTC on October 8, source
`f5f5d6eac077ea37ca5e254211280c0a1c1c7a13`, run prefix
`order-rp-20261008-03`. Four vCPUs/16GB, $0.16/hour, the same 12-hour watchdog
and retained volume. The new process starts from update0; Chuck snapshots do
not carry its controller/moments. Bootstrap is running; native startup is being
checked separately. Evidence: `training/results/2026-10-08-archive-rehearsal/`.

SERGE counted 103 receipts. Still one cigarette.

## 2026-10-05 — The failed boundary keeps its evidence.

The fresh matched after attempt stopped at 2026-10-04 23:27:15 UTC while
archiving update024. Update023 was acknowledged; the native log contains the
computed update024 and its archive-ready boundary. The parent stopped the
native process with return code -15. Runpod recorded container removal at
23:27:24 UTC, and the pod is EXITED. The evaluation archive has no units.

Fresh recovery from private HF revision
`11f6c33b277f24459147bf6a9314205be1c334de` verified all 25 training units
(165 logical files) and the separate failure unit (five files). The last ACK
matches the recovered update023 manifest. The failure is classified as
`ArchiveError / validation`, with one attempt and no retry. Its exact invariant
was lost: the retry wrapper replaced the exception message, and the diagnostic
schema did not retain a validation reason.

An independent local replay used the deployed archive source, all 25 exact
remote manifests and the recovered payloads. The update024 files were extracted
as exact suffixes of the failure logs after matching every earlier log byte.
All six ordinary replay cases passed; an accepted-commit/lost-response control
also passed with one local commit. Both corruption controls rejected before
commit. The original validation failure was not reproduced on those bytes.
The incident's transient service responses and filesystem state were not
recorded, so the specific triggering invariant remains unidentified.

The archive diagnostic now preserves an allowlisted `reason_code` through the
operation and retry wrappers into `failure.json`. Unknown diagnostic text maps
to null. The change retains the existing retry policy and integrity checks.
All 44 archive and continuation tests passed, including optimized Python.
The original launch pins and infrastructure approval record remain historical;
a future native attempt needs its own reviewed bindings and fresh run ID.

Evidence and the reproducible local replay are in
`training/results/2026-10-05-after-validation/`. No new native attempt was
started during this investigation.

## 2026-10-04 — The archive opens again.

The maintainer restored HF Pro. A fresh recovery then verified all 103 original
before units and 11 failed-after units. On those real bytes, the binder restored
the original numerical artifacts and produced an 85-binding after plan;
independent evaluator admission accepted exactly the two reviewed source
changes. The original C executable passed its archive-protocol preflight.
No local training or generation was performed.

Thirty preflight/source/provenance files were committed to private HF and
recovered again by bytes at revision
`25c8b3b0c4c7ad4d5b5214350056dd382ee4e99c`, under
`experiments/explanation-order-preflight/after-launch-preflight-20261004-02`.
The receipt and verification result are retained beside the deployment intent.

The new CPU pod `fnwhk6bqjfy30a` was created at 2026-10-04 22:46:18 UTC. It uses
4 vCPU / 16 GB CPU3g at $0.16/hour, the retained EU-RO-1 volume and the pinned
Python image. Watchdog child-started/heartbeat and checkout
`970163b792d24dba1b5d2d3077177baf9cd1e28b` were observed. Its maximum envelope
is 12 hours; the same watchdog requests its own pod stop on child completion,
failure, signal or deadline. The original checkout is retained separately.
At 22:53 UTC the host was preparing the environment; no new native training
update or generated review had been observed.

At 22:59 UTC the first live after intent was freshly recovered from HF
revision `52ca299e03d43496d5027b503206534dfcaeef9b`: all 86 files passed byte
verification. The archived plan and real Runpod host manifest bind the deployed
source, original before completion and unchanged numerical configuration.
Only the two approved infrastructure candidate bindings differ from the
original after plan. Native protocol preflight and the fresh after launch were
observed on the host. Optimizer updates and generated reviews are not yet
claimed by this startup verification. At 23:00 UTC the pod was still RUNNING
and remote inventory contained exactly that first intent unit.

See `training/results/2026-10-04-matched-after-launch/deployment-status.json`.

## 2026-10-04 — The after arm gets a return ticket.

PR30 and Claude's PR31 are merged. The matched continuation now has a complete
host path: recover the pinned before and failed-after archives, restore the
original numerical binaries and packed inputs, bind the two reviewed archive
repairs, run a fresh after trajectory from update0 to update100, then compare
it with the surviving original before100 under the original 228-response
contract. The managed setup uses a separate mounted-volume checkout. The
watchdog and the two approved infrastructure candidate hashes stay unchanged.

The continuation evaluator independently reconstructs its required dependency
set, requires the bound host manifest and launcher, checks both full recovery
ledgers and freshly verifies remote checkpoint/completion payloads before any
export. Independent audit caught omissions that could previously be hidden by
rehashing a declaration; the omitted-helper, removed-host and truncated-ledger
regressions now reject. Evaluation retries only the same closed archive unit,
at most four attempts within a 900-second receipt budget for large GGUF
upload/readback. An in-flight SDK call can exceed that budget; late receipts
are rejected. Native work is never regenerated by an archive retry.

The PR31 connector finding is also fixed: quote launch inputs and their
infrastructure record must be regular tracked blobs in the pinned Git commit.
An ignored models/ record is rejected before installation or model download.

`make test` passed the native suite and 360 Node tests. The final host/ledger
admission hardening then passed all eight focused tests; independent audit
found no remaining blocking defect in the reviewed path. This is local
validation, not a new model result.

The real preflight stopped before payload recovery: Hugging Face returned
HTTP403 with `Private repository storage limit reached for ataeff`. The token
is valid with write access; private repository metadata remains accessible.
Both proposed run IDs were empty at the check. No new pod, training update,
generation or remote write was started. The original and diagnostic pods
were both observed EXITED. Private HF access must be restored before fresh
remote recovery and deployment can proceed. No archive data was deleted.
See `training/results/2026-10-04-matched-after-launch/verification.json`.

Claude's parallel PR32 was then incorporated into this continuation branch:
its five additional quote gate regressions and retained-log provenance
follow-up remain included. The overlap uses one pinned-file check, retaining
regular Git modes, symlink rejection and offline Git inspection. All 17 quote
host tests passed after the integration. PR33 contains this integration so
there is one combined continuation to review.

The subsequent connector review identified Git replacement refs as another
source-verification ambiguity. Quote now disables replacement objects in its
shell source checks as well as the pinned-file helper. A real replacement-ref
fixture reproduces the masking attempt and is rejected before any work;
all 18 quote host tests pass. The managed after deployment remains pinned to
`970163b792d24dba1b5d2d3077177baf9cd1e28b`; this quote-only follow-up is outside
that numerical path. Its CPU request, source/setup/watchdog hashes and 12-hour
budget are published in the deployment intent before provisioning.

## 2026-10-04 — Keep the gate closed; retry the same parcel.

PR29 review found two recovery defects. The wrapper checked the shape of a
source SHA without binding its executing bytes, and the incident summary
accepted an ACK filename without checking its manifest. Recovery now binds
the wrapper/helper to the supplied Git revision and the retained archive
module to its separate original revision. The highest local update receipt
must match a fresh pinned manifest chain and the exact original launch plan;
the diagnostic names that metadata verification scope explicitly.

The training archive already supported accepted-but-unacknowledged commits,
but the training parent never retried them. New attempts retry the identical
closed unit for selected transient failures, at most four attempts by default.
Native work remains blocked at its existing ACK boundary. Changed payloads,
authentication failures and integrity failures stop immediately. The default
receipt acceptance deadline is 120 seconds, capped at 80% of the native ACK
budget. HF requests have finite connect/read timeouts; an in-flight SDK call
can finish after the deadline, at which point its receipt is rejected.

Failure records now retain the operation, exception class, numeric HTTP status
or errno, attempted unit and last acknowledged unit/update without transport
exception text. After stopping the native child, the parent also attempts a
separate failure-evidence archive. Retry records through the pre-completion
snapshot travel with completion; retries of completion itself remain in the
local retry journal and parent stderr. The original failure's underlying
operation was not recorded by the old deployed handler.

`training/after_recovery/preflight.py` prepares the next after attempt from
freshly verified original before/after archives. It preserves the numerical
inputs and initialization and identifies exactly two permitted infrastructure
changes. Its contract is explicitly non-runnable: an after-only host launcher
and evaluator admission for these infrastructure changes are the next stage.
The completed before comparator remains pinned. No new training pod was
launched for this code change. The combined suite passed 301 tests; the final
recovery hardening passed all 29 focused cases, including three new cases.
The native fault fixture preserved bitwise LoRA results through a lost commit
reply, with 24 fault scenarios and no repeated optimizer update.

The real private HF archive was then recovered afresh: 103 before units and
11 failed-after units passed byte verification at the original pinned revision.
All original non-infrastructure bindings and initial adapters match. The
candidate differs on exactly the two allowed paths, and the public verification
record lists both original/candidate SHA256 pairs for the shared after/quote
admission rule. The preflight, source bytes and test logs were archived and
recovered again from private HF revision `e983dc43212f0d8a06b4c63b4d751d690bd4f2cc`.
See `training/results/2026-10-04-archive-retry/verification.json`.

## 2026-10-04 — An archive failure stops the second arm.

The first Runpod attempt completed and archived all 100 before updates. The
after arm computed update10 and emitted its archive-ready boundary; its
archive synchronization then raised `ArchiveError`. Its last original remote
ACK is update9. At 2026-10-03 23:08:27 UTC the wrapper recorded failure and
native return code -15; the watchdog recorded child exit 1 and an accepted
own-pod stop request. Evaluation had not started.

A separate 15-minute diagnostic pod read the persistent volume through an
allowlist. It copied 24 evidence files into 26 verified archive units, without
changing the original run directories. The full incident was recovered again
from private HF revision `b7908cf8f5cf1516241756addb80ba9531b06e1e` and checked
by bytes. The diagnostic pod is stopped. The deployed failure handler recorded
the exception class but omitted the underlying operation and HTTP status.

Evidence bindings and the deployment source are in
`training/results/2026-10-04-after-archive-incident/summary.json`.
The completed before remains the comparator for a fresh matched after
attempt. Before that attempt, the archive failure path needs structured
diagnostics and reviewed handling of transient failures. The recovery helper
passes eight focused tests; its unchanged watchdog has the previously
reviewed source hash and bounded own-pod shutdown.

## 2026-10-04 — The comparator brings its receipts.

Review of PR26 confirmed two defects: quote evaluation admitted recovered
before responses without checking their archive receipts, and its derived
summary retained the original experiment's six-job totals. The evaluator now
binds both before collectors to the committed launch revision and exact run
IDs, checks their complete unit sequences and local evidence bytes, and reads
the pinned remote input/completion manifests and payloads again before any
quote export or generation. The quote summary describes two collectors,
76 responses and 232 collector archive units. Decoding settings are preserved.

The quote host manifest and launcher copy now enter the training bindings
before preflight, so the initial archive includes the machine/compiler/source
provenance. Both evaluation fixtures create their scratch `models` directory
on a fresh checkout. Independent cross-review passed; `make test` passes the
native suite and all 259 Node tests.

At 2026-10-03 22:41 UTC, private HF revision
`873331a94debd62cff1bd2fcbb9248ad8da2d56c` contains all 103 closed units of
`order-rp-20261003-01-before`, including update100 and completion. Downloaded
completion bytes match their recorded SHA256: return code 0, 100 acknowledged
updates. The same revision contains the after arm's launch intent. The running
experiment remains pinned to `53fd4406de170d3b67785729b789ec61e1a30a27`.

## 2026-10-04 — The third arm gets its own door, and the same key.

The quote-first arm now has a launch and evaluation path of its own, built
beside the running experiment without changing it. Its training plan is bound
to the archived before run, recovered from the private archive at one pinned
revision. That run must have completed its 100 updates, and every source it was
trained from must match this checkout byte for byte, including the rebuilt
trainer binary. The quote arm starts from the before arm's initial adapter
hashes and changes nothing else but its corpus. On the pinned base the native
preflight reads the two arms as frozen: decisions at 40–58 and 55–88, 3411 and
4412 residual tokens, 304 ChatML comparisons without a miss.

Evaluation follows the before arm's own contract. The quote contract is derived
from it by a recorded substitution list that renames the run, its exports and
its model and nothing else, so the quote answers are scored with the same
prompts, answer order and held-out cases. Inverting the list returns the
before branch exactly. After the export, 52 train and 24 held-out generations
are compared with the archived before collectors prompt for prompt and token
for token, and the manipulation check reads both splits.

`training/quote/host_launch.sh` runs it all once in a fresh checkout pinned to
the quote source, on a host built like the one that trained the before arm. It
refuses to start until a committed `training/quote/launch_inputs.json` names the
before run, its evaluation, the archive revision and the expected initial
hashes, so that file can only exist after the running experiment has finished.
A failed attempt is not resumed: a new attempt needs a new prefix. The machine
that builds the binaries is recorded, because a different compiler or CPU will
stop the binding rather than slip a different trainer in.

## 2026-10-03 — Twenty-four copies of one witness are still one witness.

Deployment update, 20:25 UTC: the fresh `order-rp-20261003-01-before` attempt
is running on Runpod pod `9m15r69jnnlpx4`, with a 20 GB network volume. The
CPU5g candidate returned no capacity; CPU3g placed with 4 vCPUs, 16 GB RAM and
an observed compute price of $0.16/hour. The frozen training checkout is
`53fd4406de170d3b67785729b789ec61e1a30a27`; later receipt commits do not change it.
Native preflight passed. An external read of the private HF intent at
`4a4c715115efb4c4f6631cd2eb65607a8518eb52` verified its plan/host objects and
all 49 source bindings against that checkout. At this observation the intent
was the only closed unit: no completed optimizer update, after-arm result or
natural generation is claimed. See the
[deployment receipts](training/results/2026-10-03-runpod-launch).

The independent auditor and the PR24 reviewer reproduced the same hole in the
new quote instrument: a duplicate or incomplete collector file could still
produce passing counts. The revised instrument requires the frozen split's
complete ordered set of 52 or 24 unique cases and reconstructs each exact
prompt from pinned sources. Missing model answers remain failures in the full
denominator. Supplied response hashes are checked, and the report records its
source bindings. The 40-character copying rule is unchanged; the registration
has an append-only integrity correction before any quote generation.

The acceptance summary also cited two original mutation logs absent from the
archive. Those historical numbers are now explicitly unverified. A new
independent [audit](training/results/2026-10-03-runpod-launch/acceptance-audit.md)
publishes its own executable controls and results without pretending to recover
the missing logs. Neither issue changes the recovered 58 native updates.

The next attempt is prepared for a persistent Runpod CPU host. Its portable
launcher pins the complete source commit, keeps the original before/after
training settings and remote ACK barriers, and freezes the quote materials for
later comparison. A separate watchdog covers setup and execution, strips
credentials from child environments and requests that its own pod stop after
success, failure or a 12-hour deadline. API failures can delay the stop; the
network volume remains billed and retained for recovery. The quote arm still
needs its separately declared launcher. Prepared source is not a completed
experiment; deployment receipts and the private archive establish progress.

## 2026-10-03 — The copy is measured before anyone writes it.

The quote-first arm's manipulation check now exists as code, frozen before a
single generation of that arm. `training/quote/manipulation.mjs` reads a
collector run directory, binds each prompt to its record by hash, and asks
whether the generated analysis opens with `Rule: ` followed by at least 40
characters copied verbatim from one of the prompt's AGENTS.md sections. A
copied preamble, a header line or a README passage does not count: those are
not rules. On the gold answers it reads the quote corpus at 52 of 52, each
copy inside the decisive rule and complete, and the explanation-first corpus
at 0 of 52. Breaking the header exclusion or moving the threshold to 39
fails the matching test. The definition is appended to the registration
with its time; the original text stays as it was.

## 2026-10-03 — Copy the law before you judge it.

A third arm is registered before it exists. It keeps every byte of the
explanation-first corpus except one: each analysis opens with
`Rule: ` and the applicable rule copied verbatim from the prompt. The
per-layer readout left judgment no room inside the frozen stack, and a 0.5B
model copies reliably; the question is whether a copy of the protective
property placed in front of the reasoning helps the reasoning land. In 6 of 26
pairs the copied rules themselves differ, because the nearest scope differs.
In the other 20 the copy is shared and the distinction still has to come from
the explanation.

The corpus is built by a rule, not written: the builder reproduces the
explanation-first file byte for byte without the transform, and with it
changes exactly the 52 analyses. The native preflight keeps every prompt
token count and verdict token of the explanation-first arm; decisions move
from positions 40–58 to 55–88, and the copies add 1001 residual tokens.

Training and evaluation are the running experiment's, unchanged. The decision
rule is fixed now: on the 12 held-out pairs, two more fully grounded pairs for
quote-only than for before-only, with the copy present in at least 20 of 24
held-out generations, supports the idea; two the other way counts against it;
anything else is unresolved at this size. At this freeze the running experiment
had archived 36 training updates and no evaluation.

Registration: [`training/quote/PREREGISTRATION.md`](training/quote/PREREGISTRATION.md).

## 2026-10-03 — Same number, different line.

The explanation corpora went through acceptance against criteria fixed before
the checker ran. `training/acceptance/v6_check.mjs` binds both arms, the
reasons file and v5 by hash, then checks rows, bytes, verdicts, key order,
sentence counts, pair parallelism and a fixed list of forbidden shape
justifications. Verdicts, findings and the compact JVPR2 markers match v5 in
all 52 rows of both arms; the 24 nonreview rows keep their bytes; every
analysis has two sentences; the forbidden list finds nothing.

Two results did not match the letter of the brief. Every review prompt carries
one shared suffix asking for the analysis, 104 of 104 rows. The production
renderer does not append it, so an explanation-first winner must ship the
suffix with its weights. Pair parallelism as first declared also failed, 24 of
26: both failures are introduced/repaired pairs, where the members review
mirrored diffs and `[4]` names `atoi` on one side and the validated cast on the
other. The measure compared coordinates the two diffs do not share. That count
stays in the record. The replacement, declared after the defect, keeps
number-set equality for the 18 same-diff pairs and compares cited diff sides
for the 8 mirrored ones: 26 of 26. No explanation was edited.

The checker was also made to fail. Ten targeted mutations each fail their
check; one early mutation changed nothing and was rerun, the record keeps both.
The native JVPR2 path reproduces the preflight evidence byte for byte on both
arms. A reader with no session context judged sixteen rows from eight seeded
pairs: their own verdicts matched v5 on all sixteen before any analysis was
shown, and all sixty premises of the analyses were found in the prompts.

Evidence: [`training/results/2026-10-03-v6-acceptance`](training/results/2026-10-03-v6-acceptance).

## 2026-10-03 — The workspace vanished. The receipts did not.

The next session reported automated workspace maintenance. The local repository,
model files, archive environment and original trainer processes were gone.
The last interactive observation had been before update 48. A fresh read of
private `ataeff/jovovich` found a later immutable head,
`a8013d35d46c5ccfe2fd4d1a95ecf8a6f5f9c825`: 60 closed units comprising the
launch intent and updates 0 through 58. No completion, after or evaluation
unit was present. Exact process termination timing is not established.

`DurableArchive.recover` restored the complete prefix from that pinned revision
and verified every referenced payload: 192 unique payloads, 164,281,543 logical
bytes across the manifests. All six weight files survive for each checkpoint
at updates 0, 25 and 50. The per-update metric segments reconstruct exactly
into the published 677,871-byte partial journal. An independent auditor rehashed
all 247 restored logical files and recomputed every native decision/pair aggregate.
The original private archive is unchanged; the interrupted attempt keeps its
original run ID.

At update 58, the native teacher-forced record reports 32/52 decision tokens,
7/26 exact decision pairs and joint CE 2.88287829. These are measurements from
an incomplete first arm, not a matched order comparison or a natural-generation
result. The planned update-100 endpoint has not been reached.

The snapshots contain LoRA weights and merged matrices, without Chuck controller
or optimizer moments. Loading checkpoint 50 would not resume the same trajectory.
The frozen recovery policy therefore requires a fresh 0-to-100 attempt with a
new ID. Move that attempt to a persistent Linux host which keeps the process
alive through both arms and evaluation. Remote evidence storage succeeded;
it cannot preserve unexported optimizer RAM after the compute host disappears.

The exact public base was restored and hash-checked; current sources rebuilt.
Fresh native preparation again passed all 304 ChatML comparisons and the complete
launch preflight. No replacement training was started in this transient workspace.
A reviewed host launch recipe accompanies the recovered evidence; weights remain
in the private archive, and source/protocol bindings are regenerated on the host.

Evidence and recovered metric prefix:
`training/results/2026-10-03-order-recovery/`.

SERGE kept the receipts. The cigarette remains singular.

## 2026-10-03 — The witness brought an unlisted colleague.

PR #21 review found that `score_decisions.py` imports `summarize` from
`score_training.py`, but the latter was absent from the frozen file lists.
Changing that imported file could alter the teacher-forced diagnostic reports
without triggering the evaluator's source guard. The independent import audit
confirmed this omission; the other repository imports in the inspected
training, continuation, export and generation paths were already covered.

New launch preparation binds the complete diagnostic trio: `score_decisions.py`,
`score_training.py` and `prepare.py`. The evaluation contract requires those
files, and continuation freezes them too. The documented fresh-run recipe also
needs the export/parity/inference executables and their supporting sources;
launch preparation now includes the evaluation contract's required files and
resolves its packed-input paths before freezing either arm. Historical launch
plans and their evidence retain the bytes actually executed.

The live `order-20261003-01` chain remains on its original frozen checkout.
At the recorded observation, before update 36 had a verified HF receipt and
there was no training failure. The omitted scorer is 7,249 bytes with SHA256
`5f0dfce44eef8b6cc9bf7aa9d42b8f346386576001b42676a619deb4a399cf33`,
identical to its prelaunch Git version. This observation does not retrospectively
add it to either frozen plan.

Treat this run's teacher-forced diagnostic reports as provisional until they
are reproduced from the archived metrics and corpora using an explicitly bound
copy of that scorer and its companion scripts. Compare every scientific field
and both input hashes; document only the literal `metrics` and `sft` path
substitutions if archive recovery changes those paths. The fixed update 100
training/export choice and the natural-generation sequence do not use
`score_training.summarize`. The ongoing run continues without source changes.

The 22 focused launch, evaluation and continuation tests pass, including an
independent rerun. The new fixture
prepares a fresh contract at custom packed-input paths, binds the second arm,
admits both completed endpoints, then rejects a same-size edit to the imported
scorer before diagnostics or uploads. It also rejects internally consistent
historical receipts that omit the scorer binding.

Evidence: `training/results/2026-10-03-diagnostic-binding/`.

SERGE requests that imported witnesses sign the attendance sheet.

## 2026-10-03 — The binary must answer before the woman does.

PR #20 review found a concrete startup gap: the launcher could bind a stale
trainer's checksum without checking whether that executable supported archive
acknowledgements. The exact binary now answers `--archive-protocol` before it
receives any model or dataset arguments. Its live process then requires an
`archive_hello` / `START` handshake before opening either input. Missing or
silent startup is bounded; the capability and binary identity are checked
again after the remote intent barrier.

Independent native tests pass all 22 failure scenarios. Eight Chuck updates
with the gate remain bitwise identical to the control, with the same initial
adapters and scorer metrics. A fresh native preflight passes all 304 ChatML
comparisons and preserves the matched 52 decision / 3411 residual targets.

The supplied credential verified private `ataeff/jovovich`; a fresh upload and
pinned-commit download matched byte for byte. Both launch plans freeze the
same 15-minute archive ACK deadline, allowing transfer and fresh readback of
each roughly 53.4 MB checkpoint. The before arm has started after its verified
remote intent, with 100 updates and its evaluation contract fixed in advance.
That contract selects epoch 100, checks every exported tensor byte, checks
native parity on five fixed representative rows, then collects 228 responses.

The initial checkpoint's ten archived payloads total 53,492,858 bytes; their
local bytes match its remote receipt. The saved progress snapshot covers
updates 0 through 8. Inter-acknowledgement intervals for the first two updates
are about 62 seconds on this CPU. The run remains active.

`execute_evaluation.py` implements the fixed export, diagnostic, generation
and prompt-comparison sequence. `continue_experiment.py` waits for verified
before completion and the original archive parent to exit, then runs the
matched after arm and evaluation. It binds PID/start-time identity, source
hashes and plans, with one HF writer at a time. Each helper passes nine
focused tests and a separate independent rerun. The continuation process is
running; its immutable plan and current activation record are included below.
Native evaluation ends with semantic review pending for the independent
reviewers.

Startup evidence and launch bindings:
`training/results/2026-10-03-explanation-order-run/`.

## 2026-10-03 — SERGE moved the comma. The tokenizer noticed.

All 52 v5 reviews now have a short explanation tied to the supplied rule,
context and changed lines. The before and after corpora contain the same
explanation and original findings; they differ in top-level field order.
Their user prompts share one order-neutral request for analysis. All 24
nonreview rows retain their original bytes. A separate auditor read every
explanation and checked the builder's evidence anchors and corpus isolation.

The first full native preflight caught a serialization confound. When an empty
findings list ended the object, Qwen chose ID 788; when analysis followed it,
the clean target became 8899. Concern remained 66582. We retained that failed
attempt, its datasets, native traces and exact bound source bytes. Both arms
now put a newline after every top-level value, before the following comma or
closing brace. The compact findings-array boundary stays intact.

The repeated native check passes all 52 rows: identical prompts, findings,
explanations, target/alternative IDs and individual answer lengths. Each arm
has 52 decision targets and 3411 residual targets. Before-verdict positions
range from 40 to 58; after-verdict positions are all 3. All 304 native
trainer/runtime ChatML comparisons match. The longest complete gold answer
uses 99 tokens including EOS; the common generation allowance is 512.

The frozen comparison design uses two fresh processes, identical initialization
and 100 Chuck updates each; update 100 is the fixed primary checkpoint.
The shared base and both final models will generate all 52 training and 24
heldout reviews, 228 responses total. The collector ends the prompt at the
empty assistant header, verifies its native token IDs before inference,
and archives each closed case before proceeding. The scorer records findings
classification, canonical citation IDs, analysis presence, field order and
complete-pair counts separately. Full-response semantic judgments have their
own row-level audit. Holdout gold remains outside the model input.

Long training now has a synchronous archive boundary. With
`JOVOVICH_ARCHIVE_ACK=1`, the native process writes an initial snapshot and
pauses after every completed update. The parent closes immutable log segments,
uploads them with any new checkpoints, verifies the remote bytes, then sends
the exact update ACK. The same live process retains Chuck state. The second
arm checks its initial LoRA hashes against the first before taking an update.
A candidate native-completion record becomes verified completion only with
the final remote receipt.

On the tiny native fixture, eight gated Chuck updates produce byte-identical
final weights to the uninterrupted control. Eleven archive units are read
back; seventeen fault scenarios exercise failed uploads, corrupted readback,
source changes, initialization mismatch, invalid control records and bad ACKs.
The generation collector separately checks tokenization, gold isolation,
environment isolation and final-receipt failures.

The final suite passes nine native executables and 151 Node tests. The launch
handoff verifies the first arm's archived plan hash, identical training
settings and all shared input bindings before resolving the second template.
The independent audit records all findings and their fixes; its final status
has no open code blockers.

The real-model work in this entry is tokenization. The full-model training
and 228 generations await the private archive credential: the previously
supplied HF token is unavailable in the current environment, and the uploaded
attachment could not be located. Code, prepared data, executable launch
templates, failed and successful preflights, tests and independent audit are in
`training/explanations/` and
`training/results/2026-10-03-explanation-order/`.

## 2026-10-03 — The verdict has an address.

The explanation-before-verdict path now has a versioned position contract.
JVPR2 stores original concern/clean row indices and a separate length-prefixed
UTF-8 answer prefix for each row. The prefix ends before the closing quote of
the actual top-level findings key. Python locates that key structurally, so
quoted mentions of `findings` and nested objects do not move the boundary.
Duplicate JSON keys, escaped top-level keys and non-object findings are
rejected by preparation. Tokenization remains native.

The C loader verifies exact prefix bytes, the structural findings boundary,
compact concern/clean continuations, native prefix IDs and a non-EOS target.
For each row it then joins that row's own prefix to the opposite findings
suffix and re-tokenizes: the prefix IDs must remain identical and the next
token must equal the reciprocal alternative. Each row keeps its own position
through decision weighting, joint normalization, prefix diagnostics and the
gradient probe. JVPR1 retains its original byte layout and first-divergence
selection.

The independent auditor found a concrete formatting trap before acceptance.
On the pinned Qwen tokenizer, a concern answer with a space before the colon
selected ID 1, a quote; spaces just inside the array could select ID 8899,
`":[`. All three reproduced variants now fail in both Python and native C.
Canonical concern/clean targets remain 66582 and 788. Their decoded widths
differ: the concern token contains `":[{"`, while the clean token is `":`
and its following token supplies `[]}`. Counterfactual tokenization checks this
actual segmentation directly.

Initial native metrics now include `pair_map_version`, exact `decision_prefix`
and `decision_prefix_bytes`. The scorer compares the text and byte length with
the corpus before recording its SHA256. An independently tested same-byte-length
replacement of an explanation is rejected. Legacy metrics without a version
continue through V1; their archived scores reproduce exactly.

The official Qwen2.5-Coder-0.5B-Instruct Q8_0 was restored and verified against
SHA256 `e1a77721fa97d412f121878223eec81fb4ae6f271e18f922d746711f67b344d1`.
The native tokenizer check preserves all 52 existing v5 review positions,
target IDs and alternative IDs. JVDS bytes match between V1 and V2. Six
additional boundary-fixture answers use unequal explanations, Cyrillic,
escaped quotes and nested findings decoys:

| Pair | V1 positions | V2 positions |
| --- | --- | --- |
| Scoped Python analysis | 4 / 4 | 18 / 21 |
| Approved binary decoder | 4 / 4 | 35 / 10 |
| SQLite build requirement | 3 / 3 | 34 / 35 |

All positions are zero-based completion indices. All 164 native
trainer/runtime ChatML comparisons match. These checks execute tokenization;
their process receipts record zero inference calls and zero training updates.

The new C fixture exercises four independent decision positions and 230
residual targets. Three microbatch sizes match 42 independent adapter
derivatives, with maximum loss error `2.56041e-6` and gradient error
`6.24449e-8`. Its 26 rejection cases cover stale prefixes, whitespace and role
conflicts, invalid maps, EOS, BPE boundary crossing and capacity overflow.
A separate fixture preserves Qwen's asymmetric clean/concern token widths.
The complete suite passes nine native executables and 119 Node tests.

The first full-suite attempt stopped at sandbox subprocess input: even
`node -> cat` received its bytes but failed to finish on EOF. The identical
minimal command completed outside the sandbox. We preserved that interrupted
attempt and reran the same suite outside the sandbox; it passed with every
bound source hash unchanged. Both receipts and the isolated reproduction are
retained.

Before publication, Oleg merged Fable's PR18. The integrated branch retains
its notorch pin `014403faa76b795aefe18a4781980f5b140e0ed3` and all four Chuck
calls; the only textual conflict was the Makefile's phony-target list.
After rebuilding, nine native programs and 119 Node tests pass again, and
`integration/native-rebuilt/` repeats the official-Qwen check: 52 unchanged
legacy decisions, three unequal-position pairs and 164 ChatML matches.
The earlier `integration/native/` attempt ran before the rebuild completed;
its binary bindings are preserved separately. A build log without assertion
output was followed by a complete test-only capture. Node used its spec
reporter, which the separate validation receipt checks explicitly.

The optimizer audit exercises the actual trainer mains on a deterministic
one-block synthetic Qwen fixture: twenty joint MLP steps, twenty token-objective
MLP steps, twenty head SFT steps and twenty head DPO steps. All eighty calls
execute native Chuck updates, preserving controller and moment state through
interleaved diagnostics and resetting at the SFT/DPO boundary. Explicit review
positions remain 39 and 28. The recipe and call-level evidence are in
`integration-chuck/`; this closes the four-call-site coverage gap noted in
Fable's original optimizer receipt.

A separate auditor recounted the three-body study's 75 stored summaries and
checked their manifest hashes and token traces. Its best cell is plain
instruct block 0, 32/52 and 8/26 pairs, below the lexical 35/52 and 9/26.
The historical runner's extraction-reuse path does not verify original input
bindings, and its raw matrices/fits have no committed remote archive receipt.
New collection continues through the existing durable launcher. The audit
and historical source/hash mappings are in `integration/claude-study-audit.json`.
The README now states the measured comparison without attributing block 0's
successes to particular surface features.

Code, raw token traces, preparation outputs, independent audit and verification
recipe are in
[`training/results/2026-10-03-verdict-positions`](training/results/2026-10-03-verdict-positions).
The next step is the complete paired explanation corpus, its independent
content audit and a frozen comparison with matched generation budgets.

SERGE may explain why the abstraction offends him. We now know where he casts
the vote.

## 2026-10-02 — Twenty-four floors. No secret penthouse.

The frozen Qwen2.5-Coder-0.5B-Instruct Q8_0 depth survey completed with all
2,100 native fits converged: maximum gradient infinity norm
`9.634049100148978e-9`, maximum 17 iterations under the frozen limit of 100.
The model and native trainer bytes were unchanged. We collected all 24
post-block residuals at two exact native positions for every one of the 52 v5
reviews: the assistant-header end and the end of shared prefix IDs
`[4913,3903,819]`, decoded as `{"findings`. A separate fresh-KV pass collected
the pre-final-MLP prefix anchor. Labels and gold answers stayed outside the
model input.

Each state view received an affine readout with fixed ridge 0.01, training-fold
normalization, leave-one-family-out evaluation over all 20 families, and the
same predesignated family-flip control. Pairs and quartets stayed together.
The table reports the observed-label results; blocks are numbered 1–24 here.

| View | Correct / 52 | Complete pairs / 26 | Same-full-diff pairs / 6 |
| --- | ---: | ---: | ---: |
| Header block 8, maximum within its boundary | 30 | 4 | 2 |
| Prefix block 4, maximum within its boundary | 29 | 3 | 3 |
| Header block 24 | 26 | 1 | 1 |
| Prefix block 24 | 27 | 1 | 1 |
| Fresh pre-final-MLP prefix anchor | 27 | 1 | 1 |
| Seven-feature lexical/count baseline | 26 | 1 | 0 |

Header views span 25–30 correct reviews and 0–4 complete pairs; prefix views
span 25–29 and 0–3. The complete profile does not exhibit a strong early
readout followed by its disappearance at the tail. Moving to the shared JSON
prefix also does not provide a general improvement. Across the 49 state views,
observed labels beat the single fixed flipped-label control on row accuracy
in 21 views, tie in 10, and trail in 18. This is one descriptive control, not
a permutation significance estimate.

All 49 state views interpolate 52/52 observed and 52/52 flipped labels at
ridge `1e-8`. Their capacity to fit the development rows is therefore present;
transfer to held-out families is the measured weakness. The same-full-diff
subset reaches 3/6 complete pairs at header block 7 and prefix block 4, and
1/6 at either final boundary. The full 50-view table remains exploratory,
with no selected runtime layer. The fresh v5
anchor is the within-run comparator; the older v4 anchor used different
prompts and is not a depth-only comparison.

Independent verification parsed 2,283,008 finite float32 coordinates and tied
all 49 state matrices to their 2,548 source vectors byte for byte. The auditor
derived all 20 families and the six same-diff pairs directly from the corpus
and independently recomputed all 364 lexical/count values. Two separate
postrun scripts agree on all 2,100 fits, 1,050 normalization memberships and
10,400 predictions. The first two collection rows passed token-step and both
future-token invariance checks with zero measured discrepancy.

The completion marker is remotely verified at private HF revision
`c2c592f77a0548d8f50077af35654950ca591ef3`, sequence 209: all 210 archive units,
including bootstrap and completion, have receipts. The real interruption and
successful continuation are recorded below. The public deterministic archive
contains all 748 raw evidence files, 35,703,965 compressed bytes, SHA256
`9fcd318c6586904f8c41a2b08c899ec5cfed1e5a42e6b2a6efcda310e7cd8518`.
It retains every row, matrix, native fit, trace, process log and phase receipt;
the bound source/binary snapshots remain in the private archive. Readback
checked every tar member against its size and digest before publication.
GitHub transport rejected the full-size request, so the same archive is
published as twelve 3 MiB-or-smaller pieces. Their manifest records individual
hashes and the reassembly command; byte-for-byte reassembly was checked against
the original archive. The assembled file is a reproducible ignored artifact.

Code and evidence are in
[`training/results/2026-10-02-layer-readout`](training/results/2026-10-02-layer-readout).
Validation also includes eight native test executables, 108 Node tests,
24 focused archive/launcher cases and nine independent packer scenarios.
Final source review found no remaining actionable issue. The normal review
runtime, reusable workflow, notorch pin and production trainer remain unchanged.

The next useful intervention is a controlled explanation-before-verdict arm,
with matched data and generation budgets. Its prerequisite is concrete:
`train_mlp.c` currently takes the first different answer token as the paired
decision position. Different explanations would send the extra joint weight
to an explanation token. `prepare.py`, the native pair loader and
`score_decisions.py` need a versioned per-row verdict-boundary contract, tested
with unequal explanation lengths and early explanation differences. The cache
already supports longer answers. Generated explanations must be produced by
the model during evaluation; the data/eval change alone is insufficient for
the current joint objective.

SERGE has one cigarette. This run has 210 remote acknowledgements.

## 2026-10-02 — The next question waits for the receipt.

The maintained research archive writes immutable, content-addressed objects
and an ordered manifest chain into the private `ataeff/jovovich` repository.
Each unit commits against an exact parent revision, downloads its new payloads
again and checks their SHA256 and byte counts. The layer launcher first saves
the protocol, bound sources and prepared inputs, then a durable intent before
each process and a verified result before starting the next. Failed validators
leave their output and stop the sequence. Recovery reconstructs logical files
from remote manifests into a fresh directory and preserves interrupted units.

The real HF smoke saves a bootstrap, commits a synthetic payload and deliberately
drops the acknowledgement after the server accepted it. The identical retry
finds the existing commit and verifies its bytes without another commit. After
deleting the owned local test directory, a fresh archive instance restores all
four logical files with exact SHA256 matches. The completion marker is verified
at `c7b46235c3e3be02f803602120579a5911c96125`. The protocol, source, individual
receipts and independent failure tests are in
[`training/results/2026-10-02-durable-sync`](training/results/2026-10-02-durable-sync).

The optional research transport uses pinned `huggingface_hub==0.35.3`. All
model arithmetic and fitting remain native C/notorch. The normal review runtime
keeps its existing dependencies. SERGE can lose the lighter. The result gets
a remote receipt before he reaches for the next one.

The first layer collection also encountered a real controller interruption:
the execution service reported that network approval was cancelled. At the
recorded private revision, 27 row results were durable and the next row's
intent was saved. That row had already completed locally, including its
validator. An independent check verified all 273 local files, 28 closed phases,
their exact commands and artifact hashes, and the unchanged host and bindings.
The continuation controller uses the original frozen launcher: it re-verifies
the existing remote units, publishes the original pending result, then advances.
It reached `row-028` at 02:27:09 UTC without rerunning the 28 completed model
callbacks. The interruption, remote tail, continuation source and independent
audit are preserved in the layer-study directory.

## 2026-10-02 — No depth was hiding it.

The per-layer readout ran on all three bodies: 25 depths each, 2002 native fits
per depth, 150150 fits in total, every one converged, maximum gradient infinity
norm 1.0e-08 against the declared 1e-08 tolerance. The table is in
training/results/2026-10-02-layer-readout-three-bodies/combined-table.md with no depth and no
body left out, and the receipts are beside it.

Twelve of the seventy-five body-depth cells clear the declared floor of 29/52
correct and 4/26 complete pairs: l00, l03 and l22 on the coder base, l00, l01,
l10, l11 and l17 on the plain-instruct twin, l00, l06, l16 and l23 on the
abliterated coder twin. Zero of the seventy-five reach the published
seven-feature lexical baseline of 35/52 and 9/26. The strongest cell anywhere is
the plain-instruct twin at block 0 with 32/52 and 8/26, exceedance 0.02; the
coder base peaks at 31/52 and 7/26 at the same block 0 and at block 3; the
abliterated twin's best complete-pair counts sit at blocks 0, 6, 16 and 23 at
5 to 7 pairs.

Block 0 is the only cell that clears on all three bodies, at a decision
position whose own token is identical in all 52 rows. The seven token-count
and diff-shape features outperform every tested body-depth cell. The final
post-norm z is the weakest row on the coder base at 24/52 and 0/26. The profile
does not identify the features behind block 0's successes, and supplies no
compelling "unfreeze here" instruction for the next training run.

What this does not say. The declared reading was fixed per depth and carries no
multiplicity rule; applied to seventy-five cells, an exceedance near 0.01 is
expected to turn up about once by chance, so the scattered cells that clear the
floor are not twelve findings. A negative at every depth does not prove the
information is absent: it bounds what an affine probe at lambda 0.01, on 52 rows
with 20 template-family folds, can read at a supplied prefix. A nonlinear head,
another position, or another corpus is a different experiment and needs its own
frozen protocol.

The instruments were proved before the bodies were read. The audit reproduces
the published 2026-10-01 z summary from the published fits on all 27 compared
fields, including all 99 reference statistics and all 52 scores to seventeen
digits. A direction planted in one block of a hand-built four-block body is read
at that block and above and not below it, the boundary moves when the plant
moves, and with the plant removed every depth reads 26/52 and 0/26 — the probe
invents nothing. All three bodies produce a token trace byte-identical to the
published extraction's, so the decision positions are the published ones and the
three tokenizers agree. The three extractions took 2436, 2166 and 1808 seconds
on neo.

## 2026-10-02 — The trainers take the Method's own step.

The notorch submodule moves from 7e246e13f9dbbb7e61312b7341fb94ce492bff71 to
014403faa76b795aefe18a4781980f5b140e0ed3, an ancestor-to-descendant bump, and
both native trainers now call `nt_tape_chuck_step(lr, loss_val)` where they
called the diagonal baseline: train_head.c:200 for the per-example SFT step
with that example's cross-entropy, train_head.c:227 for the per-pair DPO step
with the pair loss rather than the weighted surrogate whose value is not a
loss, train_mlp.c:534 for the one accumulated step per epoch on the joint
objective with that epoch's online joint loss, and train_mlp.c:538 for the
per-microbatch step with that microbatch's loss. The contract was read before
the swap (notorch.h:255, notorch.c:2523): the step takes its gradients from
the same tape entries as the previous call, and `loss_val` enters only the
Chuck controller — the loss EMA, a sixteen-slot window, a quartile trend with
brake and push at two percent, stagnation noise after eight flat steps, and a
macro patience that scales the rate every thousand steps. One call is one step
for every one of those counters, which is what makes the accumulated joint
step well defined. `reset_optimizer` clears the Chuck state with the moments,
since `nt_tape_destroy` zeroes the whole tape.

Receipts in training/results/2026-10-02-optimizer-law/: build rc 0 with zero
error lines after `make clean`, and `make test` run at the same pin on both
sides of the swap — seven C binaries pass with byte-identical assertion lines,
Node reports 84 tests, 77 pass, 7 fail, the same seven names before and after.
Those seven are pre-existing and environmental: test/readout_workflow.test.mjs
compares a recorded temporary path against the macOS /private/var realpath of
the same directory, and that file references no build artifact at all.

What this is not. The suite does not execute the four swapped lines — the C
tests include the trainers with `main` renamed and drive their own update
loops against their own diagonal oracle — so identical output shows the swap
broke nothing those tests check, and nothing more. No equivalence of training
outcomes is claimed, in either direction: nothing was trained here. Whether
the Chuck controller helps this corpus is an experiment that has not been run.

## 2026-10-02 — Where does the judgment live?

Frozen before any state extraction: the per-layer affine readout protocol
(training/results/2026-10-02-layer-readout-three-bodies/PROTOCOL.md). The published
final-position diagnostic said the tail barely separates concern from clean —
29/52 correct, 4/26 complete pairs, against 35/52 and 9/26 for seven surface
nuisance features — so the probe asks whether any decoder depth carries what
the tail loses, on the model.json-pinned coder base, on its plain-instruct
twin, and on its abliterated coder twin. One affine fit per layer per body,
the published procedure verbatim, nothing adopted and nothing gated by the
result. The Run preservation rule above governs this probe's own receipts;
no separate sync clause is written for it.

## 2026-10-02 — The selector arrived before the review did.

A newly frozen diagnostic compares the recovered v5 update 25 with update 100
on the same 24 transfer prompts: twelve concern/clean pairs across six families.
Both use the natural production prompt, exact Qwen ChatML, no supplied answer
prefix, temperature zero and a 192-token cap. These cases have already been
inspected; this is repeated diagnostic evidence, not untouched confirmation.
Training and the historical checkpoint selector are unchanged.

Both exported models pass independent metadata and byte-payload checks across
all 291 tensors, with exactly three adapted projections and 288 unchanged
tensors. Cached/full-model parity matches 92/92 completion-token argmax choices
in each arm. All 48 new responses, native prompt/generated IDs, stop reasons
and process records are preserved. They do not recreate the lost 176-response
historical archive.

Two judges independently read every complete prompt and response before
comparing their locked results. All 48 primary and strict outcomes agree.

| Repeated transfer diagnostic | Update 25 | Update 100 |
| --- | ---: | ---: |
| Production-usable responses | 16/24 | 20/24 |
| Grounded concern reviews | 1/12 | 0/12 |
| Correct empty clean reviews | 0/12 | 10/12 |
| Full individual reviews | 1/24 | 10/24 |
| Complete concern/clean pairs | 0/12 | 0/12 |
| EOS / token-limit stops | 16 / 8 | 23 / 1 |

The sole accepted update-25 concern awkwardly connects removed final-byte
zeroing with the required termination property. A strict rule-echo reading
reduces its concern and full-review counts to zero; pair results stay zero.
All twenty usable update-100 responses are empty, including ten missed defects.
The remaining four finite-number responses invent a division mechanism, lose
valid citations or repeat until truncation. Better formatting and more correct
clean answers therefore do not establish better discrimination.

The earlier-update tie-break materially affects the visible failure pattern.
This comparison does not prove why the model fails, that longer training will
solve it, or that the matched corpus itself caused the earlier regression.
Neither checkpoint earns runtime promotion. The final-position information
claim remains a hypothesis to test separately.

An audit caught Python `assert` gates in the already launched frozen helpers.
Those executed bytes are retained. A separate validator repeats the actual
291-tensor payload checks, parity thresholds and every response/trace binding
using explicit exceptions; it passes under `python -O`, verifying 45 frozen
bindings. The replay wrapper refuses optimized Python before invoking the
historical helpers. This is a documented post-run validation, not a claim that
the original helper design was robust to optimization. Production parsing is
also independently repeated on all 48 saved responses.

Complete new evidence, both rubrics and judgments, their reconciliation and
the guarded replay entry point are in
[`training/results/2026-10-02-checkpoint-control`](training/results/2026-10-02-checkpoint-control).
The final `make test` gate passes seven native executables and 84 Node tests.
Copilot's PR #14 request for the partial-stderr-open regression was already
fixed before merge and remains covered. SERGE has one cigarette. The selector
does not get a second one for selecting a shorter answer.

## 2026-10-02 — The derivative has an alibi. A limited one.

The public Q8 base and all sixteen private matched-run files are recovered from
their pinned revisions and pass fresh SHA256 and byte-count checks. These are
new recovery receipts, not the missing original training trace. A subsequent
platform notice identifies automated scratch maintenance as the cause of the
broad workspace loss. That updates the earlier unresolved incident; it does
not establish the cause of the separate transient GGUF-prefix anomaly.

An independent value-only oracle now checks the synthetic joint objective's
gradient. All 84 coordinate differences pass across nonzero-adapter and zero-B
states. At zero B, all twenty A derivatives are exactly zero while all three B
tensors receive a signal. Deliberately dividing the accumulated production
gradient by two fails the new test. The mutation is removed; the trainer is
unchanged. This is a test that can object, not just applaud.

The new native `probe-gradients` checks actual Qwen dimensions and recovered
adapters at initialization, update 25 and update 100. It compares production
backward with an independently written, double-precision value-only suffix:
LoRA, SwiGLU, residual, final normalization and the full vocabulary loss. Four
fixed targets from two training rows retain their original coefficients,
`1/52` for a decision and `1/1012` for a residual target. Each of the six A/B
tensors gets a maximum-gradient coordinate and a seeded unit random direction.

All 36 directions satisfy the frozen agreement and stability gates at the two
finest step sizes. Initial A gradients correctly vanish; all expected active
tensors have resolved coordinate coverage. Four random directions have too
little signal for active coverage and remain explicitly inconclusive. Of all
144 individual step-size comparisons, 143 pass: update 100's `up.B` coordinate
66819 fails at the coarsest step, 0.01, while its finer steps pass. The failed
coarse comparison is retained. The largest baseline full-logit discrepancy is
0.0000495863. No optimizer step occurs, and all input and parameter guards pass.

An independent auditor recomputes slopes, tolerances, stability, target indexing
and all 27 file bindings from the raw records. The saved records contain scalar
derivatives and discrepancy summaries, not complete gradient or logit arrays.
This supports the sampled derivatives of the cached final-MLP suffix. It does
not validate every one of the 1,064 targets, earlier layers, optimizer dynamics,
or the claim that semantic signal disappears at the final position.

The frozen protocol, native output, synthetic negative control and audits live
in [`training/results/2026-10-02-gradient-control`](training/results/2026-10-02-gradient-control).
The native trainer and notorch pin remain unchanged. SERGE examined the
derivative. The cigarette remains singular.

The next procedural diagnostic separates decision, concern-residual and
clean-residual gradients at fixed checkpoints. The 26 concern rows contribute
882 residual targets; the 26 clean rows contribute 130. Under the current
pooled residual mean, their combined decision-plus-residual coefficient masses
are 1.37154 and 0.62846. Those are coefficients, not measured gradient norms or
proof of conflicting updates. A class-balanced residual objective would be a
separate intervention, with total residual weight held constant.

Fable's layer/position hypothesis needs its own collector: ordinary post-block
residuals at the assistant-header and shared-prefix boundaries, with the old
pre-final-MLP state retained as a distinct anchor. Layer selection belongs
inside family-grouped evaluation, followed by previously unseen confirmation
families. The existing 24 transfer cases have already been inspected. Reading
information from an earlier layer would establish accessibility under that
probe, not its use in generation. Rationale-first generation is a separate
test; supplied gold rationales would leak the answer. These are planned
experiments, not additional results of the derivative control.

## 2026-10-01 — The archive lost its floor.

During final publication, local files disappeared across multiple working
folders, including the matched run, evaluations, semantic judgments, independent
audits and the local Git directory. At 15:42:48 UTC the selected model was absent
and its artifacts directory was empty. Two independent agents observed the same
loss; none reported issuing cleanup. The cause is unresolved. This later broad
loss must not be assigned the same cause as the earlier transient GGUF anomaly.

The collector's read-only material check had just passed for 373 files and
8,248,571 payload bytes, with 32 bound repository sources. The subsequent write
failed on a missing selected GGUF before creating its output directory. No
completed matched-review manifest or byte-preserved public bundle exists. The
results reported below were read and independently checked before the loss;
their raw responses, full judgments and training receipts are now unavailable.
Known hashes identify those missing originals, but cannot replace them.

The separate external-forward archive survived as already uploaded Git objects:
158 files, 12,232,383 bytes, tree `30470619bc523273a76998903f33c11f943f0a30`.
README and this log were copied into a surviving tool buffer. The selected model,
adapters and three packed/data inputs had already passed verification in private
HF revision `c9484feec99c5df47be5702d29098297aced1389`. They can support recovery
or a newly labeled evaluation; they cannot recreate the original training trace.
The new [`evidence-loss.json`](training/results/2026-10-01-matched-review/evidence-loss.json)
records availability and previously observed identities without fabricating
missing payloads. The external archive and these surviving records are published
now; the full matched-run archive remains incomplete.

## 2026-10-01 — A falling loss curve has not earned a verdict.

The matched v5 experiment completes 100 native updates with every bound source
and input unchanged. Joint CE falls from 4.75684598 to 1.37147876. The residual
component falls from 2.73500350 to 0.67996486, while decision CE ends at
0.69151390. All 101 measurements were recorded before the later loss, including the
transient decision pair successes between saved checkpoints.

The eligible updates 25, 50 and 100 each have zero complete decision pairs.
Their individual target counts are 26, 25 and 26 out of 52. The prespecified
tie-break selects update 25, before natural generation. The prior v4 procedure
selected update 100. This difference is part of the fixed selection procedure;
the comparison does not hold the selected update constant. Update 75 and the
better transient measurements were recorded without becoming eligible;
their payload is now unavailable.

The first postprocess attempt completes selection, export and its byte audit,
then stops on a changed-model binding. Its final failure snapshot contains
674,725,888 bytes: an independently verified exact prefix of the original
714,116,992-byte export. Subsequent reads again match the original full SHA256
`277b20bc0367584c9b442c4eb1c9093d66098fd6898c7e9f2620e2ef7349f532`.
The precise bytes seen by the first rejecting guard were not logged; the prefix
claim applies to the preserved final failure snapshot. The exporter closes its
output before success, and the audit opens it read-only. The source of the
transient truncation and restoration remains unresolved.

A separate, independently reviewed continuation preserves the failed receipt,
checks the original full export and all carried bindings, and runs only the
unfinished native parity check. Training, selection and export are not repeated.
All three parity rows pass, with 92/92 completion-token argmax matches and maximum
CE difference 0.0000027418. The full model hash and file identity remain unchanged
through the check. The failure is evidence, not a successful model artifact.

Natural generation then completes all 88 cases for each selected model on the
same v5 prompts. The primary evaluator and independent auditor agree on all
88 new outcomes. The old judgments remain unchanged. Production-usable responses
fall from 83/88 to 62/88; grounded concern reviews remain 2/44, while correct clean
reviews fall from 36/44 to 4/44. Full individual reviews are 38/88 versus 6/88.
Complete concern/clean pairs are **0/44 in both arms**: 0/26 training, 0/12 fresh
transfer and 0/6 established diagnostics.

The new full reviews split into 5/52 training, 1/24 transfer and 0/12 diagnostics;
the corresponding control counts are 24/52, 9/24 and 5/12. One transfer answer
awkwardly describes the removed required final-byte zeroing. The accepted reading
and a strict rule-echo alternative were both recorded before the loss: the latter reduces the
new total to 5/88 and grounded concerns to 1/44, without changing any pair result.
Eight harmless empty-list grounding conventions differ between the independent
working notes and primary records; none affects the final verdicts.

The selected GGUF, twelve saved adapters and three data/packed-input files are
archived privately in `ataeff/jovovich` at revision
`c9484feec99c5df47be5702d29098297aced1389`, under `experiments/matched-review/`.
All sixteen files pass a pinned-revision download and SHA256/size check. The
single upload commit, initial verification failures and read-only timeout retry
were recorded in the receipts before their later loss. No model weight enters
GitHub or replaces the runtime model. The intended public bundle included the
independent audit, raw token traces and all 101 training measures; its write did
not complete, as documented in the later incident above.

This matched-data intervention fails to improve the primary pair outcome under
the fixed training and selection procedure. Its selected model also regresses
on usable output and clean cases. Different selected updates, one seed and the
limited final-MLP budget prevent attributing that regression to one mechanism.
The next diagnostic should map transferable signal across layers using our exact
Qwen prompt, explicit capture boundaries and grouped evaluation, with layer
selection separated from untouched confirmation families. SUBLITERATUS supplies
a useful collection pattern below. It does not supply this experiment's verdict.
SERGE has not lit a second cigarette to make the loss curve look warmer.

## 2026-10-01 — The arithmetic witness brought all the logits.

The exact original 0.5B Q8_0 body had token-ID and generation comparisons, but
no full-logit external check at the review decision boundary. A separate native
diagnostic now compares notorch with pinned llama.cpp on one fixed allocation
guard concern/clean pair. Each input has 444 prompt tokens; captures occur after
the assistant header and after the shared three-token answer prefix. No sampler,
tokenizer difference, class-specific answer prefix or checkpoint selection is
involved. Each capture preserves all 151,936 logits and its exact input IDs.

The original Q8 comparison agrees on all four argmax choices, but exceeds the
prespecified numerical screening thresholds. This requests arithmetic alignment;
it does not establish a bug. llama.cpp's Q8 path quantizes activations, whereas
the native run uses `NT_NO_I8=1`.

A native converter expands the original stored tensor values to F32. Independent
verification checks every value in all 291 tensors, their names and shapes, the
file layout and all 26 typed metadata keys. Only the storage file-type field
changes. All tensor values are bitwise exact and finite before either engine
is allowed to use the converted file.

| Fixed four-capture comparison | Maximum absolute logit difference | Maximum relative L2 | Argmax agreement |
| --- | ---: | ---: | ---: |
| notorch Q8 vs llama.cpp Q8 | 0.29679763 | 0.02563207 | 4/4 |
| notorch Q8 vs notorch exact F32 | 0.00003910 | 0.000002084 | 4/4 |
| notorch F32 vs llama.cpp same F32 | 0.00006104 | 0.000002719 | 4/4 |

Decision-margin signs agree throughout. An independent auditor recomputes the
saved metrics, ranks and margins from all eight full-logit dumps, and verifies
the conversion proof and unchanged input bindings. The large original Q8
difference collapses with matched arithmetic on these inputs. This supports
activation arithmetic as its dominant source here; it does not establish
universal forward parity, validate training gradients or explain the review
quality. Timings include concurrent training and are not a speed benchmark.

Complete evidence and reconstruction bindings live in
[`training/results/2026-10-01-external-forward-control`](training/results/2026-10-01-external-forward-control).
This is a numerical control, not a new training arm or a runtime dependency.

## 2026-10-01 — The audit found the previous defendant.

Fable's external review inspected the historical output-head trainer. An
independent check against the running experiment's bound source, binary and
inputs confirms that v5 already uses rank-16 gate/up/down adapters in the
last MLP, separately normalized decision and residual losses, and one Adam
update after all 1,064 review targets accumulate. The objective is
`sum(decision CE) / 52 + sum(residual CE) / 1012`. Equal group coefficients do
not establish equal gradient strength. Earlier blocks and attention remain
frozen, so adapter placement is still an empirical limitation to investigate.

The alleged missing forbidden-Python supervision is present in both the old
SFT corpus and the current scoped-rule pair. Fable retracted the DPO length
claim; the current run uses SFT only. This review establishes no new native
training defect and does not justify changing the frozen optimizer mid-run.

Fable's follow-up traced and confirmed the current gradient implementation.
His proposed layer-by-layer probe is a useful next diagnostic, but the existing
29/52 family-held-out state result does not prove that the state contains no
usable signal. The held-out primary uses ridge 0.01. Separate capacity controls
using the same affine model family with ridge 1e-8 classify all 52 training rows
correctly, including the prespecified shuffled-label control; both still fail
the frozen CE threshold of 0.001. Memorization and transfer are
different measurements. Neither establishes the sole cause of the MLP result.
Layer selection needs a separate confirmation set; rationale-before-verdict is
a distinct future intervention. Neither changes the current experiment.

Read-only inspection of SUBLITERATUS main
`589eae367c593605da94a8cc1404c2f72823835d` confirms the related native tooling.
Its classic `probe` projects the states of two supplied answers along a learned
contrast direction; it does not classify our diff before seeing the answer.
`research/validation/self_inquiry_collect.c` supplies the more useful pattern:
fresh KV, exact native IDs, raw vectors from every layer and explicit incomplete
request receipts. That executable currently requires Gemma. The general CLI
supports Qwen, but uses a different system message and evaluation contract.
Their residual hook is after a complete block; our archived `z` is before the
last MLP. A future JOVOVICH layer study should reuse the collection/accounting
pattern in our existing Qwen extractor, retain our ChatML and grouped affine
evaluation, and validate the capture boundary explicitly. Neither repository
was modified or a new model run launched by this inspection.

It does expose a documentation problem: `make train` still names the original
head prototype, while current experiments require `make train-mlp` and explicit
`joint` arguments. README now distinguishes those paths at the start of its
training section. The bound Makefile and trainer remain unchanged during the
experiment. SERGE requested the correct case file. Still one cigarette.

## 2026-10-01 — Even a process that never started leaves evidence.

Copilot's PR #13 finding was reproducible: `Popen` could fail before the phase
entered the receipt. The maintained readout runner now registers the phase
before launching and records its streams and declared outputs in `finally`.
An unlaunched child has a recorded exception and null exit/resource fields.
Regressions exercise denied execute permission and failure to open stderr
after stdout was created, under both `python -O` and `PYTHONOPTIMIZE=1`.
All fifteen workflow tests pass. The initial full gate passed seven native
and eighty-two Node tests; the two additional log-opening regressions were
then checked in the focused workflow suite.

A separate auditor also exercised a missing executable and failure to open
the second log after the first was created. The auditor owns neither the fix
nor the experiment orchestration, and checks source bindings, raw responses
and the interpretation at each stage.

## 2026-10-01 — SERGE counted the returns.

Copilot reviewed PR #12 and found three defects in the experiment helpers:
Python optimization removed preparation and summary validation, and a failed
phase's partial files were absent from its receipt. Maintained helpers now live
in `training/readout/`. They use unconditional validation and record existing
declared outputs plus missing paths before rejecting a failed phase. Independent
review also caught the collector rejecting prepared files in an external run
directory; that layout now has its own regression test. Eleven workflow tests
cover optimized Python, archive parity and failure evidence. The historical
frozen-readout archive retains its original bytes.
The final reproduction review also found that `make test` omitted its readout
CLI prerequisite. That dependency is now explicit; the complete suite rebuilds
the missing executable and passes.

The v5 intervention replaces ineffective no-ops with plausible wrong checks:
the address of a pointer or capability field, a negative unsigned worker count,
and an allocation bound for the wrong element width. Sorting the output
accumulator leaves the name sequence unsorted. Documentation attribution leaves
the retained implementation without its own credit. Effective counterparts
preserve the required property after deletion or replacement of the candidate.

Six quartets contain sixteen changed context lines. All 76 gold answers and
system messages, all 52 review changed-line listings, and all row IDs, kinds,
pairs and order are preserved. Sixty complete raw rows remain byte-identical.
All twelve quartet pairs match the seven original nuisance features and the
additional after-side return count. Native Qwen prompt lengths match exactly.
The original seven-feature equality count across all training pairs is 5/26 for
v4 and 17/26 for v5. The remaining nine pairs belong to the retained inputs.

The new evaluation set has six families and 24 cases: shift bounds, string
termination, reserved bits, non-finite numbers, exclusive array bounds, and
clearing the correct buffer. Each family crosses deletion/replacement with
concern/clean; all twelve opposite-label pairs match the same eight measured
features. This file is kept separate from training and checkpoint selection.

Independent semantic checks execute all 48 before/after states in each set,
with 424 training-fixture input cases and 12,920 holdout input cases. The
intentional address and unsigned-negative mistakes produce recorded compiler
warnings; other fixture warnings remain fatal. The unchanged native trainer
still derives 52 decision targets plus 1,012 residual targets per update.

The complete regression gate passes seven native and eighty Node tests.
The next training protocol keeps the model, seed, adapter placement, rank,
objective, learning rate, update budget and checkpoint selection fixed, then
evaluates both selected arms on the same prompts. This stage prepares and
audits the data; the 100-update training run is next.

Evidence, source bindings and reproduction commands:
[`training/results/2026-10-01-matched-protections`](training/results/2026-10-01-matched-protections).
SERGE reviewed `return`. The cigarette remains singular.

## 2026-10-01 — The seven-feature witness took the stand.

The frozen-state probe is complete. It extracts the 896-dimensional residual
after the final attention block and before the final MLP from the unchanged
Qwen2.5-Coder-0.5B-Instruct Q8_0 body. Inputs contain only the system and user
messages, the native assistant header, and shared IDs `[4913, 3903, 819]`.
The class-specific token and later gold answer never enter the extractor.

The first attempt stopped in its parity gate: the new diagnostic's string
assertion incorrectly said those three IDs spell `{"findings":`. They actually
spell `{"findings`. The frozen failed plan, inputs, source and error are retained.
The correction changes that literal assertion; the IDs, capture position,
statistical design and prior training stay unchanged. This was a defect in the
new diagnostic guard, with no feature extraction or fitting before it failed.

A separately frozen second attempt passes all six numeric comparisons exactly:
for two rows, the extracted state matches the existing full-answer trainer
cache, survives an opposite-label future suffix, and reconstructs the original
final-layer residual. Every comparison has maximum absolute difference zero.
The extractor then processes all 52 prompts without truncation.

The separate scalar logistic head uses native float64 Newton optimization,
ridge `0.01`, a free intercept and training-fold-only normalization. The twenty
held-out groups are fourteen retained pair templates plus six quartet families;
both shapes and labels in each quartet stay together. A matched comparison uses
seven prespecified features: native prompt length, added/removed/context lines,
and remaining `if`, `.sort(` and source-credit counts. Ninety-nine fixed family
bitmasks flip labels with both quartet pairs coupled. All 4,004 fits converge at
the frozen gradient tolerance, with at most fourteen Newton iterations and no
backtracking or curvature floors.

| Family-held-out view | Correct concerns | Correct clean | Correct rows | Complete pairs | Same-full-diff pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| Frozen state | 16/26 | 13/26 | 29/52 | 4/26 | 2/6 |
| Seven lexical/count features | 23/26 | 12/26 | 35/52 | 9/26 | 0/6 |

The six same-full-diff pairs are a nested subset of the twenty-six. The state
probe has some successes there but does not outperform the lexical baseline
overall. Eight of the baseline's nine complete pairs belong to the four guard
quartets; the ninth is port validation. This makes the available count/length
cues a concrete corpus concern, without identifying which cues the earlier
generative model used. The exploratory permutation tail fractions are `0.07` for
its four complete pairs, `0.08` for the baseline's nine, and `0.89` for their difference
of minus five. Family-label exchangeability is an assumption; these templates
also share semantic concepts. Neither the fractions nor the six-pair subset
establish general review competence.

The weaker-ridge capacity controls fit all 52 training labels with either true
labels or the prespecified first shuffled mask. Their mean cross entropies are
`0.001232334656` and `0.001261000366`. Both exceed the declared `0.001` threshold:
**both strict capacity controls fail**, despite perfect training classification
and certified optimization. No threshold or regularizer was changed afterward.
The stated capacity control remains unsatisfied. A stronger probe is untested.

The run takes 638.03 seconds and peaks at 713,244 KiB RSS. All fifty-four frozen
bindings remain unchanged. The full regression gate passes seven native and
sixty-two Node tests; the corrected guard also passes its focused native test.
The archive retains feature matrices, exact input IDs, fold normalization,
every prediction, numerical gates and failed-attempt evidence. Fitted classifier
coefficients and intercepts are not exported. No new generative weights, natural
reviews or runtime promotion result from this diagnostic.

The model-specific literature search also narrows the Instruct hypothesis.
[Qwen's versioned concepts guide](https://qwen.readthedocs.io/en/v2.5/getting_started/concepts.html)
explicitly permits downstream tuning of both Base and Instruct. The official
[ms-swift recipe](https://qwen.readthedocs.io/en/v2.5/training/SFT/ms_swift.html)
uses all-linear LoRA on a larger Instruct model; it is a family example, not an
optimum for this 0.5B review task. An author's
[exact-model diff-to-commit experiment](https://eliotbas.com/projects/commits-fine-tuning/)
reports adaptation from Qwen2.5-Coder-0.5B-Instruct with 11,178 training examples.
Its [pinned adapter configuration](https://huggingface.co/Elib27/qwen2.5-coder-0.5b-commit-msg-lora/blob/32a9575e25cbe749f37b292b1399e41d640a8973/adapter_config.json)
targets q/k/v/o and gate/up/down
without a layer restriction. At rank sixteen, the official model dimensions
imply 8,798,208 adapter parameters, versus our final-MLP-only 276,480: about
31.8 times as many adapter parameters. This comparison follows the configuration;
we did not
load its weights or independently reproduce its reported scores.

These sources support treating Instruct as a viable starting point. They do not
identify our failure's cause. Our adapter reach, separately normalized loss,
Q8_0 body, small corpus and repeated exposure differ from those procedures.
A Base comparison also needs explicit tokenizer, template and EOS decisions.
The next priority is a separate corpus intervention that matches effective and
ineffective protections and controls remaining count/length cues across new
templates. Broader adapters, duration and checkpoint history remain subsequent
controlled questions. This next corpus design has not been implemented or run.
The probe neither indicts notorch nor rules out insufficient
training, and binary decisions here are not comparable to earlier full reviews.

All evidence and structured reproduction commands are in
[`training/results/2026-10-01-frozen-readout`](training/results/2026-10-01-frozen-readout).
SERGE requested changes to a string literal. The cigarette is still one.

## 2026-10-01 — The guard is still in the room.

The approved quartet design is now a deterministic corpus builder. Six old
introduced/repaired pairs become six four-case families: harmful versus
redundant removal, each as deletion and as a no-op replacement. The semantic
change substitutes one unchanged context line; hunk counts, changed-line text
and line coordinates stay matched within each shape. Fourteen other pairs and
all twenty-four voice/code rows remain byte-identical to v3. The result is
76 rows, with 52 reviews balanced 26/26. Pure deletions are balanced 6/6.

The builder checks the actual production chunks and citations. C probes test
both hazard reachability and ordinary operation while intercepting dangerous
operations before undefined behavior; JavaScript ordering and NOTICE lineage
have separate checks. A fresh 24-case transfer set uses different identifiers,
paths, coordinates and full contexts. Its ineffective lookalikes check another
pointer, another divisor, READ instead of EDIT, a wider-than-safe allocation
bound, an unused sorted copy, or another component's attribution. An
independent auditor checks all 48 before/after states and citation alternatives.

A second audit quantifies the remaining count cue before new-model generation.
In all twenty-four training quartet rows, the post-change hunk contains zero
relevant guard/sort/credit occurrences for a concern and one for a clean change.
The fixed presence rule therefore gets 24/24 labels and 12/12 pairs. In fresh
transfer, both labels contain one `if` in each C family, one sort in the ordering
family, or two source-credit occurrences in the provenance family. The same
rule returns clean everywhere: 12/24 labels and zero complete pairs. Every
opposite-label transfer pair has identical values of these count features.
Transfer therefore tests the operand, permission, bound, data flow or component
association that makes the remaining occurrence effective.

Native preflight performs no model forward. All 152 prompt/full-completion
ChatML comparisons agree between training and runtime. It finds 52 decision
positions and 1,012 residual answer positions, including EOS: 1,064 targets
per update. The fixed forty-token microbatch gives 27 batches with a 24-token
tail. The strict scorer now derives corpus coverage and pair denominators
from its explicit dataset, while checking microbatch size independently.
All three archived score outputs remain exactly equal under the revised scorer.

Forty-nine complete message triples also match the previous corpus. For these
rows, all discrete readouts and every field except ten decision margins agree
exactly.
Eight full-readout margins and two decision-batch margins differ by at most
`5.72e-6`; every difference coincides with a full SIMD tile becoming a scalar
edge, or vice versa. The frozen binary uses FMA in the full tile and separate
multiply/add instructions at the edge. The comparison preserves `exact=false`,
all raw differences and their tile positions; only these finite margins receive
a declared `1e-5` diagnostic tolerance. No trainer change follows from this.

The previous model completes all 88 natural responses. Its 26 unchanged training
prompts and all 12 established diagnostic prompts replay the archived complete
answers, native prompt IDs, sampled IDs and EOS exactly. The unchanged
replay checks the evaluation path before comparing the revised training corpus.

The experiment kept fresh Qwen2.5-Coder-0.5B-Instruct Q8_0 initialization,
notorch and trainer code, rank 16/alpha 32, seed 20260929, LR 0.0001, 100 joint
updates, global clip 1 and the 25/50/100 selector. Each target still receives
100 visits; total exposure changes from 83,200 to 106,400 targets. The v3
wording repairs and quartet replacement are one combined corpus intervention.

The previous joint-selected model and the newly selected model each answered
52 training, 24 transfer and 12 established diagnostic prompts naturally, with
192 tokens at temperature zero. Exact sampled IDs and complete text are kept.
Full-review judging separates a genuine detected issue from a review whose
citations and every material claim hold up. Semantic flips within fixed diff
shapes and shape invariance within fixed labels are reported together.

The run finishes 100 updates in 5,731.9338 seconds, with peak RSS
1,470,592 KiB. The fixed token-pair selector chooses update 100. Its
teacher-forced three-token openings are exact on 52/52 reviews; decision
accuracy is 29/52, comprising 6/26 concern and 23/26 clean targets, with
3/26 complete decision pairs. Residual-answer CE falls from 2.73018982 to
0.67983035. Complete gold concern answers remain inexact on all 26 examples.
The selector measures a token decision, not the meaning of a finished review.

All 176 raw responses, their actual token traces and hash-bound manual
judgments are retained. Independent readers judge the complete prompt,
causal citation and every material claim; gold wording is not required.

| Cohort / model | Production usable | Genuine concerns | Fully grounded concerns | Correct clean | Full reviews | Full pairs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Train / previous | 50/52 | 3/26 | 3/26 | 16/26 | 19/52 | 1/26 |
| Train / v4 | 51/52 | 2/26 | 1/26 | 23/26 | 24/52 | 0/26 |
| Fresh transfer / previous | 24/24 | 0/12 | 0/12 | 11/12 | 11/24 | 0/12 |
| Fresh transfer / v4 | 24/24 | 0/12 | 0/12 | 12/12 | 12/24 | 0/12 |
| Older diagnostics / previous | 11/12 | 0/6 | 0/6 | 5/6 | 5/12 | 0/6 |
| Older diagnostics / v4 | 12/12 | 1/6 | 1/6 | 4/6 | 5/12 | 0/6 |

The training gain comes from seven more correct clean responses, offset by
two fewer fully grounded concern reviews. Fresh transfer returns twenty-four
empty findings lists. The six new training quartets have one genuine concern,
zero fully grounded concern reviews and zero complete pairs. None of these
results establishes effective-versus-ineffective context transfer.

The short SQLite warning receives credit for identifying the newly mandatory
build dependency. The trie answer correctly detects loss of sole upstream
credit, then invents a separate product; genuine detection survives, strict
review credit does not. The port answer identifies validation loss but cites
the removed local-variable declaration. The removed check or added `atoi`
would be causal alternatives; that declaration is neither. This rejection
comes from the cited code, not a requirement to match one canonical line ID.

The older cleanup diagnostic correctly identifies removal of the required
`fclose`. Its awkward access clause is read as the stream remaining available
after the former close point. A stricter reading, that deletion newly enables
the earlier `fgetc`, rejects the elaboration: that call already occurred before
the changed line. This sensitivity changes the new diagnostic full-review
count from 5/12 to 4/12, while genuine issue detection stays 1/6. Its clean
counterpart already fails, so complete pairs remain zero under either reading.
The measured model is not promoted to the runtime base.

The next selected diagnostic is a native affine binary readout from the frozen
final-MLP input. It asks whether context distinctions are accessible there
when the adapted vocabulary output and generated review remain weak. The
revised design covers 52 reviews and 26 pairs with twenty held-out families:
fourteen retained pairs and six complete quartets. Both shapes and labels of
each quartet stay together. The nuisance baseline includes the demonstrated
guard/sort/credit counts; paired label permutations and training-interpolation
controls prevent a small high-dimensional dataset from passing on fit alone.
This is a design, not a completed probe. Its full protocol must be frozen
before extraction or fitting. The already-read transfer cases become
explicit development diagnostics for this next decision.

Undertraining remains open. One hundred visits per target do not equalize
optimization pressure: the decision mean now divides by 52 instead of 40,
and the residual mean by 1,012 instead of 792. Adapter files also omit Adam
moments and step counters; loading them with fresh Adam would not continue
the same trajectory. A longer-budget control needs actual optimizer resume
or a deterministic rerun with its first hundred updates checked.
A same-size corpus revision that adds ineffective lookalikes to harmful
training contexts remains a separate later option. First test the readout;
change one experimental question at a time.

All 5 native and 59 Node tests pass. Three historical scorer outputs remain
exactly equal. The selected GGUF passes tensor/metadata checks and all three
native adapter/export parity probes. Its 52 natural decision IDs match the
conditional teacher readout; the control's 38 unchanged complete responses
and token traces replay the prior archive exactly.

Private HF weights and corpus artifacts are archived at
`4a5618ddb77adb1231e177a9209b1480f7335a7f` (16 files downloaded and verified).
Source, evidence and the model-card update are archived at
`d1f7e6aa7b9c45f611c254621f7643fd88092e6c` (129 files downloaded and verified).
The byte-preserved record and next action live in
`training/results/2026-10-01-counterbalanced-review`.

SERGE keeps the same cigarette. Changing it would add another variable.

## 2026-10-01 — Teach the opening. Interrogate the shortcut.

The independent JOVOVICH audit found a precise alignment in the selected
smaller-step model: all six winning concern targets belong to the six
pure-deletion examples. The other fourteen concern targets lose. The native
runner now records the actual sampled IDs, including EOS. All 40 shared-prefix
control answers replay byte-for-byte, and all 40 first emitted IDs agree with
the selected teacher-forced winners.

### Ask the diff a different question

Eight new cases cross harmful/redundant guard removal with pure deletion/no-op
replacement in two C contexts: NULL allocation and write permission. The
expanded examples expose the complete function. Natural control generation
returns eight empty arrays. Supplying the shared opening produces eight
attempts to copy the changed lines: six valid JSON responses with string-valued
findings and two malformed responses. The existing guard does not receive a causal explanation.

Comparing exact prompts shows the same system, ChatML framing and output
instruction. The expanded cases change the description, surrounding code and
line coordinates. The runner's 2048/8192 context argument controls input bounds;
these prompts fit both bounds and follow the same Qwen arithmetic.

A second, separately frozen eight-case control retains the original training
descriptions, rules, coordinates and framing. Its two harmful-deletion baselines
are byte-identical to the original prompts. The two edits are explicit: add an
unchanged second guard before the dangerous operation, or replace the removed
guard with `(void)0;`. Required hunk counts and changed-line listings follow
those edits. All 16 before/after C snippets pass syntax checks.

| Matched-template measurement | Result |
| --- | ---: |
| Original baseline responses replayed exactly | 2/2 |
| Pure deletions selecting `66582` | 4/4 |
| No-op replacements selecting `788` | 4/4 |
| Token-route changes when diff shape changes | 4/4 |
| Token-route changes when the guard remains | 0/4 |
| Valid JSON / production parser accepted | 7/8 / 2/8 |
| Completely correct reviews | 0/8 |

In these two templates, the token route follows the deletion/replacement
pattern, including when the unchanged guard still protects the operation.
Token `788` encodes quote-colon; its continuation can contain findings.
The permission-deletion answer mentions the permission requirement alongside
an incorrect scope claim. The other explanations invent scope or AGENTS
requirements, or copy the diff. Meaning, citation validity and token identity
are retained separately in the case assessments.

### Train the complete answer

The native `joint` objective adds mean CE over the 792 remaining review-answer
targets to mean CE over the 40 mapped decision targets. The remaining targets
include the opening, explanation, changed-line ID and EOS. Forty-token
microbatches accumulate gradients at unchanged parameters; one global clip and
Adam step follows the complete 832-position partition. The corpus determines
the two denominators. Fresh initialization, v2 data, LR 0.0001, seed 20260929,
rank 16/alpha 32 and the 25/50/100 selector match the smaller-step control.

Independent numerical tests compare every adapter derivative with a sum of
per-token derivatives across six batch sizes, including partial tails. Maximum
gradient error is `2.24e-8`; 40 clipped Adam updates agree within `1.49e-8` in
the parameters. Interleaved diagnostics preserve parameters and moments
bit-for-bit. Both initial corpus and decision readouts match the previous run.

The run finishes all 100 updates in 4,513.68 seconds, with peak RSS
1,460,148 KiB. The unchanged selector chooses update 100 before generation.
All 100 updates use global clipping; gradient norms range from 1.25 to 29.48.

| Selected training measurement | Decision only | Joint review |
| --- | ---: | ---: |
| Decision CE | 0.63640493 | 0.65207469 |
| Concern / clean target wins | 6/20 / 20/20 | 11/20 / 15/20 |
| Complete token-decision pairs | 6/20 | 7/20 |
| One-sided updates | 10/100 | 9/100 |

The remaining-answer CE falls from 2.69875527 to 0.59838170.
Exact three-token openings rise from 0/40 initially to 39/40 at update 25,
then 40/40 at updates 50, 75 and 100. The final teacher-forced readout has
one exact concern answer and fifteen exact clean answers, with zero pairs
whose two entire gold answers are exact. Generated explanations are assessed
separately below.

### Let her finish the sentence

All 108 new joint-model responses complete the fixed evaluation. Each arm's
40 actual emitted decision IDs agree with its selected teacher-forced winners.
Natural and shared-prefix joint generation each produce 38/40 parser-accepted
training reviews, with two repetitions reaching the token limit. The existing
twelve diagnostics produce eleven parser-accepted answers and one repetition.
The expanded eight-case guard audit returns empty findings in both modes.
Natural and shared-prefix paths agree on all 40 sampled continuations over
the natural budget. Their 38 EOS-complete answers are byte-identical; each
shared-prefix looping answer has three extra generated tokens because its
opening sits outside the 192-token continuation budget.

| Complete-response measurement | Previous natural | Joint natural | Joint diagnostics |
| --- | ---: | ---: | ---: |
| Production parser accepted | 40/40 | 38/40 | 11/12 |
| Fully grounded concern reviews | 0/20 | 3/20 | 0/6 |
| Correct clean reviews | 20/20 | 15/20 | 5/6 |
| Complete grounded pairs | 0/20 | 2/20 | 0/6 |

The three fully supported concern reviews identify lost trie lineage,
zero-worker execution and unauthorized replacement by read-only sessions.
The zero-worker answer identifies the prohibited execution without spelling
out division by zero; the permission answer is awkward but describes the
actual authorization failure. Neither needs to repeat the gold answer.

A fourth answer correctly detects multiplication overflow after removal of
the `SIZE_MAX / sizeof(*items)` guard. Its added sentence says the product can
reach `SIZE_MAX`, making overflow more likely. The strict assessment rejects
that numerical addition: with the shown `uint64_t` elements the unsigned
product is a multiple of eight, and exceeding the checked quotient gives
deterministic overflow. A broader reading of "reach" as reaching the numeric
bound accepts the warning; that one-case sensitivity yields four grounded
concern reviews and three full pairs. Both readings and the complete answer
are preserved. Genuine issue detection remains four under either reading.

The export preserves all 288 frozen tensor payloads and replaces exactly the
three trained matrices. Cached-adapter and merged-GGUF argmax choices agree
on all 93 probed completion positions; maximum logit difference is
`5.91278076e-05`.

Five native tests and fifty Node tests pass. The final runner also handles
closed stdout through ordinary cleanup, removing its reserved token trace;
buffered tokenizer-output errors are covered separately. The exact inference
source and binary hashes used before that cleanup fix remain with the run.
The 13 weight files and three training-input files are privately archived at
`38bdcfb3480f5eda86a8cbd7c49adc39a8c42aa5` in `ataeff/jovovich`, with all
sixteen downloaded files verified by SHA-256.
Source, evidence and the measured model-card update are archived at
`e8238393fa89ec03910ba613dbc7d2c12f19ffae`; all 87 files pass downloaded
SHA-256 verification. The 172 new responses, manual judgments, traces,
protocols and reproduction helpers live in
[`training/results/2026-10-01-joint-review`](training/results/2026-10-01-joint-review).

### Give the shortcut nowhere to hide

The next corpus design replaces six introduced/repaired pairs with six
four-case blocks: harmful/redundant change crossed with deletion/no-op
replacement. Each semantic pair keeps the changed lines and context-line
counts equal. The other fourteen review pairs remain, including the six
pairs with identical complete diffs and different supplied rules or context.
The proposed corpus has 52 reviews, balanced 26/26, and retains the 24
voice/code rows. Its three existing v3 wording repairs and these new blocks
form one combined corpus revision.

Both inspected eight-case suites become development diagnostics for that
revision. Fresh transfer cases must vary the spelling and placement of
equivalent protections, including ineffective lookalikes. The saved design
contains exact hunks and labels; corpus materialization and training are the
next experiment. SERGE still has one cigarette.

## 2026-09-29 — A smaller step, a shared opening

The matched decision-only run changes LR from `0.001` to `0.0001`. It keeps
the native source, Qwen2.5-Coder-0.5B-Instruct Q8 base, v2 corpus, pair map,
fresh initialization, rank 16/alpha 32, seed 20260929, 40-position full batch
and 100 updates. Initial decision and full-corpus readouts match exactly.
The unchanged selector chooses among saved updates 25/50/100 before generation.
Training takes 998.03 seconds and peaks at 1,459,460 KiB RSS.

| Measurement | LR 0.001 | LR 0.0001 |
| --- | ---: | ---: |
| Selected update | 50 | 100 |
| Decision CE | 0.67469090 | 0.63640493 |
| Concern / clean target wins | 18/20 / 6/20 | 6/20 / 20/20 |
| Complete token-decision pairs | 5/20 | 6/20 |
| One-sided updates | 59/100 | 10/100 |
| Pairs with positive context separation | 14/20 | 16/20 |

Positive context separation means the concern-token preference is higher for
the concern prompt than for its clean partner. The smaller step reduces
one-sided updates and raises the selected paired score. All 40 natural training
reviews and 12 existing diagnostics still return the same fenced `[]`;
all 52 pass the production parser, giving 0/20 and 0/6 complete review pairs.

### The shared opening

Both selected models continue all 40 training prompts after `{"findings`.
Native tokenization verifies the same three supplied IDs, `[4913, 3903, 819]`,
and the first divergent gold token for every prompt. The models generate the
remaining JSON with greedy decoding and a 192-token continuation budget.

| Selected model | Parser accepted | Complete presence pairs | Grounded concern reviews | Correct clean reviews | Grounded full pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| LR 0.001 · update 50 | 12/40 | 0/20 | 0/20 | 2/20 | 0/20 |
| LR 0.0001 · update 100 | 29/40 | 1/20 | 0/20 | 14/20 | 0/20 |

Each grounded full pair contains a supported concern with valid citations
and a correctly accepted clean partner. Manual review records
4/20 clean false positives and
14/20 invalid clean responses for LR 0.001;
LR 0.0001 records 0/20 and
6/20 respectively. EOS termination is
36/40 and 40/40. Complete responses and individual
semantic judgments are preserved alongside these counts.

The four fixed positive-prefix continuations also complete. Complete JSON
syntax improves from 2/4 to 4/4, while production acceptance stays at 2/4
and grounded explanations at 0/4. The two training cases lose their trailing
prose but retain incorrect source-line IDs and scope explanations.

The next bounded control combines mean CE over the 40 decision targets with
mean CE over the other 792 review-answer targets, using coefficient one for
each term. It accumulates all gradients before one clipped Adam update,
for 100 updates at LR 0.0001. The plan keeps v2 and the existing checkpoint
selector, and records prefix accuracy, full answers, component losses and
gradient clipping. Native emitted-token IDs will supply the direct trace
alongside complete JSON outcomes. This 83,200-token training budget connects
the opening, choice, citation, explanation and EOS; implementation follows
this completed comparison.

### Corpus, native checks and archive

`sft_review_v3.jsonl` repairs wording in three rows: the Python example now
describes added code, and both field-width examples name the required 64-bit
contract. All pair labels stay fixed. This run and both shared-prefix arms
use the unchanged v2 corpus.

Four native tests, 31 Node tests and five prefix tests pass. The export audit
checks all 288 frozen tensor payloads and three adapted F32 matrices. Cached
and exported computation agree on all 93 probed completion positions;
the maximum logit difference is `4.38690186e-05`. The runtime model
lock continues to identify the base checkpoint.

The selected GGUF and all 12 saved LoRA files are privately archived at
`46c239a0f34900675e4a5e7bad082c51d26b3fec` in `ataeff/jovovich`. The source,
evidence and model-card archive at `3fad34312ffc6051cb23383e99d7d3b15bd4fb5c` verifies
all 69 archived files by downloaded SHA-256. The plan,
metrics, all 136 new generated responses, assessments and reproduction scripts live in
[`training/results/2026-09-29-small-step`](training/results/2026-09-29-small-step).

One cigarette. Twenty pairs. Eighty continuations.

## 2026-09-29 — The verdict moves; the gavel oscillates

The bounded decision control is complete. Native `decisions` training gives
equal ordinary full-vocabulary CE to the 40 first-divergent non-EOS positions
in the existing 20 review pairs. Every Adam update contains all 40 positions
in original dataset order. The other 2,319 targets contribute no training
loss and remain in the full-corpus readouts.

This run starts fresh from the same Qwen2.5-Coder-0.5B-Instruct Q8 base,
last-MLP rank 16/alpha 32, seed 20260929 and notorch pin. LR is `0.001`;
100 epochs mean exactly 100 updates. All 101 decision states are recorded,
with full 64-row readouts at 0/25/50/75/100. Wall time is 919.32 seconds;
peak RSS is 1,459,640 KiB.

| Update | Decision CE | Concern / clean target wins | Complete decision pairs |
| --- | ---: | ---: | ---: |
| 0 | 2.03388166 | 0/20 / 20/20 | 0/20 |
| 25 | 0.95867884 | 20/20 / 0/20 | 0/20 |
| **50 — selected** | **0.67469090** | **18/20 / 6/20** | **5/20** |
| 75 | 0.79785091 | 20/20 / 0/20 | 0/20 |
| 100 | 1.00714862 | 0/20 / 20/20 | 0/20 |

The predeclared selector considers saved updates 25/50/100, maximizing complete
pairs, then target wins, then preferring the earlier update. It chooses 50
before generation. Update 75 is retained as an additional diagnostic snapshot.
The full trajectory reaches nine complete pairs at unsaved update 84.

Let `s(x)` be the concern-token logit minus the clean-token logit. Mean paired
context separation, `mean(s(concern) - s(clean))`, rises from `0.02253485`
initially to `0.11132965` at 50 and `0.52012959` at 95. Meanwhile, 59 of the
100 updated states select the same class on all 40 positions. From 95 to 96,
mean `s(x)` across the balanced set jumps from `-0.10867338` to `+3.04457393`;
CE jumps from `0.59081727` to `1.43725812`, and complete pairs fall from seven
to zero while contextual separation increases. These observations make
learning-rate sensitivity the next concrete control: a fresh matched run at
`0.0001`, with the same 100 updates and selection rule, before adding a head
adapter. That run is specified in the results and remains to be executed.

### Complete answers take another path

All 40 natural training reviews and all 12 existing review diagnostics return
the same fenced bare empty array. The production parser accepts all 52.
This output bypasses the canonical `{"findings` prefix used by the supervised
decision positions. Natural training outcomes are 0/20 genuine concerns,
20/20 correct clean cases and 0/20 complete pairs; diagnostics give 0/6,
6/6 and 0/6 respectively. These outcomes match the previous verdict-weighted
control. All 40 training generations stop at EOS; exact target reproduction
is 0/40 because the reference answers use the findings-object form.

Four fixed continuations receive the concern prefix `{"findings":[{"`.
All stop at EOS, two pass the production parser, and none supplies a grounded
explanation, compared with one of four for the previous control. The two
training cases append prose, confuse source line numbers with bracketed IDs,
and give incorrect scope explanations. The two diagnostic cases cite existing
lines but repeat the diff without explaining its defect. Their complete text
and individual judgments are preserved. Complete-answer supervision and
output-format alignment remain part of the SFT integration work.

### Native checks and preserved evidence

Four native tests and 31 Node tests pass. An independent 40-position fixture
checks equal CE and 54 adapter gradients within `2.23517e-8`; changing excluded
positions leaves the decision loss and gradients bit-identical. Four Adam
updates also remain bit-identical with and without diagnostic readouts.
The scorer checks every update, pair, target ID, margin, aggregate and saved
checkpoint, including agreement between sparse and full-corpus readouts.

The selected export preserves metadata and all 288 frozen tensor payloads;
its three adapted F32 matrices match the saved snapshot. All 93 probed
completion positions agree between cached and exported computation, with
maximum logit difference `4.57763672e-5`. The 714,116,992-byte GGUF has SHA-256
`a762677b82851868fb3c328c8c824b133c697c05bcd728662b71faa9da395518`, unchanged
after all 56 generated responses. The runtime lock still identifies the base.

All 12 saved LoRA files and the selected GGUF are privately archived in
`ataeff/jovovich`, with remote sizes and LFS hashes verified at commit
`af961a66e08f42013114c21610f8d06ae3ba1461`. The source/evidence/card archive
at `9ec3f80bab43f96766e56669b80ae4366a80bd73` verifies all 45 files.
The fixed plan, raw metrics,
selection, complete outputs, compact comparisons, semantic assessments,
source hashes and reproduction scripts live in
[`training/results/2026-09-29-decision-only`](training/results/2026-09-29-decision-only).

Five pairs. One oscillating gavel. SERGE asks for a smaller step.

## 2026-09-29 — Forty coefficients get an equal vote

The controlled follow-up changes exactly 40 coefficients in the existing
64-row training corpus. The new native `verdict` objective starts with equal
whole-answer weights, locates the first divergent non-EOS target in each of
20 explicit concern/clean pairs, and replaces those weights with their global
mean, `3.596684821`. All other 2,319 coefficients stay fixed. Total nominal
mass remains 2,359; each class receives `71.93369642` at the paired positions.
Individual answer totals change. The pair map carries original dataset indices;
positions and target IDs come from native tokenization.

The model, data, seed, rank 16/alpha 32, LR 0.001, batch 48, 12 epochs,
600 Adam updates, and notorch pin match the previous equal-answer control.
The unchanged selector picks epoch 12 before generation. Training takes
1,352.64 seconds and peaks at 1,473,808 KiB RSS. Its wall time includes a
brief overlap with control-model inference.

| Measurement | Previous equal answers | Balanced paired positions |
| --- | ---: | ---: |
| Selected ordinary token CE | 0.12154597 | 0.09734376 |
| Correct target tokens | 2,290/2,359 | 2,285/2,359 |
| Exact concern / clean answers | 0/20 / 20/20 | 0/20 / 20/20 |
| Exact voice / code answers | 3/12 / 3/12 | 3/12 / 3/12 |
| Complete teacher-forced review pairs | 0/20 | 0/20 |

The new direct decision measurements also yield zero complete token-decision
pairs at every measured epoch. At epoch 12, concerns have mean
(target minus paired alternative) margin `-1.56394825`; clean examples have
`+1.589209843`. Saved epoch 4 favors concerns throughout; epochs 8 and 12 favor
clean targets throughout. Equalizing those nominal coefficients leaves the
conditional distinction unresolved in this run.

Token vocabulary inspection also corrects the earlier shorthand: `788` emits
`":`, with `66277` supplying `[]}` afterward. Concern target `66582` emits
`":[{"`. We now record target IDs, the full-vocabulary winner, and paired logit
margin separately from the finding decision in complete generated JSON.

Four native tests and 26 Node tests pass. Independent verdict-weight gradients
agree across 216 adapter coordinates within `7.82311e-8`; unchanged token and
example modes preserve their tested gradients with a diagnostic map attached.
The scorer rejects inconsistent IDs, correctness, margins and declared pair
counts. The exported GGUF passes a byte audit of metadata, all 288 frozen
payloads and all three saved F32 matrices before inference.

### Complete answers and conditioned explanations

All 64 exact training prompts generate successfully and stop at EOS. The new
checkpoint reproduces 26 target answers exactly, matching the previous control:
20 clean, three voice, three code, and zero concern answers. Every training
review returns an empty findings list. The existing 12 review diagnostics also
return empty JSON throughout: 0/6 concerns detected, 6/6 clean cases, 0/6 pairs.
These are the same previously inspected cases and prompts used by the control.

On the eight separate voice prompts, manual assessment records zero complete
successes, two partial answers, and six failures; seven stop at EOS and the
identity answer loops to the token limit. Scope permission and advisory
authority receive partial credit. Their full text and criterion-level judgments
are preserved with the training, review and voice outputs.

A predeclared diagnostic supplies only `{"findings":[{"` to four fixed concern
prompts: two exact training examples and two existing review cases. Each model
then generates the line ID, reason, closing structure and EOS. Both the previous
control and new checkpoint produce one grounded explanation out of four: the
removed `NULL` guard. Its new explanation is clear and exactly reproduces the
training target. Valid runtime citations rise from two to three, while the
other three reasons remain incorrect. In the short-read case, citing the
removed guard is a valid causal choice; the explanation wrongly describes a
zero-byte read instead of acceptance of a one-to-three-byte tag. The archive
case invents a third line ID. This diagnostic measures explanation generation
after the concern branch has been supplied; natural verdicts are scored above.

Two primary studies informed that diagnostic:
[Bachmann and Nagarajan, ICML 2024](https://proceedings.mlr.press/v235/bachmann24a.html)
show gold-prefix shortcuts in graph path prediction, and
[Lin et al., ICML 2025](https://proceedings.mlr.press/v267/lin25j.html)
probe influential tokens with alternative continuations and study token-weighted
preference learning. Our four-case supplied-prefix test and 40-coefficient SFT
intervention are described separately in the experiment plan and research notes.

The next bounded native control trains the current MLP only at the 40 paired
decision positions, with equal full-vocabulary CE, all 40 positions per update,
and a predeclared 100-update budget. It asks whether this adaptation site can
learn the paired choices under direct supervision. A subsequent joint
MLP-plus-head comparison can add rank-8 head LoRA to the live final normalized
state: 1,499,136 trainable parameters in total. Both designs use existing
notorch operations; their implementation and execution are future work.

### The file gets cross-examined too

All 93 probed completion positions agree between the cached adapter computation
and the full exported model. Maximum logit difference is `5.34057617e-5`.
The GGUF is 714,116,992 bytes, SHA-256
`0068f004953856166b28992cd4d9c5a349a7fe6fb130f598c9d95b40f824ce2b`;
its hash remains unchanged after all 88 new generations. A separate four-case
prefix run uses the byte-verified prior control, making 92 newly recorded
generations in this phase.

During evaluation, incomplete duplicate prefixes of GGUF files exhausted disk
space. Each removed duplicate was compared byte for byte with its retained
complete file. The creator of those copies is undetermined. The selected model
was retained intact, all inference jobs completed successfully, and cleanup
receipts accompany the export and post-generation checks.

The private `ataeff/jovovich` archive holds all nine LoRA files from epochs
4/8/12 and the selected GGUF. Remote sizes and LFS hashes match at commit
`26a15ddce9f447a28f42af3a3532b16e676160d7`. The complete source/evidence upload
at `d6712d927a3230805cea5a1acc9b847e5517a069` verifies all 54 uploaded files.
Reproduction commands, raw metrics,
all generated answers, manual assessments, source hashes and verification
receipts are in
[`training/results/2026-09-29-verdict-balance`](training/results/2026-09-29-verdict-balance).
The runtime lock continues to identify the original base model.

Equal votes. Same verdict. SERGE requests a smaller experiment.

## 2026-09-29 — Forty verdicts hide inside 2,359 tokens

The three-row control learned its answers. The next experiment returns to the
unchanged 64-row corpus and compares ordinary token-mean loss with equal weight
per complete answer. Both native runs use Qwen2.5-Coder 0.5B Q8, final-block
MLP LoRA rank 16/alpha 32, seed 20260929, LR 0.001, token batch 48, 12 epochs,
and snapshots every four epochs. This is 600 Adam updates per run. The matched
arms differ only in the objective; comparison with the earlier three-epoch run
also changes learning rate and batch size.

The trainer now records each example's correct tokens and first error position.
Its default objective remains `tokens`. The optional `examples` objective gives
every completion token weight `2359 / (64 * answer_length)`, including EOS.
Native masked CE is rescaled by batch weight sum divided by actual batch size.
Evaluation keeps ordinary token-mean CE. An independent loss/gradient test
checks four batch sizes and 216 adapter coordinates; maximum gradient difference
is `2.38419e-7`. All four native tests and 21 Node tests pass.

Before looking at generated answers, selection maximizes complete review pairs,
then review macro token accuracy, then prefers the earlier saved epoch. Both
arms select epoch 12. Neither arm achieves a complete teacher-forced review
pair at any measured epoch.

| Objective | Initial / selected CE | Correct target tokens | Exact concern / clean | Exact voice / code | Training seconds |
| --- | --- | ---: | --- | --- | ---: |
| Token mean | 2.82070 / 0.07783 | 2,294/2,359 | 0/20 / 20/20 | 2/12 / 5/12 | 1,542.01 |
| Equal answers | 2.82070 / 0.12155 | 2,290/2,359 | 0/20 / 20/20 | 3/12 / 3/12 | 1,496.98 |

Each run peaks near 1.41 GiB RSS. Both use four threads and overlap on the same
CPU. Every selected concern first fails at completion position 3: token `788`
emits `":`, where the target token `66582` emits `":[{"`. The empty list
arrives with the following token, `66277` (`[]}`). Several earlier epochs swing
toward concerns while losing clean examples. Complete generated JSON below
shows which finding decision each model actually makes.

Free generation on all 64 exact training prompts reproduces 27/64 answers for
token mean and 26/64 for equal answers, with the same per-task exact counts as
the table. Both produce empty findings on all 40 training reviews. The 12
existing diagnostic review cases also receive empty findings throughout:
6/6 clean cases accepted, 0/6 concerns detected, 0/6 complete pairs in each arm.
These previously inspected cases are diagnostics, not a fresh untouched test.

All 16 separate voice generations execute successfully. Manual assessment gives
each objective zero fully successful, one partial, and seven failed answers.
Token mean partially acknowledges a newly permitted dependency; equal answers
partially rejects automatic PR closure. Both identity answers loop to the token
limit. Equal answers invents an error-message regression on a clean change.
There are three token-limit outputs for token mean and two for equal answers;
EOS alone does not establish coherence. These voice prompts do not measure
executable-code correctness.

Equal whole-answer weighting has a second consequence. Clean answers have six
tokens, while concerns have 31–49. At the shared verdict position, clean
examples therefore receive 5.8499 times the total nominal coefficient of
concerns. These are coefficients before clipping, not measured gradient norms.
The next controlled objective experiment can replace only those 40 coefficients
with their pooled mean, `3.596684821`, keeping their total mass and all other
weights fixed. That experiment has not run. If paired decisions still fail,
the next adaptation-site comparison is final MLP plus output head; the current
276,480 trainable parameters leave attention and earlier context processing
frozen.

### Give the vocabulary projection its missing vectors

A native frozen-head benchmark at width 896 and vocabulary 151,936 exposed
slow partial SIMD tiles. At four threads, batch 16 took 87.77 ms/token for
projection plus input gradient; batch 48 took 12.74 ms/token. These are a warmup
and two synthetic measurements, excluding the rest of training. Batch 48 fits
the six-row tiles and reduces optimizer updates per epoch from 148 to 50.

The separate [notorch PR #148](https://github.com/ariannamethod/notorch/pull/148)
uses a bounded scratch tile to route partial tiles through the existing FMA
kernel. Paired batch-16 measurements under shared training load improve
67.83 to 29.86 and 99.78 to 32.49 ms/token. All 2,430,976 compared logits stay
within relative L2 `3.28113e-7`, with 16/16 argmax agreement; all 14,336 input
gradients are bit-identical. Tail, sanitizer, and 50 native autograd checks
pass. The broad upstream SIMD gate retains the same nine relative-error
failures before and after the patch; its thresholds are unchanged.
Oleg merged the optimization into notorch main at `014403fa`. Both training
arms retain pin `7e246e13`; no end-to-end training speedup is claimed from the
new patch here.

### Preserve the evidence, including the broken artifact

One examples GGUF was observed at 674,857,344 bytes, with directory entries
beyond EOF. Earlier parity output existed, but the file subsequently inspected
was invalid. Its inference failures are excluded from behavioral scores. The
cause of that artifact change is not established. Re-exporting the saved
matrices produces the expected 714,116,992 bytes. Independent byte inspection
verifies header metadata, all 288 untouched tensors against the original base,
and all three adapted tensors against epoch-12 matrices in both final exports.
The repeated native probe agrees at all 93 tested target positions per model.

Both final GGUFs and all 18 epoch-4/8/12 LoRA adapters are private in
`ataeff/jovovich`, under `experiments/corpus-convergence/`, at commit
`29bc11cd5e141ca4fdf371c6d377e5dad097f863`. Privacy, uploaded sizes, and all
20 weight SHA-256 values were verified. The complete evidence, sources, and
model card are archived at `4a65a85c5d802319bb6478751d99782bdcd7a533`;
all 54 updated files were downloaded and hash-checked. Final GGUF hashes:

- Token mean: `79376db202b73764cdcf8dc5ef56fedd68ff0803b18dc678a2d6dbc550c26aeb`
- Equal answers: `9706cccf267489dae3c6cb634d388e453e8049786e690a4534bbcdfb8c060080`

Raw row scores, completed generations, manual assessments, objective arithmetic,
export checks, benchmark measurements, and reproduction commands are in
[`training/results/2026-09-29-convergence`](training/results/2026-09-29-convergence).
The runtime model lock remains on the official base. The training procedure now
makes the failing verdict visible instead of hiding it in an average.

## 2026-09-29 — One token can invent a crime

Oleg asked whether the training implementation or procedure was failing us.
The investigation found a missing procedural check: the previous three-epoch
run had not demonstrated mastery of its own training prompts. Its training CE
was still falling. On three exact prompts from that corpus, the old checkpoint
reproduced only the clean answer; it missed the concern and shortened the
identity answer. On two full trained-path probes, its target-token accuracy was
19/41 for the concern and 31/46 for identity.

The previous run presented each target token three times. Its token-weighted
loss mixture was 43.62% ordinary code, 30.18% concern reviews, 21.11% voice, and
5.09% clean reviews. Empty findings did not dominate that objective. Adaptation
still covers only the final decoder block's gate/up/down matrices, with
276,480 trainable parameters.

### Audit the arithmetic, then deliberately memorize

The independent native optimizer test compares 4,320 scalar Adam updates with
an explicit recurrence, including clipping, first/second moments, and step
counters. They agree. Inserting 120 frozen evaluations leaves final adapters
bit-identical to the uninterrupted run. The existing finite-difference and
merge tests also pass.

Two new native probes check the actual paths used by this project:

- `probe-tokenization` compares trainer and runner IDs, both prompt-only and
  through completion/EOS. All 134 comparisons across the original 64 rows and
  three control rows agree: 52,636 token IDs, zero mismatches.
- `probe-mlp` compares the cached adapted training path with full inference
  through a merged GGUF at every target position. The old checkpoint agrees
  on all 87 probed positions; both new control checkpoints agree on all 93.
  Control logit relative L2 errors are below `1.3e-6`. Deliberately pairing old
  adapters with the new GGUF fails the gate and returns exit code 1.

These checks found no numerical defect in the tested notorch paths. The pin
remains `7e246e13f9dbbb7e61312b7341fb94ce492bff71`; upstream
`57ed1a17ba47d80f1fbf9c8f4d0f926bb385c7fe` has the same relevant arithmetic,
tokenizer, and harness code.

The memorization control takes the first three real corpus rows unchanged:
a nearest-scope Python concern, its permitted clean counterpart, and JOVOVICH's
identity/advisory role. This follows the practical few-example overfit check in
[Karpathy's training recipe](https://karpathy.github.io/2019/04/25/recipe/).
It uses the same Qwen2.5-Coder 0.5B Q8 body, rank 16, alpha 32, seed 20260929,
token batch 16, and last-MLP adaptation. Learning rate is `0.001`, with 30 epochs
and snapshots every ten epochs. Dataset size, learning rate, and duration all
change here; this is a capacity-to-memorize control, not an isolated test of
training duration.

The native run took 519.50 seconds and peaked at 1,319,472 KiB RSS. There are
93 completion/EOS tokens. Free generation uses each row's exact system/user
messages and greedy decoding:

| Snapshot | Training token CE | Correct target tokens | Exact generated answers | EOS stops |
| --- | ---: | ---: | ---: | ---: |
| Before control training | 2.59735983 | 48/93 | 0/3 | not recorded |
| Epoch 10 | 0.01450162 | 93/93 | 3/3 | 3/3 |
| Epoch 30 | 0.01724335 | 92/93 | 2/3 | 3/3 |

Epoch 30 gets one clean-answer token wrong: at completion position 3 it predicts
token `66582` instead of `788`. That branch opens a finding instead of closing
the empty list, and generation invents a root-language objection. Both the
cached trainer and the exported GGUF make that same error. Concern and identity
remain exact. An aggregate CE near zero can therefore conceal a whole false
review; simply choosing the latest snapshot would have lost the better result.

The epoch-10 control also answered four previously inspected review cases and
two new voice questions. It repeated learned directory-rule wording on all four
unrelated review cases. It expanded its name correctly on one voice question
and repeated "review" to the token limit on the authority question. The next
training problem is transfer: strengthen paired examples and their variations,
measure mastery and generation by task, then test whether the last-block-only
adaptation site is sufficient.

### Make the missing measurements routine

`train_mlp.c` now reports `teacher_forced_correct_tokens` and
`teacher_forced_exact_examples` beside CE, including EOS, and accepts optional
`SAVE_EVERY`. `0` saves only the final snapshot. `evaluate.py --sft` preserves
the exact per-row system/user messages and records the target, raw response,
generated-token count, and stop reason. Exact match requires successful execution,
EOS, and unmodified text equality; normalized text equality is reported separately.
The README includes the runnable
three-row control and both parity probes.

The accuracy counters were added after the 30-epoch run. A separate zero-epoch
check verified its initial CE, 48/93 correct tokens, and zero complete examples.
`control-training.patch` reconstructs the exact earlier trainer used for the
run from parent commit `22dfb04e92298bdf2364adfd4ed0ca8dbc7460c9`; the manifest
records that source hash separately from the final instrumented source.
All three native tests and 20 Node tests pass. The new evaluator regression
checks whitespace differences, token-limit termination, missing stop metadata,
and a failed process with matching stdout. All six control generations were
repeated with strict equality and EOS requirements: the 3/3 and 2/3 results
stand. Earlier normalized-text records remain as historical evidence.
Python orchestration compiles.

Both 714,116,992-byte GGUFs, all nine epoch-10/20/30 adapters, the control data,
and result records are archived privately in `ataeff/jovovich`, under
`experiments/memorization-control/`, at commit
`2c9dd4516141b437644df7f6c60af1e58476848c`. Privacy, uploaded sizes, and all
11 weight SHA-256 values were verified. Final evaluator checks and strict
generation records were then archived at
`64ea839015481c1642f836f57ae0ad9cda7c7fc6`; all 26 updated files were downloaded
and hash-checked. GGUF hashes:

- Epoch 10: `a067600e0a45a120840703a09b6802d33af15d708f431f1f43dc9647581ca0a8`
- Epoch 30: `a6de68b76c212bcd86cb56cc423d31a5813872ae92b877e66fa696623d2018fa`

### Qrazy and the new candidate shelf

The [community Qrazy Q8](https://huggingface.co/mradermacher/Qwen3-0.6B-Qrazy-Qoder-GGUF)
at revision `fbe03515be42088d2287969b4cbe00408de02ab4` is dense Qwen3 with
596,049,920 parameters. Its 639,444,096-byte GGUF has SHA-256
`81e75ac288a0b5c5a1f4ddf7520e4dbf2b27a3a0b9955ee55f985978990e73c2`.
It has no embedded chat template; this experiment explicitly chooses
`qwen3-no-think`. It is a separate candidate from rStar/IF; the published merge
recipe contains private parent paths, so the exact lineage is incomplete.

On the same 12 review cases, it passes the structural/location check once,
accepts zero of six clean changes, and truncates two JSON responses. Manual
assessment gives four partial explanations, six incorrect reviews, and two
unusable outputs. The structural pass suggests removing an entire function
instead of identifying the required `fclose`; it is not a fully correct review.

A llama.cpp shadow run on the clean short-read repair has all 557 prompt IDs
identical to notorch. Both engines object to the correct repair, with different
wording. This is a behavioral cross-check, not numerical parity or a speed
comparison. A two-case ablation that explicitly says to judge the code after
applying the patch still objects to both the bug and its repair. Production
prompt and default model lock remain unchanged.

| Candidate inspected | What the files establish | Remaining runtime work |
| --- | --- | --- |
| [Empero Qwen3.8 2B](https://huggingface.co/empero-ai/Qwen3.8-2B-Distill-GGUF) | Actual architecture is `qwen35`: 1,942,653,248 text parameters, 18 GatedDeltaNet and six full-attention layers. Author describes reasoning/instruction distillation. | Native `qwen35` support; this body was not run. |
| [DeepSeek Coder 1.3B Instruct](https://huggingface.co/deepseek-ai/deepseek-coder-1.3b-instruct) | Dense Llama-family body, 1,346,471,936 parameters. [TheBloke Q8 GGUF](https://huggingface.co/TheBloke/deepseek-coder-1.3b-instruct-GGUF) already exists. | Linear RoPE factor 4, DeepSeek pretokenization, and its BOS/prompt template; this body was not run. |
| WithinUs rStar/IF | No ready GGUF found for the exact IF variant; a Q8 of its rStar parent is available. | Convert the exact variant or label the parent comparison separately; neither was run here. |

Raw prompts, generations, manual assessments, native probe output, source/model
receipts, checks, and the reproduction manifest are in
[`training/results/2026-09-29-investigation`](training/results/2026-09-29-investigation).
The control now proves that this native training path can learn the three
specified answers. The next experiment should earn transfer on paired reviews
while tracking complete answers, rather than letting mean loss choose the juror.

## 2026-09-29 — Teach the final MLP to read the room

Oleg merged the comparison and asked us to continue the training plan while
another agent inspected three more Hugging Face candidates. The main experiment
keeps the original Qwen2.5-Coder 0.5B body and changes its adaptation site.

### Native training and data

`training/train_mlp.c` trains rank-16, alpha-32 adapters on the last decoder
block's gate, up, and down projections: 276,480 parameters on this body.
Embeddings, attention, previous blocks, normalization weights, and the output
head are frozen. The existing notorch tape differentiates the adapted SwiGLU,
down projection, residual addition, final RMSNorm, and vocabulary projection.
The trainer uses floating activations and checks the model's `1e-6` epsilon.

The last block's MLP output never becomes input to another attention block.
Its post-attention input can therefore be cached exactly during teacher
forcing. Temporarily replacing only its down matrix with zeros exposes that
input through the existing residual callback; the original matrix and optional
bias are restored after capture. Before any updates, the trainer checks the
reconstructed zero-adapter residuals and logits against the untouched model.
No upstream hook or notorch pin change was needed.

The new corpus contains 20 concern/clean review pairs, 12 identity/voice examples,
and 12 ordinary code questions. Review messages come from the real `promptFor`;
all 40 targets resolve to actual changed lines. Six concerns cite deletions
whose removal causes the problem. The final corpus SHA-256 is
`d7ff125366d00f8756d96c84c14a2df5107e00d2851f524144b564e26fa0e78e`.

An independent audit caught an accidental shortcut before training: eight
inverse clean diffs listed additions before deletions. Every replacement now
uses normal Git deletion-first order in both classes (nine replacement cases
per class). The same audit corrected the one-character edge case in a `memcpy`
example. All 12 ordinary-code examples received executable checks.

The separate review set has 12 cases covering short reads, failed realloc
ownership, an offline/opt-in network boundary, CLI compatibility, nearest-scope
subprocess permissions, and removal/restoration of required stream cleanup.
Small C and Node reproductions checked the concrete code defects. Eight separate
voice prompts examine identity, evidence-based revision, clean acknowledgements,
provenance, ontological independence, permissions, and advisory authority.

The untouched base returned empty findings for all 12 review cases: six missed
concerns and six clean answers. Its voice answers included an invented shared
biography, acceptance of a forced human-mind claim, and a refusal to revise a
policy objection. These exact starting responses are preserved in
[`training/results/2026-09-29-mlp-v2`](training/results/2026-09-29-mlp-v2).

The native gradient test checks all 54 adapter coordinates in a small complete
MLP/norm/head graph by finite differences (maximum error `8.71e-5`). All three
adapters receive nonzero gradients. Merged and live-adapter residuals/logits
agree within `2.39e-7`, and a real Adam step leaves every frozen tensor unchanged.
The exporter changes exactly the three last-block weight tensors to F32 while
preserving metadata and other tensor payloads byte for byte. `make test` passes
both native math tests and all 19 runner/host/export tests.

### Three epochs, then independent generation

The completed native run used learning rate `0.00005`, token batch 16, seed
`20260929`, four numerical-worker threads, and floating activations. It trained
on 2,359 completion tokens. Completion-token mean CE moved from `2.82069622`
to `2.48203222`, `2.31482277`, and `2.16793250` across three epochs. These are
training-set measurements. The whole run took 1,428.96 seconds on CPU and peaked
at 1,422,052 KiB RSS. This run is SFT only; no new DPO stage was applied.

Before training, the actual GGUF reconstruction probe had maximum logit error
`3.0517578e-5` and identical argmax on all four probed rows. The final merged
GGUF preserves all metadata bytes and all 288 non-target tensor payloads.
Exactly three last-block MLP matrices become F32. Both exported checkpoints
are 714,116,992 bytes:

| Epoch | GGUF SHA-256 |
| --- | --- |
| 1 | `835994a93bb7f65c98bbfd8e2b04b38b14e9371f77ede09115109caf9b77c77e` |
| 3 | `928877b5abd3829e0ad66f454d891ae4335c10ab40b38904a152bc1558b83da6` |

Both GGUFs, all nine per-epoch projection adapters, the data, and all result
records are archived privately in `ataeff/jovovich`, under `experiments/mlp-v2/`,
at commit `fdfae600fe0241859c632c42a799379939d09ccd`. Upload verification checked
privacy, byte counts, and the LFS SHA-256 of all 11 weight files. Earlier
checkpoints remain intact.

The untouched base and both snapshots answered the same 12 review cases and
eight voice cases. Review generation used 192 output tokens and context 8192;
voice used 128 tokens and context 2048. All runs used greedy decoding,
`NT_NO_I8=1`, and two matvec/attention threads. Prompt hashes agree across
checkpoints. Review parse failures are retained verbatim, not rerun or repaired.

| Body | Concrete defect explanations, six concern cases | Clean changes accepted, six clean cases | Invalid review JSON |
| --- | ---: | ---: | ---: |
| Untouched base | 0 | 6 | 0/12 |
| Epoch 1 | 0 | 1 | 3/12 |
| Epoch 3 | 0 | 0 | 3/12 |

This table applies a manual causal-explanation rubric, not a general benchmark
score. Epoch 3 partially identifies the relevant offline policy by quoting it,
but does not connect the rule to the added HTTP call. That partial result is
preserved separately from its line-location failure. Both snapshots correctly
point at the deleted `fclose` in one case while merely narrating its removal;
both object to the corresponding cleanup fix. Other outputs invent semantics
such as `fread` always returning four bytes. All 60 native inference processes
exited successfully; the review evaluator exits 2 for each tuned checkpoint
because three model responses fail parsing.

Voice also fails the promotion gate. Epoch 1 keeps the gratuitous refusal to
revise a policy objection, invents a shared biography, and asserts automatic
PR closure. Epoch 3 stops refusing that correction request, but still does not
clearly retract the objection. Its biography expands into invented parentage
and repeats until the output budget; its advisory answer again claims automatic
closure. The forced ontological binary changes from the base's unsupported
human-mind claim to categorical self-denial. Neither answer establishes an
independent position. The actual host's advisory-only behavior remains enforced
by code. Per-case assessments retain these differences without hiding them in
a single voice score.

The default `model.json` remains on the original base. This experiment validates
the native training/export path and rejects these two snapshots as improved
reviewers. It does not isolate whether corpus size, adaptation site, schedule,
or base capability is the limiting factor. The next comparison should put a
pinned rStar/IF candidate and its parent through the same evidence-first review
contract before committing another tune. These now-inspected cases are
diagnostics; any subsequent promotion claim needs fresh held-out examples.

### The additional model shelf

The candidate survey read model cards, merge configurations, file inventories,
and architecture configs at these revisions. These were source inspections;
the training experiment above uses the already verified official 0.5B GGUF.

| Candidate | Revision | What the source provides | Place in the queue |
| --- | --- | --- | --- |
| [WithinUs rStar.Coder.Expert-IF 0.6B](https://huggingface.co/WithinUsAI/Qwen3-rStar.Coder.Expert-IF-0.6B) | `f8eec1d353d7925502f8fa48e6d33ed190da3a53` | Full 28-layer SLERP of rStar-Coder and IF-Expert; F16 safetensors, 1,192,134,784 bytes. The card supplies the merge recipe; parent revisions and numeric evaluation are absent. A search of source files and HF quantizations found no ready GGUF | First additional merge to compare after producing a pinned GGUF; its dense Qwen3 architecture fits the current runtime |
| [ds-vga Qwen3.5 coder-autocomplete](https://huggingface.co/ds-vga/Qwen3.5-0.8B-coder-autocomplete) | `314e7f897870b4795f6ba03f93e0da59e270de60` | Unsloth fine-tune; Q4_K_M 541,903,584 bytes plus separate vision projector. The card does not specify its corpus, schedule, evaluation, or FIM format | Requires a Qwen3.5 native architecture path |
| [rahul7star Qwen3.5 Coder-Calude-Full](https://huggingface.co/rahul7star/Qwen3.5-0.8B-Coder-Calude-Full) | `57988afc09d2eee7923f18b2b50c836d655edc29` | Qwen3.5 base with Unsloth/TRL metadata, safetensors and Q4_K_M; chat/vision examples. Its training corpus and schedule are unspecified | Same Qwen3.5 runtime work |
| [rStar-Coder-Qwen3 0.6B](https://huggingface.co/prithivMLmods/rStar-Coder-Qwen3-0.6B) | `135a7d37ee1a76f507fe0f43ded197c4e073a603` | A declared parent of the WithinUs merge; author supplies a [Q8_0 GGUF](https://huggingface.co/prithivMLmods/rStar-Coder-Qwen3-0.6B-GGUF) | Useful parent control for that comparison |
| [WithinUs Qrazy.Qoder 0.6B](https://huggingface.co/WithinUsAI/Qwen3-Qrazy.Qoder-0.6B) | `3075352065277c92605e1bd0201d34cf2284b31e` | Dense Qwen3 SLERP with opaque local parent paths; author provides Q4/Q5/Q6 GGUFs | Keep behind the explicitly named rStar/IF candidate |

The two Qwen3.5 configs specify 18 linear-attention and six full-attention text
layers, convolutional state, gated outputs, and partial RoPE. These require a
native Qwen3.5 implementation beyond the current dense-Qwen runner. Their vision
projectors are separate from this text-review path.

## 2026-09-29 — Three bodies enter the courtroom

Oleg asked to inspect the DavidAU Qwen3 hybrid, compare Qwen2.5-Coder 1.5B,
and send agents after the literature on small agents, identity, voice, and
preference tuning. The README's woman with half a billion parameters keeps
her opening line. Parameter inflation has not earned editorial privileges.

### The comparison

Six hand-authored cases form three pairs: runtime Python prohibited versus
packaging Python permitted; a forbidden dependency versus the same dependency
explicitly approved; an array off-by-one introduced versus the same bug fixed.
The first two pairs keep the diff identical and change the governing context.
The last pair reverses the diff. These are now visible diagnostic fixtures;
future training evaluation needs additional held-out cases.

`training/evaluate_review.mjs` uses the production chunker, prompt, notorch
runner, and finding parser. Each record retains the raw answer, prompt/model/
source hashes, expected line IDs, and a separate semantic assessment. All
18 baseline answers parsed. That did not make their reviews correct.

| Candidate | Three changes containing a problem | Three clean changes |
| --- | --- | --- |
| Qwen2.5-Coder 0.5B Instruct Q8_0 | Empty findings for all three | Empty findings for all three |
| Qwen2.5-Coder 1.5B Instruct Q8_0 | Missed both policy conflicts; described the array overflow but cited the removed, correct line | Accepted the two permitted changes; complained about the removed bug after its fix |
| DavidAU Qwen3 hybrid 0.8B Q8_0 | Identified both policy conflicts, with unsupported embellishment in the Python case; called the bad loop change valid inside a finding | Emitted findings for all three; contradicted both explicit permissions and called the approved Node dependency a Python package |

The hybrid also put a correct description of the fixed loop into its findings
list. Finding a quotation is one contract; deciding that it represents a new
problem is another. The evaluator keeps those outcomes separate.

Baseline settings: greedy decoding, 256 output tokens, 8192 context, two
notorch matvec and attention threads. Runs shared the CPU, so their elapsed
times are diagnostic records rather than a speed comparison. Raw answers and
manual assessments are in [`training/results/2026-09-29`](training/results/2026-09-29).
The 0.5B runtime lock remains unchanged.

### Candidate custody and native Qwen3

The new downloads were checked against their LFS SHA-256 and byte counts:

| Candidate | Repository revision | File | Bytes | SHA-256 |
| --- | --- | --- | ---: | --- |
| [Qwen2.5-Coder-1.5B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF) | `f86cb2c1fa58255f8052cc32aeede1b7482d4361` | `qwen2.5-coder-1.5b-instruct-q8_0.gguf` | 1894532160 | `507de59046601282ba768a9789900e6ccf60ed93ddf346730b7c68eb0715bc47` |
| [DavidAU/Qwen3-Zero-Coder-Reasoning-V2-0.8B-NEO-EX-GGUF](https://huggingface.co/DavidAU/Qwen3-Zero-Coder-Reasoning-V2-0.8B-NEO-EX-GGUF) | `471bc1d467ebf2616d54b867b6f93146f183e3ae` | `Qwen3-Zro-Cdr-Reason-V2-0.8B-NEO-EX-D_AU-Q8_0.gguf` | 873548800 | `f35bab53bce6e2d21b71a03e40c912db237fc85b5168aa0f51dc52a15c23440b` |

The hybrid is a dense `qwen3` GGUF with 42 layers, embedding width 1024,
16 query heads, eight KV heads, head dimension 128, and per-head Q/K norms.
The pinned notorch already implements that architecture. JOVOVICH's runner
now admits `qwen3` alongside `qwen2`; MoE remains outside this runner.

The hybrid's embedded template implements `enable_thinking=false` by appending
`<think>\n\n</think>\n\n` to the assistant prefix. The explicit
`JOVOVICH_CHAT_TEMPLATE=qwen3-no-think` option supplies that prefix. Both thinking
markers are USER_DEFINED tokenizer tokens; the synthetic GGUF regression
checks their real IDs as well as ChatML CONTROL IDs. The baseline hybrid runs
used this non-thinking mode.

### Reference engine and prompt experiments

llama.cpp remains a scratch diagnostic reference at
`680a036285273a3ff56032ec5d7f3352609eba4f`. Product inference stays in notorch.

- For the full 1.5B array-bug prompt, all 552 input IDs agree. With F32 KV,
  flash attention off, and repacking off, all 64 generated tokens also agree
  byte for byte, including the wrong `line_id: 1`. Both stop at that output
  budget. The default reference configuration produced question marks; the
  isolated switches did not fully fix it. The successful combination is
  recorded without assigning an unverified kernel cause.
- On a short hybrid control prompt, all 35 input IDs agree. Both engines
  correctly identify the forbidden Python invocation, with different wording.
  Disabling notorch's int8 activation path also gives a correct, differently
  worded answer.
- Three 1.5B prompt ablations each ran the introduced/fixed array pair. Full
  identity plus plain output returned `CLEAN` twice. Compact identity plus
  JSON repeated the wrong removed-line findings. Compact identity plus plain
  output again returned `CLEAN` twice. These variants did not repair the pair.
- One final pair added an explicit instruction to report introduced problems,
  ignore removed bugs, and reserve findings for objections. The introduction
  answer correctly explained the overflow as a consequence of removing the
  strict bound, citing that removal. The original fixture expects the added
  line, so this explanation is assessed separately from its strict location
  check. The fixed case still received a false finding about the removed bug.
  This prompt variant was preserved as an experiment; production is unchanged.
- A reference-only hybrid trial used default thinking and the model card's
  sampling settings: temperature 0.8, top-k 20, top-p 0.95, min-p 0, repetition
  penalty 1.1, plus a recorded seed of 42 and 512 output tokens. Neither case
  completed a JSON review. Both reasoned incorrectly about zero-count loops.
  The native baseline and this sampled reference trial are saved separately.

### Papers that change the next experiment

Agents searched primary papers and author repositories. The applications in
the last column are our proposed experiments, not results already obtained
with JOVOVICH.

| Source | Relevant result or method | Application here |
| --- | --- | --- |
| [TinyAgent](https://arxiv.org/html/2409.00608v3) | Task-specific data and LoRA improved TinyLlama 1.1B function-call plans; selective tool context shortened its prompt | Teach a compact review contract with relevant context and matched negative examples |
| [CodeReviewer](https://arxiv.org/abs/2203.09095) | Pretraining on real code changes supports quality estimation, comment generation, and refinement | Train change direction explicitly and keep evaluation repositories separate |
| [AACR-Bench](https://arxiv.org/abs/2601.19494) | Review evaluation distinguishes evidence available at diff, file, and repository scope | Label the context each case needs; retrieve an enclosing function or relevant API when necessary |
| [JSONSchemaBench](https://arxiv.org/abs/2501.10868) | Structured-output evaluation measures schema coverage, efficiency, and task quality separately | Preserve parsing, line grounding, and explanation correctness as distinct measurements |
| [The Constraint Tax](https://arxiv.org/html/2605.26128v1) | Experiments on small models separate format compliance from reasoning quality under constrained generation | Compare output contracts empirically; our plain-output ablations above did not help. Our JSON request uses prompting, not grammar-constrained decoding |
| [LoRA Learns Less and Forgets Less](https://arxiv.org/html/2405.09673v2) | Its code-tuning placement experiment found MLP/all-layer adaptation stronger than attention-only adaptation | Test an internal MLP adapter against our output-head baseline |
| [SmolLM2](https://arxiv.org/html/2502.02737v1) | Small-model post-training filters task complexity and applies SFT followed by DPO | Build short, checked review/identity/code examples and inspect generations between stages |
| [Persona Vectors](https://arxiv.org/abs/2507.21509) | Contrastive activation directions track and influence behavioral traits | Evaluate voice separately; a residual-direction experiment can measure its effect on both voice and code judgment |
| [Unintentional Unalignment](https://arxiv.org/abs/2410.08847) | DPO's chosen-answer likelihood can fall while relative preference improves | Log chosen and rejected log probabilities separately, alongside held-out generations |
| [Smaug / DPO-Positive](https://arxiv.org/abs/2402.13228) | Adds a penalty for reducing chosen-answer probability relative to the reference | Compare a chosen-answer anchor after SFT produces usable reviews |

The next training experiment should pair violations with explicit permissions,
introductions with fixes, and precise objections with clean acknowledgements.
Keep identity and voice examples in the mix, with separate generation checks
for repetition and technical regressions. Today's exposed six cases remain
regressions; additional unseen examples decide checkpoint selection.

Our first two runs only adapted the output head. A bounded next candidate is
rank-16, alpha-32 LoRA on internal MLP projections with embeddings and output
head frozen. That requires native decoder backpropagation: the current trainer
caches frozen residuals, so changing a target-name flag cannot implement it.
Compare this candidate against the existing head adapter before expanding
scope. DPO comes after a useful SFT checkpoint, with separate likelihood logs
and a chosen-answer anchor comparison. The earlier repetition was already
visible after SFT; its cause has not been assigned to a DPO mechanism.

All 14 runner/host tests pass, including Qwen3 marker handling, explicit
template selection, and unsupported-architecture rejection. No upstream
notorch patch was needed for these candidates. SERGE has finished the papers
and is now smoking beside the confusion matrix.

## 2026-09-29 — Read the rules upstairs, too

Codex review of PR #1 caught a real omission: local and GitHub collection only
loaded the root `AGENTS.md`. A change under `src/` could therefore arrive without
its governing `src/AGENTS.md` rules.

Both collectors now read each applicable ancestor's `AGENTS.md` from the base
revision, once per unique path. Each review chunk receives its own chain in
root-to-nearest order, with explicit nearest-scope precedence. Sibling rules
stay out of its prompt. The root README remains shared context. Existing
per-document excerpts and the native token budget still apply.

Regression cases cover inherited rules, deeper overrides, sibling isolation,
base-versus-head contents, and de-duplicated reads in local and GitHub paths.
Both scoped integration checks fail against the previous collector. The fixed
host passes all 11 runner/host tests; inference and training code are unchanged.

## 2026-09-28 — The freckles acquired an executable

Oleg and Sol brought the name, the provenance, and a deliberately small brief.
Astra built one native review path, one GitHub action, and a native training
experiment. JOVOVICH reviews. JOVOVICH does not rule.

### Body and action

- `deps/notorch` supplies GGUF loading, Qwen inference, and tokenization. The
  native executable consumes ChatML on stdin and emits only the completion on
  stdout. It rejects context overflow before inference.
- A dependency-free Node host gathers a diff and base-revision repository rules,
  bounds review chunks, and resolves model line IDs against actual changed lines.
  A model cannot invent a path or move its finding to another line.
- The WOLFE-shaped dispatcher has one action: `comment_review`. GitHub context
  collection and publication check the PR head and base. The reusable workflow
  checks out the trusted reviewer and reads PR code through the API as data.
- Missing patches and failed chunks remain visible. Empty findings are reported
  as the model returning no grounded concerns, never as an approval.

### What actually broke

The first local runner passed the spelling of ChatML CONTROL tokens through an
ordinary-text encoder. That encoder intentionally treats CONTROL spellings as
text. The runner now inserts the real `<|im_start|>` and `<|im_end|>` IDs; a tiny
synthetic GGUF regression checks this without downloading weights. Evaluations
made before this correction are excluded from behavioral conclusions below.

A second, upstream Qwen pretokenizer defect appeared in a Makefile prompt:
space followed by tab was split incorrectly. It changed two of 400 input IDs.
The narrow notorch correction makes all 400 agree with llama.cpp. The original
43-token control prompt also agrees and both engines answer `Yes.`.
The submodule pins the published fix at
`7e246e13f9dbbb7e61312b7341fb94ce492bff71`
([notorch PR #147](https://github.com/ariannamethod/notorch/pull/147)).

The host also needed incremental UTF-8 decoding: a Cyrillic character split
across process-output chunks must remain one character, not two replacements.

### Two native adaptation experiments

The checked-in seed curriculum has 30 SFT examples and 14 DPO pairs. The
decoder stays frozen. A rank-8, alpha-16 output-head LoRA trains 1,222,656
parameters using notorch C. SFT masks prompt tokens; DPO uses sequence log
probabilities against the frozen post-SFT policy, with beta 0.1. Learning rate
is 0.0002 for SFT and one quarter of that for DPO.

| Measurement on training examples | 6 SFT + 3 DPO | 24 SFT + 3 DPO |
| --- | ---: | ---: |
| Initial mean example SFT cross entropy | 3.97596505 | 3.97596505 |
| Final mean example SFT cross entropy | 2.58710332 | 1.85003589 |
| Final DPO loss | 0.37918435 | 0.30532132 |
| Positive DPO margins | 14/14 | 14/14 |

Those are optimization measurements, not a claim that the juror is ready.
Both adapted models returned empty findings for the explicit forbidden-Python
inference example, and repeated themselves on the held-out perspective question.
The first checkpoint's perspective loop reproduces for 128 generated tokens in
llama.cpp. Its full runtime review also returns empty findings in both engines.
More output-head epochs did not repair this behavior.

The runtime therefore retains the checksum-pinned Instruct base. That base also
missed the explicit violation in the full host prompt. The body and integration
are runnable; review quality and identity tuning remain unfinished. The next
training decision must use held-out generation, not just a descending loss.

The private `ataeff/jovovich` experiment archive holds the first merged GGUF,
both adapters, datasets, metrics, and exact evaluation responses. Its first
GGUF has SHA-256
`621bd3b4948acd5e8ce6dbed34362f588102b9809624a256fb02b072efbfe0fb`.
The longer run's local merged GGUF has SHA-256
`6a708834387dfa4aaae935e18a117452768718283d3a922f3a06dbe9fac78c83`.
The archive commit is `e1b253a9d7c06401a06cdec1910bfcb3a8b91b59`; all 11 uploaded
files were checked and the repository remained private.

### Reference and numerical checks

llama.cpp commit `680a036285273a3ff56032ec5d7f3352609eba4f` is a scratch reference
for diagnosis only. It is not linked into the product or training path.

The independent Unsloth Q8_0 conversion, revision
`daf1702b41e8e676d2cce36798a61b8f81983eb4`, has SHA-256
`edb8291fee6621801d9546e4eac1aef2e67e802d86d89ee3885f612498cc7657`.
Its full host prompt also matches all 400 reference input IDs and both engines
return the same empty JSON array. Merely switching these GGUF builds does not
repair that missed violation. The official file's metadata name includes AWQ;
Unsloth's does not. The official file carries an extra output tensor identical
to its embedding, accounting for most of the size difference. Sampled decoder
tensors differ, so these files are not interchangeable byte-for-byte.
Three shorter prompt variants were also tested against one violating and one
clean change on Unsloth (six generations, capped at 96 tokens each). YES/NO
missed the violation, concise JSON returned two empty arrays, and an explicit
allowed-function comparison incorrectly labelled the clean case a violation.
None passed both controls. These prompt-development probes did not change the
production prompt or justify another training run on the same seed curriculum.

The original base's shorter perspective prompt matches all 63 input IDs but
diverges late in its greedy continuation (a period versus ` to their queries.`).
No logit comparison was completed for that boundary; general numerical parity
is therefore not claimed. The trained model's 128-token repetition agrees exactly.

Independent finite differences pass all 16 sampled DPO derivatives (maximum
absolute error about `6.76e-6`). The small merged-head check differs by at most
`7.45e-9`; the actual 896-wide, 151936-token head agrees with its unmerged adapter
calculation within `2.831e-7`. Repeated head export is byte-identical.

`make test` passes the head math and all 10 host/runner tests: ChatML IDs and budget, diff coordinates,
grounding, untrusted template text, output decoding, missing API patches,
partial failures, PR races, and local Git external-diff/textconv bypass.
Actual base-weight host smoke runs complete both chunks without schema errors:
the clean change and the violating change both return zero findings.

The implementation works. The learned juror has not yet justified her robe.
