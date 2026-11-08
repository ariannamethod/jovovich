#!/bin/sh
# One executable binds the inputs, oracles and code used to observe the two revisions.
set -eu
export GIT_NO_REPLACE_OBJECTS=1
action=$1 repo=$2 rev=$3 file=$4 mode=$5
case "$mode:$file" in
    1:cJSON.c) expected='[1,2,3]' ;;
    -1:cJSON.c) expected='[1,3,2]' ;;
    2:index.js) expected=-37800000 ;;
    -2:index.js) expected=-5400000 ;;
    3:modules/max.js|-3:modules/max.js) expected=-Infinity ;;
    4:modules/toArray.js|-4:modules/toArray.js) expected='[]' ;;
    5:papaparse.js) expected='a,+x++y+' ;;
    -5:papaparse.js) expected='a,xy' ;;
    6:papaparse.js|-6:papaparse.js) expected=';' ;;
    7:lib/ini.js|-7:lib/ini.js) expected=value ;;
    8:lib/ini.js) expected='["1","2"]' ;;
    -8:lib/ini.js) expected='"1"' ;;
    *) exit 2 ;;
esac
if test "$action" = expect; then
    jq -cn --arg required "$expected" '{metric:"text",$required}'
    exit 0
fi
test "$action" = observe
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
trap 'exit 1' HUP INT TERM
if test "$file" = cJSON.c; then
    git -C "$repo" show "$rev:cJSON.c" > "$work/cJSON.c"
    git -C "$repo" show "$rev:cJSON.h" > "$work/cJSON.h"
    cat > "$work/main.c" <<'C'
#include "cJSON.h"
#include <stdio.h>
#include <string.h>

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    cJSON *array = cJSON_Parse("[1,3]");
    cJSON *item = cJSON_CreateNumber(2);
    if (!array || !item) return 1;
    int index = strcmp(argv[1], "-1") == 0 ? 2 : 1;
    if (!cJSON_InsertItemInArray(array, index, item)) cJSON_Delete(item);
    char *printed = cJSON_PrintUnformatted(array);
    if (!printed) return 1;
    puts(printed);
    cJSON_free(printed);
    cJSON_Delete(array);
    return 0;
}
C
    cc -std=c99 -O2 "$work/main.c" "$work/cJSON.c" -lm -o "$work/probe"
    actual=$("$work/probe" "$mode")
    jq -cn --arg actual "$actual" '$actual'
    exit 0
fi
case "$file" in
    modules/*)
        git -C "$repo" archive "$rev" modules > "$work/modules.tar"
        tar -xf "$work/modules.tar" -C "$work"
        ;;
    *) git -C "$repo" show "$rev:$file" > "$work/upstream.cjs" ;;
esac
node --input-type=module - "$work" "$file" "$mode" <<'JS'
import { pathToFileURL } from 'node:url';
const [work, file, mode] = process.argv.slice(2);
const path = file.startsWith('modules/') ? file : 'upstream.cjs';
const { default: api } = await import(pathToFileURL(work + '/' + path));
const shared = Number(mode) < 0;
let output;
switch (Math.abs(Number(mode))) {
case 2:
    output = String(api(shared ? '-1.5h' : '-10.5h'));
    break;
case 3:
    try {
        output = String(shared ? api(null) : api(null, 0));
    } catch (error) {
        if (!(error instanceof TypeError)) throw error;
        output = error.name;
    }
    break;
case 4:
    output = JSON.stringify(api(shared ? '' : new String('')));
    break;
case 5:
    output = api.unparse([['a', shared ? 'xy' : 'x+y']], { header: false, quoteChar: '+' });
    break;
case 6: {
    const field = '"{\n  ""a"": 1,\n  ""b"": 2,\n  ""c"": 3,\n  ""d"": 4\n}"';
    const input = ['id;title;data', '1;row one;' + field, '2;row two;' + field].join('\r\n');
    output = api.parse(shared ? 'left;right\r\n1;2' : input).meta.delimiter;
    break;
}
case 7:
    output = String(api.decode(shared ? '[b]\nname=value' : '[b] \nname=value').b?.name);
    break;
case 8:
    output = JSON.stringify(api.decode(shared ? 'brr=1' : 'brr=1\nbrr=2', {bracketedArray:false}).brr);
    break;
default:
    throw new Error('Unknown probe');
}
console.log(JSON.stringify(output));
JS
