#!/bin/sh
# Bind every presentation to the frozen native input bytes and Git endpoints.
# The release archive includes 33 auxiliary controls after its 24 trial rows.
set -eu
case $1 in
    examples/release-trial/cases.tsv)
        archive=examples/release-trial/onejev.jsonl.gz rows=24
        digest=541e55655b9075b8a4b9d46e406ea7f814f01ae67b30d1739c64d3980371ece9 ;;
    examples/threshold-transfer/cases.tsv)
        archive=examples/threshold-transfer/onejev.jsonl.gz rows=48
        digest=6b5c233547ebe7ada29cd90894a0d244cddd99b09c0a5ab41d59360122dad4eb ;;
    examples/voice-pilot/method.tsv)
        archive=examples/voice-pilot/method.jsonl.gz rows=6
        digest=a127eed75bcd106facf2c270cd107a32a26c10dbae61f85c3a7cd26353a0d823 ;;
    *) echo "Unregistered panel roster" >&2; exit 1 ;;
esac
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
trap 'exit 1' HUP INT TERM
gzip -dc "$archive" > "$tmp/reference"
hash() { openssl dgst -sha256 | awk '{print $NF}'; }
test "$(hash < "$tmp/reference")" = "$digest" || { echo "Native panel reference digest mismatch" >&2; exit 1; }
sh tools/check_receipts.sh "$3/index.jsonl" "$3/inputs.jsonl"
jq -rs --argjson n "$rows" '.[:$n][] | .execution.input_sha256' "$tmp/reference" > "$tmp/expected"
while IFS= read -r line; do printf '%s\n' "$line" | hash; done < "$3/inputs.jsonl" > "$tmp/actual"
cmp "$tmp/expected" "$tmp/actual" >&2 || { echo "Ordered native input digest mismatch" >&2; exit 1; }
jq -en --argjson n "$rows" --slurpfile reference "$tmp/reference" --slurpfile inputs "$3/inputs.jsonl" '
    ($inputs|length)==$n and all(range($n); . as $i | $inputs[$i].source==$reference[$i].source)' >/dev/null ||
    { echo "Native panel Git endpoint mismatch" >&2; exit 1; }
jq -en --rawfile roster "$1" --argjson views "$2" \
    --slurpfile index "$3/index.jsonl" --slurpfile inputs "$3/inputs.jsonl" \
    -f examples/release-trial/check-panel.jq > /dev/null
