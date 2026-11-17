"""Company A1 UI storage: synthetic PKCS#12 only; no fiscal connections."""
import base64,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization.pkcs12 import serialize_key_and_certificates,PBES
import test_core as base
from test_reception_remote import make_certificate,MATRIX,BRANCH,THIRD,PASSWORD,FakeTransport
from app.reception_transport import RemoteReply
from app.core import DomainError,pack
from app.reception_vault import CompanyA1Vault,SCOPE,dpapi

class VaultTests(unittest.TestCase):
    baseSetUp=base.CoreApiTests.setUp
    tearDownBase=base.CoreApiTests.tearDown
    create_company=base.CoreApiTests.create_company
    activate=base.CoreApiTests.activate
    scope=base.CoreApiTests.scope
    def setUp(self):
        self.baseSetUp();self.a=self.create_company('VAULT','112223330001');self.b=self.create_company('FILIAL','112223330002');self.activate(self.a['id'])
        self.temp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'ESCRITURA_RECEPTION_VAULT_DIR':self.temp.name});self.env.start()
        self.uid=self.client.get('/api/session').json()['user']['id'];self.vault=CompanyA1Vault(self.core.db)
        self.options={'version':0,'environments':{'nfe_distribution':['homologation'],'nfse_adn':['restricted_production']},'allow_adn_procuration':False}
        self.key,self.cert=make_certificate()
        self.raw=serialize_key_and_certificates(b'SYNTHETIC',self.key,self.cert,None,serialization.BestAvailableEncryption(PASSWORD))
    def tearDown(self):self.env.stop();self.temp.cleanup();self.tearDownBase()
    def save(self,**kwargs):
        args=dict(cid=self.a['id'],uid=self.uid,actor='synthetic',raw=self.raw,password=PASSWORD.decode(),options=self.options);args.update(kwargs);return self.vault.save(**args)
    def test_ciphertext_only_public_metadata_identity_reload_and_versioned_update(self):
        result=self.save();self.assertTrue(result['configured']);self.assertEqual(MATRIX,result['holder_cnpj'])
        self.assertEqual(MATRIX,self.vault.load(self.a['id'],MATRIX,'nfe_distribution','homologation').tax_id)
        with self.core.db.read() as conn:
            encoded=json.dumps([dict(r) for r in conn.execute('SELECT * FROM operations')])+json.dumps([dict(r) for r in conn.execute('SELECT * FROM audit')])
        self.assertNotIn(PASSWORD.decode(),encoded);self.assertNotIn(base64.b64encode(self.raw).decode(),encoded);self.assertNotIn('ciphertext',json.dumps(result))
        with self.assertRaises(DomainError):self.save()
        updated=self.vault.update(self.a['id'],self.uid,'synthetic',self.options|{'version':1,'environments':{'nfe_distribution':['production']}})
        self.assertEqual(2,updated['version'])
        self.assertEqual(MATRIX,self.vault.load(self.a['id'],MATRIX,'nfe_distribution','production').tax_id)
        with self.assertRaises(DomainError):self.vault.load(self.a['id'],MATRIX,'nfe_distribution','homologation')
    def test_modern_legacy_and_unprotected_containers_preserve_tls_policy(self):
        legacy=(serialization.PrivateFormat.PKCS12.encryption_builder().kdf_rounds(20000).key_cert_algorithm(PBES.PBESv1SHA1And3KeyTripleDESCBC).hmac_hash(__import__('cryptography.hazmat.primitives.hashes',fromlist=['SHA1']).SHA1()).build(PASSWORD))
        for encryption,password in [(serialization.BestAvailableEncryption(PASSWORD),PASSWORD.decode()),(legacy,PASSWORD.decode()),(serialization.NoEncryption(),'')]:
            raw=serialize_key_and_certificates(b'SYNTHETIC',self.key,self.cert,None,encryption)
            version=self.vault.status(self.a['id'],self.uid)['version']
            self.save(raw=raw,password=password,options=self.options|{'version':version})
            identity=self.vault.load(self.a['id'],MATRIX,'nfe_distribution','homologation')
            import ssl
            self.assertTrue(identity.context.check_hostname);self.assertEqual(ssl.CERT_REQUIRED,identity.context.verify_mode);self.assertGreaterEqual(identity.context.minimum_version,ssl.TLSVersion.TLSv1_2)
    def test_wrong_password_expiry_identity_and_unknown_parameters_never_store(self):
        key,cert=make_certificate(expired=True);expired=serialize_key_and_certificates(b'SYNTHETIC',key,cert,None,serialization.BestAvailableEncryption(PASSWORD))
        key,cert=make_certificate(THIRD);third=serialize_key_and_certificates(b'SYNTHETIC',key,cert,None,serialization.BestAvailableEncryption(PASSWORD))
        for args in [{'password':'WRONG-SYNTHETIC'},{'raw':expired},{'raw':third},{'raw':b'not a PFX'},{'options':self.options|{'username':'not-supported'}},{'options':self.options|{'environments':{'nfse_adn':[{}]}}}]:
            with self.assertRaises(DomainError):self.save(**args)
        with self.core.db.read() as conn:self.assertIsNone(self.vault.row(conn,self.a['id']))
        self.assertFalse(list(Path(self.temp.name).glob('*.key')))
    def test_matrix_branch_tamper_and_company_copy_cannot_broaden_scope(self):
        self.save(cid=self.b['id'])
        self.assertEqual(MATRIX,self.vault.load(self.b['id'],BRANCH,'nfse_adn','restricted_production').tax_id)
        with self.core.db.read() as conn:row=dict(self.vault.row(conn,self.b['id']))
        with self.core.db.transaction() as conn:
            conn.execute('INSERT INTO operations(company_id,scope,key,request_hash,result_json,created_at) VALUES(?,?,?,?,?,?)',(self.a['id'],SCOPE,'a1',row['request_hash'],row['result_json'],row['created_at']))
        with self.assertRaises(DomainError):self.vault.load(self.a['id'],MATRIX,'nfse_adn','restricted_production')
        data=json.loads(row['result_json']);data['tag']=base64.b64encode(os.urandom(16)).decode()
        with self.core.db.transaction() as conn:conn.execute('UPDATE operations SET result_json=? WHERE company_id=? AND scope=?',(pack(data),self.b['id'],SCOPE))
        with self.assertRaises(DomainError):self.vault.load(self.b['id'],BRANCH,'nfse_adn','restricted_production')
    def test_missing_key_is_not_regenerated_and_never_falls_back(self):
        self.save();key=next(Path(self.temp.name).glob('*.key'));key.unlink()
        with patch.object(self.vault.fallback,'load') as fallback:
            with self.assertRaises(DomainError):self.vault.load(self.a['id'],MATRIX,'nfe_distribution','homologation')
            fallback.assert_not_called()
        self.assertFalse(key.exists())
        self.vault.directory=self.core.db.data_dir/'bad-vault'
        with self.assertRaises(DomainError):self.save(options=self.options|{'version':1})
        self.assertFalse((self.core.db.data_dir/'bad-vault').exists())
    def test_api_http_size_csrf_permissions_and_nonactive_company_configuration(self):
        files={'certificate':('synthetic.P12',self.raw,'application/x-pkcs12')};data={'password':PASSWORD.decode(),'options':json.dumps(self.options)}
        self.assertEqual('http',self.client.base_url.scheme)
        r=self.client.post(self.scope('/reception-credential'),data=data,files=files);self.assertEqual(200,r.status_code,r.text);self.assertNotIn('ciphertext',r.text)
        self.assertNotIn(PASSWORD.decode(),r.text);self.assertNotIn(base64.b64encode(self.raw).decode(),r.text)
        self.assertEqual(MATRIX,self.vault.load(self.a['id'],MATRIX,'nfe_distribution','homologation').tax_id)
        r=self.client.put(self.scope('/reception-credential'),json=self.options|{'version':1})
        self.assertEqual(200,r.status_code,r.text);self.assertEqual(2,r.json()['version'])
        r=self.client.post(self.scope('/reception-credential'),data=data,files={'certificate':('large.pfx',b'x'*6000001,'application/octet-stream')});self.assertEqual(400,r.status_code)
        r=self.client.put(self.scope('/reception-settings',self.b['id']),json={'version':0,'nfe_environment':'production','nfse_environment':'restricted_production'});self.assertEqual(200,r.status_code,r.text)
        self.assertEqual(self.a['id'],self.client.get('/api/session').json()['active_company_id'])
        self.assertEqual(0,self.client.get(self.scope('/reception-settings')).json()['preferences']['version'])
        token=self.client.headers.pop('X-CSRF-Token')
        self.assertEqual(403,self.client.post(self.scope('/reception-credential'),data=data,files=files).status_code)
        self.client.headers['X-CSRF-Token']=token
        with self.core.db.transaction() as conn:
            conn.execute("UPDATE users SET role='operator' WHERE id=?",(self.uid,));conn.execute('INSERT OR IGNORE INTO user_companies(user_id,company_id) VALUES(?,?)',(self.uid,self.a['id']))
            conn.execute('INSERT INTO user_permissions(user_id,company_id,routine,action,effect) VALUES(?,?,?,?,?)',(self.uid,self.a['id'],'system.companies','read','allow'))
        self.assertFalse(self.client.get(self.scope('/reception-settings')).json()['can_edit'])
        self.assertEqual(403,self.client.post(self.scope('/reception-credential'),data=data,files=files).status_code)
        self.assertEqual(403,self.client.get(self.scope('/reception-settings',self.b['id'])).status_code)
        self.assertEqual(403,self.client.post(self.scope('/reception-credential',self.b['id']),data=data,files=files).status_code)
        self.assertEqual(2,self.vault.status(self.a['id'],self.uid)['version'])
    def test_http_anonymous_and_cross_origin_uploads_cannot_store_a1(self):
        from fastapi.testclient import TestClient
        files={'certificate':('synthetic.P12',self.raw,'application/x-pkcs12')}
        data={'password':PASSWORD.decode(),'options':json.dumps(self.options)}
        with TestClient(self.app,base_url='http://testserver') as anonymous:
            self.assertEqual(401,anonymous.post(self.scope('/reception-credential'),data=data,files=files).status_code)
        r=self.client.post(self.scope('/reception-credential'),headers={'Origin':'https://foreign.invalid'},data=data,files=files)
        self.assertEqual(403,r.status_code,r.text)
        self.assertFalse(self.vault.status(self.a['id'],self.uid)['configured'])
    def test_changed_a1_during_preparation_cannot_start_remote_attempt(self):
        self.save();service=self.app.state.reception;service.transport=FakeTransport(RemoteReply(200,b'never sent'));original=service.credentials.load
        def changed(*args):
            identity=original(*args);self.vault.update(self.a['id'],self.uid,'synthetic',self.options|{'version':1,'environments':{'nfse_adn':['restricted_production']}});return identity
        with patch.object(service.credentials,'load',side_effect=changed):
            r=self.client.post(self.scope('/reception/nfe_distribution/query'),json={'environment':'homologation','configuration_revision':self.client.get(self.scope('/reception/nfe_distribution'),params={'year':2026}).json()['configuration']['revision'],'period':'2026-11','idempotency_key':'synthetic-race-0001'})
        self.assertEqual(409,r.status_code,r.text);self.assertEqual('stale_credential',r.json()['code']);self.assertEqual([],service.transport.plans)
    @unittest.skipUnless(os.name=='nt','DPAPI requires Windows; no simulation counted as physical validation')
    def test_windows_dpapi_current_user_round_trip_and_tamper(self):
        key=os.urandom(32);protected=dpapi(key,True);self.assertNotIn(key,protected);self.assertEqual(key,dpapi(protected,False))
        with self.assertRaises(DomainError):dpapi(bytes(len(protected)),False)
if __name__=='__main__':unittest.main()
