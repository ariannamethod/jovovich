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

## Linux reference

Linux x86_64 on AMD EPYC 9V74, GCC 14.2, NoTorch with OpenBLAS
(`libcasadi-tp-openblas`). The first answer took **12.952 s**.
The next five took **5.857, 5.282, 4.929, 5.236 and 4.985 s**, for a
median of **5.236 s**. The [timing record](../examples/review-latency/linux-x86_64.json)
contains the original millisecond values and the reference answer digest.

## Apple Silicon measurements

On Neo (A18 Pro), two runs of the resident reviewer gave medians of **1.47 s**
and **1.50 s**. The first answer in each process took 17.4 s and 12.2 s.
An earlier run during concurrent machine activity gave a resident median
of 4.18 s. The [field record](../examples/review-latency/apple-silicon.json)
retains the reported precision, the five individual times from each repeat
and the separate 1,024-token throughput results.

| Host | Engine and backend | Timed work | Input tokens/s | Time |
| --- | --- | --- | ---: | ---: |
| Neo · A18 Pro | JOVOVICH / NoTorch CPU, 4 threads | Full resident `draw.c` review | 203–207 | 1,470 / 1,500 ms (two medians) |
| Neo · A18 Pro | llama.cpp CPU, 4 threads | `llama-bench pp305` | 74.7 | 4,085 ms |
| Neo · A18 Pro | llama.cpp Metal | `llama-bench pp305` | 865.7 | 352 ms |
| Mac mini · M4 Pro | llama.cpp CPU, 4 threads | `llama-bench pp305` | 1,126.1 | 271 ms |
| Mac mini · M4 Pro | llama.cpp Metal | `llama-bench pp305` | 3,583.5 | 85 ms |

The Neo CPU time ratio is **2.72–2.78× in favor of JOVOVICH** across the two
resident medians. JOVOVICH processes all 305 tokens from the real Git review,
reads the A/B logits and returns its JSON answer. Its pinned GGUF contains
321 BF16 tensors and NoTorch computes in F32. Fable ran the F16 OneJev GGUF
with `llama-bench -p 305 -n 0`. Upstream `test_prompt` supplies generated
token IDs and synchronizes the backend after prefill. The CPU and Metal
times in the table are Fable's reported equivalents for that workload.
[llama-bench implementation](https://github.com/ggml-org/llama.cpp/blob/12e9084dc1c88fe73bdd2886723b4b8b7d790be8/tools/llama-bench/llama-bench.cpp#L2168-L2198)

## Replay the actual 305 tokens

The [single review fixture](../examples/review-latency/draw-replay.jsonl)
contains the 1,200 prompt bytes, the ordered token IDs captured at the input
to NoTorch, and the two reference logits. Their slots are A = 32 (CONCERN)
and B = 33 (CLEAN). A second native run from the saved IDs reproduced logits
**10.7241526** and **11.5221119**, giving **68.9538% CLEAN**.
The prompt digest matches the trace witness in the archived Git answer.

The pinned NoTorch tools reproduce the token IDs and the two-logit result
from the JOVOVICH root.

```sh
make -C deps/notorch qwen35_tokenize qwen35_eval
fixture=examples/review-latency/draw-replay.jsonl
deps/notorch/qwen35_tokenize tokenizer.gguf < "$fixture" > draw-ids.tsv
OPENBLAS_NUM_THREADS=4 VECLIB_MAXIMUM_THREADS=4 NT_ATTN_THREADS=4 \
  deps/notorch/qwen35_eval model.gguf --chunk 32 < draw-ids.tsv > draw-eval.json
jq -e --slurpfile ref "$fixture" \
  '.id == $ref[0].id and .input_ids == $ref[0].input_ids and
   ((.probabilities[1] - 0.6895378232) | fabs) < 0.0002' draw-eval.json
```

With the F16 comparison GGUF, the following check compares the full
llama.cpp token array with the captured sequence. `jq -j` preserves the
trailing newlines in the prompt. The tokenizer recognizes the literal chat
markers and receives no additional BOS.

```sh
fixture=examples/review-latency/draw-replay.jsonl
jq -j '.prompt' "$fixture" > draw-prompt.txt
llama-tokenize -m OneJev-0.8B.f16.gguf --stdin --no-bos --ids \
  < draw-prompt.txt > llama-ids.json
jq -e --slurpfile ref "$fixture" '. == $ref[0].input_ids' llama-ids.json
```

For a direct engine comparison, feed the fixture's `input_ids` to both
engines. Start each trial with resident weights and an empty sequence cache.
Time from submitting the IDs to reading the final logits at slots 32 and 33
on the host. Record both logits and each elapsed time, the model file hash,
engine revision, backend and thread count. This measures the same operation
on both CPUs and also gives a separate Metal result. The end-to-end
`bench-review` timer above continues through JSON delivery.
