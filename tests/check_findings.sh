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
  render) if test -n "${RENDER_LOG:-}"; then printf '%s\n' "$4" >> "$RENDER_LOG"; fi
    printf '%s' "${GENERATED-pass}"; if test -z "${NO_LF:-}"; then printf '\n'; fi ;;
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
# Both repositories have the same Git objects and PR number, with independent rules.
memory="$work/pr-memory"
mkdir "$memory"
git -c advice.detachedHead=false clone -q "$repo" "$work/fork"
prepare_pr() {
    build/jovovich-pack --remember "$memory" "$1" parity --all "$2" "$base" "$one" RULES > "$work/pr-pack"
    sed -n '1p' "$work/pr-pack" | "$tool" probe "$2" "$work/driver" -2 > "$3"
    sed -n '2p' "$work/pr-pack" >> "$3"
}
pr_metadata() {
    jq -n --arg url "https://github.com/$1/pull/7" --arg date "$2" --arg base "$base" --arg head "$3" \
        '{number:7,url:$url,createdAt:$date,baseRefOid:$base,headRefOid:$head}'
}
record_pr() { "$tool" locate "$1" "$work/driver" --record-pr "$memory" "$2" "$3"; }
history() { "$tool" history "$memory" "$1" 7 "$2"; }
prepare_pr Studio/One "$repo" "$work/a"
prepare_pr studio/two "$work/fork" "$work/b"
pr_metadata Studio/One 2024-02-29T23:59:59Z "$one" > "$work/a-meta"
pr_metadata studio/two 2025-01-01T00:00:00Z "$one" > "$work/b-meta"
record_pr "$repo" studio/one "$work/a-meta" < "$work/a" > "$work/a-findings" &
pid=$!
record_pr "$repo" studio/one "$work/a-meta" < "$work/a" > "$work/a-retry"
wait "$pid"
cmp "$work/a-findings" "$work/a-retry"
history STUDIO/ONE "$one" > "$work/a-history"
jq -e '.status=="checked" and .repository=="studio/one" and .number==7 and (.observations|length)==1
    and .observations[0].opened_at=={schema:"janus.instant/1",time_scale:"posix",unix_day:19782,second:86399,millisecond:0}
    and .observations[0].checked_at.schema=="janus.instant/1" and .observations[0].evidence.findings[0].location.head_start==2' "$work/a-history" >/dev/null
history studio/two "$one" | jq -e '.status=="unverified" and .created_at==null' >/dev/null
record_pr "$work/fork" studio/two "$work/b-meta" < "$work/b" > /dev/null
history studio/two "$one" | jq -e '.created_at=="2025-01-01T00:00:00Z" and .observations[0].evidence.fact.repository=="studio/two"' >/dev/null
history studio/one "$three" | jq -e '.status=="unverified" and .created_at=="2024-02-29T23:59:59Z" and .observations==[]' >/dev/null
reject record_pr "$repo" studio/one "$work/b-meta" < "$work/a"
reject record_pr "$repo" studio/one "$work/a-meta" < "$work/b"
pr_metadata studio/one 2024-02-29T23:59:59Z "$three" > "$work/wrong"
reject record_pr "$repo" studio/one "$work/wrong" < "$work/a"
for bad_date in 2023-02-29T00:00:00Z 2024-03-01T00:00:00Z 9999-12-30T00:00:00Z; do
    pr_metadata studio/one "$bad_date" "$one" > "$work/wrong"
    reject record_pr "$repo" studio/one "$work/wrong" < "$work/a"
done
reject record_pr "$repo" studio/one "$work/a-meta" < "$work/pr-pack"
sed -n '1p' "$work/a" > "$work/incomplete"
reject record_pr "$repo" studio/one "$work/a-meta" < "$work/incomplete"
record_pr "$repo" studio/one "$work/a-meta" < "$work/a" > /dev/null
history studio/one "$one" > "$work/reread"
cmp "$work/a-history" "$work/reread"
# A new head adds another observation to the PR; the earlier head stays readable.
build/jovovich-pack --recall "$memory" Studio/One parity --all "$repo" "$base" "$three" > "$work/updated-pack"
sed -n '1p' "$work/updated-pack" | probe > "$work/updated"
sed -n '2p' "$work/updated-pack" >> "$work/updated"
pr_metadata Studio/One 2024-02-29T23:59:59Z "$three" > "$work/updated-meta"
record_pr "$repo" studio/one "$work/updated-meta" < "$work/updated" > /dev/null
history studio/one "$three" | jq -e '(.observations|length)==1 and .observations[0].evidence.findings[0].status=="ambiguous"' >/dev/null
history studio/one "$one" > "$work/reread"
cmp "$work/a-history" "$work/reread"
"$tool" history "$memory" studio/one 7 | jq -e '(.observations|length)==2' >/dev/null

