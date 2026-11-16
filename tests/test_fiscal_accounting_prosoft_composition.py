"""PR49 + PR44 compatibility, synthetic companies/mappings and temporary SQLite only."""
import unittest
import test_fiscal_incoming_accounting as incoming


class FiscalAccountingProsoftCompositionTests(unittest.TestCase):
    for _name in ('setUp', 'tearDown', 'scope', 'activate', 'create_company', 'document', 'journal',
                  'post', 'mode', 'sale', 'purchase', 'model', 'payload', 'snapshot', 'reverse'):
        locals()[_name] = getattr(incoming.FiscalIncomingAccountingTests, _name)
    del _name

    def save_export_settings(self, root, changed):
        old = self.client.get(self.scope(root + '/settings')).json()
        response = self.client.put(self.scope(root + '/settings'), json={
            'version':old['version'], 'settings':old['settings'] | changed})
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def mappings(self):
        fiscal = self.save_export_settings('/prosoft-fiscal', {'company_code':'99', 'plan_code':'52',
            'species':{'55':{'code':'NFE','confirmed':True}},
            'cfop_accounts':{'1102':{'code':'123','confirmed':True},'5102':{'code':'456','confirmed':True}}})
        accounting = self.save_export_settings('/prosoft', {'company_code':'99','plan_code':'52',
            'accounts':{str(a['id']):{'code':a['access_code'],'confirmed':True} for a in self.accounts}})
        return fiscal, accounting

    def economic(self):
        return {k:v for k,v in self.snapshot().items() if k in {'documents','journals','journal_lines','titles','document_sources','imports'}}

    def export(self, cfg):
        payload = cfg['settings'] | {'settings_version':cfg['version'], 'period':'2026-11','allow_ascii':True}
        preview = self.post('/prosoft/preview', payload)
        confirm = payload | {'preview_hash':preview['preview_hash'],'destination_reviewed':True}
        saved = self.post('/prosoft/confirm', confirm)
        self.assertEqual(saved['id'], self.post('/prosoft/confirm', confirm)['id'])
        downloaded = self.client.get(self.scope(f"/exports/{saved['id']}/download"))
        self.assertEqual(200, downloaded.status_code, downloaded.text)
        return preview

    def test_saved_destination_mappings_do_not_change_integration_and_export_is_readonly(self):
        fiscal, accounting = self.mappings(); self.mode()
        buy = self.model('COMPOSE-BUY', debit='6', credit='4')
        sell = self.model('COMPOSE-SELL', direction='outgoing')
        purchases = [self.purchase('E1','0.01'),self.purchase('E2','10.02')]
        sales = [self.sale('S1','0.01'),self.sale('S2','10.02')]
        intent = self.payload(purchases, buy, 'composition-incoming')
        before = self.snapshot(); planned = self.post(incoming.ROOT + '/preview', intent)
        self.assertEqual(before, self.snapshot()); self.assertEqual(2, planned['created_count'])
        generated = self.post(incoming.ROOT + '/generate', intent)
        self.assertEqual('individual', generated['mode']); self.assertEqual(2, generated['created_count'])
        daily = self.post('/fiscal-sales-accounting/generate', self.payload(sales, sell, 'composition-daily'))
        self.assertEqual(('daily',1), (daily['mode'],daily['created_count']))
        before = self.economic(); preview = self.export(accounting)
        self.assertEqual(before, self.economic())
        self.assertEqual((3,2006,2006), tuple(preview['manifest'][k] for k in ('journals','debit_cents','credit_cents')))
        self.assertEqual('0052', preview['manifest']['plan_code'])
        shortened = [x['document_reference'] for x in preview['manifest']['trace'] if 'document_reference' in x]
        self.assertEqual({'ENTRADAS-FISCAIS','SAIDAS-FISCAIS'}, {x['original'] for x in shortened})
        self.assertTrue(all(len(x['exported']) <= 10 for x in shortened))
        for root, cfg in [('/prosoft-fiscal',fiscal),('/prosoft',accounting)]:
            self.assertEqual(cfg, self.client.get(self.scope(root + '/settings')).json())
        before = self.snapshot(); self.assertTrue(self.post(incoming.ROOT + '/generate', intent)['duplicate'])
        self.assertEqual(before, self.snapshot())
        self.assertEqual('daily', self.client.get(self.scope('/fiscal-sales-accounting/settings')).json()['mode'])

    def test_closed_export_preserves_incoming_guard_and_reversal_trace(self):
        _, accounting = self.mappings(); buy = self.model('COMPOSE-BUY', debit='6', credit='4')
        doc, pending = self.purchase('E1'), self.purchase('E2')
        original = self.post(incoming.ROOT + '/generate', self.payload([doc],buy))['journals'][0]
        for module in ('fiscal','accounting'):
            self.post('/periods/close', {'module':module,'period':'2026-11','reason':'Fixture sintetica'})
        before = self.economic(); self.export(accounting); self.assertEqual(before, self.economic())
        self.post(incoming.ROOT + '/generate', self.payload([pending],buy,'closed'), 409)
        for module in ('fiscal','accounting'):
            self.post('/periods/reopen', {'module':module,'period':'2026-11','reason':'Fixture sintetica'})
        current = next(d for d in self.core.documents(self.a['id']) if d['id']==doc['id'])
        self.reverse(current)
        before = self.economic(); preview = self.export(accounting)
        self.assertEqual(before, self.economic()); self.assertEqual(2, preview['manifest']['journals'])
        trace = self.client.get(self.scope(f"/fiscal-sales-accounting/journals/{original['id']}/sources")).json()
        self.assertEqual(doc['id'], trace['sources'][0]['document_id']); self.assertEqual(1,len(trace['reversals']))
        self.assertEqual(2,len(self.core.journals(self.a['id'])))
