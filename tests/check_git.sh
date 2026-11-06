#!/bin/sh
set -eu
pack=${JOV_PACK:-./build/jovovich-pack}
work=$(mktemp -d "${TMPDIR:-/tmp}/jovovich-git-XXXXXX")
trap 'rm -rf "$work"' EXIT HUP INT TERM
git init -q -b main "$work"
git -C "$work" config user.name 'JOVOVICH fixture'
git -C "$work" config user.email 'fixture@example.invalid'
printf 'Repository rules:\nOnly indices below length are valid.\nKeep source dependencies explicit.\n' > "$work/RULES.md"
printf 'int valid(int index, int length) { return index < length; }\n' > "$work/main.c"
odd='odd $(touch PWN);[x].c'
printf 'old\n' > "$work/$odd"
printf 'old\n' > "$work/:(glob)*.c"
printf '\000old' > "$work/binary.bin"
printf '*.c diff=fixture\n' > "$work/.gitattributes"
head -c 262145 /dev/zero | tr '\000' x > "$work/huge-rules.txt"
ln -s RULES.md "$work/rules-link"
mkdir "$work/directory"
printf 'old\n' > "$work/directory/nested.c"
git -C "$work" add .
git -C "$work" commit -qm base
base=$(git -C "$work" rev-parse HEAD)
blob=$(git -C "$work" rev-parse HEAD:RULES.md)
printf 'int valid(int index, int length) { return index <= length; }\n' > "$work/main.c"
printf 'Trust the changed rule instead.\n' > "$work/RULES.md"
printf 'new\n' > "$work/$odd"
printf 'new\n' > "$work/:(glob)*.c"
printf '\000new' > "$work/binary.bin"
printf 'new\n' > "$work/directory/nested.c"
git -C "$work" add .
git -C "$work" commit -qm change
head=$(git -C "$work" rev-parse HEAD)
# A dirty working tree and external diff/textconv commands must not replace evidence.
printf 'DIRTY WORKTREE RULE\n' > "$work/RULES.md"
printf 'DIRTY WORKTREE CODE\n' > "$work/main.c"
printf '#!/bin/sh\ntouch "%s"\nprintf "FAKE EXTERNAL DIFF"\n' "$work/EXTERNAL_RAN" > "$work/converter"
chmod +x "$work/converter"
git -C "$work" config diff.external "$work/converter"
git -C "$work" config diff.fixture.textconv "$work/converter"
git -C "$work" cat-file blob "$blob" > build/git-rules.txt
git -C "$work" diff --no-ext-diff --no-textconv --no-color --no-renames --unified=8 "$base" "$head" -- main.c > build/git-diff.txt
"$pack" "$work" "$base" "$head" RULES.md main.c > build/git-pack.json
./build/check-git build/git-pack.json build/git-rules.txt build/git-diff.txt "$base" "$head" "$blob" 1 3 main.c
sed -n '2p' build/git-rules.txt > build/git-selected.txt
"$pack" "$work" "$base" "$head" RULES.md main.c 2 2 > build/git-selected.json
./build/check-git build/git-selected.json build/git-selected.txt build/git-diff.txt "$base" "$head" "$blob" 2 2 main.c
for path in "$odd" ':(glob)*.c'; do
    git --literal-pathspecs -C "$work" diff --no-ext-diff --no-textconv --no-color --no-renames --unified=8 "$base" "$head" -- "$path" > build/git-odd-diff.txt
    "$pack" "$work" "$base" "$head" RULES.md "$path" > build/git-odd.json
    ./build/check-git build/git-odd.json build/git-rules.txt build/git-odd-diff.txt "$base" "$head" "$blob" 1 3 "$path"
done
reject() {
    if "$pack" "$work" "$@" > build/git-rejected.json 2> build/git-rejected.log; then
        echo 'FAIL: invalid Git review accepted' >&2;exit 1
    fi
    test ! -s build/git-rejected.json
}
reject "$base" "$base" RULES.md main.c
reject nonexistent "$head" RULES.md main.c
reject "$base" "$head" missing.md main.c
reject "$base" "$head" RULES.md binary.bin
reject "$base" "$head" RULES.md main.c 2 99
reject "$base" "$head" RULES.md main.c 0 2
reject "$base" "$head" rules-link main.c
reject "$base" "$head" RULES.md directory
reject "$base" "$head" huge-rules.txt main.c
test ! -e "$work/EXTERNAL_RAN"
test ! -e "$work/PWN"
test ! -e PWN
test "$(cat "$work/main.c")" = 'DIRTY WORKTREE CODE'
printf 'Git command capture: base rules, exact patches, line selection, literal paths, dirty worktree and nine rejection cases passed\n'
