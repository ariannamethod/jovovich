# What happens when OneJev sees the boundary run?

On the 96 [PR 49 reviews](equivalent-boundaries.md), frozen OneJev classified
55 correctly from source alone. Adding the compiled return and the required
return at equality raised that to 86. Giving the same observation at the
integer immediately below the threshold scored 51. With the comparison
written in canonical form, the scores were 56, 96 and 64 respectively.

## Design

The [protocol](../examples/boundary-observations/protocol.json) was committed
at [bba6c42](https://github.com/ariannamethod/jovovich/commit/bba6c42a141ad4e35fa6a8910467da024683c74e)
before the experimental forwards. Twelve rules each have a compliant
implementation and an off-by-one mutation. Each function has four spellings.
Every intervention uses the same cases, decision rule and frozen weights.
The base is the primary system. The archived PR 49 paired readout provides
a second measurement on the same backbone.

For each original function, a compiled C driver executes the threshold and
its left neighbor. It obtains the required value from the rule oracle, and
compares the original and canonical functions on all 17 integers from −8
through 8 (1,632 comparisons). On equality, each mutation returns the wrong
value. At the neighbor both members of every pair satisfy the rule. AML
supplies exactly one sentence in either observation arm, for example
`Execution at value = 0. Required return = 0. Observed return = 1.`
All verdicts come from the model's ordinary A/B readout.

## Results

| Head and source view | Observation | Correct /96 | Both sides correct /48 | Same verdict in four spellings /24 | All eight correct /12 | False alarms | Misses |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Base, raw | None | 55 | 10 | 10 | 0 | 32 | 9 |
| Base, raw | Neighbor | 51 | 6 | 4 | 0 | 11 | 34 |
| Base, raw | Equality | 86 | 38 | 16 | 4 | 10 | 0 |
| Base, canonical | None | 56 | 12 | 24 | 3 | 24 | 16 |
| Base, canonical | Neighbor | 64 | 16 | 24 | 4 | 0 | 32 |
| Base, canonical | Equality | 96 | 48 | 24 | 12 | 0 | 0 |
| Paired, raw | None | 55 | 9 | 1 | 0 | 16 | 25 |
| Paired, raw | Neighbor | 54 | 7 | 5 | 0 | 9 | 33 |
| Paired, raw | Equality | 88 | 40 | 17 | 5 | 8 | 0 |
| Paired, canonical | None | 72 | 24 | 24 | 6 | 0 | 24 |
| Paired, canonical | Neighbor | 60 | 12 | 24 | 3 | 0 | 36 |
| Paired, canonical | Equality | 96 | 48 | 24 | 12 | 0 | 0 |

On raw code the equality observation fixed 31 of the base's previous
errors and preserved all 55 previous correct verdicts. Its mean CONCERN
probability moved from 0.578 to 0.405 for compliant code and from 0.615
to 0.865 for mutations. The neighbor observation moved the two means
to 0.437 and 0.467. It fixed 21 verdicts and spoiled 25.

For example, the rule for `equiv-140` requires `value < 0`. The reversed
implementation `0 > value` initially received 83.9% CONCERN. With canonical
code and the observed correct return of 0 at equality it received 33.1%
CONCERN (CLEAN). Its mutation `0 >= value` returned 1 on that same input
and received 84.3% CONCERN. At the neighbor −1, both versions correctly
returned 1. The canonical mutation then received 47.1% CONCERN (CLEAN).

For every evidence condition, the scorer checks that each spelling yields
the exact same canonical context and AML prompt as its direct representative.
Each canonical row therefore covers 24 distinct prompts presented in four
spellings. The scorer reuses the direct representative's actual prediction.
Eight independent canonical reviews through the normal JSON CLI reproduced
the mapped base probabilities at float32 precision. The
[per-case results](../examples/boundary-observations/results.json) include
both systems' probabilities and the raw and canonical prompt digests.
The [execution receipts](../examples/boundary-observations/receipts.jsonl)
tie the observed values to each original function.

## Using the canonicalizer in a review

Pass `--canonical-boundaries` to `build/jovovich` with Markdown or JSON output.
It also works with `--readout`. The C host recognizes a complete
`int f(int x)` function with a single return containing one of `<`, `<=`,
`>` or `>=`, one decimal integer and an optional outer `!(...)`.
It puts the parameter on the left and folds the negation. It accepts a unique
change excerpt inside a fenced C block, or a Git patch adding the entire
function as a new one-line file. Other changes pass through. For a recognized
Git patch the model view omits the blob index line, which depends on spelling.
The original diff, Git hashes, rule and input digest stay in the review.
JSON records the resulting prompt digest and recognized code in
`execution.boundary_view`. The Markdown report shows the comparison beside
the original change when they differ.

Four native Git reviews of the same new file used four different blob IDs
and all produced the same canonical prompt and probability. With only the
rule and code, the base gave the compliant function 64.0% CONCERN in all
four cases.

The experiment supplies observations from its closed, compiled corpus.
The review flag only changes how qualifying source is written for inference.
Base OneJev with the original input view remains the default.

## Reproduce

From the repository root, with the pinned OneJev files and the archived
paired adapter identified in the [PR 49 run](../examples/equivalent-boundaries/run.json):

```sh
make build/semantic-corpus build/jovovich build/jovovich-readout build/boundary-observations
OPENBLAS_NUM_THREADS=4 NT_ATTN_THREADS=4 sh tools/run_boundary_observations.sh \
  /path/to/model.gguf /path/to/tokenizer.gguf /path/to/paired.json /path/to/new-run
```

The recorded run reused the 96 unmodified PR 49 feature rows and evaluated
192 new observation prompts. The reproduction script evaluates all 288 raw
prompts and eight live canonical reviews. `make check` rebuilds the compiled
observations and regenerates the result table from the recorded scores.

The [callback transfer experiment](execution-traces.md) tests the same witness
idea on ordered effects and callback counts.
