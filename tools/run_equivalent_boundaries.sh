#!/bin/sh
# Reproduce the fixed comparison from a completed original readout run.
set -eu
if test "$#" -ne 4; then echo 'Usage: sh tools/run_equivalent_boundaries.sh MODEL TOKENIZER PREVIOUS_RUN NEW_RUN' >&2; exit 2; fi
model=$1
tokenizer=$2
previous=$3
out=$4
mkdir "$out"
sh tools/build_corpus.sh --equivalent-forms "$out/corpus"
cmp examples/equivalent-boundaries/manifest.json "$out/corpus/manifest.json"
cmp examples/semantic-20261107/manifest.json "$previous/corpus/manifest.json"
features() {
    ./build/jovovich "$model" "$tokenizer" --features < "$1" > "$2.partial"
    mv "$2.partial" "$2"
}
features "$out/corpus/train.jsonl" "$out/train.features"
for objective in equivalent paired; do
    ./build/jovovich-readout "fit-$objective" "$out/corpus/train.jsonl" "$out/train.features" > "$out/$objective.partial"
    mv "$out/$objective.partial" "$out/$objective.json"
done
features "$out/corpus/eval-inputs.jsonl" "$out/fresh.features"
./build/jovovich-readout score-forms "$out/corpus/eval-inputs.jsonl" "$out/fresh.features" "$out/corpus/eval-expected.jsonl" \
    "$previous/adapter.json" "$out/equivalent.json" "$out/paired.json" > "$out/fresh-score.json"
for objective in equivalent paired; do
    ./build/jovovich-readout score "$previous/corpus/eval-inputs.jsonl" "$previous/transfer.features" "$previous/corpus/eval-expected.jsonl" "$out/$objective.json" > "$out/$objective-transfer.json"
    ./build/jovovich-readout score examples/quality-20261106/inputs.jsonl "$previous/legacy.features" examples/quality-20261106/expected.jsonl "$out/$objective.json" > "$out/$objective-legacy.json"
done
