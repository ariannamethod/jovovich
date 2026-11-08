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
streams have the same row and total byte bounds. Binary changes or an exceeded
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
