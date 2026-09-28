#!/usr/bin/env python3
"""Pack the JSONL curriculum for the C trainer; tokenization stays in notorch."""
import argparse
import json
from pathlib import Path
import struct


def prepare(sft_path, dpo_path, output):
    rows = []
    for raw in sft_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(raw)
        messages = row["messages"]
        if [m["role"] for m in messages] != ["system", "user", "assistant"]:
            raise ValueError("SFT examples must be system/user/assistant triples")
        rows.append((0, *(m["content"] for m in messages), ""))
    for raw in dpo_path.read_text(encoding="utf-8").splitlines():
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
    print(f"packed {len(rows)} examples into {output}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    p.add_argument("--sft", type=Path, default=Path(__file__).with_name("sft.jsonl"))
    p.add_argument("--dpo", type=Path, default=Path(__file__).with_name("dpo.jsonl"))
    a = p.parse_args()
    prepare(a.sft, a.dpo, a.output)
