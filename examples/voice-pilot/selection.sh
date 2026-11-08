#!/bin/sh
# Build both letter orders from the published ordinary file decisions.
set -eu
test "$#" = 1 || { echo 'Usage: sh examples/voice-pilot/selection.sh NEW_DIR' >&2; exit 2; }
out=$1
mkdir "$out"
dir=examples/voice-pilot
for trial in threshold-transfer release-trial; do
    gzip -dc "examples/$trial/onejev.jsonl.gz" >> "$out/receipts"
done
jq -cn --rawfile refs "$dir/lines.tsv" --rawfile alternatives "$dir/selection-lines.tsv" \
  --slurpfile receipts "$out/receipts" --slurpfile t examples/threshold-transfer/results.json \
  --slurpfile u examples/release-trial/results.json '
  ($refs | split("\n") | map(split("\t")|select(.[0]=="train"))) as $train |
  ($t[0].cases+$u[0].cases | map(select(.view=="witness" or .view=="execution"))) as $index |
  $alternatives|split("\n")[]|select(length>0)|split("\t") as $line |
  ($train|map(select(.[1]==$line[0] and .[2]==$line[1]))|first) as $known |
  (if $known then {split:"train",lines:$known[4:6]} else {split:"heldout",lines:$line[4:6]} end) as $style |
  $index[] | select(.project==$line[0] and .pr==($line[1]|tonumber)) as $c |
  ($receipts|map(select(.execution.input_sha256==$c.input_sha256 and .execution.trace_witness.differing==1))) as $matches |
  (if ($matches|length)!=1 or ($style.lines|length)!=2 then error("scene binding") else $matches[0] end) as $a |
  (if $c.direction=="repair" then 0 else 1 end) as $i |
  ("taste","grounding") as $axis |
  ($style.lines[$i]) as $preferred |
  (if $axis=="taste" then $line[2+$i] else $style.lines[1-$i] end) as $other |
  ("A","B") as $target |
  (if $target=="A" then [$preferred,$other] else [$other,$preferred] end) as $options |
  {review_id:$a.id,input_sha256:$a.execution.input_sha256,project:$c.project,pr:$c.pr,direction:$c.direction,
   split:$style.split,axis:$axis,target:$target,options:$options,
   state:("File: "+$a.scope.file+"\nVerdict: "+$a.choice.verdict+"\n"+$a.execution.trace_witness.observation+
      "\n\nA. "+$options[0]+"\nB. "+$options[1])}' > "$out/rows"
while IFS= read -r row; do
    sha=$(printf '%s\n' "$row"|jq -jr '.state'|openssl dgst -sha256|awk '{print $NF}')
    printf '%s\n' "$row"|jq -c --arg id "$sha" '.+{$id}' >> "$out/all.jsonl"
done < "$out/rows"
for split in train heldout; do
    jq -c --arg split "$split" 'select(.split==$split)' "$out/all.jsonl" > "$out/$split.jsonl"
done
test "$(wc -l < "$out/train.jsonl")" -eq 48
test "$(wc -l < "$out/heldout.jsonl")" -eq 24
jq -es 'length==72 and (map(.id)|unique|length)==72 and
  (group_by(.review_id,.axis)|all(.[];length==2 and .[0].options==(.[1].options|reverse) and
  .[0].target!=.[1].target))' "$out/all.jsonl" >/dev/null
rm "$out/rows" "$out/receipts"
