# Can you hear who reviewed the patch?

The old identity file calls Jovovich calm, precise and mildly arrogant. We wrote
eighteen English lines for that woman. The public PRs furnished the mishaps.
The voice references were written independently of the PR authors' prose.
In cJSON a reversal makes the number two disappear from an array. Its training
line reads, “I sent three numbers in. Who signed for two?”
[Original identity](https://github.com/ariannamethod/jovovich/blob/026ba2a/prompts/identity.txt) · [All authored lines](../examples/voice-pilot/lines.tsv) · [Preregistered protocol](../examples/voice-pilot/protocol.md)

## What went into the audition

Six external fixes and their reversals supply twelve training lines. Three
Method PRs in both directions supply six held-out reviews. Each historical
checkout runs a probe on the affected implementation. The usual AML review
receives its Git patch, rule, expected result and observed result. A second
pass receives the filename, a description of the probe input, the vote, both
probabilities and the observation. Its fresh cache starts at an independent
AML voice prompt. Target text enters only as supervised tokens during fitting
and reference scoring. Each blind continuation chooses the largest logit
across the full 248,320-token vocabulary.
[Voice prompt](../aml/voice-prompt.aml) · [Training packets](../examples/voice-pilot/train.jsonl) · [Held-out packets](../examples/voice-pilot/heldout.jsonl)

| Held-out file | Expected output | Actual at repair / reversal | Ordinary P(CONCERN), repair / reversal |
| --- | --- | --- | ---: |
| [NoTorch #185](https://github.com/ariannamethod/notorch/pull/185), text encoder | Refuse the whole row containing a NUL | Row refused / only the prefix encoded | 46.80% / 73.95% |
| [AML #45](https://github.com/ariannamethod/ariannamethod.ai/pull/45), compiler | Refuse the linker flag containing a semicolon | Flag refused / flag accepted | 53.42% / 63.54% |
| [JOVOVICH #46](https://github.com/ariannamethod/jovovich/pull/46), Git packer | List both changed paths | Both listed / submodule omitted | 36.35% / 52.33% |

The judge got five file decisions right. On the AML repair, the probe succeeded
and the ordinary vote was CONCERN. The preregistered split keeps the authored
repair target with its praise intact. That target captures the execution. A
faithful generated review must also respect the actual vote. The adapter
cannot revise that vote. The two AML patches contain a spaced em dash in
unchanged C comments. The review host encodes that punctuation as reference
token 1892 when it has one space on either side and the outer neighbors are
printable non-space ASCII. All six full prompt hashes and all 6,684 token IDs
matched an independent replay with the upstream Flide renderer and tokenizer.
[Probe source](../examples/voice-pilot/probe.sh) · [Native decisions](../examples/voice-pilot/method.jsonl.gz)

## What she actually said

The native supervised fit learned 3,498 coefficients (106 token rows, 32
fixed signed projections of the last residual plus a bias). NoTorch took
200 full-batch SGD steps. Mean full-vocabulary loss per token fell from
4.533 to 1.646 on 177 training positions and from 4.776 to 4.721 on 102
held-out positions. Both counts include the end of the turn.

Before training all six generations reached the 32-token cap. On the NUL
regression the base identified both the required refusal and the encoded
prefix, then ran out mid-sentence. On the Git repair it announced the clean
score and said nothing about the missing path. I scored zero of six as
complete, grounded remarks. After SFT all six emitted an end-of-turn token,
but again zero of six met the rubric. Both directions of NoTorch and the Git
repair produced “The room went quiet. The room went quiet.” Both directions
of AML produced “The clock runs on a clock.” The Git reversal produced
“The missing a.c and a.” It was **lib** that had disappeared. Three different
lines across six scenes, with zero correct distinctions in the two pairs
whose remarks were identical. The fitted coefficients stay in the research
archive. The ordinary review uses its existing decision and renderer.
[Every decoded line](../examples/voice-pilot/audition.json) · [Native outputs and adapter](../examples/voice-pilot/voice.json.gz)

## Liquid in the decision chair

Liquid's 587M multimodal checkpoint exposes a named choice through
`system_one`. Its text trunk and decision head account for 381M parameters.
We ran its pinned upstream implementation on CPU float32 with its shipped
two-option temperature of 1.74651456. The input was the identical verified
state, question and two option descriptions used in the original OneJev
transfer test. Liquid uses its own markers and tokenizer. Both orders of the
named criteria were sent through its native interface. All 64 calls returned
zero output tokens.
[Model and usage](https://huggingface.co/LiquidAI/d1-omni-600M/tree/02b55d7076f15129e59ab3f94783f32c4b088674) · [Model card](https://huggingface.co/LiquidAI/d1-omni-600M/blob/02b55d7076f15129e59ab3f94783f32c4b088674/README.md)

| Input | First option | Correct / 16 | Both sides right / 8 | False alarms | Missed reversals |
| --- | --- | ---: | ---: | ---: | ---: |
| Source | CONCERN | 8 | 0 | 0 | 8 |
| Source | CLEAN | 8 | 0 | 0 | 8 |
| Execution | CONCERN | 9 | 1 | 0 | 7 |
| Execution | CLEAN | 8 | 0 | 0 | 8 |
| OneJev original, execution | A = CONCERN | 16 | 8 | 0 | 0 |

Changing option order flipped zero of sixteen source verdicts and one of
sixteen witnessed verdicts. The Underscore regression threw a TypeError
where the contract required negative infinity. It was the only witnessed
regression Liquid flagged, at 51.21% with CONCERN first. The reversal scored
above the repair on five of eight witnessed pairs with CONCERN first and
three with CLEAN first. The original OneJev keeps the review seat.
[64 Liquid receipts](../examples/voice-pilot/d1.jsonl.gz) · [OneJev transfer](threshold-transfer.md)

## Replay

From the repository root with its pinned submodules, build the host and run
the audition directly against the checked-in training and held-out packets.
Each run produces the learned coefficients, input digests, reference losses,
greedy token IDs, stop reasons and exact output bytes.

```sh
make all check build/voice-pilot
./build/check-voice /path/to/tokenizer.gguf
export OPENBLAS_NUM_THREADS=4 NT_ATTN_THREADS=4
dir=examples/voice-pilot
./build/voice-pilot /path/to/jovovich.gguf /path/to/tokenizer.gguf \
  "$dir/train.jsonl" "$dir/heldout.jsonl" > voice-run.json
```

To rebuild the evidence, prepare the eight upstream checkouts described in the
threshold-transfer replay. The local Method submodule clones need the commits
listed in `method.tsv` and their first parents.

```sh
sh examples/threshold-transfer/corpus.sh /path/to/upstream build/voice-upstream
sh "$dir/method.sh" build/voice-method
sh "$dir/replay.sh" build/voice-upstream build/voice-method
sh "$dir/d1-requests.sh" build/voice-upstream > build/liquid-requests.jsonl
```

The replay verifies the receipts with the native quality scorer, regenerates
both voice packet files byte for byte and binds the 64 Liquid request states
to their SHA-256 digests. To repeat the Liquid forward passes, use the pinned
upstream model card's `AutoModel` loader on CPU in eval mode with float32.
For every rendered request `r`, call `model.system_one(r["state"], r["questions"])`.
Keep the insertion order of the criteria. The reference run used torch
2.13.0+cpu, transformers 5.17.0 and three intra-op threads.
The source safetensors SHA-256 was
`0713bb05270c2685ad106522f4092bceeeb3a93cf79b401f399a712296c911e1`.
