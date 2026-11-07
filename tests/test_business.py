"""Fluxos integrados e falhas atômicas; somente identidades e operações sintéticas."""
import base64
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import urllib.error

from fastapi.testclient import TestClient
import test_core as base
from app.business import BusinessCore
from app.core import Core, DomainError
from app.db import Database, SCHEMA, request_context, ContextConflict
from app.lookups import LookupService, normalize
from app.prosoft import encode_journals


class BusinessTests(unittest.TestCase):
    setUp=base.CoreApiTests.setUp
    tearDown=base.CoreApiTests.tearDown
    scope=base.CoreApiTests.scope
    activate=base.CoreApiTests.activate
    create_company=base.CoreApiTests.create_company
    journal=base.CoreApiTests.journal
    document=base.CoreApiTests.document
    title=base.CoreApiTests.title

    def post(self,path,payload,status=200):
        r=self.client.post(self.scope(path),json=payload)
        self.assertEqual(status,r.status_code,r.text)
        return r.json()

    def reviewed(self,number='DOC1',extra=None):
        d=self.post('/documents',self.document(number)|(extra or {}),201)
        return self.post(f"/documents/{d['id']}/review",{'version':d['version'],'reason':'Conferência sintética'})

    def booking(self,d,key='book',**extra):
        return {'version':d['version'],'reason':'Conferência sintética','idempotency_key':key,'lines':self.journal(amount='100.00')['lines'],
            'generate_titles':True,'installments':[{'due_date':'2026-11-10','amount':'40.00'},{'due_date':'2026-12-10','amount':'60.00'}],**extra}

    def test_document_titles_journal_atomic_replay_and_reverse(self):
        d=self.reviewed();payload=self.booking(d)
        booked=self.post(f"/documents/{d['id']}/book",payload)
        self.assertEqual(2,len(booked['titles']));self.assertEqual(10000,booked['journal']['total_cents'])
        replay=self.post(f"/documents/{d['id']}/book",payload);self.assertTrue(replay['duplicate'])
        self.assertEqual(2,len(self.core.titles(self.a['id'])))
        self.post(f"/journals/{booked['journal']['id']}/reverse",{'reason':'Errado','date':'2026-11-07'},409)
        reversed=self.post(f"/documents/{d['id']}/reverse",{'date':'2026-11-07','reason':'Correção sintética','version':booked['document']['version'],'idempotency_key':'reverse'})
        self.assertEqual('pending',reversed['document']['status']);self.assertEqual(2,reversed['cancelled_titles'])
        self.assertEqual(0,sum(t['balance_cents'] for t in self.core.titles(self.a['id'])))
        trace=self.client.get(self.scope(f"/documents/{d['id']}/trace")).json()
        self.assertEqual(2,len(trace['journals']));self.assertEqual(2,len(trace['titles']))
        report=self.core.business_report(self.a['id'],'trial-balance','2026-11-01','2026-11-30')
        self.assertTrue(all(r['closing_cents']==0 for r in report['rows']))

    def test_bad_installments_or_closed_accounting_roll_back_all(self):
        d=self.reviewed();payload=self.booking(d,installments=[{'due_date':'2026-11-10','amount':'99.99'}])
        self.post(f"/documents/{d['id']}/book",payload,409)
        self.assertEqual([],self.core.journals(self.a['id']));self.assertEqual([],self.core.titles(self.a['id']))
        self.post('/periods/close',{'period':'2026-11','module':'accounting','reason':'Fechamento de teste'})
        self.post(f"/documents/{d['id']}/book",self.booking(d),409)
        self.assertEqual('reviewed',self.core.documents(self.a['id'])[0]['status'])
        self.assertEqual([],self.core.titles(self.a['id']))

    def test_master_scope_version_and_identity(self):
        payload={'code':'P1','name':'Participante fictício','tax_id':'11222333000181','data':{'roles':['supplier'],'profile':{'ie_status':'not_found'}}}
        p=self.post('/masters/participant',payload,201)
        self.assertEqual('not_found',p['data']['profile']['ie_status'])
        response=self.client.put(self.scope(f"/masters/participant/{p['id']}"),json=payload|{'version':1,'name':'Revisto'})
        self.assertEqual(200,response.status_code,response.text)
        self.assertEqual(409,self.client.put(self.scope(f"/masters/participant/{p['id']}"),json=payload|{'version':1}).status_code)
        self.activate(self.b['id'])
        self.assertEqual(404,self.client.put(self.scope(f"/masters/participant/{p['id']}",self.b['id']),json=payload|{'version':2}).status_code)
        self.activate(self.a['id'])
        self.post('/documents',self.document()|{'participant_id':p['id'],'partner_tax_id':''},400)
        d=self.post('/documents',self.document()|{'participant_id':p['id'],'partner_tax_id':p['tax_id']},201)
        self.assertEqual(p['id'],d['participant_id'])

    def test_validated_model_and_sped_installments(self):
        m=self.post('/masters/accounting_model',{'code':'M1','name':'Modelo sintético','data':{'debit_account_id':self.aid['3'],'credit_account_id':self.aid['5'],'valid_from':'2026-01-01','status':'validated','history':'Entrada','source':'Critério contábil fictício','responsible':'Operador'}},201)
        d=self.reviewed(extra={'invoices':[{'installments':[{'due_date':'2026-11-10','amount':'100.00'}]}]})
        p=self.booking(d,model_id=m['id'],use_document_installments=True);p.pop('lines')
        r=self.post(f"/documents/{d['id']}/book",p)
        self.assertEqual(1,len(r['titles']));self.assertEqual(10000,r['journal']['total_cents'])

    def settlement(self,title,key='pay',amount='40.00',**extra):
        return {'date':'2026-11-07','amount':amount,'reason':'Pagamento fictício','idempotency_key':key,'version':title['version'],**extra}

    def test_settlement_charges_cash_and_reversal(self):
        t=self.title();p=self.settlement(t,interest='2.00',fine='1.00',discount='3.00',lines=[
            {'account_id':self.aid['3'],'debit':'40.00','credit':'0.00'},
            {'account_id':self.aid['5'],'debit':'3.00','credit':'0.00'},
            {'account_id':self.aid['1'],'debit':'0.00','credit':'40.00'},
            {'account_id':self.aid['4'],'debit':'0.00','credit':'3.00'}])
        r=self.post(f"/titles/{t['id']}/settle",p)
        self.assertEqual(6000,r['title']['balance_cents']);self.assertEqual(4000,r['settlement']['cash_cents'])
        self.assertEqual(4300,r['journal']['total_cents'])
        cash=self.core.business_report(self.a['id'],'cash-flow','2026-11-01','2026-11-30')
        self.assertEqual(-4000,cash['totals']['cash_cents'])
        self.post(f"/settlements/{r['settlement']['id']}/reverse",{'date':'2026-11-08','reason':'Correção','idempotency_key':'undo'})
        self.assertEqual(10000,self.core.titles(self.a['id'])[0]['balance_cents'])
        self.assertEqual(0,self.core.business_report(self.a['id'],'cash-flow','2026-11-01','2026-11-30')['totals']['cash_cents'])
        self.post(f"/settlements/{r['settlement']['id']}/reverse",{'date':'2026-11-08','reason':'Correção','idempotency_key':'undo2'},409)

    def test_settlement_previous_version_replay_and_concurrent_overpay(self):
        t=self.title();p=self.settlement(t)
        legacy=Core(self.app.state.db).settle_title(self.a['id'],t['id'],p,'teste')
        self.assertTrue(self.post(f"/titles/{t['id']}/settle",p)['duplicate'])
        def settle(key):
            try:return self.core.settle_title(self.a['id'],t['id'],self.settlement(legacy['title'],key,'60.00'),'teste')
            except DomainError as e:return e.code
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(settle,['race1','race2']))
        self.assertEqual(1,sum(isinstance(x,dict) for x in results))
        self.assertEqual(0,self.core.titles(self.a['id'])[0]['balance_cents'])

    def test_renegotiation_remaining_balance_and_stale_guard(self):
        t=self.title();paid=self.post(f"/titles/{t['id']}/settle",self.settlement(t))['title']
        p={'date':'2026-11-08','title_ids':[t['id']],'versions':{str(t['id']):t['version']},'reason':'Acordo fictício','interest':'5.00','discount':'2.00','installments':[{'due_date':'2026-12-10','amount':'63.00'}],'idempotency_key':'ren1'}
        self.post('/titles/renegotiate',p,409);p['versions'][str(t['id'])]=paid['version']
        r=self.post('/titles/renegotiate',p)
        self.assertEqual(6000,r['principal_cents']);self.assertEqual(6300,r['total_cents'])
        self.assertFalse(r['accounting_created']);self.assertTrue(self.post('/titles/renegotiate',p)['duplicate'])
        old=self.core.titles(self.a['id'])[0];self.assertEqual('renegotiated',old['status']);self.assertEqual(0,old['balance_cents'])
        self.assertEqual(1,len(old['settlements']))
        self.post(f"/titles/{t['id']}/settle",self.settlement(old,'forbidden','1.00'),409)

    def bank(self):
        raw=b'data;valor;historico;documento\n06/11/2026;-100,00;Pagamento ficticio;TEST1\n'
        p=self.post('/imports/preview',{'filename':'bank.csv','content_base64':base64.b64encode(raw).decode(),'period':'2026-11','options':{'date_format':'DMY','delimiter':';','decimal_separator':','}})
        self.post(f"/imports/{p['id']}/confirm",{'preview_hash':p['preview_hash'],'bank_account':'Banco fictício'})
        self.assertEqual(raw,self.client.get(self.scope(f"/imports/{p['id']}/original")).content)
        return self.core.banks(self.a['id'])[0]

    def test_group_allocation_is_explicit_and_reversible(self):
        bank=self.bank();t1=self.title('40.00');t2=self.title('60.00')
        p={'reason':'Conferido','idempotency_key':'allocation','allocations':[{'title_id':t1['id'],'amount':'40.00'},{'title_id':t2['id'],'amount':'60.00'}]}
        r=self.post(f"/banks/{bank['id']}/allocate",p)
        self.assertTrue(r['bank']['reconciled']);self.assertEqual(0,r['settlements_created'])
        self.assertEqual(1,self.core.dashboard(self.a['id'],'2026-11')['reconciliation']['matched'])
        self.assertEqual(10000,sum(t['balance_cents'] for t in self.core.titles(self.a['id'])))
        self.assertTrue(self.post(f"/banks/{bank['id']}/allocate",p)['duplicate'])
        for a in r['allocation_ids']:self.post(f'/allocations/{a}/reverse',{'reason':'Rever vínculos'})
        self.assertEqual(1,self.core.dashboard(self.a['id'],'2026-11')['reconciliation']['pending'])
        p['settle']=True;p['idempotency_key']='allocation2'
        r=self.post(f"/banks/{bank['id']}/allocate",p)
        self.assertEqual(2,r['settlements_created']);self.assertEqual(0,sum(t['balance_cents'] for t in self.core.titles(self.a['id'])))
        self.assertEqual(-10000,self.core.business_report(self.a['id'],'cash-flow','2026-11-01','2026-11-30',direction='payable')['totals']['cash_cents'])
        self.assertEqual([],self.core.business_report(self.a['id'],'cash-flow','2026-11-01','2026-11-30',direction='receivable')['rows'])
        settlement=self.core.titles(self.a['id'])[0]['settlements'][0]
        self.post(f"/settlements/{settlement['id']}/reverse",{'date':'2026-11-08','reason':'Rever','idempotency_key':'u1'},409)
        r=self.post(f"/allocations/{r['allocation_ids'][0]}/reverse",{'reason':'Desvincular'})
        self.assertEqual(settlement['id'],r['settlement_preserved'])

    def test_allocation_excess_rolls_back_earlier_settlement(self):
        b=self.bank();t1=self.title('40.00');t2=self.title('30.00')
        self.post(f"/banks/{b['id']}/allocate",{'reason':'Erro','settle':True,'idempotency_key':'invalid','allocations':[{'title_id':t1['id'],'amount':'40.00'},{'title_id':t2['id'],'amount':'60.00'}]},409)
        self.assertEqual(7000,sum(t['balance_cents'] for t in self.core.titles(self.a['id'])))
        self.assertEqual([],self.core.banks(self.a['id'])[0]['allocations'])

    def test_renegotiation_reversal_keeps_original_partial_payment(self):
        t=self.title();paid=self.post(f"/titles/{t['id']}/settle",self.settlement(t))['title']
        p={'date':'2026-11-08','title_ids':[t['id']],'versions':{str(t['id']):paid['version']},'reason':'Acordo fictício','installments':[{'due_date':'2026-12-10','amount':'60.00'}],'idempotency_key':'agreement'}
        r=self.post('/titles/renegotiate',p)
        self.post(f"/renegotiations/{r['id']}/reverse",{'date':'2026-11-09','reason':'Correção de acordo','idempotency_key':'reverse-agreement'})
        old=next(x for x in self.core.titles(self.a['id']) if x['id']==t['id'])
        self.assertEqual(6000,old['balance_cents']);self.assertEqual(4000,old['paid_cents'])
        new=next(x for x in self.core.titles(self.a['id']) if x['id']==r['titles'][0]['id'])
        self.assertEqual('cancelled',new['status']);self.assertTrue(self.core.renegotiations(self.a['id'])[0]['reversed_at'])

    def test_opening_journal_balanced_idempotent_and_reported(self):
        self.activate(self.a['id'],'2026-10')
        p=self.journal(day='2026-10-31',amount='100.00')
        first=self.post('/opening-balances',p,201)
        second=self.post('/opening-balances',p,201)
        self.assertEqual(first['id'],second['id']);self.assertTrue(second['duplicate'])
        self.post('/opening-balances',p|{'lines':[p['lines'][0]]},400)
        report=self.core.business_report(self.a['id'],'ledger','2026-11-01','2026-11-30',self.aid['3'])
        self.assertEqual([],report['rows'])
        trial=self.core.business_report(self.a['id'],'trial-balance','2026-11-01','2026-11-30',self.aid['3'])
        self.assertEqual(10000,trial['rows'][0]['opening_cents'])

    def test_participant_identity_retained_in_finance_and_malformed_profile(self):
        p=self.post('/masters/participant',{'code':'P1','name':'Participante sintético','tax_id':'11222333000181','data':{}},201)
        t=self.post('/titles',{'kind':'payable','description':'Título com cadastro','participant_id':p['id'],'issue_date':'2026-11-06','due_date':'2026-11-10','amount':'10.00','idempotency_key':'master-title'},201)
        self.assertEqual(p['id'],t['participant_id']);self.assertEqual(p['name'],t['partner_name'])
        self.post('/masters/participant',{'code':'bad','name':'Inválido','data':{'profile':[]}},400)
        self.post('/documents',self.document()|{'items':None},400)

    def test_report_balances_center_group_and_unmapped_rejection(self):
        c=self.core.save_cost_center(self.a['id'],{'code':'ADM','name':'Centro fictício'},'teste')
        self.core.create_journal(self.a['id'],self.journal(day='2026-10-31',amount='10.00'),'teste')
        self.core.create_journal(self.a['id'],self.journal(key='current',amount='20.00',center=c['id']),'teste')
        r=self.core.business_report(self.a['id'],'ledger','2026-11-01','2026-11-30',self.aid['3'])
        self.assertEqual((1000,3000),(r['rows'][0]['opening_cents'],r['rows'][0]['balance_cents']))
        cc=self.core.business_report(self.a['id'],'cost-centers','2026-11-01','2026-11-30')
        self.assertEqual({c['id'],None},{x['cost_center_id'] for x in cc['rows']})
        with self.assertRaises(DomainError):self.core.business_report(self.a['id'],'balance-sheet','2026-11-01','2026-11-30')
        for a in self.accounts:
            self.core.save_account(self.a['id'],a|{'report_group':'asset' if a['access_code']=='3' else 'equity'},'teste',a['id'])
        self.assertEqual(0,self.core.business_report(self.a['id'],'balance-sheet','2026-11-01','2026-11-30')['totals']['difference_cents'])

    def test_journal_origin_api_is_scoped_and_complete(self):
        j=self.core.create_journal(self.a['id'],self.journal(),'teste')
        r=self.client.get(self.scope('/journals/'+str(j['id'])))
        self.assertEqual(200,r.status_code);self.assertEqual(j['lines'],r.json()['lines'])
        self.assertEqual(404,self.client.get(self.scope('/journals/'+str(j['id']),self.b['id'])).status_code)

    def test_assessment_segregation_precision_staleness_and_adjustment(self):
        d=self.reviewed();self.post(f"/documents/{d['id']}/book",self.booking(d,generate_titles=False,lines=[]))
        r=self.post('/rules',{'name':'Taxa sintética','tax':'CBS','rate':'2.125','valid_from':'2026-01-01','status':'validated','source':'Exclusivamente teste matemático','responsible':'Teste','direction':'incoming'},201)
        a=self.post('/tax-adjustments',{'period':'2026-11','tax':'cbs','kind':'debit','amount':'1.00','source':'Cenário sintético','reason':'Ajuste','idempotency_key':'adj'})
        p={'period':'2026-11','tax':'cbs','source':'Cenário sintético','responsible':'Teste','idempotency_key':'assess','entries':[{'document_id':d['id'],'rule_id':r['id'],'base':'10.00','effect':'debit','reason':'Base fictícia'}]}
        assessment=self.post('/assessments',p);self.assertEqual(121,assessment['snapshot']['payable_cents']);self.assertFalse(assessment['snapshot']['legal_validation'])
        self.post('/assessments',p|{'idempotency_key':'wrong','tax':'ibs'},400)
        self.post(f"/tax-adjustments/{a['id']}/reverse",{'period':'2026-11','reason':'Ajuste incorreto'})
        self.assertTrue(self.client.get(self.scope('/assessments?period=2026-11')).json()[0]['stale'])
        self.post('/periods/close',{'period':'2026-11','module':'fiscal','reason':'Fechar teste'})
        self.post('/assessments',p|{'idempotency_key':'closed'},409)

    def test_prosoft_fixed_width_mapping_preview_and_replay(self):
        j=self.core.create_journal(self.a['id'],self.journal(amount='123.45')|{'document':'TEST1'},'teste')
        p={'period':'2026-11','company_code':'50','batch':'12','accounts':{str(a['id']):{'code':a['access_code'],'confirmed':True} for a in self.accounts},'centers':{}}
        pre=self.post('/prosoft/preview',p);self.assertTrue(pre['manifest']['needs_ascii_review'])
        self.post('/prosoft/confirm',p|{'preview_hash':pre['preview_hash'],'destination_reviewed':True},400)
        confirm=p|{'preview_hash':pre['preview_hash'],'destination_reviewed':True,'allow_ascii':True}
        r=self.post('/prosoft/confirm',confirm);self.assertTrue(self.post('/prosoft/confirm',confirm)['duplicate'])
        raw=self.client.get(self.scope(f"/exports/{r['id']}/download")).content
        self.assertEqual(450,len(raw));self.assertEqual(b'LC1',raw[:3]);self.assertEqual(b'1',raw[11:12]);self.assertEqual(b'06112026',raw[12:20]);self.assertEqual(b'0000000000123.45',raw[116:132]);self.assertEqual(b'\r\n',raw[-2:])
        self.core.create_journal(self.a['id'],self.journal('another')|{'document':'TEST2'},'teste')
        self.post('/prosoft/confirm',confirm,409)

    def test_prosoft_detailed_records_and_no_truncation(self):
        data=self.journal(amount='100.00')|{'document':'TEST1','lines':[{'account_id':self.aid['3'],'debit':'70.00','credit':'0.00'},{'account_id':self.aid['1'],'debit':'30.00','credit':'0.00'},{'account_id':self.aid['5'],'debit':'0.00','credit':'100.00'}]}
        j=self.core.create_journal(self.a['id'],data,'teste');mapping={str(a['id']):{'code':a['access_code'],'confirmed':True} for a in self.accounts}
        raw,manifest=encode_journals([j],mapping,{},'1');rows=raw.split(b'\r\n')[:-1]
        self.assertEqual([448,342,342,342],list(map(len,rows)));self.assertEqual(b'2',rows[0][11:12]);self.assertEqual(b'003',rows[0][65:68]);self.assertEqual(b'D',rows[1][11:12]);self.assertEqual(b'C',rows[3][11:12])
        with self.assertRaises(DomainError):encode_journals([j|{'document':'X'*11}],mapping,{},'1')

    def test_users_permissions_revoke_and_readonly(self):
        u=self.client.post('/api/users',json={'username':'consulta','password':'Senha-ficticia-123!','role':'viewer','company_ids':[self.a['id']]}).json()
        other=TestClient(self.app)
        try:
            s=other.post('/api/login',json={'username':'consulta','password':'Senha-ficticia-123!'}).json();other.headers['X-CSRF-Token']=s['csrf_token']
            self.assertEqual([self.a['id']],[x['id'] for x in other.get('/api/companies').json()])
            self.assertEqual(403,other.get(self.scope('/titles',self.b['id'])).status_code)
            self.activate(self.a['id'],client=other)
            self.assertEqual(403,other.post(self.scope('/titles'),json={}).status_code)
            self.assertEqual(403,other.get('/api/users').status_code)
            response=self.client.put('/api/users/'+str(u['id']),json=u|{'active':False})
            self.assertEqual(200,response.status_code,response.text)
            self.assertEqual(401,other.get('/api/companies').status_code)
        finally:other.close()


class LookupTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.db=Database(self.tmp.name);self.clock=[1000.0]
    def tearDown(self):self.tmp.cleanup()
    def response(self,regs=None):return {'razao_social':'Empresa sintética','estabelecimento':{'cnpj':'11222333000181','atividade_principal':{'id':'4711302'},'inscricoes_estaduais':regs or [],'estado':{'sigla':'SP'},'cidade':{'nome':'Cidade sintética','ibge_id':3550308}}}
    def test_multiple_ie_no_automatic_exemption(self):
        regs=[{'estado':{'sigla':'SP'},'inscricao_estadual':'123','ativo':True},{'estado':{'sigla':'BA'},'inscricao_estadual':'456','ativo':False}]
        fields=normalize('cnpjws',self.response(regs),'11222333000181')
        self.assertEqual(2,len(fields['profile']['state_registrations']));self.assertNotIn('ie',fields);self.assertNotIn('regime',fields)
        self.assertEqual('not_found',normalize('cnpjws',self.response(),'11222333000181')['profile']['ie_status'])
        self.assertEqual('unknown',normalize('brasilapi',{'cnpj':'11222333000181','razao_social':'Teste'},'11222333000181')['profile']['ie_status'])
    def test_cache_expiry_offline_and_identity_guard(self):
        calls=[]
        def transport(*args):calls.append(args);return self.response()
        svc=LookupService(self.db,transport,lambda:self.clock[0])
        self.assertFalse(svc.query('cnpj','11222333000181')['cached']);self.assertTrue(svc.query('cnpj','11222333000181')['cached']);self.assertEqual(1,len(calls))
        self.clock[0]+=90000;svc.transport=lambda *args:(_ for _ in ()).throw(OSError('offline'))
        stale=svc.query('cnpj','11222333000181');self.assertTrue(stale['stale']);self.assertEqual('cnpjws',stale['provider'])
        with self.assertRaises(ValueError):normalize('cnpjws',self.response(),'12345678000195')
        with self.assertRaises(DomainError):svc.query('cnpj','12ABC34501DE35')
    def test_fallback_429_and_cep_missing(self):
        calls=[]
        def transport(url,headers,timeout):
            calls.append(url)
            if 'viacep' in url:raise urllib.error.HTTPError(url,429,'busy',{'Retry-After':'120'},None)
            return {'cep':'01001000','city':'Cidade sintética','state':'SP','street':'Via de teste','ibge':{'city':'3550308','state':'35'}}
        svc=LookupService(self.db,transport,lambda:self.clock[0]);r=svc.query('cep','01001-000')
        self.assertEqual('brasilapi_cep',r['provider']);self.assertEqual('3550308',r['fields']['ibge']);self.assertEqual('rate_limited',r['attempts'][0]['status'])
        svc.query('cep','01001-000',refresh=True);self.assertEqual(1,sum('viacep' in u for u in calls))
        with self.assertRaises(DomainError):normalize('viacep',{'erro':True},'01001000')
    def test_rate_cap_and_credentials_never_returned(self):
        calls=[]
        def transport(url,headers,timeout):calls.append((url,headers));return self.response()
        svc=LookupService(self.db,transport,lambda:self.clock[0])
        with patch.dict('os.environ',{'ESCRITURA_CNPJWS_TOKEN':'segredo-de-teste'}):
            for _ in range(4):r=svc.query('cnpj','11222333000181','cnpjws',True)
        self.assertEqual(3,len(calls));self.assertTrue(r['stale']);self.assertNotIn('segredo-de-teste',json.dumps(r));self.assertEqual('segredo-de-teste',calls[0][1]['x_api_token'])


