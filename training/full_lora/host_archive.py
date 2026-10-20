#!/usr/bin/env python3
"""Run the trainer behind durable checkpoint ACKs and immutable log chunks."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from durable_archive import DurableArchive, HFTransport, sync_unit_with_retry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--state-dir', required=True, type=Path)
    parser.add_argument('--checkpoint-root', required=True, type=Path)
    parser.add_argument('--token-file', required=True, type=Path)
    parser.add_argument('--repo', default='ataeff/jovovich')
    parser.add_argument('--branch', default='main', help='Existing branch; isolate weights from host-status commits')
    parser.add_argument('--source', action='append', default=[], help='logical-name=path')
    parser.add_argument('--stop-file', type=Path, help='Touch only after the job has closed')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('a trainer command is required')
    args.state_dir.mkdir(parents=True, exist_ok=False)
    root = args.checkpoint_root.resolve()
    archive = DurableArchive(HFTransport(args.repo, args.token_file.read_text().strip(), args.branch),
                             args.run_id, prefix='training/full-lora')
    sequence = 0
    chunk = 0
    pending = []
    last_sync = time.monotonic()
    child = None

    def emit(value):
        print(json.dumps(value, sort_keys=True), flush=True)

    def sync(unit, files):
        nonlocal sequence, last_sync
        receipt = sync_unit_with_retry(archive, unit, files, sequence=sequence,
                                      deadline=time.monotonic() + 900)
        (args.state_dir / f'receipt-{sequence:06d}.json').write_text(json.dumps(receipt, indent=2))
        sequence += 1
        last_sync = time.monotonic()
        emit({'event': 'archive_verified', 'unit': unit, 'receipt': receipt})

    def close_log():
        nonlocal chunk
        if not pending:
            return {}
        name = f'logs/chunk-{chunk:06d}.log'
        path = args.state_dir / f'chunk-{chunk:06d}.log'
        path.write_bytes(b''.join(pending))
        pending.clear()
        chunk += 1
        return {name: path}

    intent = args.state_dir / 'intent.json'
    intent.write_text(json.dumps({'run_id': args.run_id, 'command': command,
        'started_at': time.time(), 'checkpoint_protocol': 'ACK-after-remote-readback',
        'source_cwd': str(Path.cwd())}, indent=2))
    bootstrap = {'intent.json': intent}
    for item in args.source:
        name, path = item.split('=', 1)
        if name in bootstrap:
            raise ValueError('duplicate source name')
        bootstrap[name] = Path(path)
    rc = 1
    try:
        sync('bootstrap', bootstrap)
        env = {k: v for k, v in os.environ.items() if k not in
               ('HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN', 'JOV_HF_TOKEN', 'JOV_RUNPOD_KEY', 'RUNPOD_API_KEY')}
        env['JOVOVICH_REQUIRE_ACK'] = '1'
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, env=env, start_new_session=True)
        lines = queue.Queue()
        def read_lines():
            try:
                for line in iter(child.stdout.readline, b''):
                    lines.put(line)
            finally:
                lines.put(None)
        threading.Thread(target=read_lines, daemon=True).start()
        previous_step = -1
        while True:
            try:
                line = lines.get(timeout=1)
            except queue.Empty:
                if pending and time.monotonic() - last_sync >= 60:
                    sync(f'log-{chunk:06d}', close_log())
                continue
            if line is None:
                break
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
            pending.append(line)
            try:
                event = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                event = {}
            if isinstance(event, dict) and event.get('event') == 'checkpoint':
                step = event.get('step')
                if type(step) is not int or step < 0 or step <= previous_step:
                    raise RuntimeError('unordered checkpoint event')
                original_directory = Path(event['path'])
                if original_directory.is_symlink():
                    raise RuntimeError('checkpoint must not be a symlink')
                directory = original_directory.resolve()
                if directory.parent != root or directory.name != f'step-{step:06d}':
                    raise RuntimeError('checkpoint outside configured output root')
                entries = sorted(directory.iterdir())
                expected = {'optimizer.bin', 'state.json'}
                if len(entries) != 9 or len(list(directory.glob('*.lora'))) != 7 or not expected.issubset(p.name for p in entries):
                    raise RuntimeError('incomplete closed checkpoint')
                files = close_log()
                files.update({f'checkpoints/{directory.name}/{p.name}': p for p in entries})
                sync(f'checkpoint-{step:06d}', files)
                child.stdin.write(f'ACK {step}\n'.encode())
                child.stdin.flush()
                previous_step = step
                emit({'event': 'checkpoint_ack', 'step': step})
            elif pending and time.monotonic() - last_sync >= 60:
                sync(f'log-{chunk:06d}', close_log())
        rc = child.wait()
        if rc == 0 and previous_step < 0:
            raise RuntimeError('trainer exited without a durable checkpoint')
        closed = args.state_dir / 'closed.json'
        closed.write_text(json.dumps({'returncode': rc, 'last_checkpoint_step': previous_step,
                                      'closed_at': time.time()}, indent=2))
        files = close_log()
        files['closed.json'] = closed
        sync('closed', files)
        return rc
    except BaseException as exc:
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        emit({'event': 'host_failure', 'exception_type': type(exc).__name__,
              'diagnostic': getattr(exc, 'diagnostic', None)})
        return 1
    finally:
        if child is not None:
            if child.stdin:
                child.stdin.close()
            if child.stdout:
                child.stdout.close()
        if args.stop_file:
            args.stop_file.touch()

if __name__ == '__main__':
    raise SystemExit(main())
