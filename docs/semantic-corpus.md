# Executed semantic training pairs

The first corpus targets the boundary and guarded-call errors measured in
[the 38-case review suite](review-quality.md). It contains **128 training rows**
and **64 evaluation rows**, balanced between CLEAN and CONCERN in each split.
Every pair shares its file and requirement and changes only the implementation.

`aml/corpus.aml` writes the English requirement and context and selects the
supervised answer from the native mismatch count. `aml/prepare.aml` supplies
the production prompt. C enumerates candidate functions, compiles their exact
bodies and compares their behavior with a separate reference calculation.

## Ground truth from executed code

The generated translation unit contains every displayed function. Preprocessor
macros give each function a unique symbol for compilation; the bodies are
unchanged. Bounds are tested at every integer from **-8 through 8**. Guarded
calls are tested for all **four combinations** of the two Boolean flags.

The result is **2,432 native observations** across 192 functions. A function
receives CLEAN when every result matches its stated requirement. A mismatch
produces CONCERN and retains its first counterexample, including input values,
expected result and actual result. For guarded calls the measured result is
the number of calls to the instrumented `emit()` function.

| Example | Requirement | Code | Label and evidence |
| --- | --- | --- | --- |
| `semantic-000` | Value must be below -5 | `return value < -5;` | CLEAN, all 17 inputs match |
| `semantic-001` | Value must be below -5 | `return value <= -5;` | CONCERN: -5 returns 1, expected 0 |
| `semantic-025` | Value may equal -5 | `return value < -5;` | CONCERN: -5 returns 0, expected 1 |

The first and third examples have **identical code and opposite labels** because
the requirements differ. Across the corpus there are 64 such same-code,
different-contract pairs. The rule is therefore an essential part of the input.
Twelve representative records are in
[`samples.jsonl`](../examples/semantic-20261107/samples.jsonl).

## Split construction

| Family | Training forms | Evaluation forms |
| --- | --- | --- |
| Bounds | Direct comparison; explicit if/return | Negated complementary comparison |
| Calls | Direct if; if/else; early return; return after emit | Local allowed/blocked variables; one-iteration for/while |

Bounds also use distinct thresholds between splits. Both members of a pair
stay in the same split. Template sets are disjoint within each family; exact
code strings never cross splits, and every context is unique. Neither code
nor context exactly duplicates a row in the existing 38-case suite.

The corpus covers strict and inclusive comparisons in both directions,
enabled and disabled conditions, conjunction and disjunction. The existing
38-case suite remains available as a separate evaluation set.

## Build and inspect

Run from the repository root with the pinned dependencies:

```sh
make build/semantic-corpus build/check-corpus
sh tools/build_corpus.sh build/semantic-v1
./build/check-corpus build/semantic-v1
```

The output path must be new. The shell runner compiles generated trusted C
snippets with `${CC:-cc}`, executes them, validates all receipts, and exports
the corpus. It moves the temporary output into place only after success and
removes the temporary executable before publication. Build, generation,
verification and export use C, AML and a POSIX shell.

| Output | Purpose |
| --- | --- |
| `train.jsonl` | Native input fields plus prompt, completion, token ID and pair ID |
| `eval-inputs.jsonl` | The existing live review input format, without target labels |
| `eval-expected.jsonl` | Separate expected decisions for `score-quality` |
| `audit.jsonl` | Split, template, hashes, domain coverage and counterexamples |
| `oracle.c`, `proofs.jsonl` | Exact compiled source and native observations per case |
| `manifest.json` | Counts and SHA-256 hashes of every exported component |

[`manifest.json`](../examples/semantic-20261107/manifest.json) freezes this
version. `make check` rebuilds it and requires the manifest to match byte for
byte. The generated files can be recreated from this commit.

## Training contract

Use only `prompt` as the model input and `completion` as the supervised target.
The completion is **A / token 32** for CONCERN or **B / token 33** for CLEAN.
Train the next-token choice with loss on that one completion token. Prompts
already end after the closed thinking section, exactly as in native inference.
IDs, labels, oracle receipts and counterexamples belong to corpus metadata and
are excluded from the prompt. Shuffle training rows; evaluation files remain
reserved for evaluation.

The [readout experiment](semantic-readout.md) uses this corpus to train and
evaluate the one-token decision on the pinned OneJev text backbone.

## Failure gates

Tests reject truncated receipts, incomplete domain counts and changed code
hashes. Receipt validation checks the expected mismatch count and the first
failing input against the mutation used to generate each pair. Swapping the
observations between the two functions fails before export. Two compiled
mutations also fail: changing a valid strict comparison
to an inclusive one, and changing the reference comparison itself. The first
breaks pair consistency; the second fails counterexample validation. An
existing output directory is refused and remains intact. All earlier native
review, Git, batch and quality-record checks run alongside these gates.
