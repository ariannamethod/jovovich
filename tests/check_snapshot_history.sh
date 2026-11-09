#!/bin/sh
set -eu
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
repo="$work/repo"; memory="$work/memory"; mkdir "$memory"
git init -q "$repo"
git -C "$repo" config user.name Fixture
git -C "$repo" config user.email fixture@localhost
commit() { git -C "$repo" add .; git -C "$repo" commit -qm "$1"; git -C "$repo" rev-parse HEAD; }
printf 'Rebuild expected output.\n' > "$repo/RULES"
printf 'base\n' > "$repo/expected"; base=$(commit base)
printf 'wrong\n' > "$repo/expected"; bad=$(commit mismatch)
printf 'gap\n' > "$repo/note"; gap=$(commit gap)
git -C "$repo" checkout -q --detach "$bad"
printf 'ok\n' > "$repo/expected"; side=$(commit 'side match')
# Keep the failing mainline tree at a merge whose second parent already passes.
merge=$(git -C "$repo" commit-tree "$gap^{tree}" -p "$gap" -p "$side" -m 'keep failing output')
git -C "$repo" checkout -q --detach "$merge"
printf 'ok\n' > "$repo/expected"; fix=$(commit 'first checked mainline repair')
printf 'later\n' >> "$repo/note"; tip=$(commit 'another passing check')

cat > "$work/driver" <<'DRIVER'
#!/bin/sh
set -eu
test "$1" = render
test "$4" != "${FAIL_FILE:-}"
printf '%s\n' "${GENERATED:-ok}"
DRIVER
chmod +x "$work/driver"
sha=$(shasum -a 256 < "$work/driver" | awk '{print $1}')
jq -n --arg h "$sha" '{schema:"jovovich.snapshot-routes/1",repository:"fixture/demo",harness_sha256:$h,paths:["expected","note"]}' > "$work/policy"
jq '.paths=["expected"]' "$work/policy" > "$work/other-policy"
jq '.paths=["absent"]' "$work/policy" > "$work/skip-policy"
make_rows() {
    head=$1; name=$2; key=$3; action=$4
    shift 4
    build/jovovich-pack "$action" "$memory" fixture/demo "$key" --all "$repo" "$base" "$head" "$@" > "$work/$name.batch"
    build/batch-fixture emit "$work/$name.batch" clean > "$work/$name.answers"
    jq -n --arg b "$base" --arg h "$head" '{number:7,url:"https://github.com/fixture/demo/pull/7",
        createdAt:"2025-01-01T00:00:00Z",baseRefOid:$b,headRefOid:$h}' > "$work/$name.pr"
}
make_rows "$bad" bad standard --remember RULES
make_rows "$side" side standard --recall
make_rows "$merge" merge standard --recall
make_rows "$fix" fix standard --recall
make_rows "$tip" tip standard --recall
make_rows "$merge" other revised --remember RULES
record() {
    packet=$1; policy=$2; shift 2
    build/jovovich-report "$work/$packet.batch" "$work/$packet.answers" --memory "$memory" \
        --auto-snapshots "$repo" "$work/driver" "$work/$policy" --record-pr fixture/demo "$work/$packet.pr" "$@"
}
history() { build/jovovich-replay history "$memory" fixture/demo 7 --snapshot "$repo" "$1" expected; }
reject() { if "$@" > "$work/rejected" 2> "$work/error"; then exit 1; fi; test ! -s "$work/rejected"; }

# Save later and off-branch observations first. Each reader starts a new process.
record side policy > /dev/null
record bad policy --json > /dev/null &
writer=$!
record bad policy > /dev/null
wait "$writer"
record merge skip-policy > /dev/null
GENERATED=wrong record merge other-policy > /dev/null
GENERATED=wrong record other policy > /dev/null
history "$gap" | jq -e --arg bad "$bad" '.status_at_head=="unverified" and
    [.checks[].head_commit]==[$bad] and .checks[0].first_checked_match==null' >/dev/null
history "$merge" | jq -e --arg bad "$bad" --arg side "$side" '
    all(.checks[]; .head_commit!=$side) and (.checks|any(.status=="skipped")) and
    [.checks[]|select(.head_commit==$bad)|.first_checked_match]==[null]' >/dev/null
