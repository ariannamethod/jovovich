#!/bin/sh
# Compile the audition material from native review receipts, keeping targets separate in each row.
set -eu
test "$#" = 5 || { echo 'Usage: sh examples/voice-pilot/packets.sh UPSTREAM_DIR UPSTREAM_ANSWERS METHOD_DIR METHOD_ANSWERS NEW_OUTPUT_DIR' >&2; exit 2; }
out=$5
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
trap 'exit 1' HUP INT TERM
up=$tmp/up method=$tmp/method fresh=$tmp/fresh old=$tmp/old
mkdir "$up" "$method"
cat < "$1/index.jsonl" > "$up/index.jsonl"
cat < "$1/inputs.jsonl" > "$up/inputs.jsonl"
cat < "$3/index.jsonl" > "$method/index.jsonl"
cat < "$3/inputs.jsonl" > "$method/inputs.jsonl"
cat < "$2" > "$old"
cat < "$4" > "$fresh"
sh tools/check_receipts.sh "$old" "$fresh"
dir=examples/voice-pilot
sh examples/release-trial/check-panel.sh examples/threshold-transfer/cases.tsv 3 "$up"
sh examples/release-trial/check-panel.sh "$dir/method.tsv" 1 "$method"
mkdir "$out"
awk '(NR-1)%3==2' "$up/inputs.jsonl" > "$out/up-input"
awk '(NR-1)%3==2' "$old" > "$out/up-answer"
for split in train heldout; do
    case "$split" in
        train) idx=$up/index.jsonl inp=$out/up-input ans=$out/up-answer ;;
        heldout) idx=$method/index.jsonl inp=$method/inputs.jsonl ans=$fresh ;;
    esac
    jq -c '{id,split:"transfer",family:.project,expected:(if .direction=="repair" then "CLEAN" else "CONCERN" end)}' "$idx" > "$out/labels"
    build/score-quality "$out/labels" "$inp" "$ans" aml/prepare.aml > "$out/native-score"
    jq -cn --arg split "$split" --rawfile refs "$dir/lines.tsv" --slurpfile idx "$idx" --slurpfile inp "$inp" --slurpfile ans "$ans" '
      ($refs | split("\n") | map(select(length>0) | split("\t") | select(.[0]==$split))) as $ref |
      range(0; $idx|length) as $i | $idx[$i] as $c | $ans[$i] as $a |
      $ref[] | select(.[1]==$c.project and (.[2]|tonumber)==$c.pr) |
      if ($a.id!=$c.id or $a.source!=$c.source or $inp[$i].trace_evidence.runs[0] != ($c.run//$c.witness) or
          $a.execution.trace_witness.differing!=1 or $a.execution.readout_sha256!=null)
      then error("review binding") else
      {id:$c.id, project:$c.project, pr:$c.pr, direction:$c.direction,
       input_sha256:$a.execution.input_sha256, verdict:$a.choice.verdict, probabilities:$a.choice.probabilities,
       state:("File: "+$a.scope.file+"\nProbe: "+.[3]+"\nVerdict: "+$a.choice.verdict+
         "\nP(CONCERN): "+($a.choice.probabilities.CONCERN|tostring)+"\nP(CLEAN): "+($a.choice.probabilities.CLEAN|tostring)+
         "\n"+$a.execution.trace_witness.observation),
       target:(if $c.direction=="repair" then .[4] else .[5] end)} end' > "$out/$split.jsonl"
done
test "$(wc -l < "$out/train.jsonl")" -eq 12 && test "$(wc -l < "$out/heldout.jsonl")" -eq 6
jq -es 'length==18 and (map(.id)|unique|length)==18 and (map(.target)|unique|length)==18' "$out/train.jsonl" "$out/heldout.jsonl" >/dev/null
rm "$out/up-input" "$out/up-answer" "$out/labels" "$out/native-score"
