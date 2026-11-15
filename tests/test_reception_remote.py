"""mTLS and capture against synthetic credentials/servers only, never fiscal hosts."""
import contextlib
from datetime import datetime, timedelta, timezone
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import json
import os
from pathlib import Path
import socket
import ssl
import tempfile
import threading
import unittest
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization.pkcs12 import serialize_key_and_certificates
from cryptography.x509.oid import NameOID, ObjectIdentifier

import test_core as base
from test_reception import FIXTURE, SUMMARY, response
from app.core import DomainError, cnpj_digits, pack
from app.reception import adn_request, nfe_request
from app.reception_credentials import ClientIdentity, LocalA1Credentials, adn_access_mode
from app.reception_service import ReceptionService, STATE_SCOPE, RUN_SCOPE
from app.reception_transport import MtlsTransport, RemoteReply

MATRIX = '11222333000181'
BRANCH = '112223330002' + cnpj_digits('112223330002')
THIRD = '998887770001' + cnpj_digits('998887770001')
PASSWORD = b'SYNTHETIC-ONLY-NOT-A-REAL-CREDENTIAL'


def make_certificate(tax_id=MATRIX, issuer=None, expired=False, malformed=False, der_tag=0x0c):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    now=datetime.now(timezone.utc)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'CERTIFICADO SINTETICO SEM VALOR FISCAL')])
    if issuer is None:
        issuer=(key,name)
    other=bytes([der_tag,14])+tax_id.encode() if not malformed else b'\x0c\x03abc'
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(issuer[1]).public_key(key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=2))
          .not_valid_after(now-timedelta(days=1) if expired else now+timedelta(days=1))
          .add_extension(x509.SubjectAlternativeName([x509.OtherName(ObjectIdentifier('2.16.76.1.3.3'),other)]),critical=False)
          .sign(issuer[0],hashes.SHA256()))
    return key,cert


def write_private(path,data):
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'wb') as file:file.write(data)


