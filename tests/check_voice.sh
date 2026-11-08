#!/bin/sh
# Replay the published auditions without loading weights or executing a checkout.
set -eu
dir=examples/voice-pilot
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
trap 'exit 1' HUP INT TERM
hash() { openssl dgst -sha256 "$1" | awk '{print $NF}'; }
gzip -dc "$dir/voice.json.gz" > "$tmp/voice"
jq -e --slurpfile heard "$dir/audition.json" --slurpfile test "$dir/heldout.jsonl" \
  --arg policy "$(hash aml/voice-prompt.aml)" --arg train "$(hash "$dir/train.jsonl")" \
  --arg held "$(hash "$dir/heldout.jsonl")" '
 .schema=="jovovich.voice-pilot/1" and .prompt_policy_sha256==$policy and
 .train_sha256==$train and .heldout_sha256==$held and .steps==200 and
 .learned_parameters==3498 and (.adapter|length)==106 and
 (.adapter|map(.token)|unique|length)==106 and all(.adapter[]; (.weight_and_bias|length)==33) and
 (.audition|length)==6 and (.audition|map(.id))==($test|map(.id)) and
 (.audition|map(.id))==($heard[0]|map(.id)) and
 all(.audition[]; .base.stop=="cap" and (.base.token_ids|length)==32 and .fitted.stop=="eog")' "$tmp/voice" >/dev/null
for i in 0 1 2 3 4 5; do
    for mode in base fitted; do
        want=$(jq -r --argjson i "$i" --arg m "$mode" '.audition[$i][$m].utf8_hex' "$tmp/voice")
        got=$(jq -jr --argjson i "$i" --arg m "$mode" '.[$i][$m].text' "$dir/audition.json"|od -A n -v -t x1|tr -d ' \n')
        test "$got" = "$want"
    done
done
gzip -dc "$dir/d1.jsonl.gz" > "$tmp/liquid"
jq -n --slurpfile rows "$tmp/liquid" --slurpfile panel examples/threshold-transfer/results.json -f "$dir/d1-score.jq" > "$tmp/d1-score"
jq -e '(.by_view_and_order|map(.pairs_correct))==[0,0,0,1] and
      (.verdict_changes_on_reorder|map(.flips))==[0,1]' "$tmp/d1-score" >/dev/null
sh "$dir/selection.sh" "$tmp/selection"
gzip -dc "$dir/selection.json.gz" > "$tmp/run"
test "$(jq -r .prompt_policy_sha256 "$tmp/run")" = "$(hash aml/voice-select.aml)"
sh "$dir/selection-score.sh" "$tmp/selection" "$tmp/run" > "$tmp/score"
cmp "$tmp/score" "$dir/selection-results.json"
gzip -dc "$dir/selection-stability.json.gz" > "$tmp/stability"
jq -e --slurpfile original "$tmp/run" '
  del(.optimizer_tail)==$original[0] and
  (.optimizer_tail|map([.rate,.step]))==[ (0.25,0.025) as $rate | range(197;201)|[$rate,.] ] and
  all(.optimizer_tail[]; (.heldout_p_a|length)==24 and all(.heldout_p_a[]; type=="number" and .>=0 and .<=1)) and
  .optimizer_tail[3].heldout_p_a==($original[0].audition|map(.fitted))' "$tmp/stability" > /dev/null
echo 'Verified original and fitted voice receipts, both selector orders and 64 Liquid choices'

paired=examples/paired-voice
sh "$paired/packets.sh" "$tmp/paired"
test "$(hash "$tmp/paired/train.jsonl")" = e1cd6c0fc5c70ee90e91b2cd0108c77a5e09e4412f41278a679ba6e762f2d459
jq -e --slurpfile h "$tmp/paired/heldout.jsonl" --slurpfile model models/onejev-0.8b.json \
  --arg held "$(hash "$tmp/paired/heldout.jsonl")" --arg aml "$(hash aml/voice-prompt.aml)" '
  .schema=="jovovich.voice-baseline/1" and .heldout_sha256==$held and .prompt_policy_sha256==$aml
  and .weights_sha256==$model[0].weights_sha256 and .tokenizer_sha256==$model[0].tokenizer_sha256
  and (.audition|map(.id))==($h|map(.id))
  and all(.audition[].base; (.utf8_hex|test("^([0-9a-f]{2})*$")) and
      (.token_ids|all(.[]; type=="number" and .==floor and .>=0)) and
      (if .stop=="cap" then (.token_ids|length)==32 else .stop=="eog" and (.token_ids|length|.>=1 and .<=32) end))
' "$paired/base.json" >/dev/null
echo 'Rebuilt the paired voice corpus and bound each frozen generation to its review'
