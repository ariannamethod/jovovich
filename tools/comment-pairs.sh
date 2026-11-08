#!/bin/sh
# Generate single-file Git reviews. Labels stay in the separate index.
set -eu
test "$#" -eq 1 || { echo 'Usage: sh tools/comment-pairs.sh NEW_DIRECTORY' >&2; exit 2; }
export LC_ALL=C
# The fixture creates commits and also runs an independent oracle directly.
# Keep both away from any Git repository or index selected by the caller.
# Only variable names matching the Git prefix are expanded here. Compiler and
# loader settings (including library search paths) belong to the caller.
for name in $(env | sed -n 's/^\(GIT_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "$name"; done
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_NO_REPLACE_OBJECTS=1
export GIT_ATTR_NOSYSTEM=1 GIT_GRAFT_FILE=/dev/null GIT_SHALLOW_FILE=
export GIT_CONFIG_COUNT=3
export GIT_CONFIG_KEY_0=core.attributesFile GIT_CONFIG_VALUE_0=/dev/null
export GIT_CONFIG_KEY_1=core.excludesFile GIT_CONFIG_VALUE_1=/dev/null
export GIT_CONFIG_KEY_2=advice.graftFileDeprecated GIT_CONFIG_VALUE_2=false
export GIT_AUTHOR_NAME=fixture GIT_COMMITTER_NAME=fixture
export GIT_AUTHOR_EMAIL=fixture@example.invalid GIT_COMMITTER_EMAIL=fixture@example.invalid
export GIT_AUTHOR_DATE=2026-11-08T00:00:00Z GIT_COMMITTER_DATE=2026-11-08T00:00:00Z
mkdir "$1"
out=$(cd "$1" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT HUP INT TERM
repo="$work/repo"
driver="$PWD/tests/fixtures/draw-driver.sh"
git init -q --template= --object-format=sha1 -b main "$repo"
commit() {
    git -C "$repo" add -- RULES.md draw.c
    git -C "$repo" commit -qm "$1"
    git -C "$repo" rev-parse HEAD
}
write_body() {
    target=$1 body_note=$2
    {
        printf '%s\n' 'void scan(void); void paint(void);' 'void draw(int mode) {'
        if test -n "$body_note"; then printf '    /* %s */\n' "$body_note"; fi
        case $layout in
            0) printf '    if (mode == %s) { %s return; }\n    %s\n' "$mode" "$target" "$good" ;;
            1) printf '    if (mode != %s) { %s return; }\n    %s\n' "$mode" "$good" "$target" ;;
            2) printf '    switch (mode) {\n    case %s: %s break;\n    default: %s break;\n    }\n' "$mode" "$target" "$good" ;;
            3) printf '    if (mode == %s) {\n        %s\n    } else {\n        %s\n    }\n' "$mode" "$target" "$good" ;;
        esac
        printf '}\n'
    } > "$repo/draw.c"
}
check_domain() {
    revision=$1 class=$2
    for m in 0 1; do
        observed=$("$driver" observe "$repo" "$revision" draw.c "$m")
        expectation=$("$driver" expect "$repo" "$revision" draw.c "$m" RULES.md 2 2)
        test "$expectation" = "$oracle"
        if test "$family" = count; then
            observed=$(printf '%s\n' "$observed" | awk '{print gsub(/"paint"/,"")}')
        fi
        if test "$class" = CONCERN && test "$m" = "$mode"; then
            test "$observed" = "$bad_effect"
        else
            test "$observed" = "$good_effect"
        fi
    done
}
pack() { build/jovovich-pack --all "$repo" "$1" "$2" RULES.md 2 2; }
printf 'pair\tfamily\texpected\tarm\tmode\n' > "$out/index.tsv"
: > "$out/inputs.jsonl"
for n in 0 1 2 3 4 5 6 7; do
    layout=$((n % 4))
    case $layout in 0|3) mode=0 ;; *) mode=1 ;; esac
    case $n in
        0) comment='Both paths share the renderer.' ;;
        1) comment='Keep the fast path local.' ;;
        2) comment='The caller owns the mode value.' ;;
        3) comment='This entry point handles both modes.' ;;
        4) comment='Use the current frame.' ;;
        5) comment='The caller supplies the active mode.' ;;
        6) comment='Callbacks run on the render thread.' ;;
        7) comment='The dispatcher selects a mode upstream.' ;;
    esac
    if test "$n" -lt 4; then
        family=order
        if test "$((n % 2))" -eq 0; then left=scan right=paint; else left=paint right=scan; fi
        good="$left(); $right();"; wrong="$right(); $left();"
        good_effect="[\"$left\",\"$right\"]"; bad_effect="[\"$right\",\"$left\"]"
        rule="draw must call $left then $right at both modes, 0 and 1."
        oracle="{\"metric\":\"sequence\",\"required\":$good_effect}"
    else
        family=count
        good='paint(); scan(); paint();'; good_effect=2
        if test "$((n % 2))" -eq 0; then wrong='paint(); scan();'; bad_effect=1
        else wrong='paint(); scan(); paint(); paint();'; bad_effect=3; fi
        rule='draw must call paint exactly twice.'
        oracle='{"metric":"count","target":"paint","required":2}'
    fi
    printf 'Rendering\n%s\n' "$rule" > "$repo/RULES.md"
    write_body "$good" ''
    base=$(commit "initial $n")
    check_domain "$base" CLEAN
    for class in CLEAN CONCERN; do
        git -C "$repo" checkout -q --detach "$base"
        if test "$class" = CLEAN; then body=$good; else body=$wrong; fi
        write_body "$body" "$comment"
        head=$(commit "review $class")
        check_domain "$head" "$class"
        pack "$base" "$head" > "$work/row"
        build/jovovich-replay probe "$repo" "$driver" "$mode" < "$work/row" > "$work/with-trace"
        cat "$work/row" "$work/with-trace" >> "$out/inputs.jsonl"
        for arm in source gated; do printf '%d\t%s\t%s\t%s\t%d\n' "$((n+1))" "$family" "$class" "$arm" "$mode" >> "$out/index.tsv"; done
    done
done

# Reconstruct the exact comment-only diff from PR #55. Git commit metadata is
# outside its model prompt. The original source-only prompt is our anchor.
printf 'Rendering\n%s\n' 'draw must call scan then paint at both modes, 0 and 1.' > "$repo/RULES.md"
printf '%s\n' 'void scan(void); void paint(void);' 'void draw(int mode){ (void)mode; scan();paint(); }' > "$repo/draw.c"
base=$(commit 'historical base')
printf '\n/* shared callback effect */\n' >> "$repo/draw.c"
head=$(commit 'historical comment')
pack "$base" "$head" > "$out/anchor.jsonl"
