#!/bin/sh
# Exercise the real runner and scorer with recorded model receipts.
set -eu
root=$(pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
trap 'exit 1' HUP INT TERM
records=${QUALITY_TEST_RECORDS:-$root/examples/quality-20261106}
export QUALITY_RECEIPTS=$records
export QUALITY_CASES=$root/examples/quality-20261106
mkdir -p "$tmp/repo/build" "$tmp/repo/examples"
cp -R "$root/aml" "$root/models" "$tmp/repo/"
cp -R "$QUALITY_CASES" "$tmp/repo/examples/quality-20261106"
ln -s "$root/tools" "$tmp/repo/tools"
export QUALITY_REPO="$root"
cat > "$tmp/repo/build/score-quality" <<'SCORER'
#!/bin/sh
set -eu
"$QUALITY_REPO/build/score-quality" "$@"
if test -n "${MUTATE_CHECKOUT:-}" && test "${3##*/}" = baseline-answers.jsonl; then
    # Baseline has been scored; replace the same named files before candidate.
    src=$MUTATE_CHECKOUT/examples/quality-20261106
    sed 's/"expected":"CLEAN"/"expected":"TEMP"/;s/"expected":"CONCERN"/"expected":"CLEAN"/;s/"expected":"TEMP"/"expected":"CONCERN"/' "$src/expected.jsonl" > "$src/other"
    mv "$src/other" "$src/expected.jsonl"
    for source in "$src/inputs.jsonl" "$src/candidate-prepare.aml" "$MUTATE_CHECKOUT"/aml/*.aml \
        "$MUTATE_CHECKOUT/models/onejev-0.8b.json"; do
        printf 'changed\n' > "$source"
    done
    : > "$MUTATE_CHECKOUT/swapped"
fi
SCORER
chmod +x "$tmp/repo/build/score-quality"
cat > "$tmp/repo/build/jovovich" <<'PRODUCER'
#!/bin/sh
set -eu
cmp - "$QUALITY_CASES/inputs.jsonl"
for policy in answer score-choices; do
    cmp "aml/$policy.aml" "$QUALITY_REPO/aml/$policy.aml"
done
cmp models/onejev-0.8b.json "$QUALITY_REPO/models/onejev-0.8b.json"
cmp -s aml/prepare.aml "$QUALITY_CASES/baseline-prepare.aml" && arm=baseline || arm=candidate
cmp aml/prepare.aml "$QUALITY_CASES/$arm-prepare.aml"
test "${FAIL_ARM:-}" != "$arm" || { echo "failed $arm" >&2; exit 1; }
cat "$QUALITY_RECEIPTS/$arm-answers.jsonl"
PRODUCER
chmod +x "$tmp/repo/build/jovovich"
cd "$tmp/repo"
run() { sh "$root/tests/run_quality.sh" weights tokenizer "$1"; }
must_fail() {
    if run "$1" > "$tmp/output" 2>&1; then echo "Unexpected publication: $1" >&2; exit 1; fi
}
verify() {
    test "$(ls -A "$1" | wc -l)" -eq 6
    for arm in baseline candidate; do
        cmp "$records/$arm-answers.jsonl" "$1/$arm-answers.jsonl"
        cmp "$records/$arm-score.json" "$1/$arm-score.json"
        test -f "$1/$arm.log"
    done
}
FAIL_ARM=candidate must_fail "$tmp/failed"
grep -q 'failed candidate' "$tmp/output"
test ! -e "$tmp/failed"
run "$tmp/complete"
verify "$tmp/complete"
printf 'existing log\n' > "$tmp/complete/baseline.log"
FAIL_ARM=baseline must_fail "$tmp/complete"
verify "$tmp/complete"
grep -Fxq 'existing log' "$tmp/complete/baseline.log"
ln -s "$tmp/complete" "$tmp/link"
must_fail "$tmp/link"
test -L "$tmp/link"
verify "$tmp/complete"
ln -s "$tmp/absent" "$tmp/dangling"
must_fail "$tmp/dangling"
test -L "$tmp/dangling"
test ! -e "$tmp/absent"
cat > "$tmp/cc-claim" <<'CC'
#!/bin/sh
mkdir "$CLAIMED_DIR"
exec "$REAL_CC" "$@"
CC
chmod +x "$tmp/cc-claim"
CLAIMED_DIR="$tmp/claimed" REAL_CC="${CC:-cc}" CC="$tmp/cc-claim" must_fail "$tmp/claimed"
test -d "$tmp/claimed"
test -z "$(ls -A "$tmp/claimed")"
test -z "$(find "$tmp" -name '.jovovich-quality-*' -print)"
# A caller can change both arms consistently before the run. The registered
# experiment still has to reject those bytes, including a rewritten protocol.
cases=examples/quality-20261106
for file in inputs.jsonl expected.jsonl baseline-prepare.aml candidate-prepare.aml protocol.json; do
    printf '\n' >> "$cases/$file"
    must_fail "$tmp/unregistered"
    grep -q 'Unregistered quality experiment' "$tmp/output"
    test ! -e "$tmp/unregistered"
    cp "$QUALITY_CASES/$file" "$cases/$file"
done
for file in aml/score-choices.aml aml/answer.aml models/onejev-0.8b.json; do
    case $file in
        aml/score-choices.aml) printf 'probabilities = [1, 0]\n' > "$file" ;;
        *) printf '\n' >> "$file" ;;
    esac
    must_fail "$tmp/unregistered"
    grep -Fqx "Unregistered quality experiment file: $file" "$tmp/output"
    test ! -e "$tmp/unregistered"
    cp "$root/$file" "$file"
done
MUTATE_CHECKOUT="$tmp/repo" run "$tmp/changed"
test -f "$tmp/repo/swapped"
verify "$tmp/changed"
echo 'Verified frozen paired inputs and policies, paired publication, existing results, symlinks, competing empty directory, and failed second arm'
