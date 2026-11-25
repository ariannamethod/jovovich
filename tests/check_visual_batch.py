#!/usr/bin/env python3
"""Report protocol gates with explicitly synthetic scores; no model inference.

Predeclared: any visual or text CONCERN makes the whole report CONCERN.
Missing, reordered, duplicate, foreign and altered receipts publish no bytes.
Every changed binary path needs one comparison; visual-only changes work too.
"""
import argparse
import copy
import json
import subprocess
import tempfile
from pathlib import Path

from check_visual_memory import ROOT, ENV, digest, git, synthetic, checkpoint


def encode(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def command(args, data=None, ok=True):
    p = subprocess.run([str(x) for x in args], input=data, capture_output=True, cwd=ROOT, env=ENV)
    if ok:
        assert p.returncode == 0, (args, p.stderr.decode())
    else:
        assert p.returncode != 0 and not p.stdout, (args, p.returncode, p.stdout, p.stderr)
    return p.stdout


def fake_visual(request, memory, concern):
    raw = command([ROOT / "build/jovovich-replay", "compare-visual", memory], encode(request).encode()).rstrip(b"\n")
    comparison = json.loads(raw)
    question = "Does the after image satisfy the repository requirement?"
    a = "CONCERN: The after image violates the repository requirement."
    b = "CLEAN: The after image satisfies the repository requirement."
    reverse = request.get("concern_letter") == "B"
    if reverse:
        a, b = b, a
    prompt = ("<|im_start|>system\nApply the question to the state. Choose exactly one of the listed options. "
              "Respond with only its uppercase letter, with no explanation or reasoning.<|im_end|>\n"
              "<|im_start|>user\n<state>\n" + comparison["state"] + "\n</state>\n\nQuestion: " + question +
              "\n\nOptions:\nA. " + a + "\nB. " + b + "\n\nAnswer with one letter: A, B."
              "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n")
    is_a = concern != reverse
    manifest = json.loads((ROOT / "models/onejev-0.8b.json").read_text())
    answer = dict(schema="jovovich.visual-review/1", id=request["id"], question=question,
                  choice_a=a, choice_b=b, input_sha256=digest(encode(request).encode()),
                  prompt_sha256=digest(prompt.encode()), weights_sha256=manifest["weights_sha256"],
                  tokenizer_sha256=manifest["tokenizer_sha256"], verdict="CONCERN" if concern else "CLEAN",
                  concern=0.731058598 if concern else 0.268941432,
                  clean=0.268941432 if concern else 0.731058598,
                  logit_a=2 if is_a else 1, logit_b=1 if is_a else 2,
                  p_a=0.731058598 if is_a else 0.268941432, p_b=0.268941432 if is_a else 0.731058598,
                  letter="A" if is_a else "B")
    return encode(answer)[:-1].encode() + b',"comparison":' + raw + b'}\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", default=str(ROOT / "build/jovovich-pack"))
    parser.add_argument("--report", default=str(ROOT / "build/jovovich-report"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="jov-visual-batch-") as temporary:
        work = Path(temporary)
        repo, memory, facts = (work / name for name in ("repo", "memory", "facts"))
        for directory in (repo, memory, facts):
            directory.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "Visual batch fixture")
        git(repo, "config", "user.email", "fixture@example.invalid")
        (repo / "RULES.md").write_text("Buttons must say Save. Functions named square return x * x.\n")
        (repo / "math.c").write_text("int square(int x) { return x * x; }\n")
        paths = ["a-screen.ppm", "z-screen.ppm"]
        commits, receipts = [], []
        parents = [0, 0]
        for version in range(3):
            if version == 1:
                (repo / "math.c").write_text("int square(int x) { const int result = x * x; return result; }\n")
            for i, path in enumerate(paths):
                pixels = b"P6\n1 1\n255\n" + bytes((0, version * 50, i * 40))
                (repo / path).write_bytes(pixels)
            git(repo, "add", ".")
            git(repo, "commit", "-qm", f"state {version}")
            commit = git(repo, "rev-parse", "HEAD")
            commits.append(commit)
            for i, path in enumerate(paths):
                row = dict(id=f"image-{version}-{i}", question="Which button is visible?", choice_a="Save", choice_b="Delete",
                           image=dict(path=str(repo / path), sha256=digest((repo / path).read_bytes())),
                           remember=dict(repository="studio/east", key=path, pull_request=7, checkout=str(repo),
                                         commit=commit, path=path, supersedes=parents[i]))
                receipt = json.loads(command([ROOT / "build/visual-memory-fixture", memory],
                                            (encode(row) + "\n" + encode(synthetic(row)) + "\n").encode()))
                receipts.append(receipt)
                parents[i] = receipt["sequence"]
        journal = checkpoint(memory)
        requests = [dict(id=f"visual-{i}", concern_letter="A" if i == 0 else "B",
                         compare=dict(repository="studio/east", key=path, checkout=str(repo), before=i+1, after=i+3,
                                      rules=dict(path="RULES.md", first=1, last=1))) for i, path in enumerate(paths)]
        request_file, batch, answers = (work / name for name in ("requests.jsonl", "batch.jsonl", "answers.jsonl"))

        def pack(req=requests, base=commits[0], head=commits[1], scope="studio/east", pr=7, ok=True, remember=False):
            request_file.write_text("".join(encode(r) + "\n" for r in req))
            prefix = ["--remember", facts, scope, "requirements"] if remember else []
            return command([args.pack, *prefix, "--with-visual", memory, scope, pr, request_file,
                            "--all", repo, base, head, "RULES.md"], ok=ok)

        packed = pack(remember=True)
        rows = [json.loads(x) for x in packed.splitlines()]
        assert [r["file"] for r in rows] == [paths[0], "math.c", paths[1]]
        assert all(r["batch"]["schema"] == "jovovich.git-batch/2" for r in rows)
        text_input = work / "text.jsonl"
        text_input.write_bytes(packed.splitlines(keepends=True)[1])
        text_clean = command([ROOT / "build/batch-fixture", "emit", text_input, "clean"])
        t = json.loads(text_clean)
        t["choice"].update(verdict="CONCERN", probabilities={"CONCERN":0.9, "CLEAN":0.1})
        text_concern = (encode(t) + "\n").encode()
        clean_visual = [fake_visual(r["visual_request"], memory, False) for r in rows if "visual_request" in r]
        concern_visual = [fake_visual(r["visual_request"], memory, True) for r in rows if "visual_request" in r]

        def report(data, votes, ok=True, scope="studio/east", pr=7, json_mode=True, extra=()):
            batch.write_bytes(data)
            answers.write_bytes(votes)
            return command([args.report, batch, answers, "--with-visual", memory, scope, pr,
                            *(["--json"] if json_mode else []), *extra], ok=ok)

        cases = [(clean_visual[0]+text_clean+clean_visual[1], 0, 0),
                 (concern_visual[0]+text_clean+clean_visual[1], 1, 1),
                 (clean_visual[0]+text_clean+concern_visual[1], 1, 1),
                 (clean_visual[0]+text_concern+clean_visual[1], 1, 0),
                 (concern_visual[0]+text_concern+concern_visual[1], 3, 2)]
        for votes, concerns, visuals in cases:
            result = json.loads(report(packed, votes))
            assert result["schema"] == "jovovich.review-report/2"
            assert result["summary"] == dict(verdict="CONCERN" if concerns else "CLEAN", reviewed_files=3,
                                              concern_files=concerns, clean_files=3-concerns)
            assert result["visual_summary"]["concern_files"] == visuals
            assert result["fact"] == rows[0]["fact"]
            assert len(result["reviews"]) == 3
        good = cases[1][0]
        traced = copy.deepcopy(rows)
        source = traced[1]["source"]
        traced[1]["trace_evidence"] = dict(schema="jovovich.paired-traces/1", review_id=traced[1]["id"],
            base_commit=source["base_commit"], head_commit=source["head_commit"],
            rule_sha256=source["rules_sha256"], change_sha256=source["diff_sha256"], metric="text",
            runs=[dict(mode=0, base="old", head="x * x", required="x * x")])
        text_input.write_text(encode(traced[1])+"\n")
        traced_vote = command([ROOT / "build/batch-fixture", "emit", text_input, "clean"])
        trace_report = json.loads(report(("".join(encode(r)+"\n" for r in traced)).encode(),
                                         concern_visual[0]+traced_vote+clean_visual[1]))
        assert trace_report["summary"]["verdict"] == "CONCERN"
        assert trace_report["execution_summary"] == dict(selected_runs=1, met=1, failed=0)
        # A semantic tie is CONCERN even when its letter is B.
        tied = []
        for raw in clean_visual:
            parsed = json.loads(raw)
            letter = "A" if parsed["choice_a"].startswith("CONCERN:") else "B"
            parsed.update(verdict="CONCERN", concern=0.5, clean=0.5, p_a=0.5, p_b=0.5, logit_a=0, logit_b=0, letter=letter)
            tied.append((encode(parsed)+"\n").encode())
        assert json.loads(report(packed, tied[0]+text_clean+tied[1]))["visual_summary"]["concern_files"] == 2
        false_tie = json.loads(tied[0])
        false_tie.update(p_a=0.499999999, p_b=0.500000001, concern=0.499999999, clean=0.500000001,
                         verdict="CLEAN", letter="B")
        report(packed, (encode(false_tie)+"\n").encode()+text_clean+tied[1], ok=False)
        markdown = report(packed, good, json_mode=False).decode()
        assert "Visual files: 2" in markdown and "### Visual review: a\\-screen\\.ppm" in markdown, markdown
        assert "memory #1" in markdown and commits[0] in markdown and commits[1] in markdown
        report(packed, good, scope="studio/west", ok=False)
        report(packed, good, pr=8, ok=False)
        report(packed, good, extra=["--locate", repo, "/unused"], ok=False)
        chunks = good.splitlines(keepends=True)
        for votes in [b"", b"".join(chunks[:-1]), good+chunks[0], chunks[0]+chunks[1]+chunks[0],
                      chunks[2]+chunks[1]+chunks[0], chunks[1]+chunks[0]+chunks[2], b'{}\n'+b"".join(chunks[1:])]:
            report(packed, votes, ok=False)
        for key, value in [("schema", "jovovich.visual-recall/1"), ("id", "foreign"), ("weights_sha256", "0"*64),
                           ("tokenizer_sha256", "0"*64), ("prompt_sha256", "0"*64), ("input_sha256", "0"*64),
                           ("verdict", "CLEAN"), ("choice_a", "changed"), ("question", "different"),
                           ("letter", "B"), ("p_a", 0.5), ("logit_a", 100), ("concern", -1)]:
            original = json.loads(chunks[0]);original[key] = value
            report(packed, (encode(original)+"\n").encode()+b"".join(chunks[1:]), ok=False)
        for where, field, value in [("before", "sequence", 2), ("after", "sequence", 1)]:
            original = json.loads(chunks[0]);original["comparison"][where][field] = value
            report(packed, (encode(original)+"\n").encode()+b"".join(chunks[1:]), ok=False)
        for mutate in [lambda r: r[0]["batch"].update(count=2), lambda r: r[0]["batch"].update(index=1),
                       lambda r: r[0]["batch"].update(id="0"*64), lambda r: r[0].update(file=paths[1]),
                       lambda r: r[0]["visual_request"]["compare"].update(after=5),
                       lambda r: r[0]["source"].update(head_commit=commits[2]),
                       lambda r: r[0]["visual_request"].update(concern_letter="B"),
                       lambda r: r[0]["batch"].update(schema="jovovich.git-batch/1"),
                       lambda r: r[0].pop("visual_request")]:
            altered = copy.deepcopy(rows);mutate(altered)
            report(("".join(encode(r)+"\n" for r in altered)).encode(), good, ok=False)
        pack(req=[], ok=False)
        pack(req=requests[:1], ok=False)
        pack(req=requests+[requests[0]], ok=False)
        pack(scope="studio/west", ok=False)
        pack(pr=8, ok=False)
        pack(base=commits[1], head=commits[2], ok=False)
        plain = pack()
        request_file.write_text("".join(" \t"+encode(r)+" \n" for r in requests))
        spaced = command([args.pack, "--with-visual", memory, "studio/east", 7, request_file,
                          "--all", repo, commits[0], commits[1], "RULES.md"])
        assert spaced == plain
        # Wrong current rule has no effect; source is the committed base.
        (repo / "RULES.md").write_text("UNCOMMITTED DIFFERENT RULE\n")
        assert json.loads(report(packed, good))["summary"]["verdict"] == "CONCERN"
        # A PR changing only images has no empty text-batch escape hatch.
        only = copy.deepcopy(requests)
        for r in only:
            r["compare"]["before"] += 2;r["compare"]["after"] += 2
        visual_only = pack(req=only, base=commits[1], head=commits[2])
        only_rows = [json.loads(x) for x in visual_only.splitlines()]
        only_votes = b"".join(fake_visual(r["visual_request"], memory, False) for r in only_rows)
        assert json.loads(report(visual_only, only_votes))["summary"] == dict(verdict="CLEAN", reviewed_files=2, concern_files=0, clean_files=2)
        recalled = command([args.pack, "--recall", facts, "studio/east", "requirements", "--with-visual",
                            memory, "studio/east", 7, request_file, "--all", repo, commits[1], commits[2]])
        assert json.loads(report(recalled, only_votes))["fact"] == rows[0]["fact"]
        assert "Remembered rule:" in report(recalled, only_votes, json_mode=False).decode()
        # No v2 interpretation through the legacy report entry point.
        batch.write_bytes(packed);answers.write_bytes(good)
        command([args.report, batch, answers, "--json"], ok=False)
        assert checkpoint(memory) == journal
        print("PASS: mixed/text/visual-only aggregation, both option orders, complete coverage, rule memory, foreign/tampered/missing/duplicate/reordered refusals; journal unchanged")


if __name__ == "__main__":
    main()
