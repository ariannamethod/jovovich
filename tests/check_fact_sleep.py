"""Replay one corrected PR fact in two repositories through AML and native DOE."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "build/jovovich-pack"
REPLAY = ROOT / "build/jovovich-replay"
REPORT = ROOT / "build/jovovich-report"
SCOPES = ("fixture/east", "fixture/west")
COLORS = ("blue", "red")
NUMBER = 7
KEY = "signal"
OPENED = "2025-02-01T00:00:00Z"


def run(*argv, cwd=ROOT, data=None, env=None):
    result = subprocess.run(argv, cwd=cwd, input=data, env=env, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{argv[0]} exited {result.returncode}\n{result.stderr[-5000:]}")
    return result.stdout


def digest(path):
    with path.open("rb") as stream:
        h = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def commit(repo, message):
    run("git", "add", ".", cwd=repo)
    stamp = "2025-02-01T01:00:00Z"
    run("git", "-c", "commit.gpgSign=false", "commit", "-qm", message, cwd=repo,
        env={**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})
    return run("git", "rev-parse", "HEAD", cwd=repo).strip()


def configure(repo):
    run("git", "config", "user.name", "Fixture", cwd=repo)
    run("git", "config", "user.email", "fixture@localhost", cwd=repo)


def rule(color):
    return f"The signal must be {color}.\n"


def fact(memory, scope, sequence=None):
    cutoff = [] if sequence is None else ["--as-of", str(sequence)]
    return json.loads(run(PACK, "--fact", memory, scope, KEY, *cutoff))


def history(memory, scope):
    return json.loads(run(REPLAY, "history", memory, scope, str(NUMBER)))


def record(work, repo, scope, base, head, color, model=None, previous=0):
    memory = work / "memory"
    parent = ["--supersedes", str(previous)] if previous else []
    batch = work / "batch"
    batch.write_text(run(PACK, "--remember", memory, scope, KEY, *parent,
                         "--all", repo, base, head, "RULES"))
    answers = work / "answers"
    if model:
        answers.write_text(run(ROOT / "build/jovovich", model, model.with_name("tokenizer.gguf"),
                               "--json", data=batch.read_text()))
    else:
        answers.write_text(run(ROOT / "build/batch-fixture", "emit", batch, "clean"))
    meta = work / "pr.json"
    meta.write_text(json.dumps({"number": NUMBER, "url": f"https://github.com/{scope}/pull/{NUMBER}",
                                "createdAt": OPENED, "baseRefOid": base, "headRefOid": head}))
    policy = work / "routes.json"
    driver = work / "render"
    policy.write_text(json.dumps({"schema": "jovovich.snapshot-routes/1", "repository": scope,
                                  "paths": ["signal"], "harness_sha256": digest(driver)}))
    run(REPORT, batch, answers, "--memory", memory, "--auto-snapshots", repo, driver, policy,
        "--record-pr", scope, meta, "--json")
    receipt = fact(memory, scope)
    pr = history(memory, scope)
    assert pr["repository"] == scope and pr["number"] == NUMBER and pr["created_at"] == OPENED
    evidence = pr["observations"][-1]["evidence"]
    assert evidence["fact"] == receipt and evidence["head_commit"] == head
    assert receipt["repository"] == scope and receipt["supersedes"] == previous
    instant = datetime.fromisoformat(receipt["recorded_at"].replace("Z", "+00:00"))
    assert instant.utcoffset().total_seconds() == 0
    assert receipt["origin"] == {"rules_path": "RULES", "rule_first_line": 1, "rule_last_line": 1,
                                 "base_commit": base, "head_commit": head, "rule_excerpt": rule(color)}
    assert any(f["status"] == "met" and f["file"] == "signal" for f in evidence["findings"])
    return receipt


def observation(memory, repo, scope, head, number=NUMBER):
    view = json.loads(run(REPLAY, "history", memory, scope, str(number), "--snapshot", repo, head,
                          "signal", "--compare-known-at", "2000-01-01T00:00:00Z", "2099-01-01T00:00:00Z"))
    stream, = view["streams"]
    evidence, = stream["new_checks"]
    return evidence["id"]


def spore_receipt(memory, scope, obs, path, record=False):
    mode = ["--record"] if record else []
    binding = json.loads(run(REPLAY, "spore", memory, scope, str(NUMBER), obs, path, *mode))
    assert binding == {"schema": "jovovich.pr-spore/1", "repository": scope, "number": NUMBER,
                       "observation_id": obs, "spore_sha256": digest(path)}
    return path, obs


def refused(memory, scope, obs, path, *flags, number=NUMBER):
    result = subprocess.run([REPLAY, "spore", memory, scope, str(number), obs, path, *flags],
                            cwd=ROOT, capture_output=True)
    assert result.returncode and not result.stdout, "foreign spore produced a receipt"


def question(scope, colors, quoted=""):
    state = f"Repository {scope}, PR #{NUMBER}."
    if quoted:
        state += f"\nVerified rule: {quoted.strip()}"
    return ("<|im_start|>system\nApply the question to the state. Choose exactly one of the listed options. "
            "Respond with only its uppercase letter, with no explanation or reasoning.<|im_end|>\n"
            f"<|im_start|>user\n<state>\n{state}\n</state>\n\nQuestion: Which color does the rule require?\n\n"
            f"Options:\nA. {colors[0]}\nB. {colors[1]}\n\nAnswer with one letter: A, B.<|im_end|>\n"
            "<|im_start|>assistant\n<think>\n\n</think>\n\n")


@lru_cache(maxsize=32)
def native_ids(tokenizer_tool, tokenizer, prompt):
    rows = [("question", prompt), ("start", "<|im_start|>"), ("end", "<|im_end|>")]
    encoded = run(tokenizer_tool, tokenizer, data="".join(json.dumps({"id": key, "prompt": text}) + "\n"
                                                          for key, text in rows))
    tokens = {}
    for line in encoded.splitlines():
        key, sequence = line.split("\t")
        tokens[key] = list(map(int, sequence.split()))
    start, = tokens["start"]
    end, = tokens["end"]
    ids = tokens["question"]
    assert ids.count(start) == 3 and ids.count(end) == 2 and 0 < len(ids) < 256
    return ids


# Only integer IDs enter the program. The teacher reads receipt text as data.
PROBE = """
ids_a = doe_encode('A')
ids_b = doe_encode('B')
assert(len(ids_a) == 1 and ids_a[0] == 32 and len(ids_b) == 1 and ids_b[0] == 33, 'OneJev A/B rows')
logits = doe_prompt(question_ids)
assert(len(logits) == 248320, 'full OneJev output head')
state = record_new()
record_set(state, 'logits', logits)
assert(checkpoint_save(state, 'logits.bin') == 1, 'durable logits')
PRINT logits[ids_a[0]]
PRINT logits[ids_b[0]]
doe_close()
"""
LEARN = """
cue = file_read_slice('cue.txt', 0, 8192)
doe_prompt(doe_encode(cue))
doe_choose(-1)
doe_finish('async')
doe_save('awake.gguf')
doe_reset()
"""


class Parliament:
    """Keep an independent chain of immutable generations per logical PR."""
    def __init__(self, directory, scope, model, aml, notorch):
        self.directory = directory / scope / str(NUMBER)
        self.directory.mkdir(parents=True)
        self.memory = directory / "memory"
        self.scope = scope
        self.model = model
        self.aml = aml
        self.notorch = notorch
        self.saved = None

    def probe(self, path, spore, colors, quoted="", learning=None):
        path.mkdir()
        (path / "host.gguf").symlink_to(self.model)
        (path / "tokenizer.gguf").symlink_to(self.model.with_name("tokenizer.gguf"))
        spore_name = ""
        if spore is not None:
            source, obs = spore
            spore_name = "prior.gguf"
            private = path / spore_name
            shutil.copyfile(source, private)
            spore_receipt(self.memory, self.scope, obs, private)
        prompt = question(self.scope, colors, quoted)
        ids = native_ids(self.notorch.with_name("qwen35_tokenize"), self.model.with_name("tokenizer.gguf"), prompt)
        if learning:
            origin = learning["origin"]
            assert learning["repository"] == self.scope
            cue = (f"Repository {self.scope}, PR #{NUMBER}. Verified rule at {origin['head_commit']}: "
                   + origin["rule_excerpt"])
            (path / "cue.txt").write_text(cue)
        program = (f"doe_open('host.gguf', '{spore_name}', 256)\nquestion_ids = zeros({len(ids)})\n"
                   + "".join(f"question_ids[{i}] = {token}\n" for i, token in enumerate(ids))
                   + (LEARN if learning else "") + PROBE)
        (path / "run.aml").write_text(program)
        output = run(self.aml, path / "run.aml", cwd=path)
        a, b = map(float, output.split())
        return {"answer": colors[0] if a > b else colors[1] if b > a else "tie",
                "a": a, "b": b, "logits": digest(path / "logits.bin"),
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "tokens": len(ids)}

    def rehearse(self, receipt, obs):
        print(f"Rehearsing {self.scope} PR {NUMBER}, rule receipt {receipt['sequence']}", file=sys.stderr, flush=True)
        gen = self.directory / str(receipt["sequence"])
        gen.mkdir()
        # First probe has fresh KV immediately after async consolidation.
        awake = self.probe(gen / "learn", self.saved, COLORS, learning=receipt)
        spore = gen / "awake.gguf"
        (gen / "learn/awake.gguf").rename(spore)
        wake = spore_receipt(self.memory, self.scope, obs, spore, record=True)
        reopened = self.probe(gen / "restart", wake, COLORS)
        assert reopened == awake
        assert (gen / "learn/logits.bin").read_bytes() == (gen / "restart/logits.bin").read_bytes()
        swapped = self.probe(gen / "awake-ba", wake, COLORS[::-1])
        asleep = gen / "dream.gguf"
        result = subprocess.run([self.notorch, "-q", "--experts", "--learn-experts",
                                 "--async-consolidation", "--expert-trace", "--dream-only", "2",
                                 "--spore-in", spore, "--spore-out", asleep, self.model],
                                cwd=gen, capture_output=True, text=True)
        dream_tokens = sum("doe dream-choice step=" in line for line in result.stderr.splitlines())
        if result.returncode or not 1 <= dream_tokens <= 2 or "doe dream-choice step=0" not in result.stderr:
            raise RuntimeError("private dream failed\n" + result.stderr[-5000:])
        assert digest(spore) != digest(asleep), "private dream did not publish new state"
        self.saved = spore_receipt(self.memory, self.scope, obs, asleep, record=True)
        answers = self.choices(gen, "post-sleep", self.saved)
        repeat = self.probe(gen / "repeat", self.saved, COLORS)
        assert repeat == answers[0]
        assert (gen / "repeat/logits.bin").read_bytes() == (gen / "post-sleep-ab/logits.bin").read_bytes()
        return {"pr": NUMBER, "observation_id": obs, "rule_receipt": receipt, "awake": [awake, swapped],
                "awake_spore": digest(spore), "dream_spore": digest(asleep), "dream_tokens": dream_tokens,
                "post_sleep": answers}

    def choices(self, gen, label, spore, quoted=""):
        return [self.probe(gen / (label + suffix), spore, order, quoted)
                for suffix, order in [("-ab", COLORS), ("-ba", COLORS[::-1])]]


def experiment(work, model, aml, notorch):
    memory = work / "memory"
    memory.mkdir()
    east, west = work / "east", work / "west"
    run("git", "init", "-q", "-b", "main", "--object-format=sha1", east)
    configure(east)
    (east / "RULES").write_text(rule("blue"))
    (east / "signal").write_text("off\n")
    base = commit(east, "blue rule")
    (east / "signal").write_text("blue\n")
    head = commit(east, "blue signal")
    run("git", "clone", "-q", "--no-local", east, west)
    driver = work / "render"
    driver.write_text("#!/bin/sh\nset -eu\ntest \"$1\" = render\ntest \"$4\" = signal\n"
                      "git -C \"$2\" show \"$3:RULES\" | sed -n 's/^The signal must be \\([a-z]*\\)\\.$/\\1/p'\n")
    driver.chmod(0o700)
    old = [record(work, repo, scope, base, head, "blue", model)
           for repo, scope in zip((east, west), SCOPES)]
    def journals():
        return {p: p.read_bytes() for p in [memory / "rules.checkpoint", *memory.glob("pr-*.checkpoint")]}

    def comparison(repo, scope, sha, first=None):
        cursor = ["--from-journal", first] if first else []
        return run(REPLAY, "history", memory, scope, str(NUMBER), "--snapshot", repo, sha,
                   "signal", "--compare-known-at", "2099-01-01T00:00:00Z", "2099-01-01T00:00:00Z", *cursor)

    old_journal = json.loads(comparison(east, SCOPES[0], head))["journal_head"]
    prior_west = history(memory, SCOPES[1])
    east_history = history(memory, SCOPES[0])
    sessions, results = [], {}
    ids = [observation(memory, repo, scope, head) for repo, scope in zip((east, west), SCOPES)]
    fingerprint = work / "sample"
    fingerprint.write_bytes(b"first fingerprint")
    spore_receipt(memory, SCOPES[0], ids[0], fingerprint, record=True)
    receipt_file, = memory.glob("spores-*.checkpoint")
    stored = receipt_file.read_bytes()
    spore_receipt(memory, SCOPES[0], ids[0], fingerprint, record=True)
    refused(memory, SCOPES[1], ids[0], fingerprint, "--record")
    refused(memory, SCOPES[1], ids[1], fingerprint)
    fingerprint.write_bytes(b"replacement at the same path")
    refused(memory, SCOPES[0], ids[0], fingerprint)
    assert receipt_file.read_bytes() == stored
    # Two PRs can contain the very same observation in the same repository.
    # The source batch, renderer, rule and SHA are identical for these reports.
    metadata = json.loads((work / "pr.json").read_text())
    metadata.update(number=8, url=f"https://github.com/{SCOPES[1]}/pull/8")
    (work / "pr.json").write_text(json.dumps(metadata))
    run(REPORT, work / "batch", work / "answers", "--memory", memory, "--auto-snapshots", west,
        driver, work / "routes.json", "--record-pr", SCOPES[1], work / "pr.json", "--json")
    assert observation(memory, west, SCOPES[1], head, number=8) == ids[1]
    spore_receipt(memory, SCOPES[1], ids[1], fingerprint, record=True)
    refused(memory, SCOPES[1], ids[1], fingerprint, number=8)
    other, = set(memory.glob("spores-*.checkpoint")) - {receipt_file}
    good = other.read_bytes()
    other.write_bytes(receipt_file.read_bytes())
    refused(memory, SCOPES[1], ids[1], fingerprint, "--record")
    assert other.read_bytes() == receipt_file.read_bytes()
    other.write_bytes(good)
    concurrent = [work / "generation-one", work / "generation-two"]
    for path in concurrent:
        path.write_bytes(path.name.encode("ascii"))
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda path: spore_receipt(memory, SCOPES[0], ids[0], path, record=True), concurrent))
    for path in concurrent:
        spore_receipt(memory, SCOPES[0], ids[0], path)
    old_bytes = journals()
    if model:
        for scope, receipt, obs in zip(SCOPES, old, ids):
            p = Parliament(work, scope, model, aml, notorch)
            sessions.append(p)
            results[scope] = {"fresh": p.choices(p.directory, "fresh", None),
                              "first": p.rehearse(receipt, obs)}
    assert journals() == old_bytes, "first sleep changed an authoritative journal"
    (east / "RULES").write_text(rule("red"))
    new_base = commit(east, "correct the rule to red")
    (east / "signal").write_text("red\n")
    new_head = commit(east, "red signal")
    new = record(work, east, SCOPES[0], new_base, new_head, "red", model, old[0]["sequence"])
    assert history(memory, SCOPES[0])["observations"][:-1] == east_history["observations"]
    assert history(memory, SCOPES[1]) == prior_west

    def recall():
        return (run(PACK, "--fact", memory, SCOPES[0], KEY),
                run(PACK, "--fact", memory, SCOPES[0], KEY, "--as-of", str(old[0]["sequence"])),
                run(PACK, "--fact", memory, SCOPES[1], KEY),
                comparison(east, SCOPES[0], new_head, old_journal),
                comparison(west, SCOPES[1], head))

    before = recall()
    assert tuple(map(json.loads, before[:3])) == (new, old[0], old[1])
    view = json.loads(before[3])
    stream, = view["streams"]
    assert (view["repository"], view["number"], view["head_commit"]) == (SCOPES[0], NUMBER, new_head)
    checked, = stream["new_checks"]
    assert stream["before"]["status"] == "unverified" and stream["after"]["status"] == "met"
    assert checked["id"] in stream["after"]["receipt_ids"]
    assert checked["checked_at"] == history(memory, SCOPES[0])["observations"][-1]["checked_at"]
    checkpoints = journals()
    if model:
        left, right = sessions
        results[SCOPES[0]]["corrected"] = left.rehearse(new, checked["id"])
        second_west = right.choices(right.directory, "after-east", right.saved)
        assert second_west == results[SCOPES[1]]["first"]["post_sleep"]
        refused(memory, right.scope, right.saved[1], left.saved[0])
        refused(memory, right.scope, left.saved[1], left.saved[0])
        for p, receipt in [(left, new), (right, old[1])]:
            quote = receipt["origin"]["rule_excerpt"]
            results[p.scope]["with_source"] = p.choices(p.directory, "source", p.saved, quote)
            results[p.scope]["source_only"] = p.choices(p.directory, "source-only", None, quote)
        scores = {}
        for scope, expected in zip(SCOPES, ("red", "blue")):
            stages = results[scope]
            final = stages.get("corrected", stages["first"])
            scores[scope] = {label: [probe["answer"] for probe in choices]
                             for label, choices in [("fresh", stages["fresh"]),
                                                    ("before_sleep", final["awake"]),
                                                    ("after_sleep", final["post_sleep"]),
                                                    ("with_source", stages["with_source"]),
                                                    ("source_only", stages["source_only"])]}
            scores[scope]["expected"] = expected
            scores[scope]["both_orders_after_sleep"] = scores[scope]["after_sleep"] == [expected, expected]
        print(json.dumps({"probes": results, "scores": scores}, sort_keys=True, indent=2), flush=True)
    assert recall() == before
    assert journals() == checkpoints
    print("PR 7 in two repositories: correction, prior receipt, source SHA, UTC and journal bytes passed.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, help="released OneJev GGUF with tokenizer.gguf beside it")
    parser.add_argument("--aml", type=Path, default=ROOT / "deps/aml/runner/aml-harness")
    parser.add_argument("--notorch", type=Path, default=ROOT / "deps/notorch/notorch")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="jov-fact-sleep-") as tmp:
        work = Path(tmp).resolve()
        model = None
        if args.model:
            manifest = json.loads((ROOT / "models/onejev-0.8b.json").read_text())
            model = work / "model.gguf"
            for source, dest, field in [(args.model, model, "weights_sha256"),
                                         (args.model.with_name("tokenizer.gguf"), work / "tokenizer.gguf", "tokenizer_sha256")]:
                shutil.copyfile(source, dest)
                if digest(dest) != manifest[field]:
                    raise ValueError(f"{field} differs from the released OneJev")
                dest.chmod(0o400)
        experiment(work, model, args.aml.resolve(), args.notorch.resolve())


if __name__ == "__main__":
    main()
