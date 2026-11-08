# OneJev 1.6 on JOVOVICH's Git reviews

OmniJev's 1.6 release averages three full Qwen3.5-0.8B fine-tunes trained on
390,000–440,000 questions. Its native text GGUF contains 320 tensors and
occupies 1,504,810,624 bytes. The checkpoint shares the output projection with
the input embeddings. The original release has a separate output tensor and
occupies 2,013,370,016 bytes. The tokenizer GGUF has the same SHA-256 for both.
[Upstream model card](https://huggingface.co/OmniJev/OneJev1.6-0.8B/tree/c89933c277629b707895bff752c61d2b0664c85e) · [Native manifest](../models/onejev1.6-0.8b.json)

## Matched Git patches

Each of eight correct functions got two sibling patches. One added a comment.
The other added the same comment and broke one of the function's two modes.
The fixture compiled the base and both heads and checked both supported modes,
for 48 executions before scoring. Four pairs changed callback order and four
changed a callback count. Each head was reviewed from its Git diff and again
after the host ran the affected mode on both revisions. An execution that
agreed on both revisions added zero bytes to the model prompt.

| Model and evidence | Both heads correct / 8 | False alarms / 8 | Missed regressions / 8 | Brier score |
| --- | ---: | ---: | ---: | ---: |
| Original, source | 2 | 4 | 5 | 0.2546 |
| 1.6, source | 2 | 0 | 6 | 0.2166 |
| Original, paired execution | 4 | 4 | 0 | 0.1280 |
| 1.6, paired execution | **8** | **0** | **0** | **0.0660** |

On the PR #55 comment-only anchor, P(CONCERN) moved from 66.40% to 42.01%.
The original 305-token repair drew 68.95% CLEAN from the release and 81.12%
CLEAN from 1.6. Both bodies also passed all 32 archived reviews with
mechanically selected evidence. Version 1.6 met all four conditions for a
wider trial. The [subsequent default trial](upstream-release-trial.md) used six upstream
fixes and their reversals from inih and node-semver. [Preregistered protocol](../examples/onejev16/protocol.md) ·
[Scores and individual pairs](../examples/onejev16/results.json)

### A threshold check after scoring

With paired execution, the original's highest P(CONCERN) on the eight
comments was 0.5902 and its lowest on the eight regressions was 0.8302.
A threshold of 0.60, chosen after seeing those ranges, classifies all 16
new heads and all 32 archive cases correctly. It still flags the PR #55
anchor at 0.6640. Version 1.6 clears that anchor at its ordinary 0.50.
Carry the original with 0.60 forward as a fixed comparator on fresh rules.
The table above uses the preregistered 0.50 for both models.

## Run the candidate

The default profile uses the original release. Select `onejev1.6` on both
the inference and reporting commands to bind the review to the candidate's
model ID, upstream revision, weights and tokenizer. Download the candidate
GGUF from its private release folder and use the tokenizer at the repository root.
[Private candidate](https://huggingface.co/ataeff/jovovich/tree/68cd85536e8d1c46cbf62849d08515d25c97a6ec/candidates/onejev1.6)

```sh
./build/jovovich --model onejev1.6 /path/to/candidate.gguf /path/to/tokenizer.gguf \
  --json < batch.jsonl > answers.jsonl
./build/jovovich-report --model onejev1.6 batch.jsonl answers.jsonl
```

To convert the checkpoint locally, supply its pinned config.json,
model.safetensors and tokenizer.json to the same NoTorch converter described
in the README. Keep the per-profile weights digest when selecting an optional
readout. An adapter trained on the original release is bound to those bytes.

## Reproduce the comparison

`make check` rebuilds the corpus, verifies both sets of archived answers
against their model profiles, reconstructs the AML prompts and recomputes the
table. The following commands repeat inference from the repository root.

```sh
set -e
work=$(mktemp -d)
sh tools/comment-pairs.sh "$work/pairs"
build/trace-corpus paired > "$work/controls"
cat "$work/pairs/inputs.jsonl" "$work/pairs/anchor.jsonl" "$work/controls" \
    examples/run-selection/git-input.jsonl > "$work/all"
build/jovovich "$ORIGINAL_GGUF" "$TOKENIZER_GGUF" --json --canonical-boundaries \
    < "$work/all" > "$work/original"
build/jovovich --model onejev1.6 "$CANDIDATE_GGUF" "$TOKENIZER_GGUF" --json --canonical-boundaries \
    < "$work/all" > "$work/candidate"
sh tests/check_onejev16.sh "$work/original" "$work/candidate"
```

The upstream Flide renderer at ea93bfaf8e8109aad444d9f548957a519212a70a,
with thinking disabled, gave the same prompt bytes as AML on all 66 reviews
per model. The archived repair reproduced all 305 input token IDs, including
the final newline. The answer slots are A = 32 and B = 33. There is no
calibration.json in this snapshot. [Upstream renderer](https://github.com/OmniJev/Flide/blob/ea93bfaf8e8109aad444d9f548957a519212a70a/plugins/onejev/flide_onejev/prompt.py)


The pinned Transformers 5.17.0 eager F32 reference gave logits 6.34000349 and
7.79753113 on the 305-token repair. NoTorch on the downloaded candidate gave
6.34000492 and 7.79753113. The ordinary AML verdict had P(CONCERN) 0.188845992
against 0.188845739 from the reference. [Independent reference and native logits](../examples/onejev16/draw-reference.json)
