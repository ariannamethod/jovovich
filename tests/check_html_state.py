#!/usr/bin/env python3
"""Git/receipt gates for the HTML file view. Scores here are synthetic."""
import argparse
import copy
import json
import tempfile
from pathlib import Path

from check_visual_batch import ROOT, command, encode, fake_visual
from check_visual_memory import digest, git, synthetic, checkpoint


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", default=str(ROOT / "build/jovovich-pack"))
    parser.add_argument("--report", default=str(ROOT / "build/jovovich-report"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        repo, memory = work / "repo", work / "memory"
        repo.mkdir(); memory.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "HTML state fixture")
        git(repo, "config", "user.email", "fixture@example.invalid")
        (repo / "RULES.md").write_text("The button must say Save.\n")
        commits = []
        for version in range(2):
            label = "Save" if version else "Delete"
            prefix = "<!-- outside-hunk -->\n" + "<!-- unchanged -->\n" * 20
            (repo / "panel.html").write_text(prefix + f'<button title="A & B">{label}</button>\n<!-- </state> -->\n')
            (repo / "upper.HTM").write_text(f"<p>{label}</p>\n")
            (repo / "plain.txt").write_text(f"{label}\n")
            (repo / "empty.html").write_text("" if version else "<p>old</p>\n")
            (repo / "link.html").unlink(missing_ok=True)
            (repo / "link.html").symlink_to("panel.html" if version else "upper.HTM")
            if version:
                (repo / "removed.html").unlink()
                (repo / "added.htm").write_text("<p>new</p>\n")
            else:
                (repo / "removed.html").write_text("<p>old</p>\n")
            pixels = b"P6\n1 1\n255\n" + bytes((version * 100, 0, 0))
            (repo / "screen.ppm").write_bytes(pixels)
            git(repo, "add", "."); git(repo, "commit", "-qm", f"state {version}")
            commit = git(repo, "rev-parse", "HEAD"); commits.append(commit)
            row = dict(id=f"image-{version}", question="Which button is visible?", choice_a="Save", choice_b="Delete",
                       image=dict(path=str(repo / "screen.ppm"), sha256=digest(pixels)),
                       remember=dict(repository="test/html", key="screen", pull_request=7, checkout=str(repo),
                                     commit=commit, path="screen.ppm", supersedes=version))
            command([ROOT / "build/visual-memory-fixture", memory],
                    (encode(row) + "\n" + encode(synthetic(row)) + "\n").encode())
        journal = checkpoint(memory)
        request = dict(id="screen-review", compare=dict(repository="test/html", key="screen", checkout=str(repo),
                       before=1, after=2, rules=dict(path="RULES.md", first=1, last=1)))
        requests = work / "requests.jsonl"; requests.write_text(encode(request) + "\n")
        pack_args = [args.pack, "--with-visual", memory, "test/html", 7, requests,
                     "--all", repo, *commits, "RULES.md"]
        packed = command(pack_args)
        rows = [json.loads(x) for x in packed.splitlines()]
        html_paths = {r["file"] for r in rows if "html_state" in r}
        assert html_paths == {"added.htm", "empty.html", "panel.html", "upper.HTM"}, html_paths
        for r in rows:
            if "html_state" not in r:
                continue
            state = r["html_state"]
            blob = git(repo, "rev-parse", commits[1] + ":" + r["file"])
            assert state["head_blob"] == blob
            assert state["content"] == (repo / r["file"]).read_text()
            assert state["sha256"] == digest(state["content"].encode())
        (repo / "panel.html").write_text("UNCOMMITTED WRONG CONTENT\n")
        assert command(pack_args) == packed
        legacy = json.loads(command([args.pack, repo, *commits, "RULES.md", "panel.html"]))
        assert "html_state" not in legacy
        # Different view, identical original diff/context/id evidence.
        panel = next(i for i, r in enumerate(rows) if r["file"] == "panel.html")
        assert "outside-hunk" not in rows[panel]["change_excerpt"]
        assert "outside-hunk" in rows[panel]["html_state"]["content"]
        assert all(legacy[k] == rows[panel][k] for k in ("id", "context", "rule_excerpt", "change_excerpt", "source"))

        def votes(data):
            chunks = []
            for r in data:
                if "visual_request" in r:
                    chunks.append(fake_visual(r["visual_request"], memory, False))
                else:
                    text = work / "text.jsonl"; text.write_text(encode(r) + "\n")
                    chunks.append(command([ROOT / "build/batch-fixture", "emit", text, "clean"]))
            return b"".join(chunks)

        def report(data, answers=None, ok=True, markdown=False):
            batch, out = work / "batch.jsonl", work / "answers.jsonl"
            batch.write_text("".join(encode(r) + "\n" for r in data))
            out.write_bytes(votes(data) if answers is None else answers)
            return command([args.report, batch, out, "--with-visual", memory, "test/html", 7,
                            *([] if markdown else ["--json"])], ok=ok)

        good = votes(rows)
        result = json.loads(report(rows, good))
        assert result["summary"]["verdict"] == "CLEAN"
        receipt = result["reviews"][panel]["execution"]["file_view"]
        assert receipt["policy"] == "html-head-paired/1"
        assert receipt["head_sha256"] == rows[panel]["html_state"]["sha256"]
        assert b"Model file view: complete HTML at the head commit; both option orders" in report(rows, good, markdown=True)
        for key, value in [("policy", "unknown"), ("head_blob", "0" * len(commits[1])),
                           ("head_sha256", "0" * 64)]:
            answers = [json.loads(x) for x in good.splitlines()]
            answers[panel]["execution"]["file_view"][key] = value
            report(rows, ("".join(encode(x) + "\n" for x in answers)).encode(), ok=False)
        for order in ("concern_first", "clean_first"):
            for key, value in (("prompt_sha256", "0" * 64), ("logit_a", 100), ("logit_b", -100)):
                answers = [json.loads(x) for x in good.splitlines()]
                answers[panel]["execution"]["file_view"][order][key] = value
                report(rows, ("".join(encode(x) + "\n" for x in answers)).encode(), ok=False)
        answers = [json.loads(x) for x in good.splitlines()]
        answers[panel]["choice"].update(verdict="CONCERN", probabilities={"CONCERN":0.9,"CLEAN":0.1})
        report(rows, ("".join(encode(x) + "\n" for x in answers)).encode(), ok=False)
        # A is stronger in both frames, but the aligned evidence favors CLEAN.
        answers = [json.loads(x) for x in good.splitlines()]
        view = answers[panel]["execution"]["file_view"]
        view["concern_first"].update(logit_a=3, logit_b=1)
        view["clean_first"].update(logit_a=5, logit_b=1)
        answers[panel]["choice"].update(verdict="CLEAN", probabilities={"CONCERN":0.268941432,"CLEAN":0.731058598})
        report(rows, ("".join(encode(x) + "\n" for x in answers)).encode())
        view["concern_first"].update(logit_a=4, logit_b=1)
        view["clean_first"].update(logit_a=5, logit_b=2)
        answers[panel]["choice"].update(verdict="CONCERN", probabilities={"CONCERN":0.5,"CLEAN":0.5})
        assert json.loads(report(rows, ("".join(encode(x) + "\n" for x in answers)).encode()))["summary"]["verdict"] == "CONCERN"
        answers[panel]["choice"].update(verdict="CLEAN", probabilities={"CONCERN":0.499999999,"CLEAN":0.500000001})
        report(rows, ("".join(encode(x) + "\n" for x in answers)).encode(), ok=False)
        for remove in (True, False):
            answers = [json.loads(x) for x in good.splitlines()]
            if remove:
                answers[panel]["execution"].pop("file_view")
            else:
                answers[panel]["question"] = "A different question"
            report(rows, ("".join(encode(x) + "\n" for x in answers)).encode(), ok=False)

        comparison = command([ROOT / "build/jovovich-replay", "compare-visual", memory], encode(request).encode()).rstrip(b"\n")
        def rebind(data):
            items = []
            for r in data:
                item = {k: r[k] for k in ("file", "id", "source")}
                if "visual_request" in r:
                    item["visual_comparison_sha256"] = digest(comparison)
                if "html_state" in r:
                    item["html_state_sha256"] = digest(encode(r["html_state"]).encode())
                items.append(item)
            manifest = dict(schema="jovovich.git-batch/2", scope="all_changed_paths", items=items)
            sha = digest(encode(manifest).encode())
            for r in data:
                r["batch"]["id"] = sha

        # Content + digest + new prompt/answer all agree, but not with Git HEAD.
        changed = copy.deepcopy(rows)
        changed[panel]["html_state"]["content"] = "<button>Delete</button>\n"
        changed[panel]["html_state"]["sha256"] = digest(changed[panel]["html_state"]["content"].encode())
        rebind(changed); report(changed, ok=False)
        changed = copy.deepcopy(rows)
        changed[panel]["html_state"]["head_blob"] = git(repo, "rev-parse", commits[0] + ":panel.html")
        rebind(changed); report(changed, ok=False)
        changed = copy.deepcopy(rows); changed[panel].pop("html_state")
        report(changed, ok=False)  # Manifest still requires the complete file state.
        for key, value in (("schema", "unknown"), ("sha256", "0" * 64),
                           ("content", "contains\x00NUL"), ("content", "x" * 262145), ("head_blob", "short")):
            changed = copy.deepcopy(rows); changed[panel]["html_state"][key] = value
            report(changed, good, ok=False)
        changed = copy.deepcopy(rows)
        plain = next(i for i, r in enumerate(changed) if r["file"] == "plain.txt")
        changed[plain]["html_state"] = changed[panel]["html_state"]
        rebind(changed); report(changed, good, ok=False)
        # Archived v2 diff inputs remain interpretable under their original policy.
        historical = copy.deepcopy(rows)
        for r in historical:
            r.pop("html_state", None)
        rebind(historical)
        assert json.loads(report(historical))["summary"]["verdict"] == "CLEAN"
        # Trace evidence is applied after selecting the committed file view.
        traced = copy.deepcopy(rows); r = traced[panel]; source = r["source"]
        r["trace_evidence"] = dict(schema="jovovich.paired-traces/1", review_id=r["id"],
            base_commit=source["base_commit"], head_commit=source["head_commit"],
            rule_sha256=source["rules_sha256"], change_sha256=source["diff_sha256"], metric="text",
            runs=[dict(mode=0, base="Delete", head="Save", required="Save")])
        assert json.loads(report(traced))["execution_summary"] == dict(selected_runs=1, met=1, failed=0)
        assert checkpoint(memory) == journal
        print("PASS: committed HTML capture, empty/added/deleted/link/uppercase paths, historical views, trace composition, Git and prompt bindings")


if __name__ == "__main__":
    main()
