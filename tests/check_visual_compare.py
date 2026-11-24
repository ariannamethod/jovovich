#!/usr/bin/env python3
"""Fixed Git/render/observation/rule gates, with optional native OneJev review.

Before execution: button labels Delete -> Save -> Delete -> Delete. The last
edit changes only the footer. East requires Save, west requires Delete. The
three east verdicts must be CLEAN/CONCERN/CONCERN; west must give the inverse.
Both concern-letter orders and a fresh process must preserve those verdicts.
"""
import argparse
import copy
import io
import json
import subprocess
import tempfile
from pathlib import Path

from check_visual_memory import ROOT, ENV, digest, git, synthetic, checkpoint


def execute(command, rows, capture=None, ok=True):
    data = b"".join((json.dumps(r, separators=(",", ":")) + "\n").encode() for r in rows)
    p = subprocess.run([str(x) for x in command], input=data, capture_output=True, cwd=ROOT, env=ENV)
    if capture:
        capture.with_suffix(".input.jsonl").write_bytes(data)
        capture.with_suffix(".stdout.jsonl").write_bytes(p.stdout)
        capture.with_suffix(".stderr").write_bytes(p.stderr)
    if not ok:
        assert p.returncode != 0 and not p.stdout, (p.returncode, p.stdout, p.stderr)
        return []
    assert p.returncode == 0, (command, p.returncode, p.stderr)
    return [json.loads(x) for x in p.stdout.splitlines()]


def panel(label, cosmetic=False):
    return '''<!doctype html><meta charset="utf-8"><style>
body{font-family:Arial,sans-serif;color:#192334;margin:24px}
h1{font-size:24px;margin:0 0 12px}p{font-size:14px;margin:0 0 24px}
table{width:100%;border-spacing:12px}td{padding:14px;text-align:center}
.button{font-size:24px;background-color:#155de9;color:white}
.cancel{font-size:16px;background-color:#eef1f5;color:#556}</style>
<h1>Settings</h1><p>Export configuration</p><table><tr><td class="button">''' + label + '''</td>
<td class="cancel">Cancel</td></tr></table><p style="color:#999">''' + (
        "Configuration" if cosmetic else "Preferences") + "</p>"


