#!/usr/bin/env python3
"""Recover pinned public/private inputs; this is a new receipt, not the lost run."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import urllib.error
import urllib.parse
import urllib.request

PRIVATE_REPO = "ataeff/jovovich"
PRIVATE_REVISION = "c9484feec99c5df47be5702d29098297aced1389"
PRIVATE_PREFIX = "experiments/matched-review/"
BASE = {
    "repo": "Qwen/Qwen2.5-Coder-0.5B-Instruct-GGUF",
    "revision": "ebb2015119c907b064c512bf053e945850b5875f",
    "file": "qwen2.5-coder-0.5b-instruct-q8_0.gguf",
    "sha256": "e1a77721fa97d412f121878223eec81fb4ae6f271e18f922d746711f67b344d1",
    "bytes": 675710848,
}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def origin(url):
    p = urllib.parse.urlsplit(url)
    return p.scheme, p.hostname, p.port or 443


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise ValueError("non-HTTPS redirect rejected")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and origin(req.full_url) != origin(newurl):
            redirected.remove_header("Authorization")
            redirected.remove_header("Proxy-Authorization")
        return redirected


def hashes(path):
    size = path.stat().st_size
    sha256 = hashlib.sha256()
    git_sha1 = hashlib.sha1(f"blob {size}\0".encode())
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(4 * 1024 * 1024), b""):
            sha256.update(chunk)
            git_sha1.update(chunk)
    return {"bytes": size, "sha256": sha256.hexdigest(), "git_blob_sha1": git_sha1.hexdigest()}


def check(actual, expected):
    return all(actual.get(key) == value for key, value in expected.items())


def error_record(exc):
    # urllib exceptions may include signed CDN URLs. Never archive their repr/message.
    item = {"type": type(exc).__name__}
    if isinstance(exc, urllib.error.HTTPError):
        item["http_status"] = exc.code
    if isinstance(exc, urllib.error.URLError):
        item["reason_type"] = type(exc.reason).__name__
    return item


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo.resolve()
    archive = root / "training/results/2026-10-02-gradient-control"
    archive.mkdir(parents=True, exist_ok=True)
    receipt_path = archive / "weight-recovery.json"
    # Preserve any earlier invocation rather than silently overwriting its evidence.
    if receipt_path.exists():
        number = 1
        while (archive / f"weight-recovery-attempt-{number}.json").exists():
            number += 1
        receipt_path.rename(archive / f"weight-recovery-attempt-{number}.json")
    receipt = {
        "schema": "jovovich.pinned-weight-recovery.v1",
        "purpose": "New download-and-verification after workspace maintenance; not a reconstruction of historical execution receipts or metrics.",
        "started_at": now(), "status": "running", "files": [], "events": [],
        "helper": {"path": str(Path(__file__).relative_to(root)), **hashes(Path(__file__))},
        "private_source": {"repo": PRIVATE_REPO, "revision": PRIVATE_REVISION, "prefix": PRIVATE_PREFIX},
        "credential_policy": "Credential read from supplied file; Authorization removed on every cross-origin redirect; no credentials or signed redirect URLs recorded.",
    }

    def save():
        temporary = receipt_path.with_suffix(".json.new")
        temporary.write_text(json.dumps(receipt, indent=2) + "\n")
        temporary.replace(receipt_path)

    opener = urllib.request.build_opener(SafeRedirect())

    def download(repo, revision, name, path, expected, token=None):
        event = {
            "repo": repo, "revision": revision, "file": name,
            "local_path": str(path.relative_to(root)), "expected": expected,
            "started_at": now(), "status": "running",
        }
        receipt["files"].append(event)
        save()
        try:
            if path.exists():
                actual = hashes(path)
                if not check(actual, expected):
                    raise ValueError("existing destination does not match expected hash/size")
                event.update(status="verified-existing", actual=actual, finished_at=now())
                save()
                print(json.dumps({"file": name, "status": event["status"], "bytes": actual["bytes"]}), flush=True)
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            partial = path.with_name(path.name + ".recovery-partial")
            serial = 1
            while partial.exists():
                partial = path.with_name(path.name + f".recovery-partial-{serial}")
                serial += 1
            event["partial_path"] = str(partial.relative_to(root))
            url = f"https://huggingface.co/{repo}/resolve/{revision}/{urllib.parse.quote(name, safe='/')}"
            headers = {"User-Agent": "jovovich-pinned-recovery/1"}
            if token:
                headers["Authorization"] = "Bearer " + token
            req = urllib.request.Request(url, headers=headers)
            with opener.open(req, timeout=120) as src, partial.open("xb") as dst:
                event["http_status"] = src.status
                event["final_origin"] = list(origin(src.url))
                sha256 = hashlib.sha256()
                git_sha1 = hashlib.sha1(f"blob {expected['bytes']}\0".encode())
                size = 0
                while True:
                    chunk = src.read(4 * 1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
                    sha256.update(chunk)
                    git_sha1.update(chunk)
                    size += len(chunk)
                    if size > expected["bytes"]:
                        raise ValueError("download exceeds pinned expected size")
                dst.flush()
                os.fsync(dst.fileno())
            actual = {"bytes": size, "sha256": sha256.hexdigest(), "git_blob_sha1": git_sha1.hexdigest()}
            event["actual"] = actual
            if not check(actual, expected):
                raise ValueError("download hash/size mismatch")
            # Verify the actual closed file as well as the streamed bytes.
            disk_actual = hashes(partial)
            if disk_actual != actual:
                raise ValueError("closed file differs from downloaded bytes")
            partial.replace(path)
            event.update(status="verified-downloaded", finished_at=now(), closed_file_verified=True)
            save()
            print(json.dumps({"file": name, "status": event["status"], "bytes": size}), flush=True)
        except Exception as exc:
            event.update(status="failed", error=error_record(exc), finished_at=now())
            if 'partial' in locals() and partial.exists():
                event["failed_partial"] = hashes(partial)
            save()
            raise

    save()
    try:
        tokens = re.findall(r"hf_[A-Za-z0-9]+", args.token_file.read_text())
        if len(set(tokens)) != 1:
            raise ValueError("expected exactly one distinct HF token")
        token = tokens[0]
        metadata_url = f"https://huggingface.co/api/models/{PRIVATE_REPO}/revision/{PRIVATE_REVISION}?blobs=true"
        with opener.open(urllib.request.Request(metadata_url, headers={"Authorization": "Bearer " + token}), timeout=120) as src:
            metadata = json.load(src)
        if metadata.get("sha") != PRIVATE_REVISION or metadata.get("private") is not True or metadata.get("id") != PRIVATE_REPO:
            raise ValueError("private source metadata binding failed")
        siblings = sorted([item for item in metadata["siblings"] if item["rfilename"].startswith(PRIVATE_PREFIX)], key=lambda item: item["rfilename"])
        if len(siblings) != 16:
            raise ValueError("expected exactly sixteen pinned private files")
        receipt["private_source"].update(private=True, metadata_sha=metadata["sha"], file_count=len(siblings))
        save()
        download(BASE["repo"], BASE["revision"], BASE["file"], root / "models/base-qwen.gguf", {"bytes": BASE["bytes"], "sha256": BASE["sha256"]})
        for item in siblings:
            name = item["rfilename"]
            relative = PurePosixPath(name.removeprefix(PRIVATE_PREFIX))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("unsafe filename")
            if "lfs" in item:
                expected = {"bytes": item["lfs"]["size"], "sha256": item["lfs"]["sha256"]}
                if item.get("size", expected["bytes"]) != expected["bytes"]:
                    raise ValueError("metadata size mismatch")
            else:
                expected = {"bytes": item["size"], "git_blob_sha1": item["blobId"]}
            download(PRIVATE_REPO, PRIVATE_REVISION, name, root / "models/recovered-matched" / relative, expected, token)
        receipt.update(status="complete", finished_at=now(), verified_files=len(receipt["files"]))
        save()
        print(json.dumps({"status": "complete", "verified_files": len(receipt["files"])}), flush=True)
    except Exception as exc:
        receipt.update(status="failed", finished_at=now(), error=error_record(exc))
        save()
        print(json.dumps({"status": "failed", "error": error_record(exc)}), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
