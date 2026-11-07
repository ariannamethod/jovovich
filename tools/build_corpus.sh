#!/bin/sh
set -eu
if test "$#" -ne 1; then echo 'Usage: sh tools/build_corpus.sh NEW_OUTPUT_DIRECTORY' >&2;exit 2;fi
out=$1
if test -e "$out"; then echo 'Corpus output directory already exists' >&2;exit 1;fi
mkdir -p "$(dirname "$out")"
work=$(mktemp -d "$(dirname "$out")/jovovich-corpus-XXXXXX")
trap 'rm -rf "$work"' EXIT HUP INT TERM
./build/semantic-corpus source > "$work/oracle.c"
"${CC:-cc}" -std=c11 -O2 -Wall -Wextra -Werror "$work/oracle.c" -o "$work/oracle"
"$work/oracle" > "$work/proofs.jsonl"
./build/semantic-corpus pack "$work/proofs.jsonl" "$work"
rm "$work/oracle"
test ! -e "$out"
mv "$work" "$out"
printf 'Verified corpus: 128 training rows, 64 evaluation rows in %s\n' "$out"
