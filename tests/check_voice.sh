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
sh "$dir/d1-score.sh" "$tmp/liquid" > "$tmp/d1-score"
jq -c '.state_sha256=("0"*64)' "$tmp/liquid" > "$tmp/wrong-state"
if sh "$dir/d1-score.sh" "$tmp/wrong-state" > "$tmp/scored" 2>/dev/null; then
    echo 'Accepted unregistered Liquid state digests' >&2; exit 1
fi
# Replacing labels in both the reference and the receipts must also fail.
sandbox=$tmp/liquid-root
mkdir -p "$sandbox/examples/threshold-transfer"
ln -s "$PWD/$dir" "$sandbox/examples/voice-pilot"
ln -s "$PWD/tools" "$sandbox/tools"
ln -s "$PWD/build" "$sandbox/build"
invert='if .=="repair" then "reverse" else "repair" end'
jq ".cases[].direction |= ($invert)" examples/threshold-transfer/results.json > "$sandbox/examples/threshold-transfer/results.json"
jq -c ".direction |= ($invert)" "$tmp/liquid" > "$tmp/relabeled-liquid"
if (cd "$sandbox" && sh "$dir/d1-score.sh" "$tmp/relabeled-liquid") > "$tmp/scored" 2>/dev/null; then
    echo 'Accepted jointly relabeled Liquid panel and receipts' >&2; exit 1
fi
# A numeric PR and its string spelling are distinct pair identities in jq.
# Text serialization used to give them the same digest and split a reversal
# from its repair, producing nine apparent pairs from eight PRs.
as_string='if .project=="DaveGamble/cJSON" and .direction=="reverse" then .pr |= tostring else . end'
jq ".cases |= map($as_string)" examples/threshold-transfer/results.json > "$sandbox/examples/threshold-transfer/results.json"
jq -c "$as_string" "$tmp/liquid" > "$tmp/unpaired-liquid"
if (cd "$sandbox" && sh "$dir/d1-score.sh" "$tmp/unpaired-liquid") > "$tmp/scored" 2>/dev/null; then
    echo 'Accepted inconsistent PR identity types in both Liquid sources' >&2; exit 1
fi
# Alternate integral JSON spellings still identify the original PR.
for pr in 810.0 8.1e2; do
    sed -E 's/("pr"[[:space:]]*:[[:space:]]*)810([,}])/\1'"$pr"'\2/g' "$tmp/liquid" > "$tmp/numeric-liquid"
    if cmp -s "$tmp/liquid" "$tmp/numeric-liquid"; then exit 1; fi
    sh "$dir/d1-score.sh" "$tmp/numeric-liquid" > "$tmp/scored"
    cmp "$tmp/d1-score" "$tmp/scored"
done
jq -c '.order=(if .order=="clean-first" then "concern-first" else "clean-first" end)' "$tmp/liquid" > "$tmp/swapped"
if sh "$dir/d1-score.sh" "$tmp/swapped" > "$tmp/scored" 2>/dev/null; then
    echo 'Accepted exchanged Liquid criterion orders' >&2; exit 1
fi
jq -e '(.by_view_and_order|map(.pairs_correct))==[0,0,0,1] and
      (.verdict_changes_on_reorder|map(.flips))==[0,1]' "$tmp/d1-score" >/dev/null
sh "$dir/selection.sh" "$tmp/selection"
gzip -dc "$dir/selection.json.gz" > "$tmp/run"
test "$(jq -r .prompt_policy_sha256 "$tmp/run")" = "$(hash aml/voice-select.aml)"
sh "$dir/selection-score.sh" "$tmp/selection" "$tmp/run" > "$tmp/score"
cmp "$tmp/score" "$dir/selection-results.json"
# A receipt supplies predictions. Targets and choices belong to the frozen test.
for alteration in '(.audition[].target)="A"' '.weights_sha256="different"' '.prompt_policy_sha256="different"' \
    '.heldout_nll=[0,0]' '.audition[0].base=0 | .audition[0].fitted=1'; do
    jq "$alteration" "$tmp/run" > "$tmp/forged"
    if sh "$dir/selection-score.sh" "$tmp/selection" "$tmp/forged" > "$tmp/scored" 2>/dev/null; then
        echo "Accepted altered voice receipt: $alteration" >&2; exit 1
    fi
    test ! -s "$tmp/scored"
done
# Rounding at unit letter mass is valid. A larger excess must fail.
jq --slurpfile score "$tmp/score" '.heldout_nll=($score[0].heldout_loss|map(.within_letters-1e-7))' "$tmp/run" > "$tmp/rounded"
sh "$dir/selection-score.sh" "$tmp/selection" "$tmp/rounded" > "$tmp/rounded-score"
jq -e 'all(.heldout_loss[]; .geometric_mean_letter_mass == 1)' "$tmp/rounded-score" >/dev/null
jq -c '.target=(if .target=="A" then "B" else "A" end)' "$tmp/selection/heldout.jsonl" > "$tmp/relabeled"
# Replace the pathname while its first, genuine byte stream is open.
# The scorer must use verified bytes for the actual score.
mv "$tmp/selection/heldout.jsonl" "$tmp/registered"
mkfifo "$tmp/selection/heldout.jsonl"
(
    exec 3>"$tmp/selection/heldout.jsonl"
    mv "$tmp/relabeled" "$tmp/selection/heldout.jsonl"
    cat "$tmp/registered" >&3
) & writer=$!
sh "$dir/selection-score.sh" "$tmp/selection" "$tmp/run" > "$tmp/after-swap"
wait "$writer"
cmp "$tmp/after-swap" "$tmp/score"
jq --arg hash "$(hash "$tmp/selection/heldout.jsonl")" '.heldout_sha256=$hash' "$tmp/run" > "$tmp/forged"
if sh "$dir/selection-score.sh" "$tmp/selection" "$tmp/forged" > "$tmp/scored" 2>/dev/null; then
    echo "Accepted jointly altered selector targets and receipt" >&2; exit 1
fi
gzip -dc "$dir/selection-stability.json.gz" > "$tmp/stability"
jq -e --slurpfile original "$tmp/run" '
  del(.optimizer_tail)==$original[0] and
  (.optimizer_tail|map([.rate,.step]))==[ (0.25,0.025) as $rate | range(197;201)|[$rate,.] ] and
  all(.optimizer_tail[]; (.heldout_p_a|length)==24 and all(.heldout_p_a[]; type=="number" and .>=0 and .<=1)) and
  .optimizer_tail[3].heldout_p_a==($original[0].audition|map(.fitted))' "$tmp/stability" > /dev/null
echo 'Verified original and fitted voice receipts, both selector orders and 64 Liquid choices'