record tip policy > /dev/null
record fix policy > /dev/null
history "$tip" > "$work/history"
jq -e --arg bad "$bad" --arg fix "$fix" --arg side "$side" '.status_at_head=="met" and
    all(.checks[];.head_commit!=$side) and [.checks[]|select(.head_commit==$bad)|
      [.status,.result.line,.result.byte_column,.result.expected,.result.observed,.first_checked_match]]
    ==[["mismatch",1,1,"wrong\n","ok\n",$fix]]' "$work/history" >/dev/null
cp "$memory"/pr-*.checkpoint "$work/checkpoint"
record fix policy --json > /dev/null
cmp "$memory"/pr-*.checkpoint "$work/checkpoint"
FAIL_FILE=note reject record fix policy
cmp "$memory"/pr-*.checkpoint "$work/checkpoint"
# A saved view of the exact fix stays reproducible after a new receipt arrives.
compare() { build/jovovich-replay history "$memory" fixture/demo 7 --snapshot "$repo" "$fix" expected --compare-known-at "$@"; }
past=2000-01-01T00:00:00Z; future=2099-01-01T00:00:00Z
compare "$past" "$future" > "$work/first-view"
jq -e --arg fix "$fix" '.streams[0] as $s |
 .head_commit==$fix and (.streams|length)==1 and $s.before=={status:"unverified",receipt_ids:[]} and $s.after.status=="met" and
 $s.verdict_changed and [$s.new_checks[].id]==$s.after.receipt_ids' "$work/first-view" >/dev/null
cursor=$(jq -r .journal_head "$work/first-view")
stamp() {
    python3 -c 'import datetime as d, json, sys
x=json.load(sys.stdin)["streams"][0]["new_checks"][-1]["checked_at"]
t=d.datetime(1970,1,1)+d.timedelta(days=x["unix_day"],seconds=x["second"],milliseconds=x["millisecond"]+int(sys.argv[1]))
print(t.isoformat(timespec="milliseconds")+"Z")' "$1"
}
first=$(stamp 0 < "$work/first-view")
one_ms_before=$(stamp -1 < "$work/first-view")
compare "$one_ms_before" "$one_ms_before" | jq -e '.streams==[]' >/dev/null
compare "$first" "$first" | jq -e '.streams[0] | .before==.after and (.verdict_changed|not) and .new_checks==[]' >/dev/null
# Conflicting renderings on one SHA withdraw it as an unambiguous match.
GENERATED=different record fix policy > /dev/null
compare "$past" "$future" --through "$cursor" > "$work/pinned-view"
cmp "$work/first-view" "$work/pinned-view"
compare "$first" "$future" > "$work/later-view"
jq -e --arg cursor "$cursor" '.streams[0] as $s |
 .journal_head!=$cursor and $s.before.status=="met" and $s.after.status=="conflicting" and $s.verdict_changed and
 ($s.new_checks|length)==1 and $s.new_checks[0].result.status=="mismatch" and
 $s.new_checks[0].result.byte_column==1 and $s.after.receipt_ids==($s.before.receipt_ids+[$s.new_checks[0].id])' "$work/later-view" >/dev/null
# A newly appended receipt can fall inside a previously read time window.
# Pin the old answer and ask about that very same instant on the new journal.
compare "$future" "$future" --from-journal "$cursor" > "$work/saved-vs-now"
jq -e --slurpfile old "$work/first-view" '.streams[0] as $s |
 .from_journal==$old[0].journal_head and $s.before==$old[0].streams[0].after and
 $s.after.status=="conflicting" and $s.verdict_changed and ($s.new_checks|length)==1' "$work/saved-vs-now" >/dev/null
last=$(jq -r .journal_head "$work/saved-vs-now")
compare "$future" "$future" --through "$last" --from-journal "$cursor" | cmp - "$work/saved-vs-now"
reject compare "$future" "$future" --from-journal "$last" --through "$cursor"
second=$(stamp 0 < "$work/later-view")
compare "$first" "$second" | jq -e '.streams[0].after.status=="conflicting"' >/dev/null
git -C "$repo" tag -a compared -m 'tag naming the same commit' "$fix"
tag=$(git -C "$repo" rev-parse refs/tags/compared)
reject build/jovovich-replay history "$memory" fixture/demo 7 --snapshot "$repo" "$tag" expected --compare-known-at "$first" "$second"
if [ "${#fix}" -eq 64 ]; then
    prefix=$(printf '%.40s' "$fix")
    reject build/jovovich-replay history "$memory" fixture/demo 7 --snapshot "$repo" "$prefix" expected --compare-known-at "$first" "$second"
