#!/bin/sh
# Run from the JOVOVICH checkout; repos contains owner/name checkouts.
set -eu
export GIT_NO_REPLACE_OBJECTS=1
test "$#" -eq 2 || test "$#" -eq 3 || { echo 'Usage: sh examples/threshold-transfer/corpus.sh REPOS NEW_OUTPUT_DIR [PROJECT_PR_TSV]' >&2; exit 2; }
repos=$1 out=$2 dir=examples/threshold-transfer
# The optional panel lists project and PR in its first two tab-separated columns.
pairs=8
panel=${3-}
if test "$#" -eq 3; then
    pairs=$(awk 'NF {n++} END {print n+0}' < "$panel")
    test "$pairs" -gt 0 || { echo 'Empty project/PR panel' >&2; exit 1; }
fi
mkdir "$out"
: > "$out/inputs.jsonl"
: > "$out/index.jsonl"
while read -r mode slug pr fixed file rules first last; do
    if test -n "$panel" && ! awk -F '\t' -v project="$slug" -v pr="$pr" '
        $1 == project && $2 == pr {found=1} END {exit !found}' "$panel"; then continue; fi
    repo=$repos/$slug
    parent=$fixed^1
    for direction in repair reverse; do
        case "$direction" in repair) base=$parent head=$fixed ;; reverse) base=$fixed head=$parent ;; esac
        build/jovovich-pack "$repo" "$base" "$head" "$rules" "$file" "$first" "$last" > "$out/source"
        build/jovovich-replay probe "$repo" "$dir/driver.sh" "-$mode" < "$out/source" > "$out/shared"
        build/jovovich-replay probe "$repo" "$dir/driver.sh" "$mode" < "$out/source" > "$out/witness"
        jq -es --arg direction "$direction" '
            map(.trace_evidence.runs | if length == 1 then .[0] else error("run count") end) |
            .[0] as $s | .[1] as $w | $s.base == $s.head and $s.head == $s.required and
            $s.mode == -$w.mode and $w.base != $w.head and
            (($w.head == $w.required) == ($direction == "repair")) and
            (($w.base == $w.required) == ($direction == "reverse"))' "$out/shared" "$out/witness" > /dev/null
        jq -cs --arg project "$slug" --argjson pr "$pr" --arg direction "$direction" '
            {project:$project,pr:$pr,direction:$direction,id:.[0].id,source:.[0].source,
             shared:.[0].trace_evidence.runs[0],witness:.[1].trace_evidence.runs[0]}' \
            "$out/shared" "$out/witness" >> "$out/index.jsonl"
        cat "$out/source" "$out/shared" "$out/witness" >> "$out/inputs.jsonl"
    done
done < "$dir/cases.tsv"
jq -es --argjson pairs "$pairs" 'length == 2*$pairs and (group_by(.witness.mode) | length == $pairs and all(.[];
    length == 2 and .[0].source.rules_sha256 == .[1].source.rules_sha256 and
    .[0].witness.base == .[1].witness.head and .[0].witness.head == .[1].witness.base and
    .[0].shared == .[1].shared and .[0].witness.required == .[1].witness.required))' "$out/index.jsonl" > /dev/null
rm "$out/source" "$out/shared" "$out/witness"
