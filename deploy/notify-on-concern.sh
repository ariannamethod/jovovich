#!/bin/sh
# notify-on-concern.sh ANSWERS QUEUE [PR_REF]
#
# Reads a jovovich --json answers stream and, for every row whose verdict is
# CONCERN, drops one tag file into QUEUE. A tag carries the id, the reviewed
# file, both probabilities, the PR reference and the answers path, so whatever
# watches QUEUE can reopen the full review. sh + jq only; the C core is not
# touched and no model is loaded. Prints the number of tags written.
set -eu

answers=${1:?usage: notify-on-concern.sh ANSWERS QUEUE [PR_REF]}
queue=${2:?usage: notify-on-concern.sh ANSWERS QUEUE [PR_REF]}
pr=${3:-unknown}

mkdir -p "$queue"
chmod 700 "$queue"
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT

jq -c --arg pr "$pr" --arg src "$answers" '
  select(.choice.verdict == "CONCERN")
  | { id,
      file:    (.scope.file // null),
      verdict: .choice.verdict,
      concern: .probabilities.CONCERN,
      clean:   .probabilities.CLEAN,
      pr:      $pr,
      answers: $src }' "$answers" > "$tmp"

n=0
while IFS= read -r tag; do
    [ -n "$tag" ] || continue
    id=$(printf '%s' "$tag" | jq -r '.id')
    # id becomes a filename here and a prompt token in wake-claude.sh. A real
    # jovovich id is a lowercase hex hash. Reject anything else so a crafted
    # answers stream can neither escape the queue directory (../, absolute
    # paths) nor smuggle text into the wake prompt.
    case "$id" in
        "" | *[!0-9a-f]*)
            printf 'skip: non-hex id %s\n' "$id" >&2
            continue ;;
    esac
    printf '%s\n' "$tag" > "$queue/$id.json"
    n=$((n + 1))
done < "$tmp"

echo "$n"
