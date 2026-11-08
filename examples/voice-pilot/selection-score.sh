#!/bin/sh
set -eu
test "$#" = 2 || { echo 'Usage: sh examples/voice-pilot/selection-score.sh PACKETS RUN.json' >&2; exit 2; }
jq -n --slurpfile run "$2" --slurpfile test "$1/heldout.jsonl" \
  --arg train_hash "$(openssl dgst -sha256 "$1/train.jsonl"|awk '{print $NF}')" \
  --arg test_hash "$(openssl dgst -sha256 "$1/heldout.jsonl"|awk '{print $NF}')" \
  -f examples/voice-pilot/selection-score.jq
