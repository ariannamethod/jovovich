#!/bin/sh
set -eu
pack=${JOV_PACK:-./build/jovovich-pack}
work=$(mktemp -d "${TMPDIR:-/tmp}/jovovich-submodules-XXXXXX")
trap 'rm -rf "$work"' EXIT HUP INT TERM
git init -q -b main "$work"
git -C "$work" config user.name 'JOVOVICH fixture'
git -C "$work" config user.email 'fixture@example.invalid'
printf 'Dependency commit updates must remain visible for review.\n' > "$work/RULES.md"
printf 'int value = 0;\n' > "$work/a.c"
git -C "$work" add .
git -C "$work" commit -qm seed
old=$(git -C "$work" rev-parse HEAD)
git -C "$work" update-index --add --cacheinfo "160000,$old,lib"
git -C "$work" commit -qm base
base=$(git -C "$work" rev-parse HEAD)
blob=$(git -C "$work" rev-parse HEAD:RULES.md)
printf 'int value = 1;\n' > "$work/a.c"
git -C "$work" add a.c
git -C "$work" update-index --cacheinfo "160000,$base,lib"
git -C "$work" commit -qm change
head=$(git -C "$work" rev-parse HEAD)
git -C "$work" config diff.ignoreSubmodules all
git -C "$work" config submodule.lib.ignore all
git -C "$work" config diff.submodule log
git -C "$work" show "$base:RULES.md" > build/submodule-rules.txt
git -C "$work" diff --no-ext-diff --no-textconv --no-color --no-renames --ignore-submodules=none --submodule=short --unified=8 "$base" "$head" -- lib > build/submodule-diff.txt
"$pack" --all "$work" "$base" "$head" RULES.md > build/submodule-batch.jsonl
test "$(wc -l < build/submodule-batch.jsonl)" -eq 2
sed -n '2p' build/submodule-batch.jsonl > build/submodule-row.jsonl
./build/check-git build/submodule-row.jsonl build/submodule-rules.txt build/submodule-diff.txt "$base" "$head" "$blob" 1 1 lib
grep -q -- "-Subproject commit $old" build/submodule-diff.txt
grep -q -- "+Subproject commit $base" build/submodule-diff.txt
"$pack" "$work" "$base" "$head" RULES.md lib > build/submodule-single.jsonl
./build/check-git build/submodule-single.jsonl build/submodule-rules.txt build/submodule-diff.txt "$base" "$head" "$blob" 1 1 lib
printf 'Submodule capture: ignored gitlinks retained in batch and single-file input with full commit IDs\n'
