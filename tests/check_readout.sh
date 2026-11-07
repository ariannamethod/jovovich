#!/bin/sh
set -eu
work=$(mktemp -d "${TMPDIR:-/tmp}/jovovich-readout-test-XXXXXX")
trap 'rm -rf "$work"' EXIT
sh tools/build_corpus.sh "$work/corpus" >/dev/null
# The test vector contains only the target sign. This fixture tests optimization
# and strict dataset binding independently of the recorded OneJev experiment.
awk -F'"' '
    /"weights_sha256"/ {w=$4}
    /"tokenizer_sha256"/ {t=$4}
    END {print w,t}
' models/onejev-0.8b.json > "$work/digests"
read -r weights tokenizer < "$work/digests"
sha256() {
    if command -v sha256sum >/dev/null; then sha256sum; else shasum -a 256; fi
}
fixture() {
    index=0
    while IFS= read -r row; do
        case "$row" in
            *'"completion":"A"'*) sign=1; label=CONCERN ;;
            *'"completion":"B"'*) sign=-1; label=CLEAN ;;
            *)
                # Pinned form-evaluation rows alternate by mutation within each pair.
                if test $((index%2)) -eq 1; then sign=1; label=CONCERN; else sign=-1; label=CLEAN; fi ;;
        esac
        index=$((index+1))
        id=$(printf '%s' "$row" | cut -d'"' -f4)
        digest=$(printf '%s\n' "$row" | sha256 | cut -d' ' -f1)
        printf '{"id":"%s","family":"fixture","expected":"%s"}\n' "$id" "$label" >> "$3"
        printf '{"schema":"jovovich.features/1","id":"%s","input_sha256":"%s","weights_sha256":"%s","tokenizer_sha256":"%s","logit_a":0,"logit_b":0,"hidden":[' "$id" "$digest" "$weights" "$tokenizer" >> "$2"
        awk -v s="$sign" 'BEGIN {printf "%d",s;for(i=1;i<1024;i++)printf ",0";print "]}"}' >> "$2"
    done < "$1"
}
fixture "$work/corpus/train.jsonl" "$work/features" "$work/expected"
run=./build/jovovich-readout
"$run" fit "$work/corpus/train.jsonl" "$work/features" > "$work/adapter"
score() { "$run" score "$work/corpus/train.jsonl" "$1" "$work/expected" "$2"; }
score "$work/features" "$work/adapter" > "$work/score"
grep -Fq '"rows":128,"base_correct":64,"readout_correct":128,"lost_correct_concerns":0' "$work/score"
reject() {
    if "$@" > "$work/bad-output" 2>/dev/null; then echo 'Invalid readout run accepted' >&2; exit 1; fi
    test ! -s "$work/bad-output"
}
sed '1d' "$work/features" > "$work/short"
reject score "$work/short" "$work/adapter"
sed '1s/"input_sha256":"./"input_sha256":"x/' "$work/features" > "$work/wrong-input"
reject score "$work/wrong-input" "$work/adapter"
sed 's/"scale":[^,]*/"scale":0/' "$work/adapter" > "$work/bad-adapter"
reject score "$work/features" "$work/bad-adapter"
reject "$run" fit "$work/corpus/eval-inputs.jsonl" "$work/features"
echo 'Readout fit, paired score and provenance checks passed'

sh tools/build_corpus.sh --equivalent-forms "$work/forms" >/dev/null
cmp "$work/forms/manifest.json" examples/equivalent-boundaries/manifest.json
fixture "$work/forms/train.jsonl" "$work/form-train" "$work/form-training-gold"
fixture "$work/forms/eval-inputs.jsonl" "$work/form-eval" "$work/form-eval-gold"
for mode in equivalent paired; do
    "$run" "fit-$mode" "$work/forms/train.jsonl" "$work/form-train" > "$work/$mode"
done
forms() {
    "$run" score-forms "$work/forms/eval-inputs.jsonl" "$work/form-eval" "$work/forms/eval-expected.jsonl" "$work/adapter" "$1" "$2"
}
forms "$work/equivalent" "$work/paired" > "$work/form-score"
grep -Fq '"name":"base","correct":48,"by_form":[12,12,12,12],"correct_mutation_pairs":0,"ranked_pairs":0,"stable_cases":24,"complete_groups":0' "$work/form-score"
test "$(grep -c '"correct_mutation_pairs":48,"ranked_pairs":48,"stable_cases":24,"complete_groups":12' "$work/form-score")" -eq 3
reject forms "$work/paired" "$work/equivalent"
reject "$run" fit-paired "$work/corpus/train.jsonl" "$work/features"
echo 'Equivalent corpus, complete groups, mutation pairs, exact ties and checkpoint binding passed'
