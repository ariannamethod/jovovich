def require($ok; $message): if $ok then . else error($message) end;

def gate_ok($view; $input; $answer; $case):
  $input.trace_evidence as $e | $answer.execution.trace_witness as $w |
  if $view == "source" then $e == null and $w == null
  elif $view == "shared" then
    $e.metric == "text" and $e.runs == [$case.shared] and $w.differing == 0 and ($w|has("selected_mode")|not)
  else
    $e.metric == "text" and $e.runs == [$case.witness] and $w.differing == 1 and $w.selected_mode == $case.witness.mode
  end;

def vote($answers; $scores; $i; $v; $j; $case):
  $answers[$i] as $a | $answers[$i-$v] as $source | $scores[$v].cases[$j] as $s |
  require($a.source == $case.source and $a.id == $case.id and $s.id == $case.id and
          $s.probabilities == $a.choice.probabilities and $s.raw_predicted == $a.choice.verdict and
          $s.threshold_applied == ($v == 2); "unbound score or unexpected threshold application") |
  require($v == 2 or $s.predicted == $s.raw_predicted; "off-scope decision changed") |
  require($v != 1 or ($a.choice == $source.choice and
          $a.execution.boundary_view.prompt_sha256 == $source.execution.boundary_view.prompt_sha256);
          "common input changed the prompt or vote") |
  {p_concern:$s.probabilities.CONCERN, raw:$s.raw_predicted, fitted:$s.predicted};

def row($i):
  ($i % 3) as $v | ($i/3|floor) as $j | $index[$j] as $case |
  ["source","shared","witness"][$v] as $view | $old[$i].execution as $a | $new[$i].execution as $b |
  require($inputs[$i].id == $case.id and $inputs[$i].source == $case.source and
          $a.input_sha256 == $b.input_sha256 and $a.boundary_view == $b.boundary_view and
          $a.boundary_view.code == null and ($a.boundary_view.prompt_sha256|length) == 64 and
          $a.trace_witness == $b.trace_witness and $a.readout_sha256 == null and $b.readout_sha256 == null and
          gate_ok($view; $inputs[$i]; $old[$i]; $case); "different inputs, prompts, witnesses or readout") |
  {project:$case.project, pr:$case.pr, direction:$case.direction, view:$view,
   base_commit:$case.source.base_commit, head_commit:$case.source.head_commit,
   input_sha256:$a.input_sha256, prompt_sha256:$a.boundary_view.prompt_sha256,
   original:vote($old; $old_scores; $i; $v; $j; $case), candidate:vote($new; $new_scores; $i; $v; $j; $case)};

def correct($model; $policy):
  .[$model][$policy] == (if .direction == "repair" then "CLEAN" else "CONCERN" end);

def tally($model; $policy):
  group_by([.project,.pr]) as $pairs |
  {both_correct:([$pairs[] | select(all(.[]; correct($model;$policy)))]|length),
   correct:([.[] | select(correct($model;$policy))]|length),
   false_alarms:([.[] | select(.direction == "repair" and (correct($model;$policy)|not))]|length),
   misses:([.[] | select(.direction == "reverse" and (correct($model;$policy)|not))]|length),
   reverse_ranked_higher:([$pairs[] | (map(select(.direction == "reverse"))[0][$model].p_concern) as $reverse |
                           select($reverse > (map(select(.direction == "repair"))[0][$model].p_concern))]|length)};

def summary($rows; $model; $policy):
  ["source","shared","witness"] | map(. as $view |
    {key:$view,value:([$rows[] | select(.view == $view)] | tally($model;$policy))}) | from_entries;

require(($index|length) == 16 and ($inputs|length) == 48 and ($old|length) == 48 and ($new|length) == 48 and
        ([$index[]|.id]|unique|length) == 16 and ($index|group_by([.project,.pr])|length) == 8 and
        ($index|group_by([.project,.pr])|all(.[]; (map(.direction)|sort) == ["repair","reverse"])) and
        ($old_scores|length) == 3 and ($new_scores|length) == 3; "incomplete or duplicated panel") |
# Subtraction compares the binary values despite equivalent decimal spellings in jq 1.7.
require(all($old_scores[]; .text_threshold - 0.4864169955253601 == 0) and
        all($new_scores[]; .text_threshold - 0.3906702995300293 == 0) and
        ([$old_scores[], $new_scores[] | .threshold_policy_sha256]|unique|length) == 1; "operating point changed") |
[range(0;48) | row(.)] as $rows |
summary($rows; "original"; "raw") as $o | summary($rows; "candidate"; "raw") as $n |
summary($rows; "original"; "fitted") as $of | summary($rows; "candidate"; "fitted") as $nf |
{original_raw:$o, original_fitted:$of, candidate_raw:$n, candidate_fitted:$nf,
 original_text_threshold:$old_scores[0].text_threshold, candidate_text_threshold:$new_scores[0].text_threshold,
 threshold_policy_sha256:$old_scores[0].threshold_policy_sha256,
 criteria:{seven_pairs:($nf.witness.both_correct >= 7), improves_on_own_raw:($nf.witness.both_correct > $n.witness.both_correct),
           matches_original_pairs:($nf.witness.both_correct >= $o.witness.both_correct),
           no_extra_false_alarms:($nf.witness.false_alarms <= $o.witness.false_alarms), no_extra_misses:($nf.witness.misses <= $o.witness.misses),
           off_scope_decisions_equal:($o.source == $of.source and $n.source == $nf.source and $o.shared == $of.shared and $n.shared == $nf.shared)},
 cases:$rows} | . + {qualifies_1_6_text_threshold:(.criteria | all(.[];.))}
