#!/usr/bin/env python3
"""Replay PR 57's text gate against its two historical Git requirements."""

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import tempfile


BASE = "a99d18b1d9ecc50ef0998fa81aec94f497d161a4"
PROTOCOL = "d7276bef471ba99674680418cb675e239237a9f4"
HEAD = "d34fce85d380e0ec1a267754a6291571add31255"
AML = "8f577e8c0d6171012ae056b55b813443ab3ef9d2"
NOTORCH = "560a6e186b58bea79c47b2571e844a35ae541244"
FILE = "src/trace_gate.c"
OLD_RULE = "Both `base` and `head` are arrays of up to 32 callback names for every metric.\n"
NEW_RULE = (
    "This gives six independent repair/regression pairs, with two presentations\n"
    "per direction: source alone and source plus the measured distinguishing\n"
    "output. Attach the latter through the differential evidence gate. It gives\n"
    "AML the expected text and the head's observed text. Each pair shares its mode\n"
    "number. Keep labels, PR URLs and scorer metadata out of the prompt.\n"
)
REJECTED = "text input rejected"
FORWARDED = "text input accepted with expected and observed values in AML"
RECEIPT = ('Execution at mode = 0. Required output text = "1.0-rc.2". '
           'Observed output text = "1.0-rc.1".')
PROBE = r'''
#define main archived_selftest
#include "tests/check_trace_gate.c"
#undef main
#include "json.h"
int main(void) {
    jov_trace_receipt r;
    am_init();
    am_persistent_mode(1);
    assert(!hash_bytes("rule",4,rule_sha) && !hash_bytes("code",4,change_sha));
    const char *control = "[{\"mode\":0,\"base\":[\"start\"],\"head\":[\"stop\"],\"required\":[\"stop\"]}]";
    assert(!apply("\"metric\":\"sequence\"",control,1,0,&r));
    assert(r.differing == 1 && strstr(am_get_var_text("review_context"),r.observation));
    const char *input = "[{\"mode\":0,\"base\":\"1.0-rc.0\",\"head\":\"1.0-rc.1\",\"required\":\"1.0-rc.2\"}]";
    memset(&r,0,sizeof(r));
    int rejected = apply("\"metric\":\"text\"",input,1,0,&r);
    if (rejected) {
        assert(!strcmp(am_get_var_text("review_context"),"original review"));
    } else {
        assert(r.differing == 1);
        assert(strstr(r.observation,"Required output text = \"1.0-rc.2\"."));
        assert(strstr(r.observation,"Observed output text = \"1.0-rc.1\"."));
        assert(strstr(am_get_var_text("review_context"),r.observation));
    }
    printf("{\"accepted\":%s,\"observation\":",rejected ? "false" : "true");
    json_string(stdout,r.observation);
    fputs(",\"context\":",stdout);
    json_string(stdout,am_get_var_text("review_context"));
    puts("}");
    am_persistent_mode(0);
}
'''


def command(args, *, cwd=None, data=None):
    return subprocess.run([str(x) for x in args], cwd=cwd, input=data,
                          stdout=subprocess.PIPE, check=True).stdout


def git(repo, *args):
    return command(["git", "-C", repo, *args])


def archive(repo, revision, destination, *paths):
    data = git(repo, "archive", revision, *paths)
    destination.mkdir()
    with tarfile.open(fileobj=io.BytesIO(data)) as stream:
        stream.extractall(destination, filter="data")


