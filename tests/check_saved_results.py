"""Compare native output with the recorded model run, including its mistakes."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "examples/onejev-20261106"


def rows(path):
    return {r["id"]: r for r in map(json.loads, path.read_text().splitlines())}


actual = rows(Path(sys.argv[1]))
answers = rows(DATA / "answers.jsonl")
cases = rows(DATA / "acceptance.jsonl")
metadata = json.loads((DATA / "metadata.json").read_text())
assert hashlib.sha256((DATA / "acceptance.jsonl").read_bytes()).hexdigest() == metadata["cases_sha256"]
assert len(actual) == 14 and actual.keys() == answers.keys()
for key, review in actual.items():
    recorded = answers[key]
    assert review["schema_version"] == 1
    assert review["choice"]["verdict"] == recorded["predicted"], key
    assert review["choice"]["probabilities"] == recorded["probabilities"], key
    assert review["model"] == {"id": metadata["model"], "revision": metadata["revision"]}
    assert review["question"] == metadata["question"]["instructions"]
    assert review["input"]["context"] == cases[key]["context"]
    assert review["scope"]["file"] in cases[key]["context"]
    for field in ("rule_excerpt", "change_excerpt"):
        assert review["input"][field] in cases[key]["context"]

# The renderer preserves both measured misses as well as all 12 correct choices.
misses = {k for k, v in actual.items() if v["choice"]["verdict"] != cases[k]["expected"]}
assert misses == {"accept-boundary-False", "accept-disabled-False"}

escaped = json.loads((ROOT / "build/escaping.json").read_text())
assert escaped["scope"]["file"] == "a*[x]<b>.c"
assert escaped["input"]["rule_excerpt"] == 'keep "quoted" \\ paths\tand controls\x01.'
assert escaped["input"]["change_excerpt"] == "```\n<script>\n`\n````\n"
markdown = (ROOT / "build/escaping.md").read_text()
assert "a\\*\\[x\\]&lt;b&gt;\\.c" in markdown
assert "`````text\n```\n<script>\n`\n````\n`````\n" in markdown
print("All 14 choices match the saved run exactly; JSON round trips and literal Markdown checked.")
