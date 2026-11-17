"""Bank reporting uses synthetic imported movements, never inferred balances."""
import io
import unittest
from unittest.mock import patch
from pypdf import PdfReader
from openpyxl import load_workbook
import test_core as base
from app.core import DomainError

class BankReportTests(unittest.TestCase):
    setUp=base.CoreApiTests.setUp
    tearDown=base.CoreApiTests.tearDown
    scope=base.CoreApiTests.scope
    activate=base.CoreApiTests.activate
    create_company=base.CoreApiTests.create_company

    def seed(self):
        with self.core.db.transaction() as conn:
            for idx,(cid,day,amount,account,description) in enumerate([
                (self.a['id'],'2026-10-31','900.00','Banco A','Anterior'),
                (self.a['id'],'2026-11-01','100.12','Banco A','Recebimento'),
                (self.a['id'],'2026-11-02','-20.01','Banco A','Tarifa'),
                (self.a['id'],'2026-11-03','50.00','Banco B','=Fórmula sintética'),
                (self.a['id'],'2026-12-01','700.00','Banco A','Posterior'),
                (self.b['id'],'2026-11-01','600.00','Banco A','Outra empresa'),
            ]):
                self.core._create_bank(conn,cid,{'date':day,'amount':amount,'description':description,'reference':'TESTE','external_id':str(idx)},account,'test')

    def url(self,extra=''):
        return self.scope('/business-reports/bank-movements?start=2026-11-01&end=2026-11-30'+extra)

    def test_period_company_and_no_invented_balance(self):
        self.seed();response=self.client.get(self.url());self.assertEqual(200,response.status_code,response.text)
        r=response.json();self.assertEqual(3,len(r['rows']))
        self.assertEqual({'transactions':3,'incoming_cents':15012,'outgoing_cents':2001,'net_movement_cents':13011},r['totals'])
        self.assertNotIn('opening_cents',r['totals']);self.assertNotIn('balance_cents',r['totals'])
        self.assertEqual([],self.core.journals(self.a['id']))
        other=self.client.get(self.scope('/business-reports/bank-movements?start=2026-11-01&end=2026-11-30',self.b['id'])).json()
        self.assertEqual(1,len(other['rows']));self.assertEqual(60000,other['totals']['incoming_cents'])

    def test_filters_invalid_and_empty(self):
        self.seed()
        r=self.client.get(self.url('&bank_account=Banco%20A&direction=outgoing&query=tarifa')).json()
        self.assertEqual(1,len(r['rows']));self.assertEqual(-2001,r['totals']['net_movement_cents'])
        r=self.client.get(self.url('&bank_account=Ausente')).json();self.assertEqual([],r['rows']);self.assertEqual(0,r['totals']['transactions'])
        for extra in ['&cfop=5102','&ncm=12345678','&status=settled','&direction=payable',f'&account_id={self.aid["3"]}','&cost_center_id=1']:
            self.assertEqual(400,self.client.get(self.url(extra)).status_code,extra)

    def test_pdf_xlsx_csv_same_scope_and_formula_escaping(self):
        self.seed()
        for fmt in ['pdf','xlsx','csv']:
            response=self.client.get(self.url('&format='+fmt));self.assertEqual(200,response.status_code,response.text[:200] if fmt=='csv' else '')
            if fmt=='pdf':
                text=' '.join(p.extract_text() for p in PdfReader(io.BytesIO(response.content)).pages)
                self.assertIn('MOVIMENTAÇÃO BANCÁRIA',text);self.assertIn('Movimento líquido',text);self.assertNotIn('Anterior',text)
            elif fmt=='xlsx':
                wb=load_workbook(io.BytesIO(response.content));self.assertEqual(4,wb['Dados'].max_row)
                self.assertFalse(any(c.data_type=='f' for row in wb['Dados'] for c in row))
            else:self.assertIn("'=Fórmula sintética",response.text)

    def test_bank_permission_rechecked_for_every_format(self):
        from app import permissions
        original=permissions.effect
        def deny(conn,cid,routine,action):
            if routine=='financial.reconciliation' and action=='read':raise DomainError('Sem acesso bancário.',403)
            return original(conn,cid,routine,action)
        with patch.object(permissions,'effect',deny):
            for fmt in ['json','csv','xlsx','pdf']:
                self.assertEqual(403,self.client.get(self.url('&format='+fmt)).status_code)

    def test_accounting_reports_does_not_grant_banking_access(self):
        from fastapi.testclient import TestClient
        cid=self.a['id']
        permissions=[{'company_id':cid,'routine':'accounting.reports','action':action,'effect':'allow'} for action in ['read','export','print']]
        response=self.client.post('/api/users',json={'username':'bank-report-reader','password':'Senha-teste-12345','role':'custom','company_ids':[cid],'permissions':permissions})
        self.assertEqual(201,response.status_code,response.text)
        with TestClient(self.app) as client:
            session=client.post('/api/login',json={'username':'bank-report-reader','password':'Senha-teste-12345'}).json()
            client.headers['X-CSRF-Token']=session['csrf_token']
            self.assertEqual(200,client.post('/api/context',json={'company_id':cid,'module':'accounting','period':'2026-11'}).status_code)
            self.assertFalse(any(m['kind']=='bank-movements' for m in client.get(self.scope('/report-models?module=accounting')).json()))
            for fmt in ['json','csv','xlsx','pdf']:
                self.assertEqual(403,client.get(self.url('&format='+fmt)).status_code)
