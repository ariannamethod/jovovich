#!/bin/sh
# Render the arguments for Liquid's upstream system_one(state, questions).
set -eu
test "$#" = 1 || { echo 'Usage: sh examples/voice-pilot/d1-requests.sh THRESHOLD_CORPUS' >&2; exit 2; }
dir=examples/threshold-transfer
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
trap 'exit 1' HUP INT TERM
gzip -dc "$dir/onejev.jsonl.gz" > "$tmp/receipts"
jq -cn --slurpfile index "$1/index.jsonl" --slurpfile inputs "$1/inputs.jsonl" --slurpfile answer "$tmp/receipts" '
  if ($index|length)!=16 or ($inputs|length)!=48 or ($answer|length)!=48 then error("incomplete transfer panel") else . end |
  range(0;16) as $j | $index[$j] as $case | ($j*3) as $i |
  if $inputs[$i].context!=$inputs[$i+1].context or $inputs[$i].context!=$inputs[$i+2].context or
     $answer[$i].execution.boundary_view.prompt_sha256!=$answer[$i+1].execution.boundary_view.prompt_sha256 or
     $answer[$i+1].execution.trace_witness.differing!=0 or $answer[$i+1].execution.trace_witness.observation!=null or
     $answer[$i+2].execution.trace_witness.differing!=1 then error("unexpected witness policy") else . end |
  (0,2) as $which | $answer[$i+$which] as $a | $inputs[$i+$which] as $in |
  if $a.id!=$case.id or $in.id!=$case.id or $a.source!=$case.source or $in.source!=$case.source or
     $a.execution.boundary_view.code!=null then error("source binding") else . end |
  {"CONCERN":"The proposed change violates a stated rule or requirement.",
   "CLEAN":"The proposed change satisfies the stated rules and requirements."} as $criteria |
  ("concern-first","clean-first") as $order |
  {project:$case.project,pr:$case.pr,direction:$case.direction,view:(if $which==0 then "source" else "witness" end),
   order:$order,input_sha256:$a.execution.input_sha256,
   state:($in.context + (if $which==0 then "" else "\n"+$a.execution.trace_witness.observation end)),
   questions:{review:{type:"choice",instructions:$a.question,
      criteria:(if $order=="concern-first" then $criteria else ($criteria|to_entries|reverse|from_entries) end)}}}'
