# A rule can outlive its review

JOVOVICH's first persistent fact is a repository requirement quoted from a Git
base. Its subject is the caller's repository name. Its key names an agreement
such as `draw-order`. The value is the exact text of the selected lines,
including their line endings.

LALO's fact journal records a source, the world an assertion describes, when it
became known and which assertion it corrects. Here the world is a Git base
commit and a line range. A UTC receipt time records arrival and a journal-wide
sequence gives an exact knowledge cutoff, including for two writes in the
same millisecond. AML owns the journal, selection, correction and checkpoint.
[LALO fact ledger](https://github.com/ariannamethod/LALO/blob/aab68a37d0bf2555c6c5bd7e0b578678b6f13c67/src/ledger.js) · [LALO action memory](https://github.com/ariannamethod/LALO/blob/aab68a37d0bf2555c6c5bd7e0b578678b6f13c67/docs/ACTION_MEMORY.md) · [AML rule memory](../aml/rule-memory.aml)

## Carry an agreement forward

Run from JOVOVICH's root. Create a local memory directory. Use the same logical
repository name across clones. Repository names and keys accept 1–128 ASCII
letters, digits, dots, slashes, underscores or hyphens.

```sh
mkdir -p build/memory
./build/jovovich-pack --remember build/memory studio/render draw-order \
  --all /path/to/repo BASE_1 HEAD_1 RULES.md 2 2 > first.jsonl
./build/jovovich-pack --fact build/memory studio/render draw-order
./build/jovovich-pack --recall build/memory studio/render draw-order \
  --all /path/to/repo BASE_2 HEAD_2 > second.jsonl
./build/jovovich model.gguf tokenizer.gguf --json < second.jsonl > second-answers.jsonl
./build/jovovich-report second.jsonl second-answers.jsonl
```

`--remember` records the rule after the Git pack has been staged. A receipt
identifies that Git input even if model inference is run later. Packing a
single file works too. Omit `--all` and append the changed path after the
rules path when recording, or after the head when recalling. On capture the
optional line range comes last.

`--recall` resolves the prior rule before inference. The packer checks that its
original base is an ancestor of the new base, then reads the recorded path and
lines from the new base and compares the bytes. A moved, removed or rewritten
rule needs an explicit new receipt. The question gets one copy of the
verified rule. Both JSON and Markdown answers cite its earlier Git review.
The full receipt is bound into the batch digest and each answer is checked
against its own packed row. Replaying a saved pack works without the store.

## Correct a fact and replay an earlier review

If the current receipt for this key is 1, record a revision with the new source
coordinates. The predecessor number comes from `--fact`. Sequence numbers
count all keys in this store.

```sh
./build/jovovich-pack --remember build/memory studio/render draw-order --supersedes 1 \
  --all /path/to/repo BASE_3 HEAD_3 RULES.md 2 2 > corrected.jsonl
./build/jovovich-pack --fact build/memory studio/render draw-order --as-of 1
./build/jovovich-pack --recall build/memory studio/render draw-order --as-of 1 \
  --all /path/to/repo BASE_2 HEAD_2 > replay.jsonl
```

The default lookup selects the latest assertion for this repository and key.
`--as-of N` selects the last one known through journal entry N, then applies the
same Git checks. A receipt names its predecessor in `supersedes`. Zero starts
a lineage. Independent keys have independent lineages. Each revision retains
the source base and head, file, inclusive line range, literal value and UTC time.

There is one checkpoint per directory, with up to 256 receipts and 16 KiB of
rule text per receipt. A stable POSIX writer lock covers load through atomic
checkpoint publication. Concurrent readers see a complete checkpoint.
Retrying the identical current capture returns its original receipt. Stale
competing corrections fail. At capacity an identical retry still works.
AML reports a damaged checkpoint and preserves it. If directory synchronization
fails after the atomic rename, the packer reports the committed receipt with
a diagnostic on stderr.

## Reproduce the two reviews

`make check` includes independent processes, distinct Git review pairs, a
changed agreement, replay at an earlier receipt, tampering and competing
writers. The optional live test also compiles both revisions of `draw.c`,
captures their callbacks and submits the ordinary review inputs to OneJev.

```sh
JOV_MEMORY_MODEL=/path/to/model.gguf JOV_MEMORY_TOKENIZER=/path/to/tokenizer.gguf \
  sh tests/check_rule_memory.sh
```

The controlled patch calls `scan` then `paint`. At mode 1 its base called
them in the opposite order. The three native F32 answers used the same patch
and the same observed executions.

| Rule supplied to OneJev | CONCERN | CLEAN |
| --- | ---: | ---: |
| Remembered `scan → paint` from the first review | 31.0462% | **68.9538%** |
| Manually selected the same Git rule | 31.0462% | **68.9538%** |
| Remembered the correction to `paint → scan` | **96.4336%** | 3.5664% |

The manually selected and recalled votes matched at float32 precision. The
correction supplied both the revised requirement and its corresponding
expected execution. All three reports passed the ordinary provenance checks.

## Replay the requirement change in PR 57

`tests/check_pr57.py` uses the merged [PR 57](https://github.com/ariannamethod/jovovich/pull/57).
Receipt 1 quotes `docs/trace-evidence.md` line 26 at `a99d18b`, requiring arrays
for every metric. Receipt 2 supersedes it with `examples/release-trial/protocol.md`
lines 23–27 at `d7276be`, requiring the expected and observed text to reach AML.
That second commit changes only the written protocol, before the implementation.

Both recalled reviews use base `d7276be`, head `d34fce8` and the same complete
`src/trace_gate.c` diff. The test compiles the archived gate with its archived
AML and NoTorch dependencies and supplies the same string input to both versions.
A valid callback-array control must pass first. The text input uses distinct
expected and observed strings, and the probe checks both the native receipt and
AML's actual review context. Its observation reports rejection or verified delivery
of both values. The literal receipt and AML context are saved under the source
revision's SHA. `jovovich-replay probe` authenticates the Git sources and attaches
the measured execution. Applying receipt 2 to the earlier base must fail with
empty stdout.

Run from a full clone with the historical submodule objects available. Python
3.12+, a C compiler and the normal native build are required. Omitting the two
weight arguments runs the provenance and execution checks alone.

```sh
make -j2 all
python3 tests/check_pr57.py --work build/pr57 \
  --model /path/to/jovovich.gguf --tokenizer /path/to/tokenizer.gguf
```

The optional live run submits four ordinary reviews, each rule with and without
execution. It preserves the original A/B prompt and 0.50 decision boundary,
prints all four scores and requires the two measured reviews to select `CONCERN`
for receipt 1 and `CLEAN` for receipt 2. Exact inputs, AML receipts and raw native
answers remain in the chosen new work directory. The reviewed scope is
`src/trace_gate.c`.

Original OneJev, native F32, OpenBLAS with one thread gave these results.

| Receipt | Presentation | CONCERN | CLEAN | Expected |
| --- | --- | ---: | ---: | --- |
| 1 | Source only | 49.4838% | **50.5162%** | CONCERN |
| 1 | Verified text delivery | **50.2653%** | 49.7347% | CONCERN |
| 2 | Source only | **58.2110%** | 41.7890% | CLEAN |
| 2 | Verified text delivery | 38.7691% | **61.2309%** | CLEAN |

Both source-only answers are incorrect. The measured old-rule decision is close
to the boundary. The new-rule decision matches the observed delivery of both values.

The [initial driver](https://github.com/ariannamethod/jovovich/blob/7ad4dd69e8d49ea247f8ed8d4ce8b9b2130782a5/tests/check_pr57.py)
passed the literal inner AML comparison into the outer observation. Its witnessed
CONCERN probabilities were 54.0898% and 63.9754% for the old and new requirements,
respectively, leaving the new requirement misclassified. Source-only votes reproduced
exactly across both trials.
The current driver projects the tested delivery contract after checking the raw
values and AML context. The code diff, quotations, checkpoint, question and decision
boundary are identical between these trials.

## Rehearse a verified fact

A saved DOE generation can carry a receipt for the PR observation that was
rehearsed. Take the observation ID from `new_checks[].id` in a
[knowledge-cutoff comparison](batch-review.md). Register the completed spore
and check the bytes again before restoring it.

```sh
./build/jovovich-replay spore "$memory" "$repository" "$number" "$observation" "$spore" --record
./build/jovovich-replay spore "$memory" "$repository" "$number" "$observation" "$spore"
```

AML records the file’s SHA-256 alongside the observation in a separate
repository/PR checkpoint. Recording the same pair again is idempotent.
Different generations can cite the same observation. Verification reads
the file supplied on that invocation. NoTorch checks the host and native
expert tensors when opening the generation. For a restore from mutable storage,
copy the spore to a private path, verify that copy and open it with NoTorch.

`make check-fact-sleep MODEL=/path/to/jovovich.gguf` runs the original OneJev
with its manifest-matched `tokenizer.gguf`. Two Git repositories share PR 7
and the same original SHA. Only one changes its signal rule from blue to red.
AML rehearses each verified receipt, consolidates asynchronously and saves
the expert state. NoTorch runs a private dream capped at two tokens. Fresh processes
repeat the same questions with both A/B orders, first from the spore alone
and then with the current Git quotation. The output includes both option logits,
the SHA-256 of the AML checkpoint containing all 248,320 float32 logits, and
the selected color in each order. Each restart also compares the checkpoint bytes.

On the manifest-pinned original OneJev-0.8B (CPU F32, OpenBLAS), each of the
three dreams took two tokens. The table gives the selected color first with
blue as A, then with red as A.

| Final PR rule | Spore after sleep | Spore and Git quote | Git quote alone |
| --- | --- | --- | --- |
| `east#7`, corrected to red | red / blue | red / red | red / red |
| `west#7`, still blue | red / blue | blue / blue | blue / blue |

The spore-only probe picked B in both orders, as it did before rehearsal.
All six process restarts reproduced the full saved logits byte for byte.
The earlier east receipt still returned blue, and all fact and PR journal
bytes matched their respective pre-sleep snapshots.
