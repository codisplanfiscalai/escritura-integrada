"""Synthetic preparation evidence, never an official ECD fixture or receipt."""
import base64
import copy
import hashlib
import json
import unittest
from fastapi.testclient import TestClient
import test_sped_generator as existing
import test_global_account_plans as plans
import test_core as base
from app.core import DomainError, digest
from app.sped_generator.ecd_snapshot import accounting_snapshot, amount, bounds, months


class EcdSnapshotValueTests(unittest.TestCase):
    def test_integer_precision_signs_and_zero_without_float_or_decimal_context(self):
        for value, decimal in [(0, '0.00'), (-1, '-0.01'), (2**53 + 1, '90071992547409.93'),
                               (10**40 + 1, '100000000000000000000000000000000000000.01')]:
            self.assertEqual({'cents': str(value), 'decimal': decimal}, amount(value))

    def test_month_intervals_partial_empty_leap_and_last_supported_day(self):
        self.assertEqual([('2025-01-17', '2025-01-31'), ('2025-02-01', '2025-02-28'),
                          ('2025-03-01', '2025-03-03')], list(months('2025-01-17', '2025-03-03')))
        self.assertEqual([('2024-02-01', '2024-02-29')], list(months('2024-02-01', '2024-02-29')))
        self.assertEqual([('9999-12-31', '9999-12-31')], list(months('9999-12-31', '9999-12-31')))
        for start, end in [('2025-02-29', '2025-03-01'), ('2025-02-02', '2025-02-01'),
                           ('2024-12-31', '2025-01-01'), ('2025-1-1', '2025-01-01')]:
            with self.subTest(start=start, end=end), self.assertRaises(DomainError):
                bounds(start, end)


