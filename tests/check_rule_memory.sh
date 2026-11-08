#!/bin/sh
set -eu
work=$(mktemp -d "${TMPDIR:-/tmp}/jovovich-facts-XXXXXX")
trap 'rm -rf "$work"' EXIT HUP INT TERM
repo=$work/repo
store="$work/fact store"
mkdir "$store"
git init -q -b main "$repo"
git -C "$repo" config user.name 'JOVOVICH memory fixture'
git -C "$repo" config user.email fixture@example.invalid
export GIT_AUTHOR_DATE='2026-11-08T00:00:00Z' GIT_COMMITTER_DATE='2026-11-08T00:00:00Z'
old='draw must call scan then paint at both modes, 0 and 1.'
new='draw must call paint then scan at both modes, 0 and 1.'
rules() { printf 'Rendering rules\n%s\n' "$1" > "$repo/RULES.md"; }
draw() {
    printf '%s\n' 'void scan(void); void paint(void);' "$1" > "$repo/draw.c"
}
broken='void draw(int mode){ if(mode){paint();scan();} else {scan();paint();} }'
fixed='void draw(int mode){ (void)mode; scan();paint(); }'
commit() {
    git -C "$repo" add .
    git -C "$repo" commit -qm "$1"
    git -C "$repo" rev-parse HEAD
}
pack() { build/jovovich-pack "$@"; }
remember() { pack --remember "$store" fixture/render draw-order "$@"; }
recall() { pack --recall "$store" fixture/render draw-order "$@"; }
fact() { pack --fact "$store" fixture/render draw-order "$@"; }
reject() {
    if "$@" > "$work/rejected" 2> "$work/error"; then
        echo "unexpected success: $*" >&2; exit 1
    fi
    test ! -s "$work/rejected"
}
rules "$old"; draw "$broken"; base1=$(commit initial)
draw "$fixed"; head1=$(commit repair)
draw "$broken"; base2=$(commit 'another import of draw')
draw "$fixed"; head2=$(commit 'repair the second import')
rules "$new"; draw "$broken"; base3=$(commit 'change the callback agreement')
draw "$fixed"; head3=$(commit 'review the same change under the new agreement')

reject fact
test ! -e "$store/rules.checkpoint"
reject remember --all "$repo" "$base1" "$base1" RULES.md 2 2
test ! -e "$store/rules.checkpoint"
remember --all "$repo" "$base1" "$head1" RULES.md 2 2 > "$work/first"
fact > "$work/receipt1"
grep -Fq '"sequence":1,"supersedes":0' "$work/receipt1"
grep -Fq "$head1" "$work/receipt1"
# Retrying a committed operation yields its original clock and receipt.
remember --all "$repo" "$base1" "$head1" RULES.md 2 2 > "$work/retried"
cmp "$work/first" "$work/retried"
recall --all "$repo" "$base2" "$head2" > "$work/second"
grep -Fq "$head1" "$work/second"
grep -Fq "$head2" "$work/second"
# A repository-local view of history cannot create a parent for an orphan
# or hide a real parent that is present in the object store.
orphan=$(git -C "$repo" -c commit.gpgSign=false commit-tree "$base1^{tree}" -m 'separate history')
orphan_head=$(git -C "$repo" -c commit.gpgSign=false commit-tree "$head1^{tree}" -p "$orphan" -m 'separate fix')
reject recall --all "$repo" "$orphan" "$orphan_head"
printf '%s %s\n' "$orphan" "$base1" > "$repo/.git/info/grafts"
git -C "$repo" -c advice.graftFileDeprecated=false merge-base --is-ancestor "$base1" "$orphan"
reject recall --all "$repo" "$orphan" "$orphan_head"
reject pack "$repo" "$orphan^" "$head1" RULES.md draw.c
recall --all "$repo" "$base2" "$head2" > "$work/with-graft"
cmp "$work/second" "$work/with-graft"
rm "$repo/.git/info/grafts"
printf '%s\n' "$base2" > "$repo/.git/shallow"
if git -C "$repo" merge-base --is-ancestor "$base1" "$base2"; then exit 1; fi
recall --all "$repo" "$base2" "$head2" > "$work/with-shallow-boundary"
cmp "$work/second" "$work/with-shallow-boundary"
pack "$repo" "$base2^" "$base2" RULES.md draw.c > "$work/parent-expression"
jq -e --arg parent "$head1" '.source.base_commit==$parent' "$work/parent-expression" >/dev/null
rm "$repo/.git/shallow"
# A real shallow clone can review the available pair, and cannot authenticate
# a named fact whose origin lies beyond its available history.
git -C "$repo" branch local-pair "$head2"
git clone -q --no-local --depth=2 --branch local-pair "$repo" "$work/shallow"
pack "$work/shallow" "$base2" "$head2" RULES.md draw.c > "$work/available-pair"
reject recall --all "$work/shallow" "$base2" "$head2"
reject pack --fact "$store" unrelated/render draw-order
reject pack --fact "$store" fixture/render missing-key
reject recall --all "$repo" "$base3" "$head3"
reject remember --all "$repo" "$base3" "$head3" RULES.md 2 2
remember --supersedes 1 --all "$repo" "$base3" "$head3" RULES.md 2 2 > "$work/updated"
recall --all "$repo" "$base3" "$head3" > "$work/third"
cmp "$work/updated" "$work/third"
fact > "$work/receipt2"
grep -Fq '"sequence":2,"supersedes":1' "$work/receipt2"
grep -Fq "$new" "$work/receipt2"
fact --as-of 1 > "$work/then"
cmp "$work/then" "$work/receipt1"
reject fact --as-of 3
reject recall --all "$repo" "$base2" "$head2"
reject recall --as-of 1 --all "$repo" "$base3" "$head3"
recall --as-of 1 --all "$repo" "$base2" "$head2" > "$work/replayed"
cmp "$work/second" "$work/replayed"
pack --all "$repo" "$base2" "$head2" RULES.md 2 2 > "$work/manual"
recall --as-of 1 "$repo" "$base2" "$head2" draw.c > "$work/one-file"
grep -Fq '"fact":{' "$work/one-file"

