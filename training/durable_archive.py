#!/usr/bin/env python3
"""Synchronous, append-only research evidence archiving (no model mathematics).

A returned receipt means the closed unit was downloaded again from a pinned
remote commit and its bytes matched. The caller may then launch the next unit.
The optional HF transport requires huggingface_hub==0.35.3; the core is stdlib.
"""
from __future__ import annotations

import hashlib
import errno
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import time
from typing import Mapping

HUB_VERSION = "0.35.3"
SCHEMA = "jovovich.durable-unit.v1"
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
_CHUNK = 1024 * 1024
_OPERATIONS = frozenset(('validation', 'head', 'inventory', 'download', 'commit',
                         'local', 'recover', 'deadline'))
_ERROR_TYPES = frozenset(('Exception', 'ArchiveError', 'OSError', 'TimeoutError',
    'ConnectionError', 'ConnectionResetError', 'ConnectionRefusedError',
    'ConnectionAbortedError', 'BrokenPipeError', 'FileNotFoundError',
    'PermissionError', 'ValueError', 'RuntimeError', 'HTTPError', 'HfHubHTTPError',
    'Timeout', 'ConnectTimeout', 'ReadTimeout', 'ProxyError', 'SSLError',
    'RepositoryNotFoundError', 'RevisionNotFoundError', 'EntryNotFoundError',
    'LocalEntryNotFoundError', 'BadRequestError', 'GatedRepoError',
    'OfflineModeIsEnabled'))
_TRANSIENT_STATUS = frozenset((408, 429, 500, 502, 503, 504))
_TRANSIENT_ERRNO = frozenset((errno.ECONNRESET, errno.ECONNREFUSED,
    errno.ECONNABORTED, errno.ETIMEDOUT, errno.EPIPE, errno.ENETUNREACH,
    errno.EHOSTUNREACH))


def _safe_diagnostic(value):
    """A closed metadata schema; never copies error text, URLs or headers."""
    value = value if isinstance(value, dict) else {}
    operation = value.get('operation')
    kind, status, number, attempts = (value.get(k) for k in
                                    ('exception_type', 'http_status', 'errno', 'attempts'))
    return {'operation': operation if isinstance(operation, str) and operation in _OPERATIONS else 'validation',
            'exception_type': kind if isinstance(kind, str) and kind in _ERROR_TYPES else 'Exception',
            'http_status': status if type(status) is int and 100 <= status <= 599 else None,
            'errno': number if type(number) is int and 0 < number < 4096 else None,
            'retryable': value.get('retryable') is True and isinstance(operation, str) and operation in
                         ('head', 'inventory', 'download', 'commit'),
            'attempts': attempts if type(attempts) is int and 0 <= attempts <= 8 else None}


class ArchiveError(RuntimeError):
    """A sanitized, fail-closed archive failure; never includes transport text."""

    def __init__(self, message, *, diagnostic=None):
        super().__init__(message)
        self._diagnostic = _safe_diagnostic(diagnostic or
            {'operation': 'validation', 'exception_type': 'ArchiveError'})

    @property
    def diagnostic(self):
        return dict(self._diagnostic)


