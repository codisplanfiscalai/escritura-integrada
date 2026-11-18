"""Regressions from live receipt diagnostics, with synthetic identities only."""
import json
import unittest
from xml.dom import minidom
from xml.etree import ElementTree as ET

import test_reception_adn as adn
import test_reception_remote as remote
from test_reception_remote import MATRIX, BRANCH, THIRD
from app.core import DomainError
from app.reception import NFE_NS, SOAP_NS, WSDL_NS, adn_request, nfe_request
from app.reception_transport import RemoteReply


class RequestWireTests(unittest.TestCase):
    def test_nfe_area_has_default_namespace_without_prefixes_in_both_environments(self):
        for environment in ('production', 'homologation'):
            with self.subTest(environment=environment):
                body = nfe_request(MATRIX, '29', environment, '42')['body']
                root = ET.fromstring(body)
                self.assertEqual('{'+SOAP_NS+'}Envelope', root.tag)
                self.assertIsNotNone(root.find('./{'+SOAP_NS+'}Body/{'+WSDL_NS+'}nfeDistDFeInteresse/{'+WSDL_NS+'}nfeDadosMsg/{'+NFE_NS+'}distDFeInt'))
                document = minidom.parseString(body)
                data = document.getElementsByTagNameNS(NFE_NS, 'distDFeInt')[0]
                for element in [data, *data.getElementsByTagName('*')]:
                    self.assertIsNone(element.prefix, element.tagName)
                    self.assertEqual(NFE_NS, element.namespaceURI)
                self.assertEqual('000000000000042', data.getElementsByTagName('ultNSU')[0].firstChild.data)
                self.assertEqual(MATRIX, data.getElementsByTagName('CNPJ')[0].firstChild.data)

    def test_adn_explicit_company_in_same_holder_branch_and_procuration(self):
        for environment in ('production', 'restricted_production'):
            for target, holder, allow, mode in ((MATRIX, MATRIX, False, 'CnpjBase'),
                    (BRANCH, MATRIX, False, 'CnpjBase'), (MATRIX, BRANCH, False, 'CnpjBase'),
                    (THIRD, MATRIX, True, 'Procuracao')):
                with self.subTest(environment=environment, target=target, holder=holder):
                    request = adn_request(target, environment, '42', certificate_tax_id=holder, allow_procuration=allow)
                    self.assertIn('cnpjConsulta='+target, request['url'])
                    self.assertNotIn('cpfConsulta', request['url'])
                    self.assertEqual(mode, request['expected_authorization_mode'])
                    self.assertFalse(request['authorization_verified'])
        with self.assertRaises(DomainError):
            adn_request(THIRD, 'production', '0', certificate_tax_id=MATRIX)


class RejectedReceiptTests(unittest.TestCase):
    setUpBase = adn.AdnCaptureTests.setUpBase
    setUp = adn.AdnCaptureTests.setUp
    tearDown = adn.AdnCaptureTests.tearDown
    create_company = adn.AdnCaptureTests.create_company
    activate = adn.AdnCaptureTests.activate
    scope = adn.AdnCaptureTests.scope
    query = adn.AdnCaptureTests.query
    state = adn.AdnCaptureTests.state

    def test_empty_error_rejection_is_never_absence_or_authorization(self):
        for status in (200, 400):
            raw = json.dumps({'TipoConsulta':'InscricaoCertificado', 'StatusProcessamento':'REJEICAO',
                'LoteDFe':[], 'Alertas':[], 'Erros':[], 'TipoAmbiente':'HOMOLOGACAO',
                'VersaoAplicativo':'SYNTHETIC', 'DataHoraProcessamento':'2026-11-18T00:00:00-03:00'}).encode()
            self.transport.reply = RemoteReply(status, raw)
            result = self.query('empty-rejection-'+str(status))
            self.assertEqual('rejected', result['state'])
            self.assertEqual('ADN_REJECTION_WITHOUT_DETAILS', result['code'])
            self.assertFalse(result['authorization_verified'])
            self.assertFalse(result['cursor_advanced'])
            self.assertEqual('000000000000000', self.state()['cursor'])
            self.assertNotIn('has_more', result)
            saved = self.client.get(self.scope('/imports/reception/receipts/'+result['receipt_key']+'/download'))
            self.assertEqual(raw, saved.content)

    def test_explicit_own_company_success_commits_all_originals_and_resumes(self):
        for number in (1, 2):
            self.transport.reply = RemoteReply(200, json.dumps(adn.page([adn.packet(number)], mode='CnpjBase')).encode())
            result = self.query('explicit-own-'+str(number))
            self.assertEqual('received', result['state'])
            self.assertTrue(result['authorization_verified'])
            self.assertEqual('CnpjBase', result['expected_authorization_mode'])
            self.assertIn('cnpjConsulta='+MATRIX, self.transport.plans[-1]['url'])
            self.assertIn('/DFe/'+str(number-1).zfill(15), self.transport.plans[-1]['url'])
            self.assertEqual(str(number).zfill(15), self.state()['cursor'])
            saved = self.client.get(self.scope('/imports/reception/receipts/'+result['receipt_key']+'/documents/'+str(number)+'/download'))
            self.assertEqual(adn.XML, saved.content)


class NfeRejectedReceiptTests(unittest.TestCase):
    setUpBase = remote.CaptureApiTests.setUpBase
    setUp = remote.CaptureApiTests.setUp
    tearDown = remote.CaptureApiTests.tearDown
    create_company = remote.CaptureApiTests.create_company
    activate = remote.CaptureApiTests.activate
    scope = remote.CaptureApiTests.scope
    query = remote.CaptureApiTests.query
    state = remote.CaptureApiTests.state

    def test_cstat_404_keeps_cursor_and_raw_then_corrected_request_can_resume(self):
        raw = remote.response(status='404', last='0', maximum='0', soap=True)
        self.transport.reply = RemoteReply(200, raw)
        result = self.query('namespace-rejected')
        self.assertEqual('rejected', result['state'])
        self.assertEqual('404', result['status_code'])
        self.assertEqual(200, result['http_status'])
        self.assertFalse(result['cursor_advanced'])
        self.assertEqual('000000000000000', self.state()['cursor'])
        self.assertEqual(raw, self.client.get(self.scope('/imports/reception/receipts/namespace-rejected/download')).content)
        self.assertEqual('rejected', self.query('namespace-rejected')['state'])
        self.query('before-interval', status=429)
        self.assertEqual(1, len(self.transport.plans))
        self.clock[0] += 3601
        self.transport.reply = RemoteReply(200, self.envelope)
        resumed = self.query('namespace-corrected')
        self.assertEqual('received', resumed['state'])
        self.assertEqual('000000000000002', self.state()['cursor'])
        self.assertEqual(2, len(self.transport.plans))