class MigrationTests(unittest.TestCase):
    def test_schema1_upgrade_preserves_money_and_is_idempotent(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as folder:
            conn=sqlite3.connect(Path(folder)/'escritura.sqlite3',isolation_level=None);conn.executescript(SCHEMA)
            conn.execute("INSERT INTO companies(id,code,name,tax_id,regime,created_at,updated_at) VALUES(1,'A','Sintética','11222333000181','outros','date','date')")
            conn.execute("INSERT INTO titles(id,company_id,kind,description,partner_name,document,issue_date,due_date,amount_cents,paid_cents,created_at) VALUES(1,1,'payable','Teste','Teste','1','2026-11-01','2026-11-02',12345,2345,'date')")
            conn.execute("INSERT INTO settlements(company_id,title_id,date,amount_cents,reason,idempotency_key,request_hash,created_at) VALUES(1,1,'2026-11-02',2345,'Teste','key','hash','date')");conn.close()
            db=Database(folder);Database(folder)
            with db.read() as c:
                self.assertEqual(2345,c.execute('SELECT cash_cents FROM settlements').fetchone()[0]);self.assertEqual(12345,c.execute('SELECT amount_cents FROM titles').fetchone()[0]);self.assertEqual('4',c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])

if __name__=='__main__':unittest.main()
