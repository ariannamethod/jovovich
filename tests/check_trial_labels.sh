#!/bin/sh
# Exercise the scorer's repair labels and PR identities independent of model output.
set -eu
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
trap 'exit 1' HUP INT TERM
printf '1\tupstream/test\t7\tfixed\tunit.c\tRULES\t2\t3\n' > "$work/roster"
jq -cn '("repair","reverse") as $dir | ($dir=="repair") as $fix |
  {direction:$dir,project:"upstream/test",pr:7,id:$dir,source:{
    head_commit:(if $fix then "fixed" else "prior" end),base_commit:(if $fix then "prior" else "fixed" end),
    rules_path:"RULES",rules_sha256:"same",rule_first_line:2,rule_last_line:3},
   witness:{mode:1,head:(if $fix then "ok" else "bad" end),base:(if $fix then "bad" else "ok" end),required:"ok"},
   shared:{mode:-1,head:"ok",base:"ok",required:"ok"}}' > "$work/genuine"
check_semantics() {
    jq -en --rawfile roster "$work/roster" --argjson views "$views" --slurpfile index "$work/index.jsonl" \
        --slurpfile inputs "$work/inputs.jsonl" -f examples/release-trial/check-panel.jq > /dev/null
}
reject() {
    if check_semantics 2>/dev/null; then
        echo "Accepted changed trial $1 ($views views)" >&2; exit 1
    fi
}
for views in 1 2 3; do
    cp "$work/genuine" "$work/index.jsonl"
    jq -c --argjson n "$views" '. as $r | {file:"unit.c",id,source} as $source |
        if $n>=2 then $source else empty end,
        if $n==3 then $source+{trace_evidence:{runs:[$r.shared]}} else empty end,
        $source+{trace_evidence:{runs:[$r.witness]}}' "$work/genuine" > "$work/inputs.jsonl"
    check_semantics
    for alteration in '.direction=(if .direction=="repair" then "reverse" else "repair" end)' '.pr=8' '.witness.required="bad"'; do
        jq -c "$alteration" "$work/genuine" > "$work/index.jsonl"
        reject "$alteration"
    done
done
for invalid in '{"vote":0,"vote":1}' '{"p":NaN}' '{"p":Infinity}' '{"p":+1}' '{"p":01}' '{"p":.5}' '{"p":1.}'; do
    printf '%s\n' "$invalid" > "$work/invalid"
    if sh tools/check_receipts.sh "$work/invalid" 2>/dev/null; then
        echo "Accepted invalid receipt: $invalid" >&2; exit 1
    fi
done
