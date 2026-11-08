#!/bin/sh
set -eu
cases=examples/quality-20261106
for variant in baseline candidate; do
    ./build/score-quality "$cases/expected.jsonl" "$cases/inputs.jsonl" "$cases/$variant-answers.jsonl" "$cases/$variant-prepare.aml" > "build/quality-$variant-score.json"
    cmp "$cases/$variant-score.json" "build/quality-$variant-score.json"
done
reject() {
    if ./build/score-quality "$1" "$cases/inputs.jsonl" "$2" "$cases/baseline-prepare.aml" > build/quality-rejected.json 2> build/quality-rejected.log; then
        echo 'FAIL: incomplete or inconsistent quality run accepted' >&2;exit 1
    fi
    test ! -s build/quality-rejected.json
}
head -n 1 "$cases/baseline-answers.jsonl" > build/quality-short.jsonl
reject "$cases/expected.jsonl" build/quality-short.jsonl
{ sed -n '2p' "$cases/expected.jsonl"; sed -n '1p' "$cases/expected.jsonl"; sed -n '3,$p' "$cases/expected.jsonl"; } > build/quality-wrong-order.jsonl
reject build/quality-wrong-order.jsonl "$cases/baseline-answers.jsonl"
sed 's/"verdict":"CLEAN"/"verdict":"CONCERN"/g' "$cases/baseline-answers.jsonl" > build/quality-wrong-verdict.jsonl
reject "$cases/expected.jsonl" build/quality-wrong-verdict.jsonl
sed '1s/"execution":{/"execution":{"readout_sha256":"000000000000000000000000000000000000000000000000000000000000000a",/' "$cases/baseline-answers.jsonl" > build/quality-mixed-readout.jsonl
reject "$cases/expected.jsonl" build/quality-mixed-readout.jsonl
for invalid in NaN inf -0.01 1.01 0.5junk; do
    if ./build/score-quality --text-threshold "$invalid" "$cases/expected.jsonl" "$cases/inputs.jsonl" "$cases/baseline-answers.jsonl" "$cases/baseline-prepare.aml" > build/quality-rejected.json 2> build/quality-rejected.log; then
        echo "Invalid threshold accepted: $invalid" >&2; exit 1
    fi
    test ! -s build/quality-rejected.json
done
# A zero threshold would flag everything if the policy escaped its text gate.
./build/score-quality --text-threshold 0 "$cases/expected.jsonl" "$cases/inputs.jsonl" "$cases/baseline-answers.jsonl" "$cases/baseline-prepare.aml" > build/quality-source-threshold.json
test "$(grep -o '"threshold_applied":false' build/quality-source-threshold.json | wc -l)" -eq 38
fixture=examples/run-selection
printf '%s\n' '{"id":"fa54d44aeecaad16ce1b97dd3111e012ae020e792d8f9872307f014cedc3373c","split":"transfer","family":"callback","expected":"CLEAN"}' > build/quality-callback-label.jsonl
./build/score-quality --text-threshold 0 build/quality-callback-label.jsonl "$fixture/git-input.jsonl" "$fixture/git-answer.jsonl" aml/prepare.aml > build/quality-callback-threshold.json
grep -q '"predicted":"CLEAN","raw_predicted":"CLEAN","threshold_applied":false' build/quality-callback-threshold.json
printf 'Quality scoring: both complete 38-case native runs verified; truncation, swapped expectations and altered verdicts refused\n'
