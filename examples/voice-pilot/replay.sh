#!/bin/sh
# Verify the archived votes against rebuilt Git inputs and reconstruct voice packets.
set -eu
test "$#" = 2 || { echo 'Usage: sh examples/voice-pilot/replay.sh THRESHOLD_CORPUS METHOD_CORPUS' >&2; exit 2; }
dir=examples/voice-pilot
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
trap 'exit 1' HUP INT TERM
for panel in upstream method; do
    case "$panel" in
        upstream) src=examples/threshold-transfer/onejev.jsonl.gz corpus=$1 n=48 ;;
        method) src=$dir/method.jsonl.gz corpus=$2 n=6 ;;
    esac
    gzip -dc "$src" > "$tmp/receipts"
    sh tools/check_receipts.sh "$tmp/receipts"
    jq -cn --argjson n "$n" --slurpfile received "$tmp/receipts" --slurpfile inp "$corpus/inputs.jsonl" '
      if ($received|length)!=$n or ($inp|length)!=$n then error("incomplete stream")
      else range(0;$n) as $i | $received[$i] + {input:($inp[$i]|{context,rule_excerpt,change_excerpt})} end' > "$tmp/$panel"
done
sh "$dir/packets.sh" "$1" "$tmp/upstream" "$2" "$tmp/method" "$tmp/rebuilt"
for split in train heldout; do cmp "$dir/$split.jsonl" "$tmp/rebuilt/$split.jsonl"; done
sh "$dir/d1-requests.sh" "$1" > "$tmp/requests"
gzip -dc "$dir/d1.jsonl.gz" > "$tmp/liquid"
sh tools/check_receipts.sh "$tmp/liquid"
jq -cn --slurpfile req "$tmp/requests" --slurpfile obs "$tmp/liquid" '
  if ($req|length)!=64 or ($obs|length)!=64 then error("incomplete Liquid stream")
  else range(64) as $i | $req[$i] as $r | $obs[$i] as $o |
    if ($r|{project,pr,direction,view,order,input_sha256}) != ($o|{project,pr,direction,view,order,input_sha256}) or
       ($r.questions.review.criteria|keys_unsorted)!=($o.answers.review.probabilities|keys_unsorted)
    then error("Liquid request does not match receipt") else [$o.state_sha256,$r.state] end end' > "$tmp/bound"
while IFS= read -r row; do
    printf '%s\n' "$row" | jq -jr '.[1]' > "$tmp/state"
    want=$(printf '%s\n' "$row" | jq -r '.[0]')
    test "$want" = "$(openssl dgst -sha256 "$tmp/state"|awk '{print $NF}')"
done < "$tmp/bound"
sh "$dir/d1-score.sh" "$tmp/liquid"
