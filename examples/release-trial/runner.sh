#!/bin/sh
# The replay host hashes this file, including all probe inputs and expectations.
set -eu
action=$1 repo=$2 commit=$3 file=$4 mode=$5
case "$mode:$file" in
    1:ini.c) expected='Hi World' ;;
    2:ini.c | 3:ini.c) expected=1 ;;
    4:ranges/subset.js) expected=true ;;
    5:classes/semver.js) expected=3.0.0-alpha.beta.5.5 ;;
    6:classes/range.js) expected=false ;;
    *) exit 2 ;;
esac
if test "$action" = expect; then
    printf '{"metric":"text","required":"%s"}\n' "$expected"
    exit 0
fi
test "$action" = observe
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
trap 'exit 1' HUP INT TERM
if test "$file" = ini.c; then
    git -C "$repo" show "$commit:ini.c" > "$work/ini.c"
    git -C "$repo" show "$commit:ini.h" > "$work/ini.h"
    cat > "$work/probe.c" <<'C'
#include "ini.h"
#include <stdio.h>
#include <string.h>

struct observed { char last[128]; int calls; };

static int receive(void *data, const char *section, const char *key, const char *value) {
    (void)section;
    (void)key;
    struct observed *out = data;
    out->calls++;
    snprintf(out->last, sizeof(out->last), "%s", value ? value : "");
    return 1;
}

int main(int argc, char **argv) {
    struct observed out = {{0}, 0};
    if (argc != 2) return 2;
    if (!strcmp(argv[1],"1")) {
        if (ini_parse_string("foo = bar\n  Hi World ;c2\n",receive,&out)) return 1;
        puts(out.last);
    } else if (!strcmp(argv[1],"2")) {
        printf("%d\n",ini_parse_string("key=abcdefghijklmnopqrstu\n",receive,&out));
    } else {
        if (ini_parse_string("[broken\nname\n",receive,&out) != 1) return 1;
        printf("%d\n",out.calls);
    }
    return 0;
}
C
    case "$mode" in
        1) set -- ;;
        2) set -- -DINI_MAX_LINE=16 ;;
        3) set -- -DINI_ALLOW_NO_VALUE=1 ;;
    esac
    cc -std=c99 -O2 "$@" "$work/probe.c" "$work/ini.c" -o "$work/probe"
    result=$("$work/probe" "$mode")
    jq -cn --arg result "$result" '$result'
else
    git -C "$repo" archive "$commit" classes functions internal ranges index.js package.json > "$work/src.tar"
    tar -xf "$work/src.tar" -C "$work"
    node - "$work" "$mode" <<'JS'
const api = require(process.argv[2]);
const mode = process.argv[3];
let result;
if (mode === '4') result = api.subset('^10.2.0-beta.2', '^10.2.0-beta.1');
if (mode === '5') result = api.inc('3.0.0-alpha.beta.5.4', 'prerelease', false, 'alpha.beta');
if (mode === '6') result = api.satisfies('0.0.3-alpha', '^0.0.3', { includePrerelease: true });
console.log(JSON.stringify(String(result)));
JS
fi
