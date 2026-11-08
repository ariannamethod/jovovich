#!/bin/sh
# Check frozen receipts without model files. With two live runs, print a new score.
set -eu
test "$#" -eq 0 || test "$#" -eq 2 || { echo 'Usage: sh tests/check_onejev16.sh [ORIGINAL.jsonl CANDIDATE.jsonl]' >&2; exit 2; }
ref=examples/onejev16
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
corpus="$tmp/pairs"
mkdir -p "$tmp/xdg/git"
printf '%s\n' 'draw.c working-tree-encoding=UTF-16' > "$tmp/xdg/git/attributes"
printf '%s\n' 'RULES.md' > "$tmp/xdg/git/ignore"
XDG_CONFIG_HOME="$tmp/xdg" sh tools/comment-pairs.sh "$corpus"
build/trace-corpus paired > "$tmp/carryover"
build/trace-corpus expected > "$tmp/labels"
if test "$#" -eq 0; then
    gzip -dc "$ref/original.jsonl.gz" > "$tmp/onejev"
    gzip -dc "$ref/candidate.jsonl.gz" > "$tmp/onejev1.6"
else
    cp "$1" "$tmp/onejev"
    cp "$2" "$tmp/onejev1.6"
fi
verify_git() {
    build/jovovich-report --model "$profile" "$1" "$tmp/answer" --json > "$tmp/report"
}
for profile in onejev onejev1.6; do
    i=0
    while IFS= read -r row; do
        i=$((i+1))
        printf '%s\n' "$row" > "$tmp/input"
        sed -n "${i}p" "$tmp/$profile" > "$tmp/answer"
        verify_git "$tmp/input"
    done < "$corpus/inputs.jsonl"
    test "$i" -eq 32
    sed -n '33p' "$tmp/$profile" > "$tmp/answer"
    verify_git "$corpus/anchor.jsonl"
    sed -n '34,65p' "$tmp/$profile" > "$tmp/controls"
    build/score-quality --model "$profile" "$tmp/labels" "$tmp/carryover" "$tmp/controls" aml/prepare.aml > "$tmp/quality"
    sed -n '66p' "$tmp/$profile" > "$tmp/answer"
    verify_git examples/run-selection/git-input.jsonl
done
reject() {
    if "$@" > "$tmp/rejected" 2>/dev/null; then echo 'Unexpected profile success' >&2; exit 1; fi
    test ! -s "$tmp/rejected"
}
# A valid receipt for one body must fail verification against the other.
reject build/jovovich-report examples/run-selection/git-input.jsonl "$tmp/answer" --json
reject build/jovovich-report --model unknown examples/run-selection/git-input.jsonl "$tmp/answer"
reject build/score-quality "$tmp/labels" "$tmp/carryover" "$tmp/controls" aml/prepare.aml
sed -n '66p' "$tmp/onejev" > "$tmp/answer"
reject build/jovovich-report --model onejev1.6 examples/run-selection/git-input.jsonl "$tmp/answer"
build/compare-comment-pairs "$corpus/index.tsv" "$tmp/labels" "$tmp/onejev" "$tmp/onejev1.6" "$ref/draw-reference.json" > "$tmp/results"
if test "$#" -eq 0; then
    cmp "$ref/results.json" "$tmp/results"
    echo 'Verified both checkpoint identities, paired prompt hashes and 132 native decisions'
else
    cat "$tmp/results"
fi

sh tests/check_trial_labels.sh
