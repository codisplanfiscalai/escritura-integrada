"""Partial own forks retain used identities, hierarchy and versioned aliases."""
import json
import unittest
import test_core as base
import test_global_account_plans as plans
import test_lazy_account_refs as lazy


def hierarchy():
    plan=plans.synthetic_plan();prototype=plan['accounts'][1]
    layout=[('30000','1',False),('30001','1.1',False),('30002','1.1.01',False),
            ('30003','1.1.01.001',True),('30004','1.1.01.001',True),('30005','1.1.01.002',True),
            ('30006','2',False),('30007','2.1.01.001',True)]
    plan['accounts']=[dict(prototype,access_code=code,prosoft_code=code,classifier=classifier,analytical=analytical,name='Synthetic '+code,prosoft={}) for code,classifier,analytical in layout]
    return plan


class GlobalForkScopeTests(unittest.TestCase):
    setUp=base.CoreApiTests.setUp
    tearDown=base.CoreApiTests.tearDown
    create_company=base.CoreApiTests.create_company
    activate=base.CoreApiTests.activate
    scope=base.CoreApiTests.scope
    post=plans.GlobalAccountPlanTests.post
    publish=plans.GlobalAccountPlanTests.publish
    prepare=plans.GlobalAccountPlanTests.prepare
    confirm=plans.GlobalAccountPlanTests.confirm
    adopt=lazy.LazyAccountRefTests.adopt
    counts=lazy.LazyAccountRefTests.counts
    journal=lazy.LazyAccountRefTests.journal

    def test_used_fork_includes_existing_parents_not_unused_twins_or_other_branches(self):
        g,refs=self.adopt(hierarchy())
        payload=self.journal({'00101':refs['30003'],'00102':refs['30005']})
        j=self.post('/journals',payload,201);used_ids={line['account_id'] for line in j['lines']}
        p=self.post(f"/global-account-plans/{g['id']}/preview",{'mode':'own','copy_scope':'used'})
        self.assertEqual((2,3,5),(p['used_accounts'],p['parents_included'],p['record_count']))
        self.assertEqual([],p['missing_parent_classifiers'])
        r=self.confirm(p);self.assertEqual('used',r['copy_scope']);self.assertEqual(3,r['created'])
        own={a['access_code']:a for a in self.core.accounts(self.b['id'])}
        self.assertEqual({'30000','30001','30002','30003','30005'},{a for a in own if a.startswith('300')})
        self.assertEqual(used_ids,{own[k]['id'] for k in ('30003','30005')})
        self.assertNotIn('30004',own,'unused subaccount sharing a classifier is not a used identity')
        native=self.client.get(self.scope(f"/account-plans/{r['batch_id']}/native",self.b['id'])).json()
        self.assertEqual(5,len(native['accounts']))
        with self.core.db.read() as conn:
            batch=conn.execute('SELECT * FROM account_plan_batches WHERE id=?',(r['batch_id'],)).fetchone()
            self.assertEqual(5,len(json.loads(batch['original'])['accounts']))
            self.assertEqual(8,conn.execute('SELECT COUNT(*) FROM global_account_entries WHERE global_plan_id=?',(g['id'],)).fetchone()[0])
            self.assertEqual([],list(conn.execute('PRAGMA foreign_key_check')))
        self.assertTrue(self.post('/journals',payload,201)['duplicate'])

    def test_used_detach_with_no_use_copies_zero_accounts_and_no_full_original(self):
        g,_=self.adopt(hierarchy())
        binding=self.client.get(self.scope('/global-account-plans',self.b['id'])).json()['binding']
        fork=self.post('/global-account-plans/binding/detach',{'version':binding['version'],'reason':'Only used accounts requested','copy_scope':'used'})
        self.assertEqual(('own','used'),(fork['mode'],fork['copy_scope']))
        self.assertEqual(6,self.counts()['accounts']);self.assertEqual(0,self.counts()['account_plan_metadata'])
        with self.core.db.read() as conn:
            batch=conn.execute('SELECT original FROM account_plan_batches WHERE company_id=?',(self.b['id'],)).fetchone()
            self.assertEqual([],json.loads(batch['original'])['accounts'])

    def test_used_preview_goes_stale_when_another_account_is_used(self):
        g,refs=self.adopt(hierarchy())
        p=self.post(f"/global-account-plans/{g['id']}/preview",{'mode':'own','copy_scope':'used'})
        self.post('/journals',self.journal({'00101':refs['30003'],'00102':refs['30005']}),201)
        self.confirm(p,409)

    def test_version_alias_b_remains_valid_after_c_and_prosoft_uses_historical_alias(self):
        _,refs_a=self.adopt();self.post('/journals',self.journal(refs_a,'use-A'),201)
        self.activate(self.a['id']);b,_,_=self.publish();self.activate(self.b['id']);self.confirm(self.prepare(b['id']))
        with self.core.db.read() as conn:
            b_ids={r['access_code']:-r['id'] for r in conn.execute('SELECT id,access_code FROM global_account_entries WHERE global_plan_id=?',(b['id'],))}
        refs_b={k:dict(v,id=b_ids[k]) for k,v in refs_a.items() if k in b_ids}
        payload=self.journal(refs_b,'use-B');created=self.post('/journals',payload,201)
        self.activate(self.a['id']);c,_,_=self.publish();self.activate(self.b['id']);self.confirm(self.prepare(c['id']))
        retry=self.post('/journals',payload,201);self.assertTrue(retry['duplicate']);self.assertEqual(created['id'],retry['id'])
        mapping={str(b_ids[k]):{'code':k,'confirmed':True,'third_mode':'none'} for k in ('00101','00102')}
        p=self.post('/prosoft/preview',{'period':'2026-11','company_code':'0001','accounts':mapping,'centers':{}})
        self.assertEqual(2,p['manifest']['journals'])

    def test_alias_to_preexisting_local_survives_access_rename_and_reuse(self):
        plan=plans.synthetic_plan()
        for a in plan['accounts']:a['prosoft']={};a.pop('synthetic_metadata',None)
        g,_,_=self.publish(plan);self.activate(self.b['id'])
        local=self.post('/accounts',plan['accounts'][1],201)
        self.confirm(self.prepare(g['id']))
        with self.core.db.read() as conn:aliases={r['access_code']:-r['id'] for r in conn.execute('SELECT id,access_code FROM global_account_entries WHERE global_plan_id=?',(g['id'],))}
        refs={a['access_code']:a for a in self.core.accounts(self.b['id'])}
        refs['00101']=dict(refs['00101'],id=aliases['00101'])
        self.post('/journals',self.journal(refs,'before-own'),201)
        binding=self.client.get(self.scope('/global-account-plans',self.b['id'])).json()['binding']
        self.post('/global-account-plans/binding/detach',{'version':binding['version'],'reason':'Own adaptation','copy_scope':'all'})
        account=next(a for a in self.core.accounts(self.b['id']) if a['id']==local['id'])
        r=self.client.put(self.scope('/accounts/'+str(local['id']),self.b['id']),json=account|{'access_code':'ADAPTED'})
        self.assertEqual(200,r.status_code,r.text)
        replacement=self.post('/accounts',plan['accounts'][1]|{'name':'Different local identity'},201)
        j=self.post('/journals',self.journal(refs,'after-reuse'),201)
        debit=next(line for line in j['lines'] if line['debit_cents'])
        self.assertEqual(local['id'],debit['account_id']);self.assertNotEqual(replacement['id'],debit['account_id']);self.assertEqual('ADAPTED',debit['access_code'])


if __name__=='__main__':unittest.main()