def driver():
    action, repo, revision, file, mode = sys.argv[1:6]
    assert file == FILE and mode == "0" and revision in (BASE, PROTOCOL, HEAD)
    if action == "expect":
        path, first, last = sys.argv[6:9]
        lines = git(repo, "show", f"{revision}:{path}").decode().splitlines(keepends=True)
        quote = "".join(lines[int(first) - 1:int(last)])
        required = {OLD_RULE: REJECTED, NEW_RULE: FORWARDED}[quote]
        print(json.dumps({"metric": "text", "required": required}))
        return

    for dependency, expected in (("aml", AML), ("notorch", NOTORCH)):
        assert git(repo, "rev-parse", f"{revision}:deps/{dependency}").decode().strip() == expected
    work = Path(os.environ["JOV_PR57_WORK"])
    original = Path(os.environ["JOV_REPOSITORY_PATH"])
    aml, notorch = work / "aml", work / "notorch"
    if not aml.exists():
        archive(original / "deps/aml", AML, aml, "Makefile", "core")
        command(["make", "-C", aml, "libaml.a"])
        archive(original / "deps/notorch", NOTORCH, notorch,
                "sha256.c", "sha256.h", "tools/narrow_json.h")
    with tempfile.TemporaryDirectory(dir=work, prefix="observe-") as temporary:
        source = Path(temporary) / "source"
        archive(repo, revision, source, "src", "aml", "tests/check_trace_gate.c")
        (source / "probe.c").write_text(PROBE)
        compiler = shlex.split(os.environ.get("CC", "cc"))
        command([*compiler, "-O2", "-std=c11", "-UNDEBUG", "-I", source, "-I", source / "src",
                 "-I", aml / "core", "-I", notorch, source / "probe.c",
                 source / FILE, aml / "libaml.a", notorch / "sha256.c",
                 "-lm", "-pthread", "-o", source / "probe"])
        proof = json.loads(command([source / "probe"], cwd=source))
        # Project the gate's delivery contract after checking its literal AML output.
        if proof["accepted"]:
            assert proof["observation"] == RECEIPT and proof["context"] == "original review\n" + RECEIPT
            observed = FORWARDED
        else:
            assert proof["observation"] == "" and proof["context"] == "original review"
            observed = REJECTED
        evidence = work / f"{revision}.json"
        if evidence.exists():
            assert json.loads(evidence.read_text()) == proof
        evidence.write_text(json.dumps(proof, indent=2) + "\n")
        print(json.dumps(observed))


