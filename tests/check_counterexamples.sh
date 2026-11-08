#!/bin/sh
set -eu
work=$(mktemp -d "${TMPDIR:-/tmp}/jov-replay-XXXXXX")
trap 'rm -rf "$work"' EXIT HUP INT TERM
repo="$work/repo with spaces"
memory="$work/case store"
mkdir "$memory"
git init -q -b main "$repo"
git -C "$repo" config user.name 'JOVOVICH replay fixture'
git -C "$repo" config user.email fixture@example.invalid
export GIT_AUTHOR_DATE='2026-11-08T00:00:00Z' GIT_COMMITTER_DATE='2026-11-08T00:00:00Z'
export JOV_CASE_CALLS="$work/calls"
driver=$PWD/tests/fixtures/draw-driver.sh
fixed='void draw(int mode){ (void)mode; scan();paint(); }'
broken='void draw(int mode){ if(mode){paint();scan();} else {scan();paint();} }'
draw() { printf '%s\n' 'void scan(void); void paint(void);' "$1" > "$repo/draw.c"; }
commit() { git -C "$repo" add .; git -C "$repo" commit -qm "$1"; git -C "$repo" rev-parse HEAD; }
rules() { printf 'Rendering\n%s\n' "$1" > "$repo/RULES.md"; }
rules 'draw must call scan then paint at both modes, 0 and 1.'
draw "$broken"; root=$(commit initial)
draw "$fixed"; repair=$(commit repair)
draw "$broken"; regression=$(commit regression)
draw "$fixed"; fixed_again=$(commit 'second repair')
printf '\n/* shared callback effect */\n' >> "$repo/draw.c"; neutral=$(commit 'comment only')
rules 'draw must call paint then scan at both modes, 0 and 1.'
draw "$broken"; newbase=$(commit 'new callback agreement')
draw "$fixed"; newhead=$(commit 'same patch, new agreement')

