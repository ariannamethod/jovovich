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