jq '.number=6 | .url="https://github.com/Studio/One/pull/6" | .createdAt="9999-12-30T00:00:00Z"' "$work/a-meta" > "$work/six"
reject record_pr "$repo" studio/one "$work/six" < "$work/a"
jq '.createdAt="2023-12-31T00:00:00Z"' "$work/six" > "$work/six-valid"
record_pr "$repo" studio/one "$work/six-valid" < "$work/a" > /dev/null
"$tool" history "$memory" studio/one | jq -e '.repository=="studio/one" and
    [.pull_requests[].number]==[6,7] and [.pull_requests[].observations]==[1,2]' >/dev/null
"$tool" history "$memory" studio/two | jq -e '.pull_requests==[{number:7,created_at:"2025-01-01T00:00:00Z",observations:1}]' >/dev/null
"$tool" history "$memory" studio/other | jq -e '.pull_requests==[]' >/dev/null
# The same reusable renderer policy runs on whole, authenticated Git batches.
sha=$(shasum -a 256 < "$work/driver" | awk '{print $1}')
jq -n --arg sha "$sha" '{schema:"jovovich.snapshot-routes/1",repository:"studio/one",
    harness_sha256:$sha, paths:["output","out*","snapshots/*.txt"]}' > "$work/policy"
auto() { build/jovovich-report "$1" "$2" --auto-snapshots "$3" "$work/driver" "$4" --memory "$memory" --json; }
build/batch-fixture emit "$work/a" clean > "$work/a-answers"
export RENDER_LOG="$work/render-calls"
: > "$RENDER_LOG"
GENERATED=wrong auto "$work/a" "$work/a-answers" "$repo" "$work/policy" > "$work/auto"
jq -e '.snapshot_coverage.matched==1 and .snapshot_coverage.mismatched==0 and
    .snapshot_coverage.skipped==[{file:"flags with spaces",reason:"no_matching_rule"}] and
    [.verified_findings[].file]==["output"]' "$work/auto" >/dev/null
test "$(cat "$RENDER_LOG")" = output
auto "$work/a" "$work/a-answers" "$repo" "$work/policy" | jq -e '.snapshot_coverage.mismatched==1 and
    .verified_findings[0].line==1 and .verified_findings[0].byte_column==1' >/dev/null
: > "$RENDER_LOG"
build/batch-fixture emit "$work/b" clean > "$work/b-answers"
reject auto "$work/b" "$work/b-answers" "$work/fork" "$work/policy"
jq '.harness_sha256=("0"*64)' "$work/policy" > "$work/wrong-renderer"
reject auto "$work/a" "$work/a-answers" "$repo" "$work/wrong-renderer"
reject "$tool" snapshots "$repo" "$work/driver" "$work/policy" --memory "$memory" < "$work/incomplete"
reject "$tool" snapshots "$repo" "$work/driver" "$work/policy" --memory "$memory" < "$work/batch"
jq '.paths=["missing/*"]' "$work/policy" > "$work/no-match"
auto "$work/a" "$work/a-answers" "$repo" "$work/no-match" | jq -e '.verified_findings==[] and
    .snapshot_coverage.matched==0 and (.snapshot_coverage.skipped|length)==2' >/dev/null
test ! -s "$RENDER_LOG"

# Removed files, symlinks, hidden entries and nested paths stay out of the renderer.
fork="$work/fork"
git -C "$fork" checkout -q --detach "$one"
mkdir -p "$fork/snapshots/nested"
rm "$fork/output"
for f in 'out"1.txt' nested/deep.txt .hidden.txt; do printf 'pass\n' > "$fork/snapshots/$f"; done
ln -s ../RULES "$fork/snapshots/link.txt"
git -C "$fork" add -A
git -C "$fork" -c user.name=Fixture -c user.email=fixture@localhost commit -qm 'routed path kinds'
fork_head=$(git -C "$fork" rev-parse HEAD)
build/jovovich-pack --recall "$memory" studio/two parity --all "$fork" "$one" "$fork_head" > "$work/kinds"
build/batch-fixture emit "$work/kinds" clean > "$work/kinds-answers"
jq '.repository="studio/two"' "$work/policy" > "$work/fork-policy"
auto "$work/kinds" "$work/kinds-answers" "$fork" "$work/fork-policy" > "$work/kinds-report"
jq -e '.snapshot_coverage.matched==1 and .snapshot_coverage.mismatched==0 and
    (.snapshot_coverage.skipped|map({key:.file,value:.reason})|from_entries)==
      {"output":"deleted","snapshots/link.txt":"non_regular_head","snapshots/.hidden.txt":"no_matching_rule",
       "snapshots/nested/deep.txt":"no_matching_rule"} and
    [.verified_findings[].file]==["snapshots/out\"1.txt"]' "$work/kinds-report" >/dev/null
test "$(cat "$RENDER_LOG")" = 'snapshots/out"1.txt'
git -C "$repo" count-objects -v > "$work/objects-after"
cmp "$work/objects-before" "$work/objects-after"
git -C "$repo" diff --quiet
git -C "$repo" diff --cached --quiet
printf 'Verified unique and ambiguous hunks, replay reproduction, batch membership and snapshot lines\n'
