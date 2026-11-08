#!/bin/sh
# Live paired experiment. Run from the repository root with converted weights.
set -eu
if test "$#" -ne 3; then
    echo 'Usage: sh tests/run_quality.sh MODEL.gguf TOKENIZER.gguf NEW_OUTPUT_DIRECTORY' >&2
    exit 2
fi
root=$(pwd)
case "$1" in /*) model=$1 ;; *) model="$root/$1" ;; esac
case "$2" in /*) tokenizer=$2 ;; *) tokenizer="$root/$2" ;; esac
case "$3" in /*) out=$3 ;; ?*) out="$root/$3" ;; *) exit 2 ;; esac
if test -e "$out" || test -L "$out"; then echo "Output exists: $out" >&2; exit 1; fi
parent=$(dirname "$out")
out=$parent/$(basename "$out")
mkdir -p "$parent"
work=$(mktemp -d "$parent/.jovovich-quality-XXXXXXXX")
trap 'rm -rf "$work"' EXIT
trap 'exit 1' HUP INT TERM
result=$work/result
cases="$root/examples/quality-20261106"
mkdir "$work/aml" "$work/models" "$work/cases" "$result"
# Freeze both arms before either producer runs. Generation and verification
# then share the same files, even if the source checkout is edited mid-run.
cp aml/answer.aml aml/score-choices.aml "$work/aml/"
cp models/onejev-0.8b.json "$work/models/"
cp "$cases/inputs.jsonl" "$cases/expected.jsonl" "$cases/baseline-prepare.aml" "$cases/candidate-prepare.aml" "$work/cases/"
# This runner replays the registered 38-case experiment. Verify the same
# snapshot that generation and scoring will consume against its protocol.
cp "$cases/protocol.json" "$work/cases/protocol.json"
digest() { openssl dgst -sha256 < "$1" | awk '{print $NF}'; }
protocol=$work/cases/protocol.json
if test "$(digest "$protocol")" != 162e7a7301845ff1814e1e6a361476514e083995dd694282f35239bab65b7baa; then
    echo 'Unregistered quality experiment protocol' >&2; exit 1
fi
check_digest() {
    if test "$(digest "$work/$1")" != "$2"; then
        echo "Unregistered quality experiment file: $1" >&2
        return 1
    fi
}
registered() {
    expected=$(jq -er --arg key "$2" '.[$key]' "$protocol") || return 1
    check_digest "cases/$1" "$expected"
}
registered inputs.jsonl inputs_sha256
registered expected.jsonl expected_sha256
registered baseline-prepare.aml baseline_prompt_sha256
registered candidate-prepare.aml candidate_prompt_sha256
# These 38 inputs use the plain review path. The current production readout
# and manifest must reproduce that experiment on both question templates.
check_digest aml/score-choices.aml 4c363922f82788a55ab3a0986ee58a02d0c773d696cc260c202c732f19d1c80e
check_digest aml/answer.aml 8925b7e962fa4dfb51494c817d1fc333e11dd46f5206fa01f0683471b8a6e095
check_digest models/onejev-0.8b.json e0882cf66c03b8375c55185a154c1993108d8c687196339a75374a6248b66b46
for variant in baseline candidate; do
    cp "$work/cases/$variant-prepare.aml" "$work/aml/prepare.aml"
    if ! (cd "$work" && "$root/build/jovovich" "$model" "$tokenizer" --json < cases/inputs.jsonl) > "$result/$variant-answers.jsonl" 2> "$result/$variant.log"; then
        cat "$result/$variant.log" >&2
        exit 1
    fi
    (cd "$work" && "$root/build/score-quality" cases/expected.jsonl cases/inputs.jsonl "$result/$variant-answers.jsonl" aml/prepare.aml) > "$result/$variant-score.json"
done
sh tools/publish_directory.sh "$work" "$result" "$out"
printf 'Complete paired native run saved in %s\n' "$out"