record() { build/jovovich-pack --remember "$memory" studio/render order "$@"; }
pack() { build/jovovich-pack --recall "$memory" studio/render order --all "$repo" "$1" "$2"; }
probe() { build/jovovich-replay probe "$repo" "$driver" "$1"; }
capture() { build/jovovich-replay remember "$memory" "$repo" "$driver"; }
replay() { build/jovovich-replay run "$memory" "$repo" "$driver"; }
reject() {
    if "$@" > "$work/rejected" 2> "$work/error"; then echo "unexpected success: $*" >&2; exit 1; fi
    test ! -s "$work/rejected"
}
record --all "$repo" "$root" "$repair" RULES.md 2 2 > "$work/first"
pack "$repair" "$regression" > "$work/regression"
pack "$regression" "$fixed_again" > "$work/repair"
pack "$fixed_again" "$neutral" > "$work/neutral"
replay < "$work/regression" > "$work/empty"
cmp "$work/regression" "$work/empty"
test ! -e "$JOV_CASE_CALLS"
probe 0 < "$work/first" > "$work/shared"
reject capture < "$work/shared"
test ! -e "$memory/cases.checkpoint"
probe 1 < "$work/first" > "$work/first-trace"
sed 's/"required":\["scan","paint"\]/"required":["paint","scan"]/' "$work/first-trace" > "$work/bad-oracle"
reject capture < "$work/bad-oracle"
sed 's/"base":\["paint","scan"\]/"base":["paint","paint"]/' "$work/first-trace" > "$work/bad-original"
reject capture < "$work/bad-original"
test ! -e "$memory/cases.checkpoint"
# The historical rule at an ancestor must have been a regular file. These
# commits share the same rules blob bytes, once as symlink target and then
# as a regular file on the current pair.
link_tree=$(git -C "$repo" ls-tree "$root" | sed '/RULES.md$/s/^100644/120000/' | git -C "$repo" mktree)
link_base=$(git -C "$repo" commit-tree "$link_tree" -m 'link target text')
regular_base=$(git -C "$repo" commit-tree "$root^{tree}" -p "$link_base" -m 'regular rules')
regular_head=$(git -C "$repo" commit-tree "$repair^{tree}" -p "$regular_base" -m 'repair under regular rules')
mkdir "$work/link-memory"
build/jovovich-pack --remember "$work/link-memory" fixture/link-rule order --all "$repo" "$regular_base" "$regular_head" RULES.md 2 2 > "$work/regular-origin"
probe 1 < "$work/regular-origin" > "$work/regular-origin-measured"
sed "s/\"origin\":{\"base_commit\":\"$regular_base/\"origin\":{\"base_commit\":\"$link_base/" "$work/regular-origin" > "$work/link-origin"
grep -Fq "\"origin\":{\"base_commit\":\"$link_base" "$work/link-origin"
sed "s/\"origin\":{\"base_commit\":\"$regular_base/\"origin\":{\"base_commit\":\"$link_base/" "$work/regular-origin-measured" > "$work/link-origin-measured"
: > "$JOV_CASE_CALLS"
reject probe 1 < "$work/link-origin"
reject build/jovovich-replay remember "$work/link-memory" "$repo" "$driver" < "$work/link-origin-measured"
reject build/jovovich-replay run "$work/link-memory" "$repo" "$driver" < "$work/link-origin"
test ! -s "$JOV_CASE_CALLS"
test ! -e "$work/link-memory/cases.checkpoint"
# A Git-valid current execution cannot authenticate a fabricated fact sequence or clock.
sed 's/"sequence":1,"supersedes":0/"sequence":173,"supersedes":172/' "$work/first-trace" > "$work/forged-sequence"
reject capture < "$work/forged-sequence"
sed 's/"recorded_at":"[0-9][0-9][0-9][0-9]-/"recorded_at":"1922-/' "$work/first-trace" > "$work/forged-clock"
reject capture < "$work/forged-clock"
test ! -e "$memory/cases.checkpoint"
capture < "$work/first-trace" > "$work/receipt"
source_sha=$(sed 's/.*"input_sha256":"\([^"]*\)".*/\1/' "$work/receipt")
build/jovovich-replay show "$memory" "$source_sha" > "$work/restored"
cmp "$work/restored" "$work/first-trace"
reject build/jovovich-replay show "$memory" 0000000000000000000000000000000000000000000000000000000000000000
cp "$memory/cases.checkpoint" "$work/original"
capture < "$work/first-trace" > "$work/again"
cmp "$work/receipt" "$work/again"
cmp "$memory/cases.checkpoint" "$work/original"
grep -Fq "$repair" "$work/receipt"
# A pre-digest trace can be captured after the operator's driver reproduces it.
mkdir "$work/older-format"
reject build/jovovich-replay remember "$work/older-format" "$repo" "$driver" < "$work/first-trace"
cp "$memory/rules.checkpoint" "$work/older-format/rules.checkpoint"
sed 's/,"harness_sha256":"[0-9a-f]*"//' "$work/first-trace" > "$work/unstamped"
build/jovovich-replay remember "$work/older-format" "$repo" "$driver" < "$work/unstamped" > "$work/legacy-receipt"
grep -Fq '"harness_sha256":' "$work/legacy-receipt"
cat "$work/first-trace" "$work/first-trace" > "$work/multiple"
reject capture < "$work/multiple"
reject replay < "$work/first-trace"
# The first review is not already landed at its own base.
replay < "$work/first" > "$work/not-landed"
cmp "$work/first" "$work/not-landed"
: > "$JOV_CASE_CALLS"
replay < "$work/regression" > "$work/regression-replayed"
printf 'observe %s 1\nobserve %s 1\nexpect %s 1\n' "$repair" "$regression" "$repair" > "$work/expected-calls"
cmp "$JOV_CASE_CALLS" "$work/expected-calls"
grep -Fq '"base":["scan","paint"],"head":["paint","scan"]' "$work/regression-replayed"
grep -Fq '"replayed_from":' "$work/regression-replayed"
# Local history metadata must not change the recovered mode or its citation.
printf '%s\n' "$repair" > "$repo/.git/shallow"
replay < "$work/regression" > "$work/replay-shallow"
cmp "$work/regression-replayed" "$work/replay-shallow"
rm "$repo/.git/shallow"
printf '%s\n' "$repair" > "$repo/.git/info/grafts"
git -C "$repo" config advice.graftFileDeprecated false
replay < "$work/regression" > "$work/replay-graft"
cmp "$work/regression-replayed" "$work/replay-graft"
rm "$repo/.git/info/grafts"
probe 1 < "$work/regression" > "$work/manual"
replay < "$work/repair" > "$work/repair-replayed"
grep -Fq '"base":["paint","scan"],"head":["scan","paint"]' "$work/repair-replayed"
replay < "$work/neutral" > "$work/neutral-replayed"
grep -Fq '"base":["scan","paint"],"head":["scan","paint"]' "$work/neutral-replayed"
record --supersedes 1 --all "$repo" "$newbase" "$newhead" RULES.md 2 2 > "$work/new-rule"
# Even without a ledger argument, probe checks what the historical base actually said.
sed "s/\"origin\":{\"base_commit\":\"[0-9a-f]*\"/\"origin\":{\"base_commit\":\"$root\"/" "$work/new-rule" > "$work/wrong-history"
reject probe 1 < "$work/wrong-history"
replay < "$work/new-rule" > "$work/corrected"
grep -Fq '"required":["paint","scan"]' "$work/corrected"
grep -Fq '"supersedes":1' "$work/corrected"

