# Score P(A) in both letter orders against the original authored preferences.
def key: [.project,.pr,.direction,.axis];
def vote($p): if $p>=0.5 then "A" else "B" end;
def letter_loss($version):
  map(if .target=="A" then .[$version] else 1-.[$version] end) |
  if any(.[]; . == 0) then error("zero target probability in selector receipt")
  else (map(-log)|add)/length end;
def heldout_loss($full; $ab; $version):
  # Native offsets use float32 arithmetic. At equality allow its rounding
  # error, then cap the inferred A+B probability mass at one.
  if $ab > $full + 1e-6 then error("within-letter loss exceeds full-vocabulary loss")
  else {version:$version, full_vocabulary:$full, within_letters:$ab,
        geometric_mean_letter_mass:(([$ab-$full,0]|min)|exp)} end;
def metrics($version):
  map(. + {chosen:vote(.[$version])}) |
  {correct:map(select(.chosen==.target))|length,presentations:length,
   both_orders:([group_by(key)[]|select(all(.[];.chosen==.target))]|length),
   letter_changes_meaning:([group_by(key)[]|select(.[0].chosen==.[1].chosen)]|length)};
($run[0]) as $r |
if ($run|length)!=1 or $r.weights_sha256!=$manifest[0].weights_sha256 or
   $r.tokenizer_sha256!=$manifest[0].tokenizer_sha256 or $r.prompt_policy_sha256!=$policy_hash or
   ($r.heldout_nll|type)!="array" or ($r.heldout_nll|length)!=2 or
   any($r.heldout_nll[]; type!="number" or .<0 or (isfinite|not)) or
   $r.schema!="jovovich.voice-selection/1" or $r.steps!=200 or $r.learned_parameters!=66 or
   $r.train_tokens!=48 or $r.heldout_tokens!=24 or $r.train_sha256!=$train_hash or $r.heldout_sha256!=$test_hash or
   ($r.audition|length)!=24 or ($test|length)!=24 or
   ($r.audition|map(.id))!=($test|map(.id)) or ($test|map(.id)|unique|length)!=24 or
   any($r.audition[]; (keys!=["base","fitted","id"]) or ([.base,.fitted]|any(.[]; type!="number" or .<0 or .>1))) or
   any($test|group_by(key)[]; length!=2 or .[0].options!=(.[1].options|reverse) or (map(.target)|sort)!=["A","B"])
then error("selector receipts do not match the frozen panel") else
[range(24) as $i | $test[$i]+($r.audition[$i]|{base,fitted})] as $joined |
{heldout_loss:[["base",0],["fitted",1]]|map(. as [$v,$i] | ($joined|letter_loss($v)) as $ab |
    heldout_loss($r.heldout_nll[$i]; $ab; $v)),
 results:[$joined|group_by(.axis)[]|{axis:.[0].axis,original:metrics("base"),fitted:metrics("fitted")}],
 pairs:[$joined|group_by(key)[]|.[0] as $row|{project:$row.project,pr:$row.pr,direction:$row.direction,axis:$row.axis,
   wanted:($row.options[if $row.target=="A" then 0 else 1 end]),
   fitted_both:all(.[];vote(.fitted)==.target),
   presentations:map({target,base_p_a:.base,fitted_p_a:.fitted})}]}
end
