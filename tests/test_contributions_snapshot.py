"""Local EFD-Contribuições preparation; temporary DBs and synthetic sources only."""
import base64
import copy
import unittest
from pathlib import Path

import test_sped_generator as existing
from fastapi.testclient import TestClient
from app.core import DomainError, digest
from app.permissions import route_policy
from app.sped_generator.contributions_snapshot import contributions_snapshot, observed_fields, REFERENCE


class ObservedContributionFieldsTests(unittest.TestCase):
    def test_xml_sped_paths_and_decimal_text_are_kept_without_cst_mapping(self):
        huge = '999999999999999999999.12345678901234567890'
        document = {'taxes': {'ICMSTot/vPIS': '0.00', 'ICMSTot/vCOFINS': ''},
            'raw_fields': {'VL_PIS': '0,00'},
            'items': [{'taxes': {'PIS/PISAliq/CST': '01', 'PIS/PISAliq/vBC': huge,
                                 'COFINS/COFINSAliq/vCOFINS': '0.00', 'ICMS/ICMS00/CST': '00'},
                       'raw_fields': {'CST_PIS': '??', 'CST_COFINS': None}}]}
        before = copy.deepcopy(document)
        result = observed_fields(document)
        values = {tuple(field['path']): field for field in result['fields']}
        self.assertEqual(huge, values[('items', 0, 'taxes', 'PIS/PISAliq/vBC')]['stored_value'])
        self.assertEqual('01', values[('items', 0, 'taxes', 'PIS/PISAliq/CST')]['stored_value'])
        self.assertEqual('??', values[('items', 0, 'raw_fields', 'CST_PIS')]['stored_value'])
        self.assertEqual('blank', values[('taxes', 'ICMSTot/vCOFINS')]['state'])
        self.assertEqual('null', values[('items', 0, 'raw_fields', 'CST_COFINS')]['state'])
        self.assertEqual('stored_text_unvalidated', values[('taxes', 'ICMSTot/vPIS')]['state'])
        self.assertFalse(result['semantic_validation_performed'])
        self.assertFalse(any('ICMS' in str(field['path']) and 'vPIS' not in str(field['path']) and 'vCOFINS' not in str(field['path']) for field in result['fields']))
        self.assertEqual(before, document)

    def test_empty_invalid_container_and_numeric_values_are_not_silently_zeroed(self):
        self.assertEqual([], observed_fields({})['fields'])
        for value in (0, 0.0, False, [], {}):
            result = observed_fields({'taxes': {'VL_PIS': value}})
            field = result['fields'][0]
            self.assertEqual(value, field['stored_value'])
            self.assertEqual('unsupported_value_type', field['state'])
        for document, expected in [({'taxes': None}, 'UNREADABLE_FIELD_CONTAINER'),
                                    ({'items': {}}, 'UNREADABLE_ITEM_CONTAINER'),
                                    ({'items': [None]}, 'UNREADABLE_ITEM')]:
            self.assertIn(expected, {issue['code'] for issue in observed_fields(document)['issues']})

    def test_reference_versions_are_separate_and_payload_provenance_is_explicit(self):
        self.assertEqual('1.35', REFERENCE['guide_version'])
        self.assertEqual('2021-06-18', REFERENCE['guide_revision'])
        self.assertEqual('006', REFERENCE['layout_code_in_guide'])
        self.assertEqual('3.2.0', REFERENCE['layout_version_in_guide'])
        self.assertEqual('2026-11', REFERENCE['diagnostic_period_reviewed'])
        self.assertFalse(REFERENCE['complete_current_layout_review'])
        self.assertEqual(3, len(REFERENCE['sources']))
        for source in REFERENCE['sources']:
            self.assertTrue(source['url'].startswith('https://www.gov.br/sped/'))
            self.assertEqual(64, len(source['sha256']))
            self.assertGreater(source['bytes'], 0)


