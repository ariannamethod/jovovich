#!/bin/sh
# Review the historical CLI for the implementation path supplied by the packer.
set -eu
export GIT_NO_REPLACE_OBJECTS=1
action=$1 repo=$2 rev=$3 file=$4 mode=$5
case "$file:$mode" in
    tools/embeddinggemma2_encode.c:1) expected='row refused' ;;
    tools/amlc.c:2) expected='flag refused' ;;
    src/pack.c:3) expected='a.c,lib' ;;
    *) exit 2 ;;
esac
if test "$action" = expect; then
    jq -cn --arg required "$expected" '{metric:"text",$required}'
    exit
fi
test "$action" = observe
root=$PWD
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
trap 'exit 1' HUP INT TERM
git -C "$repo" archive "$rev" > "$work/code.tar"
mkdir "$work/code"
tar -xf "$work/code.tar" -C "$work/code"
cd "$work/code"
case "$file" in
    tools/amlc.c)
        cc -O2 tools/amlc.c -o "$work/amlc"
        printf '%s\n' 'BLOOD LINK -lm;' 'BLOOD MAIN {' 'int main(void) { return 0; }' '}' > "$work/one.aml"
        if "$work/amlc" "$work/one.aml" --emit-c > "$work/out" 2> "$work/err"; then
            grep -q 'int main' "$work/out"; actual='flag accepted'
        else
            grep -q 'BLOOD LINK byte' "$work/err"; actual='flag refused'
        fi ;;
    tools/embeddinggemma2_encode.c)
        make -s embeddinggemma2_encode embeddinggemma2_to_gguf >&2
        # Use this revision's analytic model and synthetic tokenizer from its own test.
        cat > fixture.c <<'C'
#define main embedded_test_main
#include "tests/test_embeddinggemma2_text.c"
#undef main
int main(void) { write_model("model.gguf"); write_tokenizer("tokenizer.json", VALID); return 0; }
C
        cc -O2 -I. fixture.c examples/bpe.c gguf.c notorch.c -lm -o "$work/fixture"
        "$work/fixture"
        ./embeddinggemma2_to_gguf --tokenizer tokenizer.json tokenizer.gguf >&2
        printf 'row\tab\000c\n' > "$work/in.tsv"
        if ./embeddinggemma2_encode model.gguf "$work/in.tsv" "$work/out" --tokenizer tokenizer.gguf --condition none 2> "$work/err"; then
            printf 'row\tab\n' > "$work/prefix.tsv"
            ./embeddinggemma2_encode model.gguf "$work/prefix.tsv" "$work/prefix" --tokenizer tokenizer.gguf --condition none 2> "$work/prefix.err"
            jq -es 'length == 2 and .[0].id == "row" and (.[0].input_ids | length) > 0 and .[0].input_ids == .[1].input_ids' "$work/out" "$work/prefix" >/dev/null
            actual='prefix encoded'
        else
            grep -q 'NUL byte' "$work/err"; actual='row refused'
        fi ;;
    src/pack.c)
        cc -O2 -Isrc -I"$root/deps/notorch" -I"$root/deps/aml/core" src/pack.c src/batch.c src/review.c \
            "$root/deps/aml/libaml.a" "$root/deps/notorch/sha256.c" -lm -pthread -o "$work/pack"
        demo="$work/demo"
        git init -q -b main "$demo"
        git -C "$demo" config user.name Fixture
        git -C "$demo" config user.email fixture@example.invalid
        export GIT_AUTHOR_DATE=2026-11-08T00:00:00Z GIT_COMMITTER_DATE=2026-11-08T00:00:00Z
        printf 'Review every changed path.\n' > "$demo/RULES.md"
        printf 'int a = 0;\n' > "$demo/a.c"
        git -C "$demo" add .; git -C "$demo" commit -qm seed
        old=$(git -C "$demo" rev-parse HEAD)
        git -C "$demo" update-index --add --cacheinfo "160000,$old,lib"
        git -C "$demo" commit -qm base
        base=$(git -C "$demo" rev-parse HEAD)
        printf 'int a = 1;\n' > "$demo/a.c"
        git -C "$demo" add a.c
        git -C "$demo" update-index --cacheinfo "160000,$base,lib"
        git -C "$demo" commit -qm head
        git -C "$demo" config diff.ignoreSubmodules all
        "$work/pack" --all "$demo" "$base" HEAD RULES.md > "$work/packed"
        actual=$(jq -rs 'map(.file)|join(",")' "$work/packed") ;;
esac
jq -cn --arg s "$actual" '$s'
