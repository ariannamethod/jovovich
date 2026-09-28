#!/usr/bin/env python3
"""Run fixed held-out prompts through JOVOVICH's native notorch executable."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("models", nargs="+", type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--runner", type=Path, default=Path("build/jovovich-infer"))
    p.add_argument("--tokens", type=int, default=128)
    p.add_argument("--threads", type=int, default=2)
    p.add_argument("--names", nargs="+")
    p.add_argument("--cases", type=Path, help="alternate name/prompt JSONL cases")
    p.add_argument("--identity", type=Path, help="system identity text; defaults to the original SFT identity")
    args = p.parse_args()
    here = Path(__file__).resolve().parent
    cases_text = (args.cases or here / "eval.jsonl").read_text()
    rows = [json.loads(line) for line in cases_text.splitlines() if line.strip()]
    if args.names:
        unknown = set(args.names) - {row["name"] for row in rows}
        if unknown:
            p.error("unknown prompt names: " + ", ".join(sorted(unknown)))
        rows = [row for row in rows if row["name"] in args.names]
    system = (args.identity.read_text().strip() if args.identity else
              json.loads((here / "sft.jsonl").read_text().splitlines()[0])["messages"][0]["content"])
    env = dict(os.environ, NT_NO_I8="1", NT_QMV_THREADS=str(args.threads), NT_ATTN_THREADS=str(args.threads))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        for model in args.models:
            with model.open("rb") as body:
                model_hash = hashlib.sha256()
                for chunk in iter(lambda: body.read(1024 * 1024), b""):
                    model_hash.update(chunk)
                model_sha256 = model_hash.hexdigest()
            for row in rows:
                prompt = f'<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{row["prompt"]}<|im_end|>\n<|im_start|>assistant\n'
                started = time.monotonic()
                result = subprocess.run([str(args.runner), "--model", str(model), "--tokens", str(args.tokens), "--context", "2048", "--temperature", "0"], input=prompt, text=True, capture_output=True, env=env)
                record = dict(row, model=str(model), model_sha256=model_sha256,
                              prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                              cases_sha256=hashlib.sha256(cases_text.encode()).hexdigest(),
                              identity_sha256=hashlib.sha256(system.encode()).hexdigest(),
                              decoding=dict(tokens=args.tokens, context=2048, temperature=0,
                                            NT_NO_I8="1", NT_QMV_THREADS=str(args.threads), NT_ATTN_THREADS=str(args.threads)),
                              elapsed_ms=round((time.monotonic()-started)*1000),
                              response=result.stdout.strip(), returncode=result.returncode)
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
