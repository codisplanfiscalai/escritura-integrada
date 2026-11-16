"""PR61/dev.31 composition: direct fiscal entries reach the ledger unchanged."""
import unittest
import test_direct_fiscal_accounting as direct


class LedgerDirectCompositionTests(unittest.TestCase):
    for _name in ('setUp','tearDown','scope','activate','create_company','document','journal','post','mode','sale','purchase','model','snapshot','reverse','operator','direct'):
        locals()[_name]=getattr(direct.DirectFiscalAccountingTests,_name)
    del _name

    def assert_ledger(self,cid,journals,total):
        before=self.snapshot()
        report=self.core.business_report(cid,'ledger','2026-11-01','2026-11-30')
        rows=report['rows'];ids={j['id'] for j in journals}
        self.assertEqual(ids,{r['journal_id'] for r in rows})
        self.assertEqual(total,sum(r['debit_cents'] for r in rows))
        self.assertEqual(total,sum(r['credit_cents'] for r in rows))
        codes={a['id']:a['access_code'] for a in self.core.accounts(cid)}
        for row in rows:
            journal=next(j for j in journals if j['id']==row['journal_id'])
            other={codes[l['account_id']] for l in journal['lines'] if l['account_id']!=row['account_id']}
            self.assertEqual(next(iter(other)) if len(other)==1 else 'Diversos',row['counterpart'])
        for group in report['ledger_groups']:
            self.assertEqual([r for r in rows if r['account_id']==group['account_id']],group['rows'])
        selected=next(r['account_id'] for r in rows)
        filtered=self.core.business_report(cid,'ledger','2026-11-01','2026-11-30',account_id=selected)
        self.assertEqual([r for r in rows if r['account_id']==selected],filtered['rows'])
        self.assertEqual([],self.core.business_report(cid,'ledger','2026-10-01','2026-10-31')['rows'])
        self.assertEqual(before,self.snapshot())
        return report

    def test_individual_purchases_and_daily_sales_preserve_counterparts_and_competence(self):
        self.mode()
        incoming=[self.purchase('LEDGER-E1','0.01'),self.purchase('LEDGER-E2','10.02')]
        outgoing=[self.sale('LEDGER-S1','2.00'),self.sale('LEDGER-S2','3.00')]
        purchases=self.post('/fiscal-purchases-accounting/generate',self.direct(incoming,'ledger-in'))
        sales=self.post('/fiscal-sales-accounting/generate',self.direct(outgoing,'ledger-out'))
        self.assertEqual(2,purchases['created_count']);self.assertEqual(1,sales['created_count'])
        self.assert_ledger(self.a['id'],purchases['journals']+sales['journals'],1503)
        self.assertEqual([],self.core.business_report(self.b['id'],'ledger','2026-11-01','2026-11-30')['rows'])

    def test_global_reference_materialization_and_used_fork_preserve_ledger_identity(self):
        import test_global_account_plans as plans
        plan,_,_=plans.GlobalAccountPlanTests.publish(self);cid=self.b['id'];self.activate(cid)
        preview=self.post(f"/global-account-plans/{plan['id']}/preview",{'mode':'shared'},cid=cid)
        self.post(f"/global-account-plans/previews/{preview['id']}/confirm",{'preview_hash':preview['preview_hash'],'properties_reviewed':True,'reason':'Synthetic ledger composition'},cid=cid)
        doc=self.purchase('LEDGER-GLOBAL','10.03',cid=cid)
        payload=self.direct([doc],'ledger-global',debit='00101',credit='00102',cid=cid)
        self.assertTrue(payload['entries'][0]['debit_account_id']<0)
        result=self.post('/fiscal-purchases-accounting/generate',payload,cid=cid)
        before=self.assert_ledger(cid,result['journals'],1003)
        binding=self.client.get(self.scope('/global-account-plans',cid)).json()['binding']
        self.post('/global-account-plans/binding/detach',{'version':binding['version'],'reason':'Synthetic used fork','copy_scope':'used'},cid=cid)
        after=self.assert_ledger(cid,result['journals'],1003)
        self.assertEqual(before['rows'],after['rows'])
        self.assertTrue(self.post('/fiscal-purchases-accounting/generate',payload,cid=cid)['duplicate'])
