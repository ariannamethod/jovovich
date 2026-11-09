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
    printf '%s\n' "$tag" > "$queue/$id.json"
    n=$((n + 1))
done < "$tmp"

echo "$n"
