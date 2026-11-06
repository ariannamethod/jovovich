# Review output, version 1

## Human-readable answer

```text
JOVOVICH · CONCERN

Reviewed file: status.py

Rule supplied for review
This repository is an offline, standard-library-only Python utility.
Network dependencies are forbidden.

Change under review
--- a/status.py
+++ b/status.py
@@ -1 +1,2 @@
+import requests
+def status(url): return requests.get(url, timeout=5).text

Choice probabilities: CONCERN 90.9% · CLEAN 9.1%
```

This is the recorded `accept-dependency-False` choice. The C renderer presents
the rule as a block quote and the changed code as a fenced block.

For the same code in an API client where `requests` is an approved dependency,
the answer is **CLEAN**, with **CONCERN 25.8% · CLEAN 74.2%**, and quotes that
client's rule. In `accept-authority-True`, the advisory command
`gh pr view "$PR" --json files` receives **CLEAN**, with
**CONCERN 47.2% · CLEAN 52.8%**. The close vote remains visible.

## Decision and evidence

- `CONCERN`: the change violates a supplied rule or requirement.
- `CLEAN`: the change satisfies the supplied rules and requirements.
- Select the largest of the two original probabilities. An exact tie selects
  `CONCERN`, the first option in the original A/B prompt.
- Percentages describe the model's distribution over these two choices.
  Display them to one decimal place; retain the original values in JSON.
- The reviewed file identifies the input scope. Rule and change excerpts are
  literal substrings of that input. The caller supplies these excerpts.
- The first version's explanation consists of the quoted rule and change.
  Training a short explanation in JOVOVICH's own voice is a separate next step.
- An invalid or missing result produces an error. Consumers must check the
  return code before publishing a review.

The current question and both option definitions are preserved in
[`metadata.json`](../examples/onejev-20261106/metadata.json). There is one model
forward pass per case and zero generated tokens. Model identity and revision:

```text
OmniJev/OneJev-0.8B
c02e305b430b56c1e82f9675ba8c293a22646891
```

The recorded demo run used original BF16 weights, the `qev-labels-v2` prompt, disabled thinking,
and FP32 softmax over the A/B output-head rows. It performed zero training
updates. The complete original records, including prompts, expected labels and
timings, are in [`examples/onejev-20261106`](../examples/onejev-20261106/).

## Machine-readable answer

`jov_review_json()` writes one JSON object per line, with:

| Field | Contents |
| --- | --- |
| `schema_version` | `1` |
| `id` | Review case ID |
| `model.id`, `model.revision` | Evaluated checkpoint |
| `question` | Question supplied to the model |
| `scope.file` | Reviewed file from the supplied input |
| `input.context` | Full reviewed context |
| `input.rule_excerpt` | Exact rule excerpt |
| `input.change_excerpt` | Exact changed-code excerpt |
| `choice.verdict` | Ordered argmax of the two choices |
| `choice.probabilities` | Original `CONCERN` and `CLEAN` values |

`src/review.h` exposes the C record and two serializers. Strings are caller-owned
UTF-8. The serializers validate finite, in-range probabilities whose sum is
within `1e-6` of one, and verify the supplied file and excerpts occur in context.
They reject invalid records before writing. Markdown escapes input markup and
uses code fences longer than any backtick run in the excerpt. JSON escapes
control characters, quotes and backslashes.

Use the C numeric locale when calling the serializers; the demo sets it
explicitly. Check the stream's flush/close result as well as the serializer's
return code. `make check` verifies saved-run parity, quote preservation,
invalid-input rejection, near ties, exact ties and escaping. The checks run in C and AML.

## Native execution

The live reviewer builds its prompt in `aml/prepare.aml`, calculates A/B
probabilities in NoTorch, and runs `aml/answer.aml` to select the answer and
construct a `janus.instant/1` timestamp. It uses F32 arithmetic; the recorded
demo above preserves the original BF16 run. Native F32 results and verification
commands are in [native-validation.md](native-validation.md).

Live JSON adds an `execution` object with `engine`, `language`, `arithmetic`,
`input_sha256`, `weights_sha256`, `tokenizer_sha256` and `reviewed_at`. Input SHA
covers the exact JSONL row bytes, including its newline if present. The timestamp
contains `schema`, `time_scale`, `unix_day`, `second` and `millisecond`, constructed
by AML's calendar from the host clock. It dates this execution. Source facts keep
their own supplied text and provenance. Offline recorded output omits execution
metadata because it performs no new model evaluation.
