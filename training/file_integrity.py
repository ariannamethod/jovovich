"""Closed-file identity and byte guards for evaluation on delayed-metadata filesystems."""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat


class IntegrityError(RuntimeError):
    def __init__(self, reason, index=None, phase=None):
        if reason not in ('identity', 'content', 'not_regular', 'unreadable'):
            raise ValueError('invalid integrity reason')
        super().__init__('closed evaluation input changed: ' + reason)
        self.reason, self.index, self.phase = reason, index, phase

    @property
    def diagnostic(self):
        result = {'reason': self.reason}
        if type(self.index) is int and 0 <= self.index < 1000000:
            result['input_index'] = self.index
        if self.phase in ('before_command', 'after_command', 'completion',
                          'before_generation', 'after_tokenization', 'after_generation'):
            result['phase'] = self.phase
        return result


def _identity(value):
    if not stat.S_ISREG(value.st_mode):
        raise IntegrityError('not_regular')
    return value.st_dev, value.st_ino, value.st_size


@dataclass(frozen=True)
class Snapshot:
    identity: tuple
    sha256: str

    @property
    def size(self):
        return self.identity[2]

    def verify(self, path):
        current = snapshot(path)
        if current.identity != self.identity:
            raise IntegrityError('identity')
        if current.sha256 != self.sha256:
            raise IntegrityError('content')


def snapshot(path, expected=None):
    """Hash a regular file through one descriptor; reject replacement while reading.

    Device/inode/length and SHA-256 establish stability. FUSE may finalize mtime
    or ctime after close/fsync, so timestamps are not content identity. Every
    verification rehashes bytes, including same-length rewrites with restored mtime.
    """
    path = Path(path)
    try:
        before = _identity(path.lstat())
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            if _identity(os.fstat(stream.fileno())) != before:
                raise IntegrityError('identity')
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
            if (_identity(os.fstat(stream.fileno())) != before or
                    _identity(path.lstat()) != before):
                raise IntegrityError('identity')
        result = Snapshot(before, digest.hexdigest())
        if expected is not None and (result.size != expected['bytes'] or
                                     result.sha256 != expected['sha256']):
            raise IntegrityError('content')
        return result
    except OSError:
        raise IntegrityError('unreadable') from None


def verify_inputs(tracked, phase):
    """Use a bounded index in the bound-file order, never raw paths in diagnostics."""
    for index, (path, original) in enumerate(tracked.items()):
        try:
            original.verify(path)
        except IntegrityError as error:
            raise IntegrityError(error.reason, index, phase) from None
