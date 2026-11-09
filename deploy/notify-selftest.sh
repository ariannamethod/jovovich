#!/bin/sh
# Self-test for the CONCERN -> wake wiring. No model, no network, no real claude.
# Exits 0 and prints PASS when the emit filter and the wake hand-off both hold.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
q="$work/queue"

# 1. A CLEAN answer drops nothing.
sh "$here/notify-on-concern.sh" \
    "$root/examples/run-selection/git-answer.jsonl" "$q" pr-demo >/dev/null
test "$(ls "$q" 2>/dev/null | wc -l | tr -d ' ')" = "0" \
    || { echo "FAIL: CLEAN produced a tag"; exit 1; }

# 2. A crafted CONCERN answer drops exactly one tag carrying id + concern prob.
concern="$work/concern.jsonl"
printf '%s\n' '{"id":"abc123","scope":{"file":"draw.c"},"choice":{"verdict":"CONCERN"},"probabilities":{"CONCERN":0.82,"CLEAN":0.18}}' > "$concern"
n=$(sh "$here/notify-on-concern.sh" "$concern" "$q" pr-42)
test "$n" = "1" || { echo "FAIL: expected 1 tag, got $n"; exit 1; }
test -f "$q/abc123.json" || { echo "FAIL: tag file missing"; exit 1; }
jq -e '.verdict=="CONCERN" and .concern==0.82 and .pr=="pr-42"' \
    "$q/abc123.json" >/dev/null || { echo "FAIL: tag contents wrong"; exit 1; }

# 3. The wake dry-run names the queue and the PR, and spawns no claude.
out=$(JOV_WAKE_DRY=1 sh "$here/wake-claude.sh" "$q")
printf '%s' "$out" | grep -q 'claude -p' || { echo "FAIL: no claude -p"; exit 1; }
printf '%s' "$out" | grep -qF "$q"      || { echo "FAIL: queue path missing"; exit 1; }
printf '%s' "$out" | grep -q 'pr-42'    || { echo "FAIL: PR missing"; exit 1; }

echo PASS
