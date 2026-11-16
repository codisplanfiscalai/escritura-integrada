"""Capability claims must follow the running app, not a planned serializer.

All API data comes from the existing disposable synthetic fixture.
"""
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import test_sped_generator as existing
from app.permissions import route_policy
from app.sped_generator.obligations import (
    CATALOG_PATH, obligation_catalog, register_obligation_routes,
)


def by_id(result):
    return {item['id']: item for item in result['obligations']}


class ObligationCatalogTests(unittest.TestCase):
    def test_preparation_does_not_advertise_unimplemented_generators_or_readers(self):
        result = obligation_catalog()
        obligations = by_id(result)
        self.assertEqual({'efd_icms_ipi', 'ecd', 'ecf', 'efd_contribuicoes'}, set(obligations))
        self.assertEqual('partial', obligations['efd_icms_ipi']['implementation'])
        for key in ('ecd', 'ecf', 'efd_contribuicoes'):
            self.assertEqual('not_implemented', obligations[key]['implementation'])
            self.assertEqual([], obligations[key]['exports'])
            self.assertTrue(obligations[key]['existing_services'])
            self.assertTrue(obligations[key]['pending'])
        for item in obligations.values():
            self.assertFalse(item['complete_file_generator'])
            self.assertFalse(item['validated_in_official_program'])
            self.assertTrue(all(url.startswith('https://') for url in item['reference']['sources']))

    def test_layout_revision_and_period_are_not_interchangeable(self):
        obligations = by_id(obligation_catalog())
        self.assertEqual('9', obligations['ecd']['reference']['layout'])
        self.assertEqual('12', obligations['ecf']['reference']['layout'])
        self.assertIn('2025', obligations['ecf']['reference']['period_scope'])
        self.assertIn('situações especiais de 2026', obligations['ecf']['reference']['period_scope'])
        # No Contribuições COD_VER is guessed from guide 1.35 or PGE version.
        self.assertIsNone(obligations['efd_contribuicoes']['reference']['layout'])
        self.assertIn('NT 11/12/13', obligations['efd_contribuicoes']['reference']['manual_revision'])
        self.assertIn('2026/2027', obligations['efd_contribuicoes']['reference']['period_scope'])

    def test_registration_requires_exact_method_and_path(self):
        path = '/api/companies/{cid}/sped-generator/bookkeeping-block-c'
        for routes, expected in [([], False), ([('GET', path)], False),
                                 ([('POST', path + '-other')], False), ([('POST', path)], True)]:
            with self.subTest(routes=routes):
                export = by_id(obligation_catalog(routes))['efd_icms_ipi']['exports'][1]
                self.assertEqual(expected, export['registered'])
                self.assertFalse(export['complete_file'])

    def test_running_app_addition_is_seen_without_changing_catalog(self):
        app = FastAPI()
        register_obligation_routes(app)
        with TestClient(app) as client:
            self.assertFalse(any(x['registered'] for x in by_id(client.get(CATALOG_PATH).json())['efd_icms_ipi']['exports']))
            @app.post('/api/companies/{cid}/sped-generator/bookkeeping-block-c')
            def stub(cid: int):
                return {'fixture': True}
            exports = by_id(client.get(CATALOG_PATH).json())['efd_icms_ipi']['exports']
            self.assertEqual([False, True], [x['registered'] for x in exports])
            self.assertFalse(exports[1]['validated_in_official_program'])

    def test_fresh_responses_cannot_change_support_or_requirement_policy(self):
        first = obligation_catalog()
        first['obligations'][1]['implementation'] = 'complete'
        first['obligations'][1]['reference']['sources'].clear()
        first['requirements']['fiscal_warnings_block_export'] = True
        fresh = obligation_catalog()
        self.assertEqual('not_implemented', by_id(fresh)['ecd']['implementation'])
        self.assertTrue(by_id(fresh)['ecd']['reference']['sources'])
        self.assertFalse(fresh['requirements']['fiscal_warnings_block_export'])
        self.assertTrue(fresh['requirements']['closed_period_mutations_require_reopening'])
        self.assertTrue(fresh['requirements']['preserve_originals_and_trace'])
        self.assertFalse(fresh['interoperability']['vendor_required'])
        self.assertFalse(fresh['interoperability']['transmission_implemented'])

    def test_only_metadata_get_has_global_read_policy(self):
        self.assertEqual((None, None, False), route_policy(CATALOG_PATH, 'GET', {}, {}, {}))
        for path, method in [(CATALOG_PATH, 'POST'), (CATALOG_PATH + '/export', 'GET'),
                             ('/api/companies/1/sped-generator/consolidation-export', 'POST')]:
            with self.subTest(path=path, method=method):
                self.assertNotEqual((None, None, False), route_policy(path, method, {}, {}, {}))


