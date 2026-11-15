"""Synthetic regression for the first, read-only Gerador SPED increment."""
import base64
import copy
import hashlib
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

# Isolate the module-level app as well as each test app from user data.
_IMPORT_DATA = tempfile.TemporaryDirectory(prefix='escritura-sped-test-import-')
os.environ['ESCRITURA_DATA_DIR'] = _IMPORT_DATA.name
from fastapi.testclient import TestClient
import test_core as base
from app.core import DomainError
from app.sped_generator.consolidation import preview_nfce_groups

COMPANY_TAX_ID = '12ABC34501DE35'


def document(index=1, **changes):
    number = index
    value = {
        'id': number, 'version': 1, 'company_id': 7, 'period': '2026-11',
        'model': '65', 'direction': 'outgoing', 'number': str(number), 'series': '001',
        'key': f'{number:044d}', 'issue_date': '2026-11-05', 'posting_date': '2026-11-05',
        'total_cents': 101, 'status': 'pending', 'source_hash': hashlib.sha256(str(number).encode()).hexdigest(),
        'source': {'file': f'sintetico-{number}.xml', 'record': 'infNFe', 'line': None},
        'issuer': {'tax_id': COMPANY_TAX_ID}, 'environment': '1', 'authorization': {'status': '100'},
    }
    return value | changes


def preview(rows):
    return preview_nfce_groups(rows, company_id=7, company_tax_id=COMPANY_TAX_ID, competence='2026-11')


