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
# The exact tree path, not its normalization or descendants, is the scope.
reject "$base" "$head" RULES.md directory/
reject "$base" "$head" RULES.md ./main.c
reject "$base" "$head" RULES.md directory/../main.c
# Worktree, staged, local, info/ and environment Git settings must not enter
# the resolved commit comparison. Preserve the original bytes in a clean run.
printf '*.c -diff\n' > "$work/.gitattributes"
git -C "$work" add .gitattributes
printf '*.c diff=python\n' > "$work/.gitattributes"
printf '*.c -diff\n' > "$work/.git/info/attributes"
git -C "$work" config diff.noprefix true
git -C "$work" config core.abbrev 16
GIT_DIR="$work/not-a-repo" GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=diff.noprefix GIT_CONFIG_VALUE_0=true \
    "$pack" "$work" "$base" "$head" RULES.md main.c > build/git-isolated.json
cmp build/git-pack.json build/git-isolated.json
# A tree becoming a file, or vice versa, contributes a separate exact patch
# for the leaf and for each affected descendant.
swap="$work/swap"
git init -q -b main "$swap"
git -C "$swap" config user.name fixture
git -C "$swap" config user.email fixture@example.invalid
printf 'Keep both paths visible.\n' > "$swap/RULES.md"
printf 'leaf\n' > "$swap/node"
git -C "$swap" add .
git -C "$swap" commit -qm leaf
leaf=$(git -C "$swap" rev-parse HEAD)
rm "$swap/node"
mkdir "$swap/node"
printf 'child\n' > "$swap/node/child"
git -C "$swap" add -A
git -C "$swap" commit -qm tree
tree=$(git -C "$swap" rev-parse HEAD)
for from in "$leaf" "$tree"; do
    to=$leaf; test "$from" = "$tree" || to=$tree
    "$pack" --all "$swap" "$from" "$to" RULES.md > build/git-swap.jsonl
    jq -es 'length==2 and (map(.file)|sort)==["node","node/child"] and
      all(.[]; (.change_excerpt|split("\n")|map(select(startswith("diff --git ")))|length)==1)' build/git-swap.jsonl >/dev/null
    for path in node node/child; do
        filter=A
        if { test "$from" = "$leaf" && test "$path" = node; } || { test "$from" = "$tree" && test "$path" = node/child; }; then filter=D; fi
        git -C "$swap" diff --no-renames --unified=8 "--diff-filter=$filter" "$from" "$to" -- "$path" > build/git-swap-expected.diff
        "$pack" "$swap" "$from" "$to" RULES.md "$path" > build/git-swap-single.json
        jq -jr '.change_excerpt' build/git-swap-single.json > build/git-swap-single.diff
        jq -jr --arg path "$path" 'select(.file==$path)|.change_excerpt' build/git-swap.jsonl > build/git-swap-batch.diff
        cmp build/git-swap-expected.diff build/git-swap-single.diff
        cmp build/git-swap-expected.diff build/git-swap-batch.diff
    done
done
# BASE's committed attribute must actually be applied, even when HEAD and
# the dirty checkout both mark the changed file as text.
printf 'node/child -diff\n' > "$swap/.gitattributes"
git -C "$swap" add .gitattributes
git -C "$swap" commit -qm 'binary at base'
attr_base=$(git -C "$swap" rev-parse HEAD)
printf 'node/child diff\n' > "$swap/.gitattributes"
printf 'another child\n' > "$swap/node/child"
git -C "$swap" add -A
git -C "$swap" commit -qm 'text at head'
if "$pack" "$swap" "$attr_base" HEAD RULES.md node/child > build/git-rejected.json 2> build/git-rejected.log; then exit 1; fi
test ! -s build/git-rejected.json
grep -q 'Binary change' build/git-rejected.log
printf 'Pinned BASE attributes, literal leaf scopes, and both directions of file/tree transitions passed\n'
# Git tree objects may name paths that the checkout filesystem cannot create.
# Assemble them directly, and require every published path and excerpt to
# round-trip through UTF-8 while invalid inputs leave the fact ledger untouched.
valid_rules=$(printf 'r\303\250gles')
valid_file=$(printf 'caf\303\251.c')
bad_path=$(printf 'bad\377')
before_blob=$(printf 'avant\n' | git -C "$swap" hash-object -w --stdin)
after_blob=$(printf 'apr\303\250s\n' | git -C "$swap" hash-object -w --stdin)
rule_blob=$(printf 'R\303\250gle.\n' | git -C "$swap" hash-object -w --stdin)
bad_blob=$(printf 'bad\377\n' | git -C "$swap" hash-object -w --stdin)
utf_tree() {
    { printf '100644 blob %s\t%s\0' "$rule_blob" "$valid_rules" "$rule_blob" "$bad_path" \
        "$bad_blob" bad-rules "$1" "$valid_file" "$1" "$bad_path.c" "$2" bad-content; } | git -C "$swap" mktree -z
}
utf_base=$(git -C "$swap" commit-tree "$(utf_tree "$before_blob" "$before_blob")" -m 'raw tree paths')
utf_head=$(git -C "$swap" commit-tree "$(utf_tree "$after_blob" "$bad_blob")" -p "$utf_base" -m 'raw patch')
"$pack" "$swap" "$utf_base" "$utf_head" "$valid_rules" "$valid_file" > build/git-valid-utf8.json
jq -e --arg rules "$valid_rules" --arg file "$valid_file" \
    '.source.rules_path==$rules and .file==$file and .rule_excerpt=="Règle.\n" and (.change_excerpt|contains("+après\n"))' build/git-valid-utf8.json >/dev/null
mkdir "$work/invalid-memory"
reject_utf8() {
    if "$pack" "$@" > build/git-rejected.json 2> build/git-rejected.log; then exit 1; fi
    test ! -s build/git-rejected.json
    test ! -e "$work/invalid-memory/rules.checkpoint"
}
reject_utf8 "$swap" "$utf_base" "$utf_head" "$bad_path" "$valid_file"
reject_utf8 "$swap" "$utf_base" "$utf_head" "$valid_rules" "$bad_path.c"
reject_utf8 "$swap" "$utf_base" "$utf_head" bad-rules "$valid_file"
reject_utf8 "$swap" "$utf_base" "$utf_head" "$valid_rules" bad-content
reject_utf8 --remember "$work/invalid-memory" project key --all "$swap" "$utf_base" "$utf_head" "$valid_rules"
reject_utf8 --remember "$work/invalid-memory" project key "$swap" "$utf_base" "$utf_head" "$bad_path" "$valid_file"
