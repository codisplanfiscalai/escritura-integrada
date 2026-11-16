"""Synthetic orchestration + real subprocess bounds, NOT a PostgreSQL round-trip."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from app import backup_crypto as crypto, backup_archive as archive
from app import postgres_backup_probe as pg
from app.core import DomainError


class FakeTools:
    def __init__(self):
        self.calls = []
        self.fail_restore = False
        self.fail_create = False
        self.safe_role = '1'
        self.server = '170011'
        self.sessions = '0'

    def __call__(self, argv, *, env, output, **kwargs):
        self.calls.append((argv, env, kwargs.get('stdin', b'')))
        tool = Path(argv[0]).name
        sql = kwargs.get('stdin', b'').decode()
        if '--version' in argv: content = f'{tool} (PostgreSQL) 17.11\n'.encode()
        elif tool == 'pg_dump': content = b'PGDMPsynthetic-non-native-dump'
        elif tool == 'pg_restore':
            if self.fail_restore and '--list' not in argv: raise pg.ProbeError('fixture_failure')
            content = b'; synthetic TOC\n' if '--list' in argv else b''
        elif 'SHOW server_version_num' in sql: content = (self.server+'\n').encode()
        elif 'FROM pg_roles' in sql: content = self.safe_role.encode()
        elif 'CREATE DATABASE' in sql:
            if self.fail_create: raise pg.ProbeError('database_already_exists')
            content = b'CREATE DATABASE\n'
        elif 'count(*)' in sql: content = self.sessions.encode()
        else: raise AssertionError('Unexpected synthetic query')
        output.write_bytes(content)


@unittest.skipUnless(os.name == 'posix', 'Experimental PostgreSQL probe is POSIX-only')
class PostgresBackupProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pg-backup-unit-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.passfile = self.root/'fixture.pgpass'
        self.passfile.write_text('127.0.0.1:5432:*:backup_fixture_user:synthetic-password\n')
        self.passfile.chmod(0o600)
        self.endpoint = pg.Endpoint('127.0.0.1',5432,'backup_fixture_source','backup_fixture_user',self.passfile)
        paths=[]
        for name in ('pg_dump','pg_restore','psql'):
            path=self.root/name;path.write_text('#!/bin/false\n');path.chmod(0o700);paths.append(path)
        self.tools=pg.Tools(*paths);self.fake=FakeTools();self.probe=pg.Probe(self.tools,runner=self.fake)
        self.secret=crypto.Secret('raw',os.urandom(32));self.output=self.root/'synthetic.eipg'
        self.unknown=self.root/'unknown';self.unknown.mkdir();(self.unknown/'keep').write_text('preserved')

    def capture(self):
        return self.probe.capture(self.endpoint,['backup_probe_records'],self.output,self.secret,'probe',work_parent=self.root)

    def restore(self, result, secret=None):
        return self.probe.restore_new(self.endpoint,self.output,result['sha256'],secret or self.secret,work_parent=self.root)

    def assert_clean(self):
        self.assertEqual([],list(self.root.glob('.pg-probe-*')))
        self.assertEqual('preserved',(self.unknown/'keep').read_text())
        self.assertTrue(self.passfile.exists())

    def test_capture_selects_only_named_tables_excludes_sessions_and_secrets(self):
        with patch.dict(os.environ,PGPASSWORD='ambient-secret',PGSERVICE='ambient-service',LD_PRELOAD='evil'):
            result=self.capture()
        self.assertEqual('postgresql-logical-probe',result['manifest']['backend'])
        self.assertFalse(result['restore_tested'])
        dump=next(c for c in self.fake.calls if Path(c[0][0]).name=='pg_dump' and '--version' not in c[0])
        for table in pg.EMPTY_TABLES:
            self.assertIn('--exclude-table-data=public.'+table,dump[0])
        self.assertIn('--no-large-objects',dump[0]);self.assertIn('--compress=0',dump[0])
        for argv,env,_ in self.fake.calls:
            self.assertNotIn('PGPASSWORD',env);self.assertNotIn('PGSERVICE',env);self.assertNotIn('LD_PRELOAD',env)
            self.assertNotIn('synthetic-password',str(argv)+json.dumps(result))
        self.assert_clean()

    def test_restore_authenticates_then_creates_new_database_without_clean_or_activation(self):
        result=self.capture();self.fake.calls.clear()
        restored=self.restore(result)
        self.assertRegex(restored['database'],r'^backup_restore_[0-9a-f]{32}$')
        self.assertFalse(restored['activated']);self.assertFalse(restored['logical_payload_reconciliation'])
        restore=next(c[0] for c in self.fake.calls if '--single-transaction' in c[0])
        self.assertIn('--exit-on-error',restore)
        self.assertNotIn('--clean',restore);self.assertNotIn('--create',restore)
        self.assertNotIn('DROP ',str(self.fake.calls))
        other=self.restore(result);self.assertNotEqual(restored['database'],other['database'])
        self.assert_clean()

    def test_wrong_key_and_corruption_prevent_every_postgres_command(self):
        result=self.capture();self.fake.calls.clear()
        with self.assertRaises(ValueError):self.restore(result,crypto.Secret('raw',os.urandom(32)))
        self.assertEqual([],self.fake.calls)
        value=bytearray(self.output.read_bytes());value[-1]^=1;self.output.write_bytes(value)
        with self.assertRaises(ValueError):self.restore({'sha256':archive.sha256(self.output)})
        self.assertEqual([],self.fake.calls);self.assert_clean()

    def test_inner_hash_mismatch_before_database_access(self):
        result=self.capture()
        with crypto.authenticated_payload(self.output,result['sha256'],secret=self.secret,work_dir=self.root) as plain:
            with zipfile.ZipFile(plain) as z: manifest=z.read('manifest.json')
        package=self.root/'altered.zip'
        with zipfile.ZipFile(package,'x') as z:
            z.writestr('manifest.json',manifest);z.writestr('database.dump',b'PGDMPdifferent')
        altered=self.root/'altered.eipg'
        checksum=crypto.encrypt(package,altered,'probe',self.secret)
        self.fake.calls.clear()
        with self.assertRaises(pg.ProbeError) as raised:
            self.probe.restore_new(self.endpoint,altered,checksum,self.secret,work_parent=self.root)
        self.assertEqual('checksum',raised.exception.code);self.assertEqual([],self.fake.calls);self.assert_clean()

    def test_cancel_during_authentication_never_contacts_database(self):
        result=self.capture();self.fake.calls.clear();self.probe.cancelled=lambda:True
        with self.assertRaises(DomainError) as raised:self.restore(result)
        self.assertEqual('cancelled',raised.exception.code)
        self.assertEqual([],self.fake.calls);self.assert_clean()

    def test_sqlite_payload_is_rejected_before_postgres_commands(self):
        package=self.root/'sqlite.zip'
        with zipfile.ZipFile(package,'x') as z:
            z.writestr('manifest.json','{"format":1}')
            z.writestr('escritura.sqlite3',b'synthetic')
        checksum=crypto.encrypt(package,self.output,'probe',self.secret)
        with self.assertRaises(pg.ProbeError):self.restore({'sha256':checksum})
        self.assertEqual([],self.fake.calls);self.assert_clean()

    def test_existing_output_never_overwritten(self):
        self.output.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):self.capture()
        self.assertEqual(b'keep',self.output.read_bytes());self.assertEqual([],self.fake.calls)

    def test_fixture_guard_refuses_production_dsn_schema_and_secret_tables(self):
        for endpoint in (replace(self.endpoint,host='remote.example'),replace(self.endpoint,database='production'),
                         replace(self.endpoint,user='postgres')):
            with self.assertRaises(pg.ProbeError):endpoint.validate()
        for tables in (['stored_files'],['migration_rows'],['backup_probe_credentials'],['public.*'],['backup_probe_x;DROP'],[]):
            with self.assertRaises(pg.ProbeError):
                self.probe.capture(self.endpoint,tables,self.output,self.secret,'probe',work_parent=self.root)
        self.assertEqual([],self.fake.calls)

    def test_insecure_or_symlink_passfile_refused_without_reading_secret(self):
        self.passfile.chmod(0o644)
        with self.assertRaises(pg.ProbeError):self.endpoint.validate()
        self.passfile.chmod(0o600);link=self.root/'link';link.symlink_to(self.passfile)
        with self.assertRaises(pg.ProbeError):replace(self.endpoint,passfile=link).validate()

    def test_major_version_mismatch_prevents_dump(self):
        self.fake.server='180001'
        with self.assertRaises(pg.ProbeError):self.capture()
        self.assertFalse(any('--format=custom' in c[0] for c in self.fake.calls));self.assert_clean()

    def test_privileged_role_refused_before_create(self):
        result=self.capture();self.fake.safe_role='0';self.fake.calls.clear()
        with self.assertRaises(pg.ProbeError):self.restore(result)
        self.assertFalse(any(b'CREATE DATABASE' in c[2] for c in self.fake.calls));self.assert_clean()

    def test_restore_failure_preserves_named_database_without_drop_or_retry(self):
        result=self.capture();self.fake.fail_restore=True;self.fake.calls.clear()
        with self.assertRaises(pg.ProbeError) as raised:self.restore(result)
        self.assertEqual('restore_incomplete_or_uncertain',raised.exception.code)
        self.assertRegex(raised.exception.target,r'^backup_restore_[0-9a-f]{32}$')
        self.assertEqual(1,sum('--single-transaction' in c[0] for c in self.fake.calls))
        self.assertNotIn('DROP ',str(self.fake.calls));self.assert_clean()

    def test_create_failure_never_adopts_existing_database(self):
        result=self.capture();self.fake.fail_create=True;self.fake.calls.clear()
        with self.assertRaises(pg.ProbeError):self.restore(result)
        self.assertFalse(any('--single-transaction' in c[0] for c in self.fake.calls));self.assert_clean()

    def test_nonempty_sessions_never_report_verified_restore(self):
        result=self.capture();self.fake.sessions='1'
        with self.assertRaises(pg.ProbeError):self.restore(result)
        self.assert_clean()

    def test_disk_preflight_and_cancelled_encryption_cleanup(self):
        with patch.object(pg.shutil,'disk_usage',return_value=type('Usage',(),{'free':1})()):
            with self.assertRaises(pg.ProbeError):self.capture()
        self.assertEqual([],self.fake.calls)
        self.probe.cancelled=lambda:True
        with self.assertRaises(DomainError) as raised:self.capture()
        self.assertEqual('cancelled',raised.exception.code)
        self.assertFalse(self.output.exists());self.assert_clean()

    def test_real_subprocess_output_is_bounded_and_stderr_not_exposed(self):
        for code,limit,expected in [("print('x'*10000)",32,'output_limit'),
                                    ("import sys;sys.stderr.write('synthetic-secret')",100,'tool_failed_or_warned')]:
            with self.assertRaises(pg.ProbeError) as raised:
                pg.run([sys.executable,'-c',code],env=self.endpoint.environment(),output=self.root/expected,limit=limit)
            self.assertEqual(expected,raised.exception.code)
            self.assertNotIn('synthetic-secret',str(raised.exception))
            self.assertLessEqual((self.root/expected).stat().st_size,limit)

    def test_real_subprocess_timeout_and_cancellation_reap_child(self):
        original=pg.subprocess.Popen
        for name in ('timeout','cancelled_before','cancelled_running'):
            created=[];start=time.monotonic()
            def spawn(*args,**kwargs):
                child=original(*args,**kwargs);created.append(child);return child
            cancelled=lambda:name=='cancelled_before' or name=='cancelled_running' and time.monotonic()-start>.1
            with patch.object(pg.subprocess,'Popen',side_effect=spawn):
                with self.assertRaises(pg.ProbeError) as raised:
                    pg.run([sys.executable,'-c','import time;time.sleep(5)'],env=self.endpoint.environment(),
                           output=self.root/name,timeout=.1 if name=='timeout' else 2,cancelled=cancelled)
            self.assertEqual('timeout' if name=='timeout' else 'cancelled',raised.exception.code)
            self.assertEqual(0 if name=='cancelled_before' else 1,len(created))
            self.assertTrue(all(child.poll() is not None for child in created))


if __name__=='__main__':unittest.main()
