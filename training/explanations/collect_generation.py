#!/usr/bin/env python3
"""Collect native free generation; verify each closed case remotely before advancing."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from durable_archive import ArchiveError, DurableArchive, HFTransport

LIMIT = 512
CONTEXT = 8192
ENVIRONMENT = {"NT_NO_I8": "1", "NT_SIMD_THREADS": "4",
               "NT_QMV_THREADS": "4", "NT_ATTN_THREADS": "4"}


def native_environment():
    return {**{key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TMPDIR")
               if key in os.environ}, **ENVIRONMENT}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def identity(path):
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def binding(path):
    before = identity(path)
    result = {"path": str(path), "bytes": before[2], "sha256": digest(path)}
    require(before == identity(path), "input changed while hashing")
    return result, before


def save(path, value):
    write(path, (json.dumps(value, ensure_ascii=False, allow_nan=False,
                            sort_keys=True, indent=2) + "\n").encode())


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def parse(raw):
    def bad_number(_):
        raise ValueError("nonfinite JSON number")
    return json.loads(raw, object_pairs_hook=unique_object, parse_constant=bad_number)


def render_prompt(row):
    """The gold assistant message is inspected for role only, never rendered."""
    messages = row.get("messages")
    require(isinstance(messages, list) and len(messages) == 3 and
            [m.get("role") for m in messages] == ["system", "user", "assistant"],
            "review requires system/user/assistant messages")
    parts = []
    for message in messages[:2]:
        content = message.get("content")
        require(isinstance(content, str) and content and "\0" not in content,
                "invalid prompt content")
        require(not any(marker in content for marker in
                        ("<|im_start|>", "<|im_end|>", "<|endoftext|>")),
                "prompt contains ChatML control marker")
        parts.append("<|im_start|>" + message["role"] + "\n" + content + "<|im_end|>\n")
    return ("".join(parts) + "<|im_start|>assistant\n").encode("utf-8")


def review_cases(raw, *, split="train"):
    lines = raw.splitlines(keepends=True)
    require(lines and all(line.endswith(b"\n") and line.strip() for line in lines),
            "corpus requires nonempty newline-terminated rows")
    rows = [parse(line) for line in lines]
    identifiers = [row.get("id") for row in rows]
    require(all(isinstance(value, str) and value for value in identifiers) and
            len(set(identifiers)) == len(identifiers), "invalid or duplicate corpus IDs")
    require(split in ("train", "holdout"), "invalid corpus split")
    heldout_prompts = None
    if split == "holdout":
        # Feed only the case's source context to the production renderer. The
        # common extension is in the user task, never an assistant answer seed.
        from build_corpora import SUFFIX
        code = r'''
import {readFileSync} from 'node:fs';
import {chunksFor, promptFor} from './bin/jovovich.mjs';
const rows = JSON.parse(readFileSync(process.argv[1], 'utf8'));
const identity = readFileSync('prompts/identity.txt', 'utf8');
const end = '<|im_end|>\n<|im_start|>assistant\n';
const result = [];
for (const row of rows) {
  const chunks = chunksFor(row.files);
  if (chunks.length !== 1) throw new Error('heldout requires one review chunk');
  const prompt = await promptFor(chunks[0], row.context, identity, 'chatml');
  if (!prompt.endsWith(end)) throw new Error('production ChatML changed');
  result.push(prompt.slice(0, -end.length) + process.argv[2] + end);
}
process.stdout.write(JSON.stringify(result));
'''
        # A temporary regular file avoids pipe EOF behavior in restricted runners.
        import tempfile
        with tempfile.TemporaryDirectory(prefix="jovovich-holdout-prompts-") as temporary:
            source = Path(temporary) / "contexts.json"
            source.write_text(json.dumps([{"files": row["files"], "context": row["context"]}
                                          for row in rows], ensure_ascii=False))
            rendered = subprocess.run(["node", "--input-type=module", "-e", code, str(source), SUFFIX],
                                      cwd=ROOT, env=native_environment(), capture_output=True, check=True)
            heldout_prompts = parse(rendered.stdout)
        require(isinstance(heldout_prompts, list) and len(heldout_prompts) == len(rows),
                "heldout rendering coverage mismatch")
    cases = []
    for index, (row, line) in enumerate(zip(rows, lines)):
        if split == "holdout" or row.get("kind") == "review":
            prompt = heldout_prompts[index].encode() if split == "holdout" else render_prompt(row)
            cases.append({"case_id": row["id"], "raw_row_sha256": sha(line),
                          "prompt_sha256": sha(prompt), "prompt": prompt})
    require(cases, "corpus has no review rows")
    return cases


def validate_trace(trace):
    fields = {"schema_version", "prompt_token_ids", "generated_token_ids",
              "requested_limit", "emitted_tokens", "stop_reason"}
    require(isinstance(trace, dict) and set(trace) == fields and
            type(trace["schema_version"]) is int and trace["schema_version"] == 1,
            "unsupported native token trace")
    for field in ("prompt_token_ids", "generated_token_ids"):
        ids = trace[field]
        require(isinstance(ids, list) and ids and
                all(type(value) is int and value >= 0 for value in ids),
                "invalid native token IDs")
    require(type(trace["requested_limit"]) is int and trace["requested_limit"] == LIMIT,
            "native token budget differs from plan")
    emitted = trace["emitted_tokens"]
    count = len(trace["generated_token_ids"])
    require(type(emitted) is int and 0 <= emitted <= LIMIT and count <= LIMIT,
            "invalid native token count")
    require(len(trace["prompt_token_ids"]) <= CONTEXT - LIMIT,
            "native prompt exceeds reserved context")
    stop = trace["stop_reason"]
    require((stop == "eos" and count == emitted + 1) or
            (stop == "token-limit" and count == emitted == LIMIT),
            "native stop reason/count mismatch")
    return "eos" if stop == "eos" else "length"


def native_command(executable, model, trace):
    return [str(executable), "--model", str(model), "--tokens", str(LIMIT),
            "--context", str(CONTEXT), "--temperature", "0", "--trace-tokens", str(trace)]


def token_command(executable, model):
    return [str(executable), "--model", str(model), "--tokens", str(LIMIT),
            "--context", str(CONTEXT), "--temperature", "0", "--token-ids"]


def validate_prompt_ids(ids):
    require(isinstance(ids, list) and 0 < len(ids) <= CONTEXT - LIMIT and
            all(type(value) is int and value >= 0 for value in ids),
            "invalid tokenizer preflight IDs")
    return ids


def parse_prompt_ids(raw):
    # src/infer.c's --token-ids emits one comma-separated decimal line.
    require(re.fullmatch(rb"(?:0|[1-9][0-9]*)(?:,(?:0|[1-9][0-9]*))*\n", raw) is not None,
            "malformed native tokenizer output")
    return validate_prompt_ids([int(value) for value in raw.rstrip(b"\n").split(b",")])


def execute(argv, prompt, stdout, stderr, env):
    with prompt.open("rb") as incoming, stdout.open("xb") as out, stderr.open("xb") as err:
        child = subprocess.Popen(argv, cwd=ROOT, env=env, stdin=incoming, stdout=out, stderr=err)
        try:
            return child.wait()
        except BaseException:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            raise
        finally:
            out.flush()
            err.flush()
            os.fsync(out.fileno())
            os.fsync(err.fileno())


def collect(archive, *, corpus, model, executable, output, run_id,
            expected_model_sha256=None, expected_infer_sha256=None, split="train"):
    """New run only. Archive injection supports deterministic local transport tests.

    Bootstrap and each intent/result use DurableArchive's synchronous verified
    readback barrier. An exception leaves closed local evidence and stops work.
    Model bytes remain in their model repository; this journal binds their hash.
    """
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", run_id) is not None,
            "invalid run ID")
    corpus, model, executable = (Path(path).resolve() for path in (corpus, model, executable))
    output = Path(output).resolve()
    require(not output.exists(), "run output must be new")
    source_paths = [Path(__file__).resolve(), ROOT / "training/durable_archive.py",
                    ROOT / "src/infer.c", ROOT / "Makefile"]
    if split == "holdout":
        source_paths.extend([ROOT / "bin/jovovich.mjs", ROOT / "prompts/identity.txt",
                             ROOT / "training/explanations/build_corpora.py"])
    paths = [corpus, model, executable, *source_paths]
    bindings, identities = {}, {}
    for path in paths:
        entry, signature = binding(path)
        bindings[path] = entry
        identities[path] = signature
    if expected_model_sha256 is not None:
        require(bindings[model]["sha256"] == expected_model_sha256, "model checksum mismatch")
    if expected_infer_sha256 is not None:
        require(bindings[executable]["sha256"] == expected_infer_sha256, "infer checksum mismatch")
    raw_corpus = corpus.read_bytes()
    require(sha(raw_corpus) == bindings[corpus]["sha256"], "corpus changed while loading")
    cases = review_cases(raw_corpus, split=split)
    notorch = subprocess.run(["git", "-C", str(ROOT / "deps/notorch"), "rev-parse", "HEAD"],
                             capture_output=True, check=True, text=True).stdout.strip()
    require(re.fullmatch(r"[0-9a-f]{40}", notorch) is not None, "invalid notorch revision")
    dirty = subprocess.run(["git", "-C", str(ROOT / "deps/notorch"), "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, check=True, text=True).stdout
    require(not dirty, "notorch tracked sources must be clean")
    output.mkdir(parents=True)
    write(output / "inputs/corpus.jsonl", raw_corpus)
    files = {"inputs/corpus.jsonl": output / "inputs/corpus.jsonl"}
    for index, path in enumerate(source_paths):
        target = output / "inputs/sources" / (str(index) + "-" + path.name)
        write(target, path.read_bytes())
        require(digest(target) == bindings[path]["sha256"], "source snapshot mismatch")
        files[str(target.relative_to(output))] = target
    for index, case in enumerate(cases):
        relative = f"cases/{index:03d}/prompt.txt"
        write(output / relative, case["prompt"])
        case["prompt_path"] = relative
        files[relative] = output / relative
    manifest = {"schema_version": 1, "run_id": run_id, "split": split, "started_utc": now(),
                "corpus": bindings[corpus], "model": bindings[model], "infer": bindings[executable],
                "sources": [bindings[path] for path in source_paths], "notorch_commit": notorch,
                "environment": ENVIRONMENT, "temperature": 0, "token_budget": LIMIT,
                "context": CONTEXT, "assistant_prefix": "<|im_start|>assistant\n",
                "prompt_token_preflight": "native --token-ids before each generation; exact trace equality",
                "cases": [{k: v for k, v in case.items() if k != "prompt"} for case in cases]}
    save(output / "manifest.json", manifest)
    files["manifest.json"] = output / "manifest.json"
    archive.sync_unit("inputs", files, sequence=0)
    sequence, records = 1, []
    # Credentials remain in the archiving parent, never in the model subprocess.
    env = native_environment()
    for index, case in enumerate(cases):
        directory = output / "cases" / f"{index:03d}"
        prompt, trace_path = directory / "prompt.txt", directory / "tokens.json"
        stdout, stderr = directory / "stdout.bin", directory / "stderr.bin"
        token_stdout, token_stderr = directory / "prompt-token-ids.txt", directory / "tokenizer.stderr.bin"
        argv = native_command(executable, model, trace_path)
        token_argv = token_command(executable, model)
        intent = {"case_id": case["case_id"], "argv": argv, "environment": ENVIRONMENT,
                  "tokenizer_argv": token_argv,
                  "prompt_sha256": case["prompt_sha256"], "started_utc": now()}
        save(directory / "intent.json", intent)
        archive.sync_unit(f"case-{index:03d}-intent",
                          {f"cases/{index:03d}/intent.json": directory / "intent.json"}, sequence=sequence)
        sequence += 1
        code, trace, failure, token_code = None, None, None, None
        response, finish = None, "error"
        try:
            require(all(identity(path) == signature for path, signature in identities.items()),
                    "bound input changed before generation")
            require(digest(prompt) == case["prompt_sha256"], "rendered prompt changed")
            token_failure, expected_ids = None, None
            try:
                token_code = execute(token_argv, prompt, token_stdout, token_stderr, env)
                require(token_code == 0, "native tokenizer preflight failed")
                expected_ids = parse_prompt_ids(token_stdout.read_bytes())
            except BaseException as exc:
                token_failure = exc
            token_files = {str(path.relative_to(output)): path for path in
                           (token_stdout, token_stderr) if path.is_file()}
            save(directory / "tokenizer-result.json", {
                "case_id": case["case_id"], "return_code": token_code,
                "status": "failed" if token_failure is not None else "completed",
                "prompt_token_ids": expected_ids,
                "error_type": type(token_failure).__name__ if token_failure is not None else None,
                "finished_utc": now(), "artifacts": [binding(path)[0] for path in token_files.values()]})
            token_files[f"cases/{index:03d}/tokenizer-result.json"] = directory / "tokenizer-result.json"
            archive.sync_unit(f"case-{index:03d}-tokenizer", token_files, sequence=sequence)
            sequence += 1
            if token_failure is not None:
                raise token_failure
            require(all(identity(path) == signature for path, signature in identities.items()),
                    "bound input changed during tokenization")
            require(digest(prompt) == case["prompt_sha256"], "rendered prompt changed after tokenization")
            code = execute(argv, prompt, stdout, stderr, env)
            require(code == 0, "native inference failed")
            require(all(identity(path) == signature for path, signature in identities.items()),
                    "bound input changed during generation")
            trace = parse(trace_path.read_bytes())
            finish = validate_trace(trace)
            require(trace["prompt_token_ids"] == expected_ids,
                    "generation trace differs from native tokenizer preflight")
            response = stdout.read_bytes().decode("utf-8")
        except ArchiveError:
            # A failed readback locks the archive to that exact unit for retry.
            # Stop without attempting a different unit or a model call.
            raise
        except BaseException as exc:
            failure = exc
            finish = "error"
            if stdout.exists():
                try:
                    response = stdout.read_bytes().decode("utf-8")
                except UnicodeDecodeError:
                    pass
        metadata = {"model_path": str(model), "model_sha256": bindings[model]["sha256"],
                    "prompt_sha256": case["prompt_sha256"], "requested_limit": LIMIT}
        if trace is not None and finish != "error":
            metadata.update({key: trace[key] for key in ("prompt_token_ids", "generated_token_ids")})
        record = {"case_id": case["case_id"], "corpus_sha256": bindings[corpus]["sha256"],
                  "raw_response": response, "raw_response_sha256": sha(response.encode()) if response is not None else None,
                  "finish_reason": finish, "metadata": metadata}
        if failure is not None:
            record["error"] = type(failure).__name__
        save(directory / "record.json", record)
        result_files = {str(path.relative_to(output)): path for path in
                        (stdout, stderr, trace_path, directory / "record.json") if path.is_file()}
        receipt = {"case_id": case["case_id"], "return_code": code,
                   "tokenizer_return_code": token_code, "finish_reason": finish,
                   "finished_utc": now(), "artifacts": [binding(path)[0] for path in result_files.values()]}
        save(directory / "result.json", receipt)
        result_files[str((directory / "result.json").relative_to(output))] = directory / "result.json"
        archive.sync_unit(f"case-{index:03d}-result", result_files, sequence=sequence)
        sequence += 1
        if failure is not None:
            raise RuntimeError("generation failed; closed case evidence archived") from failure
        records.append(record)
    require(all(binding(path)[0] == entry for path, entry in bindings.items()),
            "final input binding mismatch")
    raw_records = b"".join((json.dumps(record, ensure_ascii=False, allow_nan=False,
                                     separators=(",", ":")) + "\n").encode() for record in records)
    write(output / "generations.jsonl", raw_records)
    completed = {"schema_version": 1, "run_id": run_id, "native_completed_utc": now(), "cases": len(records),
                 "status": "native_completed", "archive_status": "requires_verified_receipt",
                 "generations_sha256": sha(raw_records), "inputs_unchanged": True}
    save(output / "completion.json", completed)
    verified = archive.sync_unit("completion", {"generations.jsonl": output / "generations.jsonl",
                                                "completion.json": output / "completion.json"}, sequence=sequence)
    return {**completed, "status": "completed", "archive_status": "verified",
            "remote_verification": verified}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sft", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "holdout"), default="train")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--model-sha256", required=True)
    parser.add_argument("--infer", type=Path, default=ROOT / "build/jovovich-infer")
    parser.add_argument("--infer-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--hf-repo", required=True)
    parser.add_argument("--remote-prefix", default="experiments/explanation-order")
    parser.add_argument("--token-file", type=Path)
    args = parser.parse_args()
    token = args.token_file.read_text().strip() if args.token_file else os.environ.get("HF_TOKEN", "")
    archive = DurableArchive(HFTransport(args.hf_repo, token), args.run_id, args.remote_prefix)
    result = collect(archive, corpus=args.sft, model=args.model, executable=args.infer,
                     output=args.output, run_id=args.run_id,
                     expected_model_sha256=args.model_sha256, expected_infer_sha256=args.infer_sha256,
                     split=args.split)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
