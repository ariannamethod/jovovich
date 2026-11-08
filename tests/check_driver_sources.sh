#!/bin/sh
# Exercise the shipped native and Node drivers through the public replay interface.
set -eu
work=$(mktemp -d "${TMPDIR:-/tmp}/jov-driver-source-XXXXXX")
trap 'rm -rf "$work"' EXIT HUP INT TERM
repo="$work/repo with spaces"
ledger="$work/memory"
mkdir "$ledger"
git init -q -b main "$repo"
git -C "$repo" config user.name Fixture
git -C "$repo" config user.email fixture@example.invalid
driver=$PWD/examples/release-trial/runner.sh
printf 'Return the required output.\n' > "$repo/RULES"
printf '%s\n' 'typedef int (*callback)(void*,const char*,const char*,const char*);' \
    'int ini_parse_string(const char*,callback,void*);' > "$repo/ini.h"
commit() { git -C "$repo" add .; git -C "$repo" commit -qm "$1"; git -C "$repo" rev-parse HEAD; }
native() {
    printf '#include "ini.h"\nint ini_parse_string(const char *s,callback f,void *v){return %s;}\n' "$1" > "$repo/ini.c"
    commit "$1"
}
base=$(native 7); head=$(native 1); later=$(native 7); substitute=$(native 9)
build/jovovich-pack --remember "$ledger" fixture ini --all "$repo" "$base" "$head" RULES > "$work/native"
build/jovovich-pack --recall "$ledger" fixture ini --all "$repo" "$head" "$later" > "$work/regression"
probe() { build/jovovich-replay probe "$repo" "$driver" "$1"; }
probe 2 < "$work/native" > "$work/native-clean"
jq -e '.trace_evidence.runs[0] == {mode:2,base:"7",head:"1",required:"1"}' "$work/native-clean" >/dev/null
git -C "$repo" replace "$head" "$substitute"
git -C "$repo" show "$head:ini.c" | grep -q 'return 9'
GIT_DIR="$work/absent" GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.bare GIT_CONFIG_VALUE_0=false \
    build/jovovich-replay probe "$repo" "$driver" 2 < "$work/native" > "$work/native-replaced"
cmp "$work/native-clean" "$work/native-replaced"
build/jovovich-replay remember "$ledger" "$repo" "$driver" < "$work/native-clean" > "$work/receipt"
build/jovovich-replay run "$ledger" "$repo" "$driver" < "$work/regression" > "$work/regression-output"
jq -e '.trace_evidence.replayed_from.mode==2 and .trace_evidence.runs[0]=={mode:2,base:"1",head:"7",required:"1"}' "$work/regression-output" >/dev/null
git -C "$repo" replace -d "$head" >/dev/null

# An omitted module changes this program's observable value. A local export
# attribute can hide it during a normal archive of the exact same commit.
mkdir "$repo/classes" "$repo/functions" "$repo/internal" "$repo/ranges"
for dir in functions internal ranges; do : > "$repo/$dir/keep"; done
printf '{}\n' > "$repo/package.json"
cat > "$repo/index.js" <<'JS'
exports.inc = () => {
  try { return require('./classes/semver.js'); }
  catch (e) { if (e.code === 'MODULE_NOT_FOUND') return 'fallback'; throw e; }
};
JS
printf "module.exports='before';\n" > "$repo/classes/semver.js"; jsbase=$(commit 'before module')
printf "module.exports='3.0.0-alpha.beta.5.5';\n" > "$repo/classes/semver.js"; jshead=$(commit 'updated module')
build/jovovich-pack "$repo" "$jsbase" "$jshead" RULES classes/semver.js > "$work/node"
probe 5 < "$work/node" > "$work/node-clean"
printf 'classes/semver.js export-ignore\n' > "$repo/.git/info/attributes"
git -C "$repo" archive "$jshead" classes | tar -tf - > "$work/archive-list"
if grep -Fq classes/semver.js "$work/archive-list"; then exit 1; fi
probe 5 < "$work/node" > "$work/node-poisoned"
cmp "$work/node-clean" "$work/node-poisoned"
jq -e '.trace_evidence.runs[0]=={mode:5,base:"before",head:"3.0.0-alpha.beta.5.5",required:"3.0.0-alpha.beta.5.5"}' "$work/node-poisoned" >/dev/null

# Existing tools, original-repository resources and separate mutable build
# worktrees remain usable. No invocation inherits its predecessor's files.
cat > "$work/checkout-driver" <<'DRIVER'
#!/bin/sh
set -eu
test "$JOV_REPOSITORY_PATH" = "$ORIGINAL_SOURCE"
test "$1" != observe || test -f "$JOV_REPOSITORY_PATH/RULES"
test "$(git -C "$2" rev-parse HEAD)" = "$3"
test ! -e "$2/probe-scratch"
: > "$2/probe-scratch"
if test "$1" = expect; then printf '{"metric":"text","required":"ok"}\n'; exit; fi
checkout=$(mktemp -d)
trap 'rm -rf "$checkout"' EXIT
git -C "$2" worktree add -q --detach "$checkout" "$3"
test -f "$checkout/$4"
printf '"ok"\n'
DRIVER
chmod +x "$work/checkout-driver"
ORIGINAL_SOURCE="$repo" build/jovovich-replay probe "$repo" "$work/checkout-driver" 2 < "$work/native" > "$work/checkout-output"

# A FIFO without a writer must be refused before the host waits on open().
fifo=$work/fifo
mkfifo "$fifo"; chmod 700 "$fifo"
build/jovovich-replay probe "$repo" "$fifo" 2 < "$work/native" > "$work/fifo-out" 2>"$work/fifo-log" & pid=$!
(sleep 3; if kill -0 "$pid" 2>/dev/null; then : > "$work/timed-out"; kill "$pid"; fi) & watchdog=$!
rc=0
wait "$pid" || rc=$?
kill "$watchdog" 2>/dev/null || :
wait "$watchdog" 2>/dev/null || :
test "$rc" -eq 1
test ! -s "$work/fifo-out"
test ! -e "$work/timed-out"
printf 'Replayed native and Node from the named objects despite replace/attributes; executable FIFO refused\n'
