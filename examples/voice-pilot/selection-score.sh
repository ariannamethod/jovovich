#!/bin/sh
set -eu
test "$#" = 2 || { echo 'Usage: sh examples/voice-pilot/selection-score.sh PACKETS RUN.json' >&2; exit 2; }
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
trap 'exit 1' HUP INT TERM
# Pin the authored targets independently of the run. The panel builder can
# regenerate these exact packet bytes from the registered lines and votes.
train_hash=1c37323ba3d66a13f5d57aa9be166acdaad9c63f87e792473164a375c7a30371
test_hash=c1fdb3545164b0d77b1d884c8895d858c7dbfe4e3daba9f88f20c9c3c92f26a7
cat < "$1/train.jsonl" > "$tmp/train"
cat < "$1/heldout.jsonl" > "$tmp/heldout"
hash() { openssl dgst -sha256 < "$1" | awk '{print $NF}'; }
if test "$(hash "$tmp/train")" != "$train_hash" || test "$(hash "$tmp/heldout")" != "$test_hash"; then
    echo "Unregistered selector packets" >&2; exit 1
fi
cat < "$2" > "$tmp/run"
sh tools/check_receipts.sh "$tmp/run"
jq -n --slurpfile run "$tmp/run" --slurpfile test "$tmp/heldout" \
  --arg train_hash "$train_hash" --arg test_hash "$test_hash" \
  --slurpfile manifest models/onejev-0.8b.json \
  --arg policy_hash "$(hash aml/voice-select.aml)" \
  -f examples/voice-pilot/selection-score.jq
