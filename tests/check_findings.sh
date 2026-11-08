#!/bin/sh
set -eu
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
repo="$work/repo with spaces"
git init -q "$repo"
git -C "$repo" config user.name Fixture
git -C "$repo" config user.email fixture@localhost
printf 'Parity must be even.\n' > "$repo/RULES"
file="flags with spaces"
commit() { git -C "$repo" add .; git -C "$repo" commit -qm "$1"; git -C "$repo" rev-parse HEAD; }
flags() { printf '# flags\n%s\n# independent\n%s\n# independent\n%s\n' "$1" "$2" "$3" > "$repo/$file"; }
flags 0 0 0
printf 'pass\n' > "$repo/output"
base=$(commit base)
flags 1 0 0
printf 'wrong\n' > "$repo/output"
one=$(commit single)
flags 1 1 1
three=$(commit three)
# Insertion at the start of a file and removal of an unterminated final line.
git -C "$repo" checkout -q --detach "$base"
printf '1\n' > "$work/prefix"
cat "$repo/$file" >> "$work/prefix"
cp "$work/prefix" "$repo/$file"
inserted=$(commit inserted)
printf '1' >> "$repo/$file"
odd_tail=$(commit 'no final LF')
git -C "$repo" count-objects -v > "$work/objects-before"
cat > "$work/driver" <<'DRIVER'
#!/bin/sh
set -eu
case "$1" in
  expect) printf '{"metric":"text","required":"0"}\n' ;;
  observe) git -C "$2" show "$3:$4" > "$2/input"
    awk '/^[01]$/ {n+=$1} END {printf "\"%d\"\n",n%2}' "$2/input" ;;
  render) printf '%s' "${GENERATED-pass}"; if test -z "${NO_LF:-}"; then printf '\n'; fi ;;
  *) exit 2 ;;
esac
DRIVER
chmod +x "$work/driver"
tool=build/jovovich-replay
pack() { build/jovovich-pack "$repo" "$1" "$2" RULES "$file"; }
probe() { "$tool" probe "$repo" "$work/driver" -2; }
locate() { "$tool" locate "$repo" "$work/driver"; }
render() { "$tool" snapshot "$repo" "$work/driver"; }
reject() { if "$@" > "$work/rejected" 2>"$work/error"; then exit 1; fi; test ! -s "$work/rejected"; }
pack "$base" "$one" > "$work/row"
probe < "$work/row" > "$work/measured"
locate < "$work/measured" > "$work/finding"
jq -e '.status=="located" and .file=="flags with spaces" and .mode == -2 and
    .location=={base_start:2,base_lines:1,head_start:2,head_lines:1} and
    .trials[0].after_revert=="0" and .trials[0].after_introduction=="1"
    and .rule_excerpt=="Parity must be even.\n"' "$work/finding" >/dev/null
jq -c '.trace_evidence.runs += [(.trace_evidence.runs[0] | .mode=7)]' "$work/measured" > "$work/two-modes"
locate < "$work/two-modes" | jq -se 'map(.mode)==[-2,7] and all(.[]; .location.head_start==2)' >/dev/null
build/jovovich-pack --all "$repo" "$base" "$one" RULES > "$work/batch"
sed -n '1p' "$work/batch" | probe > "$work/first"
sed -n '2p' "$work/batch" > "$work/second"
cat "$work/first" "$work/second" > "$work/full"
locate < "$work/full" | jq -se 'length==1 and .[0].location.head_start==2' >/dev/null
# The ordinary report recomputes findings against its own validated model inputs.
build/batch-fixture emit "$work/full" clean > "$work/answers"
report() { build/jovovich-report "$work/full" "$work/answers" "$@"; }
report --locate "$repo" "$work/driver" --snapshot "$repo" "$work/driver" output > "$work/comment"
grep -Fq '**Verified regression** · flags with spaces:2' "$work/comment"
grep -Fq 'Parity must be even' "$work/comment"
grep -Fq '**Snapshot mismatch** · output:1 · byte 1' "$work/comment"
report --json --locate "$repo" "$work/driver" --snapshot "$repo" "$work/driver" output > "$work/report"
jq -e '.summary.verdict=="CLEAN" and [.verified_findings[].status]==["located","mismatch"] and
    .verified_findings[0].location.head_start==2 and .verified_findings[1].observed=="pass\n"' "$work/report" >/dev/null