class CredentialTests(unittest.TestCase):
    def test_matrix_branch_relationship_is_separate_from_procuration(self):
        for target,holder,mode in [(MATRIX,MATRIX,'InscricaoCertificado'),(BRANCH,MATRIX,'CnpjBase'),(MATRIX,BRANCH,'CnpjBase')]:
            self.assertEqual(mode,adn_access_mode(target,holder))
            request=adn_request(target,'restricted_production','0',certificate_tax_id=holder)
            self.assertEqual(mode,request['expected_authorization_mode'])
            self.assertEqual(target!=holder,'cnpjConsulta='+target in request['url'])
            self.assertFalse(request['authorization_verified'])
        with self.assertRaises(DomainError):adn_access_mode(THIRD,MATRIX)
        self.assertEqual('Procuracao',adn_access_mode(THIRD,MATRIX,True))
        self.assertFalse(adn_request(THIRD,'production','0',certificate_tax_id=MATRIX,allow_procuration=True)['authorization_verified'])
        for invalid in [MATRIX[:-1]+'0','00000000000000','12ABC34501DE35','12345678909']:
            with self.assertRaises(DomainError):adn_access_mode(invalid,MATRIX)

    def profile(self,root,target=MATRIX,holder=MATRIX,expired=False,malformed=False,allow=False):
        key,cert=make_certificate(holder,expired=expired,malformed=malformed)
        blob=serialize_key_and_certificates(b'synthetic',key,cert,None,serialization.BestAvailableEncryption(PASSWORD))
        write_private(root/'client.pfx',blob)
        config={'companies':{'1':{'tax_id':target,'pfx_file':'client.pfx','password_env':'ESCRITURA_RECEPTION_PASSWORD_SYNTHETIC',
                    'environments':{'nfse_adn':['restricted_production'],'nfe_distribution':['homologation']},'allow_adn_procuration':allow}}}
        write_private(root/'profiles.json',json.dumps(config).encode())
        return cert

    def test_macos_intel_uses_validated_profile_then_native_backend(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'ESCRITURA_RECEPTION_PASSWORD_SYNTHETIC':PASSWORD.decode()}):
            root=Path(directory);self.profile(root)
            with patch('app.reception_credentials.sys.platform','darwin'),patch('app.reception_credentials.platform.machine',return_value='x86_64'):
                with patch('app.reception_native.NativeA1Bridge.load',return_value='synthetic native identity') as load:
                    self.assertEqual('synthetic native identity',LocalA1Credentials(root).load(1,MATRIX,'nfse_adn','restricted_production'))
                self.assertEqual(MATRIX,load.call_args.args[2])
                self.assertEqual(PASSWORD.decode(),load.call_args.args[1])
                self.assertTrue(load.call_args.args[0])
                with patch('app.reception_native.NativeA1Bridge.load') as load,self.assertRaises(DomainError):
                    LocalA1Credentials(root).load(2,MATRIX,'nfse_adn','restricted_production')
                load.assert_not_called()

    def test_pfx_uses_actual_certificate_cnpj_and_ephemeral_key_is_removed(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'ESCRITURA_RECEPTION_PASSWORD_SYNTHETIC':PASSWORD.decode()}):
            root=Path(directory);self.profile(root,target=BRANCH)
            created=[]
            real=tempfile.TemporaryDirectory
            def track(*args,**kwargs):
                temp=real(*args,**kwargs);created.append(Path(temp.name));return temp
            with patch('app.reception_credentials.tempfile.TemporaryDirectory',side_effect=track):
                identity=LocalA1Credentials(root).load(1,BRANCH,'nfse_adn','restricted_production')
            self.assertEqual(MATRIX,identity.tax_id)
            self.assertTrue(identity.context.check_hostname)
            self.assertEqual(ssl.CERT_REQUIRED,identity.context.verify_mode)
            self.assertEqual(ssl.TLSVersion.TLSv1_2,identity.context.minimum_version)
            self.assertTrue(created);self.assertTrue(all(not p.exists() for p in created))
            self.assertNotIn(PASSWORD.decode(),repr(identity))

    def test_profile_never_silently_switches_company_or_environment(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'ESCRITURA_RECEPTION_PASSWORD_SYNTHETIC':PASSWORD.decode()}):
            root=Path(directory);self.profile(root)
            for cid,target,provider,env in [(2,MATRIX,'nfse_adn','restricted_production'),(1,BRANCH,'nfse_adn','restricted_production'),(1,MATRIX,'nfse_adn','production'),(1,MATRIX,'nfe_distribution','production')]:
                with self.assertRaises(DomainError):LocalA1Credentials(root).load(cid,target,provider,env)
            with patch.dict(os.environ,{'ESCRITURA_RECEPTION_PASSWORD_SYNTHETIC':'WRONG-SYNTHETIC-PASSWORD'}):
                with self.assertRaises(DomainError) as error:LocalA1Credentials(root).load(1,MATRIX,'nfse_adn','restricted_production')
                self.assertNotIn('WRONG',str(error.exception.detail))
                self.assertNotIn(str(root),str(error.exception.detail))

    def test_invalid_certificate_and_external_root_require_explicit_procuration(self):
        for expired,malformed,holder,allow,code in [(True,False,MATRIX,False,'reception_certificate_expired'),(False,True,MATRIX,False,'reception_certificate_identity'),(False,False,THIRD,False,'reception_procuration_required')]:
            with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'ESCRITURA_RECEPTION_PASSWORD_SYNTHETIC':PASSWORD.decode()}):
                root=Path(directory);self.profile(root,holder=holder,expired=expired,malformed=malformed,allow=allow)
                with self.assertRaises(DomainError) as error:LocalA1Credentials(root).load(1,MATRIX,'nfse_adn','restricted_production')
                self.assertEqual(code,error.exception.code)
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'ESCRITURA_RECEPTION_PASSWORD_SYNTHETIC':PASSWORD.decode()}):
            root=Path(directory);self.profile(root,holder=THIRD,allow=True)
            self.assertTrue(LocalA1Credentials(root).load(1,MATRIX,'nfse_adn','restricted_production').allow_procuration)
            with self.assertRaises(DomainError):LocalA1Credentials(root).load(1,MATRIX,'nfe_distribution','homologation')

    @unittest.skipIf(os.name=='nt','POSIX permissions; Windows ACL verification remains operator responsibility')
    def test_insecure_file_modes_and_symlinks_are_refused(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'ESCRITURA_RECEPTION_PASSWORD_SYNTHETIC':PASSWORD.decode()}):
            root=Path(directory);self.profile(root)
            (root/'client.pfx').chmod(0o644)
            with self.assertRaises(DomainError):LocalA1Credentials(root).load(1,MATRIX,'nfse_adn','restricted_production')
            (root/'client.pfx').chmod(0o600)
            (root/'client.pfx').rename(root/'real.pfx');(root/'client.pfx').symlink_to(root/'real.pfx')
            with self.assertRaises(DomainError):LocalA1Credentials(root).load(1,MATRIX,'nfse_adn','restricted_production')


