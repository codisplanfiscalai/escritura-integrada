import unittest
import test_core as base
import test_global_account_plans as globals_test


class PlanManagerTests(unittest.TestCase):
    setUp=base.CoreApiTests.setUp
    tearDown=base.CoreApiTests.tearDown
    create_company=base.CoreApiTests.create_company
    activate=base.CoreApiTests.activate
    scope=base.CoreApiTests.scope
    post=globals_test.GlobalAccountPlanTests.post
    publish=globals_test.GlobalAccountPlanTests.publish
    prepare=globals_test.GlobalAccountPlanTests.prepare
    confirm=globals_test.GlobalAccountPlanTests.confirm

    def manager(self,suffix='',cid=None):return self.scope('/accounting-settings/plan-manager'+suffix,cid)

    def create(self,body=None):
        r=self.client.post(self.manager('/drafts'),json=body or {'name':'Plano XXX'})
        self.assertEqual(200,r.status_code,r.text);return r.json()

    def save_account(self,draft,account,previous=None):
        r=self.client.post(self.manager('/drafts/'+draft['id']+'/accounts'),json={'version':draft['version'],'account':account,**({'previous_access_code':previous} if previous else {})})
        self.assertEqual(200,r.status_code,r.text);return r.json()

    def test_create_manual_plan_accounts_subaccounts_and_retry_safe_save(self):
        d=self.create()
        self.assertEqual([],d['accounts'])
        a={'access_code':'100','classifier':'1','name':'Ativo','nature':'debit','analytical':False}
        d=self.save_account(d,a)
        d=self.save_account(d,a|{'access_code':'101','classifier':'1.1','name':'Disponibilidades','analytical':True})
        self.assertEqual(2,d['record_count'])
        p=self.client.post(self.manager('/drafts/'+d['id']+'/publish'),json={'version':d['version']})
        self.assertEqual(200,p.status_code,p.text);gid=p.json()['id']
        retry=self.client.post(self.manager('/drafts/'+d['id']+'/publish'),json={'version':d['version']})
        self.assertEqual(gid,retry.json()['id']);self.assertTrue(retry.json()['duplicate'])
        self.assertEqual(0,p.json()['companies_updated'])
        self.assertEqual(409,self.client.post(self.manager('/drafts/'+d['id']+'/accounts'),json={'version':d['version'],'account':a}).status_code)
        self.assertEqual(2,self.core.global_account_plan(self.a['id'],gid)['record_count'])

    def test_edit_global_creates_new_version_without_rewriting_company_or_journal(self):
        plan,_,_=self.publish();self.confirm(self.prepare(plan['id']))
        accounts=self.core.accounts(self.a['id']);one=next(a for a in accounts if a['access_code']=='00101');two=next(a for a in accounts if a['access_code']=='00102')
        r=self.client.post(self.scope('/journals'),json={'date':'2026-11-06','document':'ORIGINAL','history':'Preservar','idempotency_key':'manager-preserve','lines':[{'account_id':one['id'],'debit':'10','credit':'0'},{'account_id':two['id'],'debit':'0','credit':'10'}]})
        self.assertEqual(201,r.status_code,r.text);journal=r.json()
        d=self.create({'name':'Plano XXX atualizado','source_global_id':plan['id']})
        self.assertEqual(self.a['id'],d['companies_on_source'][0]['id']);self.assertEqual(2,d['companies_on_source'][0]['journal_lines'])
        old=next(a for a in d['accounts'] if a['access_code']=='00101')
        d=self.save_account(d,{'name':'Nova descrição'},'00101')
        edited=next(a for a in d['accounts'] if a['access_code']=='00101')
        self.assertEqual(old['prosoft'],edited['prosoft']);self.assertEqual(old['synthetic_metadata'],edited['synthetic_metadata'])
        saved=self.client.post(self.manager('/drafts/'+d['id']+'/publish'),json={'version':d['version']}).json()
        self.assertNotEqual(plan['id'],saved['id']);self.assertEqual(plan['id'],saved['parent_id'])
        self.assertEqual(self.a['id'],saved['companies_on_previous'][0]['id']);self.assertEqual(0,saved['companies_updated'])
        self.assertEqual(plan['id'],self.core.global_account_plans(self.a['id'])['binding']['global_plan_id'])
        self.assertEqual(one['name'],next(a for a in self.core.accounts(self.a['id']) if a['access_code']==one['access_code'])['name'])
        self.assertEqual(journal['lines'],self.core.journals(self.a['id'])[0]['lines'])

    def test_optimistic_concurrency_duplicate_codes_and_delete_only_draft(self):
        d=self.create();a={'access_code':'1','classifier':'1','name':'Sintética','nature':'debit','analytical':False}
        newer=self.save_account(d,a)
        stale=self.client.post(self.manager('/drafts/'+d['id']+'/accounts'),json={'version':d['version'],'account':a|{'access_code':'2'}})
        self.assertEqual(409,stale.status_code)
        duplicate=self.client.post(self.manager('/drafts/'+d['id']+'/accounts'),json={'version':newer['version'],'account':a})
        self.assertEqual(409,duplicate.status_code)
        deleted=self.client.delete(self.manager('/drafts/'+d['id']+'/accounts')+'?access_code=1&version='+str(newer['version']))
        self.assertEqual(200,deleted.status_code,deleted.text);self.assertEqual([],deleted.json()['accounts'])
        empty=self.client.post(self.manager('/drafts/'+d['id']+'/publish'),json={'version':deleted.json()['version']})
        self.assertEqual(400,empty.status_code)

    def test_inactive_company_administration_and_csrf(self):
        before=self.client.get('/api/session').json()['active_company_id']
        r=self.client.post(self.manager('/drafts',self.b['id']),json={'name':'Outro plano'})
        self.assertEqual(200,r.status_code,r.text)
        self.assertEqual(before,self.client.get('/api/session').json()['active_company_id'])
        self.assertEqual(403,self.client.post(self.manager('/drafts'),json={'name':'Negado'},headers={'X-CSRF-Token':''}).status_code)

    def test_nonadmin_cannot_read_private_drafts_or_mutate_globals(self):
        from fastapi.testclient import TestClient
        self.create()
        with self.core.db.transaction() as conn:
            uid=conn.execute("INSERT INTO users(username,password_hash,created_at,role,active) VALUES(?,?,?,'operator',1)",('plan-reader',self.core._password_hash('Synthetic-password-999!'),'2026-11-01')).lastrowid
            conn.execute('INSERT INTO user_companies VALUES(?,?)',(uid,self.a['id']))
            conn.execute("INSERT INTO user_permissions VALUES(?,?,'accounting.accounts','read','allow')",(uid,self.a['id']))
        c=TestClient(self.app)
        try:
            login=c.post('/api/login',json={'username':'plan-reader','password':'Synthetic-password-999!'});c.headers['X-CSRF-Token']=login.json()['csrf_token']
            listing=c.get(self.manager());self.assertEqual(200,listing.status_code,listing.text);self.assertFalse(listing.json()['can_manage']);self.assertEqual([],listing.json()['drafts'])
            self.assertEqual(403,c.post(self.manager('/drafts'),json={'name':'Não permitido'}).status_code)
        finally:c.close()

    def test_access_identity_with_slash_is_editable_and_removable(self):
        d=self.create();d=self.save_account(d,{'access_code':'A/1','classifier':'1.1','name':'Identidade textual','nature':'debit','analytical':True})
        r=self.client.delete(self.manager('/drafts/'+d['id']+'/accounts'),params={'access_code':'A/1','version':d['version']})
        self.assertEqual(200,r.status_code,r.text);self.assertEqual(0,r.json()['record_count'])

    def test_invalid_mask_rejected_without_new_global_or_draft_mutation(self):
        d=self.create();r=self.client.put(self.manager('/drafts/'+d['id']),json={'version':d['version'],'name':d['name'],'description':'','properties':d['properties']|{'mask':''}})
        self.assertEqual(400,r.status_code,r.text)
        loaded=self.client.get(self.manager('/drafts/'+d['id'])).json();self.assertEqual(d['version'],loaded['version']);self.assertEqual(d['properties'],loaded['properties'])
    def test_parallel_draft_edits_accept_only_one_revision(self):
        from concurrent.futures import ThreadPoolExecutor
        d=self.create()
        def edit(code):return self.client.post(self.manager('/drafts/'+d['id']+'/accounts'),json={'version':d['version'],'account':{'access_code':code,'classifier':'1','name':'Concorrente','nature':'debit','analytical':True}}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(edit,['A','B']))
        self.assertEqual([200,409],sorted(statuses))
        latest=self.client.get(self.manager('/drafts/'+d['id'])).json();self.assertEqual(1,latest['record_count']);self.assertEqual(2,latest['version'])

    def test_save_global_is_atomic_when_entry_insert_fails(self):
        d=self.create();d=self.save_account(d,{'access_code':'X','classifier':'1','name':'Falha sintética','nature':'debit','analytical':True})
        with self.core.db.transaction() as conn:
            before=conn.execute('SELECT COUNT(*) FROM account_plan_batches').fetchone()[0]
            conn.execute("CREATE TRIGGER synthetic_manager_abort BEFORE INSERT ON global_account_entries BEGIN SELECT RAISE(ABORT,'synthetic manager failure'); END")
        r=self.client.post(self.manager('/drafts/'+d['id']+'/publish'),json={'version':d['version']})
        self.assertEqual(409,r.status_code,r.text)
        with self.core.db.read() as conn:
            self.assertEqual(before,conn.execute('SELECT COUNT(*) FROM account_plan_batches').fetchone()[0]);self.assertEqual(0,conn.execute('SELECT COUNT(*) FROM global_account_plans').fetchone()[0])
        self.assertNotIn('published_id',self.client.get(self.manager('/drafts/'+d['id'])).json())