class ObligationCatalogApiTests(unittest.TestCase):
    setUp = existing.SpedGeneratorApiTests.setUp
    tearDown = existing.SpedGeneratorApiTests.tearDown
    scope = existing.SpedGeneratorApiTests.scope
    activate = existing.SpedGeneratorApiTests.activate
    create_company = existing.SpedGeneratorApiTests.create_company
    database_hash = existing.SpedGeneratorApiTests.database_hash

    def test_authentication_and_readonly_metadata_without_company_leak(self):
        with TestClient(self.app) as anonymous:
            self.assertEqual(401, anonymous.get(CATALOG_PATH).status_code)
        before = self.database_hash()
        result = self.client.get(CATALOG_PATH)
        self.assertEqual(200, result.status_code, result.text)
        self.assertNotIn(self.a['tax_id'], result.text)
        self.assertNotIn(self.b['name'], result.text)
        self.assertEqual(result.json(), self.client.get(CATALOG_PATH).json())
        self.assertEqual(before, self.database_hash())
        registered = {x['id']: x['registered'] for x in by_id(result.json())['efd_icms_ipi']['exports']}
        self.assertTrue(registered['native_consolidation'])
        # The optional sibling PR may be integrated later; compare actual routes.
        present = any(getattr(r, 'path', '') == '/api/companies/{cid}/sped-generator/bookkeeping-block-c'
                      and 'POST' in getattr(r, 'methods', ()) for r in self.app.routes)
        self.assertEqual(present, registered['bookkeeping_block_c'])

    def test_accounting_reader_sees_metadata_but_does_not_gain_fiscal_export(self):
        r = self.client.post('/api/users', json={
            'username': 'catalogo-contabil', 'password': 'Catalogo-ficticio-123!', 'role': 'custom',
            'company_ids': [self.a['id']], 'permissions': [
                {'company_id': self.a['id'], 'routine': 'accounting.journals', 'action': 'read', 'effect': 'allow'}]})
        self.assertEqual(201, r.status_code, r.text)
        with TestClient(self.app) as reader:
            login = reader.post('/api/login', json={'username': 'catalogo-contabil', 'password': 'Catalogo-ficticio-123!'})
            self.assertEqual(200, login.status_code, login.text)
            reader.headers['X-CSRF-Token'] = login.json()['csrf_token']
            # The catalog is global and does not require activating a fiscal company.
            self.assertEqual(200, reader.get(CATALOG_PATH).status_code)
            self.activate(self.a['id'], client=reader)
            r = reader.post('/api/context', json={'company_id': self.a['id'], 'period': '2026-11', 'module': 'accounting'})
            self.assertEqual(200, r.status_code, r.text)
            self.assertEqual(200, reader.get(CATALOG_PATH).status_code)
            r = reader.post(self.scope('/sped-generator/consolidation-export'),
                            json={'period': '2026-11', 'import_id': 1})
            self.assertEqual(403, r.status_code, r.text)

    def test_catalog_only_adds_metadata_and_preserves_preparation_endpoints(self):
        def routes(app):
            return {(method, route.path) for route in app.routes
                    for method in getattr(route, 'methods', ())}

        app = FastAPI()
        before = routes(app)
        register_obligation_routes(app)
        self.assertEqual({('GET', CATALOG_PATH)}, routes(app) - before)

        # ECD snapshots and ECF references already belong to develop; neither
        # constitutes a complete obligation generator supplied by this catalog.
        installed = routes(self.app)
        for path in ('/api/sped/ecf-references',
                     '/api/companies/{cid}/sped-generator/accounting-snapshot'):
            self.assertIn(('GET', path), installed)
        response = self.client.get(CATALOG_PATH)
        self.assertEqual(200, response.status_code, response.text)
        obligations = by_id(response.json())
        for name in ('ecd', 'ecf', 'efd_contribuicoes'):
            self.assertEqual([], obligations[name]['exports'])
            self.assertFalse(obligations[name]['complete_file_generator'])
            self.assertFalse(obligations[name]['validated_in_official_program'])
