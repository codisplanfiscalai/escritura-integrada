"""Fail-closed, schema-preserving Docker update hold. No restore operation exists."""
from __future__ import annotations
from contextlib import closing
from contextvars import ContextVar
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile

MARKER = '.escritura-update-hold.json'
PROTOCOL = 1
DATA_ABI = 'sqlite-schema6-no-data-conversion-v1'
# Only requests admitted before a hold may drain their complete existing flow.
admitted = ContextVar('docker_update_admitted_request', default=False)


class UpdateHeld(RuntimeError):
    pass


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def fingerprint(value):
    return hashlib.sha256(encode(value)).hexdigest()


def hold(data_dir):
    path = Path(data_dir) / MARKER
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size>4096:
        raise UpdateHeld('Marcador de manutenção inválido; recuperação administrativa necessária.')
    try:
        value = json.loads(path.read_text())
        if (type(value) is not dict or value.get('protocol') != PROTOCOL or not re.fullmatch('[a-f0-9]{32}', value.get('job_id', ''))
                or not re.fullmatch('[a-f0-9]{64}', value.get('schema', '')) or not re.fullmatch('[a-f0-9]{64}',value.get('abi',''))):
            raise ValueError('invalid marker')
        return value
    except (ValueError, OSError, TypeError):
        raise UpdateHeld('Marcador de manutenção inválido; recuperação administrativa necessária.') from None


def abi():
    # Conservative equality, including startup/migration entrypoints. A change
    # here blocks the updater; no operator checkbox can bypass incompatibility.
    root = Path(__file__).parent
    sources = []
    for path in sorted(root.rglob('*.py')):
        text = path.read_text()
        if path.name in ('db.py', 'update_guard.py') or re.search(r'^def migrate\w*\(', text, re.M):
            sources.append((str(path.relative_to(root)), hashlib.sha256(path.read_bytes()).hexdigest()))
    return fingerprint({'data_abi': DATA_ABI, 'sources': sources})


