#!/bin/sh
set -eu
work=$(mktemp -d "${TMPDIR:-/tmp}/jov-boundary-observations-XXXXXX")
trap 'rm -rf "$work"' EXIT
ref=examples/boundary-observations
sh tools/build_corpus.sh --equivalent-forms "$work/corpus" >/dev/null
cmp examples/equivalent-boundaries/manifest.json "$work/corpus/manifest.json"
./build/semantic-corpus --equivalent-forms observation-driver > "$work/driver.c"
"${CC:-cc}" -std=c11 -O2 -Wall -Wextra -Werror -I"$work/corpus" "$work/driver.c" -o "$work/driver"
"$work/driver" > "$work/receipts.jsonl"
cmp "$ref/receipts.jsonl" "$work/receipts.jsonl"
for arm in boundary adjacent; do
    ./build/semantic-corpus --equivalent-forms observe "$work/receipts.jsonl" "$arm" > "$work/$arm.jsonl"
done
for name in none-score.json boundary-score.json adjacent-score.json canonical-live.jsonl; do cp "$ref/$name" "$work/$name"; done
./build/boundary-observations "$work/corpus" "$work" > "$work/results.json"
cmp "$ref/results.json" "$work/results.json"
head -8 "$work/corpus/eval-expected.jsonl" > "$work/replay-gold"
head -8 "$work/boundary.jsonl" > "$work/replay-inputs"
replay() {
    ./build/score-quality "$work/replay-gold" "$work/replay-inputs" "$1" aml/prepare.aml > "$work/replay-score"
}
replay "$work/canonical-live.jsonl"
grep -Fq '"boundary_policy":"signed-int-comparison/1","all":{"total":8,"correct":8' "$work/replay-score"
sed '1s/"prompt_sha256":"./"prompt_sha256":"x/' "$work/canonical-live.jsonl" > "$work/forged"
if replay "$work/forged" 2>/dev/null; then exit 1; fi
sed '1s/"returned":0/"returned":1/' "$work/receipts.jsonl" > "$work/forged"
if ./build/semantic-corpus --equivalent-forms observe "$work/forged" boundary > /dev/null 2>&1; then exit 1; fi
echo 'Verified compiled observations, 1,632 rewrite comparisons, all prompt mappings and the native replay'
