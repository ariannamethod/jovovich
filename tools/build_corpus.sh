#!/bin/sh
set -eu
variant=
if test "${1:-}" = --equivalent-forms; then variant=--equivalent-forms; shift; fi
if test "$#" -ne 1; then echo 'Usage: sh tools/build_corpus.sh [--equivalent-forms] NEW_OUTPUT_DIRECTORY' >&2;exit 2;fi
out=$1
if test -e "$out"; then echo 'Corpus output directory already exists' >&2;exit 1;fi
mkdir -p "$(dirname "$out")"
work=$(mktemp -d "$(dirname "$out")/jovovich-corpus-XXXXXX")
trap 'rm -rf "$work"' EXIT HUP INT TERM
./build/semantic-corpus ${variant:+"$variant"} source > "$work/oracle.c"
"${CC:-cc}" -std=c11 -O2 -Wall -Wextra -Werror "$work/oracle.c" -o "$work/oracle"
"$work/oracle" > "$work/proofs.jsonl"
./build/semantic-corpus ${variant:+"$variant"} pack "$work/proofs.jsonl" "$work"
rm "$work/oracle"
test ! -e "$out"
mv "$work" "$out"
printf 'Verified corpus: %d training rows, %d evaluation rows in %s\n' "$(wc -l < "$out/train.jsonl")" "$(wc -l < "$out/eval-inputs.jsonl")" "$out"
