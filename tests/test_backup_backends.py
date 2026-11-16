"""Explicit backend dispatch and shared queue, with synthetic sources and no cloud."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import uuid

from app.db import Database
from app.backups import BackupService
from app.backup_backends import PostgresFixtureSource,select_backend
from app import backup_crypto as crypto, postgres_backup_probe as pg
from app.core import DomainError
from tests.test_postgres_backup_probe import FakeTools

CONFIG=dict(provider='dropbox',credential_ref='ESCRITURA_BACKUP_FIXTURE',folder='/fixture',
            encryption_key_id='fixture',enabled=False,interval_hours=1)


class BackendFixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='backend-dispatch-fixture-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=Database(self.root/'data');self.uploads=[]
        self.keys=self.root/'keys';self.keys.mkdir()
        crypto.create_key(self.keys/'fixture.key','Synthetic private Windows passphrase' if os.name=='nt' else None)
        self.env=patch.dict(os.environ,ESCRITURA_BACKUP_KEYRING_DIR=str(self.keys),
                            ESCRITURA_BACKUP_FIXTURE='{"access_token":"synthetic"}')
        self.env.start();self.addCleanup(self.env.stop)

    def sqlite_service(self):
        service=BackupService(self.db,uploader=lambda *a:self.uploads.append(a))
        service.configure(CONFIG);return service


class BackendDispatchTests(BackendFixture):
    def test_explicit_sqlite_backend_ignores_postgres_environment(self):
        with patch.dict(os.environ,ESCRITURA_DATABASE_URL='postgresql://not-used',PGHOST='not-used'):
            service=self.sqlite_service()
        self.assertEqual('sqlite',service.status()['source_backend']['id'])
        self.assertTrue(service.status()['source_backend']['operational'])
        with self.assertRaises(DomainError):service.configure({**CONFIG,'backend':'postgresql'})

    def test_unknown_and_postgres_runtime_fail_before_filesystem_or_connections(self):
        for kind in (None,'unknown','postgresql','sqlite'):
            fake=SimpleNamespace(backend=kind,data_dir=self.root/'must-not-exist',path=self.db.path)
            with self.assertRaises(DomainError) as raised:BackupService(fake)
            self.assertEqual('backup_backend',raised.exception.code)
            self.assertFalse(fake.data_dir.exists())

    def test_legacy_control_schema_migrates_and_restores_sqlite_history(self):
        control=self.db.data_dir/'backup-control';control.mkdir()
        job_id=uuid.uuid4().hex
        checksum=crypto.build(self.db.path,control/(job_id+'.eibk'),'fixture',crypto.load_key('fixture',self.db.data_dir))
        with closing(sqlite3.connect(control/'state.sqlite3')) as conn:
            conn.execute("CREATE TABLE jobs(id TEXT PRIMARY KEY,intent TEXT UNIQUE,config TEXT,state TEXT,created REAL,finished REAL,actor TEXT,error TEXT,checksum TEXT,cancel INTEGER)")
            conn.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (job_id,uuid.uuid4().hex,json.dumps(CONFIG),'completed',1,2,'fixture','',checksum,0));conn.commit()
        service=BackupService(self.db)
        self.assertEqual('sqlite',service.status()['jobs'][0]['source_backend'])
        self.assertIsNone(service.status()['jobs'][0]['verification'])
        result=service.restore_job(job_id)
        self.assertTrue((self.db.data_dir/result['directory']/'escritura.sqlite3').is_file())
        self.assertEqual('sqlite',BackupService(self.db).status()['source_backend']['id'])


@unittest.skipUnless(os.name=='posix','PostgreSQL fixture adapter is POSIX-only')
class PostgresQueueTests(BackendFixture):
    def source(self,data_dir=None):
        passfile=self.root/'probe.pgpass';passfile.write_text('synthetic-only');passfile.chmod(0o600)
        paths=[]
        for name in ('pg_dump','pg_restore','psql'):
            path=self.root/name;path.write_text('#!/bin/false\n');path.chmod(0o700);paths.append(path)
        self.fake=FakeTools()
        endpoint=pg.Endpoint('127.0.0.1',5432,'backup_fixture_source','backup_fixture_user',passfile)
        directory=data_dir or self.root/'pg-control';directory.mkdir(exist_ok=True)
        return PostgresFixtureSource(directory,endpoint,replace(endpoint,database='backup_fixture_control'),
                                     ('backup_probe_records',),pg.Probe(pg.Tools(*paths),runner=self.fake))

    def service(self):
        self.pg_source=self.source()
        service=BackupService(self.pg_source,uploader=lambda *a:self.uploads.append(a))
        service.configure(CONFIG);return service

    def test_shared_queue_verifies_before_upload_and_persists_targets(self):
        service=self.service();original=self.fake.__call__
        def runner(argv,**kwargs):
            if b'CREATE DATABASE' in kwargs.get('stdin',b''):
                row=service.status()['jobs'][0]
                self.assertEqual('preparing',row['verification']['status'])
                self.assertIn(row['verification']['database'],kwargs['stdin'].decode())
            return original(argv,**kwargs)
        source=replace(self.pg_source,probe=pg.Probe(self.pg_source.probe.tools,runner=runner))
        service=BackupService(source,uploader=lambda *a:self.uploads.append(a))
        job=service.enqueue(uuid.uuid4().hex,'fixture');service.tick()
        finished=service.status()['jobs'][0]
        self.assertEqual('completed',finished['state']);self.assertEqual(1,len(self.uploads))
        self.assertEqual('postgresql-fixture',finished['source_backend'])
        self.assertEqual('verified_probe',finished['verification']['status'])
        self.assertFalse(finished['verification']['activated'])

    def test_recovery_receipt_refuses_repeat_without_new_database_commands(self):
        service=self.service();job=service.enqueue(uuid.uuid4().hex,'fixture');service.tick()
        result=service.restore_job(job['id'])
        receipt=self.pg_source.data_dir/result['directory']/'postgres-restore.json'
        self.assertEqual(result['database'],json.loads(receipt.read_text())['database'])
        self.assertFalse(result['activated']);calls=len(self.fake.calls)
        with self.assertRaises(DomainError) as raised:service.restore_job(job['id'])
        self.assertEqual('restore_exists',raised.exception.code);self.assertEqual(calls,len(self.fake.calls))

    def test_interruption_keeps_receipt_and_no_automatic_second_create(self):
        service=self.service();job=service.enqueue(uuid.uuid4().hex,'fixture');service.tick()
        original=self.fake.__call__
        def fail(argv,**kwargs):
            if b'CREATE DATABASE' in kwargs.get('stdin',b''):raise SystemExit('synthetic interruption')
            return original(argv,**kwargs)
        service.backend.source=replace(self.pg_source,probe=pg.Probe(self.pg_source.probe.tools,runner=fail))
        with self.assertRaises(SystemExit):service.restore_job(job['id'])
        receipt=service.root/'restores'/job['id']/'postgres-restore.json'
        self.assertRegex(json.loads(receipt.read_text())['database'],r'^backup_restore_[0-9a-f]{32}$')
        with self.assertRaises(DomainError):service.restore_job(job['id'])
        self.assertEqual([],list(service.work_root.iterdir()))

    def test_failed_verification_never_uploads_and_retains_uncertain_target(self):
        service=self.service();self.fake.fail_restore=True
        intent=uuid.uuid4().hex;job=service.enqueue(intent,'fixture');service.tick()
        row=service.status()['jobs'][0]
        self.assertEqual('failed',row['state']);self.assertEqual([],self.uploads)
        self.assertEqual('uncertain',row['verification']['status'])
        self.assertRegex(row['verification']['database'],r'^backup_restore_[0-9a-f]{32}$')
        self.assertEqual(job['id'],service.enqueue(intent,'fixture')['id'])
        self.assertEqual([],list(service.work_root.iterdir()))

    def test_source_changed_after_admission_never_connects_or_falls_back(self):
        service=self.service();service.enqueue(uuid.uuid4().hex,'fixture')
        changed=replace(self.pg_source,endpoint=replace(self.pg_source.endpoint,database='backup_fixture_other'))
        current=BackupService(changed,uploader=lambda *a:self.uploads.append(a))
        current.tick()
        self.assertEqual([],self.fake.calls);self.assertEqual([],self.uploads)
        self.assertEqual('failed',current.status()['jobs'][0]['state'])

    def test_sqlite_job_cannot_be_run_under_postgres_adapter(self):
        original=self.sqlite_service();original.enqueue(uuid.uuid4().hex,'fixture')
        source=self.source(self.db.data_dir)
        service=BackupService(source,uploader=lambda *a:self.uploads.append(a));service.tick()
        self.assertEqual([],self.fake.calls);self.assertEqual([],self.uploads)
        self.assertEqual('failed',service.status()['jobs'][0]['state'])


if __name__=='__main__':unittest.main()