class ContributionsSnapshotApiTests(unittest.TestCase):
    setUp = existing.SpedGeneratorApiTests.setUp
    tearDown = existing.SpedGeneratorApiTests.tearDown
    scope = existing.SpedGeneratorApiTests.scope
    activate = existing.SpedGeneratorApiTests.activate
    create_company = existing.SpedGeneratorApiTests.create_company
    database_hash = existing.SpedGeneratorApiTests.database_hash
    import_xmls = existing.SpedGeneratorApiTests.import_xmls
    own_xml = existing.SpedGeneratorApiTests.own_xml
    document = existing.base.CoreApiTests.document

    def endpoint(self, cid=None):
        return self.scope('/sped-generator/contributions-snapshot', cid)

    def get(self, client=None, period='2026-11', cid=None, **kwargs):
        return (client or self.client).get(self.endpoint(cid), params={'period': period}, **kwargs)

    def import_payload(self, filename, content):
        response = self.client.post(self.scope('/imports/preview'), json={'filename': filename,
            'period': '2026-11', 'content_base64': base64.b64encode(content).decode()})
        self.assertEqual(200, response.status_code, response.text)
        batch = response.json()
        response = self.client.post(self.scope(f"/imports/{batch['id']}/confirm"), json={'preview_hash': batch['preview_hash']})
        self.assertEqual(200, response.status_code, response.text)

    def test_real_xml_parser_to_stored_evidence_keeps_issuer_cst_and_source_blobs(self):
        huge = '9999999999999.12345678901234567890'
        xml = (Path(__file__).parent / 'fixtures/nfe_ficticia.xml').read_text().replace('12345678000195', self.a['tax_id'])
        xml = xml.replace('</ICMS>', '</ICMS><PIS><PISAliq><CST>01</CST><vBC>' + huge + '</vBC><pPIS>1.6500</pPIS><vPIS>0.00</vPIS></PISAliq></PIS><COFINS><COFINSNT><CST>07</CST></COFINSNT></COFINS>')
        self.import_payload('contribuicoes-sintetica.xml', xml.encode())
        before = self.database_hash()
        first, second = self.get(), self.get()
        self.assertEqual(200, first.status_code, first.text)
        self.assertEqual(first.content, second.content)
        self.assertEqual(before, self.database_hash())
        result = first.json(); snapshot = result['snapshot']; document = snapshot['documents'][0]
        self.assertEqual('incoming', document['direction'])
        self.assertEqual('01', document['items'][0]['taxes']['PIS/PISAliq/CST'])
        self.assertEqual(huge, document['items'][0]['taxes']['PIS/PISAliq/vBC'])
        self.assertEqual('0.00', document['items'][0]['taxes']['PIS/PISAliq/vPIS'])
        self.assertIsNone(document['efd_fiscal_inclusion'])
        self.assertIsNone(snapshot['unattested']['regime_0110'])
        self.assertTrue(document['sources'][0]['source_hash'])
        self.assertEqual(digest(snapshot), result['snapshot_sha256'])
        self.assertEqual(result['snapshot_sha256'], first.headers['X-Snapshot-SHA256'])
        self.assertEqual('no-store', first.headers['Cache-Control'])
        self.assertIn('attachment;', first.headers['Content-Disposition'])
        self.assertFalse(snapshot['generates_efd'])
        self.assertTrue(all(not w['blocking_export'] for w in snapshot['warnings']))

    def test_client_sped_source_is_preserved_without_becoming_contributions_importer(self):
        raw = (Path(__file__).parent / 'fixtures/sped_ficticio_020.txt').read_text().replace('12345678000195', self.a['tax_id'])
        self.import_payload('sped-cliente-sintetico.efd', raw.encode())
        before = self.database_hash()
        response = self.get(); self.assertEqual(200, response.status_code, response.text)
        document = response.json()['snapshot']['documents'][0]
        stored = self.core.documents(self.a['id'], '2026-11')[0]
        self.assertEqual(stored['raw_fields'], document['raw_fields'])
        self.assertEqual(stored['items'], document['items'])
        self.assertEqual('C100', document['source']['record'])
        self.assertEqual(before, self.database_hash())

    def test_scope_uses_stored_posting_period_not_issue_date_or_other_company(self):
        doc = self.client.post(self.scope('/documents'), json=self.document()).json()
        self.client.post(self.scope('/documents'), json=self.document('OTHER-MONTH') | {'posting_date': '2026-10-06'})
        self.activate(self.b['id'])
        other = self.client.post(self.scope('/documents', self.b['id']), json=self.document('OTHER-COMPANY'))
        self.assertEqual(201, other.status_code, other.text)
        self.activate(self.a['id'])
        result = self.get().json()['snapshot']
        self.assertEqual([doc['id']], [d['id'] for d in result['documents']])
        self.assertEqual('2026-10-30', result['documents'][0]['issue_date'])
        self.assertEqual('stored_posting_period', result['scope_basis'])
        self.assertIsNone(result['unattested']['tax_due'])
        self.assertIn('NO_RECOGNIZED_TAX_FIELDS', {w['code'] for w in result['warnings']})
        self.assertEqual(409, self.get(cid=self.b['id']).status_code)

    def test_empty_period_and_2027_export_warnings_without_asserting_no_movement(self):
        result = self.get().json()['snapshot']
        self.assertEqual([], result['documents'])
        self.assertIn('NO_STORED_DOCUMENTS', {w['code'] for w in result['warnings']})
        self.assertTrue(all(value is None for value in result['unattested'].values()))
        self.core.create_exercise(self.a['id'], {'module': 'fiscal', 'year': 2027, 'reason': 'Exercício sintético'}, 'teste')
        self.activate(self.a['id'], period='2027-01')
        response = self.get(period='2027-01'); self.assertEqual(200, response.status_code)
        warnings = {w['code'] for w in response.json()['snapshot']['warnings']}
        self.assertTrue({'PERIOD_OUTSIDE_REVIEWED_SLICE', 'TRANSITION_2027_NOT_IMPLEMENTED'} <= warnings)

    def test_closed_open_and_reopened_competences_read_identically_without_mutation(self):
        self.import_xmls(1, book=True)
        initial = self.get().content
        for module in ('accounting', 'fiscal'):
            payload = {'period': '2026-11', 'module': module, 'reason': 'Fixture sintética'}
            for operation in ('close', 'reopen'):
                result = self.client.post(self.scope('/periods/' + operation), json=payload)
                self.assertEqual(200, result.status_code, result.text)
                before = self.database_hash()
                self.assertEqual(initial, self.get().content)
                self.assertEqual(before, self.database_hash())

    def test_book_cancellation_is_observed_without_choosing_its_fiscal_export_treatment(self):
        payload = self.document('CANCEL-SYNTHETIC') | {'direction': 'outgoing', 'total': '0.00', 'source_hash': '', 'cfop': '',
            'taxes': {}, 'items': [], 'book_cancellation': {'source': 'Livro sintético',
                'responsible': 'Fixture', 'reason': 'Registro de teste'}}
        response = self.client.post(self.scope('/documents'), json=payload)
        self.assertEqual(201, response.status_code, response.text)
        before = self.database_hash()
        document = self.get().json()['snapshot']['documents'][0]
        self.assertEqual('cancelled', document['document_state'])
        self.assertEqual(payload['book_cancellation'], document['book_cancellation'])
        self.assertIsNone(document['efd_fiscal_inclusion'])
        self.assertEqual('0', document['stored_total_cents'])
        self.assertEqual(before, self.database_hash())

    def test_invalid_period_and_stale_context_do_not_cross_company_year_or_module(self):
        for period in ('2026-13', '2026-1', ''):
            self.assertEqual(400, self.get(period=period).status_code)
        self.assertEqual(409, self.get(period='2025-11').status_code)
        for header, value in [('X-Company-Id', str(self.b['id'])), ('X-Year', '2025'), ('X-Module', 'accounting')]:
            self.assertEqual(409, self.get(headers={header: value}).status_code)
        result = self.client.post('/api/context', json={'company_id': self.a['id'], 'period': '2026-11', 'module': 'accounting'})
        self.assertEqual(200, result.status_code)
        self.assertEqual(409, self.get().status_code)
        with self.assertRaises(DomainError):
            contributions_snapshot(self.core, self.a['id'], 'not-a-period')

    def test_authenticated_export_requires_read_export_and_live_company_permission(self):
        with TestClient(self.app) as reader:
            self.assertEqual(401, self.get(client=reader).status_code)
            grants = [{'company_id': self.a['id'], 'routine': routine, 'action': action, 'effect': 'allow'}
                      for routine, action in [('fiscal.documents', 'export'), ('fiscal.masters', 'read')]]
            user = self.client.post('/api/users', json={'username': 'contribuicoes', 'password': 'Leitor-ficticio-123!',
                'role': 'custom', 'company_ids': [self.a['id']], 'permissions': grants})
            self.assertEqual(201, user.status_code, user.text); uid = user.json()['id']
            login = reader.post('/api/login', json={'username': 'contribuicoes', 'password': 'Leitor-ficticio-123!'})
            reader.headers['X-CSRF-Token'] = login.json()['csrf_token']; self.activate(self.a['id'], client=reader)
            self.assertEqual(403, self.get(client=reader).status_code)
            with self.core.db.transaction() as conn:
                conn.execute("INSERT INTO user_permissions(user_id,company_id,routine,action,effect) VALUES(?,?,'fiscal.documents','read','allow')", (uid, self.a['id']))
            self.assertEqual(200, self.get(client=reader).status_code)
            self.assertEqual(403, self.get(client=reader, cid=self.b['id']).status_code)
            with self.core.db.transaction() as conn:
                conn.execute("UPDATE user_permissions SET effect='deny' WHERE user_id=? AND action='export'", (uid,))
            self.assertEqual(403, self.get(client=reader).status_code)
        path = self.endpoint()
        self.assertEqual(('fiscal.documents', 'export', False), route_policy(path, 'GET', {}, {}, {}))
        self.assertNotEqual(('fiscal.documents', 'export', False), route_policy(path, 'POST', {}, {}, {}))
