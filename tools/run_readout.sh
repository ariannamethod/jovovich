#!/bin/sh
# Run from repository root after building the trainer, live host and corpus tools.
set -eu
if test "$#" -ne 3; then echo 'Usage: sh tools/run_readout.sh MODEL TOKENIZER NEW_DIRECTORY' >&2; exit 2; fi
model=$1
tokenizer=$2
out=$3
mkdir "$out"
sh tools/build_corpus.sh "$out/corpus"
cmp examples/semantic-20261107/manifest.json "$out/corpus/manifest.json"
features() {
    ./build/jovovich "$model" "$tokenizer" --features < "$1" > "$2.partial"
    mv "$2.partial" "$2"
}
features "$out/corpus/train.jsonl" "$out/train.features"
./build/jovovich-readout fit "$out/corpus/train.jsonl" "$out/train.features" > "$out/adapter.partial"
mv "$out/adapter.partial" "$out/adapter.json"
evaluate() {
    name=$1
    features "$2" "$out/$name.features"
    ./build/jovovich-readout score "$2" "$out/$name.features" "$3" "$out/adapter.json" > "$out/$name-score.partial"
    mv "$out/$name-score.partial" "$out/$name-score.json"
}
evaluate transfer "$out/corpus/eval-inputs.jsonl" "$out/corpus/eval-expected.jsonl"
evaluate legacy examples/quality-20261106/inputs.jsonl examples/quality-20261106/expected.jsonl
