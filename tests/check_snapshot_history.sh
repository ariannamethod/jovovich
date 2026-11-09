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
# Conflicting renderings on one SHA withdraw it as an unambiguous match.
GENERATED=different record fix policy > /dev/null
history "$tip" | jq -e --arg bad "$bad" --arg fix "$fix" --arg tip "$tip" '
    [.checks[]|select(.head_commit==$bad)|.first_checked_match]==[$tip] and
    [.checks[]|select(.head_commit==$fix)|.status]==["conflicting","conflicting"]' >/dev/null
build/jovovich-replay history "$memory" other/demo 7 --snapshot "$repo" "$tip" expected |
    jq -e '.checks==[] and .status_at_head=="unverified"' >/dev/null
reject history 0000000000000000000000000000000000000000
printf 'Snapshot history: first-parent recovery, skipped and conflicting evidence, scoped rules, atomic retries and restart passed\n'