def _operation_failure(operation, exc):
    if isinstance(exc, ArchiveError):
        return ArchiveError('archive operation failed', diagnostic=exc.diagnostic)
    # requests is optional for the stdlib core, but is installed by the HF client.
    network_types, excluded_types = (ConnectionError, TimeoutError), ()
    try:
        from requests.exceptions import ConnectionError as RequestsConnectionError
        from requests.exceptions import Timeout, SSLError
        network_types += (RequestsConnectionError, Timeout)
        excluded_types = (SSLError,)
    except ImportError:
        pass
    # HF wraps LFS-upload and forced-download failures. Follow only explicit
    # causes, bounded and without ever reading their text or traceback.
    seen = set()
    for _ in range(8):
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        status = status if type(status) is int and 100 <= status <= 599 else None
        number = getattr(exc, 'errno', None)
        number = number if type(number) is int and 0 < number < 4096 else None
        network = isinstance(exc, network_types) and not isinstance(exc, excluded_types)
        cause = exc.__cause__
        if status is not None or number is not None or network or not isinstance(cause, Exception) or id(cause) in seen:
            break
        seen.add(id(exc))
        exc = cause
        if isinstance(exc, ArchiveError):
            return ArchiveError('archive operation failed', diagnostic=exc.diagnostic)
    retryable = (status in _TRANSIENT_STATUS or
                 (operation == 'commit' and status == 409) or
                 (status is None and (network or number in _TRANSIENT_ERRNO)))
    return ArchiveError('archive operation failed', diagnostic={
        'operation': operation, 'exception_type': type(exc).__name__,
        'http_status': status, 'errno': number, 'retryable': retryable})


def sync_unit_with_retry(archive, unit_id, files, *, sequence, deadline,
                         max_attempts=4, clock=time.monotonic, sleep=time.sleep,
                         on_retry=None):
    """Retry the identical closed unit, never native work or a raw commit.

    A commit with a lost response is discovered and read back by sync_unit.
    The absolute monotonic deadline also rejects a late successful receipt.
    It does not cancel a transport call already in progress: transports must
    impose their own finite request timeouts. Callback data is safe to journal.
    """
    _need(type(max_attempts) is int and 1 <= max_attempts <= 8,
          'invalid archive retry count')
    _need(type(deadline) in (int, float) and math.isfinite(deadline),
          'invalid archive retry deadline')
    # Freeze the mapping even if a caller mutates its original dict between tries.
    _need(isinstance(files, Mapping) and files, 'unit must contain files')
    try:
        closed_files = dict(files)
        signatures = {name: (_source_stat(Path(path)), _digest(Path(path)))
                      for name, path in closed_files.items()}
    except Exception as exc:
        raise _operation_failure('local', exc) from None

    def expired(attempt):
        return ArchiveError('archive acknowledgement deadline exceeded', diagnostic={
            'operation': 'deadline', 'exception_type': 'TimeoutError',
            'attempts': attempt})

    previous_deadline = getattr(archive, '_operation_deadline', None)
    archive._operation_deadline = (clock, deadline)
    try:
        for attempt in range(1, max_attempts + 1):
            if clock() >= deadline:
                raise expired(attempt - 1) from None
            try:
                for name, path in closed_files.items():
                    try:
                        signature = (_source_stat(Path(path)), _digest(Path(path)))
                    except Exception as exc:
                        raise _operation_failure('local', exc) from None
                    _need(signature == signatures[name], 'closed unit changed between archive retries')
                receipt = archive.sync_unit(unit_id, closed_files, sequence=sequence)
            except ArchiveError as exc:
                diagnostic = {**exc.diagnostic, 'attempts': attempt}
                if clock() >= deadline:
                    raise expired(attempt) from None
                if not diagnostic['retryable'] or attempt == max_attempts:
                    raise ArchiveError('archive synchronization stopped', diagnostic=diagnostic) from None
                delay = min(float(2 ** (attempt - 1)), max(0.0, deadline - clock()))
                if on_retry is not None:
                    on_retry({'attempt': attempt, 'next_attempt': attempt + 1,
                              'delay_seconds': delay, 'diagnostic': diagnostic})
                sleep(min(delay, max(0.0, deadline - clock())))
                continue
            if clock() >= deadline:
                raise expired(attempt) from None
            return receipt
    finally:
        archive._operation_deadline = previous_deadline


def _need(condition, message):
    if not condition:
        raise ArchiveError(message)


