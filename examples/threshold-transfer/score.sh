#!/bin/sh
# Reconstruct the inputs first. The native verifier checks the raw vote and AML prompt.
set -eu
test "$#" -eq 1 || test "$#" -eq 3 || { echo 'Usage: sh examples/threshold-transfer/score.sh CORPUS_DIR [ORIGINAL.jsonl CANDIDATE.jsonl]' >&2; exit 2; }
dir=examples/threshold-transfer
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
trap 'exit 1' HUP INT TERM
corpus=$tmp/corpus
mkdir "$corpus"
cat < "$1/index.jsonl" > "$corpus/index.jsonl"
cat < "$1/inputs.jsonl" > "$corpus/inputs.jsonl"
prior=$tmp/calibration.json
cat examples/release-trial/results.json > "$prior"
test "$(openssl dgst -sha256 "$prior" | awk '{print $NF}')" = 758dc0dc5bb0934518b9161bac3e5ab2ac108b1dde1b77b930644042ca69356d
sh examples/release-trial/check-panel.sh examples/threshold-transfer/cases.tsv 3 "$corpus"
jq -c '{id,split:"transfer",family:.project,expected:(if .direction=="repair" then "CLEAN" else "CONCERN" end)}' "$corpus/index.jsonl" > "$tmp/labels"
test "$(wc -l < "$tmp/labels")" -eq 16
test "$(wc -l < "$corpus/inputs.jsonl")" -eq 48
if test "$#" -eq 1; then
    for model in onejev onejev1.6; do
        gzip -dc "$dir/$model.jsonl.gz" > "$tmp/receipts"
        sh tools/check_receipts.sh "$tmp/receipts"
        jq -cn --slurpfile inputs "$corpus/inputs.jsonl" --slurpfile receipts "$tmp/receipts" '
            if ($receipts|length) != 48 then error("missing receipts") else
            range(0;48) as $i | $receipts[$i] + {input:($inputs[$i] | {context,rule_excerpt,change_excerpt})} end' > "$tmp/$model"
    done
else
    cat < "$2" > "$tmp/onejev"
    cat < "$3" > "$tmp/onejev1.6"
fi
original=$tmp/onejev candidate=$tmp/onejev1.6
sh tools/check_receipts.sh "$original" "$candidate"

for model in onejev onejev1.6; do
    case "$model" in
        onejev) file=$original key=original_p_concern ;;
        onejev1.6) file=$candidate key=candidate_p_concern ;;
    esac
    test "$(wc -l < "$file")" -eq 48
    threshold=$(jq -er --arg key "$key" '
        [.cases[] | select(.view == "execution")] as $cal |
        [$cal[] | select(.direction == "repair") | .[$key]] as $repairs |
        [$cal[] | select(.direction == "reverse") | .[$key]] as $reverses |
        if ($repairs|length) == 6 and ($reverses|length) == 6 and ($repairs|max) < ($reverses|min)
        then (($repairs|max) + ($reverses|min)) / 2 else error("invalid calibration set") end' "$prior")
    for view in 0 1 2; do
        awk -v view="$view" '(NR-1)%3==view' "$corpus/inputs.jsonl" > "$tmp/input"
        awk -v view="$view" '(NR-1)%3==view' "$file" > "$tmp/answer"
        build/score-quality --model "$model" --text-threshold "$threshold" "$tmp/labels" "$tmp/input" "$tmp/answer" aml/prepare.aml >> "$tmp/$model-scores"
    done
done

jq -n --slurpfile index "$corpus/index.jsonl" --slurpfile inputs "$corpus/inputs.jsonl" \
    --slurpfile old "$original" --slurpfile new "$candidate" \
    --slurpfile old_scores "$tmp/onejev-scores" --slurpfile new_scores "$tmp/onejev1.6-scores" -f "$dir/score.jq"
