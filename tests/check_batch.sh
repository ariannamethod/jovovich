#!/bin/sh
set -eu
work=$(mktemp -d "${TMPDIR:-/tmp}/jovovich-batch-XXXXXX")
trap 'rm -rf "$work"' EXIT HUP INT TERM
git init -q -b main "$work"
git -C "$work" config user.name 'JOVOVICH batch fixture'
git -C "$work" config user.email 'fixture@example.invalid'
printf 'This C project uses only the standard C library. Network dependencies are forbidden.\nFunctions named square must return x * x.\n' > "$work/RULES.md"
printf 'int square(int x) { return x * x; }\n' > "$work/math.c"
printf 'int status(void) { return 0; }\n' > "$work/status.c"
git -C "$work" add .
GIT_AUTHOR_DATE='2026-11-06T00:00:00Z' GIT_COMMITTER_DATE='2026-11-06T00:00:00Z' git -C "$work" commit -qm base
base=$(git -C "$work" rev-parse HEAD)
printf 'int square(int x) { const int result = x * x; return result; }\n' > "$work/math.c"
printf '#include <curl/curl.h>\nint status(void) { CURL *h = curl_easy_init(); return h != 0; }\n' > "$work/status.c"
git -C "$work" add .
GIT_AUTHOR_DATE='2026-11-06T00:01:00Z' GIT_COMMITTER_DATE='2026-11-06T00:01:00Z' git -C "$work" commit -qm change
head=$(git -C "$work" rev-parse HEAD)
./build/jovovich-pack --all "$work" "$base" "$head" RULES.md > build/batch-input.jsonl
test "$(wc -l < build/batch-input.jsonl)" -eq 2
for mode in clean mixed tie; do
    ./build/batch-fixture emit build/batch-input.jsonl "$mode" > "build/batch-$mode.jsonl"
    ./build/jovovich-report build/batch-input.jsonl "build/batch-$mode.jsonl" --json > "build/report-$mode.json"
    concerns=1
    if test "$mode" = clean; then concerns=0; fi
    ./build/batch-fixture check "build/report-$mode.json" "$concerns"
done
# Two files can reach different outcomes under the same rule and raw model vote.
jq -c '. + {trace_evidence: {schema:"jovovich.paired-traces/1",review_id:.id,
    base_commit:.source.base_commit,head_commit:.source.head_commit,
    rule_sha256:.source.rules_sha256,change_sha256:.source.diff_sha256,metric:"text",
    runs:[{mode:0,base:"old",head:.file,required:(if .batch.index==0 then .file else "old" end)}]}}' \
    build/batch-input.jsonl > build/batch-executions.jsonl
./build/batch-fixture emit build/batch-executions.jsonl clean > build/batch-execution-votes.jsonl
./build/jovovich-report build/batch-executions.jsonl build/batch-execution-votes.jsonl --json > build/batch-execution-report.json
jq -e '.summary.verdict=="CLEAN" and .execution_summary=={selected_runs:2,met:1,failed:1}
    and [.execution_changes[].head_matches_required]==[true,false]
    and all(.execution_changes[]; .head==.file)' build/batch-execution-report.json >/dev/null