cp "$driver" "$work/other-driver"; chmod +x "$work/other-driver"; printf '\n# another harness\n' >> "$work/other-driver"
build/jovovich-replay run "$memory" "$repo" "$work/other-driver" < "$work/regression" > "$work/other"
cmp "$work/other" "$work/regression"
reject build/jovovich-replay remember "$memory" "$repo" "$work/other-driver" < "$work/first-trace"
export JOV_CASE_FAIL=expect
reject replay < "$work/regression"
unset JOV_CASE_FAIL
# A memory round trip retains every signed integer bit of the selected mode.
probe 16777217 < "$work/first" > "$work/large"
capture < "$work/large" > "$work/large-receipt"
replay < "$work/repair" > "$work/large-replay"
grep -Fq '"mode":16777217' "$work/large-replay"
# A newer capture on a sibling branch cannot hide an earlier landed case.
git -C "$repo" checkout -q -b side "$root"
draw "$fixed"; printf '\n' >> "$repo/draw.c"; side=$(commit 'sibling repair')
build/jovovich-pack --recall "$memory" studio/render order --as-of 1 --all "$repo" "$root" "$side" > "$work/side"
# Amended/squashed work can reuse a mode from a shared base.
replay < "$work/side" > "$work/side-replayed"
grep -Fq '"mode":16777217' "$work/side-replayed"
probe 2 < "$work/side" > "$work/side-trace"; capture < "$work/side-trace" > "$work/side-receipt"
replay < "$work/repair" > "$work/on-main"; cmp "$work/on-main" "$work/large-replay"
# A different file in the same batch passes through unchanged.
git -C "$repo" checkout -q main
printf 'int marker;\n' > "$repo/other.c"; printf '\n' >> "$repo/draw.c"; multi=$(commit 'two paths')
pack "$newhead" "$multi" > "$work/both"; replay < "$work/both" > "$work/both-replayed"
sed -n '2p' "$work/both" > "$work/orig-line"; sed -n '2p' "$work/both-replayed" > "$work/copy-line"
cmp "$work/orig-line" "$work/copy-line"
# A single member of a real two-file pack remains independently measurable.
sed -n '1p' "$work/both" > "$work/member"
probe 1 < "$work/member" > "$work/member-trace"
: > "$JOV_CASE_CALLS"
for mutation in 's/"index":0/"index":1/' 's/"count":2/"count":3/' 's/"scope":"all_changed_paths","id":"./"scope":"all_changed_paths","id":"X/'; do
    sed "$mutation" "$work/member" > "$work/changed-member"
    sed "$mutation" "$work/member-trace" > "$work/changed-trace"
    ! cmp -s "$work/member" "$work/changed-member"
    reject probe 1 < "$work/changed-member"
    reject capture < "$work/changed-trace"
