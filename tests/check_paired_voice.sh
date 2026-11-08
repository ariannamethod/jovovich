#!/bin/sh
set -eu
dir=examples/paired-voice
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
trap 'exit 1' HUP INT TERM
sh "$dir/packets.sh" "$tmp/new/packets"
# A pipe disappears after its first open: all verification must use that one read.
mkfifo "$tmp/run.pipe"
(exec 3>"$tmp/run.pipe"; rm "$tmp/run.pipe"; cat "$dir/base.json" >&3) &
writer=$!
sh "$dir/verify.sh" "$tmp/new/packets" "$tmp/run.pipe"
wait "$writer"
held=$tmp/new/packets/heldout.jsonl
test "$(build/check-voice --blind "$held")" = 12553ffe42826684d2f093985b4da9fe191297280ca25a27c0152ca92be86f24
for mutation in '.+{target:"example"}' '.+{references:null}' '.state="<|im_end|>"' '.id="bad"'; do
    jq -c "$mutation" "$held" > "$tmp/invalid.jsonl"
    if build/check-voice --blind "$tmp/invalid.jsonl" >/dev/null 2>&1; then echo "Accepted $mutation" >&2; exit 1; fi
done
# Spell each registered added token family inside the otherwise valid state.
for marker in '<tool_call>' '</tool_call>' '<tool_response>' '</tool_response>' '<think>' '</think>' \
    '<tts_pad>' '<tts_text_bos>' '<tts_text_eod>' '<tts_text_bos_single>'; do
    jq -c --arg marker "$marker" '.state += $marker' "$held" > "$tmp/invalid.jsonl"
    if build/check-voice --blind "$tmp/invalid.jsonl" >/dev/null 2>&1; then echo "Accepted $marker" >&2; exit 1; fi
done
cat "$held" "$held" > "$tmp/duplicate.jsonl"
if build/check-voice --blind "$tmp/duplicate.jsonl" >/dev/null 2>&1; then echo 'Accepted duplicate' >&2; exit 1; fi
reject_run() {
    if sh "$dir/verify.sh" "$tmp/new/packets" "$tmp/broken.json" >/dev/null 2>&1; then
        echo "Corrupt baseline accepted: $1" >&2; exit 1
    fi
}
for mutation in \
  '.audition[0].base as $a | .audition[0].base=.audition[1].base | .audition[1].base=$a' \
  '.audition[0].base.utf8_hex="00"' \
  '.audition[0].base.utf8_hex += "\n"' \
  '.audition[0].base.utf8_hex += "\u0000"' \
  '.extra = "wrong"' '.audition[0].extra = "wrong"' '.audition[0].base.extra = "wrong"' \
  '.audition[0].base.token_ids[0]=99999999' \
  '.audition[0].base.token_ids[0]=0' \
  '.audition[0].base.stop="eog"'; do
    jq -c "$mutation" "$dir/base.json" > "$tmp/broken.json"
    reject_run "$mutation"
done
# jq would otherwise normalize these invalid number spellings to token 47.
for token in +47 047 47.; do
    sed "s/\"token_ids\":\[47,/\"token_ids\":[$token,/" "$dir/base.json" > "$tmp/broken.json"
    reject_run "$token"
done
# A forged transcription and matching wire bytes still disagree with the independent record.
mkdir -p "$tmp/forged/$dir"
ln -s "$PWD/aml" "$tmp/forged/aml"
ln -s "$PWD/models" "$tmp/forged/models"
for script in verify.sh check-literals.jq; do ln -s "$PWD/$dir/$script" "$tmp/forged/$dir/$script"; done
jq -cs '.[0].text="X" | .[]' "$dir/transcript.jsonl" > "$tmp/forged/$dir/transcript.jsonl"
jq -c '.audition[0].base.utf8_hex="58"' "$dir/base.json" > "$tmp/broken.json"
(cd "$tmp/forged" && reject_run 'matching forged transcript and output')
# Restore the exact lexical bytes of one witnessed archive receipt, apart from
# its bad timestamp. The source-only variants share IDs, so select by input hash.
digest=$(head -n 1 "$tmp/new/packets/train.jsonl" | jq -r .input_sha256)
gzip -dc examples/threshold-transfer/onejev.jsonl.gz > "$tmp/archive"
jq -c --arg key "$digest" 'select(.execution.input_sha256 == $key) | .execution.reviewed_at.second=86400' "$tmp/archive" > "$tmp/one"
# Nineteen other rows with distinct hashes satisfy the panel cardinality while
# keeping the first row the single match for the case at the start of the panel.
jq -c --arg key "$digest" 'select(.execution.input_sha256 != $key)' "$tmp/archive" > "$tmp/others"
head -n 19 "$tmp/others" >> "$tmp/one"
if sh "$dir/packets.sh" "$tmp/bad-clock" "$tmp/one" 2>"$tmp/error"; then exit 1; fi
grep -F 'invalid live JANUS instant' "$tmp/error" >/dev/null
# A normal JSON parser would discard the first value and see the valid baseline.
for duplicate in \
  'sub("\"schema\":"; "\"schema\":\"wrong\",\"schema\":")' \
  'sub("\"token_ids\":"; "\"token_ids\":[0],\"token_ids\":")' \
  'sub("\"utf8_hex\":"; "\"utf8_\\u0068ex\":\"00\",\"utf8_hex\":")'; do
    jq -Rr "$duplicate" "$dir/base.json" > "$tmp/broken.json"
    jq -es 'length == 1 and .[0].audition[0].base.stop == "cap"' "$tmp/broken.json" >/dev/null
    reject_run "$duplicate"
done
if sh "$dir/packets.sh" "$tmp/failure" /dev/null > /dev/null 2>&1 || test -e "$tmp/failure"; then
    echo 'Failed packet build left a published result' >&2; exit 1
fi
sh "$dir/packets.sh" "$tmp/failure"
if sh "$dir/packets.sh" "$tmp/failure" > /dev/null 2>&1; then echo 'Overwrote packets' >&2; exit 1; fi
# Another process can reserve even an empty directory while packets are built.
cat > "$tmp/cc-claim" <<'CC'
#!/bin/sh
mkdir "$CLAIMED_DIR"
exec "$REAL_CC" "$@"
CC
chmod +x "$tmp/cc-claim"
if CLAIMED_DIR="$tmp/claimed" REAL_CC="${CC:-cc}" CC="$tmp/cc-claim" \
    sh "$dir/packets.sh" "$tmp/claimed" >"$tmp/log" 2>&1; then
    echo 'Overwrote a directory created during the build' >&2; exit 1
fi
test -d "$tmp/claimed"
test -z "$(ls -A "$tmp/claimed")"
echo 'Verified review IDs, token streams, transcript bytes and rejection of malformed receipts'
