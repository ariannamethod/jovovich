# Authenticate labels using the preregistered repair commits and executed
# inputs before any score is computed. Each roster entry has both directions.
def matches($row; $case; $repair; $inputs):
  $row.source as $s | $inputs[-1].trace_evidence.runs as $runs |
  ($row.direction == (if $repair then "repair" else "reverse" end)) and
  $row.project == $case[1] and $row.pr == ($case[2]|tonumber) and
  (if $repair then $s.head_commit else $s.base_commit end) == $case[3] and
  $s.rules_path == $case[5] and $s.rule_first_line == ($case[6]|tonumber) and
  $s.rule_last_line == ($case[7]|tonumber) and
  all($inputs[]; .file == $case[4] and .source == $s and .id == $row.id) and
  ($views == 1 or $inputs[0].trace_evidence == null) and
  ($runs|length) == 1 and $runs[0] == ($row.run // $row.witness) and
  $runs[0].mode == ($case[0]|tonumber) and ($runs[0].base != $runs[0].head) and
  (($runs[0].head == $runs[0].required) == $repair) and
  (($runs[0].base == $runs[0].required) == ($repair|not)) and
  ($views < 3 or ($inputs[1].trace_evidence.runs == [$row.shared] and
    $row.shared.mode == (-$runs[0].mode) and $row.shared.head == $row.shared.required and
    $row.shared.base == $row.shared.required));

($roster | split("\n") | map(select(length>0) | split("\t"))) as $cases |
if ($index|length) == 2*($cases|length) and ($inputs|length) == $views*($index|length) and
   all(range(0; $cases|length); . as $n | (2*$n) as $i |
     $index[$i] as $fix | $index[$i+1] as $undo |
     $fix.source.base_commit == $undo.source.head_commit and
     $fix.source.head_commit == $undo.source.base_commit and
     $fix.source.rules_sha256 == $undo.source.rules_sha256 and
     matches($fix; $cases[$n]; true; $inputs[$i*$views:($i+1)*$views]) and
     matches($undo; $cases[$n]; false; $inputs[($i+1)*$views:($i+2)*$views]))
then true else error("corpus labels, executed inputs or Git sources differ from the frozen panel") end
