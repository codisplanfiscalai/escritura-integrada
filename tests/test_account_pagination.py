"""SQL pagination/search regression tests, with 22,597 synthetic accounts."""
from contextlib import contextmanager
import json
import sqlite3
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import create_app
from app.core import DomainError, now, pack
from app.global_account_plans import summary
from scripts.benchmark_workspace import fixture_workspace


class AccountPaginationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_workspace()
        folder, self.meta = self.fixture.__enter__()
        self.app = create_app(folder, demo=True)
        self.core = self.app.state.core
        self.client = TestClient(self.app)
        login = self.client.post('/api/demo-login')
        self.assertEqual(200, login.status_code, login.text)
        self.client.headers['X-CSRF-Token'] = login.json()['csrf_token']
        self.cid = self.meta['company_id']
        self.other = self.meta['other_company_id']
        self.path = f'/api/companies/{self.cid}/accounts'
        response = self.client.post('/api/context', json={'company_id': self.cid, 'period': '2026-11'})
        self.assertEqual(200, response.status_code, response.text)

    def tearDown(self):
        self.client.close()
        self.app.state.auditor.close()
        self.fixture.__exit__(None, None, None)

    def get(self, **params):
        response = self.client.get(self.path, params=params)
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def counts(self):
        with self.core.db.read() as conn:
            return {table: conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                    for table in ('accounts', 'global_account_entries', 'company_account_aliases',
                                  'account_plan_metadata', 'global_account_plan_links', 'audit')}

    def test_pages_match_legacy_order_ids_flags_and_last_page(self):
        before = self.counts()
        legacy = self.get()
        self.assertIsInstance(legacy, list)
        self.assertEqual(22597, len(legacy))
        self.assertEqual(legacy, self.core.accounts(self.cid))
        self.assertEqual(sorted(legacy, key=lambda row: (row['classifier'], row['access_code'])), legacy)
        self.assertEqual(22591, sum(row['id'] < 0 for row in legacy))
        self.assertEqual(6, sum(row['id'] > 0 for row in legacy))
        for page, size in ((1, 50), (20, 50), (452, 50), (999, 50), (1, 5000), (5, 5000), (1, 1)):
            with self.subTest(page=page, size=size):
                result = self.get(page=page, per_page=size)
                self.assertEqual({'items', 'total', 'page', 'per_page'}, set(result))
                self.assertEqual((22597, page, size), (result['total'], result['page'], result['per_page']))
                self.assertEqual(legacy[(page-1)*size:page*size], result['items'])
                for row in result['items']:
                    for key in ('analytical', 'requires_cost_center', 'active'):
                        self.assertIs(type(row[key]), bool)
        self.assertEqual(47, len(self.get(page=452)['items']))
        self.assertEqual([], self.get(page=999)['items'])
        self.assertEqual(before, self.counts(), 'Reading pages must not materialize shared references.')
        # A caller opting out of pagination continues to receive the full array.
        self.assertEqual(legacy, self.get(per_page=1))

    def test_search_is_unicode_folded_literal_and_spans_all_display_fields(self):
        last = next(row for row in self.get(page=452)['items'] if row['access_code'] == self.meta['last_access_code'])
        for term in ('ultima acao', 'ÚLTIMA AÇÃO', 'u\u0301ltima ac\u0327a\u0303o', 'STRASSE',
                     '100%', '%_literal\\fim', 'p22591', last['classifier'] + ' Última'):
            with self.subTest(search=term):
                result = self.get(page=1, search=term)
                self.assertEqual([last], result['items'])
                self.assertEqual(1, result['total'])
        for term in ('%', '_', '\\'):
            result = self.get(page=1, search=term)
            self.assertEqual([last], result['items'], 'SQL wildcard characters must remain literal.')
        by_classifier = self.get(page=1, search=last['classifier'])
        self.assertEqual([last], by_classifier['items'])
        self.assertEqual([last], self.get(search='ultima acao'), 'Unpaged filtered results stay arrays.')
        self.assertEqual([], self.get(page=1, search="%' OR 1=1 --")['items'])
        self.assertEqual(22597, self.get(page=1, search='  ')['total'])
        page = self.get(page=20, per_page=17, search='CONTA SINTÉTICA')
        all_matches = self.get(search='conta sintetica')
        self.assertEqual(len(all_matches), page['total'])
        self.assertEqual(all_matches[323:340], page['items'])

    def test_invalid_limits_and_sqlite_integer_offset_never_return_500(self):
        for params in ({'page': 0}, {'page': -1}, {'per_page': 0}, {'per_page': -1},
                       {'per_page': 5001}, {'page': 2**63, 'per_page': 50},
                       {'page': 2**63 + 1, 'per_page': 1}, {'search': 'x' * 201}):
            with self.subTest(params=params):
                response = self.client.get(self.path, params=params)
                self.assertEqual(400, response.status_code, response.text)
        for params in ({'page': '1.5'}, {'page': 'true'}, {'per_page': 'NaN'}):
            self.assertEqual(422, self.client.get(self.path, params=params).status_code)
        # The largest supported offset is valid and just returns an empty page.
        self.assertEqual([], self.get(page=2**63, per_page=1)['items'])
        for kwargs in ({'page': True}, {'page': 1.5}, {'per_page': False}, {'per_page': 1.5}, {'search': []}):
            with self.subTest(kwargs=kwargs), self.assertRaises(DomainError):
                self.core.accounts(self.cid, **kwargs)

    def test_company_scope_is_preserved_and_reads_need_permission(self):
        other = self.client.get(f'/api/companies/{self.other}/accounts', params={'page': 1}).json()
        self.assertEqual(6, other['total'])
        self.assertTrue(all(row['company_id'] == self.other and row['id'] > 0 for row in other['items']))
        self.assertEqual(0, self.core.accounts(self.other, page=1, search='ultima')['total'])
        self.assertEqual(404, self.client.get('/api/companies/999999/accounts?page=1').status_code)
        with TestClient(self.app) as anonymous:
            self.assertEqual(401, anonymous.get(self.path + '?page=1').status_code)
        user = self.client.post('/api/users', json={'username': 'limited-pager', 'password': 'Synthetic-test-password-123',
            'role': 'custom', 'company_ids': [self.other], 'permissions': [
                {'company_id': self.other, 'routine': 'accounting.accounts', 'action': 'read', 'effect': 'allow'}]})
        self.assertEqual(201, user.status_code, user.text)
        with TestClient(self.app) as limited:
            login = limited.post('/api/login', json={'username': 'limited-pager', 'password': 'Synthetic-test-password-123'})
            self.assertEqual(200, login.status_code, login.text)
            self.assertEqual(403, limited.get(self.path + '?page=1').status_code)
            self.assertEqual(200, limited.get(f'/api/companies/{self.other}/accounts?page=1').status_code)

    def test_sql_limit_and_snapshot_are_used_instead_of_python_slicing(self):
        statements = []
        calls = []
        original_read = self.core.db.read
        @contextmanager
        def observed_read(snapshot=False):
            calls.append(snapshot)
            with original_read(snapshot=snapshot) as conn:
                conn.set_trace_callback(statements.append)
                yield conn
        with patch.object(self.core.db, 'read', observed_read):
            result = self.core.accounts(self.cid, page=20, per_page=50)
        self.assertEqual(50, len(result['items']))
        self.assertEqual([True], calls)
        queries = [sql for sql in statements if 'FROM effective_accounts' in sql]
        self.assertEqual(2, len(queries))
        self.assertIn('SELECT COUNT(*)', queries[0])
        self.assertIn('LIMIT 50 OFFSET 950', queries[1])

    def test_count_and_items_remain_one_snapshot_during_concurrent_insert(self):
        original_read = self.core.db.read
        inserted = []
        database = self.core.db
        class ConnectionProxy:
            def __init__(self, conn):
                self.conn = conn
            def __getattr__(self, name):
                return getattr(self.conn, name)
            def execute(self, sql, parameters=()):
                cursor = self.conn.execute(sql, parameters)
                if sql.startswith('SELECT COUNT(*) FROM effective_accounts') and not inserted:
                    with database.transaction() as writer:
                        writer.execute('''INSERT INTO accounts(company_id,access_code,classifier,name,nature,analytical,requires_cost_center)
                            VALUES(?,'CONCURRENT','0','New concurrent account','debit',1,0)''', (self_cid,))
                    inserted.append(True)
                return cursor
        self_cid = self.cid
        @contextmanager
        def concurrent_read(snapshot=False):
            with original_read(snapshot=snapshot) as conn:
                yield ConnectionProxy(conn)
        expected = self.core.accounts(self.cid, page=1)
        with patch.object(database, 'read', concurrent_read):
            actual = self.core.accounts(self.cid, page=1)
        self.assertTrue(inserted)
        self.assertEqual(expected, actual)
        self.assertEqual(22598, self.core.accounts(self.cid, page=1)['total'])

    def test_used_lazy_reference_preserves_id_fields_and_other_company_scope(self):
        from app.account_refs import resolve_account
        virtual = self.get(page=452)['items'][-1]
        with self.core.db.transaction() as conn:
            conn.execute('''INSERT INTO company_account_plan_bindings(company_id,global_plan_id,mode,attached_at,attached_by)
                VALUES(?,?,'shared',?,'synthetic-test')''', (self.other, self.meta['global_plan_id'], now()))
        other_virtual = self.core.accounts(self.other, page=1, search=virtual['access_code'])['items'][0]
        self.assertEqual(virtual | {'company_id': self.other}, other_virtual)
        before = self.counts()
        with self.core.db.transaction() as conn:
            allocated = resolve_account(conn, self.cid, virtual['id'], materialize=True, actor='synthetic-test')
        self.assertGreater(allocated['id'], 0)
        after_use = self.counts()
        self.assertEqual(before['accounts'] + 1, after_use['accounts'])
        result = self.get(page=1, search=virtual['access_code'])
        self.assertEqual(1, result['total'])
        expected = virtual | {'id': allocated['id']}
        self.assertEqual([expected], result['items'])
        self.assertEqual(22597, self.get(page=1)['total'])
        self.assertEqual(22597, self.core.accounts(self.other, page=1)['total'])
        self.assertEqual([other_virtual], self.core.accounts(self.other, page=1, search=virtual['access_code'])['items'])
        with self.core.db.read() as conn:
            raw = conn.execute('SELECT * FROM accounts WHERE id=?', (allocated['id'],)).fetchone()
            self.assertIsNone(raw['name'])
            self.assertIsNone(raw['classifier'])
            self.assertEqual([], list(conn.execute('PRAGMA foreign_key_check')))
        self.assertEqual(after_use, self.counts())

    def test_own_binding_never_exposes_unallocated_global_accounts(self):
        from app.account_refs import resolve_account
        virtual = self.get(page=452)['items'][-1]
        with self.core.db.transaction() as conn:
            allocated = resolve_account(conn, self.cid, virtual['id'], materialize=True, actor='synthetic-test')
            # Models the used-only own scope: historical refs stay available,
            # but the unallocated shared library must no longer be exposed.
            conn.execute("UPDATE company_account_plan_bindings SET mode='own',copy_scope='used' WHERE company_id=?", (self.cid,))
        result = self.get(page=1)
        self.assertEqual(7, result['total'])
        self.assertEqual(self.get(), result['items'])
        self.assertTrue(all(row['id'] > 0 for row in result['items']))
        self.assertEqual([virtual | {'id': allocated['id']}], self.get(page=1, search=virtual['access_code'])['items'])

    def test_global_library_returns_exact_metadata_without_blob_or_full_json(self):
        # Add an empty version to cover zero counts and parent/version metadata.
        with self.core.db.transaction() as conn:
            row = dict(conn.execute('SELECT * FROM global_account_plans WHERE id=?', (self.meta['global_plan_id'],)).fetchone())
            plan = json.loads(row['plan_json'])
            plan['accounts'] = []
            row.update(name='Empty synthetic version', parent_id=row['id'], plan_json=pack(plan), original=b'synthetic original', created_at=now())
            columns = [key for key in row if key != 'id']
            conn.execute(f"INSERT INTO global_account_plans({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", [row[key] for key in columns])
        with self.core.db.read() as conn:
            expected = [summary(dict(row)) for row in conn.execute('SELECT * FROM global_account_plans ORDER BY id DESC')]
            binding = dict(conn.execute('SELECT * FROM company_account_plan_bindings WHERE company_id=?', (self.cid,)).fetchone())
        original_connect = self.core.db.connect
        def checked_connect():
            conn = original_connect()
            def rows(cursor, values):
                names = [column[0] for column in cursor.description]
                self.assertNotIn('original', names)
                self.assertNotIn('plan_json', names, 'Only extracted properties may cross into Python.')
                return sqlite3.Row(cursor, values)
            conn.row_factory = rows
            return conn
        with patch.object(self.core.db, 'connect', checked_connect), patch('app.global_account_plans.summary', side_effect=AssertionError('Full JSON summary is forbidden on the list')):
            actual = self.core.global_account_plans(self.cid)
        self.assertEqual({'binding': binding, 'plans': expected}, actual)
        large = actual['plans'][1]
        self.assertEqual((22591, 11296, 11295), (large['record_count'], large['classifier_count'], large['repeated_classifier_records']))
        self.assertEqual((0, 0, 0), tuple(actual['plans'][0][key] for key in ('record_count', 'classifier_count', 'repeated_classifier_records')))
        response = self.client.get(f'/api/companies/{self.cid}/global-account-plans')
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(actual, response.json())

    def test_fixture_is_synthetic_and_has_exact_financial_volume(self):
        response = self.client.get(f'/api/companies/{self.cid}/titles')
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(183, len(response.json()))
        self.assertTrue(all(row['company_id'] == self.cid and row['kind'] == 'payable' for row in response.json()))
        self.assertEqual({f'Título sintético {i:03}' for i in range(183)}, {row['description'] for row in response.json()})
        self.assertEqual({self.meta['title_partner']}, {row['partner_name'] for row in response.json()})
        self.assertEqual(1830000, sum(row['amount_cents'] for row in response.json()))
        from scripts.benchmark_workspace import seed_workspace
        with self.assertRaises(ValueError):
            seed_workspace(self.core)
        with patch.object(self.core, 'demo', False), self.assertRaises(ValueError):
            seed_workspace(self.core)


if __name__ == '__main__':
    unittest.main()
