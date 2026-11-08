#!/bin/sh
# Build the voice training references and the target-free audition from archived native receipts.
set -eu
test "$#" = 1 || { echo 'Usage: sh examples/paired-voice/packets.sh NEW_OUTPUT_DIR' >&2; exit 2; }
out=$1
dir=examples/paired-voice
release=examples/release-trial
mkdir "$out"
jq -cs --rawfile extra "$dir/references.tsv" '
  ($extra | split("\n") | map(select(length>0) | split("\t"))) as $extra |
  .[] as $c |
  ([$extra[] | select(.[0]==$c.project and (.[1]|tonumber)==$c.pr)] | if length==1 then .[0] else error("missing or duplicate references") end) as $r |
  $c | .references=[.target, $r[if .direction=="repair" then 2 else 3 end]] | del(.target)
' examples/voice-pilot/train.jsonl > "$out/train.jsonl"

gzip -dc "$release/onejev.jsonl.gz" > "$out/receipts.jsonl"
jq -cn --slurpfile answers "$out/receipts.jsonl" --slurpfile index "$release/results.json" --rawfile probes "$dir/probes.tsv" '
  $probes | split("\n")[] | select(length>0) | split("\t") as $p |
  $index[0].cases[] | select(.view=="execution" and .project==$p[0] and .pr==($p[1]|tonumber)) as $c |
  ([$answers[] | select(.execution.input_sha256==$c.input_sha256)] | if length==1 then .[0] else error("receipt count") end) as $a |
  if ($a.source.base_commit!=$c.base_commit or $a.source.head_commit!=$c.head_commit or $a.execution.trace_witness.differing!=1
      or $a.execution.trace_witness.prompt_sha256!=$c.prompt_sha256 or $a.choice.probabilities.CONCERN!=$c.original_p_concern)
  then error("review binding") else
  {id:$a.id, project:$c.project, pr:$c.pr, direction:$c.direction, input_sha256:$c.input_sha256,
   base_commit:$c.base_commit, head_commit:$c.head_commit,
   state:("File: "+$a.scope.file+"\nProbe: "+$p[2]+"\nVerdict: "+$a.choice.verdict+
          "\nP(CONCERN): "+($a.choice.probabilities.CONCERN|tostring)+"\nP(CLEAN): "+($a.choice.probabilities.CLEAN|tostring)+
          "\n"+$a.execution.trace_witness.observation)} end
' > "$out/heldout.jsonl"
rm "$out/receipts.jsonl"
jq -nes --slurpfile train "$out/train.jsonl" --slurpfile held "$out/heldout.jsonl" '
  def pairs: group_by([.project,.pr]) | all(.[]; (map(.direction)|sort)==["repair","reverse"]);
  ($train|length)==12 and ($held|length)==8 and ($train|pairs) and ($held|pairs)
  and ([$train[].references[]]|length)==24 and ([$train[].references[]]|unique|length)==24
  and all($train[].references[]; type=="string" and length>0)
  and (([$train[], $held[]] | map(.id) | unique | length)==20)
  and ([$train[].project] as $projects | all($held[]; .project as $p | $projects | index($p)==null))
  and ($held | group_by([.project,.pr]) | all(.[]; .[0].head_commit==.[1].base_commit and .[0].base_commit==.[1].head_commit))
' >/dev/null
