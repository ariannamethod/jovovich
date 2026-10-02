"""Independent, network-free fault injection for the durable archive contract."""
from __future__ import annotations

import hashlib
import json
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
    "lost-ack": lost_ack,
    "corrupt-remote": remote_damage,
    "missing-remote": lambda directory: remote_damage(directory, missing=True),
    "corrupt-readback": corrupt_readback,
    "local-loss": local_loss,
    "parent-conflict": parent_conflict,
    "unsafe-paths": unsafe_paths,
    "source-mutation": source_mutation,
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
