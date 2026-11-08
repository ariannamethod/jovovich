#!/bin/sh
# Called from the repository root with a caller-owned private staging directory.
# Compile there so packet construction also runs on a checkout without build/.
set -eu
test "$#" = 3
"${CC:-cc}" -std=c11 -O2 tools/publish_directory.c -o "$1/publish-directory"
exec "$1/publish-directory" "$2" "$3"