reject report --locate "$repo" "$work/driver" --snapshot "$repo" "$work/driver" missing
reject report --snapshot "$repo" "$work/driver" output --snapshot "$repo" "$work/driver" output
reject report --memory "$work"
build/jovovich-pack --all "$repo" "$base" "$three" RULES > "$work/amb-batch"
sed -n '1p' "$work/amb-batch" | probe > "$work/amb"
sed -n '2p' "$work/amb-batch" >> "$work/amb"
build/batch-fixture emit "$work/amb" clean > "$work/amb-votes"
build/jovovich-report "$work/amb" "$work/amb-votes" --locate "$repo" "$work/driver" > "$work/amb-comment"
grep -Fq 'Matching changes: flags with spaces:2, flags with spaces:4, flags with spaces:6' "$work/amb-comment"
if grep -Fq '**Verified regression**' "$work/amb-comment"; then exit 1; fi
cat "$work/second" "$work/first" > "$work/reordered"
reject locate < "$work/reordered"
pack "$one" "$base" > "$work/row"; probe < "$work/row" > "$work/repair"
locate < "$work/repair" | jq -e '.status=="met" and .location==null' >/dev/null
pack "$base" "$three" > "$work/row"; probe < "$work/row" > "$work/multiple"
locate < "$work/multiple" | jq -e '.status=="ambiguous" and (.trials|length)==3 and .location==null' >/dev/null
build/jovovich-pack --all "$repo" "$base" "$inserted" RULES > "$work/no-traces"
locate < "$work/no-traces" > "$work/no-findings"
test ! -s "$work/no-findings"
pack "$base" "$inserted" > "$work/row"; probe < "$work/row" > "$work/inserted"
locate < "$work/inserted" | jq -e '.status=="located" and .location=={base_start:0,base_lines:0,head_start:1,head_lines:1}' >/dev/null
pack "$odd_tail" "$inserted" > "$work/row"; probe < "$work/row" > "$work/deleted"
locate < "$work/deleted" | jq -e '.status=="located" and .location.base_lines==1 and .location.head_lines==0' >/dev/null
jq -c '.trace_evidence.runs[0].head="other"' "$work/measured" > "$work/forged"
reject locate < "$work/forged"
build/jovovich-pack "$repo" "$one" "$base" RULES output > "$work/text"
render < "$work/text" | jq -e '.status=="met" and .line==null' >/dev/null
GENERATED=PASS render < "$work/text" | jq -e '.status=="mismatch" and .line==1 and .byte_column==1 and
    .expected=="pass\n" and .observed=="PASS\n"' >/dev/null
NO_LF=1 render < "$work/text" | jq -e '.status=="mismatch" and .byte_column==5 and .observed=="pass"' >/dev/null
GENERATED=$(printf '\377') reject render < "$work/text"
cat > "$work/unstable" <<'DRIVER'
#!/bin/sh
set -eu
if test -e "$JOV_DRIVER_PATH.once"; then printf 'second'; else touch "$JOV_DRIVER_PATH.once"; printf 'first'; fi
DRIVER
chmod +x "$work/unstable"
reject "$tool" snapshot "$repo" "$work/unstable" < "$work/text"
git -C "$repo" count-objects -v > "$work/objects-after"
cmp "$work/objects-before" "$work/objects-after"
git -C "$repo" diff --quiet
git -C "$repo" diff --cached --quiet
printf 'Verified unique and ambiguous hunks, replay reproduction, batch membership and snapshot lines\n'
