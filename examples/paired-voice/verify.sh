#!/bin/sh
# Compare each registered scene with its independently transcribed output.
set -eu
export LC_ALL=C
test "$#" = 2 || { echo 'Usage: sh verify.sh PACKET_DIR VOICE_RUN.json' >&2; exit 2; }
packets=$1
dir=examples/paired-voice
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' 0
trap 'exit 1' HUP INT TERM
hash() { openssl dgst -sha256 < "$1" > "$tmp/digest" && awk '{print $NF}' "$tmp/digest"; }
# Use the exact same snapshot for the schema, token and transcript checks.
cat < "$2" > "$tmp/run"
cat < "$packets/heldout.jsonl" > "$tmp/held"
cat < "$dir/transcript.jsonl" > "$tmp/heard"
# A parsed object alone hides repeated keys. The streaming parser retains them,
# including repeated keys with different spellings of the same JSON escape.
test "$(hash "$tmp/heard")" = b4c5b4ba9ea9d387ee5ab382db77fd94374178de900e0cb91d7b9a47e97d27f6 || { echo 'Registered transcript changed' >&2; exit 1; }
for file in "$tmp/run" "$tmp/heard"; do
    jq -Rne -f "$dir/check-literals.jq" "$file" >/dev/null || { echo 'Invalid JSON literal' >&2; exit 1; }
    jq -c --stream . "$file" > "$tmp/events"
    jq -c tostream "$file" > "$tmp/unique"
    cmp -s "$tmp/events" "$tmp/unique" || { echo 'Duplicate JSON key' >&2; exit 1; }
done
held=$(hash "$tmp/held")
test "$held" = 12553ffe42826684d2f093985b4da9fe191297280ca25a27c0152ca92be86f24
test "$(hash "$packets/train.jsonl")" = e1cd6c0fc5c70ee90e91b2cd0108c77a5e09e4412f41278a679ba6e762f2d459
aml=$(hash aml/voice-prompt.aml)
jq -es --arg held "$held" --arg aml "$aml" \
  --slurpfile model models/onejev-0.8b.json --slurpfile rows "$tmp/held" --slurpfile heard "$tmp/heard" '
  length==1 and (.[0] |
    keys==["audition","heldout_sha256","prompt_policy_sha256","schema","tokenizer_sha256","weights_sha256"]
    and .schema=="jovovich.voice-baseline/1" and .heldout_sha256==$held and .prompt_policy_sha256==$aml
    and .weights_sha256==$model[0].weights_sha256 and .tokenizer_sha256==$model[0].tokenizer_sha256
    and (.audition|type=="array" and length==8) and (.audition|map(.id))==($rows|map(.id))
    and ($rows|map({id,project,pr,direction}))==($heard|map({id,project,pr,direction}))
    and all($heard[]; keys==["direction","id","pr","project","text","tokens_sha256"] and (.text|type=="string")
      and (.tokens_sha256|type=="string" and length==64 and (test("[^0-9a-f]")|not)))
    and all(.audition[]; keys==["base","id"]
      and (.base | keys==["stop","token_ids","utf8_hex"] and .stop=="cap" and (.utf8_hex|type=="string")
        and (.token_ids|type=="array" and length==32
          and all(.[]; type=="number" and .==floor and .>=0 and .<248320)))))
' "$tmp/run" >/dev/null
for i in 0 1 2 3 4 5 6 7; do
    jq -cj --argjson i "$i" '.audition[$i].base.token_ids' "$tmp/run" > "$tmp/ids"
    wanted=$(jq -sr --argjson i "$i" '.[$i].tokens_sha256' "$tmp/heard")
    test "$(hash "$tmp/ids")" = "$wanted" || { echo "Token mismatch on take $i" >&2; exit 1; }
    jq -sj --argjson i "$i" '.[$i].text' "$tmp/heard" > "$tmp/text"
    od -An -v -tx1 "$tmp/text" > "$tmp/od"
    tr -d ' \n' < "$tmp/od" > "$tmp/want"
    jq -j --argjson i "$i" '.audition[$i].base.utf8_hex' "$tmp/run" > "$tmp/got"
    cmp -s "$tmp/want" "$tmp/got" || { echo "Text mismatch on take $i" >&2; exit 1; }
done
