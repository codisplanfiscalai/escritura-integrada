import json
import unittest
import test_core as base
import test_global_account_plans as global_tests


class CompanyAccountingSettingsTests(unittest.TestCase):
    setUp = base.CoreApiTests.setUp
    tearDown = base.CoreApiTests.tearDown
    create_company = base.CoreApiTests.create_company
    activate = base.CoreApiTests.activate
    scope = base.CoreApiTests.scope
    journal = base.CoreApiTests.journal
    post = global_tests.GlobalAccountPlanTests.post
    publish = global_tests.GlobalAccountPlanTests.publish
    # Reuse only fixtures and synthetic publishing helpers, not inherited tests.
    def test_parameters_of_inactive_company_preserve_context_and_movements(self):
        cid=self.b['id']
        center=self.core.save_cost_center(cid, {'code':'CFG','name':'Centro B'},'teste')
        before=self.client.get('/api/session').json()['active_company_id']
        path=self.scope('/accounting-settings',cid)
        r=self.client.get(path);self.assertEqual(200,r.status_code,r.text)
        self.assertEqual(0,r.json()['version']);self.assertEqual('',r.json()['settings']['default_history'])
        body={'version':0,'settings':{'default_history':'Histórico B','default_cost_center_id':center['id']}}
        saved=self.client.put(path,json=body);self.assertEqual(200,saved.status_code,saved.text)
        self.assertEqual(1,saved.json()['version'])
        self.assertEqual(409,self.client.put(path,json=body).status_code)
        self.assertEqual(before,self.client.get('/api/session').json()['active_company_id'])
        self.assertEqual('',self.client.get(self.scope('/accounting-entry-defaults')).json()['settings']['default_history'])
        self.activate(cid)
        self.assertEqual('Histórico B',self.client.get(self.scope('/accounting-entry-defaults',cid)).json()['settings']['default_history'])
        self.assertEqual([],self.core.journals(cid))

    def test_global_plan_selected_from_company_parameters_no_duplicate_definition(self):
        plan,_,_=self.publish()
        cid=self.b['id'];before=self.client.get('/api/session').json()['active_company_id']
        with self.core.db.read() as conn:count=conn.execute('SELECT COUNT(*) FROM accounts WHERE company_id=?',(cid,)).fetchone()[0]
        prefix=self.scope('/accounting-settings',cid)
        p=self.client.post(prefix+f"/plans/{plan['id']}/preview",json={'mode':'shared'});self.assertEqual(200,p.status_code,p.text)
        r=self.client.post(prefix+f"/previews/{p.json()['id']}/confirm",json={'preview_hash':p.json()['preview_hash'],'properties_reviewed':True,'reason':'Adoção em empresa inativa'})
        self.assertEqual(200,r.status_code,r.text)
        self.assertEqual(before,self.client.get('/api/session').json()['active_company_id'])
        summary=self.client.get(prefix).json();self.assertEqual(plan['id'],summary['binding']['global_plan_id'])
        self.assertEqual('shared',summary['binding']['mode'])
        with self.core.db.read() as conn:self.assertEqual(count,conn.execute('SELECT COUNT(*) FROM accounts WHERE company_id=?',(cid,)).fetchone()[0])
        detached=self.client.post(prefix+'/detach',json={'version':summary['binding']['version'],'copy_scope':'used','reason':'Usar plano próprio'})
        self.assertEqual(200,detached.status_code,detached.text);self.assertEqual('own',detached.json()['mode'])

    def test_defaults_reject_cross_company_center_and_csrf(self):
        center=self.core.save_cost_center(self.a['id'],{'code':'A','name':'A'},'teste')
        url=self.scope('/accounting-settings',self.b['id'])
        body={'version':0,'settings':{'default_history':'Teste','default_cost_center_id':center['id']}}
        self.assertEqual(400,self.client.put(url,json=body).status_code)
        self.assertEqual(403,self.client.put(url,json=body,headers={'X-CSRF-Token':''}).status_code)
        self.assertEqual(0,self.client.get(url).json()['version'])

    def test_movement_routes_still_require_active_company(self):
        r=self.client.post(self.scope('/journals',self.b['id']),json=self.journal())
        self.assertEqual(409,r.status_code,r.text)

    def test_setting_history_is_suggestion_does_not_override_api_journal(self):
        self.client.put(self.scope('/accounting-settings'),json={'version':0,'settings':{'default_history':'Padrão','default_cost_center_id':None}})
        r=self.client.post(self.scope('/journals'),json=self.journal());self.assertEqual(201,r.status_code,r.text)
        self.assertEqual('Partida sintética de teste',r.json()['history'])


    def operator_client(self, cid):
        from fastapi.testclient import TestClient
        with self.core.db.transaction() as conn:
            uid=conn.execute("INSERT INTO users(username,password_hash,created_at,role,active) VALUES(?,?,?,'operator',1)",('accountant',self.core._password_hash('Synthetic-password-456!'),'2026-11-01')).lastrowid
            conn.execute('INSERT INTO user_companies(user_id,company_id) VALUES(?,?)',(uid,cid))
            for action in ['read','edit','create']:
                conn.execute("INSERT INTO user_permissions VALUES(?,?,'accounting.accounts',?,'allow')",(uid,cid,action))
        client=TestClient(self.app)
        r=client.post('/api/login',json={'username':'accountant','password':'Synthetic-password-456!'})
        self.assertEqual(200,r.status_code,r.text);client.headers['X-CSRF-Token']=r.json()['csrf_token']
        return client,uid

    def test_permissions_target_company_and_revocation_before_confirm(self):
        plan,_,_=self.publish();cid=self.b['id'];client,uid=self.operator_client(cid)
        try:
            prefix=self.scope('/accounting-settings',cid)
            self.assertEqual(200,client.get(prefix).status_code)
            self.assertEqual(403,client.get(self.scope('/accounting-settings',self.a['id'])).status_code)
            p=client.post(prefix+f"/plans/{plan['id']}/preview",json={'mode':'shared'})
            self.assertEqual(200,p.status_code,p.text)
            with self.core.db.transaction() as conn:conn.execute("UPDATE user_permissions SET effect='deny' WHERE user_id=? AND action='create'",(uid,))
            r=client.post(prefix+f"/previews/{p.json()['id']}/confirm",json={'preview_hash':p.json()['preview_hash'],'properties_reviewed':True,'reason':'Conferido'})
            self.assertEqual(403,r.status_code,r.text)
            with self.core.db.read() as conn:self.assertIsNone(conn.execute('SELECT 1 FROM company_account_plan_bindings WHERE company_id=?',(cid,)).fetchone())
        finally:client.close()

    def test_inactive_default_center_not_suggested_and_data_remains_saved(self):
        center=self.core.save_cost_center(self.a['id'],{'code':'X','name':'X'},'teste')
        url=self.scope('/accounting-settings')
        body={'version':0,'settings':{'default_history':'Padrão','default_cost_center_id':center['id']}}
        self.assertEqual(200,self.client.put(url,json=body).status_code)
        with self.core.db.transaction() as conn:conn.execute('UPDATE cost_centers SET active=0 WHERE id=?',(center['id'],))
        self.assertIsNone(self.client.get(self.scope('/accounting-entry-defaults')).json()['settings']['default_cost_center_id'])
        self.assertEqual(center['id'],self.client.get(url).json()['settings']['default_cost_center_id'])
