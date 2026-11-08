#!/bin/sh
# Run from JOVOVICH with its pinned submodules built.
set -eu
test "$#" = 1 || { echo 'Usage: sh examples/voice-pilot/method.sh NEW_DIR' >&2; exit 2; }
out=$1
mkdir "$out"
dir=examples/voice-pilot
while read -r mode slug pr fixed file rules first last; do
    case "$slug" in
        ariannamethod/notorch) repo=deps/notorch ;;
        ariannamethod/ariannamethod.ai) repo=deps/aml ;;
        ariannamethod/jovovich) repo=. ;;
        *) exit 2 ;;
    esac
    parent=$fixed^1
    for direction in repair reverse; do
        case "$direction" in repair) base=$parent head=$fixed ;; reverse) base=$fixed head=$parent ;; esac
        build/jovovich-pack "$repo" "$base" "$head" "$rules" "$file" "$first" "$last" > "$out/source"
        build/jovovich-replay probe "$repo" "$dir/probe.sh" "$mode" < "$out/source" > "$out/witness"
        jq -e --arg d "$direction" '.trace_evidence.runs[0] | .head != .base and
            ((.head == .required) == ($d == "repair")) and ((.base == .required) == ($d == "reverse"))' "$out/witness" >/dev/null
        jq -c --arg project "$slug" --argjson pr "$pr" --arg direction "$direction" \
            '{id,project:$project,pr:$pr,direction:$direction,source,run:.trace_evidence.runs[0]}' "$out/witness" >> "$out/index.jsonl"
        cat "$out/witness" >> "$out/inputs.jsonl"
    done
done < "$dir/method.tsv"
jq -se 'length == 6 and (group_by(.project)|length == 3 and all(.[]; length==2 and
    .[0].source.rules_sha256==.[1].source.rules_sha256 and .[0].run.base==.[1].run.head and .[0].run.head==.[1].run.base))' "$out/index.jsonl" >/dev/null
rm "$out/source" "$out/witness"
