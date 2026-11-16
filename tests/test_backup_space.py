"""ENOSPC injection on synthetic files; never fills a real volume."""
import errno
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from app import backup_archive as archive, backup_crypto as crypto, backup_workspace as workspace
from app.db import Database


class FullWriter:
    """Write a real partial fragment, then simulate the filesystem refusing more."""
    def __init__(self, stream):
        self.stream = stream
        self.written = False

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def write(self, data):
        if not self.written:
            self.stream.write(data[:min(8, len(data))])
            self.stream.flush()
            self.written = True
        raise OSError(errno.ENOSPC, 'synthetic disk full')


class BackupSpaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='backup-space-synthetic-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = Database(self.root / 'data')
        self.secret = crypto.Secret('raw', os.urandom(32))
        self.before = archive.sha256(self.db.path)
        self.unknown = self.root / 'unknown'
        self.unknown.mkdir()
        (self.unknown / 'keep').write_bytes(b'preserve')

    def assert_preserved(self):
        self.assertEqual(self.before, archive.sha256(self.db.path))
        self.assertEqual(b'preserve', (self.unknown / 'keep').read_bytes())
        for prefix in ('.snapshot-*', '.encrypt-*', '.decrypt-*'):
            self.assertEqual([], list(self.root.glob(prefix)))

    def fail_path(self, target):
        original = Path.open
        def opened(path, mode='r', *args, **kwargs):
            stream = original(path, mode, *args, **kwargs)
            return FullWriter(stream) if path == target and mode == 'xb' else stream
        return patch.object(Path, 'open', opened)

    def test_enospc_mid_zip_removes_partial_output_and_preserves_source(self):
        target = self.root / 'partial.zip'
        with self.fail_path(target):
            with self.assertRaises(OSError) as raised:
                archive.build(self.db.path, target)
        self.assertEqual(errno.ENOSPC, raised.exception.errno)
        self.assertFalse(target.exists())
        self.assert_preserved()

    def test_enospc_mid_encryption_removes_partial_envelope_and_staging(self):
        target = self.root / 'partial.eibk'
        original = os.fdopen
        def opened(fd, mode='r', *args, **kwargs):
            stream = original(fd, mode, *args, **kwargs)
            return FullWriter(stream) if mode == 'wb' else stream
        with patch.object(os, 'fdopen', opened):
            with self.assertRaises(OSError) as raised:
                crypto.build(self.db.path, target, 'synthetic', self.secret)
        self.assertEqual(errno.ENOSPC, raised.exception.errno)
        self.assertFalse(target.exists())
        self.assert_preserved()

    def test_enospc_mid_decryption_removes_plaintext_without_creating_destination(self):
        encrypted = self.root / 'fixture.eibk'
        checksum = crypto.build(self.db.path, encrypted, 'synthetic', self.secret)
        destination = self.root / 'recovery'
        original = os.fdopen
        def opened(fd, mode='r', *args, **kwargs):
            stream = original(fd, mode, *args, **kwargs)
            return FullWriter(stream) if mode == 'wb' else stream
        with patch.object(os, 'fdopen', opened):
            with self.assertRaises(OSError) as raised:
                crypto.restore(encrypted, destination, checksum, secret=self.secret)
        self.assertEqual(errno.ENOSPC, raised.exception.errno)
        self.assertFalse(destination.exists())
        self.assertEqual(checksum, archive.sha256(encrypted))
        self.assert_preserved()

    def test_enospc_mid_extraction_cleans_new_destination_and_allows_retry(self):
        encrypted = self.root / 'fixture.eibk'
        checksum = crypto.build(self.db.path, encrypted, 'synthetic', self.secret)
        destination = self.root / 'recovery'
        with self.fail_path(destination / 'escritura.sqlite3'):
            with self.assertRaises(OSError) as raised:
                crypto.restore(encrypted, destination, checksum, secret=self.secret)
        self.assertEqual(errno.ENOSPC, raised.exception.errno)
        self.assertFalse(destination.exists())
        self.assertEqual(checksum, archive.sha256(encrypted))
        self.assert_preserved()
        manifest = crypto.restore(encrypted, destination, checksum, secret=self.secret)
        self.assertEqual(manifest['files']['escritura.sqlite3']['sha256'],
                         archive.sha256(destination / 'escritura.sqlite3'))
        with self.assertRaises(FileExistsError):
            crypto.restore(encrypted, destination, checksum, secret=self.secret)

    def test_restore_disk_preflight_cleans_destination_without_consuming_archive(self):
        encrypted = self.root / 'fixture.eibk'
        checksum = crypto.build(self.db.path, encrypted, 'synthetic', self.secret)
        destination = self.root / 'recovery'
        with patch.object(archive.shutil, 'disk_usage', return_value=SimpleNamespace(free=1)):
            with self.assertRaisesRegex(ValueError, 'Espaço insuficiente'):
                crypto.restore(encrypted, destination, checksum, secret=self.secret)
        self.assertFalse(destination.exists())
        self.assertEqual(checksum, archive.sha256(encrypted))
        self.assert_preserved()

    def test_managed_cleanup_preserves_unmarked_uuid_and_unknown_directories(self):
        # Caller owns the isolated root; no service/other worker can access this fixture.
        managed = self.root / 'work'
        owned = workspace.create(managed, uuid.uuid4().hex)
        (owned / 'partial.zip').write_bytes(b'synthetic residue')
        unmarked = managed / uuid.uuid4().hex
        unmarked.mkdir()
        (unmarked / 'keep').write_bytes(b'preserve')
        unknown = managed / 'unknown'
        unknown.mkdir()
        (unknown / 'keep').write_bytes(b'preserve')
        self.assertEqual(1, workspace.cleanup(managed))
        self.assertFalse(owned.exists())
        self.assertEqual(b'preserve', (unmarked / 'keep').read_bytes())
        self.assertEqual(b'preserve', (unknown / 'keep').read_bytes())
        self.assertEqual(0, workspace.cleanup(managed))
        self.assert_preserved()


if __name__ == '__main__':
    unittest.main()
