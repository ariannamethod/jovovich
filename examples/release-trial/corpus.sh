#!/bin/sh
# Run from the JOVOVICH repository root. Source trees are read-only.
set -eu
export GIT_NO_REPLACE_OBJECTS=1
test "$#" -eq 3 || test "$#" -eq 4 || { echo 'Usage: sh examples/release-trial/corpus.sh INIH_REPO NODE_SEMVER_REPO NEW_OUTPUT_DIR [PROJECT_PR_TSV]' >&2; exit 2; }
ini=$1 semver=$2 out=$3
# The optional panel lists project and PR in its first two tab-separated columns.
pairs=6
panel=${4-}
if test "$#" -eq 4; then
    pairs=$(awk 'NF {n++} END {print n+0}' < "$panel")
    test "$pairs" -gt 0 || { echo 'Empty project/PR panel' >&2; exit 1; }
fi
mkdir "$out"
runner=examples/release-trial/runner.sh
: > "$out/inputs.jsonl"
: > "$out/index.jsonl"
while read -r mode project pr fixed file rules first last; do
    if test -n "$panel" && ! awk -F '\t' -v project="$project" -v pr="$pr" '
        $1 == project && $2 == pr {found=1} END {exit !found}' "$panel"; then continue; fi
    case "$project" in inih) repo=$ini ;; node-semver) repo=$semver ;; *) exit 1 ;; esac
    parent=$fixed^1
    for direction in repair reverse; do
        case "$direction" in repair) base=$parent head=$fixed ;; reverse) base=$fixed head=$parent ;; esac
        build/jovovich-pack "$repo" "$base" "$head" "$rules" "$file" "$first" "$last" > "$out/source"
        build/jovovich-replay probe "$repo" "$runner" "$mode" < "$out/source" > "$out/witness"
        jq -e --arg dir "$direction" '.trace_evidence.runs | length == 1 and
            (.[0] | .base != .head and ((.head == .required) == ($dir == "repair")) and
                ((.base == .required) == ($dir == "reverse")))' "$out/witness" >/dev/null
        jq -c --arg project "$project" --argjson pr "$pr" --arg dir "$direction" \
            '{project:$project,pr:$pr,direction:$dir,id,source,run:.trace_evidence.runs[0]}' "$out/witness" >> "$out/index.jsonl"
        cat "$out/source" "$out/witness" >> "$out/inputs.jsonl"
    done
done < examples/release-trial/cases.tsv
jq -es --argjson pairs "$pairs" 'length == 2*$pairs' "$out/index.jsonl" >/dev/null
jq -es --argjson pairs "$pairs" 'group_by(.run.mode) | length == $pairs and all(.[]; length == 2 and
    .[0].source.rules_sha256 == .[1].source.rules_sha256 and
    .[0].run.base == .[1].run.head and .[0].run.head == .[1].run.base and
    .[0].run.required == .[1].run.required)' "$out/index.jsonl" >/dev/null
rm "$out/source" "$out/witness"
