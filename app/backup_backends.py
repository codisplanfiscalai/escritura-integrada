"""Explicit backup adapters. Operational SQLite; PostgreSQL fixtures only, never autodetect."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import ClassVar

from . import backup_archive as archive, backup_crypto as crypto, backup_platform as platform
from .core import DomainError


def fingerprint(values):
    return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class PostgresFixtureSource:
    """Explicit server-side test configuration, not an application database or HTTP payload."""
    data_dir: Path
    endpoint: object
    restore_endpoint: object
    tables: tuple
    probe: object
    backend: ClassVar[str] = 'postgresql-fixture'


class SQLiteBackend:
    kind='sqlite'
    metadata={'id':'sqlite','label':'SQLite operacional','operational':True,
              'limits':'512 MiB no pacote cifrado / 2 GiB de SQLite'}
    max_archive_mib=512

    def __init__(self, db):
        self.db=db
        self.identity=fingerprint({'backend':self.kind,'path':str(db.path.resolve())})

    def capture(self, path, key_id, secret, cancelled, work):
        return crypto.build(self.db.path,path,key_id,secret,cancelled,work_dir=work)

    def verify(self, path, checksum, secret, cancelled, work, record):
        target=work/'verified'
        crypto.restore(path,target,checksum,secret=secret,work_dir=work)
        (target/'escritura.sqlite3').unlink();target.rmdir()
        record({'backend':self.kind,'status':'verified','activated':False})

    def restore(self, path, target, checksum, key_loader, work, *, legacy=False):
        if legacy:archive.restore(path,target,checksum)
        else:crypto.restore(path,target,checksum,key_loader=key_loader,work_dir=work)
        return {'activated':False}


class PostgresFixtureBackend:
    kind='postgresql-fixture'
    metadata={'id':'postgresql-fixture','label':'PostgreSQL · ensaio sintético','operational':False,
              'limits':'64 MiB de dump sintético; sem suporte operacional PostgreSQL'}
    max_archive_mib=65  # Envelope includes bounded ZIP/header metadata.

    def __init__(self, source):
        from .postgres_backup_probe import Probe, Endpoint
        if not isinstance(source.probe,Probe) or not all(isinstance(e,Endpoint) for e in (source.endpoint,source.restore_endpoint)):
            raise DomainError('Origem PostgreSQL de ensaio inválida.',422,'backup_backend')
        source.endpoint.validate();source.restore_endpoint.validate()
        Probe._tables(source.tables)
        self.source=source
        def endpoint(e):return (e.host,e.port,e.database,e.user)
        self.identity=fingerprint({'backend':self.kind,'source':endpoint(source.endpoint),
                                   'restore':endpoint(source.restore_endpoint),'tables':sorted(source.tables)})

    def probe(self,cancelled=lambda:False):
        from .postgres_backup_probe import Probe
        return Probe(self.source.probe.tools,runner=self.source.probe.runner,cancelled=cancelled)

    def capture(self,path,key_id,secret,cancelled,work):
        return self.probe(cancelled).capture(self.source.endpoint,list(self.source.tables),path,secret,key_id,
                                             work_parent=work)['sha256']

    def verify(self,path,checksum,secret,cancelled,work,record):
        from .postgres_backup_probe import ProbeError
        def reserved(database):
            record({'backend':self.kind,'database':database,'status':'preparing','activated':False})
        try:
            result=self.probe(cancelled).restore_new(self.source.restore_endpoint,path,checksum,secret,
                                                     work_parent=work,on_target=reserved)
        except ProbeError as error:
            if error.target:record({'backend':self.kind,'database':error.target,'status':'uncertain','activated':False})
            if error.code=='cancelled':
                raise DomainError('Verificação cancelada.',409,'cancelled') from None
            raise DomainError('Verificação PostgreSQL de ensaio incompleta. Confira o banco isolado no histórico.',422,'backup_verify') from None
        record({'backend':self.kind,'database':result['database'],'status':'verified_probe',
                'activated':False,'logical_payload_reconciliation':False})

    def restore(self,path,target,checksum,key_loader,work,*,legacy=False):
        from .postgres_backup_probe import ProbeError
        if legacy:raise DomainError('ZIP legado é exclusivo do SQLite.',422,'backup_backend')
        # Durable reservation prevents repeat after crash, including an uncertain CREATE/COMMIT.
        platform.private_directory(target)
        receipt=target/'postgres-restore.json'
        def record(database=None,status='preparing'):
            with receipt.open('w',encoding='utf-8') as stream:
                receipt.chmod(0o600)
                json.dump({'backend':self.kind,'database':database,'status':status,'activated':False},stream)
                stream.flush();os.fsync(stream.fileno())
        record()
        try:
            result=self.probe().restore_new(self.source.restore_endpoint,path,checksum,work_parent=work,
                                             key_loader=key_loader,on_target=lambda database:record(database))
            record(result['database'],'restored_probe')
        except ProbeError as error:
            record(error.target,'uncertain' if error.target else 'failed')
            raise
        except Exception:
            # Preserve receipt. Never adopt/repeat a potentially interrupted restore automatically.
            raise
        return {'database':result['database'],'activated':False,'backend':self.kind,
                'logical_payload_reconciliation':False}


def select_backend(db):
    kind=getattr(db,'backend',None)
    if kind=='sqlite':
        from .db import Database
        if isinstance(db,Database):return SQLiteBackend(db)
    if kind=='postgresql-fixture' and isinstance(db,PostgresFixtureSource):
        return PostgresFixtureBackend(db)
    raise DomainError('Backend de backup ausente ou não suportado. PostgreSQL operacional ainda não está integrado; nenhuma conexão foi iniciada.',
                      422,'backup_backend')
