"""Synthetic SQLite and mocked HTTPS only. No real credentials, datasets or destinations."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid
import zipfile

_IMPORT = tempfile.TemporaryDirectory(prefix='backup-import-fixture-')
os.environ['ESCRITURA_DATA_DIR'] = _IMPORT.name
from app.api import create_app
from app.db import Database
from app.core import DomainError
from app.backups import BackupService
from app import backup_archive as archive, backup_providers as providers, backup_crypto as crypto
from fastapi.testclient import TestClient

CONFIG = dict(provider='dropbox', credential_ref='ESCRITURA_BACKUP_FIXTURE', folder='/fixture', encryption_key_id='fixture', enabled=False, interval_hours=1)


class BackupsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.keys = tempfile.TemporaryDirectory()
        self.addCleanup(self.keys.cleanup)
        crypto.create_key(Path(self.keys.name)/'fixture.key', 'synthetic Windows recovery phrase' if os.name=='nt' else None)
        self.env = patch.dict(os.environ, ESCRITURA_BACKUP_KEYRING_DIR=self.keys.name, ESCRITURA_BACKUP_FIXTURE=json.dumps({'access_token':'synthetic-token'}))
        self.env.start(); self.addCleanup(self.env.stop)
        self.db = Database(self.temp.name)
        self.calls = []
        self.service = BackupService(self.db, uploader=lambda *args: self.calls.append(args), clock=lambda:10000)
        self.service.configure(CONFIG)

    def job(self): return self.service.enqueue(uuid.uuid4().hex, 'fixture')

    def test_wal_archive_restore_mode_and_no_overwrite(self):
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO meta VALUES('synthetic','committed-in-WAL')")
        before = self.db.path.stat()
        job = self.job(); self.service.tick()
        finished = self.service.status()['jobs'][0]
        self.assertEqual('completed', finished['state'], finished)
        self.assertEqual(1, len(self.calls))
        result = self.service.restore_job(job['id'])
        restored = Path(self.temp.name) / result['directory'] / 'escritura.sqlite3'
        with closing(sqlite3.connect(restored)) as conn:
            self.assertEqual('committed-in-WAL', conn.execute("SELECT value FROM meta WHERE key='synthetic'").fetchone()[0])
        if os.name!='nt':self.assertEqual(0o600, restored.stat().st_mode & 0o777)
        self.assertEqual(before.st_uid, restored.stat().st_uid)
        with self.assertRaises(DomainError): self.service.restore_job(job['id'])
        self.assertEqual(before.st_ino, self.db.path.stat().st_ino)
        encrypted = self.service.root / (job['id']+'.eibk')
        self.assertTrue(encrypted.read_bytes().startswith(crypto.MAGIC))
        manifest = crypto.restore(encrypted, self.service.root/'second-isolated', finished['checksum'], secret=crypto.load_key('fixture',self.db.data_dir))
        self.assertNotIn('synthetic-token',json.dumps(manifest))

    def test_idempotency_cancel_busy_and_cancel_during_copy(self):
        key=uuid.uuid4().hex
        first=self.service.enqueue(key,'fixture')
        self.assertEqual(first,self.service.enqueue(key,'fixture'))
        with self.assertRaises(DomainError): self.job()
        self.service.cancel(first['id']);self.service.cancel(first['id']);self.service.tick()
        self.assertEqual([],self.calls)
        other=self.job()
        original=archive.build
        def cancel(source,path,callback):
            self.service.cancel(other['id'])
            return original(source,path,callback)
        with patch.object(archive,'build',cancel): self.service.tick()
        self.assertEqual('cancelled',self.service.status()['jobs'][0]['state'])
        self.assertEqual([],self.calls)

    def test_failure_no_retry_and_restart_does_not_steal_active_lock(self):
        job=self.job()
        self.service.uploader=lambda *args: (_ for _ in ()).throw(TimeoutError('secret must not leak'))
        self.service.tick();self.service.tick()
        self.assertEqual('uncertain',self.service.status()['jobs'][0]['state'])
        self.assertNotIn('secret',self.service.status()['jobs'][0]['error'])
        other=BackupService(self.db)
        next_job=self.job()
        self.service.update(next_job['id'],'uploading')
        with self.service.lock() as locked:
            self.assertTrue(locked);other.tick()
            self.assertEqual('uploading',other.status()['jobs'][0]['state'])
        other.tick()
        self.assertEqual('interrupted',other.status()['jobs'][0]['state'])
        self.assertEqual(job['id'], self.service.status()['jobs'][1]['id'])

    def test_schedule_coalesces_missed_slots_and_survives_restart(self):
        self.service.configure({**CONFIG,'enabled':True})
        self.service.clock=lambda:20000
        self.service.tick();self.assertEqual(1,len(self.calls))
        self.service.tick();self.assertEqual(1,len(self.calls))
        restart=BackupService(self.db,uploader=lambda *args:self.calls.append(args),clock=lambda:23600)
        restart.tick();self.assertEqual(2,len(self.calls))
        self.assertEqual(27200,restart.status()['next_due'])

    def test_missing_credentials_record_failure_and_corruption_is_rejected(self):
        with patch.dict(os.environ,{},clear=True):
            self.job();self.service.tick()
        self.assertEqual('failed',self.service.status()['jobs'][0]['state'])
        job=self.job();self.service.tick()
        path=self.service.root/(job['id']+'.eibk');path.write_bytes(b'corrupt')
        with self.assertRaises(DomainError): self.service.restore_job(job['id'])
        self.assertFalse((self.service.root/'restores'/job['id']).exists())

    def test_concurrent_admission_and_upload_cannot_be_cancelled(self):
        key=uuid.uuid4().hex
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:self.service.enqueue(key,'fixture'),range(8)))
        self.assertEqual(1,len({job['id'] for job in results}))
        self.service.update(results[0]['id'],'uploading')
        with self.assertRaises(DomainError):self.service.cancel(results[0]['id'])

    def test_sessions_removed_and_internal_checksum_checked(self):
        with self.db.transaction() as conn:
            uid=conn.execute("INSERT INTO users(username,password_hash,created_at) VALUES('fixture','synthetic-hash','now')").lastrowid
            conn.execute("INSERT INTO sessions(token_hash,user_id,csrf_token,period,expires_at,created_at) VALUES('synthetic-token',?,'synthetic-csrf','2026-11',9999999999,'now')",(uid,))
        job=self.job();self.service.tick()
        result=self.service.restore_job(job['id'])
        with closing(sqlite3.connect(Path(self.temp.name)/result['directory']/'escritura.sqlite3')) as conn:
            self.assertEqual(0,conn.execute('SELECT count(*) FROM sessions').fetchone()[0])
        source=self.service.root/'legacy-for-corruption.zip'
        archive.build(self.db.path,source)
        bad=self.service.root/'tampered.zip'
        with zipfile.ZipFile(source) as src, zipfile.ZipFile(bad,'w') as dst:
            manifest=json.loads(src.read('manifest.json'))
            manifest['files']['escritura.sqlite3']['sha256']='0'*64
            dst.writestr('manifest.json',json.dumps(manifest))
            dst.writestr('escritura.sqlite3',src.read('escritura.sqlite3'))
        with self.assertRaises(ValueError):archive.restore(bad,self.service.root/'bad-restore')
        self.assertFalse((self.service.root/'bad-restore').exists())

    def test_local_permission_failure_never_starts_upload(self):
        self.job()
        with patch.object(archive,'build',side_effect=PermissionError('synthetic-private-path')):
            self.service.tick()
        job=self.service.status()['jobs'][0]
        self.assertEqual('failed',job['state'])
        self.assertIn('permissões',job['error'])
        self.assertNotIn('synthetic-private-path',job['error'])
        self.assertFalse(self.calls)

    def test_archive_traversal_and_secret_original_refused(self):
        path=self.service.root/'bad.zip'
        with zipfile.ZipFile(path,'w') as z: z.writestr('../escape','bad')
        target=self.service.root/'isolated'
        with self.assertRaises(ValueError): archive.restore(path,target)
        self.assertFalse(target.exists())
        # A synthetic certificate-like blob must not be exported.
        with self.db.transaction() as conn:
            conn.execute('PRAGMA foreign_keys=OFF')
        with closing(sqlite3.connect(self.db.path)) as conn:
            conn.execute("INSERT INTO stored_files(company_id,year,category,filename,sha256,content,created_at,created_by) VALUES(1,2026,'originals','fixture.pem',?,?,'now','fixture')",('0'*64,b'-----BEGIN CERTIFICATE-----'))
            conn.commit()
        self.job();self.service.tick()
        self.assertEqual('failed',self.service.status()['jobs'][0]['state'])
        self.assertEqual([],self.calls)


class ProviderTests(unittest.TestCase):
    def test_four_provider_wire_contracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'fixture.zip';path.write_bytes(b'synthetic archive')
            secret={'access_token':'synthetic','access_key_id':'fixture','secret_access_key':'fixture'}
            with patch.dict(os.environ,ESCRITURA_BACKUP_FIXTURE=json.dumps(secret)):
                for provider in ('dropbox','drive','s3','minio'):
                    calls=[]
                    config={**CONFIG,'provider':provider,'bucket':'fixture-bucket','region':'us-east-1','prefix':'daily',
                            'folder':'folder_id' if provider=='drive' else '/fixture','endpoint':'https://minio.invalid' if provider=='minio' else ''}
                    def transport(method,url,headers,body):
                        calls.append((method,url,headers,body))
                        if provider=='dropbox':
                            self.assertFalse(json.loads(headers['Dropbox-API-Arg'])['autorename'])
                            return {},{'size':path.stat().st_size,'content_hash':hashlib.sha256(hashlib.sha256(path.read_bytes()).digest()).hexdigest()}
                        if provider=='drive':
                            if method=='POST': return {'location':'https://www.googleapis.com/upload/drive/v3/files?upload_id=fixture'},{}
                            return {},{'md5Checksum':hashlib.md5(path.read_bytes()).hexdigest(),'size':str(path.stat().st_size)}
                        self.assertEqual('*',headers['if-none-match'])
                        self.assertIn('AWS4-HMAC-SHA256 Credential=fixture/',headers['Authorization'])
                        return {'x-amz-checksum-sha256':headers['x-amz-checksum-sha256']},{}
                    self.assertTrue(providers.upload(config,path,'fixture.zip',transport)['verified'])
                    self.assertEqual(2 if provider=='drive' else 1,len(calls))

    def test_bad_endpoint_and_wrong_checksum(self):
        with self.assertRaises(DomainError):providers.validate({**CONFIG,'provider':'minio','bucket':'fixture','region':'x','endpoint':'http://host'})
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,ESCRITURA_BACKUP_FIXTURE='{"access_token":"fixture"}'):
            path=Path(tmp)/'x';path.write_bytes(b'x')
            with self.assertRaises(ValueError):providers.upload(CONFIG,path,'x',lambda *a:({}, {'size':1,'content_hash':'wrong'}))


class ApiTests(unittest.TestCase):
    def test_admin_csrf_origin_and_isolated_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=create_app(tmp)
            client=TestClient(app)
            self.assertEqual(401,client.get('/api/backups').status_code)
            setup=client.post('/api/setup',json={'username':'fixture','password':'Synthetic-only-12345!'}).json()
            self.assertEqual(403,client.put('/api/backups/config',json=CONFIG).status_code)
            client.headers['X-CSRF-Token']=setup['csrf_token']
            self.assertEqual(200,client.put('/api/backups/config',json=CONFIG).status_code)
            self.assertEqual(403,client.post('/api/backups',json={},headers={'Origin':'https://untrusted.invalid'}).status_code)
            self.assertEqual(422,client.post('/api/backups',json={'idempotency_key':'../bad'}).status_code)
            with app.state.db.transaction() as conn:conn.execute("UPDATE users SET role='viewer'")
            for method,path in [('get','/api/backups'),('put','/api/backups/config'),('post','/api/backups'),('post','/api/backups/id/cancel'),('post','/api/backups/id/restore')]:
                response=getattr(client,method)(path,**({'json':CONFIG} if method!='get' else {}))
                self.assertEqual(403,response.status_code,(path,response.text))
            client.close()


if __name__=='__main__':unittest.main()
