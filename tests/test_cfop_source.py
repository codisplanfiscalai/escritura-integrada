"""Complete source conversion and company import, without activating tax rules."""
from copy import deepcopy
import json
import unittest
from fastapi.testclient import TestClient
import test_core as base
from app.cfop_source import build_source_bundle, default_source_bundle, load_comparison, SOURCE_KIND


class CfopSourceTests(unittest.TestCase):
    setUp = base.CoreApiTests.setUp
    tearDown = base.CoreApiTests.tearDown
    create_company = base.CoreApiTests.create_company
    activate = base.CoreApiTests.activate
    scope = base.CoreApiTests.scope

    def post(self, path, payload, expected=200):
        r = self.client.post(self.scope(path), json=payload)
        self.assertEqual(expected, r.status_code, r.text[:1000]); return r.json()

    def prepare(self): return self.post('/cfop-source-loads/preview', {'date': '2026-11-09'})

    def confirm(self, preview, expected=200):
        return self.post('/cfop-source-loads', {'date': '2026-11-09', 'preview_hash': preview['preview_hash'], 'reason': 'Carga sintética de conferência, sem ativar tributação'}, expected)

    def test_all_records_rebuild_with_complete_source_text_and_declared_fields(self):
        bundle = default_source_bundle()
        self.assertEqual(bundle, build_source_bundle(bundle['source_texts'], bundle['sources']))
        self.assertEqual(779, bundle['record_count']); self.assertEqual(158, bundle['pdf_pages'])
        self.assertEqual(779, len({r['code'] for r in bundle['records']}))
        c = load_comparison(bundle, '2026-11-09')
        self.assertEqual((539, 228, 12, 13, 735), (c['official'], c['legacy'], c['unmatched'], c['without_rates'], c['different_descriptions']))
        self.assertEqual(80, len(c['official_absent_from_sources']))
        self.assertTrue(all(not r['valid_from'] and not r['valid_to'] and r['review_status']=='unreviewed' for r in bundle['records']))
        self.assertTrue(all(len(r['parameters_declared'])==8 for r in bundle['records']))

    def test_company_import_preserves_all_sources_and_completes_official_catalog(self):
        self.post('/catalogs', {'kind': 'cfop', 'code': '1102', 'description': 'Descrição local preservada', 'source': 'Teste', 'active': False}, 201)
        preview = self.prepare()
        self.assertEqual((618, 1, 619), (preview['catalogs_create'], preview['catalogs_preserve'], preview['official_catalog_count']))
        result = self.confirm(preview); self.assertEqual(779, result['record_count'])
        catalogs = self.core.catalogs(self.a['id'], 'cfop'); self.assertEqual(619, len(catalogs))
        local = next(r for r in catalogs if r['code']=='1102')
        self.assertEqual('Descrição local preservada', local['description']);self.assertFalse(local['active'])
        self.assertFalse(any(r['code'] in {'111','1999'} for r in catalogs))
        self.assertIn('2102', {r['code'] for r in catalogs})
        self.assertEqual([], self.core.catalogs(self.b['id'], 'cfop'))
        original = self.client.get(self.scope(f"/cfop-source-loads/{result['id']}/original"))
        self.assertEqual(200, original.status_code);self.assertEqual(default_source_bundle(), original.json())
        row = self.client.get(self.scope(f"/cfop-source-loads/{result['id']}/rows?search=1505")).json()['rows'][0]
        self.assertEqual([], row['rates_declared'])
        with self.app.state.db.read() as conn:
            saved = conn.execute('SELECT * FROM masters WHERE company_id=? AND kind=?', (self.a['id'], SOURCE_KIND)).fetchone()
            self.assertFalse(saved['active']);self.assertFalse(json.loads(saved['data_json'])['parameters_active'])
            self.assertEqual(0, conn.execute('SELECT COUNT(*) FROM rules WHERE company_id=?', (self.a['id'],)).fetchone()[0])

    def test_repeat_load_is_idempotent_and_does_not_overwrite_catalogs(self):
        p = self.prepare();first = self.confirm(p);again = self.confirm(p)
        self.assertEqual(first['id'], again['id']);self.assertTrue(again['duplicate']);self.assertEqual(0, again['created'])
        self.assertEqual(1, len(self.core.cfop_source_loads(self.a['id'])))
        self.assertEqual(619, len(self.core.catalogs(self.a['id'], 'cfop')))

    def test_stale_catalog_preview_rejects_import_atomically(self):
        p = self.prepare();self.post('/catalogs', {'kind': 'cfop', 'code': '1101', 'description': 'Novo cadastro local', 'source': 'Teste'}, 201)
        self.confirm(p, 409)
        self.assertEqual([], self.core.cfop_source_loads(self.a['id']))
        self.assertEqual(1, len(self.core.catalogs(self.a['id'], 'cfop')))

    def test_changed_records_and_disagreeing_sources_are_rejected(self):
        bundle = deepcopy(default_source_bundle());bundle['records'][0]['rates_declared'] = ['99.0000']
        self.post('/cfop-source-loads/preview', {'date': '2026-11-09', 'bundle': bundle}, 409)
        bundle = deepcopy(default_source_bundle());bundle['source_texts']['txt'] = bundle['source_texts']['txt'].replace('7.0000', '9.0000', 1)
        self.post('/cfop-source-loads/preview', {'date': '2026-11-09', 'bundle': bundle}, 400)
        self.assertEqual([], self.core.cfop_source_loads(self.a['id']))

    def test_read_permission_cannot_import_and_other_company_cannot_read_load(self):
        p = self.prepare();saved = self.confirm(p)
        permission = {'company_id': self.a['id'], 'routine': 'fiscal.masters', 'action': 'read', 'effect': 'allow'}
        r = self.client.post('/api/users', json={'username': 'cfop-reader', 'password': 'Senha-sintetica-2026', 'role': 'custom', 'company_ids': [self.a['id']], 'permissions': [permission]})
        self.assertEqual(201, r.status_code, r.text)
        with TestClient(self.app) as client:
            session = client.post('/api/login', json={'username':'cfop-reader', 'password':'Senha-sintetica-2026'}).json();client.headers['X-CSRF-Token']=session['csrf_token']
            self.assertEqual(200, client.post('/api/context', json={'company_id': self.a['id'], 'module':'fiscal','period':'2026-11'}).status_code)
            self.assertEqual(200, client.post(self.scope('/cfop-source-loads/preview'), json={'date':'2026-11-09'}).status_code)
            self.assertEqual(403, client.post(self.scope('/cfop-source-loads'), json={'date':'2026-11-09'}).status_code)
            self.assertEqual(403, client.get(self.scope('/cfop-source-loads', self.b['id'])).status_code)
        self.activate(self.b['id'])
        self.assertEqual(404, self.client.get(self.scope(f"/cfop-source-loads/{saved['id']}/original", self.b['id'])).status_code)


if __name__ == '__main__': unittest.main()