done
test ! -s "$JOV_CASE_CALLS"
# Packing and replay share the same path order despite local options or a caller's GIT_DIR.
printf 'other.c\ndraw.c\n' > "$work/untrusted-order"
git -C "$repo" config diff.orderFile "$work/untrusted-order"
replay < "$work/both" > "$work/ordered-replay"; cmp "$work/ordered-replay" "$work/both-replayed"
GIT_DIR="$work/absent-git-directory" build/jovovich-replay run "$memory" "$repo" "$work/other-driver" < "$work/both" > "$work/isolated"
cmp "$work/isolated" "$work/both"; git -C "$repo" config --unset diff.orderFile
# Scope is checked before any driver call, including syntactically valid partial batches.
: > "$JOV_CASE_CALLS"
sed -n '1p' "$work/both" > "$work/only-first"; reject replay < "$work/only-first"
cat "$work/only-first" "$work/only-first" > "$work/duplicate"; reject replay < "$work/duplicate"
cat "$work/orig-line" "$work/only-first" > "$work/reversed"; reject replay < "$work/reversed"
sed 's/"count":2/"count":1/' "$work/only-first" > "$work/false-single"; reject replay < "$work/false-single"
sed 's/"scope":"all_changed_paths","id":"./"scope":"all_changed_paths","id":"X/' "$work/both" > "$work/false-digest"; reject replay < "$work/false-digest"
test ! -s "$JOV_CASE_CALLS"
# A count oracle comes from the new rule as well.
rules 'draw must call paint exactly twice.'; cntbase=$(commit 'switch to paint count')
draw 'void draw(int mode){ (void)mode; scan();paint();paint(); }'; cnthead=$(commit 'second paint')
record --supersedes 2 --all "$repo" "$cntbase" "$cnthead" RULES.md 2 2 > "$work/count"
replay < "$work/count" > "$work/count-replayed"
grep -Fq '"metric":"count","target":"paint"' "$work/count-replayed"
grep -Fq '"required":2' "$work/count-replayed"
# Two independently verified additions can publish concurrently. Retrying either
# afterwards must leave the joint checkpoint byte-for-byte unchanged.
probe 7 < "$work/first" > "$work/seven"
probe 8 < "$work/first" > "$work/eight"
capture < "$work/seven" > "$work/seven-receipt" & p1=$!
capture < "$work/eight" > "$work/eight-receipt" & p2=$!
wait "$p1"; wait "$p2"
cp "$memory/cases.checkpoint" "$work/joint"
capture < "$work/seven" > "$work/retry-seven"
capture < "$work/eight" > "$work/retry-eight"
cmp "$work/joint" "$memory/cases.checkpoint"
mkdir "$work/damaged"; printf torn > "$work/damaged/cases.checkpoint"
reject build/jovovich-replay run "$work/damaged" "$repo" "$driver" < "$work/repair"
test "$(cat "$work/damaged/cases.checkpoint")" = torn
{ cat "$work/repair"; printf '{invalid}\n'; } > "$work/broken-batch"
reject replay < "$work/broken-batch"
build/jovovich-pack --remember "$memory" another/project order --all "$repo" "$root" "$repair" RULES.md 2 2 > "$work/namespace"
replay < "$work/namespace" > "$work/unchanged"; cmp "$work/namespace" "$work/unchanged"
# A text-returning executable can probe, remember and remeasure a later patch.
text_driver="$work/text-driver"
export JOV_DRAW_DRIVER="$driver"
cat > "$text_driver" <<'DRIVER'
#!/bin/sh
set -eu
json=$("$JOV_DRAW_DRIVER" "$@")
case "$json" in
    '["paint","scan"]') echo '"paint scan"' ;;
    '["scan","paint"]') echo '"scan paint"' ;;
    '{"metric":"sequence","required":["scan","paint"]}') echo '{"metric":"text","required":"scan paint"}' ;;
    *) exit 1 ;;
esac
DRIVER
chmod +x "$text_driver"
build/jovovich-replay probe "$repo" "$text_driver" 1 < "$work/first" > "$work/text-origin"
build/jovovich-replay remember "$memory" "$repo" "$text_driver" < "$work/text-origin" > "$work/text-receipt"
build/jovovich-replay run "$memory" "$repo" "$text_driver" < "$work/regression" > "$work/text-replay"
grep -Fq '"replayed_from":' "$work/text-replay"
grep -Fq '"base":"scan paint","head":"paint scan","required":"scan paint"' "$work/text-replay"
# Atomic path replacement between callbacks cannot mix two executables under one digest.
export JOV_A="$work/harness-a" JOV_B="$work/harness-b"
cat > "$JOV_A" <<'DRIVER'
#!/bin/sh
set -eu
if test "$1" = observe; then
    cp "$JOV_B" "$JOV_DRIVER_PATH.next"; chmod +x "$JOV_DRIVER_PATH.next"; mv "$JOV_DRIVER_PATH.next" "$JOV_DRIVER_PATH"
    printf '"from A"\n'
else
    cp "$JOV_A" "$JOV_DRIVER_PATH.next"; chmod +x "$JOV_DRIVER_PATH.next"; mv "$JOV_DRIVER_PATH.next" "$JOV_DRIVER_PATH"
    printf '{"metric":"text","required":"oracle A"}\n'
fi
DRIVER
sed 's/from A/from B/;s/oracle A/oracle B/' "$JOV_A" > "$JOV_B"
cp "$JOV_A" "$work/changing-driver"; chmod +x "$work/changing-driver"
build/jovovich-replay probe "$repo" "$work/changing-driver" 1 < "$work/first" > "$work/stable-driver"
grep -Fq '"base":"from A","head":"from A","required":"oracle A"' "$work/stable-driver"
# Both synthetic receipts have a raw CLEAN vote. Only the differing result
# admits the zero text threshold. The shared run exercises the same Git pair.
build/jovovich-replay probe "$repo" "$text_driver" 0 < "$work/first" > "$work/text-shared"
review_id=$(sed -n 's/^{"id":"\([^"]*\)".*/\1/p' "$work/text-origin")
printf '{"id":"%s","split":"transfer","family":"text","expected":"CLEAN"}\n' "$review_id" > "$work/text-label"
for packet in text-origin text-shared; do
    build/batch-fixture emit "$work/$packet" clean > "$work/fixture-answer"
    build/jovovich-report "$work/$packet" "$work/fixture-answer" --json > "$work/$packet-report"
    build/score-quality --text-threshold 0 "$work/text-label" "$work/$packet" "$work/fixture-answer" aml/prepare.aml > "$work/$packet-score"