def render(html):
    # Optional live gate: execute HTML/CSS through MuPDF, then rasterize its
    # 384x256 page. This is a static panel; no browser or network is involved.
    import fitz
    buffer = io.BytesIO()
    writer = fitz.DocumentWriter(buffer)
    box = fitz.Rect(0, 0, 384, 256)
    device = writer.begin_page(box)
    story = fitz.Story(html=html)
    more, _ = story.place(box)
    assert not more, "panel overflow"
    story.draw(device)
    writer.end_page()
    writer.close()
    pdf = fitz.open(stream=buffer.getvalue(), filetype="pdf")
    return pdf[0].get_pixmap(alpha=False).tobytes("png")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model")
    parser.add_argument("--tokenizer")
    parser.add_argument("--vision")
    parser.add_argument("--work")
    parser.add_argument("--replay", default=str(ROOT / "build/jovovich-replay"))
    args = parser.parse_args()
    live = bool(args.model)
    assert not live or (args.tokenizer and args.vision)
    temporary = None if args.work else tempfile.TemporaryDirectory(prefix="jov-visual-compare-")
    directory = Path(args.work).resolve() if args.work else Path(temporary.name)
    if args.work:
        directory.mkdir(parents=True, exist_ok=False)
    memory = directory / "memory"
    memory.mkdir()
    fixture = [ROOT / "build/visual-memory-fixture", memory]
    preview = [Path(args.replay).resolve(), "compare-visual", memory]
    rows, comparisons, expected, sources = [], [], [], []
    image_path = "screen.png" if live else "screen.ppm"
    for scope, required in [("east", "Save"), ("west", "Delete")]:
        repo = directory / scope
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "Visual comparison test")
        git(repo, "config", "user.email", "test@example.invalid")
        rule = f"The blue button must be labelled {required}.\n"
        (repo / "RULES.md").write_text("Visual contract\n" + rule)
        (repo / "RULES.link").symlink_to("RULES.md")
        parent = 0
        sequence = []
        commits = []
        for index, label in enumerate(["Delete", "Save", "Delete", "Delete"]):
            html = panel(label, index == 3)
            (repo / "panel.html").write_text(html)
            # Offline fixtures exercise provenance only; they explicitly supply
            # synthetic answers. Live mode renders and uses native vision.
            pixels = render(html) if live else b"P6\n1 1\n255\n" + (b"\x00\x00\xff" if label == "Save" else b"\xff\x00\x00")
            (repo / image_path).write_bytes(pixels)
            git(repo, "add", ".")
            git(repo, "commit", "-qm", f"panel revision {index}")
            commit = git(repo, "rev-parse", "HEAD")
            commits.append(commit)
            if live:
                archived = git(repo, "show", f"{commit}:panel.html")
                assert render(archived) == pixels
            captured = directory / f"{scope}-{index}.image"
            captured.write_bytes(pixels)
            a, b = ("Save", "Delete") if scope == "east" else ("Delete", "Save")
            row = dict(id=f"{scope}-{index}", image=dict(path=str(captured), sha256=digest(pixels)),
                       question="What is the label of the blue button?", choice_a=a, choice_b=b,
                       remember=dict(repository=f"studio/{scope}", key="primary-button", checkout=str(repo),
                                     commit=commit, path=image_path, pull_request=7, supersedes=parent))
            rows.append(row)
            parent = len(rows)
            sequence.append(parent)
        sources.append(dict(scope=scope, repo=repo, rule=rule, commits=commits, sequence=sequence))
        for index in range(3):
            for letter in ["A", "B"]:
                comparisons.append(dict(id=f"{scope}-change-{index}-{letter}", concern_letter=letter,
                    compare=dict(repository=f"studio/{scope}", key="primary-button", checkout=str(repo),
                                 before=sequence[index], after=sequence[index+1],
                                 rules=dict(path="RULES.md", first=2, last=2))))
                expected.append((["CLEAN", "CONCERN", "CONCERN"] if scope == "east" else
                                 ["CONCERN", "CLEAN", "CLEAN"])[index])
    (directory / "expected.json").write_text(json.dumps(dict(labels=["Delete", "Save", "Delete", "Delete"] * 2,
                                                            verdicts=expected, inputs=comparisons), indent=2) + "\n")
    receipts = []
    if live:
        native = [ROOT / "build/jovovich", Path(args.model).resolve(), Path(args.tokenizer).resolve()]
        answers = execute(native + ["--vision", Path(args.vision).resolve(), "--visual-memory", memory], rows,
                          directory / "observations")
        assert len(answers) == len(rows)
        for i, (answer, row) in enumerate(zip(answers, rows)):
            label = ["Delete", "Save", "Delete", "Delete"][i % 4]
            assert answer["letter"] == ("A" if row["choice_a"] == label else "B"), answer
            receipts.append(answer["memory"])
        for row in rows:
            Path(row["image"]["path"]).unlink()
        print("PASS: eight live image observations, both repositories and option orders", flush=True)
    else:
        for i, row in enumerate(rows):
            obs = synthetic(row)
            if row["choice_a"] != ["Delete", "Save", "Delete", "Delete"][i % 4]:
                obs.update(letter="B", logit_a=1, logit_b=2, p_a=0.2689414, p_b=0.7310586)
            receipts.append(execute(fixture, [row, obs])[0])

    before = checkpoint(memory)
    packed = execute(preview, comparisons, directory / "comparison-preview")
    assert len(packed) == len(comparisons)
    for receipt, request in zip(packed, comparisons):
        c = request["compare"]
        assert receipt["before"] == receipts[c["before"]-1]
        assert receipt["after"] == receipts[c["after"]-1]
        source = sources[0 if c["repository"] == "studio/east" else 1]
        assert receipt["rule"]["commit"] == receipt["before"]["origin"]["source"]["commit"]
        assert receipt["rule"]["quote"] == source["rule"]
        assert receipt["rule"]["sha256"] == digest(source["rule"].encode())
        assert receipt["input_sha256"] == digest((json.dumps(request, separators=(",", ":")) + "\n").encode())
    # Mutable worktree text must not select the rule for a committed image.
    (sources[0]["repo"] / "RULES.md").write_text("UNCOMMITTED DIFFERENT RULE\n")
    assert execute(preview, comparisons) == packed
    for change in [dict(before=2, after=1), dict(before=1, after=5), dict(repository="studio/west"),
                   dict(key="another-button"), dict(checkout=str(sources[1]["repo"]))]:
        bad = copy.deepcopy(comparisons[0])
        bad["compare"].update(change)
        execute(preview, [bad], ok=False)
    for rules in [dict(path="../RULES.md", first=2, last=2), dict(path="RULES.link", first=2, last=2),
                  dict(path="RULES.md", first=2, last=99)]:
        bad = copy.deepcopy(comparisons[0])
        bad["compare"]["rules"] = rules
        execute(preview, [bad], ok=False)
    bad = copy.deepcopy(comparisons[0])
    bad["concern_letter"] = "C"
    execute(preview, [bad], ok=False)
    assert checkpoint(memory) == before
    print("PASS: exact revisions, base rule, image source, repository and path gates", flush=True)

    if live:
        answers = execute(native + ["--compare-visual", memory], comparisons, directory / "reviews-first")
        again = execute(native + ["--compare-visual", memory], comparisons, directory / "reviews-restarted")
        assert len(answers) == len(again) == len(expected)
        assert (directory / "reviews-first.stdout.jsonl").read_bytes() == (directory / "reviews-restarted.stdout.jsonl").read_bytes()
        for answer, request, verdict, evidence in zip(answers, comparisons, expected, packed):
            assert answer["verdict"] == verdict and answer["comparison"] == evidence, answer
            assert answer["id"] == request["id"]
            assert answer["input_sha256"] == evidence["input_sha256"]
            assert answer["concern"] == answer["p_a" if request["concern_letter"] == "A" else "p_b"]
            assert answer["clean"] == answer["p_b" if request["concern_letter"] == "A" else "p_a"]
            assert answer["verdict"] == ("CONCERN" if answer["concern"] >= answer["clean"] else "CLEAN")
            assert answer["letter"] == (request["concern_letter"] if verdict == "CONCERN" else
                                         ("B" if request["concern_letter"] == "A" else "A"))
        assert checkpoint(memory) == before
        print(json.dumps(dict(reviews=len(answers), verdicts=[a["verdict"] for a in answers], restart="byte-identical")), flush=True)
    else:
        # A newer observation can describe an older commit. Knowledge order
        # alone must not masquerade as Git ancestry.
        back = copy.deepcopy(rows[0])
        back["id"] = "backwards-commit"
        back["remember"]["supersedes"] = 4
        old = execute(fixture, [back, synthetic(back)])[0]
        bad = copy.deepcopy(comparisons[0])
        bad["compare"].update(before=2, after=old["sequence"])
        execute(preview, [bad], ok=False)
        # A rule change at the head must not replace the selected base rule.
        repo = sources[0]["repo"]
        git(repo, "checkout", "-q", "-b", "head-rule", sources[0]["commits"][0])
        (repo / "RULES.md").write_text("Visual contract\nThe blue button must be labelled Delete.\n")
        git(repo, "commit", "-qam", "different rule at head")
        trap = copy.deepcopy(back)
        trap["id"] = "head-rule-trap"
        trap["remember"].update(commit=git(repo, "rev-parse", "HEAD"), supersedes=old["sequence"])
        newest = execute(fixture, [trap, synthetic(trap)])[0]
        query = copy.deepcopy(comparisons[0])
        query["compare"]["after"] = newest["sequence"]
        assert execute(preview, [query])[0]["rule"]["quote"] == sources[0]["rule"]
        print("PASS: reversed Git ancestry refused; head rule cannot replace base rule", flush=True)
        for field, value in [("question", "Is the blue button visible?"), ("choice_a", "Open")]:
            changed = copy.deepcopy(rows[1])
            changed["id"] = "different-" + field
            changed[field] = value
            changed["remember"]["supersedes"] = newest["sequence"]
            newest = execute(fixture, [changed, synthetic(changed)])[0]
            query["compare"]["after"] = newest["sequence"]
            execute(preview, [query], ok=False)
        print("PASS: different observation questions or answer sets cannot be compared", flush=True)
    print("PASS: visual comparison" + (" with original OneJev" if live else " offline invariants"), flush=True)
    if temporary:
        temporary.cleanup()


if __name__ == "__main__":
    main()
