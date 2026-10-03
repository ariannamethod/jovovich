# Reproducing the per-layer readout

Everything below runs from the repository root. The three model files and every
feature matrix and fit file stay out of Git; each is content-addressed in
`plan.json` or in a run's `manifest.json`, so a reproduction is checked against
hashes rather than against a description.

Integration audit, 2026-10-03: the commands below document the historical
runner. It does not implement the repository's incremental remote archive
contract, and its `--reuse-extraction` option does not verify the original
model/prompt/extractor bindings. New collection uses
`training/layers/run_layers.py` with its durable archive configuration.
The committed summaries and token traces were checked independently; this
repository contains no remote archive receipt for this study's raw matrices
and fit files. Historical source/hash mappings and the audit are recorded in
`training/results/2026-10-03-verdict-positions/integration/claude-study-audit.json`.

## 1. Build

```sh
git submodule update --init --recursive        # deps/notorch at 014403faa76b795aefe18a4781980f5b140e0ed3
make build/jovovich-extract-layers-bodies build/jovovich-readout-fit build/jovovich-layer-fixture
```

## 2. The bodies

```sh
node bin/jovovich.mjs fetch-model              # body 1, verified against model.json
curl -sL -o models/qwen2.5-0.5b-instruct-q8_0.gguf \
  https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/9217f5db79a29953eb74d5343926648285ec7e67/qwen2.5-0.5b-instruct-q8_0.gguf
scp ariannamethod@<metal>:~/arianna/jovovich/models/amos-x-qwen-2.5-0.5b-before-subliteration.gguf models/
shasum -a 256 models/*.gguf                    # must match plan.json bodies[].sha256
```

## 3. The gate that licenses the word "published"

The per-layer audit is a port of the published counting rules, so it is checked
against the published record before it is used on anything new:

```sh
node training/readout/layer_summary.mjs \
  --fits training/results/2026-10-01-frozen-readout/state-fits.jsonl \
  --rows training/results/2026-10-01-frozen-readout/readout-rows.json \
  --masks-json training/results/2026-10-01-frozen-readout/readout-masks.json \
  --width 896 --label published-parity --output /tmp/published-z-summary.json
node training/readout/compare_published.mjs --mine /tmp/published-z-summary.json \
  --published training/results/2026-10-01-frozen-readout/readout-summary.json
echo $?                                         # 0, and 27 of 27 fields equal
```

`parity/published-z-summary.json` and `parity/parity-gate.json` are that run.

## 4. The fixture, before the data

```sh
mkdir -p /tmp/fx && ./build/jovovich-layer-fixture models/jovovich.gguf \
  training/results/2026-10-01-frozen-readout/readout-metadata.txt /tmp/fx 1
node training/readout/run_layers.mjs --model /tmp/fx/fixture.gguf \
  --prompts /tmp/fx/fixture-prompts.bin --metadata /tmp/fx/fixture-metadata.txt \
  --masks training/results/2026-10-01-frozen-readout/readout-masks.txt \
  --masks-json training/results/2026-10-01-frozen-readout/readout-masks.json \
  --rows training/results/2026-10-01-frozen-readout/readout-rows.json \
  --width 64 --out /tmp/fx/run --label fixture-plant1 --threads 4
```

The last argument of the fixture builder is the planted block: `1` and `2` move
the onset depth with it, `-1` builds the body with no plant at all and every
depth must then read 26/52 and 0/26. `fixture/fixture-gate.json` holds the three
runs and says plainly why the invariant is the onset depth and not isolation.

## 5. The three bodies

```sh
for body in jovovich qwen2.5-0.5b-instruct-q8_0 amos-x-qwen-2.5-0.5b-before-subliteration; do
  node training/readout/run_layers.mjs --model models/$body.gguf \
    --prompts training/results/2026-10-01-frozen-readout/readout-input.bin \
    --metadata training/results/2026-10-01-frozen-readout/readout-metadata.txt \
    --masks training/results/2026-10-01-frozen-readout/readout-masks.txt \
    --masks-json training/results/2026-10-01-frozen-readout/readout-masks.json \
    --rows training/results/2026-10-01-frozen-readout/readout-rows.json \
    --width 896 --out /tmp/$body --label $body --threads 4
done
```

Each run writes 25 feature matrices, 25 fit files, 25 summaries, a `manifest.json`
with every hash and every return code, and a `table.json`. The committed
`body1/`, `body2/` and `body3/` directories hold the manifests, tables,
summaries and token traces of the runs reported here; the matrices and fit files
are named with their hashes in those manifests.

A body's token trace must be identical to the published extraction's, which is
what proves the decision positions are the same ones:

```sh
diff body1/extract.stdout.jsonl training/results/2026-10-01-frozen-readout/extract.stdout.jsonl
```

## 6. The combined table

```sh
node training/readout/layer_table.mjs --plan training/results/2026-10-02-layer-readout-three-bodies/plan.json \
  --table coder-base=/tmp/jovovich/table.json \
  --table plain-instruct=/tmp/qwen2.5-0.5b-instruct-q8_0/table.json \
  --table abliterated-coder=/tmp/amos-x-qwen-2.5-0.5b-before-subliteration/table.json \
  --output-json /tmp/combined-table.json --output-md /tmp/combined-table.md
```

## Reading the numbers

The floor is the published final-position result: 29/52 correct and 4/26
complete pairs. A depth "clears the declared reading" when it is strictly above
both, and the permutation exceedance stands beside it rather than behind a
threshold. The seven-feature lexical nuisance baseline reached 35/52 and 9/26 on
the same corpus; it is layer-independent and is cited from the published record,
not refitted here.

Floating-point results are machine-dependent. The fit is float64 from float32
inputs and reproduces exactly on the same binary and inputs; the extraction runs
quantized Q8_0 arithmetic through notorch's kernels, so another architecture may
differ in the last bits of a feature and, at a boundary, in a prediction. The
hashes in the manifests say which bytes produced the numbers reported here.
