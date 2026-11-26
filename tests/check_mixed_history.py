#!/usr/bin/env python3
"""Mixed-review persistence with synthetic scores; native inference is separate."""
import argparse
import copy
import hashlib
import json
import resource
import signal
import struct
import subprocess
import tempfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from check_visual_batch import ROOT, command, encode, fake_visual
from check_visual_memory import ENV, digest, git, synthetic
from review_comparison_checks import check_comparisons
from report_comparison_checks import check_report_comparisons


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default=str(ROOT / "build/jovovich-report"))
    parser.add_argument("--replay", default=str(ROOT / "build/jovovich-replay"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp); repo = work / "repo"; memory = work / "memory"
        repo.mkdir(); memory.mkdir()
        git(repo, "init", "-q"); git(repo, "config", "user.name", "Mixed history fixture")
        git(repo, "config", "user.email", "fixture@example.invalid")
        (repo / "RULES.md").write_text("Buttons must say Save.\n")
        commits, pixels = [], []
        for i, label in enumerate(("Delete", "Save", "Delete", "Delete")):
            (repo / "panel.html").write_text(f"<button>{label}</button>\n")
            pixels.append(b"P6\n1 1\n255\n" + bytes((i * 60, 0, 0)))
            (repo / "screen.ppm").write_bytes(pixels[-1])
            git(repo, "add", "."); git(repo, "commit", "-qm", f"state {i}")
            commits.append(git(repo, "rev-parse", "HEAD"))

        remembered = set()

        def prepare(scope, pr, before, after, clean):
            key = f"screen-{pr}-{before}-{after}"; sequences = []
            for index in (before, after):
                image = work / "capture.ppm"; image.write_bytes(pixels[index])
                row = dict(id=f"image-{scope}-{pr}-{index}", question="Which button is visible?",
                    choice_a="Save", choice_b="Delete", image=dict(path=str(image), sha256=digest(pixels[index])),
                    remember=dict(repository=scope, key=key, pull_request=pr, checkout=str(repo),
                        commit=commits[index], path="screen.ppm", supersedes=sequences[-1] if sequences else 0))
                receipt = json.loads(command([ROOT / "build/visual-memory-fixture", memory],
                    (encode(row)+"\n"+encode(synthetic(row))+"\n").encode()))
                sequences.append(receipt["sequence"])
            request = dict(id=key, compare=dict(repository=scope, key=key, checkout=str(repo),
                before=sequences[0], after=sequences[1], rules=dict(path="RULES.md", first=1, last=1)))
            request_file = work / "request.jsonl"; request_file.write_text(encode(request)+"\n")
            recall = scope in remembered
            packed = command([ROOT / "build/jovovich-pack", "--recall" if recall else "--remember", memory, scope, "button-rule",
                "--with-visual", memory, scope, pr, request_file, "--all", repo,
                commits[before], commits[after], *([] if recall else ["RULES.md"])])
            remembered.add(scope)
            rows = [json.loads(x) for x in packed.splitlines()]
            text = work / "text.jsonl"
            text.write_bytes(b"".join(line for line,row in zip(packed.splitlines(keepends=True),rows) if "visual_request" not in row))
            answer = command([ROOT / "build/batch-fixture", "emit", text, "clean"]) if text.stat().st_size else b""
            answer += fake_visual(request, memory, not clean)
            stem = f"{scope.split('/')[1]}-{pr}-{before}-{after}"
            batch, answers, metadata = (work / (stem + suffix) for suffix in (".batch", ".answers", ".pr"))
            batch.write_bytes(packed); answers.write_bytes(answer)
            meta = dict(number=pr, url=f"https://github.com/{scope}/pull/{pr}", createdAt="2026-10-01T09:00:00Z",
                        baseRefOid=commits[before], headRefOid=commits[after])
            metadata.write_text(encode(meta))
            return dict(scope=scope, pr=pr, batch=batch, answers=answers, metadata=metadata, rows=rows, votes=answer, meta=meta)

        east = prepare("fixture/east", 7, 0, 1, False)
        update = prepare("fixture/east", 7, 1, 2, True)
        west = prepare("fixture/west", 7, 0, 1, True)
        other_pr = prepare("fixture/east", 8, 0, 1, True)
        image_only = prepare("fixture/east", 9, 2, 3, True)

        def snapshots():
            return {p.name:p.read_bytes() for p in memory.glob("*.checkpoint")}

        def report(case, record=True, markdown=False, ok=True, extra=(), file_limit=None):
            cmd = [args.report, case["batch"], case["answers"], "--with-visual", memory, case["scope"], case["pr"]]
            if not markdown: cmd += ["--json"]
            if record: cmd += ["--memory", memory, "--record-pr", case["scope"], case["metadata"]]
            if file_limit is not None:
                def limit_output():
                    resource.setrlimit(resource.RLIMIT_FSIZE,(file_limit,file_limit))
                    signal.signal(signal.SIGXFSZ,signal.SIG_IGN)
                p = subprocess.run([str(x) for x in cmd],cwd=ROOT,env=ENV,capture_output=True,preexec_fn=limit_output)
                assert p.returncode != 0 and not p.stdout and b"save before commit failed" in p.stderr, (p.returncode,p.stderr)
                return p.stdout
            return command([*cmd, *extra], ok=ok)

        def history(scope="fixture/east", number=7, head=None, ok=True):
            return command([args.replay, "history", memory, scope,
                            *([] if number is None else [number]), *([head] if head else [])], ok=ok)

        original = snapshots()
        baseline = report(east, record=False)
        assert snapshots() == original
        assert report(east) == baseline
        first_bytes = history(); first = json.loads(first_bytes)
        assert first["status"] == "reviewed" and len(first["observations"]) == 1
        entry = first["observations"][0]; evidence = entry["evidence"]; saved = evidence["review"]
        assert evidence["findings"] == [] and "snapshot_coverage" not in evidence
        assert saved["schema"] == "jovovich.mixed-review/1"
        assert saved["summary"]["verdict"] == "CONCERN"
        assert [f["input"] for f in saved["files"]] == east["rows"]
        assert [f["answer"] for f in saved["files"]] == [json.loads(x) for x in east["votes"].splitlines()]
        assert entry["opened_at"] != entry["checked_at"]
        assert first["created_at"] == east["meta"]["createdAt"]
        assert evidence["fact"] == east["rows"][0]["fact"]
        after = snapshots(); report(east, markdown=True)
        assert snapshots() == after and history() == first_bytes
        # Concurrent publication retries share the writer lock and keep the first clock.
        with ThreadPoolExecutor(max_workers=3) as pool:
            assert all(x == baseline for x in pool.map(lambda _:report(east), range(3)))
        assert snapshots() == after

        journal = memory / ("pr-"+hashlib.sha256(b"fixture/east").hexdigest()+"-7.checkpoint")
        limit = journal.stat().st_size + 512
        assert len(report(update, record=False)) < limit
        report(update, file_limit=limit)
        assert snapshots() == after and history() == first_bytes
        report(update)
        full = json.loads(history()); assert len(full["observations"]) == 2
        assert full["observations"][0] == entry
        assert [r["evidence"]["review"]["summary"]["verdict"] for r in full["observations"]] == ["CONCERN", "CLEAN"]
        assert json.loads(history(head=commits[1]))["observations"] == [entry]
        assert len(json.loads(history(head=commits[2]))["observations"]) == 1
        report(west); report(other_pr); report(image_only)
        assert len(json.loads(history("fixture/west"))["observations"]) == 1
        assert len(json.loads(history(number=8))["observations"]) == 1
        single = json.loads(history(number=9))["observations"][0]["evidence"]["review"]
        assert single["summary"] == single["visual_summary"] | {"verdict":"CLEAN"}
        assert [f["input"] for f in single["files"]] == image_only["rows"]
        assert len(single["files"]) == 1
        assert json.loads(history("fixture/absent"))["observations"] == []
        listed = json.loads(history(number=None))["pull_requests"]
        assert [(x["number"],x["observations"]) for x in listed] == [(7,2),(8,1),(9,1)]

        # Every failed publication leaves all existing checkpoints byte-identical.
        stable = snapshots()
        invalid = [{field:value} for field,value in (("number",8), ("url","https://github.com/fixture/west/pull/7"),
                             ("baseRefOid",commits[2]), ("headRefOid",commits[0]),
                             ("createdAt","2026-10-02T09:00:00Z"), ("createdAt","2999-01-01T00:00:00Z"))]
        invalid.append(dict(number=8,url="https://github.com/fixture/east/pull/8"))
        for changes in invalid:
            meta = copy.deepcopy(east["meta"]); meta.update(changes)
            east["metadata"].write_text(encode(meta)); report(east, ok=False)
            assert snapshots() == stable, changes
        east["metadata"].write_text(encode(east["meta"]))
        east["answers"].write_bytes(east["votes"].splitlines(keepends=True)[0])
        report(east, ok=False); assert snapshots() == stable
        votes = [json.loads(x) for x in east["votes"].splitlines()]
        votes[-1]["prompt_sha256"] = "0" * 64
        east["answers"].write_text("".join(encode(x)+"\n" for x in votes))
        report(east, ok=False); assert snapshots() == stable
        east["answers"].write_bytes(east["votes"])
        for extra in (("--memory",memory), ("--record-pr",east["scope"],east["metadata"])):
            report(east, record=False, extra=extra, ok=False)
        report(east, extra=("--snapshot",repo,"/unused","panel.html"), ok=False)
        assert snapshots() == stable
        # Each row is within the input limit; their complete saved review exceeds
        # the AML string limit. Ordinary reporting works, recording is atomic.
        large = dict(east, batch=work / "large.batch", answers=work / "large.answers")
        padded = [b" " * 600000 + line for line in east["batch"].read_bytes().splitlines(keepends=True)]
        large["batch"].write_bytes(b"".join(padded))
        one = work / "large-text.jsonl"; one.write_bytes(padded[0])
        large["answers"].write_bytes(command([ROOT / "build/batch-fixture", "emit", one, "clean"]) +
                                    east["votes"].splitlines(keepends=True)[-1])
        assert json.loads(report(large, record=False))["summary"]["verdict"] == "CONCERN"
        report(large, ok=False); assert snapshots() == stable
        check_report_comparisons(args.report,args.replay,work,memory,[east,update,west,other_pr,image_only])
        # Reading historical observations needs neither current Git nor the visual checkpoint.
        expected = history()
        (memory / "visual.checkpoint").rename(memory / "visual.offline")
        repo.rename(work / "repo.offline")
        assert history() == expected
        assert (memory / "rules.checkpoint").read_bytes() == original["rules.checkpoint"]
        check_comparisons(args.replay,work,memory,full["observations"])
        # A corrupted stored mixed observation cannot publish a partial history.
        raw = journal.read_bytes(); needle=b"jovovich.mixed-review/1"
        assert needle in raw
        for before, after in ((needle,b"jovovich.mixed-review/9"),
                              (b'"verdict":"CONCERN"',b'"verdict":"CLEAN  "')):
            assert before in raw
            altered = bytearray(raw.replace(before,after,1))
            journal.write_bytes(altered)
            history(ok=False)
            # Repair the AML container CRC so the review's schema/digest gate,
            # independently of checkpoint decoding, must reject the changed row.
            crc = zlib.crc32(altered[:28] + altered[32:])
            struct.pack_into("<I",altered,28,crc)
            journal.write_bytes(altered)
            history(ok=False)
        journal.write_bytes(raw)
        assert history() == expected
        print("PASS: mixed-review persistence/restart, exact receipts, idempotent/concurrent retries, repository/PR/head isolation, atomic rejection, offline and damaged history")


if __name__ == "__main__":
    main()