class EcdSnapshotTests(unittest.TestCase):
    setUpBase = existing.SpedGeneratorApiTests.setUp
    tearDown = existing.SpedGeneratorApiTests.tearDown
    scope = existing.SpedGeneratorApiTests.scope
    activate = existing.SpedGeneratorApiTests.activate
    create_company = existing.SpedGeneratorApiTests.create_company
    database_hash = existing.SpedGeneratorApiTests.database_hash
    journal = base.CoreApiTests.journal
    post = plans.GlobalAccountPlanTests.post
    publish = plans.GlobalAccountPlanTests.publish
    prepare = plans.GlobalAccountPlanTests.prepare
    confirm = plans.GlobalAccountPlanTests.confirm

    def setUp(self):
        self.setUpBase()
        for company in (self.a, self.b):
            for module in ('accounting', 'fiscal', 'financial'):
                for year in (2024, 2025):
                    self.core.create_exercise(company['id'], {'module': module, 'year': year, 'reason': 'Exercício sintético ECD'}, 'teste')
        self.activate_accounting()

    def activate_accounting(self, cid=None, period='2025-01', client=None):
        r = (client or self.client).post('/api/context', json={'company_id': cid or self.a['id'],
            'period': period, 'module': 'accounting'})
        self.assertEqual(200, r.status_code, r.text)

    def create(self, key, day, value='1.00', *, cid=None, lines=None):
        payload = self.journal(key=key, day=day, amount=value)
        if lines is not None:
            payload['lines'] = lines
        return self.core.create_journal(cid or self.a['id'], payload, 'teste')

    def get(self, start='2025-01-01', end='2025-12-31', *, cid=None, client=None):
        return (client or self.client).get(self.scope('/sped-generator/accounting-snapshot', cid), params={'start': start, 'end': end})

    def snapshot(self, *args, **kwargs):
        r = self.get(*args, **kwargs)
        self.assertEqual(200, r.status_code, r.text)
        result = r.json()
        self.assertEqual(digest(result['snapshot']), result['snapshot_sha256'])
        self.assertEqual(result['snapshot_sha256'], r.headers['X-Snapshot-SHA256'])
        self.assertIn('.json', r.headers['Content-Disposition'])
        self.assertEqual('no-store', r.headers['Cache-Control'])
        return result['snapshot']

    def test_empty_range_is_not_certified_zero_and_exports_with_informative_gaps(self):
        before = self.database_hash()
        s = self.snapshot()
        self.assertEqual([], s['journals'])
        self.assertEqual(12, len(s['monthly_balances']))
        self.assertTrue(all(month['balances'] == [] for month in s['monthly_balances']))
        self.assertEqual('0', s['reconciliation']['recorded_debits']['cents'])
        self.assertFalse(s['complete_ecd'])
        self.assertFalse(s['validated_in_official_program'])
        self.assertFalse(s['warnings_block_export'])
        self.assertFalse(s['coverage']['opening_balances_attested'])
        self.assertIsNone(s['coverage']['referential_plan'])
        self.assertIn('NO_RECORDED_JOURNALS_IN_RANGE', {x['code'] for x in s['warnings']})
        self.assertEqual(before, self.database_hash())

    def test_prior_history_is_separate_and_monthly_balances_reconcile_real_lines(self):
        old = self.create('prior', '2024-12-20', '10.01')
        jan = self.create('jan', '2025-01-17', '0.02')
        feb = self.create('feb', '2025-02-01', '2.03')
        self.create('later', '2026-01-01', '999.00')
        before = self.database_hash()
        s = self.snapshot(end='2025-03-31')
        self.assertEqual([old['id']], [j['id'] for j in s['opening_history']['journals']])
        self.assertEqual([jan['id'], feb['id']], [j['id'] for j in s['journals']])
        self.assertEqual('205', s['reconciliation']['recorded_debits']['cents'])
        self.assertTrue(s['reconciliation']['journal_totals_match'])
        balances = [{r['account_id']: r for r in m['balances']} for m in s['monthly_balances']]
        self.assertEqual(['1001', '1003', '1206'], [m[self.aid['3']]['recorded_opening']['cents'] for m in balances])
        self.assertEqual(['1003', '1206', '1206'], [m[self.aid['3']]['recorded_closing']['cents'] for m in balances])
        self.assertEqual(['-1003', '-1206', '-1206'], [m[self.aid['5']]['recorded_closing']['cents'] for m in balances])
        self.assertEqual(['D'] * 3, [m[self.aid['3']]['recorded_closing_dc'] for m in balances])
        self.assertEqual(['C'] * 3, [m[self.aid['5']]['recorded_closing_dc'] for m in balances])
        self.assertTrue(all(r['ecd_opening_balance'] is None and r['ecd_closing_balance'] is None
                            for m in balances for r in m.values()))
        self.assertEqual(before, self.database_hash())

    def test_overlapping_queries_and_partial_months_do_not_double_count(self):
        j1 = self.create('first', '2025-01-14', '1.01')
        j2 = self.create('second', '2025-01-15', '2.02')
        j3 = self.create('third', '2025-02-15', '3.03')
        complete = self.snapshot('2025-01-01', '2025-02-28')
        overlap = self.snapshot('2025-01-15', '2025-02-15')
        self.assertEqual([j2['id'], j3['id']], [j['id'] for j in overlap['journals']])
        self.assertEqual([j1['id']], [j['id'] for j in overlap['opening_history']['journals']])
        self.assertEqual(complete['monthly_balances'][-1]['balances'][0]['recorded_closing'],
                         overlap['monthly_balances'][-1]['balances'][0]['recorded_closing'])
        self.assertEqual('505', overlap['reconciliation']['recorded_debits']['cents'])
        self.assertIn('PARTIAL_MONTH_SCOPE', {w['code'] for w in overlap['warnings']})
        self.assertEqual('101', overlap['monthly_balances'][0]['balances'][0]['recorded_opening']['cents'])

    def test_reversal_preserves_both_journals_dates_history_and_signed_rollforward(self):
        original = self.create('original', '2025-01-03', '12.34')
        reversal = self.core.reverse_journal(self.a['id'], original['id'],
            {'date': '2025-02-02', 'reason': 'Estorno sintético explicitamente revisado'}, 'teste')
        s = self.snapshot(end='2025-02-28')
        first, second = s['journals']
        self.assertEqual('reversed', first['status'])
        self.assertEqual(reversal['id'], first['reversed_by'])
        self.assertEqual(original['id'], second['reversal_of'])
        self.assertIn('Estorno', second['history'])
        self.assertEqual('2468', s['reconciliation']['recorded_debits']['cents'])
        self.assertTrue(all(r['recorded_closing']['cents'] == '0' for r in s['monthly_balances'][-1]['balances']))
        self.assertTrue(all(r['recorded_closing_dc'] is None for r in s['monthly_balances'][-1]['balances']))
        self.assertTrue(all(j['ecd_candidates']['IND_LCTO'] is None for j in s['journals']))
        self.assertEqual(first['lines'][0]['debit'], second['lines'][0]['credit'])
        self.assertEqual(original['history'], first['lines'][0]['ecd_candidates']['HIST'])

    def test_reversal_outside_range_is_linked_without_entering_period_totals(self):
        original = self.create('original', '2025-01-03', '12.34')
        reversal = self.core.reverse_journal(self.a['id'], original['id'],
            {'date': '2025-02-02', 'reason': 'Estorno sintético posterior'}, 'teste')
        s = self.snapshot(end='2025-01-31')
        self.assertEqual([original['id']], [j['id'] for j in s['journals']])
        self.assertEqual(reversal['id'], s['journals'][0]['reversed_by'])
        self.assertEqual('1234', s['reconciliation']['recorded_debits']['cents'])

    def test_explicit_opening_is_retained_not_used_as_certified_balance_twice(self):
        opening = self.core.create_opening(self.a['id'], self.journal('opening', '7.89', '2025-01-01'), 'teste')
        s = self.snapshot('2025-01-01', '2025-01-31')
        self.assertEqual([opening['id']], [j['id'] for j in s['journals']])
        self.assertEqual('0', s['monthly_balances'][0]['balances'][0]['recorded_opening']['cents'])
        self.assertEqual('789', s['reconciliation']['recorded_debits']['cents'])
        self.assertIn('OPENING_ENTRY_REQUIRES_ECD_TREATMENT', {w['code'] for w in s['warnings']})
        self.assertTrue(any(e['action'] == 'opening' for e in s['journals'][0]['audit_events']))

    def test_cost_centers_are_distinct_and_unassigned_is_not_a_fabricated_code(self):
        cc = self.core.save_cost_center(self.a['id'], {'code': 'CC-001', 'name': 'Centro sintético'}, 'teste')
        self.create('center', '2025-01-01', lines=[
            {'account_id': self.aid['3'], 'debit': '0.01', 'cost_center_id': cc['id']},
            {'account_id': self.aid['3'], 'debit': '0.02'},
            {'account_id': self.aid['5'], 'credit': '0.03'}])
        s = self.snapshot(end='2025-01-31')
        rows = {(r['account_id'], r['cost_center_id']): r for r in s['monthly_balances'][0]['balances']}
        self.assertEqual('1', rows[self.aid['3'], cc['id']]['recorded_closing']['cents'])
        self.assertEqual('2', rows[self.aid['3'], None]['recorded_closing']['cents'])
        self.assertEqual('CC-001', s['journals'][0]['lines'][0]['ecd_candidates']['COD_CCUS'])
        self.assertIsNone(s['journals'][0]['lines'][1]['ecd_candidates']['COD_CCUS'])
        self.assertIsNone(s['cost_centers'][0]['ecd_DT_ALT'])

    def test_large_integer_amounts_remain_exact_after_http_json(self):
        # Each posting respects the existing domain ceiling; the aggregate exceeds 2**53.
        for index in range(91):
            self.create(f'large-{index}', '2025-01-01', '999999999999.99')
        s = self.snapshot(end='2025-01-31')
        self.assertEqual('99999999999999', s['journals'][0]['lines'][0]['debit']['cents'])
        self.assertEqual('9099999999999909', s['reconciliation']['recorded_debits']['cents'])
        self.assertEqual('90999999999999.09', s['reconciliation']['recorded_debits']['decimal'])

    def test_shared_plan_with_repeated_classifier_and_unused_virtual_accounts_is_not_copied(self):
        global_plan, _, _ = self.publish()
        self.confirm(self.prepare(global_plan['id']))
        accounts = {a['access_code']: a for a in self.core.accounts(self.a['id'])}
        before = self.database_hash()
        s = self.snapshot()
        self.assertEqual(global_plan['id'], s['plan_binding']['global_plan_id'])
        self.assertEqual('shared', s['plan_binding']['mode'])
        actual = {a['access_code']: a for a in s['accounts']}
        self.assertEqual(accounts['00101']['id'], actual['00101']['id'])
        self.assertLess(actual['00101']['id'], 0)
        self.assertNotEqual(actual['00101']['id'], actual['00102']['id'])
        self.assertEqual(actual['00101']['classifier'], actual['00102']['classifier'])
        self.assertEqual('00101', actual['00101']['ecd_candidates']['COD_CTA'])
        self.assertIsNone(actual['00101']['ecd_candidates']['COD_NAT'])
        self.assertEqual(global_plan['sha256'], actual['00101']['definition_plan_sha256'])
        self.assertEqual(before, self.database_hash())

    def test_shared_used_alias_then_own_plan_retains_ids_and_origin_without_switching_chart(self):
        global_plan, _, _ = self.publish()
        self.confirm(self.prepare(global_plan['id']))
        accounts = {a['access_code']: a for a in self.core.accounts(self.a['id'])}
        virtual = accounts['00101']['id']
        entry = self.create('alias', '2025-01-02', lines=[
            {'account_id': virtual, 'debit': '1.23'}, {'account_id': accounts['00102']['id'], 'credit': '1.23'}])
        materialized = entry['lines'][0]['account_id']
        shared = self.snapshot(end='2025-01-31')
        self.assertGreater(materialized, 0)
        self.assertIn(-virtual, next(a for a in shared['accounts'] if a['id'] == materialized)['global_alias_entry_ids'])
        r = self.client.post(self.scope('/global-account-plans/binding/detach'), json={'scope': 'used', 'version': shared['plan_binding']['version'], 'reason': 'Plano próprio sintético'})
        self.assertEqual(200, r.status_code, r.text)
        before = self.database_hash()
        own = self.snapshot(end='2025-01-31')
        self.assertEqual('own', own['plan_binding']['mode'])
        self.assertEqual(materialized, own['journals'][0]['lines'][0]['account_id'])
        self.assertEqual(shared['monthly_balances'], own['monthly_balances'])
        self.assertEqual(before, self.database_hash())

    def test_local_plan_has_no_invented_global_050_binding(self):
        s = self.snapshot()
        self.assertIsNone(s['plan_binding'])
        self.assertEqual([a['id'] for a in self.core.accounts(self.a['id'])], [a['id'] for a in s['accounts']])
        self.assertTrue(all(a['definition_plan_id'] is None for a in s['accounts']))
        self.assertTrue(all(a['ecd_candidates']['DT_ALT'] is None for a in s['accounts']))

    def test_deterministic_repeat_hash_database_and_caller_independence(self):
        self.create('repeat', '2025-01-01', '1.11')
        before = self.database_hash()
        first, second = self.get(), self.get()
        self.assertEqual(200, first.status_code, first.text)
        self.assertEqual(first.content, second.content)
        for journal in first.json()['snapshot']['journals']:
            original = copy.deepcopy(journal)
            expected = original.pop('source_record_sha256')
            self.assertEqual(expected, digest(original))
        direct = accounting_snapshot(self.core, self.a['id'], '2025-01-01', '2025-12-31')
        direct['snapshot']['reference']['pages_reviewed'].clear()
        self.assertTrue(self.snapshot()['reference']['pages_reviewed'])
        self.assertEqual(before, self.database_hash())

    def test_closed_and_reopened_period_allow_identical_read_export(self):
        entry = self.create('close', '2025-01-03', '1.11')
        expected = self.get().content
        for state in ('close', 'reopen'):
            r = self.client.post(self.scope('/periods/' + state), json={
                'module': 'accounting', 'period': '2025-01', 'reason': 'Estado sintético para ensaio ECD'})
            self.assertEqual(200, r.status_code, r.text)
            before = self.database_hash()
            self.assertEqual(expected, self.get().content)
            self.assertEqual(before, self.database_hash())
            if state == 'close':
                with self.assertRaises(DomainError):
                    self.core.reverse_journal(self.a['id'], entry['id'], {'date': '2025-01-04', 'reason': 'Competência fechada'}, 'teste')
                with self.assertRaises(DomainError):
                    self.create('blocked', '2025-01-04')
        reversal = self.core.reverse_journal(self.a['id'], entry['id'], {'date': '2025-01-04', 'reason': 'Competência reaberta'}, 'teste')
        self.assertEqual(2, len(self.snapshot()['journals']))

    def test_bad_dates_other_exercise_and_module_do_not_cross_context(self):
        for start, end in [('2025-02-29', '2025-03-01'), ('2025-02-01', '2025-01-01'),
                           ('2024-12-31', '2025-01-01')]:
            self.assertEqual(400, self.get(start, end).status_code)
        self.assertEqual(409, self.get('2026-01-01', '2026-12-31').status_code)
        self.assertEqual(409, self.get(cid=self.b['id']).status_code)
        r = self.client.post('/api/context', json={'company_id': self.a['id'], 'period': '2025-01', 'module': 'fiscal'})
        self.assertEqual(200, r.status_code, r.text)
        self.assertEqual(409, self.get().status_code)

    def test_other_reference_year_warns_without_blocking_data_export(self):
        self.activate_accounting(period='2026-01')
        s = self.snapshot('2026-01-01', '2026-01-31')
        self.assertIn('REFERENCE_YEAR_NOT_REVIEWED', {x['code'] for x in s['warnings']})
        self.assertEqual(2025, s['reference']['calendar_year_reviewed'])
        self.assertEqual(2026, s['scope']['calendar_year'])

    def test_company_isolation_for_accounts_lines_links_and_history(self):
        own = self.create('own', '2025-01-03', '1.11')
        other_accounts = {a['access_code']: a['id'] for a in self.core.accounts(self.b['id'])}
        other = self.create('other', '2025-01-03', '9.99', cid=self.b['id'], lines=[
            {'account_id': other_accounts['3'], 'debit': '9.99'}, {'account_id': other_accounts['5'], 'credit': '9.99'}])
        s = self.snapshot()
        self.assertEqual([own['id']], [j['id'] for j in s['journals']])
        self.assertNotIn(other['id'], [j['id'] for j in s['opening_history']['journals']])
        self.assertEqual({self.a['id']}, {a['company_id'] for a in s['accounts']})
        self.assertEqual('111', s['reconciliation']['recorded_debits']['cents'])

    def test_header_or_period_inconsistency_is_visible_without_blocking_or_dropping_lines(self):
        entry = self.create('inconsistent', '2025-01-03', '1.11')
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE journals SET total_cents=112,period=? WHERE id=?', ('2025-02', entry['id']))
        before = self.database_hash()
        s = self.snapshot(end='2025-01-31')
        self.assertEqual('112', s['journals'][0]['ecd_candidates']['VL_LCTO']['cents'])
        self.assertEqual('111', s['reconciliation']['recorded_debits']['cents'])
        self.assertFalse(s['reconciliation']['journal_totals_match'])
        self.assertEqual(2, sum(len(r['movement_line_ids']) for r in s['monthly_balances'][0]['balances']))
        self.assertTrue({'JOURNAL_TOTAL_MISMATCH', 'JOURNAL_PERIOD_MISMATCH'} <= {w['code'] for w in s['warnings']})
        self.assertEqual(before, self.database_hash())

    def test_auth_export_permission_account_permission_and_live_revocation(self):
        with TestClient(self.app) as anonymous:
            self.assertEqual(401, self.get(client=anonymous).status_code)
        grants = [{'company_id': self.a['id'], 'routine': routine, 'action': action, 'effect': 'allow'}
                  for routine, action in [('accounting.journals', 'read'), ('accounting.journals', 'export')]]
        r = self.client.post('/api/users', json={'username': 'ecd-leitor', 'password': 'Ecd-ficticio-123!',
            'role': 'custom', 'company_ids': [self.a['id']], 'permissions': grants})
        self.assertEqual(201, r.status_code, r.text)
        uid = r.json()['id']
        with TestClient(self.app) as reader:
            login = reader.post('/api/login', json={'username': 'ecd-leitor', 'password': 'Ecd-ficticio-123!'})
            reader.headers['X-CSRF-Token'] = login.json()['csrf_token']
            self.activate_accounting(client=reader)
            self.assertEqual(403, self.get(client=reader).status_code)
            with self.core.db.transaction() as conn:
                conn.execute("INSERT INTO user_permissions(user_id,company_id,routine,action,effect) VALUES(?,?,'accounting.accounts','read','allow')", (uid, self.a['id']))
            self.assertEqual(200, self.get(client=reader).status_code)
            with self.core.db.transaction() as conn:
                conn.execute("UPDATE user_permissions SET effect='deny' WHERE user_id=? AND action='export'", (uid,))
            self.assertEqual(403, self.get(client=reader).status_code)

    def test_actual_module_import_retains_file_fingerprint_and_row_reference(self):
        raw = ('id;date;document;history;account;debit;credit;cost_center\n'
               'a;2025-01-03;CSV-SINTETICO;Histórico importado;3;1.23;0.00;\n'
               'a;2025-01-03;CSV-SINTETICO;Histórico importado;5;0.00;1.23;\n').encode()
        r = self.client.post(self.scope('/module-imports/preview'), json={'module': 'accounting',
            'layout': 'journals-v1', 'year': 2025, 'filename': 'ecd-sintetico.csv',
            'content_base64': base64.b64encode(raw).decode()})
        self.assertEqual(200, r.status_code, r.text)
        batch = r.json()
        r = self.client.post(self.scope(f"/module-imports/{batch['id']}/confirm"), json={
            'module': 'accounting', 'fingerprint': batch['fingerprint'],
            'selected': [record['_selection'] for record in batch['records']]})
        self.assertEqual(200, r.status_code, r.text)
        before = self.database_hash()
        s = self.snapshot(end='2025-01-31')
        reference = next(x for x in s['journals'][0]['source_references'] if x['entity'] == 'module_imports')
        self.assertEqual(batch['id'], reference['id'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), reference['fingerprint'])
        self.assertEqual(batch['file_id'], reference['file_id'])
        self.assertEqual(r.json()['written'][0]['selection'], reference['selection'])
        self.assertEqual(before, self.database_hash())
        self.assertNotIn(base64.b64encode(raw).decode(), json.dumps(s))

    def test_document_and_settlement_references_do_not_copy_original_payloads(self):
        doc = self.core.create_document(self.a['id'], base.CoreApiTests.document(self) | {
            'issue_date': '2025-01-03', 'posting_date': '2025-01-03'}, 'teste')
        entry = self.create('linked', '2025-01-03', '1.23')
        # A narrowly seeded synthetic FK link exercises the reader without changing booking services.
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE documents SET journal_id=? WHERE company_id=? AND id=?',
                         (entry['id'], self.a['id'], doc['id']))
        title = self.core.create_title(self.a['id'], {'kind': 'payable', 'description': 'Título sintético',
            'partner_name': 'Parceiro sintético', 'document': 'FIN-SINTETICO', 'issue_date': '2025-01-03',
            'due_date': '2025-01-10', 'amount': '1.23'}, 'teste')
        settled = self.core.settle_title(self.a['id'], title['id'], {'date': '2025-01-10', 'amount': '1.23',
            'reason': 'Baixa sintética', 'idempotency_key': 'settlement-synthetic',
            'lines': [
                {'account_id': self.aid['3'], 'debit': '1.23'}, {'account_id': self.aid['5'], 'credit': '1.23'}]}, 'teste')
        before = self.database_hash()
        s = self.snapshot(end='2025-01-31')
        refs = [x for j in s['journals'] for x in j['source_references']]
        self.assertIn({'entity': 'documents', 'id': doc['id'], 'relationship': 'journal_id'}, refs)
        self.assertIn({'entity': 'settlements', 'id': settled['settlement']['id'], 'relationship': 'journal_id'}, refs)
        self.assertNotIn('origem-ficticia.xml', json.dumps(s))
        self.assertNotIn('Parceiro sintético', json.dumps(s))
        self.assertEqual(before, self.database_hash())

    def test_snapshot_reconciles_existing_domain_journal_and_trial_balance_services(self):
        self.create('pre', '2024-12-31', '10.01')
        self.create('movement', '2025-01-10', '20.02')
        s = self.snapshot('2025-01-01', '2025-01-31')
        report = self.core.business_report(self.a['id'], 'trial-balance', '2025-01-01', '2025-01-31')
        balances = {r['account_id']: r for r in s['monthly_balances'][0]['balances']}
        for row in report['rows']:
            if row['account_id'] in balances:
                self.assertEqual(str(row['opening_cents']), balances[row['account_id']]['recorded_opening']['cents'])
                self.assertEqual(str(row['closing_cents']), balances[row['account_id']]['recorded_closing']['cents'])
        domain = self.core.journals(self.a['id'], year=2025)
        self.assertEqual([j['id'] for j in domain], [j['id'] for j in s['journals']])
        self.assertEqual(str(domain[0]['lines'][0]['debit_cents']), s['journals'][0]['lines'][0]['debit']['cents'])

    def test_get_rejects_stale_optional_context_headers(self):
        endpoint = self.scope('/sped-generator/accounting-snapshot')
        for header, value in [('X-Company-Id', str(self.b['id'])), ('X-Year', '2026'), ('X-Module', 'fiscal')]:
            r = self.client.get(endpoint, params={'start': '2025-01-01', 'end': '2025-01-31'}, headers={header: value})
            self.assertEqual(409, r.status_code, r.text)

    def test_two_companies_keep_their_explicitly_selected_synthetic_050_or_other_plan(self):
        def publish_named(name, account_name):
            plan = plans.synthetic_plan()
            plan['accounts'][1]['name'] = account_name
            raw = json.dumps(plan).encode()
            batch = self.post('/account-plans/preview', {'format': 'native', 'filename': 'plano-ficticio.json',
                'content_base64': base64.b64encode(raw).decode()})
            return self.post(f"/global-account-plans/batches/{batch['id']}/publish", {
                'name': name, 'reason': 'Plano inteiramente sintético', 'preview_hash': batch['preview_hash'],
                'properties_reviewed': True, 'global_visibility_reviewed': True})
        first = publish_named('050 inteiramente sintético', 'Conta fictícia do primeiro plano')
        second = publish_named('Outro plano inteiramente sintético', 'Conta fictícia do segundo plano')
        self.confirm(self.prepare(first['id']))
        self.activate_accounting(self.b['id'])
        self.confirm(self.prepare(second['id']))
        before = self.database_hash()
        own_b = self.snapshot(cid=self.b['id'])
        self.assertEqual(before, self.database_hash())
        self.activate_accounting()
        # Context changes are deliberate writes; compare snapshot reads independently.
        before_a = self.database_hash()
        own_a = self.snapshot()
        self.assertEqual(first['id'], own_a['plan_binding']['global_plan_id'])
        self.assertEqual(second['id'], own_b['plan_binding']['global_plan_id'])
        self.assertEqual(first['name'], own_a['plan_binding']['name'])
        self.assertEqual(second['name'], own_b['plan_binding']['name'])
        self.assertEqual('Conta fictícia do primeiro plano', next(a['name'] for a in own_a['accounts'] if a['access_code'] == '00101'))
        self.assertEqual('Conta fictícia do segundo plano', next(a['name'] for a in own_b['accounts'] if a['access_code'] == '00101'))
        self.assertEqual(before_a, self.database_hash())
