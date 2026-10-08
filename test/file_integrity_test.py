import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'training'))
import file_integrity as integrity


class ClosedFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'input'
        self.path.write_bytes(b'closed input')
        self.initial = integrity.snapshot(self.path)

    def test_metadata_only(self):
        self.path.chmod(0o400)
        os.utime(self.path, ns=(1, 2))
        self.initial.verify(self.path)

    def test_same_size_rewrite_with_restored_mtime(self):
        old = self.path.stat()
        self.path.write_bytes(b'X' * old.st_size)
        os.utime(self.path, ns=(old.st_atime_ns, old.st_mtime_ns))
        with self.assertRaises(integrity.IntegrityError) as caught:
            integrity.verify_inputs({self.path: self.initial}, 'after_generation')
        self.assertEqual(caught.exception.diagnostic,
                         {'reason': 'content', 'input_index': 0, 'phase': 'after_generation'})

    def test_same_bytes_new_inode(self):
        replacement = self.path.with_name('replacement')
        replacement.write_bytes(self.path.read_bytes())
        replacement.replace(self.path)
        with self.assertRaisesRegex(integrity.IntegrityError, 'identity'):
            self.initial.verify(self.path)

    def test_symlink(self):
        old = self.path.with_name('old')
        self.path.rename(old)
        self.path.symlink_to(old)
        with self.assertRaisesRegex(integrity.IntegrityError, 'not_regular'):
            self.initial.verify(self.path)

    def test_fifo_never_blocks(self):
        self.path.unlink()
        os.mkfifo(self.path)
        with self.assertRaisesRegex(integrity.IntegrityError, 'not_regular'):
            integrity.snapshot(self.path)

    def test_replacement_during_hash(self):
        real = hashlib.sha256
        path = self.path
        class ReplacingHash:
            def __init__(self):
                self.hash = real()
            def update(self, block):
                self.hash.update(block)
                replacement = path.with_name('replacement')
                replacement.write_bytes(block)
                replacement.replace(path)
            def hexdigest(self):
                return self.hash.hexdigest()
        with patch.object(integrity.hashlib, 'sha256', ReplacingHash):
            with self.assertRaisesRegex(integrity.IntegrityError, 'identity'):
                integrity.snapshot(path)

    def test_expected_bytes(self):
        with self.assertRaisesRegex(integrity.IntegrityError, 'content'):
            integrity.snapshot(self.path, {'bytes': self.initial.size, 'sha256': '0' * 64})

    def test_diagnostic_closed_schema(self):
        error = integrity.IntegrityError('content', 'secret', '/private/token')
        self.assertEqual(error.diagnostic, {'reason': 'content'})
        with self.assertRaises(ValueError):
            integrity.IntegrityError('/private/token')


if __name__ == '__main__':
    unittest.main()
