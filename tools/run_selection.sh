#!/bin/sh
set -eu
if test "$#" -ne 3; then
    echo 'Usage: sh tools/run_selection.sh MODEL.gguf TOKENIZER.gguf NEW_DIRECTORY' >&2
    exit 2
fi
model=$1
tokenizer=$2
out=$3
mkdir "$out"
./build/trace-corpus choices > "$out/choices.jsonl"
./build/jovovich "$model" "$tokenizer" --select-run < "$out/choices.jsonl" > "$out/choices-answers.jsonl"
modes=$(./build/score-run-selection modes "$out")
./build/trace-corpus distinguishing > "$out/oracle-modes"
./build/trace-corpus expected > "$out/expected.jsonl"
./build/trace-corpus paired "$modes" > "$out/selected.jsonl"
./build/trace-corpus paired > "$out/mechanical.jsonl"
for arm in selected mechanical; do
    ./build/jovovich "$model" "$tokenizer" --json < "$out/$arm.jsonl" > "$out/$arm-answers.jsonl"
    ./build/score-quality "$out/expected.jsonl" "$out/$arm.jsonl" "$out/$arm-answers.jsonl" aml/prepare.aml > "$out/$arm-score.json"
done
./build/score-run-selection score "$out" > "$out/results.partial"
mv "$out/results.partial" "$out/results.json"