build/batch-fixture emit "$work/second" clean > "$work/synthetic"
build/jovovich-report "$work/second" "$work/synthetic" > "$work/report"
grep -Fq 'Remembered rule' "$work/report"
grep -Fq "$head1" "$work/report"
sed 's/"sequence":1/"sequence":2/' "$work/synthetic" > "$work/tamper"
reject build/jovovich-report "$work/second" "$work/tamper"
sed 's/"sequence":1/"sequence":2/' "$work/second" > "$work/tamper"
reject build/jovovich-report "$work/tamper" "$work/synthetic"

# Both processes expect receipt 2. Distinct proposals can have only one winner.
remember --supersedes 2 --all "$repo" "$base1" "$head1" RULES.md 2 2 > "$work/race1" 2>/dev/null & p1=$!
remember --supersedes 2 --all "$repo" "$base2" "$head2" RULES.md 2 2 > "$work/race2" 2>/dev/null & p2=$!
wins=0
if wait "$p1"; then wins=$((wins+1)); fi
if wait "$p2"; then wins=$((wins+1)); fi
test "$wins" -eq 1
fact | grep -F '"sequence":3,"supersedes":2' >/dev/null
pack --remember "$store" another/project draw-order --all "$repo" "$base3" "$head3" RULES.md 2 2 > "$work/other"
grep -Fq '"sequence":4,"supersedes":0' "$work/other"
fact > "$work/after-other"
grep -Fq '"sequence":3,"supersedes":2' "$work/after-other"
mkdir "$work/damaged"
printf 'torn' > "$work/damaged/rules.checkpoint"
reject pack --remember "$work/damaged" fixture/render draw-order --all "$repo" "$base3" "$head3" RULES.md 2 2
test "$(cat "$work/damaged/rules.checkpoint")" = torn
echo 'AML fact memory: restart, two Git reviews, correction, as-of replay, source binding, isolation and concurrent writers passed'

if test -n "${JOV_MEMORY_MODEL:-}"; then
    : "${JOV_MEMORY_TOKENIZER:?set the pinned tokenizer path}"
    cat > "$work/driver.c" <<'DRIVER'
#include <stdio.h>
#include <stdlib.h>
void scan(void) { puts("scan"); }
void paint(void) { puts("paint"); }
void draw(int mode);
int main(int argc, char **argv) { if (argc != 2) return 1; draw(atoi(argv[1])); return 0; }
DRIVER
    add_trace() {
        input=$1; base=$2; head=$3; order=$4
        for rev in "$base" "$head"; do
            git -C "$repo" show "$rev:draw.c" > "$work/body.c"
            "${CC:-cc}" "$work/body.c" "$work/driver.c" -o "$work/$rev"
        done
        id=$(sed 's/^{"id":"\([^"]*\)".*/\1/' "$input")
        rh=$(sed 's/.*"rules_sha256":"\([^"]*\)".*/\1/' "$input")
        dh=$(sed 's/.*"diff_sha256":"\([^"]*\)".*/\1/' "$input")
        row=$(sed 's/}$//' "$input")
        printf '%s,"trace_evidence":{"schema":"jovovich.paired-traces/1","review_id":"%s","rule_sha256":"%s","change_sha256":"%s",' "$row" "$id" "$rh" "$dh"
        printf '"base_commit":"%s","head_commit":"%s","metric":"sequence","runs":[' "$base" "$head"
        for mode in 0 1; do
            before=$("$work/$base" "$mode" | paste -sd, -)
            after=$("$work/$head" "$mode" | paste -sd, -)
            test "$mode" = 0 || printf ','
            printf '{"mode":%d,"required":["%s","%s"],"base":["%s","%s"],"head":["%s","%s"]}' "$mode"                 "${order%,*}" "${order#*,}" "${before%,*}" "${before#*,}" "${after%,*}" "${after#*,}"
        done
        printf ']}}\n'
    }
    add_trace "$work/second" "$base2" "$head2" scan,paint > "$work/recall-trace"
    add_trace "$work/manual" "$base2" "$head2" scan,paint > "$work/manual-trace"
    add_trace "$work/third" "$base3" "$head3" paint,scan > "$work/corrected-trace"
    cat "$work/recall-trace" "$work/manual-trace" "$work/corrected-trace" > "$work/live-input"
    build/jovovich "$JOV_MEMORY_MODEL" "$JOV_MEMORY_TOKENIZER" --json --canonical-boundaries < "$work/live-input" > "$work/live-answers"
    index=0
    for name in recall manual corrected; do
        index=$((index+1))
        sed -n "${index}p" "$work/live-answers" > "$work/$name-answer"
        build/jovovich-report "$work/$name-trace" "$work/$name-answer" > "$work/$name-report"
        sed -n 's/.*"choice":\({[^}]*}}\).*/\1/p' "$work/$name-answer" > "$work/$name-choice"
        printf '%s ' "$name"; cat "$work/$name-choice"
    done
    cmp "$work/recall-choice" "$work/manual-choice"
    grep -Fq '"verdict":"CLEAN"' "$work/recall-choice"
    grep -Fq '"verdict":"CONCERN"' "$work/corrected-choice"
    grep -Fq 'supersedes 1' "$work/corrected-report"
fi