fi
reject compare "$second" "$first"
reject compare 2025-02-29T00:00:00Z "$future"
reject compare "$first" "$future" --through deadbeef
reject build/jovovich-replay history "$memory" other/demo 7 --snapshot "$repo" "$fix" expected --compare-known-at "$first" "$future" --through "$cursor"
build/jovovich-replay history "$memory" fixture/demo 7 --snapshot "$repo" "$merge" expected --compare-known-at "$past" "$future" |
    jq -e '(.streams|length)==3 and ([.streams[].after.status]|sort)==["met","met","unverified"]' >/dev/null
history "$tip" | jq -e --arg bad "$bad" --arg fix "$fix" --arg tip "$tip" '
    [.checks[]|select(.head_commit==$bad)|.first_checked_match]==[$tip] and
    [.checks[]|select(.head_commit==$fix)|.status]==["conflicting","conflicting"]' >/dev/null
build/jovovich-replay history "$memory" other/demo 7 --snapshot "$repo" "$tip" expected |
    jq -e '.checks==[] and .status_at_head=="unverified"' >/dev/null
reject history 0000000000000000000000000000000000000000
printf 'Snapshot history: first-parent recovery, skipped and conflicting evidence, scoped rules, atomic retries and restart passed\n'

# A new PR starts from a normal merge. The old PR received an unmeasured final
# edit. Its own merge also contains a passing second parent, and its first
# checked fix has since acquired a conflicting observation (above).
old_head=$(git -C "$repo" commit-tree "$tip^{tree}" -p "$tip" -m 'untested final edit')
integrated=$(git -C "$repo" commit-tree "$tip^{tree}" -p "$base" -p "$old_head" -m 'merge old PR')
git -C "$repo" checkout -q --detach "$integrated"
printf 'current\n' > "$repo/expected"; current=$(commit 'change expected output again')
new_packet() {
    scope=$1; action=$2; key=$3; start=$4; end=$5; shift 5
    build/jovovich-pack "$action" "$memory" "$scope" "$key" --all "$repo" "$start" "$end" "$@" > "$work/new.batch"
    build/batch-fixture emit "$work/new.batch" clean > "$work/new.answers"
    jq -n --arg b "$start" --arg h "$end" --arg scope "$scope" '{number:21,
        url:("https://github.com/"+$scope+"/pull/21"), createdAt:"2025-02-01T00:00:00Z",
        baseRefOid:$b, headRefOid:$h}' > "$work/new.pr"
}
new_report() {
    scope=$1; routes=$2; shift 2
    build/jovovich-report "$work/new.batch" "$work/new.answers" --memory "$memory" \
        --auto-snapshots "$repo" "$work/driver" "$work/$routes" --record-pr "$scope" "$work/new.pr" "$@"
}
# Same commit graph, paths and PR number, in an independent repository.
jq '.repository="other/demo"' "$work/policy" > "$work/foreign-policy"
new_packet other/demo --remember standard "$integrated" "$current" RULES
new_report other/demo foreign-policy --json | jq -e '.prior_snapshot_cases==[]' >/dev/null

new_packet fixture/demo --recall standard "$integrated" "$current"
new_report fixture/demo policy --json > "$work/new.json"
jq -e --arg bad "$bad" --arg tip "$tip" --arg current "$current" '
  [.verified_findings[]|[.status,.head_commit,.expected]]==[["mismatch",$current,"current\n"]] and
  .prior_snapshot_cases==[{repository:"fixture/demo",number:7,file:"expected",line:1,byte_column:1,expected_byte:119,observed_byte:111,
    mismatch_commit:$bad,first_checked_match:$tip}]' "$work/new.json" >/dev/null
new_report fixture/demo policy > "$work/new.md"
sed -n '/^### Earlier snapshot checks/,/^<details>/p' "$work/new.md" > "$work/citations"
for value in "/fixture/demo/pull/7" "/commit/$bad" "/commit/$tip" 'line 1, byte 1'; do
    grep -F "$value" "$work/citations" >/dev/null
