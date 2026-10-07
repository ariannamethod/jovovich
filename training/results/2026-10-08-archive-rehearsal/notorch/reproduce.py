#!/usr/bin/env python3
"""Rebuild pinned/current CPU Chuck from Git blobs and compare complete traces."""
import argparse
import hashlib
import json
import pathlib
import platform
import subprocess
import tempfile
from datetime import datetime, timezone

BASELINE = "014403faa76b795aefe18a4781980f5b140e0ed3"
CANDIDATE = "420fa54fe3b92cdb2f83e20d19fc887b09db3d8e"
FIXTURE = "tests/chuck_legacy_parity.c"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()

    def blob(commit, name):
        return subprocess.check_output(
            ["git", "--no-replace-objects", "-C", str(repo), "show", commit + ":" + name])

    inputs = {}
    outputs = {}
    traces = {}
    with tempfile.TemporaryDirectory(prefix="jovovich-notorch-audit-") as name:
        root = pathlib.Path(name)
        fixture = root / "fixture.c"
        fixture_bytes = blob(CANDIDATE, FIXTURE)
        fixture.write_bytes(fixture_bytes)
        for label, commit, files in [
            ("pinned", BASELINE, ["notorch.c", "notorch.h"]),
            ("current", CANDIDATE, ["notorch.c", "notorch.h", "chuck_architect.h", "chuck_architect_impl.h"]),
        ]:
            source = root / label
            source.mkdir()
            inputs[label] = {}
            for path in files:
                data = blob(commit, path)
                (source / path).write_bytes(data)
                inputs[label][path] = {"bytes": len(data), "sha256": sha(data)}
            binary = root / (label + ".bin")
            command = ["cc", "-O2", "-std=gnu11", "-pthread", "-I" + str(source),
                       str(source / "notorch.c"), str(fixture), "-lm", "-o", str(binary)]
            subprocess.run(command, check=True, capture_output=True)
            result = subprocess.run([str(binary)], check=True, capture_output=True)
            traces[label] = result.stdout
            outputs[label] = {"bytes": len(result.stdout), "sha256": sha(result.stdout),
                              "return_code": result.returncode}

    report = {
        "schema": "jovovich.notorch-update-audit.v1",
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "repository": "https://github.com/ariannamethod/notorch",
        "baseline": BASELINE,
        "candidate": CANDIDATE,
        "fixture": {"commit": CANDIDATE, "path": FIXTURE, "sha256": sha(fixture_bytes)},
        "reproducer_sha256": sha(pathlib.Path(__file__).read_bytes()),
        "compiler": subprocess.check_output(["cc", "--version"], text=True).splitlines()[0],
        "platform": platform.platform(),
        "command_each_side": "cc -O2 -std=gnu11 -pthread -I<SOURCE> <SOURCE>/notorch.c fixture.c -lm -o <BINARY>",
        "source_policy": "Git blobs at exact commits; each side uses its own header; no BLAS/SIMD/CUDA",
        "steps": 6000,
        "trace_content": "Every global/local Chuck state, parameter, first/second Adam moment and timestep; fixture requires noise, freeze and macro LR adjustment",
        "inputs": inputs,
        "outputs": outputs,
        "byte_identical": traces["pinned"] == traces["current"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"byte_identical": report["byte_identical"], "steps": report["steps"],
                      "outputs": outputs}, indent=2))
    return 0 if report["byte_identical"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
