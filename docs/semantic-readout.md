# Training the JOVOVICH A/B readout

The adapter trains 1,024 weights and one intercept on the executed semantic
corpus. The pinned OneJev text backbone supplies the last prompt token's
residual after decoder block 24, before the final normalization. The AML
prompt ends at the same closed thinking section used for ordinary reviews.

The host L2-normalizes that residual. The trainer centers it on the 128
training vectors and divides by their root-mean-square distance from the
training mean. On that input, a NoTorch linear projection adds a learned
correction to the original A-minus-B token margin. The two-way softmax
supplies CONCERN and CLEAN probabilities. Zero weights recover the base
choice. The center and scale are frozen along with the fitted projection.

The [protocol](../examples/readout-20261107/protocol.json) fixes the optimizer
and promotion criteria. Each full-batch SGD step uses all 128 training rows,
with the binary cross entropy of the one supervised token and L2 weight
regularization. The intercept receives no L2 penalty. The trainer accepts the
pinned training file and verifies each feature's input, model and tokenizer
hash. Feature extraction checks each training prompt against the live AML
output before passing it to the model.

## Measured decisions

| Suite | OneJev | Trained readout |
| --- | ---: | ---: |
| Training | 73/128 | 90/128 |
| Semantic transfer | 34/64 | 34/64 |
| Earlier review suite | 30/38 | 27/38 |

Training cross entropy fell from 0.684391 to 0.562441. On semantic transfer,
boundary checks went from 17/32 to 16/32 and guard checks went from 17/32 to
18/32. The adapter caught all 32 violations and flagged 30 of 32 correct
implementations. Only two of the 32 matched pairs received both correct
verdicts, compared with three for OneJev.

In the earlier suite, the adapter caught the index-equals-limit and
deadline-equality violations. It also flagged the correct index check, and
changed one correctly detected injected-instruction violation to CLEAN. Overall
the earlier suite went from six missed violations and two false alarms to five
missed violations and six false alarms. The fitted checkpoint failed the
promotion criteria and is available by explicit selection.

The [semantic score](../examples/readout-20261107/transfer-score.json)
and [earlier-suite score](../examples/readout-20261107/legacy-score.json)
contain the paired decisions. The [run record](../examples/readout-20261107/run.json)
identifies the checkpoint and the independent live checks.

## Reproduce

Build with the [native dependencies](native-validation.md). For a new output
directory, run from the repository root.

```sh
make build/jovovich build/jovovich-readout build/semantic-corpus
OPENBLAS_NUM_THREADS=4 NT_ATTN_THREADS=4 sh tools/run_readout.sh \
  /path/to/model.gguf /path/to/tokenizer.gguf /path/to/new-run
```

The runner reconstructs the corpus, fits the head, then scores both evaluation
suites. A single native backbone pass per input supplies the same logits and
residual to both decisions. The score files retain the ID, family, expected
verdict, two predicted verdicts and both CONCERN probabilities for every case.
The binary's `--features` output includes the SHA-256 of the exact input line
including its newline. Keep the exported adapter and feature files with the
experiment.

To run the checkpoint on a new review, use the ordinary live host.

```sh
./build/jovovich model.gguf tokenizer.gguf --json --readout adapter.json < reviews.jsonl
```

AML selects the verdict and supplies the JANUS timestamp. The JSON execution record
includes the adapter's SHA-256. Omit `--json` for Markdown. Omitting
`--readout` selects the original OneJev output.

## Paired method checks

Pairs are ordered as compliant implementation, then violation under the same
requirement. The transfer corpus contains 32 pairs. The matrix records each
pair's base decisions by row and its adapted decisions by column. “Correct”
means CLEAN/CONCERN and “reversed” means CONCERN/CLEAN.

| Base → adapted | Both CLEAN | Correct | Reversed | Both CONCERN |
| --- | ---: | ---: | ---: | ---: |
| Both CLEAN | 0 | 0 | 0 | 0 |
| Correct | 0 | 0 | 0 | 3 |
| Reversed | 0 | 0 | 0 | 1 |
| Both CONCERN | 0 | 2 | 0 | 26 |

The [32 individual pairs](../examples/readout-20261107/pair-flips.md) include
each verdict transition and its probability gap.

The violation received a higher CONCERN score than its compliant partner
in 20/32 base pairs and 25/32 adapted pairs. Guard ranking rose from 9/16
to 16/16. Boundary ranking fell from 11/16 to 9/16. There were zero ranking
ties. An additive constant preserves this ordering.

A control fitting only the intercept on the 128 training rows learned
+0.05533 and scored 73/128 on training, 33/64 on transfer and 29/38 on the
earlier suite. On transfer boundaries, the full head raised the mean CONCERN
margin by 1.307 on clean code and 1.348 on violations. For guards those
shifts were 0.027 and 0.267. The two families therefore contribute differently
to the aggregate accuracy.

Swapping the letters on all 64 transfer prompts gave the base model 34/64
after mapping the letters back to their meanings. It kept the same semantic
verdict on 60/64 inputs and the same letter on 4/64. Averaging the two
semantically aligned margins yielded 35/64. This control evaluates OneJev
with frozen weights and both orders of the same choices.

Run the controls on the directory produced above.

```sh
sh tools/check_readout_method.sh model.gguf tokenizer.gguf /path/to/new-run
sh tools/check_boundary_form.sh model.gguf tokenizer.gguf /path/to/new-run /path/to/new-control
```

The [diagnostics](../examples/readout-20261107/diagnostics.json) include all
transition matrices, family counts and the scalar control.

### Equivalent boundary expressions

The boundary control kept the same 32 requirements, thresholds and labels.
It rewrote the held-out negated comparison as a direct comparison. For
example, `!(value >= limit)` became `value < limit`. Compiled functions
produced identical outputs in all 544 original/rewrite comparisons over
integers from −8 through 8. The unchanged training file and evaluation labels
were also checked byte for byte. This is a post-training sensitivity test.

| Same 32 cases | Base accuracy | Readout accuracy | Base ranks violation higher | Readout ranks violation higher |
| --- | ---: | ---: | ---: | ---: |
| Negated comparisons | 17/32 | 16/32 | 11/16 | 9/16 |
| Equivalent direct comparisons | 20/32 | 23/32 | 13/16 | 16/16 |

With negation the readout returned CONCERN on all 32 cases. With the direct
form it returned CONCERN on 23 cases and placed both verdicts correctly in
7/16 pairs. The direct form occurs in training with different thresholds.
The [direct-form scores](../examples/readout-20261107/boundary-direct-score.json)
preserve both decisions for every rewrite.
