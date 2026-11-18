"""Real Apple helper/IPC/TLS integration on native macOS, synthetic data only."""
import base64
import gzip
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import platform
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from app.core import DomainError, cnpj_digits
from app.reception_native import NativeA1Bridge
from app.reception import adn_request, nfe_request
from app.reception_transport import MtlsTransport

ROOT=Path(__file__).resolve().parents[1]
MATRIX='11222333000181'
BRANCH='112223330002'+cnpj_digits('112223330002')
THIRD='998887770001'+cnpj_digits('998887770001')
PASSWORD='SYNTHETIC-NATIVE-ONLY'
XML=b'<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse"><infNFSe/></NFSe>'


class Fixtures:
    def __init__(self,root):
        self.root=root
        self.openssl=next((p for p in ['/usr/local/opt/openssl@3/bin/openssl','/opt/homebrew/opt/openssl@3/bin/openssl'] if Path(p).is_file()),None)
        if not self.openssl:raise RuntimeError('Preinstalled OpenSSL 3 required for synthetic fixtures')
        if not self.run('version').decode().startswith('OpenSSL 3.'):raise RuntimeError('Modern fixture producer required')
        (root/'ca.conf').write_text('[req]\ndistinguished_name=dn\nx509_extensions=ca\nprompt=no\n[dn]\nCN=SYNTHETIC NATIVE CA\n[ca]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\n')
        self.run('req','-x509','-newkey','rsa:2048','-nodes','-keyout','ca.key','-out','ca.pem','-days','1','-config','ca.conf')
        self.make('client','otherName:2.16.76.1.3.3;UTF8:'+MATRIX,'clientAuth')
        self.make('server','IP:127.0.0.1','serverAuth')
        self.der=self.run('x509','-in','client.pem','-outform','DER')
        self.ca=self.run('x509','-in','ca.pem','-outform','DER')

    def run(self,*args,input=None):
        r=subprocess.run([self.openssl,*args],cwd=self.root,input=input,capture_output=True,timeout=30)
        if r.returncode:raise RuntimeError('Synthetic OpenSSL fixture failed')
        return r.stdout

    def make(self,name,san,eku='clientAuth',days='1'):
        self.run('req','-newkey','rsa:2048','-nodes','-keyout',name+'.key','-out',name+'.csr','-subj','/CN=SYNTHETIC-'+name)
        (self.root/(name+'.ext')).write_text('basicConstraints=CA:FALSE\nextendedKeyUsage='+eku+'\n'+('subjectAltName='+san+'\n' if san else ''))
        if days=='-1':
            # x509 -days requires a positive value on the CI OpenSSL versions.
            # Use documented CA absolute dates; keep the expiry assertion intact.
            (self.root/'issued').mkdir(exist_ok=True)
            (self.root/'expired-index').write_text('')
            (self.root/'expired-serial').write_text('1000\n')
            (self.root/'expired-ca.conf').write_text(
                '[ca]\ndefault_ca=issuer\n[issuer]\ndatabase=expired-index\nserial=expired-serial\n'
                'new_certs_dir=issued\ncertificate=ca.pem\nprivate_key=ca.key\ndefault_md=sha256\n'
                'policy=policy\n[policy]\ncommonName=supplied\n[leaf]\n'+(self.root/(name+'.ext')).read_text())
            self.run('ca','-config','expired-ca.conf','-batch','-in',name+'.csr','-out',name+'.pem',
                     '-startdate','20000101000000Z','-enddate','20000102000000Z','-extensions','leaf')
        else:
            self.run('x509','-req','-in',name+'.csr','-CA','ca.pem','-CAkey','ca.key','-CAcreateserial',
                     '-out',name+'.pem','-days',days,'-extfile',name+'.ext')
        self.run('pkcs12','-export','-in',name+'.pem','-inkey',name+'.key','-out',name+'.p12',
                 '-keypbe','AES-256-CBC','-certpbe','AES-256-CBC','-macalg','sha256','-passout','stdin',input=(PASSWORD+'\n').encode())
        for path in self.root.glob(name+'.*'):path.chmod(0o600)
        return (self.root/(name+'.p12')).read_bytes()


