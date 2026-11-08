#!/bin/sh
# Negative tests through the ordinary weighted CLI, starting from the archived Git repair.
set -eu
test "$#" = 2 || { echo 'Usage: sh tests/check_live_inputs.sh MODEL.gguf TOKENIZER.gguf' >&2; exit 2; }
build/check-prompt-tokens "$2"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
trap 'exit 1' HUP INT TERM
head -n 1 examples/run-selection/git-input.jsonl > "$tmp/original"
build/jovovich "$1" "$2" --json < "$tmp/original" > "$tmp/answer"
jq -e --slurpfile row "$tmp/original" '.id==$row[0].id and .choice.verdict=="CLEAN"' "$tmp/answer" > /dev/null
jq -Rr 'sub("}$";",\"file\":\"decoy.c\"}")' "$tmp/original" > "$tmp/duplicate"
jq -c '.context+="\nOne extra instruction."' "$tmp/original" > "$tmp/stale"
id=$(jq -j .context "$tmp/stale" | openssl dgst -sha256 | awk '{print $NF}')
jq -c --arg id "$id" '.id=$id' "$tmp/stale" > "$tmp/rehashed"
for input in duplicate stale rehashed; do
    if build/jovovich "$1" "$2" --json < "$tmp/$input" > "$tmp/answer" 2> "$tmp/err" || test -s "$tmp/answer"; then
        echo "Invalid Git review accepted: $input" >&2; exit 1
    fi
    grep -Eq 'Invalid JSON|Git evidence hash mismatch' "$tmp/err"
done
echo 'Native Git inference admitted the repair and refused duplicate, stale and rehashed context'
