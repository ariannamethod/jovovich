#!/bin/sh
# Challenge each complete sourced panel using its own freshly executed inputs.
# Pass an existing release corpus, threshold corpus and voice Method corpus.
set -eu
test "$#" = 3 || { echo 'Usage: sh tests/check_trial_sources.sh RELEASE THRESHOLD METHOD' >&2; exit 2; }
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
trap 'exit 1' HUP INT TERM
for roster in examples/release-trial/cases.tsv examples/threshold-transfer/cases.tsv examples/voice-pilot/method.tsv; do
    case "$roster" in */release-trial/*) views=2 ;; */threshold-transfer/*) views=3 ;; *) views=1 ;; esac
    corpus=$1
    shift
    sh examples/release-trial/check-panel.sh "$roster" "$views" "$corpus"
    parent=$(jq -sr '.[0].source.base_commit' "$corpus/index.jsonl")
    for name in inputs index; do
        sed "s/$parent/0000000000000000000000000000000000001234/g" "$corpus/$name.jsonl" > "$work/$name.jsonl"
    done
    if sh examples/release-trial/check-panel.sh "$roster" "$views" "$work" 2>/dev/null; then
        echo "Accepted an unregistered parent at $roster" >&2; exit 1
    fi
done
