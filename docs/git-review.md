# Review a real Git change

`jovovich-pack` reads one explicit Git path at two resolved commits and the
repository rules from the base commit. AML constructs the English review
context. The packer writes the existing JSONL input contract, extended with
Git source metadata; `jovovich` evaluates it through NoTorch.

Build from this repository root, with Git installed:

```sh
make
./build/jovovich-pack /path/to/repo BASE HEAD RULES.md src/example.c > input.jsonl
./build/jovovich model.gguf tokenizer.gguf --json < input.jsonl > answer.jsonl
```

Both revisions are resolved to commit IDs before any content is read. `BASE`
and `HEAD` may be branch names, tags or commit IDs. `RULES.md` must be a regular
file in `BASE`. Supply repository-relative paths. The packer does not modify
the source repository. Run the two commands separately and check each exit
code; when using a shell pipeline, enable that shell's `pipefail` option.

To select a relevant verbatim range from a longer rules file, append inclusive
one-based line numbers:

```sh
./build/jovovich-pack /path/to/notorch \
  a3ac4b57f79feb92bb88ed9fc7cf1f472a945b8d \
  560a6e186b58bea79c47b2571e844a35ae541244 \
  AGENTS.md harness/arch_qwen35.c 65 67 > input.jsonl
```

The selected range is explicit in the output. The caller chooses the rules and
file scope. Use [`--all` and the batch report](batch-review.md) to review every
changed path together. Diff capture uses eight
context lines and disables rename detection, so additions and deletions are
reviewable at their individual paths. The output contains the supplied rules
and the actual patch. Rules changed by the proposed commit do not replace the
selected baseline rules. Working-tree edits, external diff commands and
textconv output do not enter the record.

All diff reads explicitly include submodule changes. Gitlink patches use the
short format and retain full old/new commit IDs even when local Git settings
ignore submodules or request the log-style display.

## Source contract

The optional `source` object is retained in live JSON answers:

| Field | Content |
| --- | --- |
| `kind` | `git` |
| `base_commit`, `head_commit` | Resolved full Git object IDs |
| `rules_path`, `rules_blob` | Baseline rules path and complete rules blob ID |
| `rule_first_line`, `rule_last_line` | Exact inclusive selected line range |
| `rules_sha256` | SHA-256 of the selected rule bytes |
| `diff_sha256` | SHA-256 of the complete captured patch bytes |

The input ID is SHA-256 of the AML-built context. The live host checks both
content hashes before inference and retains the source metadata beside its
execution record. Git SHA-1 and SHA-256 object IDs are supported. The packer's
Git reads establish commit provenance; a saved JSON input can be replayed
without reopening its source repository. Markdown answers also show the commit
pair and selected rules path/lines.

Each Git command has a 256 KiB capture limit; oversized captures fail without
truncation. Binary patches, unchanged or missing paths, directories, symlinked
rules, unresolved revisions and invalid line ranges return errors before any
JSON record is written. The complete record is buffered before publication.
The native model input retains its current ASCII and 8,192-token limits. The
packer preserves text exactly; it performs no Unicode transliteration.

## Verification

`make check` creates a temporary real Git repository and verifies exact patch
bytes, baseline rules even when the proposal rewrites them, selected lines,
filenames containing shell syntax and literal Git pathspec syntax, dirty
working-tree isolation, disabled external diff/textconv commands and nine
error cases. Four valid source records pass 80 C assertions. The ordinary
saved/AML gate still passes all 941 checks, plus the formatter rejection checks.
The same Git fixture also passes with `GIT_DEFAULT_HASH=sha256`.

A temporary defective packer reading rules from `HEAD` instead of `BASE` fails
the source-record gate. The normal packer passes it.

The [recorded NoTorch review](../examples/git-notorch-20261106/) uses the real
two-line Qwen3.5 head-offset fix and lines 65–67 of its baseline `AGENTS.md`.
Original OneJev selected **CLEAN 59.78704690933228%**,
**CONCERN 40.2129590511322%**. Twenty-eight live assertions verify the retained
source, evidence, verdict and execution metadata. A second row with an altered
diff hash was refused before another decision, with `Git evidence hash mismatch`.

The original model, weights, arithmetic and A/B question are unchanged in this
stage. Python remains absent from the repository's build, tests and runtime.

A harness with executions at both commits can [attach paired callback traces](trace-evidence.md)
to the packed input before running the reviewer.
