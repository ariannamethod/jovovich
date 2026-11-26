# Review every changed path

The batch path collects all changed files between two commits, evaluates each
file through the existing NoTorch + AML reviewer, and emits one complete report.
`aml/report.aml` chooses **CONCERN** if any file received CONCERN; otherwise it
chooses **CLEAN**. Each file retains its original probability pair.

Run from the JOVOVICH repository root after `make`. Check the exit status of
each command before continuing; a shell script can use `set -e`.

```sh
./build/jovovich-pack --all /path/to/repo BASE HEAD RULES.md > batch.jsonl
./build/jovovich model.gguf tokenizer.gguf --json < batch.jsonl > answers.jsonl
./build/jovovich-report batch.jsonl answers.jsonl > report.md
./build/jovovich-report batch.jsonl answers.jsonl --json > report.json
```

An optional inclusive rule range follows `RULES.md`, for example `65 67`.
The rules come from BASE for every file. Paths come from Git's NUL-delimited
changed-path list, with rename detection disabled; a rename contributes its
deleted and added paths. The model loads once for the JSONL input and starts
each file with a fresh inference cache.

Changed submodule pins are included even when the reviewed repository has
`diff.ignoreSubmodules=all` or a per-submodule ignore setting. Their patches
use the short format with full old/new commit IDs, independent of
`diff.submodule`. This captures the dependency pin change at its Git path.

## Complete input and output

Each packed input retains the [Git source contract](git-review.md) and adds:

| Batch field | Content |
| --- | --- |
| `schema` | `jovovich.git-batch/1` |
| `scope` | `all_changed_paths` |
| `id` | SHA-256 of the ordered file/context/source manifest |
| `index` | Zero-based position in the manifest |
| `count` | Total number of changed paths |

The digest covers the schema, scope and ordered items, each containing `file`,
the context `id`, and complete Git `source`. All rows must agree on the batch
ID, count, commit pair and selected baseline rules. The report recomputes the
digest and requires every position exactly once.

For each answer, the report verifies the corresponding file, context, excerpts,
Git metadata, pinned model and revision, weight/tokenizer hashes, exact input-row
hash, AML question, probability pair, verdict and execution timestamp. It also
checks JSON syntax and rejects duplicate keys. For adapter runs, it verifies
one readout digest across all answers and includes it in the JSON report. Missing, extra, repeated,
reordered or inconsistent answers cause a nonzero exit with no report bytes
written. A model run that stops partway leaves a partial answer stream which
the report refuses. The final report is buffered until all checks pass.

The packer accepts up to **64 changed paths**, **256 KiB per Git capture**, and
**16 MiB per batch**, with **1 MiB per JSONL row**. Report inputs and answer
streams have the same row and total byte bounds. In the text-only mode, binary changes or an exceeded
bound abort the entire pack before any row is written. The native model keeps
its ASCII English and 8,192-token input limits.

A batch that selected an AML rule fact also binds its complete receipt into the
batch digest. Every file uses that receipt and the report checks it against
each answer. Saved packs and answers carry everything needed to replay this
check. [Rule memory](fact-memory.md)

## Output

Markdown starts with the overall verdict and exact file counts, followed by the
existing English answer for every file: decision, source commits, selected rule,
patch and both probabilities. JSON uses `jovovich.review-report/1`:

| Field | Content |
| --- | --- |
| `scope` | `all_changed_paths` |
| `batch_id` | Verified manifest digest |
| `base_commit`, `head_commit` | Reviewed commit pair |
| `summary.verdict` | AML aggregate decision |
| `summary.reviewed_files` | Number of validated file answers |
| `summary.concern_files`, `summary.clean_files` | Counts of each verdict |
| `reviews` | Complete original per-file answer objects, in manifest order |

The aggregate has a verdict and counts. Probabilities belong to the individual
file decisions and are preserved without averaging.

## Combine text and visual reviews

