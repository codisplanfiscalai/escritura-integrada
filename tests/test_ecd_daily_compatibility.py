"""PR46 composed with PR39/42; only synthetic bookings and disposable SQLite."""
import unittest
import test_fiscal_sales_accounting as sales
import test_sped_generator as existing


class EcdDailyCompatibilityTests(unittest.TestCase):
    setUp = sales.FiscalSalesAccountingTests.setUp
    tearDown = sales.FiscalSalesAccountingTests.tearDown
    scope = sales.FiscalSalesAccountingTests.scope
    activate = sales.FiscalSalesAccountingTests.activate
    create_company = sales.FiscalSalesAccountingTests.create_company
    document = sales.FiscalSalesAccountingTests.document
    journal = sales.FiscalSalesAccountingTests.journal
    post = sales.FiscalSalesAccountingTests.post
    model = sales.FiscalSalesAccountingTests.model
    sale = sales.FiscalSalesAccountingTests.sale
    mode = sales.FiscalSalesAccountingTests.mode
    payload = sales.FiscalSalesAccountingTests.payload
    generate = sales.FiscalSalesAccountingTests.generate
    reverse = sales.FiscalSalesAccountingTests.reverse
    database_hash = existing.SpedGeneratorApiTests.database_hash

    def accounting_context(self, cid=None):
        r = self.client.post('/api/context', json={'company_id': cid or self.a['id'],
            'module': 'accounting', 'period': '2026-11'})
        self.assertEqual(200, r.status_code, r.text)

    def export(self, cid=None, start='2026-11-01', end='2026-11-30'):
        self.accounting_context(cid)
        before = self.database_hash()
        r = self.client.get(self.scope('/sped-generator/accounting-snapshot', cid), params={'start': start, 'end': end})
        self.assertEqual(200, r.status_code, r.text)
        self.assertEqual(before, self.database_hash())
        return r

    def test_daily_real_posting_and_all_current_document_links_are_read_once(self):
        self.mode('daily'); model = self.model()
        docs = [self.sale('ECD-D1', '0.01'), self.sale('ECD-D2', '10.02'), self.sale('ECD-D3', '20.03')]
        result = self.generate(docs, model)
        snapshot = self.export().json()['snapshot']
        self.assertEqual(1, len(snapshot['journals']))
        journal = snapshot['journals'][0]
        self.assertEqual(result['journals'][0]['id'], journal['id'])
        self.assertEqual(2, len(journal['lines']))
        self.assertEqual('3006', journal['ecd_candidates']['VL_LCTO']['cents'])
        self.assertEqual('3006', snapshot['reconciliation']['recorded_debits']['cents'])
        self.assertEqual({d['id'] for d in docs}, {r['id'] for r in journal['source_references'] if r['entity'] == 'documents'})
        self.assertTrue(snapshot['reconciliation']['journal_totals_match'])
        self.assertIsNone(snapshot['coverage']['referential_plan'])
        self.assertFalse(snapshot['complete_ecd'])

    def test_individual_and_daily_modes_do_not_change_readonly_report_or_double_totals(self):
        model = self.model()
        docs = [self.sale('ECD-I1', '0.01'), self.sale('ECD-I2', '10.02')]
        result = self.generate(docs, model)
        snapshot = self.export().json()['snapshot']
        self.assertEqual(2, len(snapshot['journals']))
        self.assertEqual({j['id'] for j in result['journals']}, {j['id'] for j in snapshot['journals']})
        self.assertEqual('1003', snapshot['reconciliation']['recorded_debits']['cents'])
        before = self.database_hash()
        self.core.business_report(self.a['id'], 'consolidated-diary', '2026-11-01', '2026-11-30')
        self.assertEqual(before, self.database_hash())
        self.assertEqual(2, len(self.core.journals(self.a['id'], year=2026)))

    def test_partial_source_reversal_preserves_aggregate_and_compensation_without_global_reversal(self):
        self.mode('daily'); model = self.model()
        docs = [self.sale('ECD-R1', '0.01'), self.sale('ECD-R2', '10.02'), self.sale('ECD-R3', '20.03')]
        result = self.generate(docs, model)
        compensation = self.reverse(docs[1])['journal']
        source_id = result['journals'][0]['id']
        snapshot = self.export().json()['snapshot']
        by_id = {j['id']: j for j in snapshot['journals']}
        self.assertEqual({source_id, compensation['id']}, set(by_id))
        self.assertEqual('3006', by_id[source_id]['ecd_candidates']['VL_LCTO']['cents'])
        self.assertEqual('1002', by_id[compensation['id']]['ecd_candidates']['VL_LCTO']['cents'])
        self.assertIsNone(by_id[source_id]['reversed_by'])
        self.assertEqual('posted', by_id[source_id]['status'])
        # PR39 records partial source reversal in its dedicated audit, not reversal_of.
        self.assertIsNone(by_id[compensation['id']]['reversal_of'])
        self.assertEqual('4008', snapshot['reconciliation']['recorded_debits']['cents'])
        balances = {r['account_id']: r for r in snapshot['monthly_balances'][0]['balances']}
        self.assertEqual('2004', balances[self.aid['3']]['recorded_closing']['cents'])
        self.assertEqual('-2004', balances[self.aid['5']]['recorded_closing']['cents'])
        self.assertEqual({docs[0]['id'], docs[2]['id']}, {r['id'] for r in by_id[source_id]['source_references'] if r['entity'] == 'documents'})
        before = self.database_hash()
        trace = self.core.trace_sales_accounting_journal(self.a['id'], source_id)
        self.assertEqual({d['id'] for d in docs}, {r['document_id'] for r in trace['sources']})
        self.assertEqual(compensation['id'], trace['reversals'][0]['journal_id'])
        self.assertEqual(before, self.database_hash())
        self.assertEqual('current_links_and_journal_audit_and_accounting_import_refs_only', snapshot['coverage']['source_links'])

    def test_replay_and_closed_period_preserve_snapshot_bytes(self):
        self.mode('daily'); model = self.model()
        docs = [self.sale('ECD-C1', '10.02'), self.sale('ECD-C2', '20.03')]
        self.generate(docs, model, key='ecd-repeat')
        first = self.export().content
        self.activate(self.a['id'])
        self.generate(docs, model, key='ecd-repeat')
        self.assertEqual(first, self.export().content)
        r = self.client.post(self.scope('/periods/close'), json={'module': 'accounting',
            'period': '2026-11', 'reason': 'Fechamento sintético de compatibilidade'})
        self.assertEqual(200, r.status_code, r.text)
        self.assertEqual(first, self.export().content)
        r = self.client.post(self.scope('/periods/reopen'), json={'module': 'accounting',
            'period': '2026-11', 'reason': 'Reabertura sintética de compatibilidade'})
        self.assertEqual(200, r.status_code, r.text)
        self.assertEqual(first, self.export().content)

    def test_company_and_month_scope_preserve_opening_history_separately(self):
        self.mode('daily'); model = self.model()
        a = self.sale('ECD-A', '10.02'); self.generate([a], model)
        self.core.create_journal(self.a['id'], self.journal(key='ecd-october', day='2026-10-06', amount='1.23'), 'teste')
        self.activate(self.b['id'])
        bm = self.model('B', cid=self.b['id']); b = self.sale('ECD-B', '99.99', cid=self.b['id'])
        self.post(sales.ROOT + '/generate', self.payload([b], bm, 'ecd-company-b', version=0), cid=self.b['id'])
        self.accounting_context(self.a['id'])
        snapshot = self.export().json()['snapshot']
        self.assertEqual(1, len(snapshot['journals']))
        self.assertEqual('1002', snapshot['reconciliation']['recorded_debits']['cents'])
        self.assertEqual(1, len(snapshot['opening_history']['journals']))
        self.assertEqual('123', snapshot['opening_history']['recorded_balances'][0]['recorded_balance']['cents'])
        self.assertNotIn(b['id'], [r['id'] for j in snapshot['journals'] for r in j['source_references'] if r['entity'] == 'documents'])
