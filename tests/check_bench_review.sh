#!/bin/sh
set -eu
root=$(pwd)
work=$(mktemp -d "${TMPDIR:-/tmp}/jov-bench-XXXXXX")
trap 'rm -rf "$work"' EXIT
cd "$work"
mkdir build
ln -s "$root/examples" examples
cat > build/jovovich <<'SH'
#!/bin/sh
set -eu
test "$3" = --json && test "$4" = --canonical-boundaries || exit 1
ref=examples/run-selection/git-answer.jsonl
IFS= read -r fixture < examples/run-selection/git-input.jsonl
count=0
while IFS= read -r row; do
    test "$row" = "$fixture"
    count=$((count + 1))
    case "$1:$count" in
        missing:4) exit 0 ;;
        probability:4) sed 's/"CLEAN":0\.[0-9]*/"CLEAN":0.9/' "$ref" ;;
        hash:4) sed 's/"prompt_sha256":"./"prompt_sha256":"x/g' "$ref" ;;
        *) cat "$ref" ;;
    esac
done
test "$count" = 6
case "$1" in extra) cat "$ref" ;; failed) exit 1 ;; esac
SH
chmod +x build/jovovich
"$root/build/bench-review" ok fixture > timing.json
grep -Fq '"resident_median_ms":' timing.json
for case_name in missing probability hash extra failed; do
    if "$root/build/bench-review" "$case_name" fixture > timing.json 2>diagnostic; then
        echo "Benchmark accepted $case_name" >&2
        exit 1
    fi
    test ! -s timing.json
done
echo 'Verified six serial answers and rejection of incomplete or changed benchmark runs'
