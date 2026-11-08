# Attach comparable execution traces to a review

A test harness can send paired callback traces or short program outputs from the base and head revisions
alongside a review. The native host forwards one observation about the head
when the two executions differ on the effect specified by the contract. An
unchanged effect leaves the entire model prompt byte-identical to a source-only
review. An observed repair qualifies even when the head passes its test.

Attach the optional `trace_evidence` object to the ordinary JSONL input before
running `build/jovovich`. The harness supplies independently measured callbacks
and the required result for each input. It runs the two revisions with the same
input and setup. The reviewer never executes repository code. This path applies
to structured test evidence. Existing prose and code in the supplied review
context are preserved literally.

| Field | Value |
| --- | --- |
| `schema` | `jovovich.paired-traces/1` |
| `review_id` | The enclosing review's `id` |
| `rule_sha256`, `change_sha256` | SHA-256 of the exact rule and change excerpts |
| `base_commit`, `head_commit` | Required for Git-packed inputs, from their `source` |
| `metric` | `sequence` for the ordered list of callbacks, `count` for occurrences of one callback, or `text` for a single-line output |
| `target` | Callback name for `count` |
| `runs` | Up to 64 distinct signed 32-bit integer modes. Each holds `mode`, `base`, `head` and `required` |

For the two callback metrics, `base` and `head` are arrays of up to 32 callback names.
Names are ASCII identifiers of up to 63 characters. For `sequence`, `required`
is another such array. For `count`, it is a nonnegative signed 32-bit integer.
For `text`, all three values are JSON strings of up to 256 printable ASCII bytes.
The host compares decoded bytes and quotes the strings in the AML observation.
Quotes, backslashes and angle brackets are escaped within the observation.
An empty string is a valid output.
The harness takes the expected value from the requirement oracle. On packed Git rows,
the two excerpt hashes are available as `source.rules_sha256` and
`source.diff_sha256`.

The host compares each pair after measuring its specified effect. For a
count of `emit`, the traces `[emit, log]` and `[notify, emit]` both give one,
so this run supplies no observation. If several modes differ, the smallest
integer mode wins. When all agree, `execution.trace_witness` records zero
differences and the model receives only the original review. Invalid bindings,
duplicate modes and malformed traces fail the review.

## Run the recorded Git repair

The [input](../examples/run-selection/git-input.jsonl) contains a real
single-file patch and the traces obtained by compiling each revision. At
mode 0 both invoked `scan` then `paint`. At mode 1 the base invoked `paint`
then `scan`, and the head invoked the required `scan` then `paint`. The host
selected mode 1. OneJev returned CLEAN with probability 0.690.

```sh
make build/jovovich build/jovovich-report
input=examples/run-selection/git-input.jsonl
./build/jovovich model.gguf tokenizer.gguf --json < "$input" > answers.jsonl
./build/jovovich-report "$input" answers.jsonl
```

The input digest covers the whole record including the supplied traces.
The output records the number of supplied and differing modes, the actual
prompt digest and, when selected, the mode and observation. The report
rebuilds this information independently from the supplied input and shows
the observation in Markdown. The gate also composes with the existing
`--canonical-boundaries` option. The [selection experiment](run-selection.md)
compares this policy with asking the model to pick the input ahead of execution.
