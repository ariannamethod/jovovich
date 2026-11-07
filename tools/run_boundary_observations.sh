#!/bin/sh
set -eu
if test "$#" -ne 4; then echo 'Usage: sh tools/run_boundary_observations.sh MODEL TOKENIZER PR49_PAIRED_ADAPTER NEW_DIRECTORY' >&2; exit 2; fi
model=$1
tokenizer=$2
head=$3
out=$4
mkdir "$out"
sh tools/build_corpus.sh --equivalent-forms "$out/corpus"
cmp examples/equivalent-boundaries/manifest.json "$out/corpus/manifest.json"
./build/semantic-corpus --equivalent-forms observation-driver > "$out/observations.c"
"${CC:-cc}" -std=c11 -O2 -Wall -Wextra -Werror -I"$out/corpus" "$out/observations.c" -o "$out/observations"
"$out/observations" > "$out/receipts.jsonl"
for arm in none boundary adjacent; do
    input="$out/corpus/eval-inputs.jsonl"
    if test "$arm" != none; then
        input="$out/$arm.jsonl"
        ./build/semantic-corpus --equivalent-forms observe "$out/receipts.jsonl" "$arm" > "$input"
    fi
    ./build/jovovich "$model" "$tokenizer" --features < "$input" > "$out/$arm.features"
    ./build/jovovich-readout score "$input" "$out/$arm.features" "$out/corpus/eval-expected.jsonl" "$head" > "$out/$arm-score.json"
done
head -n 8 "$out/boundary.jsonl" > "$out/replay-inputs.jsonl"
./build/jovovich "$model" "$tokenizer" --json --canonical-boundaries < "$out/replay-inputs.jsonl" > "$out/canonical-live.jsonl"
./build/boundary-observations "$out/corpus" "$out" > "$out/results.partial"
mv "$out/results.partial" "$out/results.json"