def check_answers(root, work, inputs):
    manifest = json.loads((root / "models/onejev-0.8b.json").read_text())
    lines = (work / "inputs.jsonl").read_bytes().splitlines(keepends=True)
    answers = [json.loads(line) for line in (work / "answers.jsonl").read_text().splitlines()]
    assert len(answers) == len(inputs)
    measured_verdicts = []
    results = []
    for row, line, answer in zip(inputs, lines, answers):
        assert answer["id"] == row["id"] and answer["scope"]["file"] == FILE
        assert answer["source"] == row["source"] and answer["fact"] == row["fact"]
        for key in ("context", "rule_excerpt", "change_excerpt"):
            assert answer["input"][key] == row[key]
        execution = answer["execution"]
        assert execution["input_sha256"] == hashlib.sha256(line).hexdigest()
        for key in ("weights_sha256", "tokenizer_sha256"):
            assert execution[key] == manifest[key]
        assert execution["arithmetic"] == "float32" and "readout_sha256" not in execution
        probabilities = answer["choice"]["probabilities"]
        concern, clean = probabilities["CONCERN"], probabilities["CLEAN"]
        assert all(math.isfinite(p) and 0 <= p <= 1 for p in (concern, clean))
        assert abs(concern + clean - 1) < 1e-6
        verdict = "CONCERN" if concern >= clean else "CLEAN"
        assert answer["choice"]["verdict"] == verdict
        if "trace_evidence" in row:
            witness = execution["trace_witness"]
            assert witness["runs"] == witness["differing"] == 1 and witness["selected_mode"] == 0
            run = row["trace_evidence"]["runs"][0]
            observation = (f'Execution at mode = 0. Required output text = {json.dumps(run["required"])}. '
                           f'Observed output text = {json.dumps(run["head"])}.')
            assert witness["observation"] == observation
            measured_verdicts.append(verdict)
        else:
            assert "trace_witness" not in execution
        results.append({"receipt": row["fact"]["sequence"],
                        "measured": "trace_evidence" in row,
                        "expected": "CONCERN" if row["fact"]["sequence"] == 1 else "CLEAN",
                        **answer["choice"]})
    print(json.dumps(results, indent=2), flush=True)
    assert measured_verdicts == ["CONCERN", "CLEAN"], "measured reviews failed the recorded requirements"


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, help="new directory for receipts and outputs")
    parser.add_argument("--model", type=Path)
    parser.add_argument("--tokenizer", type=Path)
    parser.add_argument("--reviewer", type=Path, default=root / "build/jovovich")
    args = parser.parse_args()
    if bool(args.model) != bool(args.tokenizer):
        parser.error("--model and --tokenizer must be supplied together")
    if args.work:
        args.work.mkdir(parents=True)
        work = args.work.resolve()
    else:
        work = Path(tempfile.mkdtemp(prefix="jovovich-pr57-")).resolve()
    os.environ["JOV_PR57_WORK"] = str(work)
    store = work / "memory"
    store.mkdir()
    pack = root / "build/jovovich-pack"
    replay = root / "build/jovovich-replay"
    subject = [store, "ariannamethod/jovovich", "trace-input"]

    def packed(*args):
        return json.loads(command([pack, *args], cwd=root))

    # The pre-implementation commit changes only the written trial protocol.
    assert git(root, "diff", "--name-only", BASE, PROTOCOL).decode().splitlines() == [
        "examples/release-trial/protocol.md"]
    first = packed("--remember", *subject, root, BASE, HEAD, "docs/trace-evidence.md", FILE, 26, 26)
    second = packed("--remember", *subject, "--supersedes", 1, root, PROTOCOL, HEAD,
                    "examples/release-trial/protocol.md", FILE, 23, 27)
    old = packed("--recall", *subject, "--as-of", 1, root, PROTOCOL, HEAD, FILE)
    new = packed("--recall", *subject, root, PROTOCOL, HEAD, FILE)
    assert old["rule_excerpt"] == OLD_RULE and new["rule_excerpt"] == NEW_RULE
    assert old["fact"] == first["fact"] and new == second
    assert old["fact"]["sequence"] == 1 and new["fact"]["supersedes"] == 1
    for key in ("base_commit", "head_commit", "diff_sha256"):
        assert old["source"][key] == new["source"][key]
    assert old["change_excerpt"] == new["change_excerpt"] == first["change_excerpt"]
    rejected = subprocess.run([str(x) for x in [pack, "--recall", *subject,
                               root, BASE, HEAD, FILE]], cwd=root, capture_output=True)
    assert rejected.returncode and not rejected.stdout
    (work / "future-receipt.stderr").write_bytes(rejected.stderr)

    inputs = []
    for name, row, required in (("old", old, REJECTED), ("new", new, FORWARDED)):
        source = json.dumps(row) + "\n"
        (work / f"{name}-source.jsonl").write_text(source)
        output = command([replay, "probe", root, Path(__file__).resolve(), 0],
                         cwd=root, data=source.encode())
        (work / f"{name}-measured.jsonl").write_bytes(output)
        measured = json.loads(output)
        assert measured["trace_evidence"]["runs"] == [
            {"mode": 0, "base": REJECTED, "head": FORWARDED, "required": required}]
        assert measured["trace_evidence"]["harness_sha256"] == hashlib.sha256(
            Path(__file__).read_bytes()).hexdigest()
        assert measured["fact"] == row["fact"]
        inputs.extend((row, measured))
    (work / "inputs.jsonl").write_text("".join(json.dumps(row) + "\n" for row in inputs))
    print(f"Historical sources, receipts, executions and future-receipt rejection passed. {work}", flush=True)
    if not args.model:
        return
    with (work / "answers.jsonl").open("wb") as output:
        subprocess.run([str(args.reviewer.resolve()), str(args.model.resolve()),
                        str(args.tokenizer.resolve()), "--json"], cwd=root,
                       input=(work / "inputs.jsonl").read_bytes(), stdout=output, check=True)
    check_answers(root, work, inputs)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("observe", "expect"):
        driver()
    else:
        main()
