# Can OneJev take its decision threshold to a new project?

Each of eight upstream fixes went through review in both directions. Git
supplied the implementation diff and identical rule text for each pair. The
host ran a shared input and a distinguishing input against both revisions.
Each checkpoint completed 48 reviews across three equal groups. It saw
each change with source alone, after the shared run and after the
distinguishing run. The historical PR is the
repair in each pair. The regression is its exact reverse patch.
[Preregistered protocol and roster](../examples/threshold-transfer/protocol.md)

The decision thresholds came from the six previously published pairs in
inih and node-semver. On each checkpoint we took the midpoint between the
highest repair and lowest regression P(CONCERN). Both cutoffs were fixed
in Git before the first forward pass on these five repositories. The fitted
decision uses AML's inclusive float32 comparison only when the host admits
a differing text output. Every file retains its ordinary model vote and both
raw probabilities. [Calibration set](upstream-release-trial.md)

## Held-out results

One pair is correct when JOVOVICH clears the repair and flags its reversal.
At the shipped threshold the original got every witnessed pair right.
Version 1.6 gained two pairs at its fitted threshold and still missed one
reversal that the original caught. The original keeps the release name
`jovovich.gguf`. Version 1.6 keeps its named candidate profile. Its 39.07%
point is available for offline evaluation through `build/score-quality`.
[All 96 receipts and the per-case scores](../examples/threshold-transfer/)

| Body and decision | With execution, correct / 16 | Both right / 8 | False alarms on repairs | Missed reversals |
| --- | ---: | ---: | ---: | ---: |
| Original, ordinary 50% | 16 | 8 | 0 | 0 |
| Original, fitted 48.64% | 16 | 8 | 0 | 0 |
| 1.6, ordinary 50% | 13 | 5 | 0 | 3 |
| 1.6, fitted 39.07% | 15 | 7 | 0 | 1 |

On source alone both bodies voted CLEAN on all 16 files. Every shared run
returned the same value on base and head. Withholding it reproduced the
source-only prompt hash and both probabilities exactly on all 32 comparisons.
With the distinguishing run, both bodies assigned more CONCERN to the
reversal in all eight pairs.

| Upstream fix | Original P(CONCERN), repair → reverse | 1.6 P(CONCERN), repair → reverse |
| --- | ---: | ---: |
| [cJSON #810](https://github.com/DaveGamble/cJSON/pull/810) | 26.58% → 64.31% | 24.39% → 59.03% |
| [ms #111](https://github.com/vercel/ms/pull/111) | 24.35% → 63.12% | 13.68% → 60.81% |
| [Underscore #3018](https://github.com/jashkenas/underscore/pull/3018) | 26.19% → 71.25% | 19.39% → 72.40% |
| [Underscore #3026](https://github.com/jashkenas/underscore/pull/3026) | 28.20% → 53.98% | 18.84% → 57.52% |
| [PapaParse #1124](https://github.com/mholt/PapaParse/pull/1124) | 41.19% → 60.21% | 31.65% → 48.77% |
| [PapaParse #1128](https://github.com/mholt/PapaParse/pull/1128) | 40.97% → 55.64% | 24.94% → 50.43% |
| [npm/ini #123](https://github.com/npm/ini/pull/123) | 37.58% → 52.56% | 26.60% → 45.69% |
| [npm/ini #252](https://github.com/npm/ini/pull/252) | 26.53% → 56.58% | 20.26% → 36.58% |

At 39.07%, 1.6 recovered the broken custom quote in PapaParse #1124 and
the missing INI value in #123. Every previously correct decision survived.
On #252 the contract required duplicate values to produce `["1","2"]`.
The reversal returned the scalar `"1"`. Its 36.58% fell below the fitted
cutoff. This cost the candidate the preregistered comparison with the
original on full pairs and misses.

## Reproduce

Run from the JOVOVICH checkout with Git, a C compiler, Node.js (tested with
24.22.1), jq, gzip, tar and OpenSSL. The harness collects each pinned source
directly from Git. The Underscore probes load its pinned ES modules. The
other JavaScript probes need only the listed implementation file.

```sh
set -e
make all check
work=$(mktemp -d)
for repo in DaveGamble/cJSON vercel/ms jashkenas/underscore mholt/PapaParse npm/ini; do
    mkdir -p "$work/repos/${repo%/*}"
    git clone -q "https://github.com/$repo.git" "$work/repos/$repo"
done
sh examples/threshold-transfer/corpus.sh "$work/repos" "$work/corpus"
sh examples/threshold-transfer/score.sh "$work/corpus" > "$work/results.json"
cmp examples/threshold-transfer/results.json "$work/results.json"
```

The compact archived receipts omit the duplicated Git excerpts. Scoring
restores those excerpts, verifies each original input hash and reconstructs
the AML prompt and witness. It also compares all effective prompt hashes
across checkpoints, and each shared-input vote against its source-only vote.
For a separate set of labeled reviews, the same offline decision is
`build/score-quality --model onejev1.6 --text-threshold 0.3906702995300293 EXPECTED.jsonl INPUTS.jsonl ANSWERS.jsonl aml/prepare.aml`.
The report records the policy file's SHA-256, the threshold, the raw vote
and whether each row used the fitted cutoff.

Repeat the forward passes with the two release GGUFs and shared tokenizer.

```sh
set -e
export OPENBLAS_NUM_THREADS=4 NT_ATTN_THREADS=4
build/jovovich --model onejev "$ORIGINAL_GGUF" "$TOKENIZER_GGUF" --json --canonical-boundaries \
    < "$work/corpus/inputs.jsonl" > "$work/original"
build/jovovich --model onejev1.6 "$CANDIDATE_GGUF" "$TOKENIZER_GGUF" --json --canonical-boundaries \
    < "$work/corpus/inputs.jsonl" > "$work/candidate"
sh examples/threshold-transfer/score.sh "$work/corpus" "$work/original" "$work/candidate"
```
