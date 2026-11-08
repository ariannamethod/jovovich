#!/bin/sh
# Verify native receipts for each presentation before applying the frozen thresholds.
set -eu
test "$#" -eq 1 || test "$#" -eq 3 || { echo 'Usage: sh examples/release-trial/score.sh CORPUS_DIR [ORIGINAL.jsonl CANDIDATE.jsonl]' >&2; exit 2; }
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
trap 'exit 1' HUP INT TERM
corpus=$tmp/corpus
mkdir "$corpus"
cat < "$1/index.jsonl" > "$corpus/index.jsonl"
cat < "$1/inputs.jsonl" > "$corpus/inputs.jsonl"
sh examples/release-trial/check-panel.sh examples/release-trial/cases.tsv 2 "$corpus"
jq -c '{id,split:"transfer",family:.project,expected:(if .direction=="repair" then "CLEAN" else "CONCERN" end)}' "$corpus/index.jsonl" > "$tmp/labels"
test "$(wc -l < "$tmp/labels")" -eq 12
build/trace-corpus expected > "$tmp/control-labels"
build/trace-corpus paired > "$tmp/controls"
if test "$#" -eq 1; then
    # The archive omits duplicated source excerpts. Restore them from the
    # regenerated inputs, whose byte hashes the native verifier checks below.
    cat "$corpus/inputs.jsonl" "$tmp/controls" examples/run-selection/git-input.jsonl > "$tmp/all"
    for profile in onejev onejev1.6; do
        gzip -dc "examples/release-trial/$profile.jsonl.gz" > "$tmp/receipts"
        sh tools/check_receipts.sh "$tmp/receipts"
        jq -cn --slurpfile inputs "$tmp/all" --slurpfile receipts "$tmp/receipts" '
            if ($inputs|length) != 57 or ($receipts|length) != 57 then error("missing rows") else
            range(0;57) as $i | $receipts[$i] + {input:($inputs[$i] | {context,rule_excerpt,change_excerpt})} end' > "$tmp/$profile"
    done
else
    cat < "$2" > "$tmp/onejev"
    cat < "$3" > "$tmp/onejev1.6"
fi
original=$tmp/onejev candidate=$tmp/onejev1.6
sh tools/check_receipts.sh "$original" "$candidate"
for profile in onejev onejev1.6; do
    case "$profile" in onejev) file=$original ;; onejev1.6) file=$candidate ;; esac
    test "$(wc -l < "$file")" -eq 57
    for parity in 1 0; do
        awk -v p="$parity" 'NR<=24 && NR%2==p' "$corpus/inputs.jsonl" > "$tmp/input"
        awk -v p="$parity" 'NR<=24 && NR%2==p' "$file" > "$tmp/answer"
        build/score-quality --model "$profile" "$tmp/labels" "$tmp/input" "$tmp/answer" aml/prepare.aml > "$tmp/score"
    done
    sed -n '25,56p' "$file" > "$tmp/answers"
    build/score-quality --model "$profile" "$tmp/control-labels" "$tmp/controls" "$tmp/answers" aml/prepare.aml > "$tmp/$profile-controls"
    sed -n '57p' "$file" > "$tmp/anchor"
    build/jovovich-report --model "$profile" examples/run-selection/git-input.jsonl "$tmp/anchor" --json > "$tmp/report"
done
jq -n --slurpfile index "$corpus/index.jsonl" --slurpfile original "$original" \
    --slurpfile candidate "$candidate" --slurpfile oldcontrol "$tmp/onejev-controls" \
    --slurpfile newcontrol "$tmp/onejev1.6-controls" -f examples/release-trial/score.jq
