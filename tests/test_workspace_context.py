"""Optional workspace selection does not relax company/year/month boundaries."""
import unittest
from fastapi.testclient import TestClient
import test_core as base


class WorkspaceContextTests(unittest.TestCase):
    setUp = base.CoreApiTests.setUp
    tearDown = base.CoreApiTests.tearDown
    scope = base.CoreApiTests.scope
    activate = base.CoreApiTests.activate
    create_company = base.CoreApiTests.create_company
    document = base.CoreApiTests.document

    def test_clear_company_preserves_data_and_remembered_exercises(self):
        created = self.client.post(self.scope('/documents'), json=self.document())
        self.assertEqual(201, created.status_code, created.text)
        self.activate(self.a['id'], '2026-02')
        before = self.client.get('/api/session').json()
        result = self.client.post('/api/context', json={'company_id': None})
        self.assertEqual(200, result.status_code, result.text)
        self.assertIsNone(result.json()['active_company_id'])
        self.assertEqual({}, result.json()['permissions'])
        self.assertEqual([], result.json()['available_modules'])
        self.assertEqual(before['period'], result.json()['period'])
        self.assertIsNone(self.client.get('/api/session').json()['active_company_id'])
        self.assertEqual(1, len(self.core.documents(self.a['id'])))
        # A stale write from a previously open view must not run without an active company.
        stale = self.client.post(self.scope('/documents'), json=self.document('STALE'))
        self.assertEqual(409, stale.status_code, stale.text)
        selected = self.client.post('/api/context', json={'company_id': self.a['id']})
        self.assertEqual(200, selected.status_code, selected.text)
        self.assertEqual('2026-02', selected.json()['period'])
        self.assertEqual(self.a['id'], selected.json()['active_company_id'])

    def test_clear_is_session_local_and_still_requires_authentication_and_csrf(self):
        other = TestClient(self.app)
        login = other.post('/api/login', json={'username': 'teste', 'password': 'Senha-ficticia-123!'})
        other.headers['X-CSRF-Token'] = login.json()['csrf_token']
        self.activate(self.b['id'], client=other)
        denied = self.client.post('/api/context', headers={'X-CSRF-Token': ''}, json={'company_id': None})
        self.assertEqual(403, denied.status_code)
        self.assertEqual(self.a['id'], self.client.get('/api/session').json()['active_company_id'])
        self.assertEqual(200, self.client.post('/api/context', json={'company_id': None}).status_code)
        self.assertEqual(self.b['id'], other.get('/api/session').json()['active_company_id'])
        other.close()
        anonymous = TestClient(self.app)
        self.assertEqual(401, anonymous.post('/api/context', json={'company_id': None}).status_code)
        anonymous.close()

    def test_omitted_company_is_not_a_clear_and_unavailable_year_stays_blocked(self):
        self.assertEqual(400, self.client.post('/api/context', json={}).status_code)
        result = self.client.post('/api/context', json={'company_id': self.a['id'], 'period': '2199-01'})
        self.assertEqual(409, result.status_code, result.text)
        self.assertEqual('exercise_missing', result.json()['code'])
        self.assertEqual(self.a['id'], self.client.get('/api/session').json()['active_company_id'])

    def test_year_only_selection_preserves_target_module_month_and_exercise_rules(self):
        self.core.create_exercise(self.a['id'], {'module': 'accounting', 'year': 2024}, 'teste')
        selected = self.client.post('/api/context', json={'company_id': self.a['id'], 'module': 'accounting', 'period': '2026-03'})
        self.assertEqual(200, selected.status_code, selected.text)
        self.client.post('/api/context', json={'company_id': self.a['id'], 'module': 'fiscal', 'period': '2026-11'})
        selected = self.client.post('/api/context', json={'company_id': self.a['id'], 'module': 'accounting', 'year': 2024})
        self.assertEqual(200, selected.status_code, selected.text)
        self.assertEqual('2024-03', selected.json()['period'])
        for year in ['invalid', 1899, 2200]:
            self.assertEqual(400, self.client.post('/api/context', json={'company_id': self.a['id'], 'year': year}).status_code)
        self.assertEqual(409, self.client.post('/api/context', json={'company_id': self.a['id'], 'year': 2199}).status_code)
        self.assertEqual('2024-03', self.client.get('/api/session').json()['period'])
