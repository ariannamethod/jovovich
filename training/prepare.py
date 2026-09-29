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


def prepare(sft_path, dpo_path, output, pair_output=None):
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
    for raw in (dpo_path.read_text(encoding="utf-8").splitlines() if dpo_path else []):
        row = json.loads(raw)
        rows.append((1, row["system"], row["prompt"], row["chosen"], row["rejected"]))
    with output.open("wb") as f:
        f.write(b"JVDS\x01\x00\x00\x00")
        f.write(struct.pack("<I", len(rows)))
        for kind, *fields in rows:
            f.write(struct.pack("<I", kind))
            for value in fields:
                data = value.encode("utf-8")
                f.write(struct.pack("<I", len(data)))
                f.write(data)
    if pair_output:
        with pair_output.open("wb") as f:
            f.write(b"JVPR\x01\x00\x00\x00")
            f.write(struct.pack("<II", len(rows), len(pairs)))
            for concern, clean in pairs:
                f.write(struct.pack("<II", concern, clean))
        print(f"packed {len(pairs)} review pairs into {pair_output}")
    print(f"packed {len(rows)} examples into {output}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    p.add_argument("--sft", type=Path, default=Path(__file__).with_name("sft.jsonl"))
    p.add_argument("--dpo", type=Path, default=Path(__file__).with_name("dpo.jsonl"))
    p.add_argument("--sft-only", action="store_true", help="pack only SFT rows for the internal MLP trainer")
    p.add_argument("--review-pairs", type=Path, help="also write native JVPR concern/clean row pairs (requires --sft-only)")
    a = p.parse_args()
    if a.review_pairs and not a.sft_only:
        p.error("--review-pairs requires --sft-only")
    prepare(a.sft, None if a.sft_only else a.dpo, a.output, a.review_pairs)
