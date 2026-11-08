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

# Opening the answer FIFO marks the point at which the scorer has captured
# its controls. Keep the first receipt back until the named file has changed.
root=$PWD
tmp=$(mktemp -d)
writer=
trap 'if test -n "$writer"; then kill "$writer" 2>/dev/null || :; fi; rm -rf "$tmp"' EXIT
trap 'exit 1' HUP INT TERM
mkdir "$tmp/aml"; ln -s "$root/models" "$tmp/models"
cp aml/trace-witness.aml aml/text-threshold.aml "$tmp/aml/"
mkfifo "$tmp/answer-stream"
cd "$tmp"
score() { "$root/build/score-quality" --text-threshold 0 labels inputs "$1" prepare.aml; }
swap_and_score() {
    # Redirection synchronizes reader and writer without a clock or sleep.
    (case "$1" in
        labels) sed 's/"expected":"CLEAN"/"expected":"TEMP"/;s/"expected":"CONCERN"/"expected":"CLEAN"/;s/"expected":"TEMP"/"expected":"CONCERN"/' labels > inverted
                cat inverted > labels ;;
        inputs) printf '{}\n' > inputs ;;
        prepare) printf 'question = "changed"\n' > prepare.aml ;;
        threshold) printf 'text_verdict = "CLEAN"\n' > aml/text-threshold.aml ;;
    esac
    cat "$2") > answer-stream &
    writer=$!
    score answer-stream > observed
    wait "$writer"; writer=
    cmp reference observed
}
# Whitespace is valid JSON and part of the hash. Pad the label set so stdio
# cannot prefetch all its rows before the first answer arrives.
awk '{printf "%s%1024s\n", $0,""}' "$root/$cases/expected.jsonl" > gold
for change in labels inputs prepare; do
    cp gold labels
    cp "$root/$cases/inputs.jsonl" inputs
    cp "$root/$cases/baseline-prepare.aml" prepare.aml
    score "$root/$cases/baseline-answers.jsonl" > reference
    swap_and_score "$change" "$root/$cases/baseline-answers.jsonl"
done
# The optional evaluation policy must also execute the bytes it reports.
jq -c '.trace_evidence |= (.metric="text" | .runs |= map(.base |= join(" ") | .head |= join(" ") | .required |= join(" ")))' \
    "$root/$fixture/git-input.jsonl" > inputs
cp "$root/build/quality-callback-label.jsonl" labels
cp "$root/aml/prepare.aml" prepare.aml
(cd "$root" && build/batch-fixture emit "$tmp/inputs" clean) > answers
score answers > reference
jq -e '.cases[0] | .threshold_applied and .predicted=="CONCERN" and .raw_predicted=="CLEAN"' reference >/dev/null
swap_and_score threshold answers
# The trace witness also contributes to the prompt. A synchronized replacement
# must preserve a genuine receipt and cannot corroborate a different observation.
cp "$root/aml/text-threshold.aml" aml/text-threshold.aml
sed 's/gate_observed)/"never returned")/' "$root/aml/trace-witness.aml" > other-witness.aml
cp other-witness.aml aml/trace-witness.aml
cp prepare.aml aml/prepare.aml
"$root/build/batch-fixture" emit inputs clean > other-answers
cp "$root/aml/trace-witness.aml" aml/trace-witness.aml
(cp other-witness.aml aml/trace-witness.aml; cat other-answers) > answer-stream &
writer=$!
if score answer-stream > rejected 2> reason; then exit 1; fi
wait "$writer"; writer=
test ! -s rejected
cp "$root/aml/trace-witness.aml" aml/trace-witness.aml
# The named threshold option executes the published text rule. An external
# decision file would let its behavior change without changing its root hash.
for source in 'IMPORT "decision.aml"' 'text_verdict = file_read_slice("decision.txt", 0, 32)'; do
    printf '%s\n' "$source" > aml/text-threshold.aml
    printf 'text_verdict = "CLEAN"\n' > aml/decision.aml
    printf CLEAN > aml/decision.txt
    if score answers > rejected 2> reason; then exit 1; fi
    grep -Fq 'Unregistered AML policy for --text-threshold' reason
    test ! -s rejected
done
# Custom AML can include other files and perform explicit side effects. Pin
# the rendered questions and prompts and execute every row exactly once.
cp "$root/aml/text-threshold.aml" aml/text-threshold.aml
cp "$root/$cases/inputs.jsonl" inputs
cp "$root/$cases/expected.jsonl" labels
cp "$root/$cases/baseline-prepare.aml" question.aml
printf 'row_no = row_no + 1\nassert(row_no <= 38, "too many reviews")\nassert(file_append_line("reviewed.log", "review"), "write failed")\nIMPORT "question.aml"\n' > prepare.aml
score "$root/$cases/baseline-answers.jsonl" > observed
test "$(wc -l < reviewed.log)" -eq 38
registered=$(jq -er 'select(.all.correct==30) | .rendered_prompts_sha256' observed)
rm reviewed.log
(cp "$root/$cases/candidate-prepare.aml" question.aml; cat "$root/$cases/candidate-answers.jsonl") > answer-stream &
writer=$!
if "$root/build/score-quality" --expect-prompts "$registered" --text-threshold 0 labels inputs answer-stream prepare.aml > rejected 2> reason; then exit 1; fi
wait "$writer"; writer=
test ! -s rejected
grep -Fq 'Rendered AML prompts differ' reason
test "$(wc -l < reviewed.log)" -eq 38
score "$root/$cases/candidate-answers.jsonl" > changed
jq -e --slurpfile before observed '.all.correct==28 and .prepare_sha256==$before[0].prepare_sha256 and
    .rendered_prompts_sha256!=$before[0].rendered_prompts_sha256' changed >/dev/null
printf 'Verified frozen label, input, prepare and active threshold bytes across synchronized file mutations\n'
