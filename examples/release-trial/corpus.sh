#!/bin/sh
# Run from the JOVOVICH repository root. Source trees are read-only.
set -eu
export GIT_NO_REPLACE_OBJECTS=1
test "$#" -eq 3 || { echo 'Usage: sh examples/release-trial/corpus.sh INIH_REPO NODE_SEMVER_REPO NEW_OUTPUT_DIR' >&2; exit 2; }
ini=$1 semver=$2 out=$3
mkdir "$out"
runner=examples/release-trial/runner.sh
: > "$out/inputs.jsonl"
: > "$out/index.jsonl"
while read -r mode project pr fixed file rules first last; do
    case "$project" in inih) repo=$ini ;; node-semver) repo=$semver ;; *) exit 1 ;; esac
    parent=$(git -C "$repo" rev-parse --verify "$fixed^1")
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
done <<'CASES'
1 inih 140 bd798c53775a4aefaf8ac42091bface3e876d190 ini.c ini.h 112 120
2 inih 188 23acf2dd5af5287b0f170908c607560ab3995dae ini.c ini.h 78 80
3 inih 197 498f34b78610cf9e42197d22730c91f942431ea4 ini.c ini.h 78 80
4 node-semver 867 5f3ca133e040210b6ea80c350a1d61d9da02e722 ranges/subset.js README.md 531 532
5 node-semver 870 bea6028694a75e840f48b288ac019e9644cfe6e8 classes/semver.js README.md 237 242
6 node-semver 872 046da7f527cc72a482b5dea8cb59392be65bf186 classes/range.js README.md 360 360
CASES
jq -es 'length == 12' "$out/index.jsonl" >/dev/null
jq -es 'group_by(.run.mode) | length == 6 and all(.[]; length == 2 and
    .[0].source.rules_sha256 == .[1].source.rules_sha256 and
    .[0].run.base == .[1].run.head and .[0].run.head == .[1].run.base and
    .[0].run.required == .[1].run.required)' "$out/index.jsonl" >/dev/null
rm "$out/source" "$out/witness"
