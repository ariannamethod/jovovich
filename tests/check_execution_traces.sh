#!/bin/sh
set -eu
work=$(mktemp -d "${TMPDIR:-/tmp}/jov-traces-XXXXXX")
trap 'rm -rf "$work"' EXIT
ref=examples/execution-traces
./build/trace-corpus expected > "$work/expected.jsonl"
./build/trace-corpus receipts > "$work/receipts.jsonl"
cmp "$ref/receipts.jsonl" "$work/receipts.jsonl"
for arm in source control observed witness; do
    ./build/trace-corpus "$arm" > "$work/$arm.jsonl"
    ./build/score-quality "$work/expected.jsonl" "$work/$arm.jsonl" "$ref/$arm-answers.jsonl" aml/prepare.aml > "$work/$arm-score.json"
done
score() {
    ./build/score-traces "$work/source-score.json" "$work/control-score.json" "$work/observed-score.json" "$1"
}
score "$work/witness-score.json" > "$work/results.json"
cmp "$ref/results.json" "$work/results.json"
if score "$work/observed-score.json" >/dev/null 2>&1; then exit 1; fi
sed 's/"id":"trace-01"/"id":"trace-04"/' "$work/witness-score.json" > "$work/changed.json"
if score "$work/changed.json" >/dev/null 2>&1; then exit 1; fi
echo 'Verified compiled callback traces, 128 recorded reviews and all paired scores'
