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
