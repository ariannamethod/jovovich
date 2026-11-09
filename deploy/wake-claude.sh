#!/bin/sh
# wake-claude.sh QUEUE
#
# launchd fires this whenever QUEUE changes. If it holds CONCERN tags, it wakes
# a headless Claude Code run to re-review them, then moves the handed-off tags
# aside so the watcher does not re-fire on them. Scribe is deliberately NOT in
# this path: jovovich is the fast juror, Claude from Claude Code is the reviewer,
# and the tag is the whole handshake.
#
# JOV_WAKE_DRY=1 prints the claude invocation instead of running it, so the
# wiring is testable without spawning a real session.
set -eu

queue=${1:?usage: wake-claude.sh QUEUE}
set -- "$queue"/*.json
[ -e "$1" ] || { echo "queue empty"; exit 0; }

ids=$(jq -r '.id' "$@" | tr '\n' ' ')
prs=$(jq -r '.pr' "$@" | sort -u | tr '\n' ' ')
prompt="jovovich raised CONCERN. PR(s): ${prs}. Verdict tags are in ${queue} \
(one JSON each: id, file, concern probability, pr, answers path). Read each tag, \
pull the diff and the rule from its answers file, judge whether the merge is \
safe, and report per id. ids:${ids}"

if [ "${JOV_WAKE_DRY:-0}" = "1" ]; then
    printf 'claude -p "%s"\n' "$prompt"
    exit 0
fi

# ponytail: headless one-shot; the real `claude -p` seam is validated at deploy
# on neo, where PATH reaches the claude binary (see jovovich-watch.plist).
claude -p "$prompt"

handled="${queue%/}/../handled"
mkdir -p "$handled"
mv "$@" "$handled"/
