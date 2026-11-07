#!/bin/sh
set -eu
work=$(mktemp -d "${TMPDIR:-/tmp}/jovovich-corpus-test-XXXXXX")
trap 'rm -rf "$work"' EXIT HUP INT TERM
sh tools/build_corpus.sh "$work/good"
./build/check-corpus "$work/good"
cmp "$work/good/manifest.json" examples/semantic-20261107/manifest.json
reject() {
    mkdir "$work/rejected"
    if ./build/semantic-corpus pack "$1" "$work/rejected" > "$work/error.out" 2> "$work/error.log"; then
        echo 'FAIL: invalid oracle receipts accepted' >&2;exit 1
    fi
    test ! -e "$work/rejected/train.jsonl"
    rmdir "$work/rejected"
}
head -n 191 "$work/good/proofs.jsonl" > "$work/cut.jsonl"
reject "$work/cut.jsonl"
sed 's/"checked":17/"checked":16/g' "$work/good/proofs.jsonl" > "$work/coverage.jsonl"
reject "$work/coverage.jsonl"
sed 's/"code_sha256":"./"code_sha256":"x/' "$work/good/proofs.jsonl" > "$work/hash.jsonl"
reject "$work/hash.jsonl"
# Change actual compiled behavior while leaving the receipt schema intact.
sed 's/return value < -5;/return value <= -5;/g' "$work/good/oracle.c" > "$work/mutant.c"
"${CC:-cc}" -std=c11 -O2 -Wall -Wextra -Werror "$work/mutant.c" -o "$work/mutant"
"$work/mutant" > "$work/mutant.jsonl"
reject "$work/mutant.jsonl"
# A wrong reference comparison must also be caught at witness validation.
sed 's/case 0:return value<limit/case 0:return value<=limit/' "$work/good/oracle.c" > "$work/reference.c"
"${CC:-cc}" -std=c11 -O2 -Wall -Wextra -Werror "$work/reference.c" -o "$work/reference"
"$work/reference" > "$work/reference.jsonl"
reject "$work/reference.jsonl"
if sh tools/build_corpus.sh "$work/good" > "$work/error.out" 2> "$work/error.log"; then exit 1;fi
cmp "$work/good/manifest.json" examples/semantic-20261107/manifest.json
printf 'Corpus gates: frozen reproducibility, three invalid receipt streams, two compiled mutations and existing-output refusal passed\n'
