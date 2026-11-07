#!/bin/sh
set -eu
if test "$#" -ne 3; then
    echo 'Usage: sh tools/run_execution_traces.sh MODEL.gguf TOKENIZER.gguf NEW_DIRECTORY' >&2
    exit 2
fi
model=$1
tokenizer=$2
out=$3
mkdir "$out"
./build/trace-corpus expected > "$out/expected.jsonl"
./build/trace-corpus receipts > "$out/receipts.jsonl"
for arm in source control observed witness; do
    ./build/trace-corpus "$arm" > "$out/$arm.jsonl"
    ./build/jovovich "$model" "$tokenizer" --json < "$out/$arm.jsonl" > "$out/$arm-answers.jsonl"
    ./build/score-quality "$out/expected.jsonl" "$out/$arm.jsonl" "$out/$arm-answers.jsonl" aml/prepare.aml > "$out/$arm-score.json"
done
./build/score-traces "$out/source-score.json" "$out/control-score.json" "$out/observed-score.json" "$out/witness-score.json" > "$out/results.partial"
mv "$out/results.partial" "$out/results.json"
