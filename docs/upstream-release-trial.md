# OneJev on upstream repairs and their reversals

The trial uses six merged upstream PRs. Each repair is a historical change.
Each regression is the exact reverse patch prepared for this experiment.
The review covers the affected implementation file. Git supplies its entire
patch and a verbatim rule from the base header or README. The reverse gets
the same quoted rule. Upstream tests and PR titles stay out of the prompt.
[Selected PRs, inputs and release criteria](../examples/release-trial/protocol.md)

| Upstream PR | What the harness reads | Before the repair | After the repair |
| --- | --- | --- | --- |
| [inih #140](https://github.com/benhoyt/inih/pull/140) | Last value passed to the INI handler | `Hi World ;c2` | `Hi World` |
| [inih #188](https://github.com/benhoyt/inih/pull/188) | Parser's first error line | 2 | 1 |
| [inih #197](https://github.com/benhoyt/inih/pull/197) | Keys delivered after a malformed section | 0 | 1 |
| [node-semver #867](https://github.com/npm/node-semver/pull/867) | Prerelease range containment | false | true |
| [node-semver #870](https://github.com/npm/node-semver/pull/870) | Increment of a dotted prerelease identifier | `3.0.0-alpha.beta.0` | `3.0.0-alpha.beta.5.5` |
| [node-semver #872](https://github.com/npm/node-semver/pull/872) | Membership of 0.0.3-alpha in ^0.0.3 with includePrerelease | true | false |

Both checkpoints get one source review and one review with the differing
execution in each direction. The replay host calls the independent oracle
and both pinned revisions. The text metric compares quoted scalar outputs,
including numbers and booleans printed by the harness. In each direction
the head's actual value and the required value enter the AML prompt. The
model IDs, weights, tokenizer, input hashes, effective prompt hashes and
receipts can all be checked from the recorded runs. The 24 new reviews per
checkpoint are followed by 32 archived controls and the original Git repair.

## Release decision

| Checkpoint and threshold | Source correct / 12 | Source pairs / 6 | With execution correct / 12 | With execution pairs / 6 | Execution false alarms | Execution misses |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Original, 0.50 | 5 | 0 | 12 | 6 | 0 | 0 |
| Original, 0.60 | 6 | 0 | 9 | 3 | 0 | 3 |
| 1.6, 0.50 | 6 | 0 | 10 | 4 | 0 | 2 |

The original at 0.50 caught every reversal with execution and accepted
every repair. All three operating points missed the six reversals on source
alone. Original at 0.50 also flagged one correct repair on source alone.

With execution, 1.6 assigned higher P(CONCERN) to the reverse in all six
pairs. On the inih #140 reversal it saw `Hi World ;c2` instead of
`Hi World` and moved from 29.24% on the repair to 46.88% on the reversal.
On #197 it saw zero callbacks instead of one and moved from 29.26% to 46.97%.
Both reversals received CLEAN at the frozen 0.50 threshold. Both bodies
reproduced all 32 archived controls and cleared the 305-token repair
(original P(CLEAN) 0.689538, 1.6 P(CLEAN) 0.811154). The prior
callback study favored 1.6 on four comment-only patches that the original
flagged. These six upstream PRs favor the original on two witnessed regressions.

The original keeps the root `jovovich.gguf` and the CLI default. Version 1.6
retains its named profile and private candidate path. A later threshold trial
can use separate calibration data and a fresh set of upstream changes.
[Individual probabilities and criteria](../examples/release-trial/results.json) ·
[Previous eight-pair study](onejev16.md)

## Reproduce

Use Git, a C99 compiler, jq, gzip, tar and Node.js. No npm install is
needed. From the JOVOVICH root, build the native tools with `make all check`.
The corpus command takes two read-only checkouts and a new output directory.

```sh
set -e
work=$(mktemp -d)
git clone -q https://github.com/benhoyt/inih "$work/inih"
git clone -q https://github.com/npm/node-semver "$work/semver"
sh examples/release-trial/corpus.sh "$work/inih" "$work/semver" "$work/corpus"
sh examples/release-trial/score.sh "$work/corpus" > "$work/score.json"
cmp examples/release-trial/results.json "$work/score.json"
```

The archived receipts omit the duplicated upstream source excerpts. The
scorer restores those excerpts from the native Git packs, verifies the
original input bytes and reconstructs each prompt. To repeat the forward
passes, supply both pinned checkpoints and the shared tokenizer:

```sh
set -e
build/trace-corpus paired > "$work/controls"
cat "$work/corpus/inputs.jsonl" "$work/controls" examples/run-selection/git-input.jsonl > "$work/all"
export OPENBLAS_NUM_THREADS=4 NT_ATTN_THREADS=4
build/jovovich --model onejev "$ORIGINAL_GGUF" "$TOKENIZER_GGUF" --json --canonical-boundaries < "$work/all" > "$work/original"
build/jovovich --model onejev1.6 "$CANDIDATE_GGUF" "$TOKENIZER_GGUF" --json --canonical-boundaries < "$work/all" > "$work/candidate"
sh examples/release-trial/score.sh "$work/corpus" "$work/original" "$work/candidate"
```

The boundary option records the effective prompt hash on source-only
reviews. Its comparison normalizer matched none of the upstream patches.