class NfceConsolidationTests(unittest.TestCase):
    def test_exact_totals_identity_trace_order_and_no_mutation(self):
        rows = [document(2, total_cents=999999999999999999, status='booked'),
                document(1, total_cents=1)]
        before = copy.deepcopy(rows)
        result = preview(iter(rows))
        self.assertEqual(before, rows)
        self.assertEqual(result, preview(reversed(rows)))
        self.assertEqual(1000000000000000000, result['summary']['total_cents'])
        self.assertEqual(1, result['summary']['review_pending_documents'])
        group = result['groups'][0]
        self.assertEqual([1, 2], [m['document_id'] for m in group['members']])
        self.assertEqual([r['key'] for r in reversed(rows)], [m['key'] for m in group['members']])
        self.assertFalse({'key', 'number', 'model', 'C100'} & set(group))
        self.assertEqual(before[1]['source_hash'], group['members'][0]['source_hash'])
        self.assertEqual('preview_only', result['mode'])

    def test_scope_never_includes_entries_other_models_or_third_party_issuance(self):
        changes = [
            ({'company_id': 8}, 'OTHER_COMPANY'),
            ({'period': '2026-10'}, 'OTHER_POSTING_PERIOD'),
            ({'model': '55'}, 'OTHER_MODEL'), ({'model': '57'}, 'OTHER_MODEL'),
            ({'direction': 'incoming'}, 'NOT_OUTGOING'),
            ({'issuer': {'tax_id': 'OUTRAEMPRESA01'}}, 'NOT_OWN_ISSUANCE'),
            ({'book_cancellation': {'source': 'livro sintético'}}, 'CANCELLED'),
            ({'document_state': 'cancelled'}, 'CANCELLED'),
            ({'source_hash': ''}, 'SOURCE_REQUIRED'),
            ({'source': {'type': 'manual'}}, 'ISSUANCE_EVIDENCE_REQUIRED'),
            ({'environment': '2'}, 'NON_PRODUCTION_XML'),
            ({'authorization': {}}, 'REGULAR_AUTHORIZATION_REQUIRED'),
            ({'authorization': {'status': '101'}}, 'REGULAR_AUTHORIZATION_REQUIRED'),
        ]
        for change, reason in changes:
            with self.subTest(reason=reason, change=change):
                result = preview([document(**change)])
                self.assertEqual([], result['groups'])
                self.assertEqual([{'document_id': 1, 'reason': reason}], result['excluded'])

    def test_sped_requires_explicit_own_issuance_and_regular_situation(self):
        row = document(source={'file': 'origem.efd', 'record': 'C100', 'line': 7},
                       issuer={}, raw_fields={'IND_EMIT': '0', 'COD_SIT': '00'})
        self.assertEqual(1, preview([row])['summary']['included_documents'])
        for change, reason in [({'IND_EMIT': '1', 'COD_SIT': '00'}, 'NOT_OWN_ISSUANCE'),
                               ({'COD_SIT': '00'}, 'NOT_OWN_ISSUANCE'),
                               ({'IND_EMIT': '0', 'COD_SIT': '02'}, 'NON_REGULAR_SPED')]:
            self.assertEqual(reason, preview([row | {'raw_fields': change}])['excluded'][0]['reason'])

    def test_daily_series_segments_and_original_series(self):
        rows = [document(10), document(11, series='1', declared_series='01'),
                document(13), document(14, issue_date='2026-11-06'),
                document(15, series='002')]
        result = preview(rows)
        self.assertEqual([2, 1, 1, 1], [g['document_count'] for g in result['groups']])
        self.assertEqual([1, 2, 1, 1], [g['segment'] for g in result['groups']])
        self.assertEqual('01', result['groups'][0]['members'][1]['declared_series'])
        self.assertEqual('001', result['groups'][0]['members'][0]['series'])

    def test_duplicates_exclude_every_conflicting_member(self):
        rows = [document(1), document(2, number='001', series='1'),
                document(3), document(4, key=f'{3:044d}'), document(5)]
        result = preview(rows)
        self.assertEqual([1, 2, 3, 4], [r['document_id'] for r in result['excluded']])
        self.assertEqual(['DUPLICATE_IDENTITY_OR_KEY'] * 4, [r['reason'] for r in result['excluded']])
        self.assertEqual(1, result['summary']['included_documents'])
        self.assertEqual(5, result['groups'][0]['members'][0]['document_id'])

    def test_posting_competence_keeps_original_issue_date(self):
        result = preview([document(issue_date='2026-10-31', posting_date='2026-11-03')])
        self.assertEqual('2026-11', result['period'])
        self.assertEqual('2026-10-31', result['groups'][0]['issue_date'])
        self.assertEqual('2026-11-03', result['groups'][0]['members'][0]['posting_date'])

    def test_no_grid_limit_or_silent_truncation(self):
        result = preview(document(n) for n in range(1, 5002))
        self.assertEqual(5001, result['summary']['input_documents'])
        self.assertEqual(5001, result['groups'][0]['document_count'])
        self.assertEqual(5001 * 101, result['summary']['total_cents'])
        self.assertEqual(5001, result['groups'][0]['members'][-1]['document_id'])

    def test_incomplete_identity_and_totals_are_explicit_exclusions(self):
        for field, value, reason in [
            ('key', '', 'DOCUMENT_KEY_REQUIRED'), ('number', 'abc', 'DOCUMENT_NUMBER_REQUIRED'),
            ('number', '0', 'DOCUMENT_NUMBER_REQUIRED'), ('series', '', 'NUMERIC_SERIES_REQUIRED'),
            ('series', 'A', 'NUMERIC_SERIES_REQUIRED'),
            ('issue_date', '2026-02-30', 'DOCUMENT_DATE_REQUIRED'),
            ('posting_date', '2026-10-30', 'OTHER_POSTING_PERIOD'),
            ('total_cents', True, 'INVALID_DOCUMENT_TOTAL'),
            ('total_cents', -1, 'INVALID_DOCUMENT_TOTAL'),
        ]:
            with self.subTest(field=field, value=value):
                self.assertEqual(reason, preview([document(**{field: value})])['excluded'][0]['reason'])

    def test_empty_and_invalid_period(self):
        self.assertEqual([], preview([])['groups'])
        with self.assertRaises(DomainError):
            preview_nfce_groups([], company_id=7, company_tax_id=COMPANY_TAX_ID, competence='2026-13')


