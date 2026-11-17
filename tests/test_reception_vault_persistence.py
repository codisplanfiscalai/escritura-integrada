"""Linux recovery rehearsal; synthetic certificates and isolated files only.

Process restart is real; container mounts/EROFS are modeled because Docker is
not required by the unit suite. Never performs a fiscal or cloud request.
"""
import base64
import errno
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import test_reception_vault as fixture
from test_reception_remote import MATRIX,BRANCH,PASSWORD
from app import backup_crypto as crypto
from app.core import DomainError
from app.db import Database
from app.reception_vault import CompanyA1Vault,SCOPE

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(sys.platform.startswith('linux'),'Linux filesystem/container rehearsal; native DPAPI/Apple require their own execution')
class VaultPersistenceTests(unittest.TestCase):
    baseSetUp=fixture.VaultTests.baseSetUp
    tearDownBase=fixture.VaultTests.tearDownBase
    create_company=fixture.VaultTests.create_company
    activate=fixture.VaultTests.activate
    scope=fixture.VaultTests.scope
    setUp=fixture.VaultTests.setUp
    tearDown=fixture.VaultTests.tearDown
    save=fixture.VaultTests.save

    def private_file(self,path,raw):
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'wb') as out:out.write(raw)

    def snapshot(self,parent):
        secret=crypto.Secret('raw',os.urandom(32))
        encrypted=parent/'synthetic.eibk'
        checksum=crypto.build(self.core.db.path,encrypted,'synthetic-backup',secret)
        restored=parent/'restored-data'
        manifest=crypto.restore(encrypted,restored,checksum,secret=secret)
        self.assertEqual({'escritura.sqlite3'},set(manifest['files']))
        return Database(restored),secret,encrypted,checksum

    def test_new_process_reopens_same_database_and_persisted_key_without_fiscal_network(self):
        self.save();self.save(cid=self.b['id'])
        key=next(Path(self.temp.name).glob('*.key'));before=hashlib.sha256(key.read_bytes()).hexdigest()
        program='''import json,sys
from app.db import Database
from app.reception_vault import CompanyA1Vault
from app.core import DomainError
try:
 vault=CompanyA1Vault(Database(sys.argv[1]),directory=sys.argv[2])
 a=vault.load(int(sys.argv[3]),sys.argv[4],'nfe_distribution','homologation')
 print(json.dumps({'loaded':a.tax_id==sys.argv[4],'tls_minimum':a.context.minimum_version.name}))
except DomainError as error:
 print(json.dumps({'code':error.code}));raise SystemExit(1)
'''
        result=subprocess.run([sys.executable,'-c',program,str(self.core.db.data_dir),self.temp.name,str(self.a['id']),MATRIX],cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertEqual({'loaded':True,'tls_minimum':'TLSv1_2'},json.loads(result.stdout))
        self.assertNotIn(PASSWORD.decode(),result.stdout+result.stderr)
        self.assertEqual(before,hashlib.sha256(key.read_bytes()).hexdigest())
        self.assertEqual(1,len(list(Path(self.temp.name).glob('*.key'))))
        reopened=CompanyA1Vault(Database(self.core.db.data_dir),directory=self.temp.name)
        self.assertEqual(MATRIX,reopened.load(self.b['id'],BRANCH,'nfse_adn','restricted_production').tax_id)

    def test_new_empty_mount_loses_access_and_does_not_allow_silent_reenrollment(self):
        self.save();self.save(cid=self.b['id'])
        with self.core.db.read() as conn:
            before=[tuple(r) for r in conn.execute('SELECT company_id,result_json FROM operations WHERE scope=? ORDER BY company_id',(SCOPE,))]
            installation=conn.execute("SELECT value FROM meta WHERE key='reception_vault_id'").fetchone()['value']
        with tempfile.TemporaryDirectory() as empty,patch.dict(os.environ,ESCRITURA_RECEPTION_VAULT_DIR=empty):
            fresh=CompanyA1Vault(Database(self.core.db.data_dir))
            with patch.object(fresh.fallback,'load') as fallback:
                for cid,target in [(self.a['id'],MATRIX),(self.b['id'],BRANCH)]:
                    with self.assertRaises(DomainError) as error:fresh.load(cid,target,'nfe_distribution','homologation')
                    self.assertEqual('reception_vault_unavailable',error.exception.code)
                fallback.assert_not_called()
            # Even the correct original PFX/password must not silently reset the global key.
            with self.assertRaises(DomainError):fresh.save(self.a['id'],self.uid,'synthetic',self.raw,PASSWORD.decode(),self.options|{'version':1})
            self.assertEqual([],list(Path(empty).iterdir()))
            self.assertTrue(fresh.status(self.a['id'],self.uid)['configured'])  # Stored, not a readiness guarantee.
            check=self.client.post(self.scope('/reception/nfe_distribution/check'),json={'environment':'homologation'})
            self.assertEqual(200,check.status_code);self.assertFalse(check.json()['ready'])
            self.assertEqual(200,self.client.get('/api/health').status_code)
        with self.core.db.read() as conn:
            self.assertEqual(before,[tuple(r) for r in conn.execute('SELECT company_id,result_json FROM operations WHERE scope=? ORDER BY company_id',(SCOPE,))])
            self.assertEqual(installation,conn.execute("SELECT value FROM meta WHERE key='reception_vault_id'").fetchone()['value'])

    def test_encrypted_backup_restores_ciphertext_but_requires_separate_correct_vault_key(self):
        self.save();self.save(cid=self.b['id'])
        source_key=next(Path(self.temp.name).glob('*.key'))
        with tempfile.TemporaryDirectory() as work:
            work=Path(work);db,secret,encrypted,checksum=self.snapshot(work)
            with crypto.authenticated_payload(encrypted,checksum,secret=secret,work_dir=work) as payload:
                with zipfile.ZipFile(payload) as archive:self.assertEqual({'manifest.json','escritura.sqlite3'},set(archive.namelist()))
            self.assertFalse(list(db.data_dir.rglob('*.key')))
            with db.read() as conn:
                self.assertEqual(0,conn.execute('SELECT count(*) FROM sessions').fetchone()[0])
                self.assertEqual(2,conn.execute('SELECT count(*) FROM operations WHERE scope=?',(SCOPE,)).fetchone()[0])
            missing=work/'missing-vault';missing.mkdir(mode=0o700)
            restored=CompanyA1Vault(db,directory=missing)
            with self.assertRaises(DomainError):restored.load(self.a['id'],MATRIX,'nfe_distribution','homologation')
            # A backup-envelope key is independent; placing it under the A1 filename cannot decrypt the vault.
            self.private_file(missing/source_key.name,secret.value)
            with self.assertRaises(DomainError):restored.load(self.a['id'],MATRIX,'nfe_distribution','homologation')
            correct=work/'recovered-vault';correct.mkdir(mode=0o700)
            self.private_file(correct/source_key.name,source_key.read_bytes())
            recovered=CompanyA1Vault(db,directory=correct)
            for cid,target in [(self.a['id'],MATRIX),(self.b['id'],BRANCH)]:
                self.assertEqual(MATRIX,recovered.load(cid,target,'nfse_adn','restricted_production').tax_id)
            with db.read() as conn:
                text='\n'.join(r['result_json'] for r in conn.execute('SELECT result_json FROM operations WHERE scope=?',(SCOPE,)))
            self.assertNotIn(PASSWORD.decode(),text);self.assertNotIn(base64.b64encode(self.raw).decode(),text)
            self.assertEqual(hashlib.sha256(source_key.read_bytes()).digest(),hashlib.sha256((correct/source_key.name).read_bytes()).digest())

    def test_wrong_vault_key_preserves_all_rows_and_never_falls_back(self):
        self.save();source_key=next(Path(self.temp.name).glob('*.key'))
        with self.core.db.read() as conn:before=self.vault.row(conn,self.a['id'])['result_json']
        with tempfile.TemporaryDirectory() as other:
            wrong=Path(other)/source_key.name;self.private_file(wrong,os.urandom(32));digest_before=hashlib.sha256(wrong.read_bytes()).hexdigest()
            vault=CompanyA1Vault(self.core.db,directory=other)
            with patch.object(vault.fallback,'load') as fallback:
                with self.assertRaises(DomainError):vault.load(self.a['id'],MATRIX,'nfe_distribution','homologation')
                fallback.assert_not_called()
            self.assertEqual(digest_before,hashlib.sha256(wrong.read_bytes()).hexdigest())
        with self.core.db.read() as conn:self.assertEqual(before,self.vault.row(conn,self.a['id'])['result_json'])

    def test_readonly_root_failure_rolls_back_without_creating_vault_or_installation_id(self):
        blocked=Path(self.temp.name)/'synthetic-readonly-root'
        with patch.object(self.vault,'key_root',return_value=blocked),patch('app.reception_vault.Path.mkdir',side_effect=OSError(errno.EROFS,'synthetic readonly boundary')):
            with self.assertRaises(DomainError) as error:self.save()
            self.assertEqual('reception_vault_unavailable',error.exception.code)
        self.assertFalse(blocked.exists())
        with self.core.db.read() as conn:
            self.assertIsNone(self.vault.row(conn,self.a['id']))
            self.assertIsNone(conn.execute("SELECT value FROM meta WHERE key='reception_vault_id'").fetchone())

    def test_recovered_key_inside_data_or_symlink_root_is_refused(self):
        self.save();source_key=next(Path(self.temp.name).glob('*.key'))
        forbidden=self.core.db.data_dir/'vault';forbidden.mkdir(mode=0o700);self.private_file(forbidden/source_key.name,source_key.read_bytes())
        with self.assertRaises(DomainError):CompanyA1Vault(self.core.db,directory=forbidden).load(self.a['id'],MATRIX,'nfe_distribution','homologation')
        link=self.core.db.data_dir.parent/('vault-link-'+self.core.db.data_dir.name);link.symlink_to(self.temp.name,target_is_directory=True)
        self.addCleanup(link.unlink)
        with self.assertRaises(DomainError):CompanyA1Vault(self.core.db,directory=link).load(self.a['id'],MATRIX,'nfe_distribution','homologation')

    def test_optional_compose_contract_keeps_existing_data_and_security_defaults(self):
        override=json.loads((ROOT/'deploy/compose.reception-vault.yaml').read_text())
        self.assertEqual({'services','volumes'},set(override));self.assertEqual({'app'},set(override['services']))
        app=override['services']['app'];self.assertEqual({'environment','volumes'},set(app))
        target=app['environment']['ESCRITURA_RECEPTION_VAULT_DIR'];self.assertEqual('/run/escritura/reception-vault',target)
        mount,=app['volumes'];self.assertEqual('volume',mount['type']);self.assertEqual(target,mount['target'])
        self.assertEqual('reception_vault',mount['source'])
        self.assertEqual({'reception_vault':{}},override['volumes'])  # Compose namespaces by project.
        for relative in ['compose.yaml','deploy/develop/compose.yaml','deploy/production/compose.yaml']:
            with self.subTest(template=relative):
                original=json.loads((ROOT/relative).read_text())['services']['app']
                self.assertTrue(original['read_only']);self.assertIn('ALL',original['cap_drop'])
                self.assertNotIn('ESCRITURA_RECEPTION_VAULT_DIR',original['environment'])
                self.assertTrue(all(v['target']!=target for v in original['volumes']))
                self.assertTrue(any(v['target']=='/data' for v in original['volumes']))

if __name__=='__main__':unittest.main()
