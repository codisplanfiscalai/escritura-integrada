"""Isolamento, precedência real, competências e efeitos indiretos via HTTP."""
import unittest
from fastapi.testclient import TestClient
import test_core as base
from app.core import DomainError, digest
from app.db import request_context, ContextConflict


class ManagementTests(unittest.TestCase):
    setUp=base.CoreApiTests.setUp
    tearDown=base.CoreApiTests.tearDown
    scope=base.CoreApiTests.scope
    activate=base.CoreApiTests.activate
    create_company=base.CoreApiTests.create_company
    journal=base.CoreApiTests.journal
    document=base.CoreApiTests.document
    title=base.CoreApiTests.title

    def permission(self,cid,routine='fiscal.*',action='*',effect='allow'):
        return {'company_id':cid,'routine':routine,'action':action,'effect':effect}

    def user(self,name='operador',**extra):
        r=self.client.post('/api/users',json={'username':name,'password':'Senha-sintetica-2026','role':'custom',**extra})
        self.assertEqual(201,r.status_code,r.text);return r.json()

    def login_user(self,user):
        c=TestClient(self.app);r=c.post('/api/login',json={'username':user['username'],'password':'Senha-sintetica-2026'})
        self.assertEqual(200,r.status_code,r.text);c.headers['X-CSRF-Token']=r.json()['csrf_token'];return c

    def group(self,name='Fiscal',**extra):
        r=self.client.post('/api/groups',json={'name':name,'company_ids':[self.a['id']],**extra})
        self.assertEqual(201,r.status_code,r.text);return r.json()

    def context(self,c,cid,module='fiscal',p='2026-11',status=200):
        body={'company_id':cid,'module':module}
        if p:body['period']=p
        r=c.post('/api/context',json=body);self.assertEqual(status,r.status_code,r.text);return r.json()

    def test_group_company_scope_and_backend_actions(self):
        u=self.user();g=self.group(user_ids=[u['id']],permissions=[self.permission(self.a['id'],action='read')])
        c=self.login_user(u);self.context(c,self.a['id'])
        self.assertEqual([self.a['id']],[x['id'] for x in c.get('/api/companies').json()])
        self.assertEqual(200,c.get(self.scope('/documents')).status_code)
        self.assertEqual(403,c.post(self.scope('/documents'),json=self.document()).status_code)
        self.context(c,self.b['id'],status=403)
        self.assertEqual(403,c.get(self.scope('/documents',self.b['id'])).status_code)
        self.assertEqual(403,c.get('/api/groups').status_code)
        e=self.client.get(f"/api/users/{u['id']}/effective").json()
        self.assertTrue(e['companies'][0]['allowed']);self.assertIn('Grupo: Fiscal',e['companies'][0]['origins'])

    def test_individual_allow_overrides_group_deny_and_individual_deny_wins(self):
        u=self.user();self.group(user_ids=[u['id']],permissions=[self.permission(self.a['id']),self.permission(self.a['id'],'fiscal.documents','create','deny')])
        u=next(x for x in self.core.users() if x['id']==u['id'])
        u=self.core.save_user(u|{'permissions':[self.permission(self.a['id'],'fiscal.documents','create')]},'admin',u['id'])
        c=self.login_user(u);self.context(c,self.a['id'])
        self.assertEqual(201,c.post(self.scope('/documents'),json=self.document()).status_code)
        u=self.core.save_user(u|{'permissions':[self.permission(self.a['id'],'fiscal.documents','*','deny')]},'admin',u['id'])
        self.assertEqual(401,c.get(self.scope('/documents')).status_code)
        c=self.login_user(u);self.context(c,self.a['id'])
        self.assertEqual(403,c.get(self.scope('/documents')).status_code)

    def test_company_block_overrides_all_group_grants(self):
        u=self.user(company_access=[{'company_id':self.a['id'],'effect':'deny'}]);self.group(user_ids=[u['id']],permissions=[self.permission(self.a['id'])])
        c=self.login_user(u);self.assertEqual([],c.get('/api/companies').json());self.context(c,self.a['id'],status=403)

    def test_direct_permissions_without_group_and_effective_origins(self):
        u=self.user(company_ids=[self.a['id']],permissions=[self.permission(self.a['id'])]);c=self.login_user(u)
        self.context(c,self.a['id']);self.assertEqual(201,c.post(self.scope('/documents'),json=self.document()).status_code)
        self.assertEqual(403,c.post(self.scope('/journals'),json=self.journal()).status_code)
        e=self.core.effective_access(u['id'])['companies'][0]['routines']
        doc=next(x for x in e if x['id']=='fiscal.documents')
        self.assertEqual('Permissão individual',doc['actions']['create']['origin'])

    def test_group_deactivation_revokes_session_and_company(self):
        u=self.user();g=self.group(user_ids=[u['id']],permissions=[self.permission(self.a['id'])]);c=self.login_user(u)
        self.context(c,self.a['id'])
        r=self.client.put(f"/api/groups/{g['id']}",json=g|{'active':False});self.assertEqual(200,r.status_code,r.text)
        self.assertEqual(401,c.get(self.scope('/documents')).status_code)
        c=self.login_user(u);self.assertEqual([],c.get('/api/companies').json())
        self.assertEqual(409,self.client.put(f"/api/groups/{g['id']}",json=g).status_code)

    def test_cross_module_booking_denied_without_accounting_or_financial_right(self):
        u=self.user(company_ids=[self.a['id']],permissions=[self.permission(self.a['id'])]);c=self.login_user(u);self.context(c,self.a['id'])
        d=c.post(self.scope('/documents'),json=self.document()).json()
        d=c.post(self.scope(f"/documents/{d['id']}/review"),json={'version':d['version'],'reason':'Conferido'}).json()
        r=c.post(self.scope(f"/documents/{d['id']}/book"),json={'version':d['version'],'reason':'Conferido','idempotency_key':'cross','lines':self.journal(amount='100.00')['lines']})
        self.assertEqual(403,r.status_code,r.text);self.assertEqual([],self.core.journals(self.a['id']))
        self.assertEqual('reviewed',self.core.documents(self.a['id'])[0]['status'])

    def test_new_exercise_has_twelve_months_without_transactions(self):
        r=self.client.post(self.scope('/exercises'),json={'module':'fiscal','year':2029})
        self.assertEqual(201,r.status_code,r.text);self.assertEqual(12,len(r.json()['months']))
        self.assertTrue(all(x['enabled'] and not x['closed'] for x in r.json()['months']))
        self.assertEqual([],self.core.documents(self.a['id']))
        self.context(self.client,self.a['id'],'fiscal','2029-12')
        self.assertFalse(self.core.exercises(self.a['id'],'accounting',2029)['months'][0]['enabled'])
        self.assertFalse(self.core.exercises(self.b['id'],'fiscal',2029)['months'][0]['enabled'])

    def test_context_remembers_each_module_and_company(self):
        self.core.create_exercise(self.a['id'],{'module':'fiscal','year':2027},'admin')
        self.context(self.client,self.a['id'],'fiscal','2027-02')
        self.context(self.client,self.a['id'],'accounting','2026-03')
        self.assertEqual('2027-02',self.context(self.client,self.a['id'],'fiscal',None)['period'])
        self.context(self.client,self.b['id'],'fiscal','2026-09')
        self.assertEqual('2027-02',self.context(self.client,self.a['id'],'fiscal',None)['period'])

    def test_closed_period_is_consultable_but_rejects_write_and_independent(self):
        r=self.client.post(self.scope('/periods/close'),json={'period':'2026-11','module':'fiscal','reason':'Conferido','version':0})
        self.assertEqual(200,r.status_code,r.text)
        self.context(self.client,self.a['id'])
        self.assertEqual(200,self.client.get(self.scope('/documents')).status_code)
        self.assertEqual(409,self.client.post(self.scope('/documents'),json=self.document()).status_code)
        self.assertEqual(201,self.client.post(self.scope('/journals'),json=self.journal()).status_code)
        r=self.client.post(self.scope('/periods/reopen'),json={'period':'2026-11','module':'fiscal','reason':'Correção','version':0})
        self.assertEqual(409,r.status_code)
        r=self.client.post(self.scope('/periods/reopen'),json={'period':'2026-11','module':'fiscal','reason':'Correção','version':1})
        self.assertEqual(200,r.status_code,r.text)
        self.assertEqual(201,self.client.post(self.scope('/documents'),json=self.document()).status_code)

    def test_financial_closure_blocks_settlement_without_accounting(self):
        t=self.title()
        self.core.set_period(self.a['id'],{'period':'2026-11','module':'financial','reason':'Conferido'},'admin',True)
        r=self.client.post(self.scope(f"/titles/{t['id']}/settle"),json={'version':t['version'],'date':'2026-11-07','amount':'10.00','reason':'Teste','idempotency_key':'closed'})
        self.assertEqual(409,r.status_code,r.text);self.assertEqual(0,self.core.titles(self.a['id'])[0]['paid_cents'])
        self.assertFalse(self.core.periods(self.a['id'],'2026-11')['accounting']['closed'])

    def test_period_management_requires_specific_action(self):
        u=self.user(company_ids=[self.a['id']],permissions=[self.permission(self.a['id'],action='read')]);c=self.login_user(u);self.context(c,self.a['id'])
        self.assertEqual(403,c.post(self.scope('/exercises'),json={'module':'fiscal','year':2027}).status_code)
        self.assertEqual(403,c.post(self.scope('/periods/close'),json={'period':'2026-11','module':'fiscal','reason':'Tentativa'}).status_code)

    def test_stale_module_header_prevents_write(self):
        self.context(self.client,self.a['id'],'accounting')
        r=self.client.post(self.scope('/journals'),headers={'X-Module':'fiscal','X-Period':'2026-11','X-Company-Id':str(self.a['id'])},json=self.journal())
        self.assertEqual(409,r.status_code,r.text);self.assertEqual([],self.core.journals(self.a['id']))

    def test_social_only_exercises_and_audit_are_operational(self):
        self.core.create_exercise(self.a['id'],{'module':'social','year':2028},'admin')
        self.core.set_period(self.a['id'],{'module':'social','period':'2028-01','reason':'Controle operacional'},'admin',True)
        result=self.core.exercises(self.a['id'],'social',2028)
        self.assertTrue(result['months'][0]['closed']);self.assertFalse(result['months'][1]['closed'])
        self.assertTrue(any(x['entity']=='exercise' for x in self.core.audit(self.a['id'])))

    def test_manual_title_and_settlement_reject_foreign_month(self):
        r=self.client.post(self.scope('/titles'),json={'kind':'payable','description':'Fora da tela','partner_name':'Teste','document':'X','issue_date':'2026-12-01','due_date':'2026-12-10','amount':'10.00'})
        self.assertEqual(409,r.status_code,r.text)
        t=self.title()
        r=self.client.post(self.scope(f"/titles/{t['id']}/settle"),json={'version':t['version'],'date':'2026-12-01','amount':'10.00','reason':'Fora da tela','idempotency_key':'wrong-month'})
        self.assertEqual(409,r.status_code,r.text)
        self.assertEqual(0,self.core.titles(self.a['id'])[0]['paid_cents'])

    def test_lookup_cache_read_request_keeps_authorized_session(self):
        from unittest.mock import patch
        u=self.user(company_ids=[self.a['id']],permissions=[self.permission(self.a['id'],'fiscal.masters','read')])
        c=self.login_user(u);self.context(c,self.a['id'])
        service=self.app.state.lookups
        with patch.object(service,'transport',return_value={'cep':'01001000','logradouro':'Praça sintética','localidade':'São Paulo','uf':'SP'}):
            result=c.get('/api/lookups/cep/01001000?provider=viacep')
        self.assertEqual(200,result.status_code,result.text)
        self.assertEqual('ok',result.json()['status'])
        cached=c.get('/api/lookups/cep/01001000?provider=viacep')
        self.assertTrue(cached.json()['cached'])

    def test_fiscal_only_trace_hides_financial_and_accounting(self):
        d=self.client.post(self.scope('/documents'),json=self.document()).json()
        d=self.client.post(self.scope(f"/documents/{d['id']}/review"),json={'version':d['version'],'reason':'Conferência'}).json()
        self.client.post(self.scope(f"/documents/{d['id']}/book"),json={'version':d['version'],'reason':'Escrituração','idempotency_key':'trace-book','generate_titles':True,'lines':self.journal(amount='100.00')['lines']})
        u=self.user(company_ids=[self.a['id']],permissions=[self.permission(self.a['id'],'fiscal.documents','read')])
        c=self.login_user(u);self.context(c,self.a['id']);result=c.get(self.scope(f"/documents/{d['id']}/trace"))
        self.assertEqual(200,result.status_code,result.text)
        trace=result.json()
        self.assertEqual([],trace['titles']);self.assertEqual([],trace['journals']);self.assertEqual([],trace['events'])