def _name(value):
    _need(isinstance(value, str) and 0 < len(value) <= 512,
          "invalid logical path")
    path = PurePosixPath(value)
    _need(bool(path.parts) and not path.is_absolute() and str(path) == value and
          all(x not in ("", ".", "..") for x in path.parts) and
          all(re.fullmatch(r"[A-Za-z0-9_.-]+", x) for x in path.parts),
          "invalid logical path")
    return value


def _identifier(value):
    _need(isinstance(value, str) and _ID.fullmatch(value), "invalid identifier")
    return value


def _revision(value):
    _need(isinstance(value, str) and _HEX40.fullmatch(value),
          "invalid remote commit")
    return value


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode()


def _digest(path):
    size = path.stat().st_size
    sha = hashlib.sha256()
    git = hashlib.sha1(b"blob " + str(size).encode() + b"\0")
    count = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK), b""):
            count += len(chunk)
            sha.update(chunk)
            git.update(chunk)
    _need(count == size, "file changed while hashing")
    return {"size": size, "sha256": sha.hexdigest(),
            "git_blob_sha1": git.hexdigest()}


def _source_stat(path):
    value = path.lstat()
    _need(stat.S_ISREG(value.st_mode), "source must be a regular non-symlink file")
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_ctime_ns)


def _metadata_matches(meta, entry):
    if not isinstance(meta, dict) or type(meta.get("size")) is not int:
        return False
    if meta["size"] != entry["size"]:
        return False
    sha, git = meta.get("sha256"), meta.get("git_blob_sha1")
    if not sha and not git:
        return False
    return ((not sha or sha == entry["sha256"]) and
            (not git or git == entry["git_blob_sha1"]))


