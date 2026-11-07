# Equivalent boundary comparisons

The original [readout experiment](semantic-readout.md) found a large difference
between direct and negated comparisons. This follow-up trained two heads on the
same 128 examples. Across the new 96 decisions, the base and the paired-loss
head both scored 55. Each system missed at least one verdict in every group.

## Design

The [protocol](../examples/equivalent-boundaries/protocol.json) was committed
before fitting or scoring. Each boundary group specifies one of four integer
comparisons and one threshold. Its clean and defective functions differ at
equality. Each appears in four equivalent forms. For a strict upper bound
these are `x < n`, `!(x >= n)`, `n > x`, and `!(n <= x)`.

For training, 48 negated comparisons replaced the previous 48 if-return
examples. The 48 direct comparisons and 32 guard examples retained their
exact input bytes. Both new heads used the previous architecture and optimizer.
The BCE control learned from individual verdicts. The paired objective also
penalized a violation scoring below its compliant partner and discrepancies
between the margins of equivalent direct and negated functions. Each added
term had a coefficient of 0.25. The [run record](../examples/equivalent-boundaries/run.json)
identifies both archived heads.

The fresh thresholds were −7, 0 and 7. Each was absent from the preceding
boundary training and transfer sets. Reversed operands first appear in this
evaluation. The compiled oracle compared 3,392 outputs to their requirements.
Across the training and evaluation boundary groups, 2,040 further checks
compared equivalent implementations and 1,632 checked that a mutation
changed the output exactly at equality. The previous corpus and its
published results are reproducible with their original commands.

## Results

| System | Correct /96 | Both mutation verdicts correct /48 | Violation ranked higher /48 | Same verdict in all four spellings /24 | All eight correct /12 |
| --- | ---: | ---: | ---: | ---: | ---: |
| OneJev | 55 | 10 | 31 | 10 | 0 |
| PR 48 head | 55 | 7 | 29 | 12 | 0 |
| New BCE head | 51 | 6 | 33 | 1 | 0 |
| New paired head | 55 | 9 | 33 | 1 | 0 |

Across the 24 clean or defective functions, the direct and negated forms
received the same verdict on 17 for the base, 12 for PR 48, 14 for BCE and
18 for the paired head. Both of these verdicts were correct on 11, 9, 10
and 13 functions respectively. Changing from direct to reversed operands
gave agreement on 14, 13, 5 and 6 functions respectively.

| System | Direct /24 | Negated /24 | Reversed /24 | Negated reversed /24 | Previous semantic /64 | Earlier reviews /38 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| OneJev | 14 | 15 | 12 | 14 | 34 | 30 |
| PR 48 head | 18 | 12 | 13 | 12 | 34 | 27 |
| New BCE head | 17 | 13 | 12 | 9 | 37 | 28 |
| New paired head | 18 | 14 | 12 | 11 | 38 | 27 |

The paired head marked all 24 direct reversed-operand examples CONCERN,
including the 12 correct functions. For the clean `value < 0` requirement,
its CONCERN probability was 0.320 for `value < 0`, 0.293 for `!(value >= 0)`,
0.764 for `0 > value` and 0.520 for `!(0 <= value)`. The
[fresh score](../examples/equivalent-boundaries/fresh-score.json) contains
every input ID and all four systems' probabilities.

Training accuracy was 74/128 for the base, 88/128 for BCE and 89/128 for
paired training. The paired head missed three previously correct concerns
on the earlier review suite. It failed the promotion criteria. Both heads
can be selected explicitly with the existing `--readout` option.

## Reproduce

From the repository root, with the native dependencies and a completed
original run from `tools/run_readout.sh`:

```sh
make build/semantic-corpus build/jovovich build/jovovich-readout
OPENBLAS_NUM_THREADS=4 NT_ATTN_THREADS=4 sh tools/run_equivalent_boundaries.sh \
  /path/to/model.gguf /path/to/tokenizer.gguf /path/to/previous-run /path/to/new-run
```

The recorded run reused 80 training feature rows keyed by exact input SHA-256
and computed the other 48 afresh. The runner recomputes all training rows.
For an independent check, all eight live predictions in the first evaluation
group matched the paired head's cached probabilities at F32 precision. A
separate F64 implementation reproduced both fitted parameter vectors with a
maximum absolute discrepancy below 2.1e−7.