done
grep -Fq '"predicted":"CONCERN","raw_predicted":"CLEAN","threshold_applied":true' "$work/text-origin-score"
grep -Fq '"predicted":"CLEAN","raw_predicted":"CLEAN","threshold_applied":false' "$work/text-shared-score"
jq -e '.execution_summary=={selected_runs:1,met:1,failed:0} and .execution_changes == [{file:"draw.c", mode:1, metric:"text", base:"paint scan",
    head:"scan paint", required:"scan paint", head_matches_required:true}]' "$work/text-origin-report" >/dev/null
jq -e '(has("execution_changes") or has("execution_summary")) | not' "$work/text-shared-report" >/dev/null
for packet in regression-replayed text-replay; do
    build/batch-fixture emit "$work/$packet" clean > "$work/fixture-answer"
    build/jovovich-report "$work/$packet" "$work/fixture-answer" --json > "$work/change-report"
    jq -e '.reviews[0].choice.verdict=="CLEAN" and .execution_summary=={selected_runs:1,met:0,failed:1}
        and .execution_changes[0].head_matches_required==false' "$work/change-report" >/dev/null
    build/jovovich-report "$work/$packet" "$work/fixture-answer" > "$work/change-comment"
    grep -Fq '**Execution checks:** 0 met, 1 failed' "$work/change-comment"
    grep -Fq 'This run fails the measured requirement.' "$work/change-comment"
done
build/batch-fixture emit "$work/count-replayed" clean > "$work/count-answer"
build/jovovich-report "$work/count-replayed" "$work/count-answer" --json > "$work/count-report"
jq -e '.execution_changes | length==1 and .[0].metric=="count" and .[0].target=="paint"
    and .[0].base==1 and .[0].head==2 and .[0].required==2 and .[0].head_matches_required' "$work/count-report" >/dev/null
echo 'Counterexample capture, fresh paired replay, current oracle, branch and harness scope passed'

if test -n "${JOV_MEMORY_MODEL:-}"; then
    : "${JOV_MEMORY_TOKENIZER:?set the pinned tokenizer path}"
    cases='regression-replayed manual repair-replayed neutral-replayed neutral corrected'
    for name in $cases; do cat "$work/$name"; done > "$work/live"
    build/jovovich "$JOV_MEMORY_MODEL" "$JOV_MEMORY_TOKENIZER" --json --canonical-boundaries < "$work/live" > "$work/answers"
    i=0
    for name in $cases; do
        i=$((i+1))
        sed -n "${i}p" "$work/answers" > "$work/$name-answer"
        build/jovovich-report "$work/$name" "$work/$name-answer" > "$work/$name-report"
        sed -n 's/.*"choice":\({[^}]*}}\).*/\1/p' "$work/$name-answer" > "$work/$name-choice"
        sed -n 's/.*"boundary_view":{"policy":"signed-int-comparison\/1","prompt_sha256":"\([a-f0-9]*\)".*/\1/p' "$work/$name-answer" > "$work/$name-prompt"
        test "$(wc -c < "$work/$name-prompt")" -eq 65
        printf '%s ' "$name"; cat "$work/$name-choice"
    done
    cmp "$work/regression-replayed-prompt" "$work/manual-prompt"
    cmp "$work/neutral-replayed-prompt" "$work/neutral-prompt"
    cmp "$work/regression-replayed-choice" "$work/manual-choice"
    cmp "$work/neutral-replayed-choice" "$work/neutral-choice"
    grep -Fq 'Replayed counterexample' "$work/neutral-replayed-report"
    grep -Fq '"differing":0' "$work/neutral-replayed-answer"
    grep -Fq '"verdict":"CONCERN"' "$work/regression-replayed-choice"
    grep -Fq '"verdict":"CLEAN"' "$work/repair-replayed-choice"
    grep -Fq '"verdict":"CONCERN"' "$work/corrected-choice"
    sed 's/"mode":1,"base_commit"/"mode":2,"base_commit"/' "$work/regression-replayed-answer" > "$work/bad-answer"
    reject build/jovovich-report "$work/regression-replayed" "$work/bad-answer"
fi
