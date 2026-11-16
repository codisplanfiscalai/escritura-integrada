"""Synthetic protocol, crash-cleanup and Windows boundary tests; never contacts providers."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from app import backup_archive as archive, backup_crypto as crypto, backup_platform as platform, backup_workspace as workspace, backup_providers as providers
from app.backups import BackupService, UnavailableBackupService
from app.db import Database
from app.core import DomainError

CONFIG={'provider':'dropbox','credential_ref':'ESCRITURA_BACKUP_FIXTURE','folder':'/synthetic','encryption_key_id':'fixture'}


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'fixture.eibk';self.path.write_bytes(os.urandom(700000))
        self.env=patch.dict(os.environ,ESCRITURA_BACKUP_FIXTURE=json.dumps({'access_token':'fixture','access_key_id':'fixture','secret_access_key':'fixture'}))
        self.env.start();self.addCleanup(self.env.stop)

    def test_dropbox_session_offsets_final_commit_and_content_hash(self):
        calls=[];received=bytearray()
        def transport(method,url,headers,body):
            args=json.loads(headers['Dropbox-API-Arg']);calls.append((url,args))
            self.assertIsInstance(body,providers.FileSlice)
            with body.path.open('rb') as f:f.seek(body.offset);received.extend(f.read(body.length))
            if url.endswith('/start'):return {},{'session_id':'synthetic-session'}
            self.assertEqual(body.offset,args['cursor']['offset'])
            if url.endswith('/append_v2'):return {},None
            self.assertFalse(args['commit']['autorename']);self.assertTrue(args['commit']['strict_conflict'])
            return {},{'size':self.path.stat().st_size,'content_hash':hashlib.sha256(hashlib.sha256(bytes(received)).digest()).hexdigest()}
        with patch.object(providers,'DROPBOX_SINGLE_LIMIT',300000),patch.object(providers,'CHUNK_BYTES',262144):
            self.assertTrue(providers.upload(CONFIG,self.path,'fixture.eibk',transport)['verified'])
        self.assertEqual(self.path.read_bytes(),received)
        self.assertTrue(calls[0][0].endswith('/start'));self.assertTrue(calls[1][0].endswith('/append_v2'));self.assertTrue(calls[2][0].endswith('/finish'))

    def test_drive_308_ranges_and_incomplete_ack_never_repeat(self):
        config={**CONFIG,'provider':'drive','folder':'synthetic-folder'}
        for incomplete in (False,True):
            calls=[];received=bytearray()
            def transport(method,url,headers,body):
                if method=='POST':
                    self.assertIn('supportsAllDrives=true',url)
                    self.assertIn('ignoreDefaultVisibility=true',url)
                    return {'location':'https://www.googleapis.com/upload/drive/v3/files?upload_id=synthetic'},{}
                calls.append(headers['Content-Range'])
                with body.path.open('rb') as f:f.seek(body.offset);received.extend(f.read(body.length))
                end=body.offset+body.length
                if end<self.path.stat().st_size:
                    return {'_status':308,'range':f'bytes=0-{end-2 if incomplete else end-1}'},{}
                return {'_status':201},{'size':str(len(received)),'md5Checksum':hashlib.md5(received).hexdigest()}
            with patch.object(providers,'CHUNK_BYTES',262144):
                if incomplete:
                    with self.assertRaises(ValueError):providers.upload(config,self.path,'fixture.eibk',transport)
                    self.assertEqual(1,len(calls))
                else:
                    providers.upload(config,self.path,'fixture.eibk',transport)
                    self.assertEqual(3,len(calls));self.assertEqual(self.path.read_bytes(),received)

    def test_minio_and_s3_head_fallback_checksum_size_and_permissions(self):
        for provider in ('s3','minio'):
            config={**CONFIG,'provider':provider,'region':'us-east-1','bucket':'fixture-bucket','endpoint':'https://minio.invalid' if provider=='minio' else ''}
            calls=[]
            def transport(method,url,headers,body):
                calls.append(method)
                if method=='PUT':
                    self.assertEqual('*',headers['if-none-match'])
                    if provider=='minio':self.assertEqual('SHA256',headers['x-amz-checksum-algorithm'])
                    return {},{}
                self.assertEqual('ENABLED',headers['x-amz-checksum-mode'])
                import base64
                return {'content-length':str(self.path.stat().st_size),'x-amz-checksum-sha256':base64.b64encode(bytes.fromhex(archive.sha256(self.path))).decode()},{}
            providers.upload(config,self.path,'fixture.eibk',transport);self.assertEqual(['PUT','HEAD'],calls)
            def denied(method,*args):
                if method=='HEAD':raise PermissionError('synthetic only')
                return {},{}
            with self.assertRaises(PermissionError):providers.upload(config,self.path,'fixture.eibk',denied)

    def test_drive_session_url_cannot_redirect_token_to_another_host(self):
        calls=[]
        def transport(*args):
            calls.append(args)
            return {'location':'https://www.googleapis.com.evil.invalid/upload/drive/v3/files'},{}
        with self.assertRaises(ValueError):
            providers.upload({**CONFIG,'provider':'drive','folder':'fixture-folder'},self.path,'fixture.eibk',transport)
        self.assertEqual(1,len(calls))

    def test_http_transport_streams_exact_slice_and_exposes_308_without_redirect(self):
        received=bytearray();headers={}
        class Connection:
            def __init__(self,*args,**kwargs):pass
            def putrequest(self,method,path,**kwargs):self.method=method
            def putheader(self,name,value):headers[name]=value
            def endheaders(self):pass
            def send(self,value):received.extend(value)
            def getresponse(self):return SimpleNamespace(status=308,read=lambda _:b'',getheaders=lambda:[('Range','bytes=0-99')])
            def close(self):pass
        with patch.object(providers.http.client,'HTTPSConnection',Connection):
            result,_=providers.request('PUT','https://fixture.invalid/session',{},providers.FileSlice(self.path,25,100))
        self.assertEqual(self.path.read_bytes()[25:125],received)
        self.assertEqual('100',headers['Content-Length']);self.assertEqual(308,result['_status'])


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=Database(self.root/'data');self.service=BackupService(self.db,uploader=lambda *a:None)
        keys=self.root/'keys';keys.mkdir();crypto.create_key(keys/'fixture.key', 'synthetic Windows recovery phrase' if os.name=='nt' else None)
        self.env=patch.dict(os.environ,ESCRITURA_BACKUP_KEYRING_DIR=str(keys),ESCRITURA_BACKUP_FIXTURE='{"access_token":"fixture"}')
        self.env.start();self.addCleanup(self.env.stop);self.service.configure(CONFIG)

    def test_abrupt_process_exit_leaves_owned_work_and_restart_cleans_only_work(self):
        job=self.service.enqueue(uuid.uuid4().hex,'fixture');self.service.update(job['id'],'snapshot')
        code="from app.backup_workspace import create; import os,sys; p=create(sys.argv[1],sys.argv[2]); (p/'synthetic.txt').write_text('synthetic'); os._exit(17)"
        result=subprocess.run([sys.executable,'-c',code,str(self.service.work_root),job['id']])
        self.assertEqual(17,result.returncode)
        archive_file=self.service.root/'preserved.eibk';archive_file.write_bytes(b'encrypted fixture')
        restored=self.service.root/'restores'/'preserved';restored.mkdir();(restored/'fixture').write_text('keep')
        unknown=self.service.work_root/'unknown';unknown.mkdir();(unknown/'keep').write_text('keep')
        self.service.tick()
        self.assertFalse((self.service.work_root/job['id']).exists())
        self.assertEqual('interrupted',self.service.status()['jobs'][0]['state'])
        self.assertTrue(archive_file.exists());self.assertTrue((restored/'fixture').exists());self.assertTrue((unknown/'keep').exists())

    @unittest.skipIf(os.name=='nt','Symlink creation requires Windows developer privileges; reparse boundary still enforced')
    def test_cleanup_refuses_symlink_and_never_runs_under_another_worker_lock(self):
        work=workspace.create(self.service.work_root,uuid.uuid4().hex)
        target=self.root/'outside';target.mkdir();(target/'keep').write_text('keep')
        (work/'indirect').symlink_to(target,target_is_directory=True)
        with self.assertRaises(ValueError):workspace.cleanup(self.service.work_root)
        self.assertEqual('keep',(target/'keep').read_text())
        other=BackupService(self.db)
        with self.service.lock() as held:
            self.assertTrue(held);other.tick()
            with self.assertRaises(DomainError):other.restore_job('0'*32)
        self.assertTrue(work.exists())
        (work/'indirect').unlink();workspace.cleanup(self.service.work_root)

    def test_failed_verification_cleans_plaintext_and_successful_restore_survives_cleanup(self):
        job=self.service.enqueue(uuid.uuid4().hex,'fixture')
        def fail(path,target,*args,**kwargs):
            target.mkdir();(target/'partial.sqlite3').write_text('synthetic plaintext')
            raise ValueError('fixture')
        with patch.object(crypto,'restore',fail):self.service.tick()
        self.assertEqual([],list(self.service.work_root.iterdir()))
        self.assertEqual('failed',self.service.status()['jobs'][0]['state'])
        job=self.service.enqueue(uuid.uuid4().hex,'fixture');self.service.tick();result=self.service.restore_job(job['id'])
        workspace.cleanup(self.service.work_root)
        self.assertTrue((self.db.data_dir/result['directory']/'escritura.sqlite3').exists())

    def test_crash_during_restore_preserves_destination_and_allows_new_isolated_recovery(self):
        job=self.service.enqueue(uuid.uuid4().hex,'fixture');self.service.tick()
        final=self.service.status()['jobs'][0]
        code="from app.db import Database; from app.backups import BackupService; from unittest.mock import patch; import os,sys; s=BackupService(Database(sys.argv[1])); p=patch('app.backup_archive.integrity',side_effect=lambda _:os._exit(23)); p.start(); s.restore_job(sys.argv[2])"
        result=subprocess.run([sys.executable,'-c',code,str(self.db.data_dir),job['id']])
        self.assertEqual(23,result.returncode)
        destination=self.service.root/'restores'/job['id']/'escritura.sqlite3'
        before=archive.sha256(destination)
        self.service.tick()
        self.assertEqual([],list(self.service.work_root.iterdir()))
        self.assertEqual(before,archive.sha256(destination))
        with self.assertRaises(DomainError):self.service.restore_job(job['id'])
        recovered=self.root/'new-recovery'
        crypto.restore(self.service.root/(job['id']+'.eibk'),recovered,final['checksum'],secret=crypto.load_key('fixture',self.db.data_dir))
        with closing(sqlite3.connect(recovered/'escritura.sqlite3')) as conn:
            self.assertEqual('ok',conn.execute('PRAGMA integrity_check').fetchone()[0])

    def test_cleanup_permission_error_is_visible_and_preserves_residue(self):
        work=workspace.create(self.service.work_root,uuid.uuid4().hex)
        (work/'synthetic').write_text('synthetic')
        with patch.object(workspace,'safe_remove',side_effect=PermissionError('fixture')):
            with self.assertRaises(DomainError) as result:self.service.restore_job('0'*32)
        self.assertEqual('backup_cleanup',result.exception.code)
        self.assertTrue((work/'synthetic').exists())

    def test_zip_budget_and_disk_preflight_fail_without_partial_output(self):
        output=self.root/'budget.zip'
        with patch.object(archive,'MAX_BYTES',100):
            with self.assertRaises(DomainError):archive.build(self.db.path,output)
        self.assertFalse(output.exists());self.assertFalse(list(self.root.glob('.snapshot-*')))
        with patch.object(archive.shutil,'disk_usage',return_value=SimpleNamespace(free=1)):
            with self.assertRaises(DomainError):archive.build(self.db.path,output)
        self.assertFalse(output.exists())

    def test_secret_marker_across_blob_chunks_is_refused(self):
        blob=b'Z'*(1024*1024-8)+b'PRIVATE KEY-----'+b'Z'*100
        with closing(sqlite3.connect(self.db.path)) as conn:
            conn.execute("INSERT INTO stored_files(company_id,year,category,filename,sha256,content,created_at,created_by) VALUES(1,2026,'originals','synthetic.txt',?,?,'now','fixture')",('0'*64,blob));conn.commit()
        with self.assertRaises(DomainError) as result:archive.build(self.db.path,self.root/'must-not-exist.zip')
        self.assertEqual('secret_in_original',result.exception.code)

    def test_windows_lock_always_uses_same_byte_without_append_growth(self):
        seen=[]
        fake=SimpleNamespace(LK_NBLCK=1,LK_UNLCK=0,locking=lambda fd,mode,count:seen.append((os.lseek(fd,0,os.SEEK_CUR),count)))
        with patch.object(platform,'WINDOWS',True),patch.dict(sys.modules,msvcrt=fake):
            for _ in range(5):
                with self.service.lock() as held:self.assertTrue(held)
        self.assertTrue(all(row==(0,1) for row in seen));self.assertEqual(1,(self.service.root/'worker.lock').stat().st_size)


class WindowsBoundaryTests(unittest.TestCase):
    def test_dpapi_key_requires_passphrase_and_never_writes_plain_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'fixture.key';records={}
            def fake_dpapi(value,protect):
                if protect:records[b'opaque-dpapi']=value;return b'opaque-dpapi'
                return records[value]
            with patch.object(platform,'WINDOWS',True),patch.object(platform,'dpapi',fake_dpapi):
                with self.assertRaises(ValueError):crypto.create_key(path)
                crypto.create_key(path,'synthetic portable recovery phrase')
                self.assertNotIn(b'synthetic',path.read_bytes())
                self.assertEqual(b'synthetic portable recovery phrase',crypto.read_key(path).value)
                with patch.object(platform,'dpapi',side_effect=ValueError('wrong Windows user')):
                    with self.assertRaises(ValueError):crypto.read_key(path)

    def test_windows_directory_acl_failure_prevents_plaintext_creation(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(platform,'WINDOWS',True),patch.object(platform,'_windows_directory',side_effect=OSError('ACL unavailable')):
            with self.assertRaises(OSError):
                with platform.temporary_directory(tmp,'.fixture-'):self.fail('must not release directory')
            self.assertEqual([],list(Path(tmp).iterdir()))

    def test_unavailable_windows_backup_keeps_other_application_routes_working(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Importing app.api is isolated from any configured operational path.
            with patch.dict(os.environ,ESCRITURA_DATA_DIR=tmp):
                from app.api import create_app
            from fastapi.testclient import TestClient
            with patch.object(platform,'WINDOWS',True),patch('app.backups.BackupService',side_effect=OSError('ACL unavailable')):
                app=create_app(tmp)
            client=TestClient(app)
            self.assertEqual(200,client.get('/api/health').status_code)
            setup=client.post('/api/setup',json={'username':'fixture','password':'Synthetic-only-12345!'}).json()
            client.headers['X-CSRF-Token']=setup['csrf_token']
            self.assertIn('ACLs',client.get('/api/backups').json()['worker_error'])
            self.assertEqual(503,client.put('/api/backups/config',json=CONFIG).status_code)
            client.close()

    @unittest.skipUnless(os.name=='nt','Requires native Windows DPAPI and NTFS ACLs; mocks are not homologation')
    def test_native_windows_dpapi_private_staging_and_portable_passphrase(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);key=root/'fixture.key';password='synthetic native Windows recovery phrase'
            crypto.create_key(key,password)
            self.assertEqual(password.encode(),crypto.read_key(key).value)
            with platform.temporary_directory(root,'.native-') as private:
                (private/'fixture').write_text('synthetic')
                self.assertFalse(platform.reparse(private))
            self.assertFalse(private.exists())


if __name__=='__main__':unittest.main()
