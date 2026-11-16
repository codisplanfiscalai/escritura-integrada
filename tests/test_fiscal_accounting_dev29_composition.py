"""PR49/dev.29 composition, exclusively synthetic parties, documents and SQLite."""
import unittest
import test_fiscal_incoming_accounting as incoming


class FiscalAccountingDev29CompositionTests(unittest.TestCase):
    for _name in ('setUp','tearDown','scope','activate','create_company','document','journal',
                  'post','mode','sale','purchase','model','payload','snapshot','reverse'):
        locals()[_name] = getattr(incoming.FiscalIncomingAccountingTests, _name)
    del _name

    def contributions(self, cid=None):
        response = self.client.get(self.scope('/sped-generator/contributions-snapshot?period=2026-11', cid))
        self.assertEqual(200, response.status_code, response.text)
        self.assertFalse(response.json()['snapshot']['generates_efd'])
        return response.json()

    def test_shared_supplier_is_explicitly_local_and_incoming_remains_individual_per_company(self):
        self.mode()
        party = self.post('/registrations/third-party', {'name':'Fornecedor global sintético',
            'tax_id':'11222333000181','code':'SUP-SYN','data':{}}, 201)
        linked = self.post(f"/registrations/third-party/{party['id']}/use", {'version':party['version']})
        aid, bid = self.a['id'], self.b['id']
        local_a = next(l['master_id'] for l in linked['links'] if l['company_id']==aid)
        model_a = self.model('A-BUY', debit='6', credit='4')
        docs = [self.purchase('A-'+str(i), amount, participant_id=local_a,
                             partner_tax_id=party['tax_id'], partner_name=party['name'])
                for i, amount in [(1,'0.01'),(2,'10.02')]]
        payload = self.payload(docs, model_a, 'dev29-A')
        before = self.snapshot(); self.post(incoming.ROOT+'/preview',payload)
        self.contributions(); self.assertEqual(before,self.snapshot())
        result = self.post(incoming.ROOT+'/generate',payload)
        self.assertEqual(('individual',2), (result['mode'],result['created_count']))
        self.assertEqual({local_a},{l['participant_id'] for j in result['journals'] for l in j['lines']})
        before = self.snapshot(); self.assertTrue(self.post(incoming.ROOT+'/generate',payload)['duplicate'])
        self.assertEqual(before,self.snapshot())
        self.activate(bid)
        linked = self.post(f"/registrations/third-party/{party['id']}/use", {'version':linked['version']}, cid=bid)
        local_b = next(l['master_id'] for l in linked['links'] if l['company_id']==bid)
        self.assertNotEqual(local_a,local_b)
        model_b = self.model('B-BUY', debit='6', credit='4', cid=bid)
        doc_b = self.purchase('B-1','0.03',cid=bid,participant_id=local_b,
                              partner_tax_id=party['tax_id'],partner_name=party['name'])
        generated = self.post(incoming.ROOT+'/generate',self.payload([doc_b],model_b,'dev29-B',version=0),cid=bid)
        self.assertEqual({local_b},{l['participant_id'] for l in generated['journals'][0]['lines']})
        self.assertEqual((2,1),(len(self.core.journals(aid)),len(self.core.journals(bid))))
        before = self.snapshot(); self.contributions(bid); self.assertEqual(before,self.snapshot())
        with self.core.db.read() as conn:
            self.assertEqual([],conn.execute('PRAGMA foreign_key_check').fetchall())
        self.assertEqual('daily',self.client.get(self.scope('/fiscal-sales-accounting/settings',aid)).json()['mode'])

    def test_contributions_reads_do_not_change_daily_sources_or_partial_reversal(self):
        self.mode(); model = self.model('SALE', direction='outgoing')
        docs = [self.sale('D1','0.01'),self.sale('D2','10.02')]
        original = self.post('/fiscal-sales-accounting/generate',self.payload(docs,model,'dev29-daily'))
        self.assertEqual((1,2),(original['created_count'],original['accounted_count']))
        journal = original['journals'][0]; self.assertEqual(1003,journal['total_cents'])
        before = self.snapshot(); self.contributions(); self.contributions()
        trace = self.client.get(self.scope(f"/fiscal-sales-accounting/journals/{journal['id']}/sources")).json()
        self.assertEqual({d['id'] for d in docs},{s['document_id'] for s in trace['sources']})
        self.assertEqual(before,self.snapshot())
        current = next(d for d in self.core.documents(self.a['id']) if d['id']==docs[0]['id'])
        compensation = self.reverse(current)['journal']; self.assertEqual(1,compensation['total_cents'])
        before = self.snapshot(); self.contributions(); self.assertEqual(before,self.snapshot())
        self.assertEqual(2,len(self.core.journals(self.a['id'])))
        for j in self.core.journals(self.a['id']):
            self.assertEqual(sum(l['debit_cents'] for l in j['lines']),sum(l['credit_cents'] for l in j['lines']))
