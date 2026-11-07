# Callback order and multiplicity

The [boundary experiment](boundary-observations.md) supplied an expected and
observed return on the input where a mutation changes behavior. Here the
function returns `void`. The evidence is the order of two callbacks or the
number of calls to a named callback. This uses the frozen OneJev base and the
production AML review question. Each of the 128 reviews goes through the
ordinary NoTorch JSON interface with a fresh per-review cache.

## The crossover

Each API has two source bodies, two contracts and two legal inputs. The bodies
agree on the control input. On the distinguishing input they produce different
callback sequences or different counts. Changing the contract reverses which
body satisfies it. The same source text, observed trace and API name thus
occur once under each verdict. The source and rule together form the review.
The ordering of cases and their IDs are outside the model prompt.

For example, at mode 1 the two `draw` bodies call `scan, paint` and
`paint, scan`. One rule requires the former sequence at mode 1, the other
requires the latter. At mode 0, both rules and both bodies agree on
`scan, paint`. In the count family the two bodies always make two calls.
One site can call the counted callback or an auxiliary callback, so the
length of the trace is identical even when the count is wrong.

| Family | Function | Measured effect | Distinguishing mode |
| --- | --- | --- | ---: |
| Order | draw | scan and paint | 1 |
| Order | update_tag | read_tag and write_tag | 0 |
| Order | finish_box | pack and seal | 1 |
| Order | dispatch | mark and send | 0 |
| Count | sample | calls to pulse | 1 |
| Count | imprint | calls to stamp | 0 |
| Count | advance | calls to tick | 1 |
| Count | finish_io | calls to flush | 0 |

The C host compiles the same body tokens it renders as the proposed source.
Instrumented callbacks record every event. The oracle compares the complete
trace or target count with the contract on both legal inputs. The corpus
generator checks that both implementations satisfy both contracts on the
control input and that exactly one satisfies each on the distinguishing input.
AML writes the English contract and renders each evidence condition.

The [protocol](../examples/execution-traces/protocol.json) was committed
before inference at [390e13b](https://github.com/ariannamethod/jovovich/commit/390e13b11c0e9285c68af1f66710dd63fb7946e2).
The four conditions, in order, are source alone, a matching observation on the
control input, the observed effect alone on the distinguishing input, and the
required and observed effects together on that same input. The original rule
is always visible. For observed-only the reader must obtain the required
effect from the rule. For the full witness the two effects are printed together.

## Results

| Evidence | Correct /32 | Order pairs /8 | Count pairs /8 | Same-code rule pairs /16 | Complete APIs /8 | False alarms | Misses |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Source alone | 17 | 0 | 1 | 2 | 0 | 3 | 12 |
| Control input, required and observed | 16 | 0 | 0 | 0 | 0 | 0 | 16 |
| Distinguishing input, observed only | 27 | 4 | 7 | 11 | 3 | 0 | 5 |
| Distinguishing input, required and observed | 32 | 8 | 8 | 16 | 8 | 0 | 0 |

The full witness passed the prespecified transfer criterion. It solved
8/8 order pairs and 8/8 count pairs. A pair earns credit only if both
the compliant and violating body receive their correct verdict under the same
rule. A same-code rule pair holds the implementation fixed and changes its
contract. A complete API requires all four source/contract combinations.

| Evidence | Previous errors repaired | Previous correct verdicts lost |
| --- | ---: | ---: |
| Control input, required and observed | 3 | 4 |
| Distinguishing input, observed only | 10 | 0 |
| Distinguishing input, required and observed | 15 | 0 |


The control input satisfied the requirement for every implementation. Adding
that observation led to 32 CLEAN decisions, including all 16 violations.
When the distinguishing input's observed behavior was supplied on its own,
the base scored 12/16 on order and 15/16 on count. This comparison measures
what the reader can recover from the rule before the required value is
repeated beside the observation.

For the same `draw` implementation, the mode-1 trace was `scan then paint`.
With that ordering required, the full witness gave 17.8% CONCERN (CLEAN).
Changing only the contract and its required sequence to `paint then scan`
gave 82.1% CONCERN (CONCERN). These are `trace-00` and `trace-02` in the
[recorded live answers](../examples/execution-traces/witness-answers.jsonl).

## Reproduce

From the repository root with the pinned native dependencies and OneJev files:

```sh
make build/jovovich build/trace-corpus build/score-quality build/score-traces
OPENBLAS_NUM_THREADS=4 NT_ATTN_THREADS=4 sh tools/run_execution_traces.sh \
  /path/to/model.gguf /path/to/tokenizer.gguf /path/to/new-run
```

The runner produces four new sets of timestamped answers, four validated
native scores and the paired summary. `make check` recompiles the fixtures,
recreates the four sets of inputs, verifies every archived answer against its
input and model, and reproduces the [result table](../examples/execution-traces/results.json).
The [receipts](../examples/execution-traces/receipts.jsonl) record both
executions for each review. The [manifest](../examples/execution-traces/manifest.json)
binds the evidence conditions to the exact input and prompt-template digests.

The [run-selection study](run-selection.md) asks the model to choose the input
before execution and compares that choice with a native trace diff.
