"""CNPJ domains are service-specific; official NF-e XSD and synthetic A1 only."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

from lxml import etree
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization.pkcs12 import serialize_key_and_certificates
import test_reception_remote as remote
import test_reception_native as native
import test_reception_adn as adn
from test_reception import response
from app.core import DomainError, cnpj_digits, normalize_cnpj
from app.importers import ImportProblem
from app.reception import NFE_NS, adn_request, nfe_request
from app.reception_credentials import LocalA1Credentials, adn_access_mode, certificate_cnpj
from app.reception_native import NativeA1Bridge
from app.reception_transport import RemoteReply

ALPHA='12ABC34501DE35'  # RFB published calculation example, not a real identity.
ALPHA_BRANCH='12ABC3450001'+cnpj_digits('12ABC3450001')
NUMERIC_ROOT_BRANCH='11222333S1N1'+cnpj_digits('11222333S1N1')


class CnpjProtocolTests(unittest.TestCase):
    def test_nfe_numeric_and_alphanumeric_requests_match_unmodified_official_xsd(self):
        folder=Path(__file__).parent/'fixtures/nfe-dist-dfe-104'
        expected={'distDFeInt_v1.01.xsd':'2d95df1430b0f0e2b04c6f29cf6bb69cdb5a392ac52102987653902b9a34ff7a',
                  'tiposDistDFe_v1.01.xsd':'0bc215b9bda6422e37c2c28b80590b4c5ba3041f0db85ca17ebba61edadd7547'}
        for name,digest in expected.items():
            self.assertEqual(digest,hashlib.sha256((folder/name).read_bytes()).hexdigest())
        schema=etree.XMLSchema(etree.parse(str(folder/'distDFeInt_v1.01.xsd'),etree.XMLParser(no_network=True,resolve_entities=False)))
        for target in [remote.MATRIX,ALPHA,ALPHA_BRANCH,NUMERIC_ROOT_BRANCH]:
            self.assertEqual(target,normalize_cnpj(target))
            for environment in ['production','homologation']:
                with self.subTest(target=target,environment=environment):
                    plan=nfe_request(target,'35',environment,'42')
                    root=etree.fromstring(plan['body'])
                    document=root.find('.//{'+NFE_NS+'}distDFeInt')
                    schema.assertValid(document)
                    self.assertEqual(target,document.find('{'+NFE_NS+'}CNPJ').text)
                    self.assertEqual(['tpAmb','cUFAutor','CNPJ','distNSU'],[etree.QName(n).localname for n in document])
                    self.assertFalse(plan['network_executed'])

    def test_remote_validation_keeps_dv_ascii_case_and_length(self):
        for target in ['12ABC34501DE30','11222333000180','00000000000000',ALPHA.lower(),
                       '12ABC34501DE3A','１２ABC34501DE35','12ABC34501DÉ35','12.ABC.345/01DE-35',ALPHA+'0']:
            with self.subTest(target=target),self.assertRaises(ImportProblem):
                nfe_request(target,'35','homologation','0')

    def test_adn_query_contract_is_not_inferred_from_nfe_or_nfse_xml_support(self):
        for target in [ALPHA,ALPHA_BRANCH,NUMERIC_ROOT_BRANCH]:
            for environment in ['production','restricted_production']:
                with self.subTest(target=target,environment=environment),self.assertRaises(ImportProblem) as error:
                    adn_request(target,environment,'42')
                self.assertEqual('ADN_ALPHANUMERIC_CONTRACT_PENDING',error.exception.code)
            for target_id,holder in [(target,target),(target,remote.MATRIX),(remote.MATRIX,target)]:
                with self.assertRaises(DomainError) as error:adn_access_mode(target_id,holder,True)
                self.assertEqual('reception_adn_alphanumeric_pending',error.exception.code)


    def test_adn_opaque_xml_keeps_alphanumeric_parties_without_broadening_query_contract(self):
        xml=adn.XML.replace(b'<nNFSe>',('<prest><CNPJ>'+ALPHA+'</CNPJ></prest><nNFSe>').encode())
        result=adn.decode(adn.page([adn.packet(xml=xml)]))
        self.assertEqual(xml,result['entries'][0]['xml'])
        self.assertEqual('nfse_bookkeeping_review_required',result['entries'][0]['reason'])
        self.assertEqual('000000000000001',result['reported_last_nsu'])


class CnpjCredentialsTests(unittest.TestCase):
    def test_classic_a1_reads_printable_cnpj_and_preserves_same_root_policy(self):
        for holder,target in [(remote.MATRIX,NUMERIC_ROOT_BRANCH),(ALPHA,ALPHA_BRANCH),(ALPHA_BRANCH,ALPHA)]:
            with self.subTest(holder=holder,target=target),tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'ESCRITURA_RECEPTION_PASSWORD_SYNTHETIC':remote.PASSWORD.decode()}):
                root=Path(directory)
                key,cert=remote.make_certificate(holder,der_tag=0x13)
                self.assertEqual(holder,certificate_cnpj(cert))
                raw=serialize_key_and_certificates(b'synthetic',key,cert,None,serialization.BestAvailableEncryption(remote.PASSWORD))
                remote.write_private(root/'client.pfx',raw)
                profile={'companies':{'1':{'tax_id':target,'pfx_file':'client.pfx','password_env':'ESCRITURA_RECEPTION_PASSWORD_SYNTHETIC',
                         'environments':{'nfe_distribution':['homologation'],'nfse_adn':['restricted_production']}}}}
                remote.write_private(root/'profiles.json',json.dumps(profile).encode())
                identity=LocalA1Credentials(root).load(1,target,'nfe_distribution','homologation')
                self.assertEqual(holder,identity.tax_id)
                self.assertTrue(identity.context.check_hostname)
                with self.assertRaises(DomainError) as error:LocalA1Credentials(root).load(1,target,'nfse_adn','restricted_production')
                self.assertEqual('reception_adn_alphanumeric_pending',error.exception.code)
        for value in ['12ABC34501DE30',ALPHA.lower()]:
            _,cert=remote.make_certificate(value,der_tag=0x13)
            with self.assertRaises(DomainError):certificate_cnpj(cert)

    def test_native_bridge_accepts_nfe_alpha_and_keeps_adn_and_roots_separate(self):
        for holder,target in [(remote.MATRIX,NUMERIC_ROOT_BRANCH),(ALPHA,ALPHA_BRANCH),(ALPHA_BRANCH,ALPHA)]:
            bridge=NativeA1Bridge()
            with patch.object(bridge,'_invoke',return_value=native.metadata(holder)):
                identity=bridge.load(native.PFX,native.PASSWORD,target,'nfe_distribution','homologation',False)
                plan=nfe_request(target,'35','homologation','42')|{'provider':'nfe_distribution'}
                self.assertEqual({'last_nsu':'000000000000042','uf_code':'35'},bridge._parameters(plan,identity))
                with self.assertRaises(DomainError) as error:
                    bridge.load(native.PFX,native.PASSWORD,target,'nfse_adn','restricted_production',True)
                self.assertEqual('reception_adn_alphanumeric_pending',error.exception.code)
            with patch.object(bridge,'_invoke',return_value=native.metadata(remote.THIRD)),self.assertRaises(DomainError):
                bridge.load(native.PFX,native.PASSWORD,target,'nfe_distribution','homologation',True)


class CnpjCaptureTests(unittest.TestCase):
    setUpBase=remote.CaptureApiTests.setUpBase
    setUp=remote.CaptureApiTests.setUp
    tearDown=remote.CaptureApiTests.tearDown
    create_company=remote.CaptureApiTests.create_company
    activate=remote.CaptureApiTests.activate
    scope=remote.CaptureApiTests.scope
    query=remote.CaptureApiTests.query
    state=remote.CaptureApiTests.state

    def test_company_nfe_capture_original_cursor_and_canonical_preview_keep_letters(self):
        self.a=self.create_company('ALPHA','11222333S1N1');self.activate(self.a['id'])
        target=self.a['tax_id'];self.assertEqual(NUMERIC_ROOT_BRANCH,target)
        raw=self.raw.replace(remote.MATRIX.encode(),target.encode())
        envelope=response([('1','procNFe_v4.00.xsd',raw)],last='1',maximum='1')
        self.transport.reply=RemoteReply(200,envelope)
        receipt=self.query()
        self.assertTrue(receipt['cursor_advanced'])
        self.assertEqual('000000000000001',self.state(target=target)['cursor'])
        plan=self.transport.plans[0]
        self.assertEqual(target,ET.fromstring(plan['body']).find('.//{'+NFE_NS+'}CNPJ').text)
        url=self.scope('/imports/reception/receipts/synthetic-0001')
        self.assertEqual(envelope,self.client.get(url+'/download').content)
        preview=self.client.post(url+'/preview',json={'period':'2026-11'})
        self.assertEqual(200,preview.status_code,preview.text)
        self.assertTrue(preview.json()['can_confirm'])
        self.assertEqual('incoming',preview.json()['documents'][0]['direction'])
        self.assertEqual([],self.core.documents(self.a['id']))

    def test_adn_alpha_pending_happens_before_credential_network_or_cursor_reservation(self):
        self.a=self.create_company('ALPHA','12ABC3450001');self.activate(self.a['id'])
        result=self.query(provider='nfse_adn',environment='restricted_production',status=422)
        self.assertEqual('reception_adn_alphanumeric_pending',result['code'])
        self.assertEqual(0,self.service.credentials.calls);self.assertEqual([],self.transport.plans)
        state=self.state('nfse_adn','restricted_production',target=self.a['tax_id'])
        self.assertEqual(('000000000000000',0,0),(state['cursor'],state['lease_until'],state['next_allowed_at']))
