"""Synthetic NF-e snapshots, company charts and disposable databases only."""
import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from xml.etree.ElementTree import fromstring
import test_direct_fiscal_accounting as prior
from app.importers import _xml_snapshot
from app.fiscal_payment_allocations import payment_evidence

ROOT = '/fiscal-sales-accounting'


def declared(payments, change=None):
    text = '<infNFe><pag>' + ''.join(f'<detPag><tPag>{m}</tPag><vPag>{v}</vPag></detPag>' for m, v in payments)
    if change is not None:
        text += f'<vTroco>{change}</vTroco>'
    return _xml_snapshot(fromstring(text + '</pag></infNFe>'))


class FiscalPaymentAllocationTests(unittest.TestCase):
    for _name in ('setUp','tearDown','scope','activate','create_company','document','journal','post','mode','sale','purchase','model','snapshot','reverse','operator','direct'):
        locals()[_name] = getattr(prior.DirectFiscalAccountingTests,_name)
    del _name

    def note(self, number='P1', payments=(('01','6.00'),('03','4.01')), total='10.01', change=None, **kw):
        return self.sale(number,total,declared_document_fields=declared(payments,change),**kw)

    def payload(self, docs, key='payments', cid=None):
        refs={a['access_code']:a['id'] for a in self.core.accounts(cid or self.a['id'])}
        cfg=self.client.get(self.scope(ROOT+'/settings',cid)).json()
        return dict(settings_version=cfg['version'],idempotency_key=key,entries=[dict(document_id=d['id'],version=d['version'],credit_account_id=refs['5'],payment_accounts=[dict(method='01',account_id=refs['3']),dict(method='03',account_id=refs['6'])]) for d in docs])

    def test_declared_payments_readonly_preview_daily_cash_and_mixed_trace(self):
        self.mode();docs=[self.note(),self.note('P2',(('01','0.01'),),'0.01')];payload=self.payload(docs)
        before=self.snapshot();details=self.post(ROOT+'/payments',{'entries':[{'document_id':d['id'],'version':d['version']} for d in docs]})
        self.assertEqual(before,self.snapshot());self.assertEqual([600,401],[p['amount_cents'] for p in details['documents'][0]['payments']])
        preview=self.post(ROOT+'/preview',payload);self.assertEqual(before,self.snapshot())
        self.assertEqual((1,2),(preview['created_count'],preview['accounted_count']));self.assertEqual(1002,preview['journals'][0]['total_cents'])
        result=self.post(ROOT+'/generate',payload);journal=result['journals'][0]
        self.assertEqual((1,2),(result['created_count'],result['accounted_count']))
        self.assertEqual(1002,sum(l['debit_cents'] for l in journal['lines']));self.assertEqual(1002,sum(l['credit_cents'] for l in journal['lines']))
        self.assertEqual({601,401},{l['debit_cents'] for l in journal['lines'] if l['debit_cents']})
        trace=self.client.get(self.scope(f"{ROOT}/journals/{journal['id']}/sources")).json()
        self.assertEqual({d['id'] for d in docs},{s['document_id'] for s in trace['sources']})
        self.assertTrue(all(s['entry_method']=='payments' for s in trace['sources']))
        self.assertEqual([600,401],[p['net_cents'] for p in trace['sources'][0]['payment_snapshot']['payments']])
        for d in docs:
            saved=next(n for n in self.core.documents(self.a['id']) if n['id']==d['id']);self.assertEqual(d|{'journal_id':journal['id']},saved)
        self.assertEqual([],self.core.titles(self.a['id']))

    def test_individual_multiple_dates_classifications_accounts_and_company(self):
        docs=[self.note(),self.note('P2')];first=self.post(ROOT+'/generate',self.payload(docs));self.assertEqual(2,first['created_count'])
        self.mode();more=[self.note('D1'),self.note('D2',day='2026-11-07'),self.note('D3',cfop='6102'),self.note('D4')]
        payload=self.payload(more,'dimensions');payload['entries'][-1]['payment_accounts'][1]['account_id']=self.aid['4']
        result=self.post(ROOT+'/generate',payload);self.assertEqual(4,result['created_count'])
        self.activate(self.b['id']);doc=self.note('OTHER',cid=self.b['id']);other=self.post(ROOT+'/generate',self.payload([doc],cid=self.b['id']),cid=self.b['id']);self.assertEqual(1,other['created_count'])
        self.assertEqual(6,len(self.core.journals(self.a['id'])));self.assertEqual(1,len(self.core.journals(self.b['id'])))

    def test_explicit_change_not_assumed_and_split_evidence_retained(self):
        doc=self.note(payments=(('01','8.00'),('03','5.00')),total='10.00',change='3.00');payload=self.payload([doc]);before=self.snapshot()
        self.post(ROOT+'/generate',payload,400);self.assertEqual(before,self.snapshot())
        payload['entries'][0]['change_allocations']=[dict(payment_index=0,amount_cents=200),dict(payment_index=1,amount_cents=100)]
        result=self.post(ROOT+'/generate',payload);snapshot=result['sources'][0]['payment_snapshot']
        self.assertEqual([600,400],[p['net_cents'] for p in snapshot['payments']]);self.assertEqual([200,100],[p['change_cents'] for p in snapshot['payments']])

    def test_invalid_amounts_evidence_and_allocations_are_atomic(self):
        invalid=[None,declared([('01','9.99')]),declared([('90','10.01')]),declared([('91','10.01')]),declared([('01','-10.01')]),declared([('01','10.001')]),{'children':{}},declared([('','10.01')])]
        for index,snapshot in enumerate(invalid):
            doc=self.sale('BAD'+str(index),'10.01',declared_document_fields=snapshot)
            before=self.snapshot();self.post(ROOT+'/generate',self.payload([doc],'bad'+str(index)),400);self.assertEqual(before,self.snapshot())
        doc=self.note('MAP');original=self.payload([doc]);others=self.core.accounts(self.b['id'])
        changes=[{'payment_accounts':[]},{'payment_accounts':[{'method':'01','account_id':self.aid['3']}]},
                 {'payment_accounts':[{'method':'01','account_id':others[0]['id']},{'method':'03','account_id':self.aid['6']}]},
                 {'payment_accounts':[{'method':'01','account_id':True}]},{'debit_account_id':self.aid['3']},
                 {'change_allocations':[{'payment_index':True,'amount_cents':0}]},
                 {'change_allocations':[{'payment_index':0,'amount_cents':0},{'payment_index':0,'amount_cents':0}]},
                 {'change_allocations':[{'payment_index':10,'amount_cents':0}]}]
        for patch in changes:
            payload=copy.deepcopy(original);payload['entries'][0].update(patch);before=self.snapshot();r=self.client.post(self.scope(ROOT+'/generate'),json=payload)
            self.assertIn(r.status_code,[400,404],r.text);self.assertEqual(before,self.snapshot())

    def test_replay_changed_key_mode_and_concurrency_have_one_effect(self):
        self.mode();docs=[self.note(),self.note('P2')];payload=self.payload(docs)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.core.generate_sales_accounting(self.a['id'],payload,'synthetic'),range(2)))
        self.assertEqual(1,sum(bool(r.get('duplicate')) for r in results));self.assertEqual(1,len(self.core.journals(self.a['id'])))
        before=self.snapshot();self.assertTrue(self.post(ROOT+'/generate',payload)['duplicate']);self.assertEqual(before,self.snapshot())
        self.mode('individual');skipped=self.post(ROOT+'/generate',self.payload(docs,'fresh'));self.assertEqual((0,2),(skipped['created_count'],len(skipped['skipped'])))
        new=self.note('CONCURRENT');payload=self.payload([new],'new1');other=payload|{'idempotency_key':'new2'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            rs=list(pool.map(lambda p:self.core.generate_sales_accounting(self.a['id'],p,'synthetic'),[payload,other]))
        self.assertEqual(1,sum(r['created_count'] for r in rs));self.assertEqual(2,len(self.core.journals(self.a['id'])))

    def test_closed_reopened_and_partial_reversal_use_each_source_lines(self):
        self.mode();docs=[self.note(),self.note('P2')];payload=self.payload(docs)
        self.post('/periods/close',{'module':'accounting','period':'2026-11','reason':'Fixture'})
        before=self.snapshot();self.post(ROOT+'/generate',payload,409);self.assertEqual(before,self.snapshot())
        self.post('/periods/reopen',{'module':'accounting','period':'2026-11','reason':'Fixture'})
        result=self.post(ROOT+'/generate',payload);original=result['journals'][0]
        current=next(d for d in self.core.documents(self.a['id']) if d['id']==docs[0]['id']);self.reverse(current)
        trace=self.client.get(self.scope(f"{ROOT}/journals/{original['id']}/sources")).json();self.assertEqual(1,len(trace['reversals']))
        compensation=next(j for j in self.core.journals(self.a['id']) if j['id']!=original['id'])
        self.assertEqual(1001,compensation['total_cents']);self.assertEqual(3,len(compensation['lines']))
        self.assertEqual(original,self.client.get(self.scope(f"/journals/{original['id']}")).json())
        self.assertEqual(original['id'],next(d for d in self.core.documents(self.a['id']) if d['id']==docs[1]['id'])['journal_id'])

    def test_read_permissions_stale_versions_and_incoming_rejection(self):
        doc=self.note();payload=self.payload([doc]);entries={'entries':[{'document_id':doc['id'],'version':doc['version']}]}
        client,uid=self.operator({'fiscal.documents':['read'],'accounting.accounts':['read'],'accounting.journals':['read']})
        try:
            self.assertEqual(200,client.post(self.scope(ROOT+'/payments'),json=entries).status_code)
            self.assertEqual(200,client.post(self.scope(ROOT+'/preview'),json=payload).status_code)
            self.assertEqual(403,client.post(self.scope(ROOT+'/generate'),json=payload).status_code)
        finally:client.close()
        entries['entries'][0]['version']-=1;self.post(ROOT+'/payments',entries,409)
        payload['entries'][0]['version']-=1;self.post(ROOT+'/generate',payload,409)
        incoming=self.purchase();payload=self.payload([incoming]);self.post('/fiscal-purchases-accounting/generate',payload,400)

    def test_repeated_methods_and_full_change_keep_all_detail_origins(self):
        doc=self.note(payments=(('03','1.00'),('03','2.00'),('01','7.01')))
        result=self.post(ROOT+'/generate',self.payload([doc]));self.assertEqual(3,len(result['journals'][0]['lines']))
        self.assertEqual(3,len(result['sources'][0]['payment_snapshot']['payments']))
        other=self.note('ZERO',payments=(('01','3.00'),('03','10.00')),total='10.00',change='3.00')
        payload=self.payload([other],'zero');payload['entries'][0]['change_allocations']=[dict(payment_index=0,amount_cents=300)]
        result=self.post(ROOT+'/generate',payload);self.assertEqual(2,len(result['journals'][0]['lines']))
        self.assertEqual(0,result['sources'][0]['payment_snapshot']['payments'][0]['net_cents'])

    def test_global_accounts_preview_does_not_materialize_and_group_is_stable(self):
        import test_global_account_plans as plans
        plan,_,_=plans.GlobalAccountPlanTests.publish(self);cid=self.b['id'];self.activate(cid)
        preview=self.post(f"/global-account-plans/{plan['id']}/preview",{'mode':'shared'},cid=cid)
        self.post(f"/global-account-plans/previews/{preview['id']}/confirm",{'preview_hash':preview['preview_hash'],'properties_reviewed':True,'reason':'Fixture'},cid=cid)
        docs=[self.note('G1',cid=cid),self.note('G2',cid=cid)];refs={a['access_code']:a['id'] for a in self.core.accounts(cid)}
        version=self.mode(cid=cid)
        payload=dict(settings_version=version,idempotency_key='global-pay',entries=[dict(document_id=d['id'],version=d['version'],credit_account_id=refs['00102'],payment_accounts=[dict(method=m,account_id=refs['00101']) for m in ['01','03']]) for d in docs])
        before=self.snapshot();self.assertEqual(1,self.post(ROOT+'/preview',payload,cid=cid)['created_count']);self.assertEqual(before,self.snapshot())
        result=self.post(ROOT+'/generate',payload,cid=cid);self.assertEqual((1,2),(result['created_count'],result['accounted_count']))
        self.assertTrue(all(l['account_id']>0 for l in result['journals'][0]['lines']))
        self.assertTrue(self.post(ROOT+'/generate',payload,cid=cid)['duplicate'])

    def test_split_accounts_require_active_company_account_and_center(self):
        account=next(a for a in self.core.accounts(self.a['id']) if a['id']==self.aid['6'])
        self.core.save_account(self.a['id'],account|{'requires_cost_center':True},'synthetic',account['id'])
        doc=self.note();payload=self.payload([doc]);before=self.snapshot();self.post(ROOT+'/generate',payload,400);self.assertEqual(before,self.snapshot())
        center=self.core.save_cost_center(self.a['id'],{'code':'PAY-C','name':'Centro sintético'},'synthetic')
        payload['entries'][0]['cost_center_id']=center['id'];preview=self.post(ROOT+'/preview',payload)
        self.assertEqual({center['id']},{l['cost_center_id'] for l in preview['journals'][0]['lines']})
        account=next(a for a in self.core.accounts(self.a['id']) if a['id']==self.aid['6'])
        self.core.save_account(self.a['id'],account|{'active':False},'synthetic',account['id'])
        before=self.snapshot();self.post(ROOT+'/generate',payload,400);self.assertEqual(before,self.snapshot())

    def test_missing_evidence_does_not_change_single_account_flow(self):
        doc=self.sale();details=self.post(ROOT+'/payments',{'entries':[{'document_id':doc['id'],'version':doc['version']}]})
        self.assertTrue(details['documents'][0]['issue'])
        result=self.post(ROOT+'/generate',self.direct([doc],debit='3',credit='5'))
        self.assertEqual('direct',result['sources'][0]['entry_method'])


if __name__=='__main__':unittest.main()