class FakeCredentials:
    def __init__(self,holder=MATRIX,allow=False):self.holder,self.allow,self.calls=holder,allow,0
    def load(self,*args):self.calls+=1;return ClientIdentity(self.holder,ssl.create_default_context(),self.allow)


class FakeTransport:
    def __init__(self,reply):self.reply,self.plans=reply,[]
    def send(self,plan,identity):
        self.plans.append(plan)
        if isinstance(self.reply,Exception):raise self.reply
        return self.reply


class CaptureApiTests(unittest.TestCase):
    setUpBase=base.CoreApiTests.setUp
    tearDown=base.CoreApiTests.tearDown
    create_company=base.CoreApiTests.create_company
    activate=base.CoreApiTests.activate
    scope=base.CoreApiTests.scope

    def setUp(self):
        self.setUpBase()
        self.a=self.create_company('CAPTURE','112223330001')
        self.b=self.create_company('FILIAL','112223330002')
        self.activate(self.a['id'])
        self.clock=[1000.]
        self.raw=FIXTURE.read_bytes().replace(b'12345678000195',MATRIX.encode())
        self.envelope=response([('1','procNFe_v4.00.xsd',self.raw),('2','resNFe_v1.01.xsd',SUMMARY)],last='2',maximum='3')
        self.transport=FakeTransport(RemoteReply(200,self.envelope))
        self.service=ReceptionService(self.core,FakeCredentials(),self.transport,lambda:self.clock[0])
        self.app.state.reception=self.service
        self.uid=self.client.get('/api/session').json()['user']['id']

    def query(self,key='synthetic-0001',provider='nfe_distribution',environment='homologation',status=200):
        r=self.client.post(self.scope('/imports/reception/query'),json={'provider':provider,'environment':environment,'period':'2026-11','idempotency_key':key})
        self.assertEqual(status,r.status_code,r.text)
        return r.json()

    def state(self,provider='nfe_distribution',environment='homologation',cid=None,target=None):
        with self.core.db.read() as conn:
            return self.service._state(conn,cid or self.a['id'],provider+':'+environment+':'+(target or MATRIX))

    def test_query_receipt_cursor_and_preparation_use_canonical_services(self):
        received=self.query()
        self.assertEqual('received',received['state'])
        self.assertEqual('shared_database_only',received['coordination']['scope'])
        self.assertFalse(received['coordination']['external_systems_coordinated'])
        self.assertEqual('NFE_EXTERNAL_NSU_COORDINATION',received['coordination']['warning_code'])
        self.assertEqual('000000000000002',received['cursor_after'])
        self.assertTrue(received['cursor_advanced'])
        self.assertEqual([],self.core.documents(self.a['id']))
        self.assertEqual([],self.core.journals(self.a['id']))
        original=self.client.get(self.scope('/imports/reception/receipts/synthetic-0001/download'))
        self.assertEqual(self.envelope,original.content)
        preview=self.client.post(self.scope('/imports/reception/receipts/synthetic-0001/preview'),json={'period':'2026-11','options':{'posting_date':'2026-11-06'}})
        self.assertEqual(200,preview.status_code,preview.text)
        self.assertEqual(1,len(preview.json()['documents']))
        self.assertEqual('2026-11-06',preview.json()['documents'][0]['posting_date'])
        self.assertEqual('summary',preview.json()['reception'][0]['entries'][1]['kind'])
        self.assertEqual([],self.core.documents(self.a['id']))
        self.assertEqual(1,len(self.transport.plans))
        self.assertTrue(self.query()['duplicate'])
        self.assertEqual(1,len(self.transport.plans))
        self.query(key='synthetic-0002',status=429)
        self.clock[0]+=61
        self.transport.reply=RemoteReply(200,response(status='137',last='2',maximum='2'))
        self.assertEqual('000000000000002',self.query(key='synthetic-0002')['cursor_after'])
        self.assertIn(b'000000000000002',self.transport.plans[-1]['body'])

    def test_matrix_branch_queries_share_certificate_without_sharing_cursor(self):
        self.transport.reply=RemoteReply(400,json.dumps({'Erros':[{'Codigo':'E2220'}]}).encode())
        own=self.query(provider='nfse_adn',environment='restricted_production')
        self.assertNotIn('cnpjConsulta',self.transport.plans[-1]['url'])
        self.activate(self.b['id'])
        r=self.client.post(self.scope('/imports/reception/query',self.b['id']),json={'provider':'nfse_adn','environment':'restricted_production','period':'2026-11','idempotency_key':'synthetic-branch'})
        self.assertEqual(200,r.status_code,r.text)
        self.assertIn('cnpjConsulta='+BRANCH,self.transport.plans[-1]['url'])
        self.assertEqual('CnpjBase',r.json()['expected_authorization_mode'])
        self.assertEqual('000000000000000',r.json()['cursor_after'])
        self.assertFalse(r.json()['authorization_verified'])
        self.assertEqual(404,self.client.get(self.scope('/imports/reception/receipts/synthetic-0001',self.b['id'])).status_code)

    def test_third_party_and_e2245_preserve_cursor_and_do_not_assume_authorization(self):
        self.service.credentials=FakeCredentials(THIRD,False)
        self.query(provider='nfse_adn',environment='restricted_production',status=409)
        self.assertEqual([],self.transport.plans)
        self.service.credentials=FakeCredentials(THIRD,True)
        self.transport.reply=RemoteReply(400,json.dumps({'TipoConsulta':'InscricaoCertificado','Erros':[{'Codigo':'E2245','Descricao':'synthetic private diagnostic'}]}).encode())
        result=self.query(provider='nfse_adn',environment='restricted_production')
        self.assertEqual('authorization_pending',result['state'])
        self.assertEqual('Procuracao',result['expected_authorization_mode'])
        self.assertFalse(result['authorization_verified'])
        self.assertFalse(result['cursor_advanced'])
        self.assertNotIn('private diagnostic',json.dumps(result))
        self.assertEqual('000000000000000',self.state('nfse_adn','restricted_production')['cursor'])

    def test_unknown_adn_success_is_retained_without_inventing_schema(self):
        raw=b'{"TipoConsulta":"CnpjBase","unverified_fixture_field":"opaque received bytes"}'
        self.service.credentials=FakeCredentials(BRANCH)
        self.transport.reply=RemoteReply(200,raw)
        result=self.query(provider='nfse_adn',environment='restricted_production')
        self.assertEqual('received_unparsed',result['state'])
        self.assertFalse(result['cursor_advanced'])
        self.assertEqual(raw,self.client.get(self.scope('/imports/reception/receipts/synthetic-0001/download')).content)
        r=self.client.post(self.scope('/imports/reception/receipts/synthetic-0001/preview'),json={'period':'2026-11'})
        self.assertEqual(409,r.status_code)
        self.assertEqual([],self.core.documents(self.a['id']))

    def test_timeout_status_656_redirect_and_invalid_response_preserve_cursor(self):
        cases=[TimeoutError('private path or secret'),RemoteReply(200,response(status='656')),RemoteReply(302,b'https://forbidden.invalid'),RemoteReply(200,b'<invalid>'),RemoteReply(200,self.envelope.replace(b'>2</ns0:tpAmb>',b'>1</ns0:tpAmb>')),RemoteReply(429,b'limited',7200)]
        for i,reply in enumerate(cases):
            with self.subTest(reply=i):
                self.transport.reply=reply;self.clock[0]+=10000
                result=self.query(key=f'synthetic-error-{i}')
                self.assertEqual('000000000000000',result['cursor_after'])
                self.assertFalse(result['cursor_advanced'])
                self.assertNotIn('private path',json.dumps(result))
                self.assertEqual(0,self.state()['lease_until'])
                self.query(key=f'synthetic-next-{i}',status=429)
                if isinstance(reply,RemoteReply):
                    self.assertEqual(reply.body,self.client.get(self.scope(f'/imports/reception/receipts/synthetic-error-{i}/download')).content)

    def test_failed_persistence_cannot_commit_cursor(self):
        from app.reception_service import store_file as actual
        def fail(*args,**kwargs):
            actual(*args,**kwargs)
            raise DomainError('Falha sintética após original',503,'synthetic_storage_failure')
        with patch('app.reception_service.store_file',side_effect=fail):self.query(status=503)
        self.assertEqual('000000000000000',self.state()['cursor'])
        self.assertGreater(self.state()['lease_until'],self.clock[0])
        self.query(status=409)
        self.query(key='synthetic-other',status=409)
        with self.core.db.read() as conn:
            self.assertEqual(0,conn.execute('SELECT COUNT(*) FROM stored_files WHERE company_id=?',(self.a['id'],)).fetchone()[0])
        self.assertEqual(1,len(self.transport.plans))

    def test_in_flight_lease_and_permission_revocation_prevent_commit(self):
        def send(plan,identity):
            self.assertEqual('000000000000000',self.state()['cursor'])
            self.assertGreater(self.state()['lease_until'],self.clock[0])
            with self.core.db.transaction() as conn:
                conn.execute("UPDATE users SET active=0 WHERE id=?",(self.uid,))
            return RemoteReply(200,self.envelope)
        self.transport.send=send
        self.query(status=403)
        self.assertEqual('000000000000000',self.state()['cursor'])
        self.assertGreater(self.state()['lease_until'],self.clock[0])

    def test_csrf_scope_permissions_context_and_secret_payloads_are_rejected_before_network(self):
        payload={'provider':'nfe_distribution','environment':'homologation','period':'2026-11','idempotency_key':'synthetic-bad'}
        self.assertEqual(403,self.client.post(self.scope('/imports/reception/query'),json=payload,headers={'X-CSRF-Token':''}).status_code)
        self.assertEqual(409,self.client.post(self.scope('/imports/reception/query',self.b['id']),json=payload).status_code)
        for field in ['url','pfx_file','password','certificate_tax_id','last_nsu']:
            self.assertEqual(400,self.client.post(self.scope('/imports/reception/query'),json=payload|{field:'synthetic-forbidden'}).status_code)
        for field in ['provider','environment']:
            self.assertEqual(400,self.client.post(self.scope('/imports/reception/query'),json=payload|{field:[]}).status_code)
        self.assertEqual([],self.transport.plans)
        with self.core.db.transaction() as conn:
            conn.execute("UPDATE users SET role='operator' WHERE id=?",(self.uid,))
            conn.execute('INSERT INTO user_companies(user_id,company_id) VALUES(?,?)',(self.uid,self.a['id']))
            conn.execute("INSERT INTO user_permissions VALUES(?,?,'fiscal.imports','read','allow')",(self.uid,self.a['id']))
        self.query(status=403)
        self.assertEqual([],self.transport.plans)

    def test_lease_expiry_cannot_accept_old_response_or_replay_uncertain_key(self):
        def send(plan,identity):
            self.clock[0]+=601
            return RemoteReply(200,self.envelope)
        self.transport.send=send
        self.query(status=409)
        self.assertEqual('000000000000000',self.state()['cursor'])
        self.query(status=409)
        self.query(key='synthetic-after-crash',status=429)

    def test_missing_uf_is_rejected_before_credentials_reservation_or_network(self):
        with self.core.db.transaction() as conn:
            conn.execute("UPDATE companies SET state='' WHERE id=?",(self.a['id'],))
        result=self.query(status=409)
        self.assertEqual('reception_company_uf',result['code'])
        self.assertEqual(0,self.service.credentials.calls)
        self.assertEqual([],self.transport.plans)
        self.assertEqual(0,self.state()['lease_until'])

    def test_backup_retains_receipt_and_cursor_with_original_hash(self):
        self.query()
        from app.snapshots import create_snapshot,restore_snapshot
        from app.db import Database
        path=Path(self.tmp.name)/'synthetic-backup.zip'
        create_snapshot(self.core.db.path,path)
        destination=Path(self.tmp.name)/'restored'
        restore_snapshot(path,destination)
        restored=Database(destination)
        with restored.read() as conn:
            row=conn.execute('SELECT result_json FROM operations WHERE company_id=? AND scope=?',(self.a['id'],STATE_SCOPE)).fetchone()
            self.assertEqual('000000000000002',json.loads(row['result_json'])['cursor'])
            self.assertEqual(self.envelope,conn.execute('SELECT content FROM stored_files WHERE company_id=?',(self.a['id'],)).fetchone()[0])


