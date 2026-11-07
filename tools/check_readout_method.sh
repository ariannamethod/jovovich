#!/bin/sh
# Repeat the readout diagnostics with the fitted model and a swapped A/B prompt.
set -eu
if test "$#" -ne 3; then echo 'Usage: sh tools/check_readout_method.sh MODEL TOKENIZER COMPLETED_RUN' >&2; exit 2; fi
root=$(pwd -P)
absolute() { case "$1" in /*) printf '%s\n' "$1";; *) printf '%s/%s\n' "$root" "$1";; esac; }
model=$(absolute "$1")
tokenizer=$(absolute "$2")
run=$(absolute "$3")
work=$(mktemp -d "${TMPDIR:-/tmp}/jovovich-order-XXXXXX")
trap 'rm -rf "$work"' EXIT
mkdir "$work/aml"
ln -s "$root/models" "$work/models"
cp examples/readout-20261107/swapped-prepare.aml "$work/aml/prepare.aml"
(cd "$work" && "$root/build/jovovich" "$model" "$tokenizer" --features < "$run/corpus/eval-inputs.jsonl") > "$run/swapped.features.partial"
mv "$run/swapped.features.partial" "$run/swapped.features"
./build/jovovich-readout audit "$run/corpus" "$run" "$run/swapped.features" "$run/adapter.json" > "$run/diagnostics.partial"
mv "$run/diagnostics.partial" "$run/diagnostics.json"
