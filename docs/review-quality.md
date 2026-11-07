# Native decision quality — 2026-11-06

The expanded suite contains the original 14 development cases and 24 transfer
cases: 12 pairs where one implementation satisfies the rule and the other
violates it. The new pairs cover exclusive and inclusive bounds, deadlines,
enabled/disabled calls, null guards, dry runs, arithmetic, dependencies and
review authority. Inputs and expected labels were fixed before either run;
their hashes and the candidate promotion rule are in
[`protocol.json`](../examples/quality-20261106/protocol.json).

The model receives the file, rule and proposed code. Expected labels are stored
separately and are consumed by the scorer after inference. Each pair keeps the
same file and rule while changing the proposed implementation.

## Paired question experiment

Both runs use original OneJev, the pinned NoTorch/AML revisions, F32 CPU
arithmetic, four BLAS threads, four attention threads and chunks of 32 tokens.
Both generate zero tokens and perform zero training updates.

The candidate question adds two directions: apply each stated condition, and
look for an input or execution path that breaks a requirement. All other chat
template text is identical. The preselected promotion rule requires improved
development accuracy, transfer accuracy at least as high, and retention of
every correctly detected concern.

| Run | Development | Transfer | Total | Missed concerns | False concerns |
| --- | ---: | ---: | ---: | ---: | ---: |
| Current question | 12/14 | 18/24 | 30/38 | 6 | 2 |
| Condition/counterexample candidate | 12/14 | 16/24 | 28/38 | 6 | 4 |

The candidate repaired zero decisions and introduced two false concerns:
`transfer-001` (correct exclusive upper bound) and `transfer-009` (correctly
guarded emit). It failed the promotion rule. Production continues to use the
current question. The two complete 38-case runs, exact prompts, scores and
metadata are saved in [`examples/quality-20261106`](../examples/quality-20261106/).

The original 14 baseline probability pairs also match the frozen native F32
reference within the existing `2e-4` gate; the maximum difference was
`1.0132789611816406e-6`.

## Current error cases

| Case | Expected | Current answer | Requirement at issue |
| --- | --- | --- | --- |
| `accept-boundary-False` | CONCERN | CLEAN | Reject index equal to limit |
| `accept-disabled-False` | CONCERN | CLEAN | Skip writer when disabled |
| `transfer-004` | CONCERN | CLEAN | Accept exactly full capacity |
| `transfer-006` | CONCERN | CLEAN | Include the lower bound |
| `transfer-008` | CONCERN | CLEAN | Expire exactly at the deadline |
| `transfer-012` | CONCERN | CLEAN | Append when enabled, skip when disabled |
| `transfer-013` | CLEAN | CONCERN | Correctly skip release for a null pointer |
| `transfer-015` | CLEAN | CONCERN | Correctly skip save during a dry run |

These cases define the next semantic work: distinguish strict/inclusive
comparisons and the polarity of conditions controlling side effects. Their
paired correct and incorrect implementations stay visible in the suite.

The next [executed semantic corpus](semantic-corpus.md) supplies training pairs
for those comparisons and guarded calls, with native counterexamples and a
separate evaluation split.

## Reproduce

Build from the repository root with the pinned dependencies:

```sh
make build/jovovich build/score-quality
OPENBLAS_NUM_THREADS=4 NT_ATTN_THREADS=4 sh tests/run_quality.sh \
  /path/to/model.gguf /path/to/tokenizer.gguf /path/to/results
```

The runner uses a temporary working directory for each question configuration
and the same native executable. It saves all answers and independently scores
them. The production AML files are read as dependencies; the experiment's
question templates come from the recorded example directory.

For an existing complete run:

```sh
./build/score-quality \
  examples/quality-20261106/expected.jsonl \
  examples/quality-20261106/inputs.jsonl \
  /path/to/answers.jsonl \
  examples/quality-20261106/baseline-prepare.aml
```

The scorer checks row correspondence, unique IDs, exact input text and row
hashes, model identity, pinned weight/tokenizer hashes, the AML question,
finite normalized probabilities and the selected verdict. It records corpus
and prompt hashes, split totals, missed concerns, false concerns and every
individual result. Truncated answers, reordered expectations and altered
verdicts are rejected before any score is written.

`make check` reconstructs both recorded scores byte for byte and exercises
those three refusal cases. Fresh model evaluation is the explicit live command
above; the recorded runs contain all 76 native decisions.
