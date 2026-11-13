"""Shared definitions: no eager copies and minimum FK allocation at actual use."""
import base64
import json
import re
import unittest
from fastapi.testclient import TestClient
import test_core as base
import test_global_account_plans as plans
from app.module_imports import LAYOUTS


class LazyAccountRefTests(unittest.TestCase):
    setUp=base.CoreApiTests.setUp
    tearDown=base.CoreApiTests.tearDown
    create_company=base.CoreApiTests.create_company
    activate=base.CoreApiTests.activate
    scope=base.CoreApiTests.scope
    post=plans.GlobalAccountPlanTests.post
    publish=plans.GlobalAccountPlanTests.publish
    prepare=plans.GlobalAccountPlanTests.prepare
    confirm=plans.GlobalAccountPlanTests.confirm

    def adopt(self,plan=None):
        g,_,_=self.publish(plan);self.activate(self.b['id']);self.confirm(self.prepare(g['id']))
        refs={a['access_code']:a for a in self.core.accounts(self.b['id'])}
        return g,refs

    def counts(self):
        with self.core.db.read() as conn:
            return {table:conn.execute(f'SELECT COUNT(*) FROM {table} WHERE company_id=?',(self.b['id'],)).fetchone()[0]
                    for table in ('accounts','account_plan_batches','account_plan_metadata','account_plan_properties','global_account_plan_links')}

    def journal(self,refs,key='lazy-journal',**extra):
        return {'date':'2026-11-06','document':'LAZY','history':'Synthetic journal','idempotency_key':key,'lines':[
            {'account_id':refs['00101']['id'],'debit':'17.00','credit':'0.00'},
            {'account_id':refs['00102']['id'],'debit':'0.00','credit':'17.00'}],**extra}

    def test_binding_read_reports_and_export_copy_no_company_definitions(self):
        g,refs=self.adopt();before=self.counts()
        self.assertEqual({'accounts':6,'account_plan_batches':0,'account_plan_metadata':0,'account_plan_properties':0,'global_account_plan_links':0},before)
        self.assertLess(refs['00101']['id'],0)
        self.core.business_report(self.b['id'],'ledger','2026-11-01','2026-11-30',account_id=refs['00101']['id'])
        self.core.report(self.b['id'],'trial-balance','2026-11',account_id=refs['00101']['id'])
        p=self.post('/account-plans/export-preview',{'format':'native'})
        exported=self.post('/account-plans/export-confirm',{'format':'native','preview_hash':p['preview_hash'],'destination_reviewed':True})
        native=json.loads(base64.b64decode(exported['content_base64']))
        exported_accounts={a['access_code']:a for a in native['accounts']}
        self.assertEqual(plans.synthetic_plan()['accounts'][1],exported_accounts['00101'])
        self.assertEqual(plans.synthetic_plan()['accounts'][2],exported_accounts['00102'])
        original=self.client.get(self.scope(f"/global-account-plans/{g['id']}/original",self.b['id']))
        self.assertEqual(200,original.status_code)
        self.assertEqual(3,len(json.loads(original.content)['accounts']))
        self.assertEqual(before,self.counts())

    def test_lazy_journal_alias_retry_filters_and_own_fork_keep_used_ids(self):
        _,refs=self.adopt();payload=self.journal(refs)
        j=self.post('/journals',payload,201);self.assertTrue(self.post('/journals',payload,201)['duplicate'])
        current={a['access_code']:a for a in self.core.accounts(self.b['id'])}
        used={current[k]['id'] for k in ('00101','00102')};self.assertTrue(all(i>0 for i in used))
        self.assertEqual(8,self.counts()['accounts']);self.assertEqual(0,self.counts()['account_plan_metadata'])
        with self.core.db.read() as conn:
            for row in conn.execute('SELECT * FROM accounts WHERE shared_entry_id IS NOT NULL'):
                self.assertIsNone(row['name']);self.assertIsNone(row['classifier']);self.assertIsNone(row['nature']);self.assertIsNone(row['prosoft_code'])
        for report in (self.core.report(self.b['id'],'ledger','2026-11',account_id=refs['00101']['id']),
                       self.core.business_report(self.b['id'],'ledger','2026-11-01','2026-11-30',account_id=refs['00101']['id'])):
            self.assertEqual(1,len(report['rows']));self.assertEqual(current['00101']['id'],report['rows'][0]['account_id'])
        maps={str(refs[k]['id']):{'code':refs[k]['access_code'],'confirmed':True,'third_mode':'none'} for k in ('00101','00102')}
        prosoft=self.post('/prosoft/preview',{'period':'2026-11','company_code':'0001','accounts':maps,'centers':{}})
        self.assertEqual(1,prosoft['manifest']['journals'])
        binding=self.client.get(self.scope('/global-account-plans',self.b['id'])).json()['binding']
        self.post('/global-account-plans/binding/detach',{'version':binding['version'],'reason':'Own copy explicitly requested'})
        after={a['access_code']:a for a in self.core.accounts(self.b['id'])}
        self.assertEqual(used,{after[k]['id'] for k in ('00101','00102')})
        self.assertEqual(9,self.counts()['accounts']);self.assertEqual(3,self.counts()['account_plan_metadata'])
        self.assertTrue(self.post('/journals',payload,201)['duplicate'])
        reversed_j=self.post(f"/journals/{j['id']}/reverse",{'date':'2026-11-07','reason':'Synthetic reversal','idempotency_key':'lazy-reversal'})
        self.assertEqual(used,{line['account_id'] for line in reversed_j['lines']})

    def test_model_refs_materialize_only_selected_accounts_and_survive_own_copy(self):
        _,refs=self.adopt()
        model={'code':'LAZY','name':'Synthetic shared accounts model','data':{'debit_account_id':refs['00101']['id'],'credit_account_id':refs['00102']['id'],
            'valid_from':'2026-01-01','status':'validated','history':'Synthetic history','source':'Synthetic source','responsible':'Synthetic operator'}}
        saved=self.post('/masters/accounting_model',model,201)
        self.assertGreater(saved['data']['debit_account_id'],0);self.assertGreater(saved['data']['credit_account_id'],0)
        self.assertEqual(8,self.counts()['accounts'])
        bad=json.loads(json.dumps(model));bad['code']='SAME';bad['data']['credit_account_id']=saved['data']['debit_account_id']
        self.post('/masters/accounting_model',bad,400)
        binding=self.client.get(self.scope('/global-account-plans',self.b['id'])).json()['binding']
        self.post('/global-account-plans/binding/detach',{'version':binding['version'],'reason':'Own fork for adaptation'})
        current=self.client.get(self.scope('/masters/accounting_model',self.b['id'])).json()
        self.assertEqual(saved['data'],next(m for m in current if m['id']==saved['id'])['data'])

    def test_csv_preview_keeps_virtual_alias_after_other_use_without_allocation(self):
        _,refs=self.adopt()
        lines='CSV-LAZY;2026-11-06;SYN;Synthetic CSV;00101;17.00;0;\nCSV-LAZY;2026-11-06;SYN;Synthetic CSV;00102;0;17.00;\n'
        raw=(';'.join(LAYOUTS['journals-v1']['fields'])+'\n'+lines).encode()
        preview=self.post('/module-imports/preview',{'module':'accounting','layout':'journals-v1','year':2026,'filename':'synthetic.csv','content_base64':base64.b64encode(raw).decode()})
        self.assertEqual(6,self.counts()['accounts']);self.assertTrue(all(line['account_id']<0 for line in preview['records'][0]['payload']['lines']))
        local=self.journal(refs,'materialize-one');local['lines'][1]['account_id']=next(a['id'] for a in self.core.accounts(self.b['id']) if a['access_code']=='5')
        self.post('/journals',local,201);self.assertEqual(7,self.counts()['accounts'])
        result=self.post(f"/module-imports/{preview['id']}/confirm",{'module':'accounting','fingerprint':preview['fingerprint'],'selected':['0']})
        self.assertEqual(1,len(result['written']));self.assertEqual(8,self.counts()['accounts'])

    def test_forged_cross_plan_ref_closed_period_unbalanced_and_cost_center_roll_back(self):
        first,_=self.adopt()
        before=self.counts()
        self.activate(self.a['id']);other=json.loads(json.dumps(plans.synthetic_plan()));other['accounts'][1]['access_code']='00991'
        second,_,_=self.publish(other)
        with self.core.db.read() as conn:forged=-conn.execute('SELECT id FROM global_account_entries WHERE global_plan_id=? AND access_code=?',(second['id'],'00991')).fetchone()[0]
        self.activate(self.b['id']);refs={a['access_code']:a for a in self.core.accounts(self.b['id'])}
        payload=self.journal(refs);payload['lines'][0]['account_id']=forged
        self.post('/journals',payload,404);self.assertEqual(before,self.counts())
        payload=self.journal(refs);payload['lines'][0]['debit']='18.00'
        self.post('/journals',payload,400);self.assertEqual(before,self.counts())
        self.post('/periods/close',{'period':'2026-11','module':'accounting','reason':'Synthetic lock'})
        self.post('/journals',self.journal(refs),409);self.assertEqual(before,self.counts())
        self.post('/periods/reopen',{'period':'2026-11','module':'accounting','reason':'Synthetic reopen'})
        # New shared version requires a center on one otherwise unused account.
        self.activate(self.a['id']);plan=plans.synthetic_plan();plan['accounts'][1]['requires_cost_center']=True
        third,_,_=self.publish(plan);self.activate(self.b['id']);self.confirm(self.prepare(third['id']))
        refs={a['access_code']:a for a in self.core.accounts(self.b['id'])}
        self.post('/journals',self.journal(refs),400);self.assertEqual(6,self.counts()['accounts'])

    def test_journal_only_user_can_allocate_technical_refs_without_account_create(self):
        _,refs=self.adopt()
        permissions=[{'company_id':self.b['id'],'routine':routine,'action':action,'effect':'allow'} for routine,action in [('accounting.accounts','read'),('accounting.journals','read'),('accounting.journals','create')]]
        self.client.post('/api/users',json={'username':'journal-only','password':'Senha-sintetica-2026','role':'custom','company_ids':[self.b['id']],'permissions':permissions})
        with TestClient(self.app) as limited:
            session=limited.post('/api/login',json={'username':'journal-only','password':'Senha-sintetica-2026'}).json();limited.headers['X-CSRF-Token']=session['csrf_token']
            self.activate(self.b['id'],client=limited)
            r=limited.post(self.scope('/journals',self.b['id']),json=self.journal(refs))
            self.assertEqual(201,r.status_code,r.text)
            self.assertEqual(403,limited.post(self.scope('/accounts',self.b['id']),json={'access_code':'X','classifier':'1','name':'No','nature':'debit'}).status_code)
        self.assertEqual(8,self.counts()['accounts'])

    def test_opening_financial_settlement_center_and_reversal_use_same_minimum_refs(self):
        plan=plans.synthetic_plan();plan['accounts'][1]['requires_cost_center']=True
        _,refs=self.adopt(plan)
        center=self.post('/cost-centers',{'code':'LAZY','name':'Synthetic center'},201)
        lines=self.journal(refs)['lines'];lines[0]['cost_center_id']=center['id']
        opening=self.post('/opening-balances',{'date':'2026-11-01','history':'Synthetic opening','lines':lines},201)
        title=self.post('/titles',{'kind':'payable','description':'Synthetic payable','partner_name':'Synthetic partner','document':'P-1','issue_date':'2026-11-01','due_date':'2026-11-07','amount':'17.00'},201)
        settlement={'date':'2026-11-07','amount':'17.00','reason':'Synthetic settlement','idempotency_key':'lazy-settle','version':title['version'],'lines':lines}
        paid=self.post(f"/titles/{title['id']}/settle",settlement)
        self.assertTrue(self.post(f"/titles/{title['id']}/settle",settlement)['duplicate'])
        allocated={a['access_code']:a['id'] for a in self.core.accounts(self.b['id'])}
        updated_lines=[dict(line,account_id=allocated[refs['00101']['access_code'] if i==0 else refs['00102']['access_code']]) for i,line in enumerate(lines)]
        self.assertTrue(self.post(f"/titles/{title['id']}/settle",settlement|{'lines':updated_lines})['duplicate'])
        used={line['account_id'] for line in opening['lines']}
        self.assertEqual(used,{line['account_id'] for line in paid['journal']['lines']})
        self.assertEqual(center['id'],paid['journal']['lines'][0]['cost_center_id'])
        self.post(f"/settlements/{paid['settlement']['id']}/reverse",{'date':'2026-11-08','reason':'Synthetic reversal','idempotency_key':'lazy-settle-reverse'})
        ledger=self.core.business_report(self.b['id'],'ledger','2026-11-02','2026-11-30',account_id=refs['00101']['id'])
        self.assertEqual(1700,ledger['rows'][0]['opening_cents']);self.assertEqual(1700,ledger['rows'][-1]['balance_cents'])
        self.assertEqual(8,self.counts()['accounts']);self.assertEqual(0,self.counts()['account_plan_metadata'])
        mappings={str(refs[k]['id']):{'code':refs[k]['access_code'],'confirmed':True,'third_mode':'none'} for k in ('00101','00102')}
        payload={'period':'2026-11','company_code':'0001','accounts':mappings,'centers':{str(center['id']):{'code':'00001','confirmed':True}}}
        preview=self.post('/prosoft/preview',payload)
        exported=self.post('/prosoft/confirm',payload|{'preview_hash':preview['preview_hash'],'destination_reviewed':True,'allow_ascii':True})
        self.assertEqual(3,exported['manifest']['journals'])
        with self.core.db.read() as conn:self.assertEqual([],list(conn.execute('PRAGMA foreign_key_check')))


if __name__=='__main__':unittest.main()
