#!/bin/sh
set -eu
ref=examples/run-selection
d=$(mktemp -d "${TMPDIR:-/tmp}/jov-selection-XXXXXX")
trap 'rm -rf "$d"' EXIT
for arm in choices selected mechanical; do cp "$ref/$arm-answers.jsonl" "$d/$arm-answers.jsonl"; done
./build/trace-corpus choices > "$d/choices.jsonl"
modes=$(./build/score-run-selection modes "$d")
./build/trace-corpus distinguishing > "$d/oracle-modes"
./build/trace-corpus expected > "$d/expected.jsonl"
./build/trace-corpus paired "$modes" > "$d/selected.jsonl"
./build/trace-corpus paired > "$d/mechanical.jsonl"
for arm in selected mechanical; do
    ./build/score-quality "$d/expected.jsonl" "$d/$arm.jsonl" "$d/$arm-answers.jsonl" aml/prepare.aml > "$d/$arm-score.json"
done
./build/score-run-selection score "$d" > "$d/results.json"
cmp "$ref/results.json" "$d/results.json"
sed '1s/"differing":1/"differing":0/' "$d/mechanical-answers.jsonl" > "$d/forged"
if ./build/score-quality "$d/expected.jsonl" "$d/mechanical.jsonl" "$d/forged" aml/prepare.aml >/dev/null 2>&1; then exit 1; fi
sed '1s/"prompt_sha256":"./"prompt_sha256":"x/' "$ref/choices-answers.jsonl" > "$d/choices-answers.jsonl"
if ./build/score-run-selection modes "$d" >/dev/null 2>&1; then exit 1; fi
./build/jovovich-report "$ref/git-input.jsonl" "$ref/git-answer.jsonl" > "$d/git.md"
grep -Fq '**Execution supplied to the model**' "$d/git.md"
./build/jovovich-report "$ref/git-input.jsonl" "$ref/git-answer.jsonl" --json > "$d/git.json"
grep -Fq '"selected_mode":1' "$d/git.json"
echo 'Verified 32 blind selections, 64 gated live decisions and their archived F32 prompt replays'
