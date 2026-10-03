#!/usr/bin/env python3
"""Pack the JSONL curriculum for the C trainer; tokenization stays in notorch."""
import argparse
import json
from pathlib import Path
import struct


def review_pairs(data):
    """Identify explicit concern/clean partners; token positions stay native."""
    pairs = {}
    for index, row in enumerate(data):
        if row.get("kind") != "review":
            continue
        pair_id = row.get("pair")
        if not isinstance(pair_id, str) or not pair_id:
            raise ValueError("review rows require a nonempty pair ID")
        answer = json.loads(row["messages"][2]["content"])
        if not isinstance(answer, dict) or not isinstance(answer.get("findings"), list):
            raise ValueError("review answers require a findings array")
        side = "concern" if answer["findings"] else "clean"
        pair = pairs.setdefault(pair_id, {})
        if side in pair:
            raise ValueError("each review pair requires one concern and one clean row")
        pair[side] = index
    if not pairs or any(set(pair) != {"concern", "clean"} for pair in pairs.values()):
        raise ValueError("review pairs must contain both concern and clean rows")
    return [(pair["concern"], pair["clean"]) for pair in pairs.values()]


def review_prefixes(data):
    """Return exact prefixes ending inside each top-level literal findings key.

    JVPR2 lets the native tokenizer locate the verdict independently for each
    answer, including answers with explanations of different lengths. The
    closing quote of the findings key is excluded. The compact findings-array
    boundary lets the native tokenizer verify a concern/clean branch token.
    """
    pairs = review_pairs(data)

    def unique_object(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("JVPR2 review answers must not contain duplicate JSON keys")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"JVPR2 review answers require standard JSON: {value}")

    decoder = json.JSONDecoder(object_pairs_hook=unique_object,
                               parse_constant=invalid_constant)
    whitespace = json.decoder.WHITESPACE.match
    prefixes = {}
    for index in sorted(i for pair in pairs for i in pair):
        answer = data[index]["messages"][2]["content"]
        # Validate the entire object before walking its top-level members. In
        # particular, duplicates after findings or inside a nested object fail.
        decoded = decoder.decode(answer)
        findings = decoded["findings"]
        if any(not isinstance(finding, dict) for finding in findings):
            raise ValueError("JVPR2 concern findings must be nonempty arrays of objects")
        position = whitespace(answer, 0).end() + 1  # validated opening brace
        while True:
            position = whitespace(answer, position).end()
            if answer[position] == "}":
                break
            key, end = decoder.raw_decode(answer, position)
            spelling = answer[position:end]
            if "\\" in spelling:
                raise ValueError("JVPR2 requires literal, unescaped top-level JSON keys")
            if key == "findings":
                boundary = '":[{' if findings else '":[]'
                if not answer.startswith(boundary, end - 1):
                    raise ValueError(
                        "JVPR2 requires a compact findings boundary "
                        f"{boundary!r}; remove whitespace between the key, colon, "
                        "array and first branch")
                prefixes[index] = answer[:end - 1]
            position = whitespace(answer, end).end() + 1  # validated colon
            position = whitespace(answer, position).end()
            _, position = decoder.raw_decode(answer, position)
            position = whitespace(answer, position).end()
            if answer[position] == "}":
                break
            position += 1  # validated comma
        if index not in prefixes:
            raise ValueError("JVPR2 review answers require a literal findings key")
    return prefixes


def prepare(sft_path, dpo_path, output, pair_output=None, pair_format=1):
    if pair_format not in (1, 2):
        raise ValueError("review pair format must be 1 or 2")
    if pair_format == 2 and not pair_output:
        raise ValueError("review pair format 2 requires a review pair output")
    rows = []
    data = [json.loads(raw) for raw in sft_path.read_text(encoding="utf-8").splitlines()]
    for row in data:
        messages = row["messages"]
        if [m["role"] for m in messages] != ["system", "user", "assistant"]:
            raise ValueError("SFT examples must be system/user/assistant triples")
        rows.append((0, *(m["content"] for m in messages), ""))
    if pair_output and dpo_path:
        raise ValueError("review pair maps require SFT-only data")
    if pair_output and pair_output.resolve() == output.resolve():
        raise ValueError("dataset and review pair map need distinct output paths")
    pairs = review_pairs(data) if pair_output else None
    prefixes = review_prefixes(data) if pair_format == 2 else None
    for raw in (dpo_path.read_text(encoding="utf-8").splitlines() if dpo_path else []):
        row = json.loads(raw)
        rows.append((1, row["system"], row["prompt"], row["chosen"], row["rejected"]))
    # Encode and validate both payloads before touching either destination.
    dataset_bytes = bytearray(b"JVDS\x01\x00\x00\x00")
    dataset_bytes.extend(struct.pack("<I", len(rows)))
    for kind, *fields in rows:
        dataset_bytes.extend(struct.pack("<I", kind))
        for value in fields:
            encoded = value.encode("utf-8")
            dataset_bytes.extend(struct.pack("<I", len(encoded)))
            dataset_bytes.extend(encoded)
    pair_bytes = None
    if pair_output:
        pair_bytes = bytearray(b"JVPR" + struct.pack("<I", pair_format))
        pair_bytes.extend(struct.pack("<II", len(rows), len(pairs)))
        for concern, clean in pairs:
            pair_bytes.extend(struct.pack("<II", concern, clean))
            if prefixes is not None:
                for index in (concern, clean):
                    encoded = prefixes[index].encode("utf-8")
                    pair_bytes.extend(struct.pack("<I", len(encoded)))
                    pair_bytes.extend(encoded)
    output.write_bytes(dataset_bytes)
    if pair_output:
        pair_output.write_bytes(pair_bytes)
        print(f"packed {len(pairs)} review pairs into {pair_output}")
    print(f"packed {len(rows)} examples into {output}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    p.add_argument("--sft", type=Path, default=Path(__file__).with_name("sft.jsonl"))
    p.add_argument("--dpo", type=Path, default=Path(__file__).with_name("dpo.jsonl"))
    p.add_argument("--sft-only", action="store_true", help="pack only SFT rows for the internal MLP trainer")
    p.add_argument("--review-pairs", type=Path, help="also write native JVPR concern/clean row pairs (requires --sft-only)")
    p.add_argument("--pair-format", type=int, choices=(1, 2), default=1,
                   help="JVPR version; 2 records each answer's explicit findings prefix")
    a = p.parse_args()
    if a.review_pairs and not a.sft_only:
        p.error("--review-pairs requires --sft-only")
    if a.pair_format == 2 and not a.review_pairs:
        p.error("--pair-format 2 requires --review-pairs")
    prepare(a.sft, None if a.sft_only else a.dpo, a.output, a.review_pairs, a.pair_format)
