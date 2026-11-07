# How long does one review take?

This benchmark submits the recorded [`draw.c` repair](../examples/run-selection/git-input.jsonl)
to the ordinary JSON reviewer. Model, tokenizer, input and prompt are pinned
by the [recorded answer](../examples/run-selection/git-answer.jsonl).
The host selects mode 1 and the frozen base gives the repair 69.0% CLEAN.

## Reproduce on Neo

From a fresh checkout on Apple Silicon, build the CPU reviewer with Accelerate.
Use the two GGUF files produced by the [native conversion](../README.md#live-review).

```sh
git submodule update --init
make build/jovovich build/bench-review \
  BLAS_FLAGS='-DUSE_BLAS -DACCELERATE -DACCELERATE_NEW_LAPACK' \
  BLAS_LIBS='-framework Accelerate'
./build/bench-review /path/to/model.gguf /path/to/tokenizer.gguf > neo-latency.json
```

For a hardware comparison, record the chip and system version with
`sysctl -n machdep.cpu.brand_string` and `sw_vers -productVersion` alongside
the JSON. The same benchmark runs on Linux with the reviewer's usual
[OpenBLAS build](native-validation.md). The driver requests four attention
threads and four BLAS threads on both systems.

## What the times include

- **First answer** starts immediately before the child process is created and
  ends when its first complete JSON answer is read. It includes checking both
  GGUF digests, loading the weights and tokenizer, and reviewing the change.
  The OS file cache is left in its current state.
- **Resident answers** are five more serial requests to that same process.
  Each interval runs from sending the packed row to receiving a complete
  answer. Each review has a fresh model cache, builds its prompt in AML,
  tokenizes it and runs NoTorch prefill. The job generates zero tokens.
  The output contains the five measurements in order and their median.

Both intervals use a monotonic clock. Preparing the Git fixture and its two
executions happens before timing. After each interval the driver checks the
review ID, input and prompt digests, weight and tokenizer digests, selected
mode, verdict and both probabilities (absolute tolerance `2e-4`).
A receipt requires six matching answers and a successful reviewer exit.

## Recorded run

Linux x86_64 on AMD EPYC 9V74, GCC 14.2, NoTorch with OpenBLAS
(`libcasadi-tp-openblas`). The first answer took **12.952 s**.
The next five took **5.857, 5.282, 4.929, 5.236 and 4.985 s**, for a
median of **5.236 s**. The [timing record](../examples/review-latency/linux-x86_64.json)
contains the original millisecond values and the reference answer digest.
The Apple Silicon measurement is pending.
