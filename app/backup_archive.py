"""Versioned, bounded SQLite archives. Never traverse the operational data directory."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import shutil
import time
import zipfile

from . import __version__, backup_platform as platform
from .core import DomainError
from .maintenance import integrity

MAX_BYTES = 512 * 1024 * 1024
MAX_DATABASE = 2 * 1024 * 1024 * 1024


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def build(source, output, cancelled=lambda: False):
    """SQLite online backup includes committed WAL; filesystem caches are regenerable."""
    output = Path(output)
    deadline = time.monotonic() + 300
    page_size = 4096
    def progress(*stats):
        if len(stats) == 3 and stats[2] * page_size > MAX_DATABASE:
            raise DomainError('Banco cresceu além do limite durante a cópia.', 422, 'backup_size')
        if cancelled():
            raise DomainError('Backup cancelado antes do envio.', 409, 'cancelled')
        if time.monotonic() > deadline:
            raise DomainError('Tempo de cópia excedido; banco muito ocupado.', 409, 'snapshot_timeout')
    with platform.temporary_directory(output.parent, '.snapshot-') as work:
        snapshot = Path(work) / 'escritura.sqlite3'
        with closing(sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True)) as src:
            page_size = src.execute('PRAGMA page_size').fetchone()[0]
            source_bytes = src.execute('PRAGMA page_count').fetchone()[0] * page_size
            if source_bytes > MAX_DATABASE:
                raise DomainError('Banco excede o limite de 2 GiB antes da cópia.', 422, 'backup_size')
            if shutil.disk_usage(output.parent).free < source_bytes * 2 + min(source_bytes, MAX_BYTES) + 64*1024*1024:
                raise DomainError('Espaço livre insuficiente para snapshot e verificação.', 409, 'backup_space')
            with closing(sqlite3.connect(snapshot)) as dst:
                src.backup(dst, pages=256, progress=progress, sleep=.05)
                dst.execute('PRAGMA journal_mode=DELETE')
                dst.execute('PRAGMA secure_delete=ON')
                # Authentication sessions must never survive a restore.
                dst.execute('DELETE FROM session_contexts')
                dst.execute('DELETE FROM sessions')
                dst.execute('DELETE FROM login_attempts')
                # Refuse known secret containers rather than silently dropping fiscal originals.
                for row_id, name in dst.execute('SELECT rowid,filename FROM stored_files WHERE content IS NOT NULL'):
                    forbidden = Path(name).suffix.lower() in {'.pfx', '.p12', '.pem', '.key', '.env'}
                    with dst.blobopen('stored_files', 'content', row_id, readonly=True) as content:
                        tail = b''
                        while block := content.read(1024*1024):
                            window = tail + block
                            forbidden |= b'PRIVATE KEY-----' in window or b'CERTIFICATE-----' in window
                            tail = window[-64:]
                            progress()
                    if forbidden:
                        raise DomainError('Original contém certificado ou segredo; revisão local necessária.', 409, 'secret_in_original')
                dst.commit()
                dst.execute('VACUUM')
        snapshot.chmod(0o600)
        info = integrity(snapshot)
        if snapshot.stat().st_size > MAX_DATABASE:
            raise DomainError('Banco excede o limite de 2 GiB desta versão.', 422, 'backup_size')
        manifest = {'format': 1, 'created_at': datetime.now(timezone.utc).isoformat(), 'application_version': __version__, 'schema_version': info['schema_version'],
                    'files': {'escritura.sqlite3': {'sha256': sha256(snapshot), 'bytes': snapshot.stat().st_size}},
                    'scope': 'SQLite com originais canônicos; caches regeneráveis não incluídos',
                    'excluded': ['sessions', 'session_contexts', 'login_attempts', 'backup configuration', 'external credentials', 'filesystem caches']}
        progress()
        class BoundedWriter:
            def __init__(self, raw): self.raw = raw
            def __getattr__(self, name): return getattr(self.raw, name)
            def write(self, data):
                progress()
                if self.raw.tell() + len(data) > MAX_BYTES:
                    raise DomainError(f'Pacote excede {MAX_BYTES // (1024*1024)} MiB; envio não iniciado.', 422, 'backup_size')
                return self.raw.write(data)
        raw = output.open('xb')  # Exclusive creation: never delete a pre-existing file on failure.
        try:
            with raw:
                os.chmod(output, 0o600)
                with zipfile.ZipFile(BoundedWriter(raw), 'w', zipfile.ZIP_DEFLATED) as archive:
                    archive.write(snapshot, 'escritura.sqlite3')
                    archive.writestr('manifest.json', json.dumps(manifest))
                raw.flush(); os.fsync(raw.fileno())
        except Exception:
            output.unlink(missing_ok=True)
            raise
    return sha256(output)


def restore(archive_path, destination, expected_hash=None):
    """Validate into a newly created isolated directory; no extractall or overwrite."""
    archive_path, destination = Path(archive_path), Path(destination)
    if archive_path.stat().st_size > MAX_BYTES or (expected_hash and sha256(archive_path) != expected_hash):
        raise ValueError('Arquivo inválido ou checksum divergente.')
    platform.private_directory(destination)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            if len(entries) != 2 or {e.filename for e in entries} != {'manifest.json', 'escritura.sqlite3'}:
                raise ValueError('Inventário inválido.')
            if archive.getinfo('manifest.json').file_size > 16384 or archive.getinfo('escritura.sqlite3').file_size > MAX_DATABASE:
                raise ValueError('Limite de extração excedido.')
            if shutil.disk_usage(destination.parent).free < archive.getinfo('escritura.sqlite3').file_size + 64*1024*1024:
                raise ValueError('Espaço insuficiente para recuperação isolada.')
            manifest = json.loads(archive.read('manifest.json'))
            if manifest['format'] != 1 or set(manifest['files']) != {'escritura.sqlite3'}:
                raise ValueError('Formato não suportado.')
            path = destination / 'escritura.sqlite3'
            expected = manifest['files'][path.name]
            with archive.open(path.name) as src, path.open('xb') as dst:
                path.chmod(0o600)
                size = 0
                for block in iter(lambda: src.read(1024 * 1024), b''):
                    size += len(block)
                    if size > MAX_DATABASE:
                        raise ValueError('Limite de extração excedido.')
                    dst.write(block)
                dst.flush()
                os.fsync(dst.fileno())
            if size != expected['bytes'] or sha256(path) != expected['sha256']:
                raise ValueError('Checksum divergente.')
            info = integrity(path)
            if info['schema_version'] != manifest['schema_version']:
                raise ValueError('Esquema divergente.')
        return manifest
    except Exception:
        # Only files created by this call, never an existing destination.
        for child in destination.iterdir():
            child.unlink()
        destination.rmdir()
        raise


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Validar e extrair backup para uma pasta nova, sem ativar.')
    parser.add_argument('archive', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--sha256', required=True, help='Checksum externo registrado no histórico')
    args = parser.parse_args()
    restore(args.archive, args.destination, args.sha256)
    print('Cópia validada e extraída; ativação não executada.')
