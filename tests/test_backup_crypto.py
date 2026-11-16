"""Local synthetic cryptographic recovery: no keys or plaintext retained in artifacts."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid

from app import backup_archive as archive, backup_crypto as crypto
from app.backups import BackupService
from app.core import DomainError
from app.db import Database


class CryptoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.db=Database(self.root/'data')
        self.keyring=self.root/'keys';self.keyring.mkdir(mode=0o700)
        self.keyfile=self.keyring/'first.key';crypto.create_key(self.keyfile, 'synthetic Windows recovery phrase' if os.name=='nt' else None)
        self.key=crypto.read_key(self.keyfile)
        self.env=patch.dict(os.environ,ESCRITURA_BACKUP_KEYRING_DIR=str(self.keyring),ESCRITURA_BACKUP_FIXTURE='{"access_token":"synthetic"}')
        self.env.start();self.addCleanup(self.env.stop)
        self.plain=self.root/'synthetic.zip';archive.build(self.db.path,self.plain)

    def encrypted(self,secret=None):
        target=self.root/(uuid.uuid4().hex+'.eibk')
        checksum=crypto.encrypt(self.plain,target,'first',secret or self.key)
        return target,checksum

    def test_ciphertext_is_randomized_and_key_is_not_serialized(self):
        first,one=self.encrypted();second,two=self.encrypted()
        self.assertNotEqual(one,two)
        self.assertNotIn(self.key.value,first.read_bytes())
        self.assertNotIn(b'SQLite format 3',first.read_bytes())
        if os.name!='nt':self.assertEqual(0o600,first.stat().st_mode&0o777)
        crypto.restore(first,self.root/'restored',one,secret=self.key)
        with closing(sqlite3.connect(self.root/'restored'/'escritura.sqlite3')) as conn:
            self.assertEqual('ok',conn.execute('PRAGMA integrity_check').fetchone()[0])
        self.assertFalse(list(self.root.glob('.decrypt-*')))

    def test_corruption_in_every_envelope_region_fails_even_with_new_outer_checksum(self):
        source,_=self.encrypted();raw=source.read_bytes()
        with source.open('rb') as stream:_,aad,_,_=crypto._header(stream)
        # Nonce/salt header, encrypted bytes, tag, format, truncation and append.
        for label,blob in [('magic',b'X'+raw[1:]),('header',raw[:25]+bytes([raw[25]^1])+raw[26:]),
                           ('cipher',raw[:len(aad)]+bytes([raw[len(aad)]^1])+raw[len(aad)+1:]),
                           ('tag',raw[:-1]+bytes([raw[-1]^1])),('truncated',raw[:-1]),('appended',raw+b'x')]:
            with self.subTest(label=label):
                path=self.root/(label+'.eibk');path.write_bytes(blob)
                destination=self.root/('recover-'+label)
                with self.assertRaises((ValueError,KeyError,TypeError)):
                    crypto.restore(path,destination,archive.sha256(path),secret=self.key)
                self.assertFalse(destination.exists())
                self.assertFalse(list(self.root.glob('.decrypt-*')))

    def test_wrong_key_and_wrong_password_never_create_or_overwrite_destination(self):
        for secret,wrong in [(self.key,crypto.Secret('raw',os.urandom(32))),
                             (crypto.Secret('scrypt-17',b'synthetic long correct passphrase'),crypto.Secret('scrypt-17',b'synthetic long incorrect passphrase'))]:
            source,checksum=self.encrypted(secret)
            destination=self.root/uuid.uuid4().hex
            with self.assertRaises(ValueError):crypto.restore(source,destination,checksum,secret=wrong)
            self.assertFalse(destination.exists())
            crypto.restore(source,destination,checksum,secret=secret)
            before=archive.sha256(destination/'escritura.sqlite3')
            with self.assertRaises(FileExistsError):crypto.restore(source,destination,checksum,secret=wrong)
            self.assertEqual(before,archive.sha256(destination/'escritura.sqlite3'))

    @unittest.skipIf(os.name=='nt','POSIX permissions; Windows DPAPI covered separately')
    def test_key_permissions_symlinks_missing_and_location(self):
        self.assertEqual(self.key,crypto.load_key('first',self.db.data_dir))
        self.keyfile.chmod(0o644)
        with self.assertRaises(DomainError):crypto.load_key('first',self.db.data_dir)
        self.keyfile.chmod(0o600)
        (self.keyring/'link.key').symlink_to(self.keyfile)
        for key in ('link','absent','../first'):
            with self.assertRaises(DomainError):crypto.load_key(key,self.db.data_dir)
        with patch.dict(os.environ,ESCRITURA_BACKUP_KEYRING_DIR=str(self.db.data_dir)):
            with self.assertRaises(DomainError):crypto.load_key('first',self.db.data_dir)
        before=self.keyfile.read_bytes()
        with self.assertRaises(FileExistsError):crypto.create_key(self.keyfile, 'synthetic Windows recovery phrase' if os.name=='nt' else None)
        self.assertEqual(before,self.keyfile.read_bytes())

    def test_rotation_and_legacy_recovery_new_jobs_never_fallback(self):
        service=BackupService(self.db,uploader=lambda *args:None)
        config=dict(provider='dropbox',credential_ref='ESCRITURA_BACKUP_FIXTURE',folder='/fixture',encryption_key_id='first')
        service.configure(config)
        first=service.enqueue(uuid.uuid4().hex,'fixture');service.tick()
        crypto.create_key(self.keyring/'second.key', 'synthetic second Windows recovery phrase' if os.name=='nt' else None)
        service.configure({**config,'encryption_key_id':'second'})
        second=service.enqueue(uuid.uuid4().hex,'fixture');service.tick()
        service.restore_job(first['id']);service.restore_job(second['id'])
        # Historical row retains the legacy config and ZIP, never guessed from corrupt ciphertext.
        old=uuid.uuid4().hex
        checksum=archive.build(self.db.path,service.root/(old+'.zip'))
        with service.connection() as conn:
            conn.execute("INSERT INTO jobs(id,intent,config,state,created,actor,checksum) VALUES(?,?,?,'completed',1,'fixture',?)",(old,old,json.dumps({k:v for k,v in config.items() if k!='encryption_key_id'}),checksum))
        service.restore_job(old)
        (self.keyring/'second.key').unlink()
        service.enqueue(uuid.uuid4().hex,'fixture');service.tick()
        self.assertEqual('failed',service.status()['jobs'][0]['state'])
        self.assertFalse(list(service.root.glob('.encrypt-*')))

    def test_offline_cli_recovery_and_password_requires_no_echo_terminal(self):
        source,checksum=self.encrypted()
        target=self.root/'offline-recovered'
        result=subprocess.run([sys.executable,'-m','app.backup_crypto','restore',str(source),str(target),'--sha256',checksum,'--key-file',str(self.keyfile)],capture_output=True,text=True)
        self.assertEqual(0,result.returncode,result.stderr)
        before=archive.sha256(target/'escritura.sqlite3')
        repeated=subprocess.run([sys.executable,'-m','app.backup_crypto','restore',str(source),str(target),'--sha256',checksum,'--key-file',str(self.keyfile)],capture_output=True,text=True)
        self.assertEqual(1,repeated.returncode)
        self.assertEqual(before,archive.sha256(target/'escritura.sqlite3'))
        denied=subprocess.run([sys.executable,'-m','app.backup_crypto','restore',str(source),str(self.root/'password-stdin'),'--sha256',checksum,'--password'],input='synthetic-secret-must-not-echo',capture_output=True,text=True)
        self.assertEqual(1,denied.returncode)
        self.assertNotIn('synthetic-secret-must-not-echo',denied.stdout+denied.stderr)
        self.assertFalse((self.root/'password-stdin').exists())

    def test_size_bounds_and_cancellation_clean_partial_ciphertext(self):
        destination=self.root/'too-large.eibk'
        with patch.object(archive,'MAX_BYTES',self.plain.stat().st_size):
            with self.assertRaises(DomainError):crypto.encrypt(self.plain,destination,'first',self.key)
        self.assertFalse(destination.exists())
        with self.assertRaises(DomainError):crypto.encrypt(self.plain,destination,'first',self.key,lambda:True)
        self.assertFalse(destination.exists())
        with patch.object(archive,'MAX_DATABASE',1024):
            with self.assertRaises(DomainError):archive.build(self.db.path,self.root/'over-limit.zip')
        self.assertFalse((self.root/'over-limit.zip').exists())


if __name__=='__main__':unittest.main()
