# Run with jq -n --slurpfile rows RECEIPTS --slurpfile panel THRESHOLD_RESULTS -f THIS_FILE
def panelkey: [.project,.pr,.direction,.view];
def expected: if .direction=="repair" then "CLEAN" else "CONCERN" end;
def vote: .answers.review.choice;
def p: .answers.review.probabilities.CONCERN;
def valid:
    . as $r | .answers.review as $a | $a.probabilities as $p |
    ($p|keys)==["CLEAN","CONCERN"] and ($a.type=="choice") and
    ([$p[]]|all(.[]; type=="number" and .>=0 and .<=1)) and ((($p|add)-1)|fabs)<0.000001 and
    ($a.choice=="CONCERN" or $a.choice=="CLEAN") and $a.confidence==$p[$a.choice] and
    $a.confidence==([$p[]]|max) and ($r.state_sha256|test("^[0-9a-f]{64}$")) and
    (.usage.input_tokens|type=="number" and .>0 and .<16384 and floor==.) and .usage.output_tokens==0;
def metrics:
    . as $rows | group_by([.project,.pr]) as $pairs |
    {rows:length, correct:map(select(vote==expected))|length,
     pairs:($pairs|length), pairs_correct:([$pairs[]|select(all(.[];vote==expected))]|length),
     false_alarms:map(select(expected=="CLEAN" and vote=="CONCERN"))|length,
     missed:map(select(expected=="CONCERN" and vote=="CLEAN"))|length,
     reverse_ranks_higher:([$pairs[]|sort_by(.direction)|select((.[1]|p)>(.[0]|p))]|length)};
($panel[0].cases|map(select(.view=="source" or .view=="witness"))) as $known |
if ($known|length)!=32 or ($rows|length)!=64 or
   ([$rows[]|select(valid)]|length)!=64 or
   ([$known[]|panelkey]|sort)!=([$rows[]|panelkey]|unique) or
   ([$rows|group_by(panelkey)[]|select(
     (map(.order)|sort)!=["clean-first","concern-first"] or
     (map(.state_sha256)|unique|length)!=1 or (map(.input_sha256)|unique|length)!=1 or
     (map(.usage.input_tokens)|unique|length)!=1)]|length)!=0 or
   any($rows[]; . as $r | ([$known[]|select(panelkey==($r|panelkey))][0].input_sha256)!=$r.input_sha256)
then error("Liquid receipts differ from the registered panel or violate the choice contract") else
{by_view_and_order:[$rows|group_by([.view,.order])[]|{view:.[0].view,order:.[0].order} + metrics],
 verdict_changes_on_reorder:[$rows|group_by(.view)[]|{view:.[0].view,
    comparisons:(length/2), flips:([group_by(panelkey)[]|select((map(vote)|unique|length)>1)]|length)}]}
end
