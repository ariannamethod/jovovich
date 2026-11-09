#!/bin/sh
set -eu
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
repo="$work/repo"; memory="$work/memory"; mkdir "$memory"
git init -q -b main "$repo"
git -C "$repo" config user.name Fixture
git -C "$repo" config user.email fixture@localhost
commit() { git -C "$repo" add .; git -C "$repo" commit -qm "$1"; git -C "$repo" rev-parse HEAD; }
printf 'Rebuild outputs.\n' > "$repo/RULES"
printf 'initial\n' > "$repo/expected"
printf 'ok\n' > "$repo/reverted"
base=$(commit initial)
git -C "$repo" switch -qc source
printf 'wrong\n' > "$repo/expected"
printf 'bad-before-revert\n' > "$repo/reverted"
bad=$(commit 'two mismatches')
git -C "$repo" switch -qc side
printf 'ok\n' > "$repo/expected"
printf 'bad-only-on-side\n' > "$repo/only-on-side"
side=$(commit 'sibling branch')
git -C "$repo" switch -q source
printf 'ok\n' > "$repo/expected"
printf 'ok\n' > "$repo/reverted"
head=$(commit 'pass expected and revert the other file')
git -C "$repo" switch -q main
printf 'base advanced\n' > "$repo/note"; parent=$(commit 'advance target')
printf 'changed-during-integration\n' > "$repo/expected"
landed=$(commit 'squash without the reviewed bytes')
printf 'new review\n' > "$repo/expected"
printf 'changed again\n' > "$repo/reverted"
current=$(commit 'new PR')

cat > "$work/render" <<'DRIVER'
#!/bin/sh
set -eu
test "$1" = render
if [ -n "${BARRIER:-}" ] && [ "$4" = expected ]; then
    printf ready > "$BARRIER.ready"
    i=0
    while [ ! -f "$BARRIER.continue" ]; do i=$((i+1)); [ "$i" -lt 250 ] || exit 2; sleep .05; done
fi
test "$4" != "${FAIL_PATH:-}"
printf '%s\n' "${GENERATED:-ok}"
DRIVER
chmod +x "$work/render"
hash=$(shasum -a 256 < "$work/render" | awk '{print $1}')
jq -n --arg sha "$hash" '{schema:"jovovich.snapshot-routes/1",repository:"fixture/squash",harness_sha256:$sha,paths:["*"]}' > "$work/routes"
scope=fixture/squash
packet() {
    name=$1; number=$2; start=$3; end=$4; mode=$5; shift 5
    build/jovovich-pack "$mode" "$memory" "$scope" rule --all "$repo" "$start" "$end" "$@" > "$work/$name.batch"
    build/batch-fixture emit "$work/$name.batch" clean > "$work/$name.answers"
    jq -n --argjson n "$number" --arg s "$scope" --arg b "$start" --arg h "$end" '{
      number:$n,url:("https://github.com/"+$s+"/pull/"+($n|tostring)),createdAt:"2025-01-01T10:00:00Z",baseRefOid:$b,headRefOid:$h}' > "$work/$name.pr"
}
report() {
    build/jovovich-report "$work/$1.batch" "$work/$1.answers" --memory "$memory" --auto-snapshots "$repo" \
      "$work/render" "$work/routes" --record-pr "$scope" "$work/$1.pr" "$2"
}
land() {
    build/jovovich-replay land "$repo" "$work/render" "$1" --record-pr "$memory" "$scope" "$2" "$3" < "$work/head.batch"
}
reject() { if "$@" > "$work/rejected" 2>/dev/null; then exit 1; fi; test ! -s "$work/rejected"; }
history() { build/jovovich-replay history "$memory" "$scope" 7; }
packet bad 7 "$base" "$bad" --remember RULES
packet side 7 "$base" "$side" --recall
packet head 7 "$base" "$head" --recall
packet new 8 "$landed" "$current" --recall
jq --arg sha "$landed" '.+{state:"MERGED",mergedAt:"2025-01-02T12:34:56Z",mergeCommit:{oid:$sha}}' "$work/head.pr" > "$work/merged"
report side --json > /dev/null
report bad --json > /dev/null
reject land "$work/routes" "$work/merged" "$landed"   # final head must have been checked
report head --json > /dev/null
report new --json | jq -e '.prior_snapshot_cases==[]' > /dev/null
history > "$work/before"
cp "$memory"/pr-*-7.checkpoint "$work/pre"
for transform in '.state="OPEN"' '.mergedAt="2024-01-01T00:00:00Z"' '.mergedAt="2999-01-01T00:00:00Z"' \
    '.url="https://github.com/foreign/repo/pull/7"' '.number=42|.url="https://github.com/fixture/squash/pull/42"' \
    '.headRefOid=.baseRefOid'; do
    jq "$transform" "$work/merged" > "$work/invalid"
    reject land "$work/routes" "$work/invalid" "$landed"
