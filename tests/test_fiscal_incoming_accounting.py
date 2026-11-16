"""Incoming/outgoing integration uses only synthetic disposable companies and charts."""
import unittest
from concurrent.futures import ThreadPoolExecutor
import test_fiscal_sales_accounting as sales

ROOT = '/fiscal-purchases-accounting'


class FiscalIncomingAccountingTests(unittest.TestCase):
    for _name in ('setUp', 'tearDown', 'scope', 'activate', 'create_company', 'document', 'journal',
                  'post', 'mode', 'sale', 'payload', 'snapshot', 'reverse', 'operator'):
        locals()[_name] = getattr(sales.FiscalSalesAccountingTests, _name)
    del _name

    def model(self, code='BUY', debit='3', credit='5', cid=None, direction='incoming'):
        accounts = {a['access_code']: a['id'] for a in self.core.accounts(cid or self.a['id'])}
        return self.post('/masters/accounting_model', {'code': code, 'name': 'Modelo sintético explícito', 'data': {
            'debit_account_id': accounts[debit], 'credit_account_id': accounts[credit],
            'valid_from': '2026-01-01', 'status': 'validated', 'direction': direction,
            'history': 'Fixture sintética', 'source': 'Configuração sintética', 'responsible': 'Teste'}}, 201, cid)['id']

    def purchase(self, number='E1', amount='100.00', cid=None, **extra):
        return self.sale(number, amount, cfop='1102', cid=cid, direction='incoming', **extra)

    def test_preview_incoming_read_only_and_actual_individual_when_sales_daily(self):
        self.mode(); model = self.model(); docs = [self.purchase('E01', '0.01'), self.purchase('E02', '10.02')]
        payload = self.payload(docs, model)
        before = self.snapshot()
        for _ in range(2):
            preview = self.post(ROOT + '/preview', payload)
            self.assertTrue(preview['preview']); self.assertEqual('individual', preview['mode'])
            self.assertEqual((2, 2), (preview['created_count'], preview['accounted_count']))
            self.assertEqual([1, 1002], [j['total_cents'] for j in preview['journals']])
            self.assertTrue(all(l['account_code'] and l['account_name'] for j in preview['journals'] for l in j['lines']))
            self.assertEqual(before, self.snapshot())
        actual = self.post(ROOT + '/generate', payload)
        self.assertEqual((2, 2), (actual['created_count'], actual['accounted_count']))
        self.assertEqual('individual', actual['mode'])
        self.assertEqual('daily', self.client.get(self.scope(sales.ROOT + '/settings')).json()['mode'])
        for old, source, journal in zip(docs, actual['sources'], actual['journals']):
            self.assertEqual(old | {'journal_id': journal['id']}, next(d for d in self.core.documents(self.a['id']) if d['id'] == old['id']))
            self.assertEqual('incoming', source['direction'])
            self.assertEqual(journal['total_cents'], sum(l['debit_cents'] for l in journal['lines']))
            self.assertEqual(journal['total_cents'], sum(l['credit_cents'] for l in journal['lines']))
            trace = self.client.get(self.scope(sales.ROOT + f"/journals/{journal['id']}/sources")).json()
            self.assertEqual([old['id']], [s['document_id'] for s in trace['sources']])
        self.assertEqual([], self.core.titles(self.a['id']))

    def test_outgoing_preview_keeps_daily_and_dimensions(self):
        self.mode(); model = self.model(direction='outgoing'); other = self.model('OTHER', credit='4', direction='outgoing')
        docs = [self.sale('S1', '0.01'), self.sale('S2', '10.02'), self.sale('S3', day='2026-11-07'), self.sale('S4', cfop='6102'), self.sale('S5')]
        payload = self.payload(docs, model); payload['entries'][-1]['model_id'] = other
        before = self.snapshot(); planned = self.post(sales.ROOT + '/preview', payload)
        self.assertEqual(before, self.snapshot()); self.assertEqual(4, planned['created_count'])
        actual = self.post(sales.ROOT + '/generate', payload)
        self.assertEqual([j['total_cents'] for j in planned['journals']], [j['total_cents'] for j in actual['journals']])
        self.assertEqual(5, actual['accounted_count']); self.assertEqual(1003, actual['journals'][0]['total_cents'])

    def test_retry_scope_change_mode_and_fresh_key_do_not_duplicate(self):
        model = self.model(); docs = [self.purchase('R1'), self.purchase('R2')]; payload = self.payload(docs, model, 'shared-key')
        first = self.post(ROOT + '/generate', payload); before = self.snapshot()
        replay = self.post(ROOT + '/generate', payload); self.assertTrue(replay['duplicate']); self.assertEqual(before, self.snapshot())
        self.mode(); replay = self.post(ROOT + '/generate', payload); self.assertTrue(replay['duplicate'])
        changed = self.payload(docs, model, 'fresh-key'); second = self.post(ROOT + '/generate', changed)
        self.assertEqual((0, 2), (second['created_count'], len(second['skipped'])))
        self.assertEqual(2, len(self.core.journals(self.a['id'])))
        sales_model = self.model('SALE', direction='outgoing'); out = self.sale('SAME-KEY')
        sale_result = self.post(sales.ROOT + '/generate', self.payload([out], sales_model, 'shared-key'))
        self.assertEqual(1, sale_result['created_count']); self.assertNotEqual(first['journals'][0]['id'], sale_result['journals'][0]['id'])

    def test_invalid_direction_models_duplicates_and_mixed_batch_are_atomic(self):
        model = self.model(); wrong = self.model('SALE', direction='outgoing'); a = self.purchase(); b = self.sale('OUT')
        for path, docs, chosen in [(ROOT, [a, b], model), (sales.ROOT, [a], model), (ROOT, [a], wrong), (ROOT, [a, a], model)]:
            before = self.snapshot(); self.post(path + '/generate', self.payload(docs, chosen), 400); self.assertEqual(before, self.snapshot())
        payload = self.payload([a], model); del payload['entries'][0]['model_id']
        self.post(ROOT + '/generate', payload, 400)
        self.assertEqual([], self.core.journals(self.a['id']))

    def test_closed_reopened_and_changed_document_revalidated_after_preview(self):
        model = self.model(); doc = self.purchase(); payload = self.payload([doc], model)
        self.post(ROOT + '/preview', payload)
        for module in ('fiscal', 'accounting'):
            self.post('/periods/close', {'module': module, 'period': '2026-11', 'reason': 'Fixture'})
            before = self.snapshot()
            for suffix in ('preview', 'generate'): self.post(ROOT + '/' + suffix, payload, 409)
            self.assertEqual(before, self.snapshot())
            self.post('/periods/reopen', {'module': module, 'period': '2026-11', 'reason': 'Fixture'})
        self.post(ROOT + '/generate', payload)
        self.assertEqual(1, len(self.core.journals(self.a['id'])))

    def test_reversal_through_document_replay_and_reprocessing(self):
        model = self.model(); doc = self.purchase(); original = self.post(ROOT + '/generate', self.payload([doc], model))['journals'][0]
        doc = next(d for d in self.core.documents(self.a['id']) if d['id'] == doc['id'])
        reversed_result = self.reverse(doc)
        before = self.snapshot(); self.assertTrue(self.reverse(doc)['duplicate']); self.assertEqual(before, self.snapshot())
        trace = self.client.get(self.scope(sales.ROOT + f"/journals/{original['id']}/sources")).json()
        self.assertEqual(original['id'], trace['reversals'][0]['source_journal_id'])
        self.assertEqual(10000, reversed_result['journal']['total_cents'])
        self.assertEqual(original, self.client.get(self.scope(f"/journals/{original['id']}")).json())
        with self.core.db.read() as conn:
            self.assertEqual([], conn.execute('PRAGMA foreign_key_check').fetchall())
        self.assertEqual(2, len(self.core.journals(self.a['id'])))

    def test_companies_year_and_permissions_apply_to_preview_and_execute(self):
        model = self.model(); doc = self.purchase(); payload = self.payload([doc], model)
        for suffix in ('preview', 'generate'):
            self.post(ROOT + '/' + suffix, payload, 409, cid=self.b['id'])
        client, uid = self.operator({'fiscal.documents': ['read'], 'accounting.histories': ['read'], 'accounting.journals': ['read']})
        try:
            before = self.snapshot(); self.assertEqual(200, client.post(self.scope(ROOT + '/preview'), json=payload).status_code)
            self.assertEqual(403, client.post(self.scope(ROOT + '/generate'), json=payload).status_code); self.assertEqual(before, self.snapshot())
            with self.core.db.transaction() as conn:
                conn.execute("UPDATE user_permissions SET effect='deny' WHERE user_id=? AND routine='accounting.histories'", (uid,))
            self.assertEqual(403, client.post(self.scope(ROOT + '/preview'), json=payload).status_code)
        finally: client.close()
        self.core.create_exercise(self.a['id'], {'module':'fiscal','year':2027}, 'synthetic')
        self.activate(self.a['id'], '2027-01')
        for suffix in ('preview', 'generate'): self.post(ROOT + '/' + suffix, payload, 409)

    def test_incoming_global_plan_preview_does_not_materialize_accounts(self):
        import test_global_account_plans as plans
        plan, _, _ = plans.GlobalAccountPlanTests.publish(self)
        cid = self.b['id']; self.activate(cid)
        p = self.post(f"/global-account-plans/{plan['id']}/preview", {'mode': 'shared'}, cid=cid)
        self.post(f"/global-account-plans/previews/{p['id']}/confirm", {'preview_hash': p['preview_hash'], 'properties_reviewed': True, 'reason': 'Fixture'}, cid=cid)
        model = self.model('GLOBAL', debit='00101', credit='00102', cid=cid)
        doc = self.purchase(cid=cid); payload = self.payload([doc], model, version=0)
        before = self.snapshot(); planned = self.post(ROOT + '/preview', payload, cid=cid)
        self.assertEqual(before, self.snapshot())
        self.assertEqual({'00101', '00102'}, {l['account_code'] for l in planned['journals'][0]['lines']})
        configured = {m['id']: m for m in self.core.masters(cid, 'accounting_model')}[model]['data']
        self.assertEqual({configured['debit_account_id'], configured['credit_account_id']}, {l['account_id'] for l in planned['journals'][0]['lines']})
        actual = self.post(ROOT + '/generate', payload, cid=cid)
        self.assertTrue(all(l['account_id'] > 0 for l in actual['journals'][0]['lines']))
        self.assertEqual(planned['journals'][0]['total_cents'], actual['journals'][0]['total_cents'])

    def test_concurrent_incoming_generation_has_one_effect(self):
        model = self.model(); docs = [self.purchase('C1'), self.purchase('C2')]; payload = self.payload(docs, model)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: self.core.generate_purchase_accounting(self.a['id'], payload, 'synthetic'), range(2)))
        self.assertEqual(1, sum(bool(r.get('duplicate')) for r in results)); self.assertEqual(2, len(self.core.journals(self.a['id'])))

    def test_incoming_supplier_must_be_explicitly_linked(self):
        model = self.model(); tax_id = self.a['tax_id']
        doc = self.purchase('SUPPLIER-MISSING', partner_tax_id=tax_id)
        before = self.snapshot()
        for suffix in ('preview', 'generate'):
            self.post(ROOT + '/' + suffix, self.payload([doc], model), 400)
        self.assertEqual(before, self.snapshot())
        party = self.post('/masters/participant', {'code':'SUP-SYN','name':'Fornecedor sintético','tax_id':tax_id,'data':{}}, 201)
        linked = self.purchase('SUPPLIER-LINKED', participant_id=party['id'], partner_tax_id=tax_id)
        result = self.post(ROOT + '/generate', self.payload([linked], model))
        self.assertEqual({party['id']}, {l['participant_id'] for l in result['journals'][0]['lines']})

    def test_model_revoked_after_preview_is_rejected_without_writes(self):
        model = self.model(); doc = self.purchase(); payload = self.payload([doc], model)
        self.post(ROOT + '/preview', payload)
        current = next(m for m in self.core.masters(self.a['id'], 'accounting_model') if m['id'] == model)
        response = self.client.put(self.scope(f'/masters/accounting_model/{model}'), json=current | {'active':False})
        self.assertEqual(200, response.status_code, response.text)
        before = self.snapshot(); self.post(ROOT + '/generate', payload, 400); self.assertEqual(before, self.snapshot())

    def test_rebook_after_reversal_preserves_old_sources_and_creates_new_individual(self):
        model = self.model(); doc = self.purchase(); original = self.post(ROOT + '/generate', self.payload([doc], model))['journals'][0]
        current = next(d for d in self.core.documents(self.a['id']) if d['id'] == doc['id'])
        current = self.reverse(current)['document']
        current = self.post(f"/documents/{doc['id']}/review", {'version':current['version'],'reason':'Fixture'})
        current = self.post(f"/documents/{doc['id']}/book", {'version':current['version'],'reason':'Fixture'})['document']
        regenerated = self.post(ROOT + '/generate', self.payload([current], model, 'after-reversal'))
        self.assertNotEqual(original['id'], regenerated['journals'][0]['id'])
        trace = self.client.get(self.scope(f"/documents/{doc['id']}/trace")).json()
        self.assertEqual(2, len(trace['accounting_sources'])); self.assertEqual(3, len(self.core.journals(self.a['id'])))
