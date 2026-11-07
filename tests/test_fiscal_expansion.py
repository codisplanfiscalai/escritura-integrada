import io,json,unittest
from openpyxl import load_workbook
import test_business as base

class FiscalExpansionTests(unittest.TestCase):
    setUp=base.BusinessTests.setUp;tearDown=base.BusinessTests.tearDown
    create_company=base.BusinessTests.create_company
    scope=base.BusinessTests.scope;activate=base.BusinessTests.activate;document=base.BusinessTests.document
    journal=base.BusinessTests.journal;post=base.BusinessTests.post;reviewed=base.BusinessTests.reviewed;booking=base.BusinessTests.booking

    def rule(self,**extra):
        return self.post('/rules',{'name':'Cenário matemático sintético','tax':'ICMS','rate':'10','valid_from':'2026-01-01','status':'validated','source':'Fonte sintética de testes; não representa legislação','responsible':'Revisor teste','direction':'incoming',**extra},201)

    def memory(self,**extra):
        return {'period':'2026-11','tax':'icms','source':'Cenário sintético revisado','responsible':'Teste','idempotency_key':'memory','opening_mode':'previous','no_movement_confirmed':True,'entries':[],**extra}

    def finalize(self,a,key='final'):
        return self.post(f"/assessments/{a['id']}/finalize",{'period':a['snapshot']['period'],'reason':'Revisão integral do cenário sintético','coverage_reviewed':True,'idempotency_key':key})

    def test_item_selection_regime_and_no_overlapping_bases(self):
        d=self.reviewed(extra={'items':[{'description':'A','ncm':'11111111','cfop':'1102','total':'40.00'},{'description':'B','ncm':'22222222','cfop':'1102','total':'60.00'}]})
        self.post(f"/documents/{d['id']}/book",self.booking(d,generate_titles=False,lines=[]))
        r=self.rule(ncm='11111111',cfop='1102')
        entry={'document_id':d['id'],'rule_id':r['id'],'effect':'credit','base':'40.05','reason':'Base por item, conferida'}
        self.post('/assessments',self.memory(entries=[entry]),400)
        a=self.post('/assessments',self.memory(entries=[entry|{'item_indices':[0]}]));self.assertEqual(401,a['snapshot']['credit_cents'])
        self.assertEqual([0],a['snapshot']['entries'][0]['item_indices'])
        self.post('/assessments',self.memory(idempotency_key='overlap',entries=[entry|{'item_indices':[0]},entry|{'item_indices':[0]}]),400)
        scoped=self.rule(state='ZZ')
        self.post('/assessments',self.memory(idempotency_key='wrong-uf',entries=[entry|{'rule_id':scoped['id'],'item_indices':[0]}]),400)

    def test_finalized_balance_carried_only_same_tax_and_reverse_order(self):
        self.post('/tax-adjustments',{'period':'2026-11','tax':'icms','kind':'credit','category':'credit','amount':'100.00','source':'Teste sintético','reason':'Crédito conferido','idempotency_key':'credit'})
        a=self.post('/assessments',self.memory());ledger=self.finalize(a)
        self.assertEqual(10000,ledger['snapshot']['carry_credit_cents'])
        self.post('/documents',self.document('blocked-final'),409)
        self.post('/tax-adjustments',{'period':'2026-11','tax':'icms','kind':'debit','amount':'10.00','source':'Teste','reason':'Ajuste','idempotency_key':'blocked'},409)
        self.client.post('/api/context',json={'company_id':self.a['id'],'module':'fiscal','period':'2026-12'})
        next_a=self.post('/assessments',self.memory(period='2026-12',idempotency_key='next'))
        self.assertEqual(10000,next_a['snapshot']['opening_credit_cents'])
        next_l=self.finalize(next_a,'next-final')
        ibs=self.post('/assessments',self.memory(period='2026-12',tax='ibs',idempotency_key='ibs'))
        self.assertEqual(0,ibs['snapshot']['opening_credit_cents'])
        self.activate(self.a['id'])
        self.post(f"/tax-ledgers/{ledger['id']}/reverse",{'period':'2026-11','reason':'Revisar'},409)
        self.client.post('/api/context',json={'company_id':self.a['id'],'module':'fiscal','period':'2026-12'})
        self.post(f"/tax-ledgers/{next_l['id']}/reverse",{'period':'2026-12','reason':'Revisar dependência'})
        self.activate(self.a['id']);self.post(f"/tax-ledgers/{ledger['id']}/reverse",{'period':'2026-11','reason':'Corrigir base'})
        self.post('/documents',self.document('unblocked-final'),201)

    def test_finalization_requires_review_and_refuses_changed_origin(self):
        a=self.post('/assessments',self.memory())
        self.post(f"/assessments/{a['id']}/finalize",{'period':'2026-11','reason':'Teste','idempotency_key':'no-review'},400)
        self.post('/tax-adjustments',{'period':'2026-11','tax':'icms','kind':'debit','amount':'1.00','source':'Teste','reason':'Base mudou','idempotency_key':'change'})
        self.post(f"/assessments/{a['id']}/finalize",{'period':'2026-11','reason':'Teste','idempotency_key':'stale','coverage_reviewed':True},409)
        self.post('/assessments',self.memory(no_movement_confirmed=False,idempotency_key='implicit-empty'),400)

    def test_fiscal_reports_totals_filters_unknown_values_and_exports(self):
        d=self.reviewed(extra={'partner_name':'=HYPERLINK("malicioso")','taxes':{'ICMSTot.vICMS':'18.00','ICMSTot.vBC':'100.00'},'items':[{'description':'Item A','ncm':'11111111','cfop':'1102','total':'30.00'},{'description':'Item B','ncm':'22222222','cfop':'1102','total':'70.00'}]})
        self.post(f"/documents/{d['id']}/book",self.booking(d,generate_titles=False,lines=[]))
        path='/business-reports/fiscal-taxes?start=2026-11-01&end=2026-11-30'
        result=self.client.get(self.scope(path)).json();self.assertEqual(1800,result['totals']['icms_cents']);self.assertEqual(1,result['totals']['icms_informed_documents']);self.assertIsNone(result['rows'][0]['cbs_cents'])
        items=self.client.get(self.scope('/business-reports/fiscal-items?start=2026-11-01&end=2026-11-30&ncm=11111111')).json();self.assertEqual(3000,items['totals']['item_total_cents'])
        for fmt in ['pdf','xlsx']:
            response=self.client.get(self.scope(path+'&format='+fmt));self.assertEqual(200,response.status_code,response.text[:100] if response.status_code!=200 else '')
            self.assertTrue(response.content.startswith(b'%PDF') if fmt=='pdf' else response.content.startswith(b'PK'))
            if fmt=='xlsx':
                wb=load_workbook(io.BytesIO(response.content));ws=wb['Dados'];headers=[c.value for c in ws[1]]
                cell=ws.cell(2,headers.index('Participante')+1);self.assertEqual('s',cell.data_type);self.assertTrue(cell.value.startswith('='));self.assertEqual(18,ws.cell(2,headers.index('ICMS declarado (R$)')+1).value)
                self.assertIn('Valores em centavos',wb.sheetnames)
        entries=self.client.get(self.scope('/business-reports/fiscal-entries?start=2026-11-01&end=2026-11-30')).json();self.assertEqual(10000,entries['totals']['total_cents'])

    def test_fiscal_closure_blocks_finalization_and_ledger_reversal(self):
        a=self.post('/assessments',self.memory());ledger=self.finalize(a)
        self.post('/periods/close',{'period':'2026-11','module':'fiscal','reason':'Conferido'})
        self.post(f"/tax-ledgers/{ledger['id']}/reverse",{'period':'2026-11','reason':'Tentar reverter fechado'},409)
        self.assertEqual(200,self.client.get(self.scope(f"/tax-ledgers/{ledger['id']}/report?format=pdf")).status_code)
