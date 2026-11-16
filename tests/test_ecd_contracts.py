"""Explicit synthetic declarations; never fiscal inference or opening attestation."""
import copy
import json
import unittest
import test_ecd_snapshot as existing
import test_global_account_plans as plans
from app.core import digest
from app.sped_generator.ecd_contracts import account_review, opening_review, NAMESPACE


def account(aid, code, analytical=False, **extra):
    return {'id': aid, 'access_code': code, 'analytical': analytical, 'nature': 'credit',
            'classifier': '1.1.01.001', 'report_group': 'asset'} | extra


def declaration(level=1, parent='', nature='01', changed='2024-01-01'):
    return {'DT_ALT': changed, 'COD_NAT': nature, 'NIVEL': level, 'COD_CTA_SUP': parent}


def metadata(values):
    return {aid: {'present': True, 'value': value, 'metadata_sha256': digest(value),
                  'source': {'batch_id': 17, 'global_plan_id': None}} for aid, value in values.items()}


def inspect(accounts, values, end='2025-12-31'):
    return account_review(accounts, metadata(values), end)


def by_id(review):
    return {row['account_id']: row for row in review['accounts']}


def codes(row):
    return {d['code'] for d in row['diagnostics']}


class AccountContractTests(unittest.TestCase):
    def test_missing_declarations_never_infer_nature_levels_or_parent_from_domain_fields(self):
        row = by_id(inspect([account(1, '00100', True)], {}))[1]
        self.assertEqual({}, row['declared_fields'])
        self.assertEqual(['COD_CTA_SUP', 'COD_NAT', 'DT_ALT', 'NIVEL'], row['missing_fields'])
        self.assertEqual('missing', row['status'])
        self.assertIsNone(row['resolved_parent_account_id'])

    def test_consistent_explicit_leading_zero_codes_do_not_collapse_repeated_classifiers(self):
        result = inspect([account(-10, '00100'), account(-11, '00101', True), account(-12, '00102', True)],
                         {-10: declaration(), -11: declaration(2, '00100'), -12: declaration(2, '00100')})
        self.assertEqual({'consistent_for_preparation': 3}, result['summary'])
        self.assertEqual(-10, by_id(result)[-11]['resolved_parent_account_id'])
        self.assertEqual(-10, by_id(result)[-12]['resolved_parent_account_id'])
        self.assertFalse(result['classification_applied'])
        self.assertFalse(result['book_dependent_rules_evaluated'])

    def test_cycles_and_self_parent_are_reported_without_recursion_or_repair(self):
        rows = [account(1, 'A'), account(2, 'B'), account(3, 'C'), account(4, 'SELF')]
        values = {1: declaration(2, 'B'), 2: declaration(3, 'C'), 3: declaration(4, 'A'), 4: declaration(1, 'SELF')}
        result = inspect(rows, values)
        self.assertEqual([[1, 2, 3], [4]], result['cycles'])
        self.assertTrue(all('CYCLIC_PARENT_RELATION' in codes(row) for row in result['accounts']))
        self.assertIn('ROOT_HAS_PARENT', codes(by_id(result)[4]))
        self.assertEqual('B', by_id(result)[1]['declared_fields']['COD_CTA_SUP'])

    def test_parent_must_exist_once_in_company_plan_and_be_synthetic(self):
        rows = [account(1, 'A', True), account(2, 'B'), account(3, 'C'), account(4, 'D'), account(5, 'D')]
        result = by_id(inspect(rows, {1: declaration(), 2: declaration(2, 'A'),
                                     3: declaration(2, 'FORA'), 4: declaration(2, 'D')}))
        self.assertIn('PARENT_IS_ANALYTICAL', codes(result[2]))
        self.assertIn('PARENT_NOT_UNIQUE_IN_COMPANY_PLAN', codes(result[3]))
        self.assertIn('DUPLICATE_ACCOUNT_CODE', codes(result[4]))
        self.assertIn('PARENT_NOT_UNIQUE_IN_COMPANY_PLAN', codes(result[4]))

    def test_child_level_greater_rule_and_declared_nature_condition_above_two(self):
        rows = [account(1, 'A'), account(2, 'B'), account(3, 'C'), account(4, 'D')]
        result = by_id(inspect(rows, {1: declaration(), 2: declaration(2, 'A', '02'),
                                     3: declaration(3, 'B', '01'), 4: declaration(2, 'B', '02')}))
        self.assertNotIn('NATURE_DIFFERS_FROM_PARENT_ABOVE_LEVEL_TWO', codes(result[2]))
        self.assertIn('NATURE_DIFFERS_FROM_PARENT_ABOVE_LEVEL_TWO', codes(result[3]))
        self.assertIn('CHILD_LEVEL_NOT_GREATER_THAN_PARENT', codes(result[4]))

    def test_missing_parent_nature_is_not_reported_as_consistent(self):
        row = by_id(inspect([account(1, 'A'), account(2, 'B')],
                            {1: declaration(nature=None), 2: declaration(3, 'A')}))[2]
        self.assertIn('PARENT_NATURE_NOT_REVIEWABLE', codes(row))
        self.assertEqual('declared_needs_review', row['status'])

    def test_unknown_and_absent_natures_are_not_coerced_or_guessed(self):
        for nature in (None, '', '99', 1, True, {}, []):
            with self.subTest(nature=nature):
                result = by_id(inspect([account(1, 'A'), account(2, 'B')],
                                      {1: declaration(), 2: declaration(3, 'A', nature)}))[2]
                self.assertEqual(nature, result['declared_fields']['COD_NAT'])
                if nature in (None, ''):
                    self.assertIn('COD_NAT', result['missing_fields'])
                else:
                    self.assertIn('UNKNOWN_NATURE_CODE', codes(result))
        for nature in ('01', '02', '03', '04', '05', '09'):
            self.assertEqual('consistent_for_preparation', by_id(inspect([account(1, 'A')], {1: declaration(nature=nature)}))[1]['status'])

    def test_invalid_level_types_and_parent_codes_do_not_raise_or_become_zero(self):
        for level in (0, -1, True, '2', 2.0, {}, []):
            with self.subTest(level=level):
                row = by_id(inspect([account(1, 'A')], {1: declaration(level)}))[1]
                self.assertIn('INVALID_LEVEL', codes(row))
                self.assertEqual(level, row['declared_fields']['NIVEL'])
        for parent in (1, True, {}, [], ' A '):
            row = by_id(inspect([account(1, 'A')], {1: declaration(2, parent)}))[1]
            self.assertIn('INVALID_PARENT_CODE', codes(row))
            self.assertIsNone(row['resolved_parent_account_id'])

    def test_dates_are_explicit_and_january_warning_compares_year_only(self):
        row = by_id(inspect([account(1, 'A')], {1: declaration(changed='2025-12-31')}, '2025-01-31'))[1]
        self.assertNotIn('ALTERATION_YEAR_AFTER_SCOPE', codes(row))
        row = by_id(inspect([account(1, 'A')], {1: declaration(changed='2026-01-01')}))[1]
        self.assertIn('ALTERATION_YEAR_AFTER_SCOPE', codes(row))
        self.assertEqual('declared_needs_review', row['status'])
        for day in ('2025-02-29', '01012025', ' 2025-01-01', None, {}):
            row = by_id(inspect([account(1, 'A')], {1: declaration(changed=day)}))[1]
            if day is None:
                self.assertIn('DT_ALT', row['missing_fields'])
            else:
                self.assertIn('INVALID_ALTERATION_DATE', codes(row))

    def test_malformed_namespace_and_unsupported_attestation_claims_are_not_applied(self):
        for value in (None, True, [], 'texto'):
            row = by_id(inspect([account(1, 'A')], {1: value}))[1]
            self.assertIn('DECLARATION_NOT_OBJECT', codes(row))
        value = declaration() | {'opening_attested': True, 'opening_balance': '123.45'}
        result = inspect([account(1, 'A')], {1: value})
        row = by_id(result)[1]
        self.assertIn('UNSUPPORTED_DECLARATION_FIELDS', codes(row))
        self.assertNotIn('opening_balance', row['declared_fields'])
        self.assertFalse(result['classification_applied'])

    def test_deep_graph_is_iterative_and_repeatable_without_mutating_inputs(self):
        rows = [account(i, f'{i:05d}') for i in range(1, 2501)]
        values = {i: declaration(i, f'{i-1:05d}' if i > 1 else '') for i in range(1, 2501)}
        before = copy.deepcopy((rows, values))
        first = inspect(rows, values)
        self.assertEqual([], first['cycles'])
        self.assertEqual(first, inspect(list(reversed(rows)), dict(reversed(list(values.items())))))
        self.assertEqual(before, (rows, values))

    def test_opening_postings_reversed_or_balanced_do_not_attest_observed_balances(self):
        def journal(jid, day, reversed_by=None):
            return {'id': jid, 'date': day, 'reversed_by': reversed_by,
                    'audit_events': [{'action': 'opening'}], 'source_record_sha256': f'hash-ficticio-{jid}'}
        snapshot = {'scope': {'start': '2025-01-01', 'company_id': 7},
                    'opening_history': {'journals': [journal(1, '2024-01-01', 2)],
                                        'recorded_balances': [{'account_id': 3, 'recorded_balance': {'cents': '0', 'decimal': '0.00'}}]},
                    'journals': [journal(3, '2025-01-01')], 'opening_balances_attested': True}
        before = copy.deepcopy(snapshot)
        review = opening_review(snapshot)
        self.assertFalse(review['observed_is_attested'])
        self.assertIsNone(review['attested_opening_balances'])
        self.assertEqual(2, review['explicit_opening_postings'][0]['reversed_by'])
        self.assertEqual(['2024-01-01', '2025-01-01'], review['opening_dates'])
        self.assertIn('MULTIPLE_OPENING_DATES', {d['code'] for d in review['diagnostics']})
        self.assertEqual(before, snapshot)


