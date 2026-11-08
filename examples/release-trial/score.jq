def concern: .choice.probabilities.CONCERN;

def fresh($i):
  $original[$i] as $old | $candidate[$i] as $new | $index[($i / 2 | floor)] as $case |
  if ($old.source == $case.source and $new.source == $case.source and
      $old.execution.boundary_view.code == null and $new.execution.boundary_view.code == null and
      (($i % 2 == 1) == ($new.execution.trace_witness != null))) then
    {project:$case.project, pr:$case.pr, direction:$case.direction,
     view:(if $i % 2 == 0 then "source" else "execution" end),
     base_commit:$case.source.base_commit, head_commit:$case.source.head_commit,
     input_sha256:$old.execution.input_sha256, prompt_sha256:$old.execution.boundary_view.prompt_sha256,
     original_p_concern:($old|concern), candidate_p_concern:($new|concern)}
  else error("fresh case binding or presentation mismatch") end;

def tally($cases; $p; $threshold; $view):
  [$cases[] | select(.view == $view) | . + {flag:(.[$p] >= $threshold)}] |
  {both_correct:(group_by([.project,.pr]) | map(select(length == 2 and all(.[]; .flag == (.direction == "reverse")))) | length),
   correct:(map(select(.flag == (.direction == "reverse"))) | length),
   false_alarms:(map(select(.direction == "repair" and .flag)) | length),
   misses:(map(select(.direction == "reverse" and (.flag|not))) | length)};

def point($cases; $p; $threshold; $controls; $anchor):
  {threshold:$threshold, source:tally($cases;$p;$threshold;"source"),
   execution:tally($cases;$p;$threshold;"execution"),
   controls_correct:([$controls.cases[] | select((.probabilities.CONCERN >= $threshold) == (.expected == "CONCERN"))] | length),
   anchor_p_clean:$anchor.choice.probabilities.CLEAN};

if ($original|length) != 57 or ($candidate|length) != 57 or ($index|length) != 12 or
  (all(range(0;57); . as $i | $original[$i].execution as $a | $candidate[$i].execution as $b |
    $a.input_sha256 == $b.input_sha256 and $a.boundary_view == $b.boundary_view and
    $a.trace_witness == $b.trace_witness and $a.readout_sha256 == null and $b.readout_sha256 == null) | not)
then error("incomplete run or different inputs, AML prompts, evidence or readout") else . end |
[range(0;24) | fresh(.)] as $cases |
point($cases;"original_p_concern";0.5;$oldcontrol[0];$original[56]) as $old |
point($cases;"original_p_concern";0.6;$oldcontrol[0];$original[56]) as $old60 |
point($cases;"candidate_p_concern";0.5;$newcontrol[0];$candidate[56]) as $new |
{original_050:$old, original_060:$old60, candidate_050:$new,
 criteria:{
  execution_pairs:($new.execution.both_correct >= ([5,$old.execution.both_correct,$old60.execution.both_correct]|max)),
  execution_misses:($new.execution.misses <= ([$old.execution.misses,$old60.execution.misses]|min)),
  source_correct:($new.source.correct + 1 >= ([$old.source.correct,$old60.source.correct]|max)),
  source_misses:($new.source.misses <= ([$old.source.misses,$old60.source.misses]|min) + 1),
  controls:($new.controls_correct == 32), anchor:($new.anchor_p_clean > 0.5)},
 cases:$cases} | . + {promote:(.criteria|all(.[];.))}