class SpedGeneratorApiTests(unittest.TestCase):
    setUp = base.CoreApiTests.setUp
    tearDown = base.CoreApiTests.tearDown
    scope = base.CoreApiTests.scope
    activate = base.CoreApiTests.activate
    create_company = base.CoreApiTests.create_company

    def own_xml(self, number=1, model='65'):
        xml = (Path(__file__).parent / 'fixtures/nfe_ficticia.xml').read_text()
        key = '352611' + self.a['tax_id'] + model + '001' + f'{number:09d}' + '1' + f'{number:08d}' + '0'
        return (xml.replace('35261187654321000198550010000000421000000420', key)
                .replace('87654321000198', self.a['tax_id'])
                .replace('12345678000195', self.b['tax_id'])
                .replace('<mod>55</mod>', f'<mod>{model}</mod>')
                .replace('<nNF>42</nNF>', f'<nNF>{number}</nNF>')
                .replace('<tpAmb>2</tpAmb>', '<tpAmb>1</tpAmb>')).encode()

    def import_xmls(self, *numbers, book=False):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            for number in numbers:
                archive.writestr(f'ficticia-{number}.xml', self.own_xml(number))
        raw = buffer.getvalue()
        r = self.client.post(self.scope('/imports/preview'), json={
            'filename': 'nfce-sinteticas.zip', 'period': '2026-11',
            'content_base64': base64.b64encode(raw).decode()})
        self.assertEqual(200, r.status_code, r.text)
        batch = r.json()
        payload = {'preview_hash': batch['preview_hash']}
        if book:
            p = self.client.post(self.scope(f"/imports/{batch['id']}/posting-preview"), json={})
            self.assertEqual(200, p.status_code, p.text)
            payload |= {'posting_mode': 'book', 'posting_hash': p.json()['posting_hash']}
        r = self.client.post(self.scope(f"/imports/{batch['id']}/confirm"), json=payload)
        self.assertEqual(200, r.status_code, r.text)
        return batch, raw

    def get_preview(self, **params):
        return self.client.get(self.scope('/sped-generator/nfce-consolidation'),
                               params={'period': '2026-11'} | params)

    def database_hash(self):
        # Include every table, original BLOB, audit, financial and accounting state.
        with self.app.state.db.read(snapshot=True) as conn:
            return hashlib.sha256('\n'.join(conn.iterdump()).encode()).hexdigest()

    def test_xml_import_remains_individual_and_repeated_preview_writes_nothing(self):
        batch, raw = self.import_xmls(1, 2)
        before = self.database_hash()
        r = self.get_preview()
        self.assertEqual(200, r.status_code, r.text)
        self.assertEqual(2, r.json()['summary']['included_documents'])
        self.assertEqual(1, r.json()['summary']['groups'])
        self.assertEqual(20000, r.json()['summary']['total_cents'])
        self.assertEqual(r.json(), self.get_preview().json())
        self.assertEqual(before, self.database_hash())
        self.assertEqual(2, len(self.core.documents(self.a['id'])))
        self.assertEqual([], self.core.titles(self.a['id']))
        self.assertEqual([], self.core.journals(self.a['id']))
        with self.app.state.db.read() as conn:
            self.assertEqual(raw, conn.execute('SELECT original FROM imports WHERE id=?', (batch['id'],)).fetchone()[0])

    def test_booked_xml_import_also_supports_later_preview(self):
        self.import_xmls(1, 2, book=True)
        before = self.database_hash()
        r = self.get_preview()
        self.assertEqual(200, r.status_code, r.text)
        members = r.json()['groups'][0]['members']
        self.assertEqual(['booked', 'booked'], [m['status'] for m in members])
        self.assertTrue(all(m['review_pending'] for m in members))
        self.assertEqual(before, self.database_hash())

    def test_other_company_module_year_and_bad_period(self):
        self.import_xmls(1)
        r = self.client.get(self.scope('/sped-generator/nfce-consolidation', self.b['id']), params={'period': '2026-11'})
        self.assertEqual(409, r.status_code, r.text)
        self.assertEqual(409, self.get_preview(period='2025-11').status_code)
        self.assertEqual(400, self.get_preview(period='2026-13').status_code)
        self.assertEqual(422, self.client.get(self.scope('/sped-generator/nfce-consolidation')).status_code)
        r = self.client.post('/api/context', json={'company_id': self.a['id'], 'period': '2026-11', 'module': 'accounting'})
        self.assertEqual(200, r.status_code, r.text)
        self.assertEqual(409, self.get_preview().status_code)

    def test_period_filter_and_company_scope(self):
        self.import_xmls(1, 3)
        self.assertEqual(0, self.get_preview(period='2026-10').json()['summary']['input_documents'])
        self.activate(self.b['id'])
        r = self.client.get(self.scope('/sped-generator/nfce-consolidation', self.b['id']), params={'period': '2026-11'})
        self.assertEqual(200, r.status_code, r.text)
        self.assertEqual([], r.json()['groups'])

    def test_authentication_and_live_read_permission_revocation(self):
        self.import_xmls(1)
        endpoint = self.scope('/sped-generator/nfce-consolidation')
        with TestClient(self.app) as anonymous:
            self.assertEqual(401, anonymous.get(endpoint, params={'period': '2026-11'}).status_code)
        permissions = [{'company_id': self.a['id'], 'routine': 'fiscal.documents',
                        'action': 'read', 'effect': 'allow'}]
        r = self.client.post('/api/users', json={'username': 'leitor-sped', 'password': 'Leitor-ficticio-123!',
            'role': 'custom', 'company_ids': [self.a['id']], 'permissions': permissions})
        self.assertEqual(201, r.status_code, r.text)
        user = r.json()
        with TestClient(self.app) as reader:
            login = reader.post('/api/login', json={'username': 'leitor-sped', 'password': 'Leitor-ficticio-123!'})
            self.assertEqual(200, login.status_code, login.text)
            reader.headers['X-CSRF-Token'] = login.json()['csrf_token']
            self.activate(self.a['id'], client=reader)
            self.assertEqual(200, reader.get(endpoint, params={'period': '2026-11'}).status_code)
            with self.app.state.db.transaction() as conn:
                conn.execute("UPDATE user_permissions SET effect='deny' WHERE user_id=?", (user['id'],))
            self.assertEqual(403, reader.get(endpoint, params={'period': '2026-11'}).status_code)

    def test_sped_origin_preserves_c140_c141_and_model55_outside_preview(self):
        raw = (Path(__file__).parent / 'fixtures/sped_ficticio_020.txt').read_text()
        lines = raw.replace('12345678000195', self.a['tax_id']).splitlines()
        own_lines = []
        for line in lines:
            if line.startswith('|C100|'):
                fields = line.strip('|').split('|')
                fields[1:6] = ['1', '0', '', '65', '00']
                fields[8] = '1' * 44
                line = '|' + '|'.join(fields) + '|'
            own_lines.append(line)
        own = ('\n'.join(own_lines) + '\n').encode()
        for filename, content in [('modelo65.efd', own), ('modelo55.efd', ('\n'.join(lines) + '\n').encode())]:
            r = self.client.post(self.scope('/imports/preview'), json={'filename': filename, 'period': '2026-11',
                'content_base64': base64.b64encode(content).decode()})
            self.assertEqual(200, r.status_code, r.text)
            batch = r.json()
            r = self.client.post(self.scope(f"/imports/{batch['id']}/confirm"), json={'preview_hash': batch['preview_hash']})
            self.assertEqual(200, r.status_code, r.text)
        before = self.database_hash()
        r = self.get_preview()
        self.assertEqual(200, r.status_code, r.text)
        self.assertEqual(1, r.json()['summary']['included_documents'])
        self.assertEqual(['OTHER_MODEL'], [d['reason'] for d in r.json()['excluded']])
        self.assertEqual('C100', r.json()['groups'][0]['members'][0]['source']['record'])
        self.assertEqual(before, self.database_hash())
        for doc in self.core.documents(self.a['id']):
            self.assertEqual(2, len(doc['invoices'][0]['installments']))
