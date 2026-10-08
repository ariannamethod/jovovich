"""Independent, network-free fault injection for the durable archive contract."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import traceback
import types


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "training"))
import durable_archive as archive_module

ArchiveError = archive_module.ArchiveError
DurableArchive = archive_module.DurableArchive


def check(condition, message):
    # This fixture must keep its own checks when launched with python -O.
    if not condition:
        raise RuntimeError(message)


def rejected(call, message):
    try:
        call()
    except ArchiveError:
        return
    raise RuntimeError(message)


class FakeTransport:
    """Immutable revisions and server-side CAS; no archive implementation reused."""
    def __init__(self):
        self.revisions = {"0" * 40: {}}
        self.current = "0" * 40
        self.private = True
        self.commits = 0
        self.downloads = []
        self.before_commit = None
        self.after_commit = None
        self.download_fault = None
        self.head_fault = None

    def head(self):
        if self.head_fault:
            raise self.head_fault
        if not self.private:
            raise ArchiveError("remote repository is public")
        return self.current

    def inventory(self, revision, prefix):
        return {name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                       "git_blob_sha1": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}
                for name, data in self.revisions[revision].items() if name.startswith(prefix)}

    def download(self, remote_path, revision, destination):
        self.downloads.append((revision, remote_path))
        try:
            data = self.revisions[revision][remote_path]
        except KeyError:
            raise ArchiveError("remote file missing") from None
        if self.download_fault:
            data = self.download_fault(remote_path, data)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)

    def commit(self, files, parent, message):
        if self.before_commit:
            action, self.before_commit = self.before_commit, None
            action(files)
        if parent != self.current:
            raise ArchiveError("remote parent conflict")
        snapshot = dict(self.revisions[parent])
        snapshot.update({name: Path(local).read_bytes() for name, local in files.items()})
        self.commits += 1
        revision = f"{self.commits:040x}"
        self.revisions[revision] = snapshot
        self.current = revision
        if self.after_commit:
            action, self.after_commit = self.after_commit, None
            action(revision)
        return revision


def source(directory, name="weights.bin", data=b"closed checkpoint\x00\xff"):
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def payload_path(remote, payload):
    matches = [name for name, data in remote.revisions[remote.current].items() if data == payload]
    check(len(matches) == 1, "expected one remote payload")
    return matches[0]


def normal(directory):
    remote = FakeTransport()
    local = source(directory)
    expected = local.read_bytes()
    archive = DurableArchive(remote, "normal")
    receipt = archive.sync_unit("000", {"weights.bin": local}, sequence=0)
    check(remote.commits == 1, "unit was not atomic")
    check(hashlib.sha256(expected).hexdigest() in json.dumps(receipt), "receipt lacks payload identity")
    check(any(name == payload_path(remote, expected) for _, name in remote.downloads), "payload never read back")
    count = remote.commits
    archive.sync_unit("000", {"weights.bin": local}, sequence=0)
    check(remote.commits == count, "same unit retry created another commit")
    local.write_bytes(b"different checkpoint")
    rejected(lambda: archive.sync_unit("000", {"weights.bin": local}, sequence=0), "same unit accepted different bytes")
    check(remote.commits == count, "mismatching retry overwrote immutable unit")


def lost_ack(directory):
    remote = FakeTransport()
    local = source(directory)
    archive = DurableArchive(remote, "lost-ack")
    def disconnect(_):
        raise ArchiveError("connection closed after server accepted commit")
    remote.after_commit = disconnect
    try:
        archive.sync_unit("000", {"weights.bin": local}, sequence=0)
    except ArchiveError:
        pass
    check(remote.commits == 1, "server did not receive interrupted commit")
    receipt = DurableArchive(remote, "lost-ack").sync_unit("000", {"weights.bin": local}, sequence=0)
    check(remote.commits == 1, "lost-ACK retry duplicated commit")
    check(hashlib.sha256(local.read_bytes()).hexdigest() in json.dumps(receipt), "retry lacks verified identity")


def remote_damage(directory, missing=False):
    remote = FakeTransport()
    local = source(directory)
    expected = local.read_bytes()
    archive = DurableArchive(remote, "damage")
    archive.sync_unit("000", {"weights.bin": local}, sequence=0)
    name = payload_path(remote, expected)
    if missing:
        del remote.revisions[remote.current][name]
    else:
        remote.revisions[remote.current][name] = b"X" * len(expected)
    rejected(lambda: archive.sync_unit("000", {"weights.bin": local}, sequence=0), "retry accepted damaged remote bytes")
    rejected(lambda: archive.recover(directory / "recovered"), "recovery accepted damaged remote bytes")
    check(remote.commits == 1, "damage was silently overwritten")


def corrupt_readback(directory):
    remote = FakeTransport()
    local = source(directory)
    expected = local.read_bytes()
    archive = DurableArchive(remote, "corrupt-transfer")
    remote.download_fault = lambda _, data: b"X" * len(data) if data == expected else data
    rejected(lambda: archive.sync_unit("000", {"weights.bin": local}, sequence=0), "upload success bypassed byte verification")
    check(remote.commits == 1, "fault did not happen after commit")
    remote.download_fault = None
    archive.sync_unit("000", {"weights.bin": local}, sequence=0)
    check(remote.commits == 1, "verification retry re-uploaded unit")


def local_loss(directory):
    remote = FakeTransport()
    workspace = directory / "ephemeral"
    first = source(workspace, "weights.bin", b"checkpoint one\x00")
    second = source(workspace, "segment.jsonl", b'{"loss":1.0}\n')
    expected = [first.read_bytes(), second.read_bytes()]
    archive = DurableArchive(remote, "reconstruct")
    archive.sync_unit("000", {"weights.bin": first}, sequence=0)
    archive.sync_unit("001", {"logs/segment.jsonl": second}, sequence=1)
    del archive
    shutil.rmtree(workspace)
    # Only the transport and run ID survive. No local receipt/cache is available.
    destination = directory / "new-pod"
    DurableArchive(remote, "reconstruct").recover(destination)
    recovered = [p.read_bytes() for p in destination.rglob("*") if p.is_file()]
    check(all(data in recovered for data in expected), "local loss prevented byte-exact reconstruction")
    check(remote.commits == 2, "recovery wrote new remote history")


def parent_conflict(directory):
    remote = FakeTransport()
    first = source(directory, "a.bin", b"worker A")
    second = source(directory, "b.bin", b"worker B")
    left, right = DurableArchive(remote, "concurrent-a"), DurableArchive(remote, "concurrent-b")
    remote.before_commit = lambda _: right.sync_unit("001", {"b.bin": second}, sequence=0)
    try:
        left.sync_unit("000", {"a.bin": first}, sequence=0)
    except ArchiveError:
        pass
    left.sync_unit("000", {"a.bin": first}, sequence=0)
    payloads = remote.revisions[remote.current].values()
    check(first.read_bytes() in payloads and second.read_bytes() in payloads, "CAS retry lost another writer's unit")
    check(remote.commits == 2, "concurrency produced duplicate commits")


def unsafe_paths(directory):
    remote = FakeTransport()
    local = source(directory)
    archive = DurableArchive(remote, "paths")
    for name in ["../escape", "/absolute", "a/../../escape", "a\\escape", "", ".", "a//b", "a/./b", "x\x00y",
                 "_durable-recovery.json", "_durable-recovery.json/child"]:
        rejected(lambda name=name: archive.sync_unit("000", {name: local}, sequence=0), "unsafe artifact name accepted: " + repr(name))
    for run_id in ["../escape", "/absolute", "a/b", "a\\b", ""]:
        rejected(lambda run_id=run_id: DurableArchive(remote, run_id), "unsafe run ID accepted: " + repr(run_id))
    check(remote.commits == 0, "unsafe path reached remote commit")


def source_mutation(directory):
    remote = FakeTransport()
    local = source(directory)
    original = local.read_bytes()
    archive = DurableArchive(remote, "mutation")
    remote.before_commit = lambda _: local.write_bytes(b"mutated producer output")
    try:
        receipt = archive.sync_unit("000", {"weights.bin": local}, sequence=0)
    except ArchiveError:
        return
    # Immutable staging is also valid, but a receipt must describe the original
    # closed snapshot and remote bytes, never silently adopt a moving source.
    check(original in remote.revisions[remote.current].values(), "moving source was uploaded without immutable staging")
    check(hashlib.sha256(original).hexdigest() in json.dumps(receipt), "receipt did not bind original snapshot")


def source_metadata(directory):
    # Change real filesystem timestamps without changing inode, size or bytes.
    # Cover every remote-facing window and the all-empty stderr-segment case.
    for point in ('after-copy', 'head', 'commit', 'readback'):
        for empty in (False, True):
            remote = FakeTransport()
            local = source(directory, point + str(empty), b'' if empty else b'closed bytes')
            original, before = local.read_bytes(), archive_module._source_stat(local)
            def touch():
                value = local.stat()
                os.utime(local, ns=(value.st_atime_ns, value.st_mtime_ns + 1000000))
                local.chmod(0o600)
            real_copy, real_head = archive_module.shutil.copyfile, remote.head
            if point == 'after-copy':
                def copy(src, dst, **kwargs):
                    result = real_copy(src, dst, **kwargs)
                    if Path(src) == local:
                        touch()
                    return result
                archive_module.shutil.copyfile = copy
            elif point == 'head':
                def head():
                    touch()
                    return real_head()
                remote.head = head
            elif point == 'commit':
                remote.before_commit = lambda _: touch()
            else:
                def readback(path, data):
                    touch()
                    return data
                remote.download_fault = readback
            try:
                receipt = DurableArchive(remote, point + str(empty)).sync_unit(
                    '000', {'closed.bin': local}, sequence=0)
            finally:
                archive_module.shutil.copyfile = real_copy
            after = archive_module._source_stat(local)
            check(before[:3] == after[:3] and before[3:] != after[3:], 'metadata injection did not execute')
            check(receipt['verified_remote_bytes'] and local.read_bytes() == original and
                  original in remote.revisions[remote.current].values(), 'metadata drift lost exact bytes')


def source_identity(directory):
    for kind in ('replacement', 'symlink', 'replacement-during-hash', 'symlink-during-hash'):
        remote, local = FakeTransport(), source(directory, kind)
        original, real_digest = local.read_bytes(), archive_module._digest
        replacement = source(directory, kind + '-target', original)
        def replace():
            if kind.startswith('symlink'):
                local.unlink()
                local.symlink_to(replacement)
            else:
                replacement.replace(local)
        if kind.endswith('during-hash'):
            armed = [False]
            original_head = remote.head
            def head():
                armed[0] = True
                return original_head()
            remote.head = head
            def digest(path):
                result = real_digest(path)
                if Path(path) == local and armed[0]:
                    armed[0] = False
                    replace()
                return result
            archive_module._digest = digest
        else:
            remote.before_commit = lambda _: replace()
        archive = DurableArchive(remote, kind)
        try:
            try:
                archive.sync_unit('000', {'closed.bin': local}, sequence=0)
            except ArchiveError as exc:
                expected = 'not_regular' if kind.startswith('symlink') else 'identity'
                check(exc.diagnostic['source_mismatch'] == expected and
                      exc.diagnostic['source_index'] == 0 and not exc.diagnostic['retryable'],
                      'source replacement lost bounded identity diagnosis')
            else:
                raise RuntimeError('same-byte replacement received an ACK: ' + kind)
        finally:
            archive_module._digest = real_digest
        check(archive._pending == (0, '000'), 'source replacement unlocked the next unit')


def source_content(directory):
    for point in ('after-copy', 'head', 'commit'):
        remote, local = FakeTransport(), source(directory, point)
        original, value = local.read_bytes(), local.stat()
        def mutate():
            local.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            os.utime(local, ns=(value.st_atime_ns, value.st_mtime_ns))
        real_copy, real_head = archive_module.shutil.copyfile, remote.head
        if point == 'after-copy':
            def copy(src, dst, **kwargs):
                result = real_copy(src, dst, **kwargs)
                if Path(src) == local:
                    mutate()
                return result
            archive_module.shutil.copyfile = copy
        elif point == 'head':
            def head():
                mutate()
                return real_head()
            remote.head = head
        else:
            remote.before_commit = lambda _: mutate()
        archive = DurableArchive(remote, point)
        try:
            try:
                archive.sync_unit('000', {'closed.bin': local}, sequence=0)
            except ArchiveError as exc:
                phases = {'after-copy': 'after_staging', 'head': 'before_commit', 'commit': 'after_readback'}
                check(exc.diagnostic['source_mismatch'] == 'content' and
                      exc.diagnostic['source_phase'] == phases[point] and
                      exc.diagnostic['source_index'] == 0, 'content mutation lost its exact phase')
            else:
                raise RuntimeError('same-size mutation with restored mtime received an ACK')
        finally:
            archive_module.shutil.copyfile = real_copy
        check(local.stat().st_mtime_ns == value.st_mtime_ns and
              archive._pending == (0, '000'), 'mutation fixture did not preserve mtime or gate')
        check(remote.commits == (1 if point == 'commit' else 0), 'content mutation crossed the wrong commit boundary')


def source_diagnostic(directory):
    secret = 'hf_SYNTHETIC_SOURCE_SECRET /private/file'
    for fields in (
            {'source_index': True, 'source_phase': 'retry', 'source_mismatch': 'content'},
            {'source_index': 1000000, 'source_phase': 'retry', 'source_mismatch': 'content'},
            {'source_index': 0, 'source_phase': secret, 'source_mismatch': 'content'},
            {'source_index': 0, 'source_phase': 'retry', 'source_mismatch': [secret]},
            {'source_index': 0, 'source_phase': 'retry', 'source_mismatch': 'content ' + secret}):
        error = ArchiveError('unused', diagnostic={**fields, 'path': secret})
        check(not any(k.startswith('source_') for k in error.diagnostic) and
              secret not in json.dumps(error.diagnostic), 'unbounded source detail escaped sanitization')
    remote = FakeTransport()
    first, second = source(directory, 'first'), source(directory, 'second')
    remote.before_commit = lambda _: second.write_bytes(b'changed')
    try:
        DurableArchive(remote, 'source-index').sync_unit('000',
            {'z-last.bin': second, 'a-first.bin': first}, sequence=0)
    except ArchiveError as exc:
        check(exc.diagnostic['source_index'] == 1 and
              str(directory) not in json.dumps(exc.diagnostic), 'source index was not sorted or leaked a path')
    else:
        raise RuntimeError('source-index mutation accepted')


def privacy(directory):
    remote = FakeTransport()
    remote.private = False
    local = source(directory)
    archive = DurableArchive(remote, "privacy")
    rejected(lambda: archive.sync_unit("000", {"weights.bin": local}, sequence=0), "public destination accepted")
    check(remote.commits == 0, "public destination received checkpoint")


def auth_redaction(directory):
    remote = FakeTransport()
    local = source(directory)
    secret = "hf_SYNTHETIC_AUDIT_TOKEN_NEVER_REAL"
    remote.head_fault = RuntimeError("Authorization: Bearer " + secret)
    try:
        DurableArchive(remote, "redaction").sync_unit("000", {"weights.bin": local}, sequence=0)
    except ArchiveError:
        check(secret not in traceback.format_exc(), "transport credential leaked through exception chain")
        return
    raise RuntimeError("credential-bearing transport failure was not blocked")


def sequence_gate(directory):
    remote = FakeTransport()
    local = source(directory)
    archive = DurableArchive(remote, "sequence")
    rejected(lambda: archive.sync_unit("001", {"weights.bin": local}, sequence=1), "initial sequence gap accepted")
    archive = DurableArchive(remote, "sequence")
    archive.sync_unit("000", {"weights.bin": local}, sequence=0)
    rejected(lambda: archive.sync_unit("other", {"weights.bin": local}, sequence=0), "duplicate sequence with new ID accepted")
    archive = DurableArchive(remote, "sequence")
    rejected(lambda: archive.sync_unit("002", {"weights.bin": local}, sequence=2), "later sequence gap accepted")
    check(remote.commits == 1, "invalid sequence reached commit")


def verification_barrier(directory):
    remote = FakeTransport()
    local = source(directory)
    archive = DurableArchive(remote, "barrier")
    expected = local.read_bytes()
    remote.download_fault = lambda _, data: b"X" * len(data) if data == expected else data
    rejected(lambda: archive.sync_unit("000", {"weights.bin": local}, sequence=0), "readback fault was ignored")
    rejected(lambda: archive.sync_unit("001", {"next.bin": local}, sequence=1), "next unit advanced past failed verification")
    check(remote.commits == 1, "unverified prior unit allowed new remote commit")
    remote.download_fault = None
    archive.sync_unit("000", {"weights.bin": local}, sequence=0)
    archive.sync_unit("001", {"next.bin": local}, sequence=1)
    check(remote.commits == 2, "verified retry did not unblock exactly one next unit")


def hf_transport_contract(directory):
    """Exercise real HFTransport with a stub SDK, without network or credentials."""
    token = "hf_SYNTHETIC_TRANSPORT_TOKEN_NEVER_REAL"
    calls = []
    settings = {"private": True, "error": False}
    revision = "a" * 40

    class RepoFile:
        def __init__(self, path, size, blob_id, lfs=None):
            self.path, self.size, self.blob_id, self.lfs = path, size, blob_id, lfs

    class Api:
        def __init__(self, **kwargs):
            calls.append(("api", kwargs))

        def repo_info(self, **kwargs):
            calls.append(("info", kwargs))
            if settings["error"]:
                raise RuntimeError("Bearer " + token)
            return types.SimpleNamespace(private=settings["private"], id="owner/private", sha=revision)

        def list_repo_tree(self, **kwargs):
            calls.append(("tree", kwargs))
            return [RepoFile("archive/small", 3, "b" * 40),
                    RepoFile("archive/large", 12, "c" * 40,
                             types.SimpleNamespace(sha256="d" * 64))]

        def create_commit(self, **kwargs):
            calls.append(("commit", kwargs))
            return types.SimpleNamespace(oid="e" * 40)

    def download(**kwargs):
        calls.append(("download", kwargs))
        path = Path(kwargs["cache_dir"]) / "network-bytes"
        path.write_bytes(b"fresh remote payload")
        return str(path)

    hub = types.ModuleType("huggingface_hub")
    hub.__version__ = archive_module.HUB_VERSION
    hub.HfApi = Api
    hub.configure_http_backend = lambda **kwargs: None
    hub.hf_api = types.SimpleNamespace(RepoFile=RepoFile)
    hub.hf_hub_download = download
    hub.CommitOperationAdd = lambda **kwargs: types.SimpleNamespace(**kwargs)
    utilities = types.ModuleType("huggingface_hub.utils")
    utilities.disable_progress_bars = lambda: None
    errors = types.ModuleType("huggingface_hub.errors")
    errors.EntryNotFoundError = type("EntryNotFoundError", (Exception,), {})
    sys.modules.update({"huggingface_hub": hub, "huggingface_hub.utils": utilities,
                        "huggingface_hub.errors": errors})
    transport = archive_module.HFTransport("owner/private", token)
    check(transport.head() == revision, "HF head identity mismatch")
    inventory = transport.inventory(revision, "archive")
    check(inventory["archive/small"]["git_blob_sha1"] == "b" * 40, "ordinary Git hash was lost")
    check(inventory["archive/large"]["sha256"] == "d" * 64, "LFS content hash was lost")
    transport.download("archive/file", revision, directory / "read1")
    transport.download("archive/file", revision, directory / "read2")
    downloads = [args for action, args in calls if action == "download"]
    check(len(downloads) == 2 and downloads[0]["cache_dir"] != downloads[1]["cache_dir"],
          "remote verification reused a local cache")
    check(all(d["revision"] == revision and d["force_download"] is True and
              d["local_files_only"] is False and d["endpoint"] == "https://huggingface.co"
              for d in downloads), "HF verification did not force pinned fresh reads")
    local = source(directory)
    transport.commit({"archive/file": local}, revision, "fixture")
    commit = [args for action, args in calls if action == "commit"][0]
    check(commit["parent_commit"] == revision and commit["revision"] == "main" and
          not commit.get("create_pr", False), "HF commit lacks branch CAS")
    check(calls[0][1]["endpoint"] == "https://huggingface.co", "ambient endpoint may receive credential")
    settings["private"] = False
    for operation in [transport.head, lambda: transport.inventory(revision, "archive"),
                      lambda: transport.download("archive/file", revision, directory / "public-read"),
                      lambda: transport.commit({"archive/file": local}, revision, "fixture")]:
        rejected(operation, "HF transport accepted public repository")
    check(len([1 for action, _ in calls if action == "commit"]) == 1, "public repository received write")
    settings.update(private=True, error=True)
    try:
        transport.head()
    except ArchiveError:
        check(token not in traceback.format_exc(), "HF error exposed authentication")
    else:
        raise RuntimeError("HF error was ignored")



class HTTPError(RuntimeError):
    def __init__(self, status):
        super().__init__('Authorization: Bearer hf_SYNTHETIC_RETRY_SECRET')
        self.response = types.SimpleNamespace(status_code=status,
            text='hf_SYNTHETIC_RETRY_SECRET', url='https://secret.invalid',
            headers={'Authorization': 'hf_SYNTHETIC_RETRY_SECRET'})


class RetryClock:
    def __init__(self):
        self.value, self.sleeps = 0.0, []

    def __call__(self):
        return self.value

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.value += delay


def bounded_sync(archive, local, *, clock=None, deadline=60, attempts=4, callback=None):
    clock = clock or RetryClock()
    return archive_module.sync_unit_with_retry(archive, '000', {'weights.bin': local},
        sequence=0, deadline=deadline, max_attempts=attempts, clock=clock,
        sleep=clock.sleep, on_retry=callback)


def retry_transient(directory):
    wrapped = RuntimeError('hf_SYNTHETIC_RETRY_SECRET LFS upload path')
    wrapped.__cause__ = HTTPError(503)
    for index, error in enumerate([HTTPError(n) for n in (408, 429, 500, 502, 503, 504)] +
                                  [wrapped] +
                                  [ConnectionResetError(104, 'secret'), TimeoutError('secret')]):
        remote, records = FakeTransport(), []
        remote.head_fault = error
        local = source(directory, str(index))
        def callback(record):
            records.append(record)
            remote.head_fault = None
        result = bounded_sync(DurableArchive(remote, 'retry-' + str(index)), local, callback=callback)
        check(result['verified_remote_bytes'] and remote.commits == 1 and len(records) == 1,
              'transient archive failure did not retry exactly once')
        record = records[0]
        check(set(record) == {'attempt', 'next_attempt', 'delay_seconds', 'diagnostic'} and
              record['attempt'] == 1 and record['next_attempt'] == 2 and
              record['diagnostic']['operation'] == 'head' and record['diagnostic']['retryable'],
              'retry callback lacks fixed safe metadata')
        check('secret' not in json.dumps(record).lower(), 'retry callback leaked exception contents')


def retry_commit(directory):
    for mode in ('lost-ack', 'readback', 'cas'):
        remote, local, events = FakeTransport(), source(directory, mode), []
        archive = DurableArchive(remote, mode)
        if mode == 'lost-ack':
            def lost(_):
                raise ConnectionResetError(104, 'credential-containing transport text')
            remote.after_commit = lost
        elif mode == 'readback':
            def disconnected(path, data):
                remote.download_fault = None
                raise TimeoutError('credential-containing transport text')
            remote.download_fault = disconnected
        else:
            other = source(directory, 'other', b'concurrent writer')
            def conflict(_):
                DurableArchive(remote, 'other-writer').sync_unit('000', {'other': other}, sequence=0)
                raise HTTPError(409)
            remote.before_commit = conflict
        result = bounded_sync(archive, local, callback=events.append)
        check(remote.commits == (2 if mode == 'cas' else 1) and len(events) == 1,
              'whole-unit retry duplicated an accepted commit or lost CAS writer')
        check(result['reused'] is (mode != 'cas'), 'ambiguous commit was not discovered on retry')
        check(events[0]['diagnostic']['operation'] == ('download' if mode == 'readback' else 'commit'),
              'retry failure lost the remote operation')
        check(archive._pending is None and archive._operation_deadline is None,
              'successful retry left stale gate/deadline state')


def retry_terminal(directory):
    for index, error in enumerate([HTTPError(n) for n in (400, 401, 403, 404, 409, 422)] +
                                  [RuntimeError('hf_SYNTHETIC_RETRY_SECRET')]):
        remote, events = FakeTransport(), []
        remote.head_fault = error
        try:
            bounded_sync(DurableArchive(remote, 'terminal-' + str(index)),
                         source(directory, str(index)), callback=events.append)
        except ArchiveError as exc:
            check(not exc.diagnostic['retryable'] and exc.diagnostic['attempts'] == 1,
                  'terminal remote failure was classified transient')
            check('SYNTHETIC' not in traceback.format_exc() + json.dumps(exc.diagnostic),
                  'terminal retry error leaked credential text')
        else:
            raise RuntimeError('terminal remote failure accepted')
        check(not events and remote.commits == 0, 'terminal failure retried or committed')
    remote, events = FakeTransport(), []
    remote.download_fault = lambda path, data: data + b'corrupt'
    try:
        bounded_sync(DurableArchive(remote, 'integrity'), source(directory, 'integrity'),
                     callback=events.append)
    except ArchiveError as exc:
        check(exc.diagnostic['operation'] == 'validation' and not exc.diagnostic['retryable'],
              'integrity failure was classified as transport retry')
    else:
        raise RuntimeError('corrupt readback accepted')
    check(remote.commits == 1 and not events, 'integrity failure retried')


def retry_exhaustion(directory):
    remote, clock, events = FakeTransport(), RetryClock(), []
    remote.head_fault = HTTPError(503)
    archive, local = DurableArchive(remote, 'exhaustion'), source(directory)
    try:
        bounded_sync(archive, local, attempts=3, clock=clock, callback=events.append)
    except ArchiveError as exc:
        check(exc.diagnostic['attempts'] == 3 and exc.diagnostic['http_status'] == 503,
              'exhaustion lost attempt count or original status')
    else:
        raise RuntimeError('retry count limit ignored')
    check(len(events) == 2 and clock.sleeps == [1.0, 2.0], 'retry exhaustion exceeded bounded attempts')
    check(archive._pending == (0, '000') and archive._operation_deadline is None,
          'failed retry unlocked unit or retained scoped deadline')
    rejected(lambda: archive.sync_unit('next', {'weights.bin': local}, sequence=1),
             'failed retry allowed the next unit')


def retry_deadline(directory):
    remote, clock, events = FakeTransport(), RetryClock(), []
    remote.head_fault = HTTPError(503)
    try:
        bounded_sync(DurableArchive(remote, 'deadline'), source(directory), clock=clock,
                     deadline=.5, callback=events.append)
    except ArchiveError as exc:
        check(exc.diagnostic['operation'] == 'deadline' and not exc.diagnostic['retryable'] and
              exc.diagnostic['attempts'] == 1, 'deadline failure missing terminal metadata')
    else:
        raise RuntimeError('deadline accepted')
    check(clock.sleeps == [.5] and len(events) == 1 and remote.commits == 0,
          'deadline sleep or retry exceeded the budget')
    # A slow successful remote head must stop before inventory or commit.
    remote, clock = FakeTransport(), RetryClock()
    original = remote.head
    def slow_head():
        clock.value = 3
        return original()
    remote.head = slow_head
    try:
        bounded_sync(DurableArchive(remote, 'late-head'), source(directory, 'late'), clock=clock, deadline=2)
    except ArchiveError as exc:
        check(exc.diagnostic['operation'] == 'deadline', 'late operation lost deadline metadata')
    else:
        raise RuntimeError('late head acknowledged')
    check(remote.commits == 0 and not remote.downloads, 'archive continued after a late remote call')
    # Even a non-DurableArchive caller cannot receive an ACK after its deadline.
    class LateArchive:
        def sync_unit(self, *args, **kwargs):
            clock.value = 9
            return {'verified_remote_bytes': True}
    clock.value = 0
    try:
        bounded_sync(LateArchive(), source(directory, 'late-receipt'), clock=clock, deadline=2)
    except ArchiveError as exc:
        check(exc.diagnostic['operation'] == 'deadline', 'late successful receipt was misclassified')
    else:
        raise RuntimeError('late successful receipt acknowledged')


def retry_immutable(directory):
    remote, local = FakeTransport(), source(directory)
    remote.head_fault = HTTPError(503)
    def changed(_):
        remote.head_fault = None
        local.write_bytes(b'changed between retries')
    try:
        bounded_sync(DurableArchive(remote, 'changed-retry'), local, callback=changed)
    except ArchiveError as exc:
        check(exc.diagnostic['operation'] == 'validation' and not exc.diagnostic['retryable'],
              'changed retry input was not terminal')
    else:
        raise RuntimeError('retry uploaded changed closed unit')
    check(remote.commits == 0, 'retry sent changed bytes to remote')


def retry_source_metadata(directory):
    remote, local, events = FakeTransport(), source(directory), []
    original = local.read_bytes()
    remote.head_fault = HTTPError(503)
    def changed(event):
        events.append(event)
        remote.head_fault = None
        value = local.stat()
        os.utime(local, ns=(value.st_atime_ns, value.st_mtime_ns + 1000000))
        local.chmod(0o600)
    receipt = bounded_sync(DurableArchive(remote, 'metadata-retry'), local, callback=changed)
    check(receipt['verified_remote_bytes'] and len(events) == 1 and remote.commits == 1 and
          original in remote.revisions[remote.current].values(), 'metadata-only retry lost exact bytes')


def retry_source_identity(directory):
    for kind in ('replacement', 'symlink', 'content'):
        remote, local = FakeTransport(), source(directory, kind)
        original, value = local.read_bytes(), local.stat()
        remote.head_fault = HTTPError(503)
        def changed(_):
            remote.head_fault = None
            if kind == 'content':
                local.write_bytes(bytes([original[0] ^ 1]) + original[1:])
                os.utime(local, ns=(value.st_atime_ns, value.st_mtime_ns))
            else:
                target = source(directory, kind + '-target', original)
                if kind == 'symlink':
                    local.unlink()
                    local.symlink_to(target)
                else:
                    target.replace(local)
        try:
            bounded_sync(DurableArchive(remote, kind + '-retry'), local, callback=changed)
        except ArchiveError as exc:
            expected = {'replacement': 'identity', 'symlink': 'not_regular', 'content': 'content'}[kind]
            check(exc.diagnostic['source_mismatch'] == expected and
                  exc.diagnostic['source_phase'] == 'retry' and exc.diagnostic['attempts'] == 2,
                  'retry replacement/content failure lost its diagnosis')
        else:
            raise RuntimeError('changed retry source received an ACK')
        check(remote.commits == 0, 'changed retry source reached remote commit')


def retry_metadata(directory):
    malformed = ArchiveError('unused', diagnostic={
        'operation': ['https://secret.invalid'], 'exception_type': {'Authorization': 'secret'},
        'http_status': True, 'errno': 'secret', 'retryable': True, 'attempts': False,
        'headers': {'Authorization': 'secret'}})
    check(malformed.diagnostic == {'operation': 'validation', 'exception_type': 'Exception',
        'reason_code': None, 'http_status': None, 'errno': None, 'retryable': False, 'attempts': None},
        'diagnostic schema accepted unbounded or credential-bearing values')
    Poison = type('hf_SYNTHETIC_RETRY_SECRET', (RuntimeError,), {})
    remote = FakeTransport()
    remote.head_fault = Poison('hf_SYNTHETIC_RETRY_SECRET')
    try:
        bounded_sync(DurableArchive(remote, 'metadata'), source(directory))
    except ArchiveError as exc:
        check(exc.diagnostic['exception_type'] == 'Exception' and
              'SYNTHETIC' not in traceback.format_exc() + json.dumps(exc.diagnostic),
              'credential-bearing class name escaped safe enum')
    else:
        raise RuntimeError('poison error ignored')
    missing = directory / ('missing-' + 'source')
    try:
        bounded_sync(DurableArchive(FakeTransport(), 'missing-source'), missing)
    except ArchiveError as exc:
        check(exc.diagnostic['operation'] == 'local' and
              exc.diagnostic['exception_type'] == 'FileNotFoundError' and
              str(missing) not in traceback.format_exc(), 'local source error leaked a path')
    else:
        raise RuntimeError('missing retry input accepted')


def retry_validation_reasons(directory):
    # These distinct real invariant failures previously became the same
    # validation/ArchiveError metadata after the bounded sync wrapper.
    for scenario, expected in (
            ('missing-object', 'remote_object_missing_or_changed'),
            ('missing-history', 'previously_verified_unit_missing'),
            ('extra-object', 'unreferenced_or_unexpected_archive_object'),
            ('different-unit', 'unit_already_exists_with_different_content')):
        remote, local = FakeTransport(), source(directory, scenario)
        archive = DurableArchive(remote, scenario)
        bounded_sync(archive, local)
        if scenario == 'missing-object':
            del remote.revisions[remote.current][payload_path(remote, local.read_bytes())]
        elif scenario == 'missing-history':
            remote.inventory = lambda revision, prefix: {}
        elif scenario == 'extra-object':
            remote.revisions[remote.current][archive.prefix + '/objects/' + 'f' * 64] = b'unreferenced'
        else:
            local.write_bytes(b'different closed bytes')
        events = []
        try:
            bounded_sync(archive, local, callback=events.append)
        except ArchiveError as exc:
            check(str(exc) == 'archive synchronization stopped' and
                  exc.diagnostic['reason_code'] == expected and
                  exc.diagnostic['operation'] == 'validation' and
                  not exc.diagnostic['retryable'] and exc.diagnostic['attempts'] == 1,
                  'bounded wrapper lost the distinct validation reason: ' + scenario)
        else:
            raise RuntimeError('invalid archive accepted: ' + scenario)
        check(not events and remote.commits == 1, 'validation diagnostic change retried or committed')

    # Exercise the HF transport's own _need(), then both operation wrappers and
    # the retry wrapper, with no installed HF client, token or network request.
    transport = archive_module.HFTransport.__new__(archive_module.HFTransport)
    transport.repo_id, transport.branch = 'fixture/archive', 'main'
    transport._api = types.SimpleNamespace(repo_info=lambda **kwargs:
        types.SimpleNamespace(private=False, id='fixture/archive', sha='0' * 40))
    try:
        bounded_sync(DurableArchive(transport, 'privacy-reason'), source(directory, 'privacy'))
    except ArchiveError as exc:
        check(exc.diagnostic['reason_code'] == 'archive_repository_must_be_private' and
              exc.diagnostic['attempts'] == 1 and not exc.diagnostic['retryable'],
              'transport operation wrapper lost its validation reason')
    else:
        raise RuntimeError('public archive accepted')


def retry_unknown_reasons(directory):
    secret = 'hf_SYNTHETIC_REASON_SECRET https://secret.invalid/private /private/credential'
    values = ('unknown_reason', 'remote_object_missing_or_changed ' + secret,
              [secret], {'reason_code': secret}, secret)
    for index, reason in enumerate(values):
        remote = FakeTransport()
        remote.head_fault = ArchiveError(secret, diagnostic={
            'operation': 'validation', 'exception_type': 'ArchiveError',
            'reason_code': reason, 'message': secret})
        try:
            bounded_sync(DurableArchive(remote, 'unknown-' + str(index)),
                         source(directory, 'unknown-' + str(index)))
        except ArchiveError as exc:
            check(exc.diagnostic['reason_code'] is None and exc.diagnostic['attempts'] == 1,
                  'unlisted reason entered the diagnostic schema')
            check('SYNTHETIC' not in traceback.format_exc() + json.dumps(exc.diagnostic),
                  'unknown reason leaked through an operation or retry wrapper')
        else:
            raise RuntimeError('unknown validation failure accepted')
    # A known message plus arbitrary suffix must not become an allowed code.
    remote = FakeTransport()
    remote.head_fault = ArchiveError('remote object missing ' + secret)
    try:
        bounded_sync(DurableArchive(remote, 'message-suffix'), source(directory, 'suffix'))
    except ArchiveError as exc:
        check(exc.diagnostic['reason_code'] is None and
              'SYNTHETIC' not in traceback.format_exc() + json.dumps(exc.diagnostic),
              'arbitrary exception text was converted to a reason')
    else:
        raise RuntimeError('unknown exception message accepted')


def training_failure_reason(directory):
    from explanations.run_training import ARCHIVE_CAPABILITY, TrainingError, run_training
    trainer = source(directory, 'protocol-trainer', (
        '#!/usr/bin/env python3\nimport sys\n'
        'if sys.argv[1:] != ["--archive-protocol"]: raise SystemExit(88)\n'
        'print(' + repr(json.dumps(ARCHIVE_CAPABILITY)) + ')\n').encode())
    trainer.chmod(0o755)
    paths = [trainer, source(directory, 'base'), source(directory, 'dataset'), source(directory, 'pairs')]
    plan = {'schema_version': 1, 'run_id': 'failure-reason',
            'argv': [path.name for path in paths[:3]] +
                    ['@RUN@/adapter', '0', '0.0001', '40', '25', 'joint', paths[3].name],
            'bindings': [{'path': path.name, 'bytes': path.stat().st_size,
                          'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths],
            'environment': {'NT_NO_I8': '1'}}
    transport = archive_module.HFTransport.__new__(archive_module.HFTransport)
    transport.repo_id, transport.branch = 'fixture/archive', 'main'
    transport._api = types.SimpleNamespace(repo_info=lambda **kwargs:
        types.SimpleNamespace(private=False, id='fixture/archive', sha='0' * 40))
    output = directory / 'training-failure'
    try:
        run_training(DurableArchive(transport, plan['run_id']), plan, output, repo=directory)
    except TrainingError:
        pass
    else:
        raise RuntimeError('training ignored the archive validation failure')
    failure = json.loads((output / 'failure.json').read_text())
    check(failure['archive_error']['reason_code'] == 'archive_repository_must_be_private' and
          failure['archive_error']['attempts'] == 1 and failure['unit_id'] == 'intent' and
          failure['return_code'] is None, 'real training failure journal lost the validation reason')
    check(not (output / 'stdout.jsonl').exists(), 'training began after failed archive intent')


def hf_request_timeouts(directory):
    observed = []
    class Session:
        def request(self, method, url, **kwargs):
            observed.append(kwargs['timeout'])
            return object()
    request_module = types.ModuleType('requests')
    request_module.Session = Session
    sys.modules['requests'] = request_module
    session = archive_module._hf_session_factory()
    for value in (None, 7, (4, 8), 100, (None, 5), float('inf'), 0):
        session.request('GET', 'https://unused.invalid', timeout=value)
    session.request('POST', 'https://unused.invalid')
    check(observed == [30.0, 7.0, (4.0, 8.0), 30.0, (30.0, 5.0), 30.0, 30.0, 30.0],
          'HF requests lack bounded connect/read timeouts or lost a stricter timeout')


def runner_module():
    sys.path.insert(0, str(REPO / "training" / "layers"))
    import run_layers
    return run_layers


def work_units():
    return [{"id": f"row{i}", "outputs": [f"row{i}.json"]} for i in range(2)]


def work_callback(executed):
    def execute(unit, run_dir):
        executed.append(unit["id"])
        source(run_dir, unit["outputs"][0], json.dumps({"row": unit["id"]}).encode())
        return 0
    return execute


def expect_runner_failure(call):
    try:
        call()
    except (ArchiveError, RuntimeError):
        return
    raise RuntimeError("launcher advanced through injected failure")


def runner_barrier(directory):
    runner = runner_module()
    for fail_at in ["row0.intent", "row0.result"]:
        remote = FakeTransport()
        delegate = DurableArchive(remote, "runner-" + fail_at)
        class FailingArchive:
            def sync_unit(self, unit_id, files, *, sequence):
                if unit_id == fail_at:
                    raise ArchiveError("verification failed")
                return delegate.sync_unit(unit_id, files, sequence=sequence)
        executed = []
        expect_runner_failure(lambda: runner.run_work_units(
            FailingArchive(), work_units(), work_callback(executed), run_dir=directory / fail_at))
        check(executed == ([] if fail_at.endswith(".intent") else ["row0"]), "work launched before its durability barrier")


def runner_lost_ack(directory):
    runner = runner_module()
    remote = FakeTransport()
    delegate = DurableArchive(remote, "runner-recover")
    class LostAckArchive:
        def sync_unit(self, unit_id, files, *, sequence):
            receipt = delegate.sync_unit(unit_id, files, sequence=sequence)
            if unit_id == "row0.result":
                raise ArchiveError("process lost result acknowledgement")
            return receipt
    executed = []
    run_dir = directory / "lost-pod"
    expect_runner_failure(lambda: runner.run_work_units(
        LostAckArchive(), work_units(), work_callback(executed), run_dir=run_dir))
    check(executed == ["row0"], "lost result acknowledgement failed to stop launcher")
    shutil.rmtree(run_dir)
    runner.resume_work_units(DurableArchive(remote, "runner-recover"), work_units(),
                             work_callback(executed), run_dir=run_dir)
    check(executed == ["row0", "row1"], "remote recovery reran a completed callback or skipped next work")
    check(remote.commits == 4, "resume duplicated an intent or result")


def runner_interrupted(directory):
    runner = runner_module()
    remote = FakeTransport()
    delegate = DurableArchive(remote, "runner-interrupted")
    class MissingResultArchive:
        def sync_unit(self, unit_id, files, *, sequence):
            if unit_id == "row0.result":
                raise ArchiveError("pod died before result upload")
            return delegate.sync_unit(unit_id, files, sequence=sequence)
    executed = []
    run_dir = directory / "lost-pod"
    expect_runner_failure(lambda: runner.run_work_units(
        MissingResultArchive(), work_units(), work_callback(executed), run_dir=run_dir))
    shutil.rmtree(run_dir)
    expect_runner_failure(lambda: runner.resume_work_units(
        DurableArchive(remote, "runner-interrupted"), work_units(), work_callback(executed), run_dir=run_dir))
    check(executed == ["row0"], "resume silently repeated or advanced past unknown outcome")
    check(any(b'interrupted' in payload for payload in remote.revisions[remote.current].values()),
          "recovered orphan intent did not preserve interruption evidence")


def runner_preflight(directory):
    runner = runner_module()
    runner.REPO = directory
    local = source(directory, "input.txt", b"frozen source")
    binding = {"path": "input.txt", "snapshot": "source.txt", "bytes": local.stat().st_size,
               "sha256": hashlib.sha256(local.read_bytes()).hexdigest()}
    plan = {"schema_version": 1, "run_id": "preflight", "bindings": [binding],
            "phases": [{"id": "row0", "argv": ["fixture"], "outputs": ["row0.json"]}]}
    runner.validate_plan(plan)
    mutations = [
        lambda p: p.update(environment={"HF_TOKEN": "synthetic-never-real"}),
        lambda p: p["bindings"][0].update(snapshot="plan.json"),
        lambda p: p["bindings"][0].update(snapshot="_units/row0.result.json"),
        lambda p: p["bindings"].append(dict(p["bindings"][0])),
        lambda p: p["phases"][0].update(outputs=["source.txt"]),
        lambda p: p["phases"][0].update(outputs=["plan.json"]),
        lambda p: p["phases"][0].update(outputs=["_units/row0.result.json"]),
        lambda p: p["bindings"][0].update(snapshot="completion.json"),
        lambda p: p["bindings"][0].update(snapshot="_units"),
        lambda p: p["bindings"][0].update(snapshot="_durable-recovery.json"),
        lambda p: p["phases"][0].update(outputs=["completion.json"]),
        lambda p: p["phases"][0].update(outputs=["source.txt/child"]),
        lambda p: p["phases"].append({"id": "row1", "argv": ["fixture"], "outputs": ["row0.json"]}),
    ]
    for mutation in mutations:
        altered = json.loads(json.dumps(plan))
        mutation(altered)
        expect_runner_failure(lambda: runner.validate_plan(altered))


def runner_stale_output(directory):
    runner = runner_module()
    remote = FakeTransport()
    source(directory, "row0.json", b"stale earlier measurement")
    executed = []
    expect_runner_failure(lambda: runner.run_work_units(
        DurableArchive(remote, "stale-output"), work_units(), work_callback(executed), run_dir=directory))
    check(executed == [], "launcher reused or overwrote an already existing measurement")


def runner_symlink(directory):
    runner = runner_module()
    remote = FakeTransport()
    outside = directory / "outside"
    outside.mkdir()
    run_dir = directory / "run"
    def execute(unit, destination):
        (destination / "linked").symlink_to(outside, target_is_directory=True)
        return 0
    expect_runner_failure(lambda: runner.run_work_units(
        DurableArchive(remote, "symlink-output"), [{"id": "row0", "outputs": ["linked"]}],
        execute, run_dir=run_dir))


def runner_failed_work(directory):
    runner = runner_module()
    remote = FakeTransport()
    executed = []
    callback = work_callback(executed)
    def fail(unit, destination):
        callback(unit, destination)
        return 7
    expect_runner_failure(lambda: runner.run_work_units(
        DurableArchive(remote, "failed-work"), work_units(), fail, run_dir=directory / "run"))
    check(executed == ["row0"], "failed callback allowed next callback")
    check(remote.commits == 2, "failed work lost its intent or result")
    records = []
    for payload in remote.revisions[remote.current].values():
        try:
            records.append(json.loads(payload))
        except (ValueError, UnicodeDecodeError):
            pass
    check(any(r.get("status") == "failed" and r.get("return_code") == 7 for r in records),
          "nonzero process result was not preserved remotely")


def runner_validation_failure(directory):
    runner = runner_module()
    remote = FakeTransport()
    run_dir = directory / "run"
    run_dir.mkdir()
    plan = {"schema_version": 1, "run_id": "validation-failed", "bindings": [],
            "phases": [
                {"id": "row0", "outputs": ["features.bin"],
                 "argv": [sys.executable, "-c", "from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(b'collector bytes')", "@RUN@/features.bin"],
                 "check_argv": [sys.executable, "-c", "raise SystemExit(9)"]},
                {"id": "row1", "outputs": ["forbidden.bin"],
                 "argv": [sys.executable, "-c", "from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(b'wrongly advanced')", "@RUN@/forbidden.bin"]},
            ]}
    (run_dir / "plan.json").write_text(json.dumps(plan))
    expect_runner_failure(lambda: runner.execute_plan(
        DurableArchive(remote, "validation-failed"), plan, run_dir, 0))
    check(not (run_dir / "forbidden.bin").exists(), "next native work launched after validator failure")
    record = json.loads((run_dir / "_units/row0.result.json").read_text())
    check(record["status"] == "failed" and [r["return_code"] for r in record["commands"]] == [0, 9],
          "collector/validator results were conflated")
    check(any(payload == (run_dir / "_units/row0.result.json").read_bytes()
              for payload in remote.revisions[remote.current].values()), "validator failure record not remotely durable")


SCENARIOS = {
    "normal": normal,
    "retry-transient": retry_transient,
    "retry-commit": retry_commit,
    "retry-terminal": retry_terminal,
    "retry-exhaustion": retry_exhaustion,
    "retry-deadline": retry_deadline,
    "retry-immutable": retry_immutable,
    "retry-source-metadata": retry_source_metadata,
    "retry-source-identity": retry_source_identity,
    "retry-metadata": retry_metadata,
    "retry-validation-reasons": retry_validation_reasons,
    "retry-unknown-reasons": retry_unknown_reasons,
    "training-failure-reason": training_failure_reason,
    "hf-request-timeouts": hf_request_timeouts,
    "lost-ack": lost_ack,
    "corrupt-remote": remote_damage,
    "missing-remote": lambda directory: remote_damage(directory, missing=True),
    "corrupt-readback": corrupt_readback,
    "local-loss": local_loss,
    "parent-conflict": parent_conflict,
    "unsafe-paths": unsafe_paths,
    "source-mutation": source_mutation,
    "source-metadata": source_metadata,
    "source-identity": source_identity,
    "source-content": source_content,
    "source-diagnostic": source_diagnostic,
    "privacy": privacy,
    "auth-redaction": auth_redaction,
    "sequence-gate": sequence_gate,
    "verification-barrier": verification_barrier,
    "hf-transport-contract": hf_transport_contract,
    "runner-barrier": runner_barrier,
    "runner-lost-ack": runner_lost_ack,
    "runner-interrupted": runner_interrupted,
    "runner-preflight": runner_preflight,
    "runner-stale-output": runner_stale_output,
    "runner-symlink": runner_symlink,
    "runner-failed-work": runner_failed_work,
    "runner-validation-failure": runner_validation_failure,
}


if __name__ == "__main__":
    name = sys.argv[1]
    with tempfile.TemporaryDirectory(prefix="jovovich-durable-audit-") as temporary:
        SCENARIOS[name](Path(temporary))
    print(json.dumps({"scenario": name, "passed": True, "optimization": sys.flags.optimize}))
