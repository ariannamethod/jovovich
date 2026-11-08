#!/bin/sh
set -eu
test "$#" = 1 || { echo 'Usage: sh examples/voice-pilot/d1-score.sh RECEIPTS' >&2; exit 2; }
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
trap 'exit 1' HUP INT TERM
cat < "$1" > "$tmp/rows"
cat examples/threshold-transfer/results.json > "$tmp/panel"
sh tools/check_receipts.sh "$tmp/rows" "$tmp/panel"
# Bind each of the 32 Git presentations to its rendered state across both orders.
# Regenerate these tuples from d1-requests.sh and its registered source corpus.
# jq can preserve decimal spellings when it serializes a JSON number. An
# integer PR has the same identity in 810, 810.0 and 8.1e2. Validate the
# decimal digits before converting to avoid rounding a fractional ID into one.
jq -cs '
  def pr_number:
    if type != "number" or . < 1 or . > 9007199254740991 then error("invalid PR number") end |
    (tostring | ascii_downcase | split("e")) as $parts |
    ($parts[0] | split(".")) as $decimal |
    ((($decimal[1] // "") | length) - (($parts[1] // "0") | tonumber)) as $places |
    if $places > (($decimal | join("") | match("0*$")).length) then error("fractional PR number")
    else floor end;
  map([.project,(.pr | pr_number),.direction,.view,.input_sha256,.state_sha256]) | unique[]
' "$tmp/rows" > "$tmp/bindings"
digest=$(openssl dgst -sha256 < "$tmp/bindings" | awk '{print $NF}')
test "$digest" = e33ff26574c9ad0108a940c9505845b5ab276197125b8e212db5f0b7e71d1acb || { echo 'Liquid case or state differs from the executed panel' >&2; exit 1; }
jq -n --slurpfile rows "$tmp/rows" --slurpfile panel "$tmp/panel" -f examples/voice-pilot/d1-score.jq
