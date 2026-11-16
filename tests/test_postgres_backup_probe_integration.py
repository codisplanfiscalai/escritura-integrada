"""Opt-in PostgreSQL 17 disposable-cluster proof. Never enabled by a generic DSN."""
from dataclasses import replace
import hashlib
import json
import selectors
import subprocess
import time
import os
from pathlib import Path
import tempfile
import unittest
import uuid

from app import backup_crypto as crypto, backup_archive as archive
from app import postgres_backup_probe as pg

ENABLED = os.environ.get('ESCRITURA_PG_PROBE_DISPOSABLE') == 'yes'


@unittest.skipUnless(ENABLED, 'Requires explicitly provisioned disposable PostgreSQL 17 and official tools')
class NativePostgresBackupProbeTests(unittest.TestCase):
    def setUp(self):
        # Operator supplies a *synthetic* private passfile, never password/DSN in argv.
        bindir = Path(os.environ['ESCRITURA_PG_PROBE_BINDIR'])
        parent = Path(os.environ['ESCRITURA_PG_PROBE_WORK_PARENT'])
        self.temp = tempfile.TemporaryDirectory(prefix='pg-native-fixture-', dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.control = pg.Endpoint('127.0.0.1', int(os.environ['ESCRITURA_PG_PROBE_PORT']),
                                   'backup_fixture_control', 'backup_fixture_user',
                                   Path(os.environ['ESCRITURA_PG_PROBE_PASSFILE']))
        self.probe = pg.Probe(pg.Tools(*(bindir/name for name in ('pg_dump','pg_restore','psql'))))
        self.probe._versions(self.control, self.root)
        self.source = replace(self.control,database='backup_fixture_'+uuid.uuid4().hex)
        self.probe._query(self.control,self.root,'CREATE DATABASE "'+self.source.database+'" TEMPLATE template0;')
        self.owned = [self.source.database]
        self.addCleanup(self.cleanup_created_databases)
        self.probe._query(self.source,self.root, """
            CREATE TABLE public.backup_probe_records(id bigint PRIMARY KEY, amount bigint NOT NULL CHECK(amount>=0), content bytea NOT NULL);
            CREATE TABLE public.sessions(id bigint PRIMARY KEY, token text);
            CREATE TABLE public.session_contexts(id bigint PRIMARY KEY, session_id bigint REFERENCES sessions(id));
            CREATE TABLE public.login_attempts(id bigint PRIMARY KEY, username text);
            INSERT INTO backup_probe_records VALUES(1,1234567890123,decode('00ff3c786d6c2f3e','hex')),(2,42,decode('616263','hex'));
            INSERT INTO sessions VALUES(1,'synthetic-session-token');
            INSERT INTO session_contexts VALUES(1,1);
            INSERT INTO login_attempts VALUES(1,'synthetic-user');
        """)

    def cleanup_created_databases(self):
        # Test harness only; exact successful creations, no FORCE/termination/unknown adoption.
        for name in reversed(self.owned):
            self.probe._query(self.control,self.root,'DROP DATABASE "'+name+'";')

    def payload(self, endpoint):
        return self.probe._query(endpoint,self.root,
            "SELECT json_agg(json_build_array(id,amount,encode(content,'hex')) ORDER BY id)::text FROM public.backup_probe_records;")

    def record(self, name, **values):
        filename=os.environ.get('ESCRITURA_PG_PROBE_RESULT')
        if filename:
            path=Path(filename)
            records=json.loads(path.read_text()) if path.exists() else []
            records.append({'test':name,**values})
            path.write_text(json.dumps(records,indent=2))

    def test_application_queue_restore_and_repeat_protection(self):
        from unittest.mock import patch
        from app.backups import BackupService
        from app.backup_backends import PostgresFixtureSource
        from app.core import DomainError
        from tests.test_backup_backends import CONFIG
        keys=self.root/'keys';keys.mkdir();crypto.create_key(keys/'fixture.key')
        data=self.root/'service';data.mkdir();uploads=[]
        source=PostgresFixtureSource(data,self.source,self.control,('backup_probe_records',),self.probe)
        with patch.dict(os.environ,ESCRITURA_BACKUP_KEYRING_DIR=str(keys),
                        ESCRITURA_BACKUP_FIXTURE='{"access_token":"synthetic"}'):
            service=BackupService(source,uploader=lambda *a:uploads.append(a))
            service.configure(CONFIG)
            intent=uuid.uuid4().hex;job=service.enqueue(intent,'synthetic');service.tick()
            row=service.status()['jobs'][0]
            self.assertEqual('completed',row['state'],row.get('error'))
            verified=row['verification']['database'];self.owned.append(verified)
            self.assertEqual(1,len(uploads))
            self.assertEqual(job['id'],service.enqueue(intent,'synthetic')['id'])
            service.tick();self.assertEqual(1,len(uploads))
            restored=service.restore_job(job['id']);self.owned.append(restored['database'])
            for target in (verified,restored['database']):
                payload=self.probe._query(self.control,self.root,
                    "SELECT json_agg(json_build_array(id,amount,encode(content,'hex')) ORDER BY id)::text FROM public.backup_probe_records;",target)
                self.assertEqual(self.payload(self.source),payload)
                self.assertEqual('0',self.probe._query(self.control,self.root,'SELECT count(*) FROM sessions;',target))
            receipt=data/restored['directory']/'postgres-restore.json'
            self.assertEqual(restored['database'],json.loads(receipt.read_text())['database'])
            query="SELECT count(*) FROM pg_database WHERE datname LIKE 'backup_restore_%';"
            before=self.probe._query(self.control,self.root,query)
            with self.assertRaises(DomainError) as raised:service.restore_job(job['id'])
            self.assertEqual('restore_exists',raised.exception.code)
            self.assertEqual(before,self.probe._query(self.control,self.root,query))
            self.assertFalse(service.status()['source_backend']['operational'])
            self.record('application_queue',backend=row['source_backend'],upload_simulated=True,
                        upload_count=len(uploads),verification_and_restore_hash_match=True,
                        payload_sha256=hashlib.sha256(payload.encode()).hexdigest(),
                        repeat_refused=True,receipt_persisted=True,activated=False)

    def test_wrong_key_and_corruption_create_no_database(self):
        secret=crypto.Secret('raw',os.urandom(32));envelope=self.root/'fixture.eipg'
        captured=self.probe.capture(self.source,['backup_probe_records'],envelope,secret,'synthetic',work_parent=self.root)
        query="SELECT count(*) FROM pg_database WHERE datname LIKE 'backup_restore_%';"
        before=self.probe._query(self.control,self.root,query)
        with self.assertRaises(ValueError):
            self.probe.restore_new(self.control,envelope,captured['sha256'],crypto.Secret('raw',os.urandom(32)),work_parent=self.root)
        corrupted=bytearray(envelope.read_bytes());corrupted[-1]^=1;envelope.write_bytes(corrupted)
        with self.assertRaises(ValueError):
            self.probe.restore_new(self.control,envelope,archive.sha256(envelope),secret,work_parent=self.root)
        after=self.probe._query(self.control,self.root,query)
        self.assertEqual('0',before);self.assertEqual(before,after)
        self.record('authentication',wrong_key_refused=True,corruption_refused=True,
                    restore_databases_before=int(before),restore_databases_after=int(after))

    def test_capture_excludes_pending_write_and_preserves_snapshot_after_commit(self):
        before=self.payload(self.source)
        writer=subprocess.Popen([str(self.probe.tools.psql),'-X','--no-password','-At','-v','ON_ERROR_STOP=1'],
                                env=self.source.environment(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            writer.stdin.write(b"BEGIN; UPDATE public.backup_probe_records SET amount=amount+9; SELECT 'writer-ready';\n")
            writer.stdin.flush()
            ready=b'';deadline=time.monotonic()+5
            with selectors.DefaultSelector() as selector:
                selector.register(writer.stdout,selectors.EVENT_READ)
                while b'writer-ready' not in ready and time.monotonic()<deadline:
                    for event,_ in selector.select(.1):
                        block=os.read(event.fileobj.fileno(),1024)
                        if not block:raise AssertionError('Synthetic writer exited before readiness')
                        ready+=block
            self.assertIn(b'writer-ready',ready)
            active=self.probe._query(self.source,self.root,
                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND state='idle in transaction';")
            self.assertGreaterEqual(int(active),1)
            secret=crypto.Secret('raw',os.urandom(32));envelope=self.root/'concurrent.eipg'
            captured=self.probe.capture(self.source,['backup_probe_records'],envelope,secret,'synthetic',work_parent=self.root)
            self.assertIsNone(writer.poll())
            writer.stdin.write(b'COMMIT;\n\\q\n');writer.stdin.close()
            self.assertEqual(0,writer.wait(timeout=5))
            self.assertNotEqual(before,self.payload(self.source))
            result=self.probe.restore_new(self.control,envelope,captured['sha256'],secret,work_parent=self.root)
            self.owned.append(result['database'])
            after=self.probe._query(self.control,self.root,
                "SELECT json_agg(json_build_array(id,amount,encode(content,'hex')) ORDER BY id)::text FROM public.backup_probe_records;",
                result['database'])
            self.assertEqual(before,after)
            self.record('concurrent_snapshot',writer_open_during_capture=True,source_commit_visible_after_capture=True,
                        restored_matches_capture_snapshot=True,payload_sha256=hashlib.sha256(after.encode()).hexdigest())
        finally:
            if writer.poll() is None:
                writer.terminate();writer.wait(timeout=5)
            for stream in (writer.stdin,writer.stdout,writer.stderr):
                if not stream.closed:stream.close()

    def test_real_dump_restore_hashes_sessions_constraints_and_source_preserved(self):
        before = self.payload(self.source)
        secret = crypto.Secret('raw',os.urandom(32))
        envelope = self.root/'fixture.eipg'
        captured = self.probe.capture(self.source,['backup_probe_records'],envelope,secret,'synthetic',work_parent=self.root)
        result = self.probe.restore_new(self.control,envelope,captured['sha256'],secret,work_parent=self.root)
        self.owned.append(result['database'])
        # Endpoint guard deliberately does not admit arbitrary restoration targets. Queries
        # below use the existing synthetic control config plus the returned generated name.
        after = self.probe._query(self.control,self.root,
            "SELECT json_agg(json_build_array(id,amount,encode(content,'hex')) ORDER BY id)::text FROM public.backup_probe_records;",
            result['database'])
        self.assertEqual(hashlib.sha256(before.encode()).digest(), hashlib.sha256(after.encode()).digest())
        self.assertEqual(before,self.payload(self.source))
        self.assertEqual('1',self.probe._query(self.source,self.root,'SELECT count(*) FROM public.sessions;'))
        for name in pg.EMPTY_TABLES:
            self.assertEqual('0',self.probe._query(self.control,self.root,'SELECT count(*) FROM public.'+name+';',result['database']))
        with self.assertRaises(pg.ProbeError):
            self.probe._query(self.control,self.root,'INSERT INTO public.backup_probe_records VALUES(3,-1,decode(\'00\',\'hex\'));',result['database'])
        self.assertEqual('2',self.probe._query(self.control,self.root,'SELECT count(*) FROM public.backup_probe_records;',result['database']))
        self.assertFalse(result['activated'])
        self.assertEqual([],list(self.root.glob('.pg-probe-*')))
        self.record('roundtrip',payload_sha256=hashlib.sha256(after.encode()).hexdigest(),
                    source_payload_sha256=hashlib.sha256(before.encode()).hexdigest(),
                    dump_bytes=captured['manifest']['file']['bytes'],dump_sha256=captured['manifest']['file']['sha256'],
                    envelope_bytes=envelope.stat().st_size,envelope_sha256=captured['sha256'],
                    constraints_verified=True,sessions_empty=True,source_preserved=True)


if __name__ == '__main__':
    if not ENABLED:
        raise SystemExit('NOT EXECUTED: provision a disposable PostgreSQL 17 fixture and explicitly opt in.')
    unittest.main()