./build/jovovich-report build/batch-input.jsonl build/batch-mixed.jsonl > build/report-mixed.md
grep -q 'Reviewed files: 2' build/report-mixed.md
grep -q 'CONCERN 90.0%' build/report-mixed.md
grep -q 'math\\.c' build/report-mixed.md
reject() {
    if ./build/jovovich-report "$1" "$2" --json > build/report-rejected.json 2> build/report-rejected.log; then
        echo 'FAIL: incomplete/inconsistent report accepted' >&2;exit 1
    fi
    test ! -s build/report-rejected.json
}
head -n 1 build/batch-input.jsonl > build/batch-cut.jsonl
head -n 1 build/batch-clean.jsonl > build/answers-cut.jsonl
reject build/batch-cut.jsonl build/answers-cut.jsonl
reject build/batch-input.jsonl build/answers-cut.jsonl
{ sed -n '2p' build/batch-clean.jsonl; sed -n '1p' build/batch-clean.jsonl; } > build/answers-order.jsonl
reject build/batch-input.jsonl build/answers-order.jsonl
cat build/answers-cut.jsonl build/answers-cut.jsonl > build/answers-duplicate.jsonl
reject build/batch-input.jsonl build/answers-duplicate.jsonl
cat build/batch-clean.jsonl build/answers-cut.jsonl > build/answers-extra.jsonl
reject build/batch-input.jsonl build/answers-extra.jsonl
sed 's/"count":2/"count":1/g' build/batch-input.jsonl > build/batch-count.jsonl
reject build/batch-count.jsonl build/batch-clean.jsonl
sed 's/"index":1/"index":0/g' build/batch-input.jsonl > build/batch-index.jsonl
reject build/batch-index.jsonl build/batch-clean.jsonl
./build/batch-fixture emit build/batch-input.jsonl badhash > build/answers-badhash.jsonl
reject build/batch-input.jsonl build/answers-badhash.jsonl
sed 's#OmniJev/OneJev-0.8B#Wrong/Model#g' build/batch-clean.jsonl > build/answers-model.jsonl
reject build/batch-input.jsonl build/answers-model.jsonl
: > build/batch-empty.jsonl
reject build/batch-empty.jsonl build/batch-empty.jsonl
printf '{"unfinished":' > build/batch-malformed.jsonl
reject build/batch-malformed.jsonl build/batch-clean.jsonl
sed 's/"choice":{/"choice":{"verdict":"CLEAN","probabilities":{"CONCERN":0.1,"CLEAN":0.9}},"choice":{/' build/batch-mixed.jsonl > build/answers-duplicate-key.jsonl
reject build/batch-input.jsonl build/answers-duplicate-key.jsonl
sed 's/"CLEAN":0/"CLEAN":00/g' build/batch-clean.jsonl > build/answers-number.jsonl
reject build/batch-input.jsonl build/answers-number.jsonl
sed 's/"scope":"all_changed_paths","id":"./"scope":"all_changed_paths","id":"x/' build/batch-input.jsonl > build/batch-digest.jsonl
reject build/batch-digest.jsonl build/batch-clean.jsonl
readout=000000000000000000000000000000000000000000000000000000000000000a
sed 's/"execution":{/"execution":{"readout_sha256":"'"$readout"'",/' build/batch-clean.jsonl > build/answers-readout.jsonl
./build/jovovich-report build/batch-input.jsonl build/answers-readout.jsonl --json > build/report-readout.json
grep -Fq '"readout_sha256":"'"$readout"'","summary"' build/report-readout.json
sed '1s/"execution":{/"execution":{"readout_sha256":"bad",/' build/batch-clean.jsonl > build/answers-readout.jsonl
reject build/batch-input.jsonl build/answers-readout.jsonl
sed '1s/"execution":{/"execution":{"readout_sha256":"'"$readout"'",/' build/batch-clean.jsonl > build/answers-readout.jsonl
reject build/batch-input.jsonl build/answers-readout.jsonl
# The boundary accepts all 64 paths and refuses the 65th before emitting rows.
i=1
while test "$i" -le 62; do
    printf 'int value = 1;\n' > "$work/extra-$i.c"
    i=$((i+1))
done
git -C "$work" add .
git -C "$work" commit -qm boundary
./build/jovovich-pack --all "$work" "$base" HEAD RULES.md > build/batch-64.jsonl
test "$(wc -l < build/batch-64.jsonl)" -eq 64
printf 'int value = 1;\n' > "$work/extra-63.c"
git -C "$work" add .
git -C "$work" commit -qm overflow
if ./build/jovovich-pack --all "$work" "$base" HEAD RULES.md > build/batch-65.jsonl 2> build/batch-65.log; then exit 1; fi
test ! -s build/batch-65.jsonl
git -C "$work" checkout -q "$head"
# Any non-text changed path prevents publication of the whole input batch.
printf '\000binary' > "$work/z.bin"
git -C "$work" add z.bin
git -C "$work" commit -qm binary
if ./build/jovovich-pack --all "$work" "$base" HEAD RULES.md > build/batch-binary.jsonl 2> build/batch-binary.log; then exit 1; fi
test ! -s build/batch-binary.jsonl
printf 'Batch checks: 3 aggregate cases, 16 report refusals, 64/65-file boundary and whole-batch binary refusal passed\n'
# Reports retain unknown fields verbatim. Validate their bytes as carefully as
# known fields, including Unicode's scalar boundaries. POSIX printf %b emits
# these fixtures independent of the shell's locale.
unicode_answer() {
    { printf '{"annotation":"'; printf '%b' "$1"; printf '",'; cut -c 2- build/batch-clean.jsonl | sed -n '1p'; sed -n '2p' build/batch-clean.jsonl; } > build/answers-unicode.jsonl
}
unicode_answer '\0302\0200\0337\0277\0340\0240\0200\0355\0237\0277\0356\0200\0200\0357\0277\0277\0360\0220\0200\0200\0364\0217\0277\0277'
./build/jovovich-report build/batch-input.jsonl build/answers-unicode.jsonl --json > build/report-unicode.json
for bytes in '\0000' '\0300\0200' '\0340\0237\0277' '\0355\0240\0200' '\0360\0217\0277\0277' '\0364\0220\0200\0200' '\0377' '\0200' '\0342\0202' '\0342X\0200'; do
    unicode_answer "$bytes"
    reject build/batch-input.jsonl build/answers-unicode.jsonl
done
printf 'UTF-8 boundaries accepted; malformed, overlong, surrogate, out-of-range, truncated and NUL strings refused\n'