def schema(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchone():
            raise UpdateHeld('Banco sem integridade comprovada.')
        version = db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if not version or version[0] != '6':
            raise UpdateHeld('Este protocolo exige o esquema SQLite 6 já existente.')
        rows = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
    return fingerprint(rows)


def contract(data):
    from . import __version__
    database=Path(data)/'escritura.sqlite3'
    writable=os.access(data,os.W_OK|os.X_OK) and all(os.access(path,os.W_OK) for path in
        (database,Path(str(database)+'-wal'),Path(str(database)+'-shm')) if path.exists())
    return {'protocol': PROTOCOL, 'abi': abi(), 'schema': schema(database), 'version': __version__, 'writable':writable, 'held_job':(hold(data) or {}).get('job_id')}


def create_hold(data, job):
    if not re.fullmatch('[a-f0-9]{32}', job):
        raise UpdateHeld('Identificador inválido.')
    value = {**contract(data), 'job_id': job}
    path = Path(data)/MARKER
    # No replacing a hold from another operation, including malformed holds.
    temporary=path.with_name(MARKER+'.'+job+'.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(encode(value)); output.flush(); os.fsync(output.fileno())
        os.link(temporary,path)  # Atomic exclusive publish: never a partial hold.
    finally:
        temporary.unlink(missing_ok=True)
    sync_dir(Path(data))
    return value


def release(data, job):
    value = hold(data)
    if not value or value['job_id'] != job or value['schema'] != schema(Path(data)/'escritura.sqlite3') or value['abi'] != abi():
        raise UpdateHeld('Manutenção não pertence ao job ou dados/esquema incompatíveis.')
    (Path(data)/MARKER).unlink()
    sync_dir(Path(data))
    return {'released': True}


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def inventory(root):
    root = Path(root)
    entries, inodes = [], {}
    paths=[]
    for path in root.rglob('*'):
        paths.append(path)
        if len(paths)>50000: raise UpdateHeld('Limite de 50 mil entradas para backup excedido.')
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        if relative in (MARKER, 'escritura.sqlite3-shm'):
            continue
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise UpdateHeld('Links/arquivos especiais impedem backup automático.')
        if (info.st_uid, info.st_gid) != (os.getuid(), os.getgid()):
            raise UpdateHeld('Propriedade de arquivo incompatível; não será feito chown automático.')
        item = {'name': relative, 'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid,
                'gid': info.st_gid, 'mtime_ns': info.st_mtime_ns, 'directory': path.is_dir()}
        if path.is_file():
            digest = hashlib.sha256()
            with path.open('rb') as content:
                for block in iter(lambda: content.read(1024*1024), b''): digest.update(block)
            item.update(size=info.st_size, sha256=digest.hexdigest())
            inode = (info.st_dev, info.st_ino)
            item['hardlink'] = inodes.get(inode)
            inodes.setdefault(inode, relative)
        entries.append(item)
    return {'fingerprint': fingerprint(entries), 'bytes': sum(x.get('size', 0) for x in entries),
            'files': len(entries), 'entries': entries}


def backup(source, destination):
    source, destination = Path(source), Path(destination)
    before = inventory(source)
    target = destination/'source'
    target.mkdir(mode=0o700)  # Exclusive; never merge/overwrite a backup.
    for entry in before['entries']:
        src, dst = source/entry['name'], target/entry['name']
        if entry['directory']:
            dst.mkdir(mode=0o700)
        elif entry['hardlink']:
            os.link(target/entry['hardlink'], dst)
        else:
            shutil.copyfile(src, dst)
        if not entry['directory']:
            os.chmod(dst, entry['mode']); os.utime(dst, ns=(src.stat().st_atime_ns, entry['mtime_ns']))
            with dst.open('rb') as content: os.fsync(content.fileno())
    for entry in reversed(before['entries']):
        if entry['directory']:
            dst=target/entry['name']; os.chmod(dst, entry['mode']); os.utime(dst, ns=(0,entry['mtime_ns'])); sync_dir(dst)
    if inventory(target)['fingerprint'] != before['fingerprint'] or inventory(source)['fingerprint'] != before['fingerprint']:
        raise UpdateHeld('Origem ou cópia mudou durante o backup.')
    db_copy = destination/'consistent.sqlite3'
    with closing(sqlite3.connect((source/'escritura.sqlite3').resolve().as_uri()+'?mode=ro', uri=True)) as original:
        with closing(sqlite3.connect(db_copy)) as copied: original.backup(copied)
    os.chmod(db_copy, 0o600)
    if schema(db_copy) != schema(source/'escritura.sqlite3'):
        raise UpdateHeld('Backup SQLite divergente.')
    with db_copy.open('rb') as content: os.fsync(content.fileno())
    receipt = {k:before[k] for k in ('fingerprint','bytes','files')}
    digest=hashlib.sha256()
    with db_copy.open('rb') as content:
        for block in iter(lambda:content.read(1024*1024),b''):digest.update(block)
    receipt.update(schema=schema(db_copy), sqlite_sha256=digest.hexdigest())
    with (destination/'receipt.json').open('xb') as output:
        output.write(encode(receipt)); output.flush(); os.fsync(output.fileno())
    sync_dir(target); sync_dir(destination)
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['contract','template','hold','release','inventory','backup','writable'])
    parser.add_argument('--job-id',default='')
    parser.add_argument('--data',default=os.environ.get('ESCRITURA_DATA_DIR','/data'))
    args=parser.parse_args()
    try:
        if args.action=='template':
            from .db import Database
            with tempfile.TemporaryDirectory() as folder:
                Database(folder); result=contract(folder)
        elif args.action=='contract': result=contract(args.data)
        elif args.action=='writable':
            if hold(args.data):raise UpdateHeld('Escritas continuam bloqueadas.')
            with closing(sqlite3.connect(Path(args.data)/'escritura.sqlite3',timeout=10)) as db:
                db.execute('BEGIN IMMEDIATE');db.rollback()
            result={'writable':True}
        elif args.action=='hold': result=create_hold(args.data,args.job_id)
        elif args.action=='release': result=release(args.data,args.job_id)
        elif args.action=='inventory':
            result=inventory(args.data); result.pop('entries')
        else: result=backup(args.data,'/backup')
        print(json.dumps(result,sort_keys=True))
    except Exception:
        # Host paths, SQL, file names, credentials and data never enter daemon logs.
        print('Não foi possível comprovar contrato, manutenção ou backup.',file=__import__('sys').stderr)
        raise SystemExit(1)


if __name__=='__main__': main()
