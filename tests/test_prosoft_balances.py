"""Synthetic-only SLD preparation; no external destination or certified opening."""
import json
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import test_ecd_snapshot as existing
from app.core import DomainError, digest
from app.db import request_context
from app.prosoft_balances import observed_balances, REQUIRED_READS, _project, amount


class ProsoftBalancesTests(unittest.TestCase):
    setUpBase = existing.EcdSnapshotTests.setUpBase
    setUp = existing.EcdSnapshotTests.setUp
    tearDown = existing.EcdSnapshotTests.tearDown
    scope = existing.EcdSnapshotTests.scope
    activate = existing.EcdSnapshotTests.activate
    activate_accounting = existing.EcdSnapshotTests.activate_accounting
    create_company = existing.EcdSnapshotTests.create_company
    database_hash = existing.EcdSnapshotTests.database_hash
    journal = existing.EcdSnapshotTests.journal
    create = existing.EcdSnapshotTests.create

    def get(self, start='2025-01-01', end='2025-12-31', cid=None, client=None, headers=None):
        return (client or self.client).get(self.scope('/prosoft/observed-balances', cid),
            params={'start': start, 'end': end}, headers=headers or {})

    def snapshot(self, *args, **kwargs):
        before = self.database_hash()
        response = self.get(*args, **kwargs)
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(before, self.database_hash())
        data = response.json()
        self.assertEqual(digest(data['snapshot']), data['snapshot_sha256'])
        self.assertEqual('no-store', response.headers['Cache-Control'])
        return data['snapshot']

    def party(self, code, cid=None):
        return self.core.save_master(cid or self.a['id'], 'participant',
            {'code': code, 'name': 'Nome privado sintético', 'tax_id': '', 'data': {}}, 'teste')['id']

    def test_empty_is_unknown_and_deterministic(self):
        s = self.snapshot()
        self.assertEqual(s, self.snapshot())
        self.assertEqual('blocked', s['sld_generation'])
        self.assertIsNone(s['official_opening_balances'])
        self.assertIsNone(s['destination_mappings'])
        self.assertEqual('unknown', s['historical_integrity'])
        self.assertEqual([], s['prior_history_balances'])
        self.assertEqual(12, len(s['monthly_balances']))
        for month in s['monthly_balances']:
            self.assertEqual([], month['balances'])
            self.assertEqual('no_recorded_journals', month['evidence'])
            self.assertEqual('unknown', month['completeness'])

    def test_grouping_party_center_history_reversal_and_missing_month(self):
        p1, p2 = self.party('P1'), self.party('P2')
        cc = self.core.save_cost_center(self.a['id'], {'code': 'C1', 'name': 'Sintético'}, 'teste')['id']
        prior = self.create('prior', '2024-12-31', '10.01')
        entry = self.create('parties', '2025-01-01', lines=[
            {'account_id': self.aid['3'], 'participant_id': p1, 'cost_center_id': cc, 'debit': '1.01'},
            {'account_id': self.aid['3'], 'participant_id': p2, 'cost_center_id': cc, 'debit': '2.02'},
            {'account_id': self.aid['3'], 'participant_id': p1, 'debit': '3.03'},
            {'account_id': self.aid['5'], 'credit': '6.06'}])
        reversal = self.core.reverse_journal(self.a['id'], entry['id'],
            {'date': '2025-03-01', 'reason': 'Estorno sintético'}, 'teste')
        self.create('future', '2026-01-01', '99.00')
        s = self.snapshot(end='2025-03-31')
        rows = {(r['account_id'], r['participant_id'], r['cost_center_id']): r for r in s['monthly_balances'][0]['balances']}
        self.assertEqual('101', rows[self.aid['3'], p1, cc]['observed_net_after']['cents'])
        self.assertEqual('202', rows[self.aid['3'], p2, cc]['observed_net_after']['cents'])
        self.assertEqual('303', rows[self.aid['3'], p1, None]['observed_net_after']['cents'])
        self.assertEqual('1001', rows[self.aid['3'], None, None]['observed_net_before']['cents'])
        self.assertEqual('no_recorded_journals', s['monthly_balances'][1]['evidence'])
        for row in s['monthly_balances'][2]['balances']:
            if row['participant_id']:
                self.assertEqual('0', row['observed_net_after']['cents'])
            self.assertIsNone(row['official_opening_balance'])
        self.assertEqual([prior['id'], entry['id'], reversal['id']], [j['id'] for j in s['journal_evidence']])
        self.assertEqual(reversal['id'], s['journal_evidence'][1]['reversed_by'])
        self.assertEqual(entry['id'], s['journal_evidence'][2]['reversal_of'])
        self.assertTrue(s['journal_evidence'][1]['audit_events'])
        self.assertNotIn('Nome privado', json.dumps(s))

    def test_precision_above_javascript_safe_integer(self):
        for i in range(91):
            self.create(f'large-{i}', '2025-01-01', '999999999999.99')
        row = next(r for r in self.snapshot()['monthly_balances'][0]['balances'] if r['account_id'] == self.aid['3'])
        self.assertEqual('9099999999999909', row['observed_debits']['cents'])
        self.assertEqual('90999999999999.09', row['observed_debits']['decimal'])

    def test_period_context_headers_and_company_isolation(self):
        self.create('own', '2025-01-01', '1.00')
        other = {a['access_code']: a['id'] for a in self.core.accounts(self.b['id'])}
        self.create('other', '2025-01-01', cid=self.b['id'], lines=[
            {'account_id': other['3'], 'debit': '9.00'}, {'account_id': other['5'], 'credit': '9.00'}])
        s = self.snapshot()
        self.assertEqual(1, len(s['journal_evidence']))
        for start, end in [('2025-02-29', '2025-03-01'), ('2025-03-01', '2025-02-01'), ('2024-12-31', '2025-01-01')]:
            self.assertEqual(400, self.get(start, end).status_code)
        self.assertEqual(409, self.get('2024-01-01', '2024-12-31').status_code)
        self.assertEqual(409, self.get(cid=self.b['id']).status_code)
        for header, value in [('X-Company-Id', str(self.b['id'])), ('X-Year', '2026'), ('X-Module', 'fiscal')]:
            self.assertEqual(409, self.get(headers={header: value}).status_code)
        self.client.post('/api/context', json={'company_id': self.a['id'], 'period': '2025-01', 'module': 'fiscal'})
        self.assertEqual(409, self.get().status_code)

    def test_partial_month_explicit_opening_and_closed_period(self):
        opening = self.core.create_opening(self.a['id'], self.journal('opening', '7.89', '2025-01-01'), 'teste')
        self.create('selected', '2025-01-15', '1.00')
        s = self.snapshot('2025-01-15', '2025-02-15')
        self.assertEqual('2025-01-15', s['monthly_balances'][0]['start'])
        self.assertEqual('2025-02-15', s['monthly_balances'][1]['end'])
        self.assertEqual(opening['id'], s['journal_evidence'][0]['id'])
        self.assertEqual('prior_history', s['journal_evidence'][0]['scope'])
        for operation in ('close', 'reopen'):
            r = self.client.post(self.scope('/periods/' + operation), json={'module': 'accounting', 'period': '2025-01', 'reason': 'Teste sintético'})
            self.assertEqual(200, r.status_code, r.text)
            self.assertEqual(s, self.snapshot('2025-01-15', '2025-02-15'))

    def test_auth_permissions_live_revocation_and_catalog_only(self):
        with TestClient(self.app) as anonymous:
            self.assertEqual(401, self.get(client=anonymous).status_code)
        grants = [{'company_id': self.a['id'], 'routine': r, 'action': 'read', 'effect': 'allow'} for r in REQUIRED_READS]
        result = self.client.post('/api/users', json={'username': 'sld-reader', 'password': 'Synthetic-123!',
            'role': 'custom', 'company_ids': [self.a['id']], 'permissions': grants})
        self.assertEqual(201, result.status_code, result.text)
        uid = result.json()['id']
        with TestClient(self.app) as reader:
            login = reader.post('/api/login', json={'username': 'sld-reader', 'password': 'Synthetic-123!'})
            reader.headers['X-CSRF-Token'] = login.json()['csrf_token']
            self.activate_accounting(client=reader)
            self.assertEqual(200, self.get(client=reader).status_code)
            for routine in REQUIRED_READS:
                with self.core.db.transaction() as conn:
                    conn.execute("UPDATE user_permissions SET effect='deny' WHERE user_id=? AND routine=?", (uid, routine))
                self.assertEqual(403, self.get(client=reader).status_code)
                with self.core.db.transaction() as conn:
                    conn.execute("UPDATE user_permissions SET effect='allow' WHERE user_id=? AND routine=?", (uid, routine))
            self.assertEqual(403, self.get(client=reader, cid=self.b['id']).status_code)
            with self.core.db.transaction() as conn:
                conn.execute('DELETE FROM user_permissions WHERE user_id=?', (uid,))
                conn.execute("INSERT INTO user_permissions(user_id,company_id,routine,action,effect) VALUES(?,?,'fiscal.shared_parties','read','allow')", (uid, self.a['id']))
            self.assertEqual(403, self.get(client=reader).status_code)
            with self.core.db.transaction() as conn:
                conn.execute('UPDATE users SET active=0 WHERE id=?', (uid,))
            self.assertIn(self.get(client=reader).status_code, (401, 403))

    def test_service_requires_session_and_revalidates_in_read_snapshot(self):
        with self.assertRaises(DomainError) as error:
            observed_balances(self.core, self.a['id'], '2025-01-01', '2025-01-31')
        self.assertEqual(401, error.exception.status)
        with self.core.db.read() as conn:
            session = dict(conn.execute('SELECT * FROM sessions LIMIT 1').fetchone())
        ctx = request_context.set({'user_id': session['user_id'], 'token_hash': session['token_hash']})
        try:
            with self.core.db.transaction() as conn:
                conn.execute('DELETE FROM sessions WHERE token_hash=?', (session['token_hash'],))
            with self.assertRaises(DomainError) as error:
                observed_balances(self.core, self.a['id'], '2025-01-01', '2025-01-31')
            self.assertEqual(401, error.exception.status)
        finally:
            request_context.reset(ctx)

    def test_limits_fail_without_partial_response_or_mutation(self):
        self.create('limit', '2025-01-01')
        before = self.database_hash()
        for name in ('MAX_SOURCE_ROWS', 'MAX_RESPONSE_BYTES'):
            with patch('app.prosoft_balances.' + name, 1):
                response = self.get()
            self.assertEqual(413, response.status_code, response.text)
            self.assertEqual('preparation_volume_limit', response.json()['code'])
            self.assertNotIn('snapshot', response.json())
        self.assertEqual(before, self.database_hash())

    def test_colliding_codes_in_other_company_never_merge(self):
        p1 = self.party('SAME')
        p2 = self.party('SAME', self.b['id'])
        centers = [self.core.save_cost_center(cid, {'code': 'SAME', 'name': 'Centro sintético'}, 'teste')['id']
                   for cid in (self.a['id'], self.b['id'])]
        for cid, party, center in [(self.a['id'], p1, centers[0]), (self.b['id'], p2, centers[1])]:
            accounts = {a['access_code']: a['id'] for a in self.core.accounts(cid)}
            self.create('same', '2025-01-01', cid=cid, lines=[
                {'account_id': accounts['3'], 'participant_id': party, 'cost_center_id': center, 'debit': '1.01'},
                {'account_id': accounts['5'], 'credit': '1.01'}])
        for cid, party, center in [(self.a['id'], p1, centers[0]), (self.b['id'], p2, centers[1])]:
            self.activate_accounting(cid)
            s = self.snapshot(cid=cid)
            self.assertEqual(cid, s['scope']['company_id'])
            rows = [r for r in s['monthly_balances'][0]['balances'] if r['participant_id']]
            self.assertEqual(1, len(rows))
            self.assertEqual(party, rows[0]['participant_id'])
            self.assertEqual(center, rows[0]['cost_center_id'])

    def test_import_origin_limits_and_inconsistent_stored_period(self):
        import base64
        raw = ('id;date;document;history;account;debit;credit;cost_center\n'
               'a;2025-01-03;SYN;Origem sintética;3;1.23;0.00;\n'
               'a;2025-01-03;SYN;Origem sintética;5;0.00;1.23;\n').encode()
        r = self.client.post(self.scope('/module-imports/preview'), json={'module': 'accounting',
            'layout': 'journals-v1', 'year': 2025, 'filename': 'sld-synthetic.csv',
            'content_base64': base64.b64encode(raw).decode()})
        self.assertEqual(200, r.status_code, r.text)
        batch = r.json()
        r = self.client.post(self.scope(f"/module-imports/{batch['id']}/confirm"), json={
            'module': 'accounting', 'fingerprint': batch['fingerprint'],
            'selected': [record['_selection'] for record in batch['records']]})
        self.assertEqual(200, r.status_code, r.text)
        s = self.snapshot(end='2025-01-31')
        journal = s['journal_evidence'][0]
        ref = next(x for x in journal['source_references'] if x['entity'] == 'module_imports')
        self.assertEqual(batch['id'], ref['id'])
        self.assertEqual(batch['fingerprint'], ref['fingerprint'])
        from app.prosoft_balances import _limit_source_text
        with self.core.db.read(snapshot=True) as conn:
            text_size = _limit_source_text(conn, self.a['id'], '2025-12-31')
            saved_json = conn.execute('SELECT result_json FROM module_imports WHERE id=?', (batch['id'],)).fetchone()[0]
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE module_imports SET result_json=? WHERE id=?', (saved_json + ' ' * 1000, batch['id']))
        before_text_query = self.database_hash()
        with self.core.db.read(snapshot=True) as conn:
            self.assertEqual(text_size + 1000, _limit_source_text(conn, self.a['id'], '2025-12-31'))
        with patch('app.prosoft_balances.MAX_SOURCE_TEXT_BYTES', text_size + 999), patch('app.prosoft_balances._snapshot') as reader:
            self.assertEqual(413, self.get().status_code)
            reader.assert_not_called()
        self.assertEqual(before_text_query, self.database_hash())
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE journals SET period=?, total_cents=124 WHERE id=?', ('2025-02', journal['id']))
        s = self.snapshot(end='2025-01-31')
        self.assertEqual({'JOURNAL_TOTAL_MISMATCH', 'JOURNAL_PERIOD_MISMATCH'}, {w['code'] for w in s['source_anomalies']})
        self.assertEqual([journal['id']], s['monthly_balances'][0]['journal_ids'])
        before = self.database_hash()
        with patch('app.prosoft_balances.MAX_IMPORT_JSON_CHARS', 1):
            self.assertEqual(413, self.get().status_code)
        self.assertEqual(before, self.database_hash())

    def test_projected_row_budget_counts_carry_forward_and_exact_boundary(self):
        self.create('january', '2025-01-01', '1.00')
        center = self.core.save_cost_center(self.a['id'], {'code': 'BORDER', 'name': 'Sintético'}, 'teste')['id']
        self.create('february', '2025-02-01', lines=[
            {'account_id': self.aid['3'], 'cost_center_id': center, 'debit': '1.00'},
            {'account_id': self.aid['5'], 'credit': '1.00'}])
        # January has two groups; February introduces a third. Ten empty months
        # still carry three groups each: 2 + 3 + 10 * 3 = 35 projected rows.
        before = self.database_hash()
        for budget, status in [(34, 413), (35, 200), (36, 200)]:
            with self.subTest(budget=budget), patch('app.prosoft_balances.MAX_PROJECTED_BALANCE_ROWS', budget):
                response = self.get()
                self.assertEqual(status, response.status_code, response.text)
                if status == 413:
                    self.assertEqual('preparation_volume_limit', response.json()['code'])
                    self.assertNotIn('snapshot', response.json())
                else:
                    months = response.json()['snapshot']['monthly_balances']
                    self.assertEqual(35, sum(len(m['balances']) for m in months))
                    self.assertEqual('no_recorded_journals', months[-1]['evidence'])
            self.assertEqual(before, self.database_hash())
        with patch('app.prosoft_balances.MAX_PROJECTED_BALANCE_ROWS', 5):
            s = self.snapshot(end='2025-02-28')
            self.assertEqual([2, 3], [len(m['balances']) for m in s['monthly_balances']])
        with patch('app.prosoft_balances.MAX_PROJECTED_BALANCE_ROWS', 4):
            self.assertEqual(413, self.get(end='2025-02-28').status_code)
        self.assertEqual(before, self.database_hash())

    def test_default_projected_budget_stops_before_building_excess_month(self):
        # 2,000 source lines/groups are below the 10,000 source-row cap, yet
        # twelve months would amplify them to 24,000 projected balance rows.
        source = {'scope': {'start': '2025-01-01', 'end': '2025-12-31'},
                  'opening_history': {'journals': [{'lines': [
                      {'id': i, 'account_id': 1, 'participant_id': i, 'cost_center_id': None,
                       'debit': {'cents': '1'}, 'credit': {'cents': '0'}}
                      for i in range(1, 2001)]}]}, 'journals': []}
        import copy
        original = copy.deepcopy(source)
        before = self.database_hash()
        calls = 0
        def count_amount(value):
            nonlocal calls
            calls += 1
            return amount(value)
        with patch('app.prosoft_balances.amount', side_effect=count_amount):
            with self.assertRaises(DomainError) as error:
                _project(source)
        self.assertEqual(413, error.exception.status)
        self.assertEqual('preparation_volume_limit', error.exception.code)
        # History plus four amounts per allowed monthly row. No amount from
        # month 11 is constructed: the cumulative budget is checked first.
        self.assertEqual(2000 + 4 * 20000, calls)
        self.assertEqual(original, source)
        self.assertEqual(before, self.database_hash())

    def test_zero_projected_budget_allows_empty_but_rejects_first_group(self):
        with patch('app.prosoft_balances.MAX_PROJECTED_BALANCE_ROWS', 0):
            s = self.snapshot()
            self.assertTrue(all(m['balances'] == [] for m in s['monthly_balances']))
            self.create('first-group', '2025-01-01', '1.00')
            before = self.database_hash()
            response = self.get()
            self.assertEqual(413, response.status_code)
            self.assertNotIn('snapshot', response.json())
            self.assertEqual(before, self.database_hash())

    def test_large_history_fails_before_reader_with_few_rows(self):
        from app.prosoft_balances import MAX_SOURCE_TEXT_BYTES
        journal = self.create('large-history', '2025-01-01')
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE journals SET history=? WHERE id=?', ('á' * (MAX_SOURCE_TEXT_BYTES + 1), journal['id']))
        before = self.database_hash()
        with patch('app.prosoft_balances._snapshot') as reader:
            response = self.get()
            self.assertEqual(413, response.status_code)
            self.assertEqual('preparation_volume_limit', response.json()['code'])
            self.assertNotIn('snapshot', response.json())
            reader.assert_not_called()
        self.assertEqual(before, self.database_hash())

    def test_text_budget_utf8_bytes_boundary_and_master_fields(self):
        from app.prosoft_balances import _limit_source_text
        journal = self.create('unicode', '2025-01-01')
        center = self.core.save_cost_center(self.a['id'], {'code': 'TXT', 'name': 'Centro'}, 'teste')['id']
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE journals SET history=? WHERE id=?', ('á\x00😀', journal['id']))
        with self.core.db.read(snapshot=True) as conn:
            size = _limit_source_text(conn, self.a['id'], '2025-12-31')
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE journals SET history=? WHERE id=?', ('abc', journal['id']))
        with self.core.db.read(snapshot=True) as conn:
            ascii_size = _limit_source_text(conn, self.a['id'], '2025-12-31')
            self.assertEqual(len('á\x00😀'.encode('utf-8')) - len(b'abc'), size - ascii_size)
            size = ascii_size
        before = self.database_hash()
        for limit, status in [(size - 1, 413), (size, 200), (size + 1, 200)]:
            with patch('app.prosoft_balances.MAX_SOURCE_TEXT_BYTES', limit):
                self.assertEqual(status, self.get().status_code)
            self.assertEqual(before, self.database_hash())
        for table, column, identity in [('accounts', 'name', self.aid['3']),
                                        ('cost_centers', 'name', center),
                                        ('companies', 'profile_json', self.a['id'])]:
            with self.core.db.transaction() as conn:
                old = conn.execute(f'SELECT {column} FROM {table} WHERE id=?', (identity,)).fetchone()[0]
                value = 'x' * (size + 1)
                if column == 'profile_json':
                    value = json.dumps({'synthetic_note': value})
                conn.execute(f'UPDATE {table} SET {column}=? WHERE id=?', (value, identity))
            before = self.database_hash()
            with patch('app.prosoft_balances.MAX_SOURCE_TEXT_BYTES', size), patch('app.prosoft_balances._snapshot') as reader:
                self.assertEqual(413, self.get().status_code)
                reader.assert_not_called()
            self.assertEqual(before, self.database_hash())
            with self.core.db.transaction() as conn:
                conn.execute(f'UPDATE {table} SET {column}=? WHERE id=?', (old, identity))

    def test_shared_reader_omits_balances_and_default_ecd_is_equivalent(self):
        from app.sped_generator.ecd_snapshot import _snapshot
        import copy
        self.create('prior-ecd', '2024-12-31', '1.00')
        self.create('selected-ecd', '2025-01-01', '2.00')
        before = self.database_hash()
        with self.core.db.read(snapshot=True) as conn:
            full = _snapshot(conn, self.a['id'], '2025-01-01', '2025-12-31')
            self.assertEqual(full, _snapshot(conn, self.a['id'], '2025-01-01', '2025-12-31', include_balances=True))
            with patch('app.sped_generator.ecd_snapshot.months', side_effect=AssertionError('unused ECD months')), \
                 patch('app.sped_generator.ecd_snapshot.balance_row', side_effect=AssertionError('unused ECD balances')):
                lean = _snapshot(conn, self.a['id'], '2025-01-01', '2025-12-31', include_balances=False)
        expected = copy.deepcopy(full)
        del expected['monthly_balances']
        del expected['opening_history']['recorded_balances']
        expected['derived_balances_omitted'] = True
        self.assertEqual(expected, lean)  # Includes identical journal origin hashes.
        self.assertEqual(12, len(full['monthly_balances']))
        self.assertTrue(full['opening_history']['recorded_balances'])
        with patch('app.sped_generator.ecd_snapshot.months', side_effect=AssertionError('unused ECD months')), \
             patch('app.sped_generator.ecd_snapshot.balance_row', side_effect=AssertionError('unused ECD balances')):
            result = self.snapshot()
        self.assertEqual(digest(lean), result['source_snapshot_sha256'])
        self.assertEqual(12, len(result['monthly_balances']))
        self.assertEqual(before, self.database_hash())
