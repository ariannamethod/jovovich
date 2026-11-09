# deploy — autonomous watch on neo

JOVOVICH is a fast local juror: she reviews, emits a verdict, and exits. This
folder turns a CONCERN into a wake-up for Claude Code, so a questionable PR gets
a second, slower read before a human reaches it.

The chain, left to right:

```
jovovich --json  ->  notify-on-concern.sh  ->  QUEUE/<id>.json  ->  launchd WatchPaths  ->  wake-claude.sh  ->  claude -p
```

- **notify-on-concern.sh ANSWERS QUEUE [PR_REF]** — reads a `jovovich --json`
  answers stream and drops one tag per CONCERN into `QUEUE`. sh + jq; no model.
- **wake-claude.sh QUEUE** — launchd runs this when `QUEUE` changes. It wakes a
  headless `claude -p` to re-review the tagged ids, then moves the tags to
  `QUEUE/../handled` so the watch does not re-fire. The woken reviewer is locked
  to read-only tools (`--allowedTools Read,Grep,Glob --permission-prompts none`)
  and the PR content is framed as untrusted, so an injected instruction in a
  diff cannot reach a command, a write or the network. `JOV_WAKE_DRY=1` prints
  the invocation instead of running it.
- **jovovich-watch.plist** — launchd template. `__JOVOVICH_ROOT__` and
  `__QUEUE__` are placeholders; `RunAtLoad` is false and the job is not loaded
  by this repository.

**Scribe is not in this chain.** jovovich is the fast juror, Claude from Claude
Code is the reviewer, the tag is the whole handshake. Scribe — memory, mail,
Hostinger — can subscribe to the verdict log later as durable memory, on its
own axis; it is not a relay for a review ping.

## Verify the wiring

```sh
sh deploy/notify-selftest.sh      # CLEAN -> 0 tags, CONCERN -> 1 tag, wake dry-run
plutil -lint deploy/jovovich-watch.plist
```

## Enable on neo (deploy step, not done here)

```sh
root=$(pwd); queue="$root/deploy/queue"; mkdir -p "$queue"
sed -e "s#__JOVOVICH_ROOT__#$root#g" -e "s#__QUEUE__#$queue#g" \
    deploy/jovovich-watch.plist > ~/Library/LaunchAgents/com.ariannamethod.jovovich.watch.plist
launchctl load ~/Library/LaunchAgents/com.ariannamethod.jovovich.watch.plist
```

A review run then pipes its answers through `notify-on-concern.sh` with the same
`$queue`, and a CONCERN wakes Claude Code on its own.
