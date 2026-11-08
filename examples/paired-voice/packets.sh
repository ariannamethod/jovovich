#!/bin/sh
# From the repository root: make both splits from original OneJev execution receipts.
set -eu
export LC_ALL=C
fail() { echo "$*" >&2; exit 1; }
case $# in 1|2) ;; *) echo 'Usage: sh examples/paired-voice/packets.sh NEW_OUTPUT_DIR [LIVE_RECEIPTS.jsonl]' >&2; exit 2;; esac
case $1 in /*) out=$1;; ?*) out=./$1;; *) fail 'Empty output path';; esac
name=$(basename "$out")
parent=$(dirname "$out")
case $name in .|..|/) fail 'Output must be a new directory';; esac
out=$parent/$name
if test -e "$out" || test -L "$out"; then fail "Output exists: $out"; fi
mkdir -p "$parent"
stage=$(mktemp -d "$parent/.paired-voice.XXXXXXXX")
trap 'rm -rf "$stage"' 0
trap 'exit 1' HUP INT TERM
result=$stage/result
mkdir -p "$result"
dir=examples/paired-voice
train=examples/threshold-transfer
held=examples/release-trial
hash() { openssl dgst -sha256 < "$1" | awk '{print $NF}'; }
check_hash() { test "$(hash "$1")" = "$2" || fail "SHA-256 mismatch: $1"; }

# The archives omit repeated input excerpts. Pin their native receipts, including the
# source and witness fields which are deliberately not all copied to AML.
gzip -dc "$train/onejev.jsonl.gz" > "$stage/train"
gzip -dc "$held/onejev.jsonl.gz" > "$stage/held"
check_hash "$stage/train" 6b5c233547ebe7ada29cd90894a0d244cddd99b09c0a5ab41d59360122dad4eb
check_hash "$stage/held" 541e55655b9075b8a4b9d46e406ea7f814f01ae67b30d1739c64d3980371ece9

live=false
: > "$stage/live"
if test "$#" -eq 2; then
    live=true
    cat < "$2" > "$stage/raw"
    jq -Rne -f "$dir/check-literals.jq" "$stage/raw" >/dev/null || fail "Invalid JSON literal in live receipt"
    jq -Rce fromjson "$stage/raw" > "$stage/live"
    # A normal JSON reader silently discards duplicate keys. Compare parse events
    # before and after that reader to reject ambiguous probabilities or provenance.
    jq -c --stream . "$stage/raw" > "$stage/events"
    jq -c tostream "$stage/live" > "$stage/unique"
    cmp -s "$stage/events" "$stage/unique" || fail "Duplicate key in live receipt"
fi
jq -cen --argjson live "$live" --slurpfile fresh "$stage/live" \
    --slurpfile model models/onejev-0.8b.json \
    --slurpfile trainIndex "$train/results.json" --slurpfile trainVotes "$stage/train" \
    --slurpfile heldIndex "$held/results.json" --slurpfile heldVotes "$stage/held" \
    --rawfile lines examples/voice-pilot/lines.tsv --rawfile refs "$dir/references.tsv" \
    --rawfile probes "$dir/probes.tsv" -f "$dir/packets.jq" > "$stage/splits"

# Full live receipts carry the original diff and rules as well as their Git digests.
if test "$live" = true; then
    while IFS= read -r row; do
        printf '%s\n' "$row" > "$stage/row"
        for field in rule change; do
            case $field in rule) digest=rules_sha256;; change) digest=diff_sha256;; esac
            jq -jr --arg k "${field}_excerpt" '.input[$k]' "$stage/row" > "$stage/excerpt"
            check_hash "$stage/excerpt" "$(jq -r --arg k "$digest" '.source[$k]' "$stage/row")"
        done
    done < "$stage/live"
fi

jq -c '.train[]' "$stage/splits" > "$result/train.jsonl"
jq -c '.heldout[]' "$stage/splits" > "$result/heldout.jsonl"
check_hash "$result/train.jsonl" e1cd6c0fc5c70ee90e91b2cd0108c77a5e09e4412f41278a679ba6e762f2d459
check_hash "$result/heldout.jsonl" 12553ffe42826684d2f093985b4da9fe191297280ca25a27c0152ca92be86f24
sh tools/publish_directory.sh "$stage" "$result" "$out"
