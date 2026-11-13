"""Adversarial HTTP checks for bulk operations, using temporary synthetic data only."""
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

# app.api has a module-level application: isolate even that import from real data.
_IMPORT_DATA = tempfile.TemporaryDirectory(prefix='escritura-bulk-import-')
os.environ['ESCRITURA_DATA_DIR'] = _IMPORT_DATA.name
from fastapi.testclient import TestClient
import test_core as base


class BulkSecurityTests(unittest.TestCase):
    setUp = base.CoreApiTests.setUp
    tearDown = base.CoreApiTests.tearDown
    scope = base.CoreApiTests.scope
    activate = base.CoreApiTests.activate
    create_company = base.CoreApiTests.create_company
    journal = base.CoreApiTests.journal
    document = base.CoreApiTests.document

    def context(self, module='accounting', period='2026-11', client=None, cid=None):
        r = (client or self.client).post('/api/context', json={
            'company_id': cid or self.a['id'], 'module': module, 'period': period})
        self.assertEqual(200, r.status_code, r.text)

    def movement(self, kind='journals', key='synthetic-1'):
        self.context('accounting' if kind == 'journals' else 'fiscal')
        payload = self.journal(key) if kind == 'journals' else self.document(key)
        r = self.client.post(self.scope('/' + kind), json=payload)
        self.assertEqual(201, r.status_code, r.text)
        return r.json()

    def preview(self, ids, kind='journals', client=None, **extra):
        return (client or self.client).post(self.scope('/bulk-operations/preview'), json={
            'kind': kind, 'action': 'delete', 'period': '2026-11', 'ids': ids,
            'changes': {}, 'include_linked_journals': False, **extra})

    def ready(self, ids, kind='journals', **extra):
        r = self.preview(ids, kind, **extra)
        self.assertEqual(200, r.status_code, r.text)
        p = r.json()
        self.assertTrue(p['can_confirm'], p)
        self.assertFalse(p['blockers'], p)
        self.assertLessEqual(len(p['rows']), 100)
        return p

    def confirmation(self, p):
        return {'preview_id': p['id'], 'preview_hash': p['preview_hash'],
                'reason': 'Exclusão de dados exclusivamente sintéticos',
                'confirmation_phrase': p['confirmation_phrase'], 'irreversible_acknowledged': True}

    def confirm(self, p, client=None, **extra):
        return (client or self.client).post(self.scope('/bulk-operations/confirm'),
                                           json=self.confirmation(p) | extra)

    def exists(self, kind, rid):
        with self.app.state.db.read() as conn:
            return conn.execute(f'SELECT 1 FROM {kind} WHERE id=?', (rid,)).fetchone() is not None

    def assert_integrity(self):
        with self.app.state.db.read() as conn:
            self.assertEqual([], list(conn.execute('PRAGMA foreign_key_check')))
            self.assertEqual('ok', conn.execute('PRAGMA integrity_check').fetchone()[0])

    def login(self, username='teste', password='Senha-ficticia-123!'):
        c = TestClient(self.app)
        self.addCleanup(c.close)
        r = c.post('/api/login', json={'username': username, 'password': password})
        self.assertEqual(200, r.status_code, r.text)
        c.headers['X-CSRF-Token'] = r.json()['csrf_token']
        self.context(client=c)
        return c

    def test_authentication_and_csrf_on_both_endpoints(self):
        j = self.movement()
        p = self.ready([j['id']])
        with TestClient(self.app) as anonymous:
            for endpoint, body in [('preview', {'kind': 'journals'}), ('confirm', self.confirmation(p))]:
                r = anonymous.post(self.scope('/bulk-operations/' + endpoint), json=body)
                self.assertEqual(401, r.status_code, r.text)
                r = self.client.post(self.scope('/bulk-operations/' + endpoint), json=body,
                                     headers={'X-CSRF-Token': ''})
                self.assertEqual(403, r.status_code, r.text)
        self.assertTrue(self.exists('journals', j['id']))

    def test_confirmation_requires_hash_and_ack(self):
        j = self.movement()
        p = self.ready([j['id']])
        for changes in [{'preview_hash': 'forged'},
                        {'irreversible_acknowledged': False}, {'irreversible_acknowledged': 'true'}]:
            with self.subTest(changes=changes):
                r = self.confirm(p, **changes)
                self.assertIn(r.status_code, (400, 409, 422), r.text)
                self.assertTrue(self.exists('journals', j['id']))
        for field in ('preview_hash', 'irreversible_acknowledged'):
            body = self.confirmation(p)
            del body[field]
            r = self.client.post(self.scope('/bulk-operations/confirm'), json=body)
            self.assertIn(r.status_code, (400, 409, 422), r.text)
        self.assert_integrity()

    def test_same_user_other_session_cannot_confirm(self):
        j = self.movement()
        p = self.ready([j['id']])
        r = self.confirm(p, client=self.login())
        self.assertIn(r.status_code, (403, 404, 409), r.text)
        self.assertTrue(self.exists('journals', j['id']))

    def test_another_admin_cannot_confirm(self):
        j = self.movement()
        p = self.ready([j['id']])
        r = self.client.post('/api/users', json={'username': 'outro-admin', 'password': 'Outra-senha-ficticia-123!', 'role': 'admin'})
        self.assertEqual(201, r.status_code, r.text)
        r = self.confirm(p, client=self.login('outro-admin', 'Outra-senha-ficticia-123!'))
        self.assertIn(r.status_code, (403, 404, 409), r.text)
        self.assertTrue(self.exists('journals', j['id']))

    def test_read_edit_permission_does_not_grant_delete(self):
        j = self.movement()
        permissions = [{'company_id': self.a['id'], 'routine': 'accounting.journals', 'action': action, 'effect': 'allow'} for action in ('read', 'edit')]
        r = self.client.post('/api/users', json={'username': 'editor', 'password': 'Editor-ficticio-123!', 'role': 'custom', 'company_ids': [self.a['id']], 'permissions': permissions})
        self.assertEqual(201, r.status_code, r.text)
        r = self.preview([j['id']], client=self.login('editor', 'Editor-ficticio-123!'))
        self.assertEqual(403, r.status_code, r.text)
        self.assertTrue(self.exists('journals', j['id']))

    def test_wrong_company_module_and_year_fail_closed(self):
        j = self.movement()
        p = self.ready([j['id']])
        r = self.client.post(self.scope('/exercises'), json={'module': 'accounting', 'year': 2025})
        self.assertIn(r.status_code, (200, 201), r.text)
        for kwargs in ({'cid': self.b['id']}, {'module': 'fiscal'}, {'period': '2025-11'}):
            self.context(**kwargs)
            r = self.confirm(p)
            self.assertIn(r.status_code, (400, 403, 404, 409), r.text)
            self.assertTrue(self.exists('journals', j['id']))
        self.context()
        r = self.preview([j['id']], period='2025-11')
        self.assertIn(r.status_code, (400, 403, 409), r.text)

    def test_close_after_preview_does_not_reopen_or_delete(self):
        j = self.movement()
        p = self.ready([j['id']])
        r = self.client.post(self.scope('/periods/close'), json={'period': '2026-11', 'module': 'accounting', 'reason': 'Fechamento sintético'})
        self.assertEqual(200, r.status_code, r.text)
        self.assertEqual(409, self.confirm(p).status_code)
        self.assertTrue(self.exists('journals', j['id']))
        with self.app.state.db.read() as conn:
            self.assertTrue(conn.execute("SELECT closed FROM period_locks WHERE company_id=? AND period='2026-11' AND module='accounting'", (self.a['id'],)).fetchone()[0])

    def test_changed_row_and_new_dependency_invalidate_preview(self):
        for dependency in (False, True):
            with self.subTest(dependency=dependency):
                j = self.movement(key=f'synthetic-{dependency}')
                p = self.ready([j['id']])
                if dependency:
                    d = self.movement('documents', key='linked-later')
                    with self.app.state.db.transaction() as conn:
                        conn.execute('UPDATE documents SET journal_id=? WHERE id=?', (j['id'], d['id']))
                else:
                    with self.app.state.db.transaction() as conn:
                        conn.execute('UPDATE journals SET history=? WHERE id=?', ('Histórico alterado depois da prévia', j['id']))
                self.context()
                self.assertEqual(409, self.confirm(p).status_code)
                self.assertTrue(self.exists('journals', j['id']))
        self.assert_integrity()

    def test_expired_preview_cannot_execute(self):
        j = self.movement()
        p = self.ready([j['id']])
        with self.app.state.db.transaction() as conn:
            conn.execute('UPDATE bulk_previews SET expires_at=0 WHERE id=?', (p['id'],))
        self.assertEqual(409, self.confirm(p).status_code)
        self.assertTrue(self.exists('journals', j['id']))

    def test_mixed_valid_missing_selection_is_all_or_nothing(self):
        j = self.movement()
        r = self.preview([j['id'], j['id'] + 999999])
        self.assertEqual(200, r.status_code, r.text)
        p = r.json()
        self.assertFalse(p['can_confirm'])
        self.assertTrue(p['blockers'])
        self.assertEqual(409, self.confirm(p).status_code)
        self.assertTrue(self.exists('journals', j['id']))
        self.assert_integrity()

    def test_failure_after_mutation_rolls_back_whole_transaction(self):
        from app.bulk_operations import BulkOperations
        from app.core import DomainError
        j = self.movement()
        p = self.ready([j['id']])
        apply = BulkOperations._apply
        def fail_after_apply(service, *args, **kwargs):
            apply(service, *args, **kwargs)
            raise DomainError('Falha sintética após mutação', 409, 'synthetic_failure')
        with patch.object(BulkOperations, '_apply', fail_after_apply):
            self.assertEqual(409, self.confirm(p).status_code)
        self.assertTrue(self.exists('journals', j['id']))
        self.assert_integrity()
        self.assertEqual(200, self.confirm(p).status_code)

    def test_concurrent_confirmation_and_replay_never_delete_reused_id(self):
        j = self.movement()
        p = self.ready([j['id']])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.confirm(p), range(2)))
        self.assertTrue(any(r.status_code == 200 for r in results), [r.text for r in results])
        self.assertTrue(all(r.status_code in (200, 409) for r in results), [r.text for r in results])
        self.assertFalse(self.exists('journals', j['id']))
        replacement = self.movement(key='new-after-deletion')
        # Normal creation must avoid tombstones. Also simulate an external restore
        # that explicitly reuses the old PK, then prove nonce replay is harmless.
        self.assertNotEqual(j['id'], replacement['id'])
        with self.app.state.db.transaction() as conn:
            row = dict(conn.execute('SELECT * FROM journals WHERE id=?', (replacement['id'],)).fetchone())
            row.update(id=j['id'], number=row['number'] + 1, idempotency_key='restored-synthetic-key')
            conn.execute('INSERT INTO journals (' + ','.join(row) + ') VALUES (' + ','.join('?' for _ in row) + ')', tuple(row.values()))
        replay = self.confirm(p)
        self.assertIn(replay.status_code, (200, 409), replay.text)
        if replay.status_code == 200:
            self.assertTrue(replay.json()['duplicate'])
        self.assertTrue(self.exists('journals', replacement['id']))
        self.assertTrue(self.exists('journals', j['id']))
        self.assert_integrity()

    def test_malformed_json_types_are_client_errors(self):
        self.context()
        with TestClient(self.app, raise_server_exceptions=False) as client:
            client.cookies.update(self.client.cookies)
            client.headers.update(self.client.headers)
            for endpoint in ('preview', 'confirm'):
                for raw in ('{', 'null', '[]', '"text"', '42'):
                    r = client.post(self.scope('/bulk-operations/' + endpoint), content=raw, headers={'Content-Type': 'application/json'})
                    self.assertIn(r.status_code, (400, 422), (endpoint, raw, r.text))
            for ids in ([], [True], ['1'], [1, 1], [-1]):
                r = client.post(self.scope('/bulk-operations/preview'), json={'kind': 'journals', 'action': 'delete', 'period': '2026-11', 'ids': ids})
                self.assertIn(r.status_code, (400, 422), r.text)

    def test_shared_linked_journal_requires_complete_selection(self):
        j = self.movement()
        docs = [self.movement('documents', key=f'shared-{n}') for n in (1, 2)]
        with self.app.state.db.transaction() as conn:
            conn.executemany('UPDATE documents SET journal_id=? WHERE id=?', [(j['id'], d['id']) for d in docs])
        for include in (False, True):
            p = self.preview([docs[0]['id']], 'documents', include_linked_journals=include).json()
            self.assertFalse(p['can_confirm'], p)
            self.assertEqual(409, self.confirm(p).status_code)
        p = self.ready([d['id'] for d in docs], 'documents', include_linked_journals=True)
        self.assertEqual(200, self.confirm(p).status_code)
        self.assertFalse(self.exists('journals', j['id']))
        for d in docs:
            self.assertFalse(self.exists('documents', d['id']))
        self.assert_integrity()

    def test_shared_source_other_document_remains_untouched(self):
        first = self.movement('documents', key='source-first')
        other = self.movement('documents', key='source-other')
        with self.app.state.db.read() as conn:
            before = [dict(r) for r in conn.execute('SELECT * FROM document_sources WHERE document_id=?', (other['id'],))]
        p = self.ready([first['id']], 'documents')
        self.assertEqual(200, self.confirm(p).status_code)
        self.assertFalse(self.exists('documents', first['id']))
        self.assertTrue(self.exists('documents', other['id']))
        with self.app.state.db.read() as conn:
            after = [dict(r) for r in conn.execute('SELECT * FROM document_sources WHERE document_id=?', (other['id'],))]
            self.assertEqual(before, after)
            self.assertEqual(0, conn.execute('SELECT count(*) FROM document_sources WHERE document_id=?', (first['id'],)).fetchone()[0])
        self.assert_integrity()

    def test_financial_dependency_blocks_entire_document_batch(self):
        first = self.movement('documents', key='free-document')
        linked = self.movement('documents', key='financial-document')
        self.context('financial')
        r = self.client.post(self.scope('/titles'), json={
            'kind': 'payable', 'description': 'Título sintético protegido',
            'partner_name': 'Parceiro fictício', 'document': 'FIN-TEST',
            'issue_date': '2026-11-06', 'due_date': '2026-12-10', 'amount': '100.00'})
        self.assertEqual(201, r.status_code, r.text)
        title_id = r.json()['id']
        with self.app.state.db.transaction() as conn:
            conn.execute('UPDATE titles SET document_id=? WHERE id=?', (linked['id'], title_id))
        self.context('fiscal')
        r = self.preview([first['id'], linked['id']], 'documents')
        self.assertEqual(200, r.status_code, r.text)
        p = r.json()
        self.assertFalse(p['can_confirm'])
        self.assertEqual(409, self.confirm(p).status_code)
        self.assertTrue(self.exists('documents', first['id']))
        self.assertTrue(self.exists('documents', linked['id']))
        self.assertTrue(self.exists('titles', title_id))
        self.assert_integrity()

    def test_invalid_nested_field_types_never_raise_server_error(self):
        self.context()
        template = {'kind': 'journals', 'action': 'delete', 'period': '2026-11', 'ids': [1]}
        with TestClient(self.app, raise_server_exceptions=False) as client:
            client.cookies.update(self.client.cookies)
            client.headers.update(self.client.headers)
            for changes in ({'kind': []}, {'action': {}}, {'period': []}, {'ids': [[1]]}, {'changes': []}):
                r = client.post(self.scope('/bulk-operations/preview'), json=template | changes)
                self.assertIn(r.status_code, (400, 422), (changes, r.text))

    def test_maximum_500_journals_delete_atomically_and_preserve_other_company(self):
        self.context()
        with self.app.state.db.transaction() as conn:
            ids = [self.core._create_journal(conn, self.a['id'], self.journal(f'limit-{n}'), 'teste')['id']
                   for n in range(500)]
            accounts_b = {r['access_code']: r['id'] for r in conn.execute(
                'SELECT id,access_code FROM accounts WHERE company_id=?', (self.b['id'],))}
            other_payload = self.journal('other-company-preserved')
            other_payload['lines'][0]['account_id'] = accounts_b['3']
            other_payload['lines'][1]['account_id'] = accounts_b['5']
            other = self.core._create_journal(conn, self.b['id'], other_payload, 'teste')
            other_before = dict(conn.execute('SELECT * FROM journals WHERE id=?', (other['id'],)).fetchone())
            lines_before = [dict(r) for r in conn.execute('SELECT * FROM journal_lines WHERE journal_id=? ORDER BY id', (other['id'],))]
            self.assertEqual(1000, conn.execute('SELECT count(*) FROM journal_lines WHERE company_id=?', (self.a['id'],)).fetchone()[0])
        p = self.ready(ids)
        self.assertEqual(500, p['selected_count'])
        self.assertEqual(100, len(p['rows']))
        self.assertEqual(500, p['affected_counts']['journals'])
        self.assertEqual(1000, p['affected_counts']['journal_lines'])
        r = self.confirm(p)
        self.assertEqual(200, r.status_code, r.text)
        self.assertTrue(r.json()['completed'])
        self.assertEqual(500, r.json()['selected_count'])
        with self.app.state.db.read() as conn:
            self.assertEqual(0, conn.execute('SELECT count(*) FROM journals WHERE company_id=?', (self.a['id'],)).fetchone()[0])
            self.assertEqual(0, conn.execute('SELECT count(*) FROM journal_lines WHERE company_id=?', (self.a['id'],)).fetchone()[0])
            self.assertEqual(other_before, dict(conn.execute('SELECT * FROM journals WHERE id=?', (other['id'],)).fetchone()))
            self.assertEqual(lines_before, [dict(row) for row in conn.execute('SELECT * FROM journal_lines WHERE journal_id=? ORDER BY id', (other['id'],))])
        repeated = self.confirm(p)
        self.assertEqual(200, repeated.status_code, repeated.text)
        self.assertTrue(repeated.json()['duplicate'])
        self.assertTrue(self.exists('journals', other['id']))
        self.assert_integrity()
