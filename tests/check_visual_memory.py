#!/usr/bin/env python3
"""Fixed observation/correction/restart gates; optional actual OneJev inference.

Expected before execution: east blue -> red, west blue throughout; knowledge
cutoff 1 returns east blue. Recall in both option orders returns those values.
Git mismatches, stale corrections and future cutoffs fail without a write.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "NT_ATTN_THREADS": "2"}
MANIFEST = json.loads((ROOT / "models/onejev-0.8b-vision.json").read_text())


def run(cmd, rows=None, ok=True, capture=None):
    data = None if rows is None else "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows)
    p = subprocess.run([str(x) for x in cmd], input=data, text=True, capture_output=True, cwd=ROOT, env=ENV)
    if capture is not None:
        capture.with_suffix(".stdout.jsonl").write_text(p.stdout)
        capture.with_suffix(".stderr").write_text(p.stderr)
        if data is not None:
            capture.with_suffix(".input.jsonl").write_text(data)
    if ok:
        assert p.returncode == 0, (cmd, p.returncode, p.stderr)
        return [json.loads(x) for x in p.stdout.splitlines()]
    assert p.returncode != 0 and not p.stdout, (cmd, p.stdout, p.stderr)
    return []


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], env=ENV, stderr=subprocess.DEVNULL).decode().strip()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def image(color):
    return b"P6\n256 256\n255\n" + bytes(color) * (256 * 256)


def checkpoint(memory):
    path = memory / "visual.checkpoint"
    return path.read_bytes() if path.exists() else b""


def synthetic(row):
    return dict(schema="jovovich.visual-choice/1", id=row["id"], question=row["question"],
                choice_a=row["choice_a"], choice_b=row["choice_b"], input_sha256=digest((json.dumps(row, separators=(",", ":")) + "\n").encode()),
                prompt_sha256="1" * 64, **{k: MANIFEST[k] for k in ("weights_sha256", "tokenizer_sha256", "vision_weights_sha256")},
                image=dict(sha256=row["image"]["sha256"], width=256, height=256, resized_width=256,
                           resized_height=256, tokens=64, max_pixels=262144),
                logit_a=2, logit_b=1, p_a=0.7310586, p_b=0.2689414, letter="A",
                observed_at=dict(schema="janus.instant/1", time_scale="posix", unix_day=20781, second=1, millisecond=0))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model")
    parser.add_argument("--tokenizer")
    parser.add_argument("--vision")
    parser.add_argument("--work")
    parser.add_argument("--fixture", default=str(ROOT / "build/visual-memory-fixture"))
    args = parser.parse_args()
    live = bool(args.model)
    if live:
        assert args.tokenizer and args.vision
    if args.work:
        directory = Path(args.work).resolve()
        directory.mkdir(parents=True, exist_ok=False)
        cleanup = None
    else:
        cleanup = tempfile.TemporaryDirectory(prefix="jov-visual-memory-")
        directory = Path(cleanup.name)
    memory = directory / "memory"
    memory.mkdir()
    repo = directory / "east"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Visual memory test")
    git(repo, "config", "user.email", "test@example.invalid")
    blue = directory / "blue.ppm"
    red = directory / "red.ppm"
    blue.write_bytes(image((10, 20, 240)))
    red.write_bytes(image((240, 20, 10)))
    (repo / "screen.ppm").write_bytes(blue.read_bytes())
    git(repo, "add", "screen.ppm")
    git(repo, "commit", "-qm", "blue observation")
    first = git(repo, "rev-parse", "HEAD")
    (repo / "screen.ppm").write_bytes(red.read_bytes())
    git(repo, "commit", "-qam", "red correction")
    second = git(repo, "rev-parse", "HEAD")
    west = directory / "west"
    subprocess.run(["git", "clone", "-q", str(repo), str(west)], check=True)
    replay = [ROOT / "build/jovovich-replay", "visual", memory]
    fixture = [Path(args.fixture).resolve(), memory]
    infer = [ROOT / "build/jovovich", Path(args.model).resolve(), Path(args.tokenizer).resolve()] if live else None

    def row(scope, color, parent=0, key="status", identifier=None):
        path = blue if color == "blue" else red
        return dict(id=identifier or f"{scope}-{color}-{key}", question="Is the image predominantly red or blue?",
                    choice_a=color, choice_b="red" if color == "blue" else "blue",
                    image=dict(path=str(path), sha256=digest(path.read_bytes())),
                    remember=dict(repository=f"studio/{scope}", key=key, pull_request=7,
                                  checkout=str(repo if scope == "east" else west), commit=first if color == "blue" else second,
                                  path="screen.ppm", supersedes=parent))

    recordings = 0

    def record(r, ok=True):
        nonlocal recordings
        if live:
            recordings += 1
            answer = run(infer + ["--vision", Path(args.vision).resolve(), "--visual-memory", memory], [r], ok,
                         capture=directory / f"observation-{recordings}")
            if not ok:
                return None
            assert len(answer) == 1, answer
            (directory / (r["id"].replace("/", "_") + ".json")).write_text(json.dumps(answer[0], indent=2) + "\n")
            assert answer[0]["letter"] == "A", answer[0]
            return answer[0]["memory"]
        answer = run(fixture, [r, synthetic(r)], ok)
        return answer[0] if ok else None

    east0 = row("east", "blue")
    west0 = row("west", "blue")
    old = record(east0)
    other = record(west0)
    assert (old["sequence"], other["sequence"]) == (1, 2)
    before = checkpoint(memory)
    assert record(east0) == old and checkpoint(memory) == before
    corrected = record(row("east", "red", 1))
    assert corrected["sequence"] == 3 and corrected["supersedes"] == 1
    assert run(replay + ["studio/east", "status"])[0] == corrected
    assert run(replay + ["studio/east", "status", "--as-of", "1"])[0] == old
    assert run(replay + ["studio/west", "status"])[0] == other
    print("PASS: distinct repositories, correction, historical and restarted exact receipts", flush=True)

    if not live:
        before = checkpoint(memory)
        bad = row("east", "blue", 3)
        bad["remember"]["commit"] = second
        record(bad, False)
        for field, value in [("commit", "HEAD"), ("commit", first[:12]), ("path", "../screen.ppm"), ("path", "/screen.ppm")]:
            bad = row("east", "blue", 3)
            bad["remember"][field] = value
            record(bad, False)
        record(row("east", "blue", 1), False)
        valid = row("east", "blue", 3)
        for field, value in [("id", "another-image"), ("input_sha256", "0" * 64), ("letter", "B"), ("p_a", 0.2)]:
            altered = {**synthetic(valid), field: value}
            run(fixture, [valid, altered], ok=False)
        assert checkpoint(memory) == before
        # Offline writes test journal retention independently of inference.
        for i in range(32):
            record(row("west", "blue", key=f"unrelated-{i}"))
        assert run(replay + ["studio/east", "status"])[0] == corrected
        assert run(replay + ["studio/east", "status", "--as-of", "1"])[0] == old
        same = row("west", "blue", key="concurrent")
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            receipts = list(pool.map(lambda _: record(same), range(12)))
        assert all(x == receipts[0] for x in receipts)
        print("PASS: Git byte binding, stale writers, 32 intervening observations, 12 concurrent retries", flush=True)

    before = checkpoint(memory)
    for tail in [["studio/absent", "status"], ["studio/east", "absent"], ["studio/east", "status", "--as-of", "0"],
                 ["studio/east", "status", "--as-of", "256"], ["studio/east", "status", "--as-of", "-1"]]:
        run(replay + tail, ok=False)
    assert checkpoint(memory) == before

    if live:
        queries = []
        expected = []
        memories = []
        for scope, through, color, receipt in [("east", None, "red", corrected), ("west", None, "blue", other), ("east", 1, "blue", old)]:
            for a, b in [("red", "blue"), ("blue", "red")]:
                recall = dict(repository=f"studio/{scope}", key="status")
                if through is not None:
                    recall["through"] = through
                queries.append(dict(id=f"recall-{len(queries)}", recall=recall,
                                    question="What color was recorded in the image observation?", choice_a=a, choice_b=b))
                expected.append("A" if a == color else "B")
                memories.append(receipt)
        blue.unlink()
        red.unlink()
        raw = run(infer + ["--recall-visual", memory], queries, capture=directory / "recall-first")
        again = run(infer + ["--recall-visual", memory], queries, capture=directory / "recall-restarted")
        assert len(raw) == len(again) == len(expected)
        assert (directory / "recall-first.stdout.jsonl").read_bytes() == (directory / "recall-restarted.stdout.jsonl").read_bytes()
        assert raw == again
        (directory / "recall.json").write_text(json.dumps(dict(queries=queries, expected=expected, answers=raw), indent=2) + "\n")
        for response, letter, receipt, query in zip(raw, expected, memories, queries):
            assert response["letter"] == letter and response["memory"] == receipt, response
            for field in ("id", "question", "choice_a", "choice_b"):
                assert response[field] == query[field], response
            assert response["input_sha256"] == digest((json.dumps(query, separators=(",", ":")) + "\n").encode())
        assert checkpoint(memory) == before
        print(json.dumps({"recall": len(raw), "letters": [a["letter"] for a in raw], "restart": "byte-identical JSON"}), flush=True)
    else:
        path = memory / "visual.checkpoint"
        data = bytearray(path.read_bytes())
        data[len(data) // 2] ^= 0x80
        path.write_bytes(data)
        run(replay + ["studio/east", "status"], ok=False)
        assert path.read_bytes() == data
    print("PASS: visual memory" + (" with actual OneJev recall" if live else " offline journal invariants"), flush=True)
    if cleanup:
        cleanup.cleanup()


if __name__ == "__main__":
    main()
