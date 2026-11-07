#!/bin/sh
# Change only the held-out boundary expression, then repeat the compiled oracle.
set -eu
if test "$#" -ne 4; then echo 'Usage: sh tools/check_boundary_form.sh MODEL TOKENIZER COMPLETED_RUN NEW_OUTPUT' >&2; exit 2; fi
model=$1
tokenizer=$2
run=$3
out=$4
mkdir "$out"
./build/semantic-corpus --direct-boundary source > "$out/oracle.c"
"${CC:-cc}" -O2 -std=c11 -Wall -Wextra -Werror "$out/oracle.c" -o "$out/oracle"
"$out/oracle" > "$out/proofs.jsonl"
./build/semantic-corpus --direct-boundary pack "$out/proofs.jsonl" "$out"
cmp "$run/corpus/train.jsonl" "$out/train.jsonl"
cmp "$run/corpus/eval-expected.jsonl" "$out/eval-expected.jsonl"
# Verify every return value against its original function over the specified domain.
for variant in original direct; do
    source="$run/corpus/oracle.c"
    if test "$variant" = direct; then source="$out/oracle.c"; fi
    {
        printf '#define main original_oracle_main\n'
        cat "$source"
        printf '\n#undef main\nint main(void) { for(int x=-8;x<=8;x++) {\n'
        i=128; while test "$i" -lt 160; do printf 'printf("%%d\\n",case_%d(x));\n' "$i"; i=$((i+1)); done
        printf '} return 0; }\n'
    } > "$out/check.c"
    "${CC:-cc}" -std=c11 -O2 -Wall -Wextra -Werror "$out/check.c" -o "$out/check"
    "$out/check" > "$out/$variant-returns.txt"
done
cmp "$out/original-returns.txt" "$out/direct-returns.txt"
test "$(wc -l < "$out/direct-returns.txt")" -eq 544
head -n 32 "$out/eval-inputs.jsonl" > "$out/inputs.jsonl"
head -n 32 "$out/eval-expected.jsonl" > "$out/expected.jsonl"
./build/jovovich "$model" "$tokenizer" --features < "$out/inputs.jsonl" > "$out/direct.features"
./build/jovovich-readout score "$out/inputs.jsonl" "$out/direct.features" "$out/expected.jsonl" "$run/adapter.json" > "$out/score.json"