done
if grep -Eq "$fix|$side|other/demo|/pull/21" "$work/citations"; then exit 1; fi
new_report fixture/demo other-policy --json | jq -e '.prior_snapshot_cases==[]' >/dev/null
new_report fixture/demo skip-policy --json | jq -e '.prior_snapshot_cases==[] and .verified_findings==[]' >/dev/null
new_packet fixture/demo --recall revised "$integrated" "$current"
new_report fixture/demo policy --json | jq -e '.prior_snapshot_cases==[]' >/dev/null
# A new branch based on the unverified gap never treats the side or current
# PR's verification as the historical fix. Squashed-away heads are unrelated.
new_packet fixture/demo --recall standard "$gap" "$current"
new_report fixture/demo policy --json | jq -e --arg bad "$bad" '
  .prior_snapshot_cases==[{repository:"fixture/demo",number:7,file:"expected",line:1,byte_column:1,expected_byte:119,observed_byte:111,
    mismatch_commit:$bad,first_checked_match:null}]' >/dev/null
new_packet fixture/demo --recall standard "$base" "$current"
new_report fixture/demo policy --json | jq -e '.prior_snapshot_cases==[]' >/dev/null

# Neither of two different failing renders can supply a single historical
# location for the same revision. The old observations remain queryable.
GENERATED=another record bad policy > /dev/null
history "$bad" | jq -e --arg bad "$bad" '
    .status_at_head=="mixed" and [.checks[] | select(.head_commit==$bad) | .status]==["conflicting","conflicting"]' >/dev/null
new_packet fixture/demo --recall standard "$integrated" "$current"
new_report fixture/demo policy --json | jq -e '.prior_snapshot_cases==[]' >/dev/null

# Record other PRs in the same namespace. Only the most recent eligible PR
# may supply the citation. Recording and opening order can differ.
prior_number() {
    jq --argjson n "$1" --arg date "$2" '.number=$n|.url=("https://github.com/fixture/demo/pull/"+($n|tostring))|
        .createdAt=$date' "$work/bad.pr" > "$work/number.pr"
    build/jovovich-report "$work/bad.batch" "$work/bad.answers" --memory "$memory" \
        --auto-snapshots "$repo" "$work/driver" "$work/policy" --record-pr fixture/demo "$work/number.pr" >/dev/null
}
prior_number 25 2025-03-01T00:00:00Z
prior_number 10 2025-03-01T00:00:00Z
prior_number 9 2025-01-02T00:00:00Z
new_report fixture/demo policy --json | jq -e --arg bad "$bad" '
    [.prior_snapshot_cases[]|[.number,.mismatch_commit,.first_checked_match]]==[[9,$bad,null]]' >/dev/null
# Failure while reading historical evidence publishes no comment or new PR checkpoint.
jq '.number=20|.url="https://github.com/fixture/demo/pull/20"' "$work/new.pr" > "$work/20.pr"
cp "$work/20.pr" "$work/new.pr"
for checkpoint in "$memory"/pr-*-9.checkpoint; do printf damaged > "$checkpoint"; done
reject new_report fixture/demo policy --json
for checkpoint in "$memory"/pr-*-20.checkpoint; do test ! -e "$checkpoint"; done
# An otherwise identical snapshot ending before the regenerated newline has
# no expected byte at the reported column.
git -C "$repo" checkout -q --detach "$base"
printf ok > "$repo/expected"; short=$(commit 'missing newline')
printf 'ok\n' > "$repo/expected"; newline=$(commit 'restore newline')
jq '.repository="fixture/eof"' "$work/policy" > "$work/eof-policy"
new_packet fixture/eof --remember standard "$base" "$short" RULES
jq '.number=2|.url="https://github.com/fixture/eof/pull/2"' "$work/new.pr" > "$work/2.pr"
cp "$work/2.pr" "$work/new.pr"
new_report fixture/eof eof-policy > /dev/null
new_packet fixture/eof --recall standard "$short" "$newline"
new_report fixture/eof eof-policy --json | jq -e --arg sha "$short" '
    [.prior_snapshot_cases[]|[.number,.mismatch_commit,.byte_column,.expected_byte,.observed_byte,.first_checked_match]]
    ==[[2,$sha,3,null,10,null]] and .verified_findings[0].status=="met"' >/dev/null
printf 'PR comment: automatic cross-PR recall, real merge ancestry, exact scope, separate current results and replay passed\n'