class DurableArchive:
    """Closed-unit archive with an injectable synchronous transport.

    Transport contract:
      head() -> private repository's current full commit SHA
      inventory(revision, prefix) -> {path: {size, sha256?, git_blob_sha1?}}
      download(path, revision, destination: Path) -> fresh remote bytes on disk
      commit(files: dict[str, Path], parent, message) -> atomic CAS commit SHA

    Each call must enforce private-repository access. Inventory fingerprints must
    describe actual contents, not filenames. Transport exceptions are redacted.
    No background worker is used. Sequence numbers start at zero with no gaps.
    """

    def __init__(self, transport, run_id, prefix="experiments/durable-layer-readout"):
        self.transport = transport
        self.run_id = _identifier(run_id)
        self.prefix = _name(prefix) + "/" + self.run_id
        self._known = {}  # unit sequence -> immutable manifest SHA256
        self._manifest_cache = {}  # path -> (verified digest, bytes)
        self._verified_objects = set()
        self._pending = None
        self._operation_deadline = None

    def _check_deadline(self):
        if self._operation_deadline is not None:
            clock, deadline = self._operation_deadline
            if clock() >= deadline:
                raise ArchiveError('archive acknowledgement deadline exceeded', diagnostic={
                    'operation': 'deadline', 'exception_type': 'TimeoutError'})

    def _remote(self, method, *args):
        self._check_deadline()
        try:
            result = getattr(self.transport, method)(*args)
        except Exception as exc:
            raise _operation_failure(method, exc) from None
        self._check_deadline()
        return result

    def _object_path(self, sha):
        return self.prefix + "/objects/" + sha

    def _download_verified(self, remote, revision, entry, directory):
        dest = directory / entry["sha256"]
        self._remote("download", remote, revision, dest)
        _need(dest.is_file() and not dest.is_symlink(), "remote object missing")
        _need(_digest(dest) == {k: entry[k] for k in
                              ("size", "sha256", "git_blob_sha1")},
              "remote object integrity mismatch")
        return dest

    def _history(self, revision, directory, verify_all=False):
        inventory = self._remote("inventory", revision, self.prefix)
        _need(isinstance(inventory, dict), "invalid remote inventory")
        for path in inventory:
            _name(path)
            _need(path.startswith(self.prefix + "/"), "unexpected remote path")
        manifest_paths = sorted(p for p in inventory
                                if p.startswith(self.prefix + "/units/"))
        manifests = []
        previous = None
        ids = set()
        referenced = set()
        logical = {}
        downloaded_objects = set()
        for index, path in enumerate(manifest_paths):
            _need(inventory[path].get("size", 1000001) <= 1000000,
                  "remote manifest exceeds size bound")
            local = directory / ("manifest-%06d.json" % index)
            cached = self._manifest_cache.get(path)
            if cached and _metadata_matches(inventory[path], cached[0]):
                raw = cached[1]
                local.write_bytes(raw)
            else:
                self._remote("download", path, revision, local)
                raw = local.read_bytes()
            _need(len(raw) <= 1000000, "remote manifest exceeds size bound")
            try:
                manifest = json.loads(raw)
            except Exception:
                raise ArchiveError("invalid remote manifest") from None
            _need(isinstance(manifest, dict) and _canonical(manifest) == raw,
                  "noncanonical remote manifest")
            _need(set(manifest) == {"schema", "run_id", "sequence", "unit_id",
                                   "previous_manifest", "parent_revision", "files"},
                  "invalid remote manifest fields")
            _need(manifest["schema"] == SCHEMA and manifest["run_id"] == self.run_id
                  and type(manifest["sequence"]) is int and manifest["sequence"] == index
                  and manifest["previous_manifest"] == previous,
                  "remote manifest chain mismatch")
            unit = _identifier(manifest["unit_id"])
            _revision(manifest["parent_revision"])
            _need(unit not in ids, "duplicate remote unit")
            ids.add(unit)
            _need(path == self.prefix + "/units/%06d-%s.json" % (index, unit),
                  "remote sequence path mismatch")
            entries = manifest["files"]
            _need(isinstance(entries, list) and entries, "empty remote unit")
            names = []
            for entry in entries:
                _need(isinstance(entry, dict) and set(entry) ==
                      {"name", "size", "sha256", "git_blob_sha1", "object"},
                      "invalid remote file entry")
                name = _name(entry["name"])
                _need(name != "_durable-recovery.json" and
                      not name.startswith("_durable-recovery.json/"),
                      "reserved logical path")
                _need(type(entry["size"]) is int and entry["size"] >= 0 and
                      isinstance(entry["sha256"], str) and
                      _HEX64.fullmatch(entry["sha256"]) and
                      isinstance(entry["git_blob_sha1"], str) and
                      _HEX40.fullmatch(entry["git_blob_sha1"]),
                      "invalid remote file digest")
                _need(entry["object"] == self._object_path(entry["sha256"]),
                      "remote object path mismatch")
                _need(name not in logical or logical[name] == entry,
                      "logical path was changed across units")
                logical[name] = entry
                names.append(name)
                referenced.add(entry["object"])
                _need(_metadata_matches(inventory.get(entry["object"]), entry),
                      "remote object missing or changed")
                if entry["sha256"] not in downloaded_objects and (
                        verify_all or entry["sha256"] not in self._verified_objects):
                    self._download_verified(entry["object"], revision, entry, directory)
                    self._verified_objects.add(entry["sha256"])
                    downloaded_objects.add(entry["sha256"])
            _need(names == sorted(set(names)), "duplicate or unordered logical names")
            for a, b in zip(names, names[1:]):
                _need(not b.startswith(a + "/"), "overlapping logical paths")
            digest = hashlib.sha256(raw).hexdigest()
            _need(index not in self._known or self._known[index] == digest,
                  "previously verified unit changed")
            _need(_metadata_matches(inventory[path], _digest(local)),
                  "remote manifest metadata mismatch")
            self._manifest_cache[path] = (_digest(local), raw)
            manifests.append((manifest, digest))
            previous = digest
        all_names = sorted(logical)
        for a, b in zip(all_names, all_names[1:]):
            _need(not b.startswith(a + "/"), "overlapping logical paths across units")
        _need(len(manifests) >= len(self._known), "previously verified unit missing")
        _need(set(inventory) == set(manifest_paths) | referenced,
              "unreferenced or unexpected archive object")
        return manifests, inventory

    def _source_unchanged(self, sources):
        for source, signature, entry in sources:
            _need(_source_stat(source) == signature and _digest(source) ==
                  {key: entry[key] for key in ("size", "sha256", "git_blob_sha1")},
                  "source changed during archive operation")

    def sync_unit(self, unit_id, files: Mapping[str, Path], *, sequence: int):
        """Archive one closed unit; returning is the permission to advance.

        A failed call locks this instance to that sequence/id until an identical
        retry succeeds. Accepted-but-unacknowledged commits are discovered and
        verified on retry. A new instance can resume from remote manifests alone.
        """
        unit = _identifier(unit_id)
        _need(type(sequence) is int and 0 <= sequence < 1000000,
              "invalid unit sequence")
        _need(self._pending in (None, (sequence, unit)),
              "previous unit has not been durably acknowledged")
        _need(isinstance(files, Mapping) and files, "unit must contain files")
        self._pending = (sequence, unit)
        try:
            with tempfile.TemporaryDirectory(prefix="jovovich-archive-") as temp:
                directory = Path(temp)
                staging = directory / "staging"
                staging.mkdir()
                entries, sources, staged = [], [], {}
                names = sorted(_name(x) for x in files)
                for a, b in zip(names, names[1:]):
                    _need(not b.startswith(a + "/"), "overlapping logical paths")
                for index, name in enumerate(names):
                    _need(name != "_durable-recovery.json" and
                          not name.startswith("_durable-recovery.json/"),
                          "reserved logical path")
                    source = Path(files[name])
                    before = _source_stat(source)
                    target = staging / str(index)
                    shutil.copyfile(source, target)
                    digests = _digest(target)
                    entry = {"name": name, **digests,
                             "object": self._object_path(digests["sha256"])}
                    entries.append(entry)
                    sources.append((source, before, entry))
                    staged[entry["object"]] = target
                self._source_unchanged(sources)
                head = _revision(self._remote("head"))
                history, inventory = self._history(head, directory)
                _need(sequence <= len(history), "unit sequence has a gap")
                if sequence < len(history):
                    manifest, manifest_sha = history[sequence]
                    _need(manifest["unit_id"] == unit and manifest["files"] == entries,
                          "unit already exists with different content")
                    for entry in entries:
                        self._download_verified(entry["object"], head, entry, directory)
                    self._source_unchanged(sources)
                    self._known = {i: item[1] for i, item in enumerate(history)}
                    self._pending = None
                    return self._receipt(head, manifest, manifest_sha, True)
                _need(all(item[0]["unit_id"] != unit for item in history),
                      "unit identifier already used")
                previous_files = {f["name"]: f for m, _ in history for f in m["files"]}
                for entry in entries:
                    _need(entry["name"] not in previous_files or
                          previous_files[entry["name"]] == entry,
                          "logical path was changed across units")
                    previous_files[entry["name"]] = entry
                all_names = sorted(previous_files)
                for a, b in zip(all_names, all_names[1:]):
                    _need(not b.startswith(a + "/"), "overlapping logical paths across units")
                manifest = {"schema": SCHEMA, "run_id": self.run_id,
                            "sequence": sequence, "unit_id": unit,
                            "previous_manifest": history[-1][1] if history else None,
                            "parent_revision": head, "files": entries}
                raw = _canonical(manifest)
                _need(len(raw) <= 1000000, "unit manifest exceeds size bound")
                manifest_sha = hashlib.sha256(raw).hexdigest()
                manifest_path = self.prefix + "/units/%06d-%s.json" % (sequence, unit)
                local_manifest = staging / "manifest.json"
                local_manifest.write_bytes(raw)
                additions = {p: f for p, f in staged.items() if p not in inventory}
                additions[manifest_path] = local_manifest
                self._source_unchanged(sources)
                revision = _revision(self._remote("commit", additions, head,
                                                 "Archive closed research unit"))
                # Do not trust the upload response or a cache hit as byte evidence.
                actual = directory / "committed-manifest.json"
                self._remote("download", manifest_path, revision, actual)
                _need(actual.read_bytes() == raw, "committed manifest mismatch")
                for entry in entries:
                    self._download_verified(entry["object"], revision, entry, directory)
                self._source_unchanged(sources)
                self._known = {i: item[1] for i, item in enumerate(history)}
                self._known[sequence] = manifest_sha
                self._manifest_cache[manifest_path] = (_digest(actual), raw)
                self._verified_objects.update(entry["sha256"] for entry in entries)
                self._pending = None
                return self._receipt(revision, manifest, manifest_sha, False)
        except ArchiveError:
            raise
        except Exception as exc:
            raise _operation_failure('local', exc) from None

    def _receipt(self, revision, manifest, sha, reused):
        return {"schema": "jovovich.durable-receipt.v1", "run_id": self.run_id,
                "prefix": self.prefix, "revision": revision,
                "sequence": manifest["sequence"], "unit_id": manifest["unit_id"],
                "manifest_sha256": sha, "files": manifest["files"],
                "verified_remote_bytes": True, "reused": reused}

    def recover(self, destination, revision=None):
        """Restore every unit from remote-only state into a new destination.

        Destination must not exist. Its atomic rename occurs only after the full
        manifest chain and every referenced payload have passed byte checks.
        Restored logical files live directly under destination. The reserved
        _durable-recovery.json records the pinned revision and complete unit list.
        """
        try:
            target = Path(destination)
            _need(not target.exists() and not target.is_symlink(),
                  "recovery destination already exists")
            target.parent.mkdir(parents=True, exist_ok=True)
            head = _revision(self._remote("head") if revision is None else revision)
            with tempfile.TemporaryDirectory(prefix=".jovovich-recover-",
                                             dir=target.parent) as temp:
                directory = Path(temp)
                downloaded = directory / "downloads"
                downloaded.mkdir()
                history, _ = self._history(head, downloaded, verify_all=True)
                _need(history, "remote archive has no closed units")
                restored = directory / "restored"
                restored.mkdir()
                for manifest, sha in history:
                    for entry in manifest["files"]:
                        output = restored / entry["name"]
                        output.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(downloaded / entry["sha256"], output)
                result = {"schema": "jovovich.durable-recovery.v1",
                          "run_id": self.run_id, "prefix": self.prefix,
                          "revision": head, "next_sequence": len(history),
                          "verified_remote_bytes": True,
                          "units": [{"sequence": m["sequence"], "unit_id": m["unit_id"],
                                     "manifest_sha256": sha, "files": m["files"]}
                                    for m, sha in history]}
                (restored / "_durable-recovery.json").write_bytes(_canonical(result))
                _need(not target.exists() and not target.is_symlink(),
                      "recovery destination appeared during restore")
                os.rename(restored, target)
                self._known = {i: item[1] for i, item in enumerate(history)}
                self._pending = None
                return result
        except ArchiveError:
            raise
        except Exception as exc:
            raise _operation_failure('recover', exc) from None


