"""Direct account selection; only synthetic companies, notes and disposable SQLite."""
import unittest
from concurrent.futures import ThreadPoolExecutor
import test_fiscal_incoming_accounting as prior

ROOT = '/fiscal-purchases-accounting'


class DirectFiscalAccountingTests(unittest.TestCase):
    for _name in ('setUp','tearDown','scope','activate','create_company','document','journal','post','mode','sale','purchase','model','snapshot','reverse','operator'):
        locals()[_name] = getattr(prior.FiscalIncomingAccountingTests,_name)
    del _name

    def direct(self, docs, key='direct', debit='6', credit='4', cid=None, center=None):
        refs={a['access_code']:a['id'] for a in self.core.accounts(cid or self.a['id'])}
        version=self.client.get(self.scope('/fiscal-sales-accounting/settings',cid)).json()['version']
        return {'settings_version':version,'idempotency_key':key,'reason':'Contas escolhidas na integração sintética',
                'entries':[{'document_id':d['id'],'version':d['version'],'debit_account_id':refs[debit],
                            'credit_account_id':refs[credit],'cost_center_id':center} for d in docs]}

    def test_incoming_without_any_model_preview_values_trace_and_fiscal_preservation(self):
        self.mode(); docs=[self.purchase('E1','0.01'),self.purchase('E2','10.02')];payload=self.direct(docs)
        before=self.snapshot();preview=self.post(ROOT+'/preview',payload)
        self.assertEqual(before,self.snapshot());self.assertEqual(('individual',2), (preview['mode'],preview['created_count']))
        result=self.post(ROOT+'/generate',payload)
        self.assertEqual([1,1002],[j['total_cents'] for j in result['journals']]);self.assertEqual([],self.core.masters(self.a['id'],'accounting_model'))
        for old,source,journal in zip(docs,result['sources'],result['journals']):
            self.assertIsNone(source['model_snapshot']);self.assertEqual('direct',source['entry_method'])
            self.assertEqual(old|{'journal_id':journal['id']},next(d for d in self.core.documents(self.a['id']) if d['id']==old['id']))
            trace=self.client.get(self.scope(f"/fiscal-sales-accounting/journals/{journal['id']}/sources")).json()
            self.assertEqual(old['id'],trace['sources'][0]['document_id'])
            self.assertEqual(journal['total_cents'],sum(l['debit_cents'] for l in journal['lines']))
            self.assertEqual(journal['total_cents'],sum(l['credit_cents'] for l in journal['lines']))
        self.assertEqual([],self.core.titles(self.a['id']))

    def test_daily_direct_and_optional_model_share_real_group_and_separate_dimensions(self):
        self.mode();model=self.model('OPTIONAL',debit='6',credit='4',direction='outgoing')
        docs=[self.sale('S1','0.01'),self.sale('S2','10.02'),self.sale('S3',day='2026-11-07'),self.sale('S4',cfop='6102'),self.sale('S5')]
        payload=self.direct(docs);payload['entries'][1]={'document_id':docs[1]['id'],'version':docs[1]['version'],'model_id':model}
        payload['entries'][-1]['credit_account_id']=self.aid['5']
        before=self.snapshot();preview=self.post('/fiscal-sales-accounting/preview',payload);self.assertEqual(before,self.snapshot())
        result=self.post('/fiscal-sales-accounting/generate',payload)
        self.assertEqual((4,5),(result['created_count'],result['accounted_count']));self.assertEqual(1003,result['journals'][0]['total_cents'])
        self.assertEqual({'direct','model'},{s['entry_method'] for s in result['sources']})
        self.assertEqual([j['total_cents'] for j in preview['journals']],[j['total_cents'] for j in result['journals']])

    def test_direct_does_not_require_model_permission_and_model_still_requires_it(self):
        model=self.model();doc=self.purchase();payload=self.direct([doc])
        client,uid=self.operator({'fiscal.documents':['read'],'accounting.accounts':['read'],'accounting.journals':['read','create']})
        try:
            self.assertEqual(200,client.post(self.scope(ROOT+'/preview'),json=payload).status_code)
            r=client.post(self.scope(ROOT+'/generate'),json=payload);self.assertEqual(200,r.status_code,r.text)
            self.assertTrue(client.post(self.scope(ROOT+'/generate'),json=payload).json()['duplicate'])
            other=self.purchase('MODEL');modeled=self.direct([other],'model-no-grant')
            modeled['entries']=[{'document_id':other['id'],'version':other['version'],'model_id':model}]
            self.assertEqual(403,client.post(self.scope(ROOT+'/generate'),json=modeled).status_code)
        finally:client.close()

    def test_invalid_missing_other_company_same_account_and_mixed_method_are_atomic(self):
        doc=self.purchase();valid=self.direct([doc]);other=self.core.accounts(self.b['id'])[0]['id'];model=self.model()
        changes=[{'debit_account_id':None},{'debit_account_id':True},{'debit_account_id':'6'},
                 {'credit_account_id':valid['entries'][0]['debit_account_id']},{'debit_account_id':other},{'model_id':model},{'total_cents':1}]
        for changed in changes:
            payload=valid|{'entries':[valid['entries'][0]|changed]};before=self.snapshot()
            r=self.client.post(self.scope(ROOT+'/generate'),json=payload)
            self.assertIn(r.status_code,[400,404],r.text);self.assertEqual(before,self.snapshot())
        self.assertEqual([],self.core.journals(self.a['id']))

    def test_required_cost_center_and_account_activity_use_existing_validation(self):
        expense=next(a for a in self.core.accounts(self.a['id']) if a['id']==self.aid['6'])
        self.core.save_account(self.a['id'],expense|{'requires_cost_center':True},'synthetic',expense['id'])
        expense=next(a for a in self.core.accounts(self.a['id']) if a['id']==self.aid['6'])
        doc=self.purchase();payload=self.direct([doc]);self.post(ROOT+'/generate',payload,400)
        center=self.core.save_cost_center(self.a['id'],{'code':'SYN-C','name':'Centro sintético'},'synthetic')
        payload=self.direct([doc],center=center['id']);preview=self.post(ROOT+'/preview',payload)
        self.assertEqual({center['id']},{l['cost_center_id'] for l in preview['journals'][0]['lines']})
        self.core.save_account(self.a['id'],expense|{'requires_cost_center':True,'active':False},'synthetic',expense['id'])
        before=self.snapshot();self.post(ROOT+'/generate',payload,400);self.assertEqual(before,self.snapshot())

    def test_global_virtual_accounts_preview_readonly_and_own_fork_keeps_used_accounts(self):
        import test_global_account_plans as plans
        plan,_,_=plans.GlobalAccountPlanTests.publish(self);cid=self.b['id'];self.activate(cid)
        p=self.post(f"/global-account-plans/{plan['id']}/preview",{'mode':'shared'},cid=cid)
        self.post(f"/global-account-plans/previews/{p['id']}/confirm",{'preview_hash':p['preview_hash'],'properties_reviewed':True,'reason':'Fixture'},cid=cid)
        doc=self.purchase(cid=cid);payload=self.direct([doc],debit='00101',credit='00102',cid=cid)
        self.assertTrue(all(payload['entries'][0][k]<0 for k in ['debit_account_id','credit_account_id']))
        before=self.snapshot();preview=self.post(ROOT+'/preview',payload,cid=cid);self.assertEqual(before,self.snapshot())
        self.assertTrue(all(l['account_id']<0 for l in preview['journals'][0]['lines']))
        result=self.post(ROOT+'/generate',payload,cid=cid);ids={l['account_id'] for l in result['journals'][0]['lines']}
        self.assertTrue(all(i>0 for i in ids))
        binding=self.client.get(self.scope('/global-account-plans',cid)).json()['binding']
        self.post('/global-account-plans/binding/detach',{'version':binding['version'],'reason':'Fixture','copy_scope':'used'},cid=cid)
        self.assertTrue(self.post(ROOT+'/generate',payload,cid=cid)['duplicate'])
        self.assertEqual(ids,{l['account_id'] for l in self.core.journals(cid)[0]['lines']})

    def test_closed_reopened_reversal_and_mode_change_do_not_duplicate_or_rewrite(self):
        doc=self.purchase();payload=self.direct([doc]);self.post(ROOT+'/preview',payload)
        self.post('/periods/close',{'module':'accounting','period':'2026-11','reason':'Fixture'})
        before=self.snapshot();self.post(ROOT+'/generate',payload,409);self.assertEqual(before,self.snapshot())
        self.post('/periods/reopen',{'module':'accounting','period':'2026-11','reason':'Fixture'})
        original=self.post(ROOT+'/generate',payload)['journals'][0];self.mode()
        self.assertTrue(self.post(ROOT+'/generate',payload)['duplicate'])
        skipped=self.post(ROOT+'/generate',self.direct([doc],'new-key'))
        self.assertEqual((0,1),(skipped['created_count'],len(skipped['skipped'])))
        current=next(d for d in self.core.documents(self.a['id']) if d['id']==doc['id']);self.reverse(current)
        trace=self.client.get(self.scope(f"/fiscal-sales-accounting/journals/{original['id']}/sources")).json()
        self.assertEqual('direct',trace['sources'][0]['entry_method']);self.assertEqual(1,len(trace['reversals']))
        self.assertEqual(original,self.client.get(self.scope(f"/journals/{original['id']}")).json())

    def test_concurrent_direct_requests_have_one_effect(self):
        docs=[self.purchase('C1'),self.purchase('C2')];payload=self.direct(docs)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.core.generate_purchase_accounting(self.a['id'],payload,'synthetic'),range(2)))
        self.assertEqual(1,sum(bool(r.get('duplicate')) for r in results));self.assertEqual(2,len(self.core.journals(self.a['id'])))

    def test_individual_sales_then_daily_preserves_previous_and_report_readonly(self):
        docs=[self.sale('I1','0.01'),self.sale('I2','10.02')];payload=self.direct(docs)
        first=self.post('/fiscal-sales-accounting/generate',payload)
        self.assertEqual(('individual',2),(first['mode'],first['created_count']))
        before=self.core.journals(self.a['id']);self.mode();self.assertEqual(before,self.core.journals(self.a['id']))
        skipped=self.post('/fiscal-sales-accounting/generate',self.direct(docs,'mode-changed'))
        self.assertEqual((0,2),(skipped['created_count'],len(skipped['skipped'])))
        snapshot=self.snapshot();report=self.core.business_report(self.a['id'],'consolidated-diary','2026-11-01','2026-11-30')
        self.assertEqual(1003,report['totals']['debit_cents']);self.assertEqual(1003,report['totals']['credit_cents'])
        self.assertEqual(snapshot,self.snapshot())
