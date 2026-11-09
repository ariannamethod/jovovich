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

# 3. The wake dry-run names the queue and the PR, locks the woken reviewer to
#    read-only tools, frames the content as untrusted, and spawns no claude.
out=$(JOV_WAKE_DRY=1 sh "$here/wake-claude.sh" "$q")
printf '%s' "$out" | grep -q 'claude -p'                       || { echo "FAIL: no claude -p"; exit 1; }
printf '%s' "$out" | grep -qF "$q"                             || { echo "FAIL: queue path missing"; exit 1; }
printf '%s' "$out" | grep -q 'pr-42'                           || { echo "FAIL: PR missing"; exit 1; }
printf '%s' "$out" | grep -q -- '--restricted'                 || { echo "FAIL: restricted mode missing"; exit 1; }
printf '%s' "$out" | grep -q -- '--tools Read,Grep,Glob'       || { echo "FAIL: fail-closed tool set missing"; exit 1; }
printf '%s' "$out" | grep -q -- '--strict-mcp-config'          || { echo "FAIL: ambient MCP not disabled"; exit 1; }
printf '%s' "$out" | grep -q -- '--permission-prompts none'    || { echo "FAIL: prompt-deny layer missing"; exit 1; }
printf '%s' "$out" | grep -qi 'untrusted'                      || { echo "FAIL: untrusted framing missing"; exit 1; }
if printf '%s' "$out" | grep -q 'Bash'; then echo "FAIL: Bash reachable by woken reviewer"; exit 1; fi

# 4. A crafted non-hex id is refused, so no tag is written anywhere (the id
#    would otherwise be used verbatim as a path). The queue sits three levels
#    under $work, so a successful ../../pwned write would land at
#    $work/a/pwned.json; the gate must leave nothing there and emit zero tags.
evil="$work/evil.jsonl"
printf '%s\n' '{"id":"../../pwned","scope":{"file":"x"},"choice":{"verdict":"CONCERN"},"probabilities":{"CONCERN":0.9,"CLEAN":0.1}}' > "$evil"
deep="$work/a/b/queue"
m=$(sh "$here/notify-on-concern.sh" "$evil" "$deep" pr-evil 2>/dev/null)
test "$m" = "0" || { echo "FAIL: non-hex id written ($m)"; exit 1; }
test ! -e "$work/a/pwned.json" || { echo "FAIL: path traversal wrote outside queue"; exit 1; }

# 5. The queue is owner-only.
mode=$(stat -f '%Lp' "$q")
test "$mode" = "700" || { echo "FAIL: queue mode $mode, expected 700"; exit 1; }

echo PASS
