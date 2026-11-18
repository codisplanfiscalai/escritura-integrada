"""ADN timing and national issuer regressions; synthetic data, no fiscal network."""
import json
import unittest

import test_reception_adn as adn
from app.reception_metadata import classify
from app.reception_transport import RemoteReply
from test_reception_remote import MATRIX, BRANCH


class AdnTimingRegressionTests(unittest.TestCase):
    setUpBase = adn.AdnCaptureTests.setUpBase
    setUp = adn.AdnCaptureTests.setUp
    tearDown = adn.AdnCaptureTests.tearDown
    create_company = adn.AdnCaptureTests.create_company
    activate = adn.AdnCaptureTests.activate
    scope = adn.AdnCaptureTests.scope
    query = adn.AdnCaptureTests.query
    state = adn.AdnCaptureTests.state

    def absence(self, status=404, retry=0):
        payload = {'StatusProcessamento': 'NENHUM_DOCUMENTO_LOCALIZADO',
                   'TipoAmbiente': 'HOMOLOGACAO', 'Erros': [{'Codigo': 'E2220'}]}
        self.transport.reply = RemoteReply(status, json.dumps(payload).encode(), retry)

    def test_explicit_end_waits_without_restarting_or_redownloading(self):
        self.query()
        for status in (200, 404):
            with self.subTest(status=status):
                self.absence(status)
                key = f'explicit-end-{status}'
                result = self.query(key)
                self.assertEqual('no_documents', result['state'])
                self.assertEqual('000000000000002', self.state()['cursor'])
                self.assertEqual(self.clock[0] + 3600, self.state()['next_allowed_at'])
                attempts = len(self.transport.plans)
                self.assertTrue(self.query(key)['duplicate'])
                self.query(f'early-restart-{status}', status=429)
                self.assertEqual(attempts, len(self.transport.plans))
                self.clock[0] += 3601
        self.transport.reply = RemoteReply(200, json.dumps(adn.page([adn.packet(3)])).encode())
        self.assertTrue(self.query('after-absence-001')['cursor_advanced'])
        self.assertIn('/DFe/000000000000002', self.transport.plans[-1]['url'])
        self.assertEqual([], self.core.documents(self.a['id']))

    def test_server_pause_larger_than_absence_minimum_is_preserved(self):
        self.absence(retry=7200)
        self.query('long-absence-pause')
        self.assertEqual(self.clock[0] + 7200, self.state()['next_allowed_at'])
        self.clock[0] += 3601
        self.query('still-long-pause', status=429)
        self.assertEqual(1, len(self.transport.plans))

    def test_positive_page_honors_retry_after_but_no_header_allows_continuation(self):
        self.transport.reply = RemoteReply(200, json.dumps(adn.page([adn.packet(1)])).encode(), 90)
        result = self.query('positive-page-with-pause')
        self.assertTrue(result['has_more'])
        self.assertEqual('000000000000001', self.state()['cursor'])
        self.assertEqual(self.clock[0] + 90, self.state()['next_allowed_at'])
        self.query('positive-page-too-early', status=429)
        self.assertEqual(1, len(self.transport.plans))
        self.clock[0] += 91
        self.transport.reply = RemoteReply(200, json.dumps(adn.page([adn.packet(2)])).encode())
        self.query('positive-page-no-pause')
        self.assertEqual(self.clock[0], self.state()['next_allowed_at'])
        self.transport.reply = RemoteReply(200, json.dumps(adn.page([adn.packet(3)])).encode())
        self.query('positive-next-immediate')
        self.assertEqual('000000000000003', self.state()['cursor'])
        self.assertEqual(3, len(self.transport.plans))


    def test_historical_and_current_event_record_names_preserve_mixed_batch(self):
        # The archive intentionally does not infer cancellation from event XML.
        events = [(f'<evento xmlns="{adn.NFSE_NS}"><infEvento><dhProc>2024-11-01T12:00:00-03:00</dhProc>'
                   f'<{name}>42</{name}></infEvento></evento>').encode()
                  for name in ('nDFe', 'nDFSe')]
        self.transport.reply = RemoteReply(200, json.dumps(adn.page([
            adn.packet(1), adn.packet(2, 'EVENTO', events[0]),
            adn.packet(3, 'EVENTO', events[1]), adn.packet(4),
        ])).encode())
        result = self.query('historical-current-mixed')
        self.assertEqual('received', result['state'])
        self.assertEqual('000000000000004', self.state()['cursor'])
        self.assertTrue(result['has_more'])
        self.assertEqual(4, len(result['entries']))
        for number, original in zip(('2', '3'), events):
            response = self.client.get(self.scope('/imports/reception/receipts/historical-current-mixed/documents/' + number + '/download'))
            self.assertEqual(200, response.status_code)
            self.assertEqual(original, response.content)
        self.assertEqual([], self.core.documents(self.a['id']))
        self.assertEqual(1, len(self.transport.plans))


class NationalIssuerRegressionTests(unittest.TestCase):
    def note(self, emit=MATRIX, name='Empresa sintética', prest_name=''):
        return (f'<NFSe xmlns="{adn.NFSE_NS}"><infNFSe><emit><CNPJ>{emit}</CNPJ>'
                f'<xNome>{name}</xNome></emit><DPS><infDPS><prest><CNPJ>{MATRIX}</CNPJ>'
                f'{prest_name}</prest><toma><CNPJ>{BRANCH}</CNPJ></toma></infDPS></DPS></infNFSe></NFSe>').encode()

    def test_issuer_name_uses_emit_when_same_complete_registration_matches(self):
        result = classify(self.note(), 'nfse_adn', MATRIX)
        self.assertEqual('Empresa sintética', result['issuer_name'])
        self.assertEqual(MATRIX, result['issuer_tax_id'])
        self.assertEqual('issued', result['direction'])
        self.assertNotIn('posting_date', result)

    def test_other_branch_ambiguous_or_foreign_emit_cannot_supply_the_name(self):
        for raw in (self.note(emit=BRANCH),
                    self.note().replace(b'</emit>', b'</emit><emit><CNPJ>' + MATRIX.encode() + b'</CNPJ><xNome>Outro</xNome></emit>'),
                    self.note().replace(b'<emit>', b'<emit xmlns="urn:other">')):
            with self.subTest(raw=raw):
                self.assertEqual('', classify(raw, 'nfse_adn', MATRIX)['issuer_name'])

    def test_existing_provider_name_keeps_precedence(self):
        result = classify(self.note(prest_name='<xNome>Nome declarado no prestador</xNome>'), 'nfse_adn', MATRIX)
        self.assertEqual('Nome declarado no prestador', result['issuer_name'])


if __name__ == '__main__':
    unittest.main()