def _bounded_timeout(value):
    def component(item):
        return min(float(item), 30.0) if (type(item) in (int, float) and
            math.isfinite(item) and item > 0) else 30.0
    if isinstance(value, tuple) and len(value) == 2:
        return tuple(component(item) for item in value)
    return component(value)


def _hf_session_factory():
    import requests

    class BoundedSession(requests.Session):
        def request(self, method, url, **kwargs):
            kwargs['timeout'] = _bounded_timeout(kwargs.get('timeout'))
            return super().request(method, url, **kwargs)

    return BoundedSession()


class HFTransport:
    """Private model-repository transport; no token is persisted or logged.

    Existing repository/branch only. Nothing here creates or changes visibility.
    The fixed official endpoint avoids ambient HF_ENDPOINT credential redirects.
    Intended for the dedicated archive parent: configuring the official Hub HTTP
    backend is process-wide. Every requests call, including metadata, pagination
    and commit requests, receives finite connect/read timeouts of at most 30s.
    SDK download retries may span several requests; DurableArchive checks the
    overall acknowledgement deadline between transport operations.
    """

    def __init__(self, repo_id, token, branch="main"):
        _need(isinstance(repo_id, str) and re.fullmatch(
              r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repo_id),
              "invalid repository identifier")
        _name(branch)
        _need(isinstance(token, str) and token.strip() and "\n" not in token,
              "missing archive credential")
        try:
            import huggingface_hub as hub
            _need(hub.__version__ == HUB_VERSION, "unsupported hub client version")
            from huggingface_hub.utils import disable_progress_bars
            disable_progress_bars()
            hub.configure_http_backend(backend_factory=_hf_session_factory)
            self._hub = hub
            self._api = hub.HfApi(endpoint="https://huggingface.co", token=token)
            self._token = token
            self.repo_id, self.branch = repo_id, branch
        except ArchiveError:
            raise
        except Exception:
            raise ArchiveError("pinned research hub client unavailable") from None

    def _private(self, revision):
        info = self._api.repo_info(repo_id=self.repo_id, repo_type="model",
                                   revision=revision, timeout=30)
        _need(info.private is True and info.id == self.repo_id,
              "archive repository must be private")
        sha = _revision(info.sha)
        if _HEX40.fullmatch(revision):
            _need(sha == revision, "remote revision binding mismatch")
        return sha

    def head(self):
        try:
            return self._private(self.branch)
        except Exception as exc:
            raise _operation_failure('head', exc) from None

    def inventory(self, revision, prefix):
        try:
            self._private(_revision(revision))
            _name(prefix)
            from huggingface_hub.errors import EntryNotFoundError
            try:
                values = list(self._api.list_repo_tree(
                    repo_id=self.repo_id, repo_type="model", revision=revision,
                    path_in_repo=prefix, recursive=True))
            except EntryNotFoundError:
                return {}
            result = {}
            for value in values:
                if isinstance(value, self._hub.hf_api.RepoFile):
                    lfs = value.lfs
                    result[value.path] = {"size": value.size,
                                          "sha256": lfs.sha256 if lfs else None,
                                          "git_blob_sha1": None if lfs else value.blob_id}
            return result
        except Exception as exc:
            raise _operation_failure('inventory', exc) from None

    def download(self, path, revision, destination):
        try:
            self._private(_revision(revision))
            _name(path)
            # An empty temporary cache plus force_download disallows cached proof.
            with tempfile.TemporaryDirectory(prefix="jovovich-hf-read-") as cache:
                downloaded = self._hub.hf_hub_download(
                    repo_id=self.repo_id, repo_type="model", filename=path,
                    revision=revision, token=self._token, cache_dir=cache,
                    endpoint="https://huggingface.co", force_download=True,
                    local_files_only=False)
                shutil.copyfile(downloaded, destination)
        except Exception as exc:
            raise _operation_failure('download', exc) from None

    def commit(self, files, parent, message):
        try:
            self._private(self.branch)
            _revision(parent)
            operations = [self._hub.CommitOperationAdd(
                path_in_repo=_name(path), path_or_fileobj=str(local))
                          for path, local in files.items()]
            result = self._api.create_commit(
                repo_id=self.repo_id, repo_type="model", revision=self.branch,
                parent_commit=parent, operations=operations,
                commit_message="Archive closed research unit", num_threads=2)
            return _revision(result.oid)
        except Exception as exc:
            raise _operation_failure('commit', exc) from None
