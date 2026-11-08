def require($ok; $why): if $ok then . else error($why) end;
def one($what): require(length == 1; "expected one " + $what) | .[0];
def tsv($width): split("\n") | map(select(length > 0) | split("\t") |
    require(length == $width and all(.[]; length > 0); "malformed author/probe row"));

def whole($min; $max): type == "number" and . == floor and . >= $min and . <= $max;
def janus_instant:
  type == "object" and keys == ["millisecond","schema","second","time_scale","unix_day"]
  and .schema == "janus.instant/1" and .time_scale == "posix"
  and (.unix_day | whole(-2147483648; 2147483647)) and (.second | whole(0; 86399))
  and (.millisecond | whole(0; 999));

# An execution row is identified by the hash of the full reviewed input, not by
# position or by the repair/reverse label. The same id occurs in the source-only views.
def receipt($case; $archive):
  ([$archive[] | select(.execution.input_sha256 == $case.input_sha256)] | one("archived execution")) as $old |
  $old.execution as $e | $e.trace_witness as $w | $model[0] as $m |
  require($old.schema_version == 1 and $old.model == {id:$m.model_id,revision:$m.revision}
      and $e.weights_sha256 == $m.weights_sha256 and $e.tokenizer_sha256 == $m.tokenizer_sha256
      and $e.engine == "NoTorch" and $e.language == "AML" and $e.arithmetic == $m.arithmetic
      and $e.readout_sha256 == null; "not the original unadapted model") |
  require($old.source.kind == "git" and $old.source.base_commit == $case.base_commit
      and $old.source.head_commit == $case.head_commit and $case.base_commit != $case.head_commit
      and $w.policy == "paired-trace-diff/1" and $w.runs == 1 and $w.differing == 1
      and $w.prompt_sha256 == $case.prompt_sha256 and ($w.observation | type == "string" and length > 0)
      and $old.choice.probabilities.CONCERN == ($case.original.p_concern // $case.original_p_concern)
      and $old.choice.verdict == ($case.original.raw //
        (if $old.choice.probabilities.CONCERN >= $old.choice.probabilities.CLEAN then "CONCERN" else "CLEAN" end));
      "case/receipt mismatch: " + $case.input_sha256) |
  if $live then
    ([$fresh[] | select(.execution.input_sha256 == $case.input_sha256)] | one("live execution")) as $a |
    require(($a.execution.reviewed_at | janus_instant); "invalid live JANUS instant") |
    require(($a | del(.input,.execution.reviewed_at,.execution.boundary_view))
            == ($old | del(.execution.reviewed_at,.execution.boundary_view))
        and (($a.execution | has("boundary_view") | not)
             or (($a.execution.boundary_view | type == "object") and $a.execution.boundary_view == $e.boundary_view))
        and ($a.input | keys) == ["change_excerpt","context","rule_excerpt"]
        and $a.input.context == ("Reviewed file: " + $a.scope.file + "\nRepository rules from the base commit:\n"
            + $a.input.rule_excerpt + "\nChange under review (git diff):\n" + $a.input.change_excerpt);
        "live receipt differs from archived execution: " + $case.input_sha256) | $a
  else $old end;

# Only these six lines enter the voice state. References and provenance live outside it.
def packet($c; $a; $probe; $targets):
  $a.choice.probabilities as $p |
  ("File: " + $a.scope.file + "\nProbe: " + $probe + "\nVerdict: " + $a.choice.verdict
   + "\nP(CONCERN): " + ($p.CONCERN|tostring) + "\nP(CLEAN): " + ($p.CLEAN|tostring)
   + "\n" + $a.execution.trace_witness.observation) as $state |
  {id:$a.id,project:$c.project,pr:$c.pr,direction:$c.direction,input_sha256:$c.input_sha256} +
  (if $targets == null then {base_commit:$c.base_commit,head_commit:$c.head_commit,state:$state}
   else {verdict:$a.choice.verdict,probabilities:{CONCERN:$p.CONCERN,CLEAN:$p.CLEAN},state:$state,
         references:$targets[if $c.direction == "repair" then 0 else 1 end]} end);

def pair($project; $pr; $probe; $targets; $index; $archive; $view):
  [$index.cases[] | select(.project == $project and .pr == $pr and .view == $view)] as $cases |
  ($cases | sort_by(.direction)) as $ordered |
  require(($ordered | map(.direction)) == ["repair","reverse"]
      and $ordered[0].base_commit == $ordered[1].head_commit
      and $ordered[0].head_commit == $ordered[1].base_commit; "invalid revision pair: " + $project + "#" + ($pr|tostring)) |
  $ordered[] as $c | receipt($c; $archive) as $a | packet($c; $a; $probe; $targets);

($lines | tsv(6) | map(select(.[0] == "train"))) as $author |
($refs | tsv(4)) as $extra |
($probes | tsv(3)) as $blind |
require(($author|length) == 6 and ($extra|length) == 6 and ($blind|length) == 4
    and (($live|not) or ($fresh|length) == 20); "incomplete corpus") |
{train:[$author[] as $r | ([$extra[] | select(.[0:2] == $r[1:3])] | one("second reading")) as $s |
        pair($r[1]; ($r[2]|tonumber); $r[3]; [[$r[4],$s[2]],[$r[5],$s[3]]]; $trainIndex[0]; $trainVotes; "witness")],
 heldout:[$blind[] as $r | pair($r[0]; ($r[1]|tonumber); $r[2]; null; $heldIndex[0]; $heldVotes; "execution")]} |
require(([.train[],.heldout[]] | map(.id) | unique | length) == 20
    and ([.train[],.heldout[]] | map(.input_sha256) | unique | length) == 20
    and ([.train[].references[]] | unique | length) == 24
    and ([.train[].project] as $projects | all(.heldout[]; .project as $p | ($projects|index($p)) == null));
    "duplicate case, reference or shared project")