done
reject land "$work/routes" "$work/merged" "$current"
normal=$(git -C "$repo" commit-tree "$head^{tree}" -p "$parent" -p "$head" -m 'ordinary merge')
jq --arg sha "$normal" '.mergeCommit.oid=$sha' "$work/merged" > "$work/invalid"
reject land "$work/routes" "$work/invalid" "$normal"
jq '.paths=["expected"]' "$work/routes" > "$work/other-routes"
reject land "$work/other-routes" "$work/merged" "$landed"
FAIL_PATH=reverted reject land "$work/routes" "$work/merged" "$landed"
cmp "$memory"/pr-*-7.checkpoint "$work/pre"

# A source observation concurrent with native rendering invalidates the plan.
# The operator can retry from the newly appended evidence.
BARRIER="$work/gate" land "$work/routes" "$work/merged" "$landed" > "$work/race" 2>/dev/null &
worker=$!
i=0
while [ ! -f "$work/gate.ready" ]; do i=$((i+1)); [ "$i" -lt 250 ]; sleep .05; done
GENERATED=elsewhere report side --json > /dev/null
touch "$work/gate.continue"
if wait "$worker"; then exit 1; fi
test ! -s "$work/race"
history > "$work/before"
jq -e 'all(.observations[]; .evidence.landing==null)' "$work/before" >/dev/null

land "$work/routes" "$work/merged" "$landed" > "$work/run1" & worker=$!
land "$work/routes" "$work/merged" "$landed" > "$work/run2"
wait "$worker"; cmp "$work/run1" "$work/run2"
jq -se --arg h "$landed" 'map(select(.kind=="snapshot"))|map([.file,.status,.head_commit]) ==
    [["expected","mismatch",$h],["reverted","met",$h]]' "$work/run1" >/dev/null
history > "$work/after"
jq -e --slurpfile before "$work/before" --arg base "$base" --arg head "$head" --arg landed "$landed" --arg bad "$bad" --arg parent "$parent" '
    .observations[:-1]==$before[0].observations and (.observations[-1] |
      .checked_at.unix_day >= .evidence.landing.merged_at.unix_day and
      .evidence.landing.merged_at=={schema:"janus.instant/1",time_scale:"posix",unix_day:20090,second:45296,millisecond:0} and
      (.evidence | (.batch_id==null) and (.source_batch_id|length)==64 and .base_commit==$parent and .head_commit==$landed and
        (.landing|.source_base==$base and .source_head==$head and .merge_commit==$landed and
          .source_history==[$bad,$head] and (.source_observations|length)==2)))' "$work/after" >/dev/null
cp "$memory"/pr-*-7.checkpoint "$work/post"
land "$work/routes" "$work/merged" "$landed" >/dev/null
jq '.mergedAt="2025-01-03T12:34:56Z"' "$work/merged" > "$work/invalid"
reject land "$work/routes" "$work/invalid" "$landed"
# Same number, a second single-parent commit, matching metadata and event.
jq --arg sha "$current" '.mergeCommit.oid=$sha' "$work/merged" > "$work/invalid"
reject land "$work/routes" "$work/invalid" "$current"
cmp "$memory"/pr-*-7.checkpoint "$work/post"

# Only the target branch is available in a future checkout.
git clone -q --no-local --single-branch --branch main "$repo" "$work/fresh"
repo="$work/fresh"
if git -C "$repo" cat-file -e "$head^{commit}" 2>/dev/null; then exit 1; fi
if git -C "$repo" cat-file -e "$bad^{commit}" 2>/dev/null; then exit 1; fi
report new --json > "$work/new.json"
jq -e --arg bad "$bad" --arg head "$head" --arg landed "$landed" --arg curr "$current" '
    [.prior_snapshot_cases[] | [.file,.number,.mismatch_commit,.first_checked_match,.landing]]==
    [["expected",7,$bad,$head,{source_head:$head,source_status:"met",commit:$landed,status:"mismatch"}],
     ["reverted",7,$bad,$landed,{source_head:$head,source_status:"unverified",commit:$landed,status:"met"}]]
    and all(.verified_findings[];.head_commit==$curr and .status=="mismatch")' "$work/new.json" >/dev/null
build/jovovich-report "$work/new.batch" "$work/new.answers" --memory "$memory" --auto-snapshots "$repo" "$work/render" \
  "$work/routes" --record-pr "$scope" "$work/new.pr" > "$work/new.md"
for sha in "$bad" "$head" "$landed"; do grep -F "/commit/$sha" "$work/new.md" >/dev/null; done
packet unrelated 9 "$base" "$current" --recall
report unrelated --json | jq -e '.prior_snapshot_cases==[]' >/dev/null
printf 'Squash receipts: changed integration bytes, reverted path, scoped source history, clocks, concurrent edits, atomic retries and pruned source passed\n'
