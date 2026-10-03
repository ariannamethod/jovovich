#!/usr/bin/env python3
"""Build two review corpora differing only in analysis/findings key order."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "training/sft_review_v5.jsonl"
REASONS = "training/explanations/reasons.json"
BEFORE = "training/sft_review_v6_before.jsonl"
AFTER = "training/sft_review_v6_after.jsonl"
SUFFIX = " Include a concise analysis string connecting the relevant rule, changed line and consequence."
END = ("Review the changed lines against these rules. Return only a JSON object with findings. "
       "Each finding uses line_id (the bracketed number) and reason (explain the concrete conflict). "
       "If clean, return an empty findings list. At most two findings.")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse(text):
    def bad_number(value):
        raise ValueError(f"invalid JSON number: {value}")
    return json.loads(text, object_pairs_hook=unique_object, parse_constant=bad_number)


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def prompt_parts(user):
    require(user.endswith(END), "unexpected review task suffix")
    evidence, instruction = user.rsplit("\n\n" + END, 1)
    require(not instruction, "review instruction has trailing data")
    preamble, tail = evidence.split("\n\nSurrounding diff:\n")
    patch, listing = tail.split("\n\nChanged lines to review:\n")
    description, rules = preamble.split("Repository rules for ", 1)
    # The file heading and precedence guidance are not repository rules.
    rules = rules.split("AGENTS.md:\n", 1)[1]
    changed = {}
    for line in listing.splitlines():
        match = re.fullmatch(r"\[(\d+)\] (ADDED|REMOVED) ([^\n]+?):(\d+): (.*)", line)
        require(match is not None, "malformed changed-line listing")
        index = int(match[1])
        require(index not in changed, "duplicate changed-line index")
        changed[index] = {"line_id": index, "side": match[2], "path": match[3],
                          "line": int(match[4]), "quote": match[5]}
    context = description + "\n" + "\n".join(line[1:] for line in patch.splitlines() if line.startswith(" "))
    return rules, context, changed


def build_corpora(root=ROOT, source=None, reasons=None):
    root = Path(root)
    source_path = Path(source) if source is not None else root / SOURCE
    reasons_path = Path(reasons) if reasons is not None else root / REASONS
    source_bytes, reason_bytes = source_path.read_bytes(), reasons_path.read_bytes()
    spec = parse(reason_bytes)
    require(spec["schema_version"] == 1, "unsupported reasons schema")
    require(spec["source"] == {"path": SOURCE, "sha256": sha(source_bytes)}, "source hash mismatch")
    require(spec["authoring_inputs"] == [SOURCE], "rationales must be sourced only from the training corpus")
    raw_rows = source_bytes.splitlines(keepends=True)
    require(all(line.endswith(b"\n") and line.strip() for line in raw_rows), "source requires nonempty newline-terminated rows")
    rows = [parse(line) for line in raw_rows]
    require(len(rows) == 76, "expected 76 source rows")
    ids = [row["id"] for row in rows]
    require(len(set(ids)) == len(ids), "duplicate source row id")
    reviews = [row for row in rows if row["kind"] == "review"]
    require(len(reviews) == 52, "expected 52 review rows")
    require(isinstance(spec["rows"], list), "reasons rows must be a list")
    reason_ids = [entry["id"] for entry in spec["rows"]]
    require(len(set(reason_ids)) == len(reason_ids), "duplicate rationale id")
    require(reason_ids == [row["id"] for row in reviews], "rationale coverage/order mismatch")
    entries = {entry["id"]: entry for entry in spec["rows"]}
    pairs, before, after, audit_rows, retained = {}, [], [], [], []
    for row, raw in zip(rows, raw_rows):
        if row["kind"] != "review":
            before.append(raw)
            after.append(raw)
            retained.append({"id": row["id"], "raw_row_sha256": sha(raw)})
            continue
        identifier = row["id"]
        require([message["role"] for message in row["messages"]] == ["system", "user", "assistant"],
                f"{identifier}: expected system/user/assistant messages")
        entry = entries[identifier]
        require(entry["pair"] == row["pair"], f"{identifier}: pair mismatch")
        analysis = entry["analysis"]
        require(isinstance(analysis, str) and 80 <= len(analysis) <= 640 and analysis.strip() == analysis,
                f"{identifier}: rationale must be concise nonempty prose")
        require(not re.search(r"\b(?:concern|clean|gold|label|dataset|holdout)\b|<\|[^>]*\|>|\"findings\"", analysis, re.I),
                f"{identifier}: rationale leaks class/format metadata")
        require(all(source_id not in analysis for source_id in ids), f"{identifier}: rationale leaks source id")
        rules, context, changed = prompt_parts(row["messages"][1]["content"])
        evidence = entry["evidence"]
        require(set(evidence) == {"rule", "context", "changed"}, f"{identifier}: unexpected evidence fields")
        for field, region in (("rule", rules), ("context", context)):
            quote = evidence[field]
            require(isinstance(quote, str) and len(quote.strip()) >= 12 and quote in region,
                    f"{identifier}: invalid {field} anchor")
        anchors = evidence["changed"]
        require(isinstance(anchors, list) and anchors, f"{identifier}: changed anchors required")
        anchor_ids = [anchor["line_id"] for anchor in anchors]
        require(len(set(anchor_ids)) == len(anchor_ids), f"{identifier}: duplicate changed anchor")
        for anchor in anchors:
            index = anchor["line_id"]
            require(type(index) is int and index in changed and anchor == changed[index],
                    f"{identifier}: invalid changed-line anchor")
        references = [int(number) for number in re.findall(r"\[(\d+)\]", analysis)]
        require(set(references) == set(anchor_ids), f"{identifier}: analysis references must match changed anchors")
        answer = parse(row["messages"][2]["content"])
        require(set(answer) == {"findings"} and isinstance(answer["findings"], list), f"{identifier}: invalid original answer")
        for finding in answer["findings"]:
            require(type(finding["line_id"]) is int and finding["line_id"] in changed,
                    f"{identifier}: finding has invalid line_id")
        pairs.setdefault(row["pair"], []).append(bool(answer["findings"]))
        versions = []
        for order in ("before", "after"):
            output = copy.deepcopy(row)
            output["messages"][1]["content"] += SUFFIX
            result = ({"analysis": analysis, "findings": answer["findings"]} if order == "before"
                      else {"findings": answer["findings"], "analysis": analysis})
            output["messages"][2]["content"] = compact(result)
            versions.append((compact(output) + "\n").encode())
        before.append(versions[0])
        after.append(versions[1])
        audit_rows.append({"id": identifier, "pair": row["pair"], "source_raw_row_sha256": sha(raw),
                           "analysis_sha256": sha(analysis.encode()), "analysis_characters": len(analysis),
                           "analysis_words": len(analysis.split()), "findings_sha256": sha(compact(answer["findings"]).encode()),
                           "changed_line_ids": anchor_ids})
    require(len(pairs) == 26 and all(values == [True, False] for values in pairs.values()),
            "expected 26 ordered concern/clean pairs")
    before_bytes, after_bytes = b"".join(before), b"".join(after)
    audit = {"schema_version": 1, "source": spec["source"],
             "reasons": {"path": REASONS, "sha256": sha(reason_bytes)},
             "builder": {"path": "training/explanations/build_corpora.py", "sha256": sha(Path(__file__).read_bytes())},
             "task_suffix": SUFFIX,
             "counts": {"rows": len(rows), "review_rows": len(reviews), "review_pairs": len(pairs), "retained_raw_rows": len(retained)},
             "before": {"sha256": sha(before_bytes), "bytes": len(before_bytes)},
             "after": {"sha256": sha(after_bytes), "bytes": len(after_bytes)},
             "review_rows": audit_rows, "retained_rows": retained}
    return {"before": before_bytes, "after": after_bytes, "audit": audit}


def write_exclusive(outputs):
    paths = [Path(path).resolve() for path, _ in outputs]
    require(len(set(paths)) == len(paths), "output paths must be distinct")
    require(all(not path.exists() for path in paths), "output already exists")
    created = []
    try:
        for path, (_, data) in zip(paths, outputs):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            created.append(path)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
    except BaseException:
        for path in created:
            path.unlink()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / SOURCE)
    parser.add_argument("--reasons", type=Path, default=ROOT / REASONS)
    parser.add_argument("--before", type=Path, default=ROOT / BEFORE)
    parser.add_argument("--after", type=Path, default=ROOT / AFTER)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--check", action="store_true", help="verify existing corpora without writing")
    args = parser.parse_args()
    try:
        built = build_corpora(source=args.source, reasons=args.reasons)
        outputs = [(args.before, built["before"]), (args.after, built["after"])]
        if args.check:
            require(args.audit is None, "--check does not write an audit")
            for path, data in outputs:
                require(path.read_bytes() == data, f"generated corpus differs: {path}")
        else:
            if args.audit:
                outputs.append((args.audit, (json.dumps(built["audit"], ensure_ascii=False, indent=2) + "\n").encode()))
            inputs = {args.source.resolve(), args.reasons.resolve(), Path(__file__).resolve()}
            require(not any(path.resolve() in inputs for path, _ in outputs), "output aliases an input")
            write_exclusive(outputs)
        print(json.dumps({"counts": built["audit"]["counts"], "before": built["audit"]["before"], "after": built["audit"]["after"]}))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f"explanation corpus: {error}\n")


if __name__ == "__main__":
    main()
