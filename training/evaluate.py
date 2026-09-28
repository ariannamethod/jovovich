#!/usr/bin/env python3
"""Run fixed held-out prompts through JOVOVICH's native notorch executable."""
import argparse
import json
import os
from pathlib import Path
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("models", nargs="+", type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--runner", type=Path, default=Path("build/jovovich-infer"))
    p.add_argument("--tokens", type=int, default=128)
    p.add_argument("--threads", type=int, default=2)
    p.add_argument("--names", nargs="+")
    args = p.parse_args()
    here = Path(__file__).resolve().parent
    rows = [json.loads(line) for line in (here / "eval.jsonl").read_text().splitlines()]
    if args.names:
        unknown = set(args.names) - {row["name"] for row in rows}
        if unknown:
            p.error("unknown prompt names: " + ", ".join(sorted(unknown)))
        rows = [row for row in rows if row["name"] in args.names]
    system = json.loads((here / "sft.jsonl").read_text().splitlines()[0])["messages"][0]["content"]
    env = dict(os.environ, NT_NO_I8="1", NT_QMV_THREADS=str(args.threads), NT_ATTN_THREADS=str(args.threads))
    with args.output.open("w", encoding="utf-8") as output:
        for model in args.models:
            for row in rows:
                prompt = f'<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{row["prompt"]}<|im_end|>\n<|im_start|>assistant\n'
                result = subprocess.run([str(args.runner), "--model", str(model), "--tokens", str(args.tokens), "--context", "2048", "--temperature", "0"], input=prompt, text=True, capture_output=True, env=env)
                record = dict(row, model=str(model), response=result.stdout.strip(), returncode=result.returncode)
                if result.returncode:
                    record["error"] = result.stderr
                line = json.dumps(record, ensure_ascii=False)
                output.write(line + "\n")
                output.flush()
                print(line, flush=True)
                if result.returncode:
                    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
