#!/bin/sh
# Live paired experiment. Run from the repository root with converted weights.
set -eu
if test "$#" -ne 3; then
    echo 'Usage: sh tests/run_quality.sh MODEL.gguf TOKENIZER.gguf OUTPUT_DIRECTORY' >&2
    exit 2
fi
root=$(pwd)
case "$1" in /*) model=$1 ;; *) model="$root/$1" ;; esac
case "$2" in /*) tokenizer=$2 ;; *) tokenizer="$root/$2" ;; esac
mkdir -p "$3"
out=$(cd "$3" && pwd)
work=$(mktemp -d "$out/runtime-XXXXXX")
trap 'rm -rf "$work"' EXIT HUP INT TERM
mkdir "$work/aml" "$work/models"
cp aml/answer.aml "$work/aml/answer.aml"
cp models/onejev-0.8b.json "$work/models/onejev-0.8b.json"
cases="$root/examples/quality-20261106"
for variant in baseline candidate; do
    cp "$cases/$variant-prepare.aml" "$work/aml/prepare.aml"
    (cd "$work" && "$root/build/jovovich" "$model" "$tokenizer" --json < "$cases/inputs.jsonl") > "$out/$variant-answers.jsonl" 2> "$out/$variant.log"
    "$root/build/score-quality" "$cases/expected.jsonl" "$cases/inputs.jsonl" "$out/$variant-answers.jsonl" "$cases/$variant-prepare.aml" > "$out/$variant-score.json"
done
printf 'Complete paired native run saved in %s\n' "$out"