class TransportTests(unittest.TestCase):
    def identity(self):return ClientIdentity(MATRIX,ssl.create_default_context())
    def plan(self):return adn_request(MATRIX,'restricted_production','0')|{'provider':'nfse_adn'}

    def test_only_official_query_destinations_and_methods_are_accepted(self):
        for url in ['http://adn.nfse.gov.br/contribuintes/DFe/000000000000000','https://evil.invalid/','https://adn.nfse.gov.br:444/contribuintes/DFe/000000000000000','https://x:y@adn.nfse.gov.br/contribuintes/DFe/000000000000000','https://adn.nfse.gov.br/contribuintes/NFSe/emit']:
            with self.assertRaises(DomainError):MtlsTransport().send(self.plan()|{'url':url},self.identity())
        for method in ['POST','DELETE','PUT']:
            with self.assertRaises(DomainError):MtlsTransport().send(self.plan()|{'method':method},self.identity())
        insecure=ssl._create_unverified_context()
        with self.assertRaises(DomainError):MtlsTransport().send(self.plan(),ClientIdentity(MATRIX,insecure))
        with self.assertRaises(DomainError):MtlsTransport().send(nfe_request(MATRIX,'35','homologation','0')|{'provider':'nfe_distribution','body':b'<envEvento/>'},self.identity())

    def test_transport_caps_response_body_deadline_and_does_not_follow_redirect(self):
        class Reply:
            def __init__(self,raw,status=200,encoding='identity'):
                self.raw,self.status,self.encoding=raw,status,encoding
            def getheader(self,name,default=''):
                return self.encoding if name=='Content-Encoding' else 'https://forbidden.invalid' if name=='Location' else default
            def read1(self,count):
                chunk,self.raw=self.raw[:count],self.raw[count:]
                return chunk
        class Connection:
            def __init__(self,reply):self.reply,self.sock,self.calls,self.closed=reply,None,[],False
            def request(self,*args,**kwargs):self.calls.append((args,kwargs))
            def getresponse(self):return self.reply
            def close(self):self.closed=True
        for raw,status,encoding,code in [(b'x'*33,200,'identity','reception_response_size'),(b'x',200,'gzip','reception_response_encoding')]:
            conn=Connection(Reply(raw,status,encoding))
            with patch('app.reception_transport.HTTPSConnection',return_value=conn),patch('app.reception_transport.MAX_FILE_BYTES',32),self.assertRaises(DomainError) as error:
                MtlsTransport().send(self.plan(),self.identity())
            self.assertEqual(code,error.exception.code)
            self.assertTrue(conn.closed)
        conn=Connection(Reply(b'redirect',302))
        with patch('app.reception_transport.HTTPSConnection',return_value=conn):
            self.assertEqual(302,MtlsTransport().send(self.plan(),self.identity()).status)
        self.assertEqual(1,len(conn.calls))
        conn=Connection(Reply(b'pending'))
        with patch('app.reception_transport.HTTPSConnection',return_value=conn),patch('app.reception_transport.time.monotonic',side_effect=[0,31]),self.assertRaises(DomainError) as error:
            MtlsTransport().send(self.plan(),self.identity())
        self.assertEqual('reception_transport_uncertain',error.exception.code)
        self.assertTrue(conn.closed)

    def test_real_local_tls_requires_client_certificate_and_returns_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            ca_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            ca_name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'CA SINTETICA LOCAL')])
            now=datetime.now(timezone.utc)
            ca=(x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).sign(ca_key,hashes.SHA256()))
            server_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            server_cert=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'SERVIDOR SINTETICO LOCAL')])).issuer_name(ca_name).public_key(server_key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).sign(ca_key,hashes.SHA256()))
            client_key,client_cert=make_certificate(issuer=(ca_key,ca_name))
            for name,raw in [('ca.pem',ca.public_bytes(serialization.Encoding.PEM)),('server.pem',server_cert.public_bytes(serialization.Encoding.PEM)),('client.pem',client_cert.public_bytes(serialization.Encoding.PEM)),('server.key',server_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())),('client.key',client_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))]:write_private(root/name,raw)
            observed=[]
            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    observed.append((self.path,self.connection.getpeercert(binary_form=True)))
                    raw=b'{"synthetic":"local mTLS only"}'
                    self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
                def do_POST(self):
                    body=self.rfile.read(int(self.headers['Content-Length']))
                    observed.append((self.path,self.connection.getpeercert(binary_form=True),body))
                    raw=response([('1','procNFe_v4.00.xsd',FIXTURE.read_bytes())])
                    self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
                def log_message(self,*args):pass
            server=HTTPServer(('127.0.0.1',0),Handler)
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(root/'server.pem',root/'server.key');context.load_verify_locations(root/'ca.pem');context.verify_mode=ssl.CERT_REQUIRED
            server.socket=context.wrap_socket(server.socket,server_side=True)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            client=ssl.create_default_context(cafile=str(root/'ca.pem'));client.load_cert_chain(root/'client.pem',root/'client.key')
            actual=http.client.HTTPSConnection
            hosts=[]
            def local(host,**kwargs):hosts.append(host);return actual('127.0.0.1',server.server_port,**kwargs)
            try:
                with patch('app.reception_transport.HTTPSConnection',side_effect=local):
                    reply=MtlsTransport().send(adn_request(MATRIX,'restricted_production','9223372036854775807')|{'provider':'nfse_adn'},ClientIdentity(MATRIX,client))
                self.assertEqual(200,reply.status)
                self.assertEqual(b'{"synthetic":"local mTLS only"}',reply.body)
                self.assertEqual(['adn.producaorestrita.nfse.gov.br'],hosts)
                self.assertEqual(client_cert.public_bytes(serialization.Encoding.DER),observed[0][1])
                self.assertIn('/contribuintes/DFe/9223372036854775807?',observed[0][0])
                self.assertIn('lote=true',observed[0][0])
                with patch('app.reception_transport.HTTPSConnection',side_effect=local):
                    nfe=MtlsTransport().send(nfe_request(MATRIX,'35','homologation','0')|{'provider':'nfe_distribution'},ClientIdentity(MATRIX,client))
                self.assertEqual(200,nfe.status)
                self.assertEqual('hom.nfe.fazenda.gov.br',hosts[-1])
                self.assertIn(b'distNSU',observed[1][2])
                self.assertNotIn(b'envEvento',observed[1][2])
                self.assertIn(b'procNFe_v4.00.xsd',nfe.body)
                no_client=ssl.create_default_context(cafile=str(root/'ca.pem'))
                with patch('app.reception_transport.HTTPSConnection',side_effect=local),self.assertRaises(DomainError):
                    MtlsTransport().send(self.plan(),ClientIdentity(MATRIX,no_client))
                self.assertEqual(2,len(observed))
            finally:
                server.shutdown();server.server_close();thread.join(timeout=5)