@unittest.skipUnless(sys.platform=='darwin','Native Apple API/TLS requires macOS; no emulation')
class NativeAppleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='escritura-native-integration-');cls.root=Path(cls.temp.name)
        cls.fixture=Fixtures(cls.root)
        from scripts.build_native_a1 import build
        cls.binary,cls.manifest=build()
        cls.testing=cls.root/'native-testing'
        subprocess.run(['xcrun','swiftc','-swift-version','5','-D','RECEPTION_TESTING',str(ROOT/'native/EscrituraA1.swift'),
            '-framework','Security','-framework','CFNetwork','-o',str(cls.testing)],check=True,timeout=150)
        cls.bridge=NativeA1Bridge(cls.binary)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def input(self,action='inspect',**changes):
        return {'protocol':1,'action':action,'pfx_base64':base64.b64encode((self.root/'client.p12').read_bytes()).decode(),
                'password':PASSWORD}|changes

    def invoke(self,data,testing=False):
        r=subprocess.run([str(self.testing if testing else self.binary)],input=json.dumps(data).encode(),capture_output=True,timeout=45)
        payload=json.loads(r.stdout)
        return r.returncode,payload

    def test_signed_production_helper_inspects_structured_oid_dates_and_exact_der(self):
        result=self.bridge._invoke(self.input())
        self.assertEqual(MATRIX,result['holder_tax_id'])
        self.assertEqual(hashlib.sha256(self.fixture.der).hexdigest(),result['certificate_sha256'])
        self.assertLess(abs(result['not_before']-time.time()),600)
        self.assertAlmostEqual(86400,result['not_after']-result['not_before'])
        self.assertEqual('production',result['build'])
        self.assertEqual(platform.machine(),self.manifest['architecture'])
        identity=self.bridge.load((self.root/'client.p12').read_bytes(),PASSWORD,MATRIX,'nfse_adn','restricted_production',False)
        self.assertEqual(MATRIX,identity.tax_id)

    def test_wrong_password_missing_duplicate_or_invalid_cnpj_and_expiry_are_refused(self):
        code,result=self.invoke(self.input(password='WRONG-SYNTHETIC'))
        self.assertNotEqual(0,code);self.assertEqual('reception_credentials',result['code'])
        for name,san,days,expected in [
            ('missing','','1','reception_certificate_identity'),
            ('invalid','otherName:2.16.76.1.3.3;UTF8:00000000000000','1','reception_certificate_identity'),
            ('duplicate','otherName:2.16.76.1.3.3;UTF8:'+MATRIX+',otherName:2.16.76.1.3.3;UTF8:'+MATRIX,'1','reception_certificate_identity'),
            ('expired','otherName:2.16.76.1.3.3;UTF8:'+MATRIX,'-1','reception_certificate_expired')]:
            with self.subTest(name=name):
                raw=self.fixture.make(name,san,days=days)
                code,result=self.invoke(self.input(pfx_base64=base64.b64encode(raw).decode()))
                self.assertNotEqual(0,code);self.assertEqual(expected,result['code'])

    def query_payload(self,**changes):
        inspected=self.bridge._invoke(self.input())
        return self.input('query',target=MATRIX,provider='nfse_adn',environment='restricted_production',allow_procuration=False,
            expected_holder=MATRIX,certificate_sha256=inspected['certificate_sha256'],last_nsu='000000000000000')|changes

    def test_production_binary_refuses_test_ca_urls_events_pin_and_other_root(self):
        for change,expected in [({'test_port':1},'reception_credentials'),({'url':'https://127.0.0.1/'},'reception_credentials'),
            ({'provider':'manifestacao'},'reception_operation'),({'certificate_sha256':'0'*64},'reception_native_pin'),
            ({'expected_holder':'00000000000000'},'reception_native_pin'),({'target':THIRD},'reception_certificate_identity')]:
            with self.subTest(change=change):
                code,result=self.invoke(self.query_payload(**change))
                self.assertNotEqual(0,code);self.assertEqual(expected,result['code'])

    def server(self,body=b'{"synthetic":true}',status=200,encoding=None):
        observed=[]
        class Handler(BaseHTTPRequestHandler):
            def answer(handler):
                content=handler.rfile.read(int(handler.headers.get('Content-Length','0')))
                observed.append((handler.command,handler.path,handler.connection.getpeercert(binary_form=True),content,handler.headers.get('X-Escritura-Test-Original-URL')))
                handler.send_response(status)
                if encoding:handler.send_header('Content-Encoding',encoding)
                if 300<=status<400:handler.send_header('Location','https://forbidden.invalid/')
                handler.send_header('Content-Length',str(len(body)));handler.end_headers()
                try:handler.wfile.write(body)
                except (BrokenPipeError,ssl.SSLError):pass
            do_GET=answer
            do_POST=answer
            def log_message(self,*args):pass
        server=HTTPServer(('127.0.0.1',0),Handler)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(self.root/'server.pem',self.root/'server.key');context.load_verify_locations(self.root/'ca.pem');context.verify_mode=ssl.CERT_REQUIRED
        server.socket=context.wrap_socket(server.socket,server_side=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join(timeout=3)))
        return server,observed

    def test_real_native_tls_validates_ca_requires_client_and_never_follows_redirect(self):
        server,observed=self.server()
        payload=self.query_payload(test_port=server.server_port,test_ca_base64=base64.b64encode(self.fixture.ca).decode())
        code,result=self.invoke(payload,testing=True)
        self.assertEqual(0,code,result);self.assertEqual(self.fixture.der,observed[0][2])
        self.assertEqual(b'{"synthetic":true}',base64.b64decode(result['body_base64']))
        for change in [{'test_present_client':False},{'test_ca_base64':base64.b64encode(self.fixture.der).decode()}]:
            code,result=self.invoke(payload|change,testing=True)
            self.assertNotEqual(0,code);self.assertEqual('reception_transport_uncertain',result['code'])
        redirected,requests=self.server(status=302)
        code,result=self.invoke(payload|{'test_port':redirected.server_port},testing=True)
        self.assertEqual(0,code,result);self.assertEqual(302,result['http_status']);self.assertEqual(1,len(requests))

    def test_native_matrix_branch_procuration_attempt_and_environment_remain_distinct(self):
        server,observed=self.server()
        local={'test_port':server.server_port,'test_ca_base64':base64.b64encode(self.fixture.ca).decode()}
        for target,allow in [(MATRIX,False),(BRANCH,False),(THIRD,True)]:
            for environment in ['production','restricted_production']:
                with self.subTest(target=target,environment=environment):
                    code,result=self.invoke(self.query_payload(target=target,allow_procuration=allow,environment=environment,**local),testing=True)
                    self.assertEqual(0,code,result)
                    original=observed[-1][4]
                    self.assertIn('adn.nfse.gov.br' if environment=='production' else 'adn.producaorestrita.nfse.gov.br',original)
                    self.assertIn('cnpjConsulta='+target,original)
                    self.assertIn('lote=true',original)
        # Reverse same-root case: the certificate belongs to the branch.
        pfx=self.fixture.make('branch','otherName:2.16.76.1.3.3;UTF8:'+BRANCH)
        inspected=self.bridge._invoke(self.input(pfx_base64=base64.b64encode(pfx).decode()))
        payload=self.query_payload(pfx_base64=base64.b64encode(pfx).decode(),target=MATRIX,
            expected_holder=BRANCH,certificate_sha256=inspected['certificate_sha256'],**local)
        code,result=self.invoke(payload,testing=True)
        self.assertEqual(0,code,result);self.assertIn('cnpjConsulta='+MATRIX,observed[-1][4])
        self.assertEqual(hashlib.sha256(observed[-1][2]).hexdigest(),inspected['certificate_sha256'])
        code,result=self.invoke(self.query_payload(target=THIRD,allow_procuration=False,**local),testing=True)
        self.assertNotEqual(0,code);self.assertEqual('reception_certificate_identity',result['code'])
        # A permitted attempt is not proof of an externally granted procuração.
        rejected,_=self.server(body=b'{"TipoConsulta":"InscricaoCertificado","Erros":[{"Codigo":"E2245"}]}',status=400)
        code,result=self.invoke(self.query_payload(target=THIRD,allow_procuration=True,**(local|{'test_port':rejected.server_port})),testing=True)
        self.assertEqual(0,code,result);self.assertEqual(400,result['http_status'])
        self.assertIn(b'E2245',base64.b64decode(result['body_base64']))

    def test_nfe_is_only_dist_nsu_and_body_encoding_size_are_bounded(self):
        server,observed=self.server(body=b'<synthetic/>')
        payload=self.query_payload(provider='nfe_distribution',environment='homologation',uf_code='35',
            test_port=server.server_port,test_ca_base64=base64.b64encode(self.fixture.ca).decode())
        code,result=self.invoke(payload,testing=True)
        self.assertEqual(0,code,result);self.assertEqual('POST',observed[0][0]);self.assertIn(b'<distNSU>',observed[0][3])
        self.assertNotIn(b'envEvento',observed[0][3])
        for body,encoding,expected in [(b'x','gzip','reception_response_encoding'),(b'x'*(20*1024*1024+1),None,'reception_response_size')]:
            server,_=self.server(body=body,encoding=encoding)
            code,result=self.invoke(payload|{'test_port':server.server_port},testing=True)
            self.assertNotEqual(0,code);self.assertEqual(expected,result['code'])

    def test_native_alphanumeric_nfe_printable_identity_dv_and_adn_contract_boundary(self):
        alpha='12ABC34501DE35'  # Official calculation example, no real taxpayer.
        branch='12ABC3450001'+cnpj_digits('12ABC3450001')
        numeric_branch='11222333S1N1'+cnpj_digits('11222333S1N1')
        server,observed=self.server(body=b'<synthetic/>')
        local={'test_port':server.server_port,'test_ca_base64':base64.b64encode(self.fixture.ca).decode()}
        holders={MATRIX:(self.root/'client.p12').read_bytes()}
        for index,holder in enumerate([alpha,branch]):
            holders[holder]=self.fixture.make('alpha'+str(index),'otherName:2.16.76.1.3.3;PRINTABLESTRING:'+holder)
        for holder,target in [(MATRIX,numeric_branch),(alpha,alpha),(alpha,branch),(branch,alpha)]:
            raw=holders[holder]
            inspected=self.bridge._invoke(self.input(pfx_base64=base64.b64encode(raw).decode()))
            self.assertEqual(holder,inspected['holder_tax_id'])
            identity=self.bridge.load(raw,PASSWORD,target,'nfe_distribution','homologation',False)
            self.assertEqual(holder,identity.tax_id);self.assertEqual(target,identity.target)
            for environment in ['production','homologation']:
                code,result=self.invoke(self.query_payload(pfx_base64=base64.b64encode(raw).decode(),expected_holder=holder,
                    certificate_sha256=inspected['certificate_sha256'],target=target,provider='nfe_distribution',
                    environment=environment,uf_code='35',**local),testing=True)
                self.assertEqual(0,code,result)
                self.assertIn(('<CNPJ>'+target+'</CNPJ>').encode(),observed[-1][3])
                self.assertEqual(inspected['certificate_sha256'],hashlib.sha256(observed[-1][2]).hexdigest())
            count=len(observed)
            payload=self.query_payload(pfx_base64=base64.b64encode(raw).decode(),expected_holder=holder,
                    certificate_sha256=inspected['certificate_sha256'],target=target,allow_procuration=True,**local)
            code,result=self.invoke(payload,testing=True)
            self.assertNotEqual(0,code);self.assertEqual('reception_adn_alphanumeric_pending',result['code'])
            self.assertEqual(count,len(observed))
        for name,holder in [('bad-alpha-dv','12ABC34501DE30'),('lower-alpha',alpha.lower())]:
            raw=self.fixture.make(name,'otherName:2.16.76.1.3.3;PRINTABLESTRING:'+holder)
            code,result=self.invoke(self.input(pfx_base64=base64.b64encode(raw).decode()))
            self.assertNotEqual(0,code);self.assertEqual('reception_certificate_identity',result['code'])

    def test_domain_api_native_capture_keeps_permissions_cursor_and_originals(self):
        # Base setup uses the real API/session/RBAC/SQLite, no cryptography import.
        import test_core as base
        fixture=base.CoreApiTests();fixture.setUp()
        self.addCleanup(fixture.tearDown)
        company=fixture.create_company('NATIVE','112223330001');fixture.activate(company['id'])
        page={'TipoConsulta':'CnpjBase','TipoAmbiente':'HOMOLOGACAO','StatusProcessamento':'DOCUMENTOS_LOCALIZADOS',
            'LoteDFe':[{'NSU':1,'TipoDocumento':'NFSE','ArquivoXml':base64.b64encode(gzip.compress(XML)).decode()}],
            'DataHoraProcessamento':'2026-11-15T00:00:00Z'}
        raw=json.dumps(page).encode();server,observed=self.server(body=raw)
        owner=self
        class TestBridge(NativeA1Bridge):
            def _invoke(self,payload):
                if payload['action']=='query':payload=payload|{'test_port':server.server_port,'test_ca_base64':base64.b64encode(owner.fixture.ca).decode()}
                code,result=owner.invoke(payload,testing=True)
                if code:raise DomainError('Synthetic native test failure',502,result['code'])
                return result
        bridge=TestBridge()
        class Credentials:
            def load(self,cid,target,provider,environment):
                return bridge.load((owner.root/'client.p12').read_bytes(),PASSWORD,target,provider,environment,False)
        from app.reception_service import ReceptionService,STATE_SCOPE
        service=ReceptionService(fixture.core,Credentials(),clock=lambda:1000.)
        fixture.app.state.reception=service
        path=fixture.scope('/imports/reception/query',company['id'])
        payload={'provider':'nfse_adn','environment':'restricted_production','period':'2026-11','idempotency_key':'native-synthetic-api'}
        result=fixture.client.post(path,json=payload)
        self.assertEqual(200,result.status_code,result.text);self.assertTrue(result.json()['cursor_advanced'])
        self.assertEqual('000000000000001',result.json()['cursor_after'])
        self.assertEqual([],fixture.core.documents(company['id']))
        download=fixture.client.get(fixture.scope('/imports/reception/receipts/native-synthetic-api/documents/1/download',company['id']))
        self.assertEqual(XML,download.content)
        self.assertTrue(fixture.client.post(path,json=payload).json()['duplicate']);self.assertEqual(1,len(observed))
        user=fixture.client.get('/api/session').json()['user']['id']
        with fixture.core.db.transaction() as conn:
            conn.execute("UPDATE users SET role='operator' WHERE id=?",(user,))
            conn.execute('INSERT INTO user_companies(user_id,company_id) VALUES(?,?)',(user,company['id']))
            conn.execute("INSERT INTO user_permissions VALUES(?,?,'fiscal.imports','read','allow')",(user,company['id']))
        with patch.object(bridge,'_invoke') as invoke:
            denied=fixture.client.post(path,json=payload|{'idempotency_key':'native-synthetic-denied'})
            self.assertEqual(403,denied.status_code,denied.text);invoke.assert_not_called()
        self.assertEqual(1,len(observed))


if __name__=='__main__':unittest.main()