When a change modifies committed images, provide one
[visual comparison request](fact-memory.md#compare-a-visual-change) per changed
binary image. Each request selects two exact memory revisions, the image path,
and a rule from the base commit. The image must exist as a regular Git blob at
both commits. The same logical repository and PR number must appear in both
observations. Supply that scope explicitly to packing and reporting:

```sh
set -e
./build/jovovich-pack --with-visual visual-memory studio/east 7 comparisons.jsonl \
  --all /path/to/repo BASE HEAD RULES.md 2 2 > batch.jsonl
./build/jovovich model.gguf tokenizer.gguf --json --with-visual visual-memory \
  < batch.jsonl > answers.jsonl
./build/jovovich-report batch.jsonl answers.jsonl \
  --with-visual visual-memory studio/east 7 > report.md
./build/jovovich-report batch.jsonl answers.jsonl \
  --with-visual visual-memory studio/east 7 --json > report.json
```

The packer enumerates every changed Git path before writing anything. Text
paths retain their patch evidence; a visual comparison cannot replace a text
decision. Each binary path must have exactly one request bound to the batch's exact
BASE/HEAD commits and that path. Missing, duplicate, foreign or unused requests
abort the pack. Other binary changes, image additions/deletions and image
renames remain unsupported. A change containing only modified images works.
The repository name is the caller's logical memory scope, as in rule memory.

The mixed manifest uses `jovovich.git-batch/2`. Its digest includes the original
ordered file/context/source items and, for visual entries, the SHA-256 of the
complete verified comparison receipt. A visual row's `visual_request` contains
the captured comparison object without surrounding JSONL whitespace. Inference
hashes those exact nested bytes. Text rows still hash the complete input line.
The model loads once and uses a fresh inference cache for each decision.

For a regular `.html` or `.htm` file at HEAD (case-insensitive extension), this
mixed mode also captures the complete committed HTML in `html_state`, including
its Git blob ID and SHA-256. The manifest binds the digest of that state. The
model reads the selected base rule and the complete after-file, and answers
whether that file satisfies the requirement. This includes unchanged elements
outside the diff hunks. The original diff, context ID and rule receipt remain
in the answer as source evidence.

Each HTML decision uses two fresh forwards: CONCERN/CLEAN and CLEAN/CONCERN.
`aml/score-html.aml` aligns their logits by meaning and averages each pair before
the ordinary float32 softmax. CONCERN still wins an exact tie; there is no fitted
threshold. The answer's `execution.file_view` names `html-head-paired/1` and
retains both prompt hashes and all four logits. Reporting rereads the HTML blob
at HEAD, rebuilds both AML prompts and recomputes the probability pair. It uses
the checkout already identified by the visual comparison, not the worktree's
current HTML. Attached trace evidence is appended to this complete-file view.

Deleted HTML paths, symlinks and other text types keep the existing diff view.
Text-only packing and archived mixed inputs without `html_state` retain their
original behavior. The complete HTML must fit the existing capture, row and
8,192-token model limits; an over-limit file does not silently lose its state.

Reporting rereads the selected historical observations, verifies their image
blobs and base rule against Git, and reconstructs the comparison receipt. The
answer must carry that exact receipt, input and prompt hashes, pinned model and
tokenizer hashes, and the AML question/options. Logits must reproduce the listed
probabilities; the semantic CONCERN/CLEAN mapping must match the option order.
CONCERN wins a tie in either order. Keep the captured nested receipt bytes intact
when moving results; rewriting their JSON formatting changes this binding.

JSON uses `jovovich.review-report/2`, with `repository`, `pull_request`, a
`visual_summary` and the common `summary`. The ordered `reviews` array retains
ordinary text answers and `jovovich.visual-review/1` answers. A CONCERN from
either kind contributes to the common total. Markdown shows each image's
before/after answer, memory revision, Git commit, image SHA-256, and quoted rule.
Missing, extra, reordered, repeated or inconsistent answers produce no report.
The selected visual journal and Git objects must remain available when reporting.

Rule-memory packing remains available: put `--remember DIR REPOSITORY KEY` or
`--recall DIR REPOSITORY KEY` before `--with-visual`. The remembered repository
must match the visual scope. The mixed report retains that rule receipt at its
root, including when the change contains only images. It does not append a
model verdict to the rule journal. This mode accepts already-attached
text execution evidence. It does not combine with `--locate`, `--snapshot` or
`--auto-snapshots`; those execution operations keep their text-batch path.
Readout adapters and canonical
boundary inference also keep their separate existing invocation.

Without `--with-visual`, v1 manifest digests and text report bytes are unchanged.

## Keep a mixed review in the PR's AML history

Pack with a named rule using `--remember` or `--recall` as above. To save the
validated report, supply both `--memory` and `--record-pr`. The history and
visual-memory directories may differ. Fetch the PR's actual metadata, including
its opening date and exact base/head revisions:

```sh
mkdir -p review-memory
gh pr view 7 --repo studio/east \
  --json number,url,createdAt,baseRefOid,headRefOid > pr.json
./build/jovovich-report batch.jsonl answers.jsonl \
  --with-visual visual-memory studio/east 7 \
  --memory review-memory --record-pr studio/east pr.json > report.md
./build/jovovich-replay history review-memory studio/east 7
./build/jovovich-replay history review-memory studio/east 7 HEAD_SHA
```

The repository and PR number must match the visual scope; metadata revisions
must match the batch. The existing per-PR AML journal stores `evidence.review`
with schema `jovovich.mixed-review/1`: aggregate counts, visual counts, and each
file's complete input and answer. HTML state, both prompt hashes and raw logits,
visual observations, model hashes, rule provenance and inference clocks survive
unchanged. The outer observation dates PR opening and successful publication
separately with JANUS.CALENDAR.

An exact publication retry, including switching Markdown to JSON, keeps one
observation and its first publication clock. A new answer receipt is a new
observation. The journal permits 256 distinct observations per PR and up to
1 MiB for each complete stored observation, including its enclosing metadata.
The AML checkpoint also has a total 64 MiB limit.
Validation, capacity or persistence failure emits no report and leaves the
previous checkpoint intact. Rule and visual checkpoints remain unchanged.

History reading requires neither Git nor the model nor the visual journal.
It validates each selected mixed observation against its saved evidence digest
before emitting the history. A model-review-only history has status `reviewed`;
deterministic execution findings retain `checked`. Model answers occupy
`evidence.review`, with `evidence.findings` empty, and supply no snapshot
coverage. Existing execution and snapshot history queries keep their behavior.

### Compare two recorded reviews

List the mixed reviews in one PR, then select two exact observation IDs:

```sh
./build/jovovich-replay reviews review-memory studio/east 7
./build/jovovich-replay reviews review-memory studio/east 7 \
  --compare BEFORE_OBSERVATION_ID AFTER_OBSERVATION_ID
```

The `jovovich.mixed-review-index/1` index gives each evidence SHA-256, its
one-based ordinal in the complete PR journal, batch ID, base/head revisions,
rule receipt, publication clock and counts. Repeated evaluations of one head
can therefore be selected individually. Execution-only entries retain their
positions in the journal and are omitted from this index.

The earlier ID must precede the later ID in this journal's insertion order.
`jovovich.mixed-review-comparison/1` retains both complete original observations
and aligns their files by exact Git path. Per-file `before`/`after` references
give zero-based positions in those original file arrays and the saved verdicts.
The array keeps the earlier review's path order, then appends newly reviewed
paths in the later review's order. AML classifies each pair and counts the results:

| Transition | Earlier review | Later review |
| --- | --- | --- |
| `concern_to_clean` | CONCERN | CLEAN |
| `clean_to_concern` | CLEAN | CONCERN |
| `unchanged_concern` | CONCERN | CONCERN |
| `unchanged_clean` | CLEAN | CLEAN |
| `first_review` | Path absent | Path reviewed |
| `not_reviewed_after` | Path reviewed | Path absent |
| `not_comparable` | Different rule, model, policy or review kind | Changed identities listed in `reasons` |

Compatibility requires the same named rule receipt and selected requirement.
Model identities include text/tokenizer hashes and the vision hashes in both
image observations. Policy identities include the question, HTML/trace/boundary
view, readout, visual memory key, option order and image pixel budget. Every
changed identity is reported; a missing file has a `null` reference, and a
rename produces one absent path and one new path.

Both commands are read-only and work without Git, model files or the visual
journal. The index validates evidence digests before filtering entries. Selected
comparisons verify both original records; unknown, repeated, reversed or
ambiguous IDs fail without partial output. Appending later observations leaves
a comparison between existing IDs byte-identical. Ordinary `history` output
and stored records retain their format.

### Bring the previous review into the report

Add `--compare-previous` when recording a mixed review:

```sh
./build/jovovich-report batch.jsonl answers.jsonl \
  --with-visual visual-memory studio/east 7 \
  --memory review-memory --record-pr studio/east pr.json \
  --compare-previous > report.md
```

The report appends a **Since the previous review** section with the two
observation IDs, journal positions, head revisions and a file-by-file table.
The preceding mixed review is selected within this repository and PR by journal
insertion order. Execution-only entries retain their positions and are skipped.
A changed rule, model, policy or review kind appears in the table; a missing
path is marked **Not reviewed this time**.

With `--json`, `review_observation` gives the current receipt's indexed identity
and `review_comparison` contains the exact comparison returned by `replay reviews
--compare`, including both complete observations. The first mixed review has
`review_comparison: null` and Markdown explicitly reports no earlier mixed review.

Selection, comparison and journal publication share the writer lock. The whole
report is rendered and checked before committing. A failed comparison, report
write or checkpoint save publishes no report; a failed render or comparison
leaves the journal intact. A retry of an existing observation uses its original
predecessor and clock, even after later reviews arrive. The flag requires
`--with-visual`, `--memory` and `--record-pr`. Reports without it retain their bytes.

## Include verified findings in the PR comment

Give the report the project repository and the driver that measured the batch.
It reproduces the checks after validating all model answers. A located
regression includes its head line range, quoted rule and observations. Deleted
lines use base coordinates. Ambiguous results list the qualifying ranges.

```sh
build/jovovich-report replayed.jsonl answers.jsonl --locate "$repo" "$driver" --memory "$memory"
```

With `--memory DIR`, a cited case is read from the AML journal by its original
input digest under the repository, rule, file and driver used for this review.
The comment includes the earlier measurement and its own rule receipt, including
when a newer receipt supersedes it. An unavailable or conflicting citation stops
the report. Omit the memory option to report fresh execution with its recorded reference.

Add `--snapshot REPO RENDER_DRIVER FILE` for each expected output to regenerate.
Markdown puts verified checks above the file votes and diffs. JSON retains all
findings, including successful checks, in `verified_findings`. These commands
write the comment to stdout.

## Recorded native run

[`examples/batch-20261106`](../examples/batch-20261106/) contains an actual
NoTorch model run over a controlled two-file Git fixture. Its commits and rules
are reproducible from the first two commits in `tests/check_batch.sh` using
Git's SHA-1 object format.

| File and change | CONCERN | CLEAN | Verdict |
| --- | ---: | ---: | --- |
| `math.c`: retain `square(x) == x * x` while naming the intermediate result | 22.4023% | 77.5977% | CLEAN |
| `status.c`: add libcurl despite the standard-library-only rule | 84.5038% | 15.4962% | CONCERN |

The resulting report is **CONCERN**, with one file in each category. The saved
inputs, live answers, Markdown, JSON and run metadata preserve the complete
execution. The model performed zero training updates and generated zero tokens.

`make check` covers all-clean, mixed and tied file decisions, Markdown output,
14 incomplete/inconsistent-report refusals, the 64/65-file boundary and atomic
refusal of a batch containing a binary change. These protocol checks use
explicitly synthetic probability fixtures. The same checks pass with SHA-256
Git objects. Changing the AML threshold from `> 0` to `> 1` makes the mixed-case
verification fail.

## Select snapshot checks for a repository

Keep a local policy with the operator's renderer. Set its repository to the
same owner/name used to pack the AML rule. For example, a policy for inih
matches its expected test outputs with one shell-style path pattern.

```sh
renderer_sha=$(shasum -a 256 < "$renderer" | awk '{print $1}')
jq -n --arg sha "$renderer_sha" '{
  schema: "jovovich.snapshot-routes/1", repository: "benhoyt/inih",
  harness_sha256: $sha, paths: ["tests/baseline_*.txt"]
}' > "$policy"
build/jovovich-report batch.jsonl answers.jsonl --memory "$memory" \
  --auto-snapshots "$checkout" "$renderer" "$policy"
```

Reuse this policy for later PRs. The report authenticates the named rule in
AML memory and checks the complete changed-path list against Git. Patterns
match whole paths, are case-sensitive, and keep wildcards within one path
component. A leading dot in a component must be matched explicitly. Multiple
patterns can select the same file. It receives one snapshot check.

The renderer is pinned by SHA-256 before execution. Each chosen regular file
is regenerated against the reviewed head. A reproducible mismatch includes
the file, line, byte column and differing text. JSON retains the model votes
and includes `snapshot_coverage` with match counts, the policy and renderer
digests, and every skipped path with its reason. Deleted paths, non-regular
head entries and paths outside the policy are identified separately. Add
`--locate "$checkout" "$execution_driver"` to reproduce execution findings
in the same report.

## Keep snapshot results in the PR's AML history

Pass the GitHub PR metadata described in [counterexample history](counterexamples.md#when-a-pull-request-opened-and-which-revisions-were-checked)
when generating either report format. The completed report records its findings,
coverage, exact Git revisions and JANUS verification time in one checkpoint
update. Identical evidence reuses its observation. A run whose policy skips
every file records those skips.

```sh
build/jovovich-report batch.jsonl answers.jsonl --memory "$memory" \
  --auto-snapshots "$checkout" "$renderer" "$policy" --record-pr "$owner_repo" pr.json
build/jovovich-replay history "$memory" "$owner_repo" "$number" \
  --snapshot "$checkout" "$tip_sha" "$file"
```

The query walks the requested commit's first-parent history. It returns
recorded checks for that file in Git order, with their original timestamps.
A mismatch includes its line, byte column, expected and regenerated text.
Its `first_checked_match` is the earliest later verified match on that
line with the same AML rule receipt, policy digest and renderer digest.
A null value means there is no such observation through this tip.
Contradictory measurements at a commit appear as `conflicting` for that
rule and renderer. AML uses an unambiguous match for recovery.
`status_at_head` describes the requested SHA itself. A skipped or
unmeasured file at that SHA is `unverified`. The ordinary PR history
continues to include execution-only entries from older checkpoints.

When reviewing a new PR with the same command, the Markdown comment cites
earlier mismatches under **Earlier snapshot checks**. JSON exposes the same
citations in `prior_snapshot_cases`. Each currently measured file gets at most
one citation, from the highest-numbered earlier PR in the same repository
with eligible evidence. The file, full rule receipt, routing policy and
renderer must match. The citation names the source PR, line, byte column,
differing bytes, mismatch commit and first later match verified in that PR.
A null byte field denotes end of file. Measurements which disagree on the regenerated bytes at one commit are conflicting.

The new PR's base bounds the history search. Git follows first parents when
they contain the cited mismatch. At the merge that introduced the mismatch,
the search follows its source branch. An untested merge tip can therefore
lead back to a tested repair. A null recovery leaves the old mismatch open
in the cited observations. Current checks stay in `verified_findings`, and
the journal records the new PR's own evidence.

### Remember a squash merge

After the merge, fetch the merged GitHub PR metadata. Supply the landing
SHA from the integration event separately. Run this while both the source
head and the landed commit are available locally. Reuse the final batch
previously recorded for that PR, its AML memory, policy and renderer.

```sh
gh pr view "$number" --repo "$owner_repo" \
  --json number,url,createdAt,baseRefOid,headRefOid,state,mergedAt,mergeCommit > merged.json
build/jovovich-replay land "$checkout" "$renderer" "$policy" \
  --record-pr "$memory" "$owner_repo" merged.json "$landing_sha" < final-source-batch.jsonl
build/jovovich-replay history "$memory" "$owner_repo" "$number" "$landing_sha"
```

The command binds the repository, PR, reviewed base/head and event SHA to
the supplied GitHub record. Git must show a single-parent integration
on a descendant of the reviewed base, with the source head outside its
ancestry and the rule still applicable at its parent. The renderer checks
the final batch's routed snapshots on the landed tree. It also rechecks
earlier mismatches on the source's first-parent line, including files
reverted out of the final diff. The combined path limit is 64. Missing and
non-regular files retain their coverage reasons.

The resulting AML observation keeps the original check identifiers and
source Git order. JANUS records GitHub's merge instant in
`evidence.landing.merged_at` and the actual verification instant in
`checked_at`. A repeat of the same evidence reuses the original observation.
A new source observation recorded during rendering requires a retry.

A later PR can cite these checks when its base includes the landed SHA,
even in a fresh clone after the source branch was removed. Its citation
includes `landing.source_head`, `source_status`, `commit` and `status`.
For example, a source fix can be `met` and its landing `mismatch`. An earlier
source mismatch can also have the squash commit as its first verified match.
Without a recorded landing, the usual Git ancestry search applies.

### Compare what was known about the same commit

Run the query for one repository, PR, full commit SHA and path. The two UTC
cutoffs include observations through the specified millisecond. A whole
second denotes its start. Both views use the original JANUS `checked_at`.

```sh
build/jovovich-replay history "$memory" "$owner_repo" "$number" \
  --snapshot "$checkout" "$commit" "$file" --compare-known-at "$from" "$to"
```

Each rule, routing policy and renderer has its own stream. Its `before` and
`after` contain the verdict and exact receipt IDs. `new_checks` gives the
timestamps and results added in the interval, including byte-level findings
or skip reasons. Conflicting observations on the same SHA remain visible.
An empty stream list means there were no checks of this file by the second
cutoff. Pass `--through JOURNAL_HEAD` with the returned `journal_head` to
repeat a reading against the same prefix after more observations arrive.
To compare a saved answer to the current journal, use its ending cutoff as
`from` and pass its `journal_head` as `--from-journal`. A receipt added later
can then appear in `new_checks` even when its check time falls inside the
earlier window. Both journal identities are included in the result.
