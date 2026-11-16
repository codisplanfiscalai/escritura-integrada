"""Opt-in synthetic 2 GiB SQLite boundary experiment; never reads operational data.

Use --work-parent on a disk with >= 12 GiB free (not a small memory-backed /tmp).
Only JSON metrics remain; temporary databases and in-memory test key are discarded.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import backup_archive as archive, backup_crypto as crypto
from app.core import DomainError
from app.db import Database

MIB = 1024 * 1024


def payload_hash(path):
    digest = hashlib.sha256()
    total = 0
    with closing(sqlite3.connect(path)) as conn:
        for (row_id,) in conn.execute('SELECT id FROM synthetic_payload ORDER BY id'):
            with conn.blobopen('synthetic_payload', 'content', row_id, readonly=True) as blob:
                while block := blob.read(MIB):
                    total += len(block)
                    digest.update(block)
    return total, digest.hexdigest()


def fixture(path):
    """Allocate real SQLite pages, not a sparse file with a forged header."""
    with closing(sqlite3.connect(path)) as conn:
        conn.execute('PRAGMA journal_mode=DELETE')
        conn.execute('PRAGMA cache_size=-8192')
        page_size = conn.execute('PRAGMA page_size').fetchone()[0]
        pages = archive.MAX_DATABASE // page_size
        conn.execute(f'PRAGMA max_page_count={pages}')
        conn.execute('CREATE TABLE synthetic_payload(id INTEGER PRIMARY KEY, content BLOB)')
        conn.commit()
        while True:
            current = conn.execute('PRAGMA page_count').fetchone()[0]
            if current == pages:
                break
            remaining = pages - current
            amount = min(8 * MIB, max(1024, (remaining - 16) * page_size))
            try:
                conn.execute('INSERT INTO synthetic_payload(content) VALUES(zeroblob(?))', (amount,))
                conn.commit()
            except sqlite3.OperationalError as error:
                conn.rollback()
                raise RuntimeError(f'Could not reach exact boundary: {current}/{pages} pages') from error
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert path.stat().st_size == archive.MAX_DATABASE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-parent', required=True, type=Path)
    args = parser.parse_args()
    free = shutil.disk_usage(args.work_parent).free
    if free < 12 * 1024**3:
        raise SystemExit(f'Refused: {free} bytes free; require at least 12 GiB.')
    result = {'ok': False, 'free_bytes_before': free, 'database_limit_bytes': archive.MAX_DATABASE,
              'encrypted_limit_bytes': archive.MAX_BYTES, 'fixture': 'allocated SQLite, zero-filled synthetic BLOBs'}
    with tempfile.TemporaryDirectory(prefix='backup-2gib-synthetic-', dir=args.work_parent) as temporary:
        root = Path(temporary)
        db = Database(root / 'data')
        start = time.monotonic()
        fixture(db.path)
        result['fixture_seconds'] = round(time.monotonic() - start, 3)
        result['source_bytes'] = db.path.stat().st_size
        before = archive.sha256(db.path)
        logical_before = payload_hash(db.path)
        secret = crypto.Secret('raw', os.urandom(32))
        encrypted = root / 'fixture.eibk'
        start = time.monotonic()
        checksum = crypto.build(db.path, encrypted, 'synthetic-2gib', secret)
        result['build_seconds'] = round(time.monotonic() - start, 3)
        result['encrypted_bytes'] = encrypted.stat().st_size
        with encrypted.open('rb') as stream:
            result['compressed_bytes'] = crypto._header(stream)[0]['bytes']
        assert encrypted.stat().st_size <= archive.MAX_BYTES
        destination = root / 'restored'
        start = time.monotonic()
        manifest = crypto.restore(encrypted, destination, checksum, secret=secret)
        result['restore_seconds'] = round(time.monotonic() - start, 3)
        restored = destination / 'escritura.sqlite3'
        assert archive.sha256(restored) == manifest['files']['escritura.sqlite3']['sha256']
        assert payload_hash(restored) == logical_before
        assert archive.sha256(db.path) == before
        result.update(payload_bytes=logical_before[0], payload_sha256=logical_before[1],
                      encrypted_sha256=checksum, restored_bytes=restored.stat().st_size,
                      manifest_sha256_verified=True, source_unchanged=True, payload_verified=True)
        try:
            crypto.restore(encrypted, destination, checksum, secret=secret)
        except FileExistsError:
            result['existing_destination_refused'] = True
        else:
            raise AssertionError('Existing destination overwritten')
        assert archive.sha256(restored) == manifest['files']['escritura.sqlite3']['sha256']
        # A real extra SQLite page must be refused before copying, without changing the limit.
        with closing(sqlite3.connect(db.path)) as conn:
            conn.execute('PRAGMA max_page_count=1073741823')
            conn.execute('CREATE TABLE over_boundary(value TEXT)')
            conn.commit()
        assert db.path.stat().st_size > archive.MAX_DATABASE
        try:
            crypto.build(db.path, root / 'refused.eibk', 'synthetic-2gib', secret)
        except DomainError as error:
            assert error.code == 'backup_size'
            result['over_boundary_bytes'] = db.path.stat().st_size
        else:
            raise AssertionError('Oversized database accepted')
        assert not (root / 'refused.eibk').exists()
        assert not list(root.glob('.encrypt-*')) and not list(root.glob('.snapshot-*'))
        result['oversized_refused_without_partial_output'] = True
    # Incompressible data can hit the envelope budget well below the SQLite limit.
    with tempfile.TemporaryDirectory(prefix='backup-oversize-synthetic-', dir=args.work_parent) as temporary:
        random_root = Path(temporary)
        random_db = Database(random_root / 'data')
        with closing(sqlite3.connect(random_db.path)) as conn:
            conn.execute('PRAGMA journal_mode=DELETE')
            conn.execute('CREATE TABLE synthetic_random(id INTEGER PRIMARY KEY, content BLOB)')
            for _ in range(520):
                conn.execute('INSERT INTO synthetic_random(content) VALUES(?)', (os.urandom(MIB),))
            conn.commit()
        before = archive.sha256(random_db.path)
        start = time.monotonic()
        try:
            crypto.build(random_db.path, random_root / 'refused.eibk', 'synthetic-random', secret)
        except DomainError as error:
            assert error.code == 'backup_size'
        else:
            raise AssertionError('Incompressible oversize archive accepted')
        assert archive.sha256(random_db.path) == before
        assert not (random_root / 'refused.eibk').exists()
        assert not list(random_root.glob('.encrypt-*')) and not list(random_root.glob('.snapshot-*'))
        result['incompressible_case'] = {'payload_mib': 520, 'database_bytes': random_db.path.stat().st_size,
                                       'refused': 'backup_size', 'partial_output_removed': True,
                                       'source_unchanged': True, 'seconds': round(time.monotonic() - start, 3)}
    result.update(ok=True, synthetic_workspace_removed=not root.exists() and not random_root.exists(),
                  free_bytes_after=shutil.disk_usage(args.work_parent).free)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
