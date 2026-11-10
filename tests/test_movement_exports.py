"""Full filtered Excel searches; disposable synthetic databases only."""
import os
import tempfile
import unittest
from io import BytesIO
from openpyxl import load_workbook
from fastapi.testclient import TestClient

_IMPORT = tempfile.TemporaryDirectory(prefix='movement-export-import-')
os.environ['ESCRITURA_DATA_DIR'] = _IMPORT.name
import test_core as base


class MovementExportTests(unittest.TestCase):
    setUp = base.CoreApiTests.setUp
    tearDown = base.CoreApiTests.tearDown
    scope = base.CoreApiTests.scope
    activate = base.CoreApiTests.activate
    create_company = base.CoreApiTests.create_company
    document = base.CoreApiTests.document
    journal = base.CoreApiTests.journal

    def context(self, module):
        r = self.client.post('/api/context', json={'company_id': self.a['id'], 'module': module, 'period': '2026-11'})
        self.assertEqual(200, r.status_code, r.text)

    def export(self, kind, **params):
        r = self.client.get(self.scope(f'/movement-exports/{kind}.xlsx'), params={'year': 2026, **params})
        self.assertEqual(200, r.status_code, r.text[:500])
        self.assertIn('spreadsheetml', r.headers['content-type'])
        return load_workbook(BytesIO(r.content))

    def test_documents_filters_and_formula_text(self):
        self.context('fiscal')
        for number, partner in [('=1+1', 'São João'), ('other', 'Outra empresa')]:
            r = self.client.post(self.scope('/documents'), json=self.document(number) | {'partner_name': partner})
            self.assertEqual(201, r.status_code, r.text)
        wb = self.export('documents', query='sao joao', month='11', direction='incoming', status='pending')
        sheet = wb['Dados']
        self.assertEqual(2, sheet.max_row)
        cells = list(sheet[2])
        formula_text = next(c for c in cells if c.value == '=1+1')
        self.assertEqual('s', formula_text.data_type)
        self.assertEqual(100, next(c.value for c in cells if c.number_format.startswith('#,##0.00')))
        self.assertEqual(1, self.export('documents', month='10')['Dados'].max_row)

    def test_journal_search_and_context(self):
        self.context('accounting')
        for i in range(3):
            r = self.client.post(self.scope('/journals'), json=self.journal(str(i)))
            self.assertEqual(201, r.status_code, r.text)
        self.assertEqual(4, self.export('journals', query='sintetica')['Dados'].max_row)
        self.assertEqual(1, self.export('journals', query='not-present')['Dados'].max_row)
        self.assertEqual(409, self.client.get(self.scope('/movement-exports/journals.xlsx'), params={'year': 2025}).status_code)
        self.assertEqual(409, self.client.get(self.scope('/movement-exports/journals.xlsx', self.b['id']), params={'year': 2026}).status_code)
        self.context('fiscal')
        self.assertEqual(409, self.client.get(self.scope('/movement-exports/journals.xlsx'), params={'year': 2026}).status_code)

    def test_export_requires_read_and_export_permissions(self):
        self.context('fiscal')
        permissions = [{'company_id': self.a['id'], 'routine': 'fiscal.documents', 'action': action, 'effect': 'allow'} for action in ('read', 'export')]
        r = self.client.post('/api/users', json={'username': 'exporter', 'password': 'Export-ficticio-123!', 'role': 'custom', 'company_ids': [self.a['id']], 'permissions': permissions})
        self.assertEqual(201, r.status_code, r.text)
        uid = r.json()['id']
        with TestClient(self.app) as client:
            r = client.post('/api/login', json={'username': 'exporter', 'password': 'Export-ficticio-123!'})
            client.headers['X-CSRF-Token'] = r.json()['csrf_token']
            r = client.post('/api/context', json={'company_id': self.a['id'], 'period': '2026-11', 'module': 'fiscal'})
            self.assertEqual(200, r.status_code, r.text)
            url = self.scope('/movement-exports/documents.xlsx') + '?year=2026'
            self.assertEqual(200, client.get(url).status_code)
            for action in ('read', 'export'):
                with self.app.state.db.transaction() as conn:
                    conn.execute("UPDATE user_permissions SET effect='allow' WHERE user_id=?", (uid,))
                    conn.execute("UPDATE user_permissions SET effect='deny' WHERE user_id=? AND action=?", (uid, action))
                self.assertEqual(403, client.get(url).status_code)

    def test_complete_search_exceeds_page_size(self):
        self.context('fiscal')
        r = self.client.post(self.scope('/documents'), json=self.document('template'))
        self.assertEqual(201, r.status_code, r.text)
        # Clone only synthetic rows in this disposable test database, without HTTP overhead.
        with self.app.state.db.transaction() as conn:
            row = dict(conn.execute('SELECT * FROM documents WHERE id=?', (r.json()['id'],)).fetchone())
            row.pop('id')
            for i in range(1001):
                row['number'] = f'export-match-{i}'
                row['payload_hash'] = f'export-match-hash-{i}'
                row['business_key'] = f'export-match-key-{i}'
                conn.execute(f"INSERT INTO documents ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", list(row.values()))
        self.assertEqual(1002, self.export('documents', query='export-match')['Dados'].max_row)


if __name__ == '__main__':
    unittest.main()