class ContractSnapshotApiTests(unittest.TestCase):
    setUp = existing.EcdSnapshotTests.setUp
    setUpBase = existing.EcdSnapshotTests.setUpBase
    tearDown = existing.EcdSnapshotTests.tearDown
    activate_accounting = existing.EcdSnapshotTests.activate_accounting
    activate = existing.EcdSnapshotTests.activate
    create_company = existing.EcdSnapshotTests.create_company
    scope = existing.EcdSnapshotTests.scope
    database_hash = existing.EcdSnapshotTests.database_hash
    snapshot = existing.EcdSnapshotTests.snapshot
    get = existing.EcdSnapshotTests.get
    journal = existing.EcdSnapshotTests.journal
    create = existing.EcdSnapshotTests.create
    post = existing.EcdSnapshotTests.post
    publish = existing.EcdSnapshotTests.publish
    prepare = existing.EcdSnapshotTests.prepare
    confirm = existing.EcdSnapshotTests.confirm

    def declared_plan(self, nature='01'):
        plan = plans.synthetic_plan()
        plan['accounts'][0][NAMESPACE] = declaration(nature=nature)
        plan['accounts'][1][NAMESPACE] = declaration(2, '00100', nature)
        plan['accounts'][2][NAMESPACE] = declaration(2, '00100', nature)
        plan['accounts'][0]['unrelated_note'] = 'Nota sintética fora do contrato ECD'
        return plan

    def adopt(self, plan):
        published, _, _ = self.publish(plan)
        self.confirm(self.prepare(published['id']))
        return published

    def test_real_shared_metadata_is_reviewed_without_materialization_or_applying_candidates(self):
        published = self.adopt(self.declared_plan())
        before = self.database_hash()
        snapshot = self.snapshot()
        review = snapshot['preparation_review']['account_contracts']
        child = next(r for r in review['accounts'] if r['access_code'] == '00101')
        self.assertEqual('consistent_for_preparation', child['status'])
        self.assertLess(child['account_id'], 0)
        self.assertEqual(published['id'], child['source']['global_plan_id'])
        self.assertEqual('shared_entry_metadata', child['source']['kind'])
        self.assertEqual(digest(declaration(2, '00100')), child['declaration_sha256'])
        original = next(a for a in snapshot['accounts'] if a['id'] == child['account_id'])
        self.assertIsNone(original['ecd_candidates']['COD_NAT'])
        self.assertIsNone(original['ecd_candidates']['NIVEL'])
        self.assertNotIn('Nota sintética fora do contrato ECD', json.dumps(snapshot))
        self.assertEqual(before, self.database_hash())

    def test_two_company_plans_keep_explicit_natures_and_do_not_resolve_cross_company_parent(self):
        first = self.adopt(self.declared_plan('01'))
        a = self.snapshot()
        self.activate_accounting(self.b['id'])
        second = self.adopt(self.declared_plan('02'))
        before = self.database_hash()
        b = self.snapshot(cid=self.b['id'])
        for snapshot, expected, plan_id in [(a, '01', first['id']), (b, '02', second['id'])]:
            row = next(r for r in snapshot['preparation_review']['account_contracts']['accounts'] if r['access_code'] == '00101')
            self.assertEqual(expected, row['declared_fields']['COD_NAT'])
            self.assertEqual(plan_id, row['source']['global_plan_id'])
        self.assertEqual(before, self.database_hash())
        self.assertNotEqual(a['preparation_review'], b['preparation_review'])

    def test_inconsistent_or_cyclic_metadata_still_exports_in_closed_period(self):
        plan = self.declared_plan()
        plan['accounts'][0][NAMESPACE] = declaration(1, '00101')
        self.adopt(plan)
        r = self.client.post(self.scope('/periods/close'), json={'module': 'accounting', 'period': '2025-01', 'reason': 'Teste sintético fechado'})
        self.assertEqual(200, r.status_code, r.text)
        before = self.database_hash()
        result = self.get()
        self.assertEqual(200, result.status_code, result.text)
        snapshot = result.json()['snapshot']
        self.assertTrue(snapshot['preparation_review']['account_contracts']['cycles'])
        self.assertFalse(snapshot['warnings_block_export'])
        self.assertFalse(snapshot['preparation_review']['warnings_block_export'])
        self.assertEqual(result.content, self.get().content)
        self.assertEqual(before, self.database_hash())

    def test_local_metadata_after_own_fork_has_precedence_and_no_shared_definition_is_changed(self):
        published = self.adopt(self.declared_plan())
        shared = self.snapshot()
        r = self.client.post(self.scope('/global-account-plans/binding/detach'), json={
            'copy_scope': 'all', 'version': shared['plan_binding']['version'], 'reason': 'Plano próprio sintético'})
        self.assertEqual(200, r.status_code, r.text)
        with self.core.db.transaction() as conn:
            row = conn.execute("SELECT id FROM accounts WHERE company_id=? AND access_code='00101'", (self.a['id'],)).fetchone()
            saved = conn.execute('SELECT extras_json FROM account_plan_metadata WHERE company_id=? AND account_id=?', (self.a['id'], row['id'])).fetchone()
            value = json.loads(saved['extras_json']);value[NAMESPACE]['COD_NAT'] = '03'
            conn.execute('UPDATE account_plan_metadata SET extras_json=? WHERE company_id=? AND account_id=?', (json.dumps(value), self.a['id'], row['id']))
        before = self.database_hash()
        own = self.snapshot()
        child = next(r for r in own['preparation_review']['account_contracts']['accounts'] if r['access_code'] == '00101')
        self.assertEqual('03', child['declared_fields']['COD_NAT'])
        self.assertIsNotNone(child['source']['batch_id'])
        self.assertEqual('local_account_metadata', child['source']['kind'])
        self.assertEqual('own', own['plan_binding']['mode'])
        self.assertEqual(before, self.database_hash())

    def test_malformed_persisted_extras_and_namespace_are_visible_without_copying_unrelated_values(self):
        self.adopt(self.declared_plan())
        for raw in ('{inválido', '[]', '{"ecd_preparation_v1":{"NIVEL":NaN}}', '{"ecd_preparation_v1":{"COD_NAT":"\\ud800"}}'):
            with self.subTest(raw=raw):
                with self.core.db.transaction() as conn:
                    conn.execute("UPDATE global_account_entries SET extras_json=? WHERE access_code='00101'", (raw,))
                before = self.database_hash()
                snapshot = self.snapshot()
                row = next(r for r in snapshot['preparation_review']['account_contracts']['accounts'] if r['access_code'] == '00101')
                self.assertIn('ACCOUNT_METADATA_NOT_OBJECT', codes(row))
                self.assertEqual(before, self.database_hash())

    def test_actual_opening_history_and_current_opening_are_evidence_only_for_partial_scope(self):
        self.core.create_opening(self.a['id'], self.journal('old-open', '1.23', '2024-01-01'), 'teste')
        current = self.core.create_opening(self.a['id'], self.journal('new-open', '4.56', '2025-02-01'), 'teste')
        before = self.database_hash()
        snapshot = self.snapshot('2025-02-01', '2025-02-28')
        review = snapshot['preparation_review']['opening_contract']
        self.assertEqual('2025-02-01', review['cutoff'])
        self.assertEqual(self.a['id'], review['company_id'])
        self.assertEqual('123', review['observed_balances'][0]['recorded_balance']['cents'])
        self.assertFalse(review['observed_is_attested'])
        self.assertIsNone(review['attested_opening_balances'])
        self.assertIn(current['id'], [r['journal_id'] for r in review['explicit_opening_postings']])
        self.assertEqual(before, self.database_hash())

    def test_parent_cannot_be_resolved_from_another_company_or_unbound_global_plan(self):
        own_plan = self.declared_plan()
        own_plan['accounts'][1][NAMESPACE]['COD_CTA_SUP'] = '99000'
        self.adopt(own_plan)
        self.activate_accounting(self.b['id'])
        other_plan = self.declared_plan()
        other_plan['accounts'][0]['access_code'] = '99000'
        self.adopt(other_plan)
        self.activate_accounting()
        before = self.database_hash()
        snapshot = self.snapshot()
        row = next(r for r in snapshot['preparation_review']['account_contracts']['accounts'] if r['access_code'] == '00101')
        self.assertIn('PARENT_NOT_UNIQUE_IN_COMPANY_PLAN', codes(row))
        self.assertIsNone(row['resolved_parent_account_id'])
        self.assertEqual(before, self.database_hash())
