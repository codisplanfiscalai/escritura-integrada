"""Contratos dos modelos: filtros, paridade de valores e permissões existentes."""
import io
import unittest
from pypdf import PdfReader
from openpyxl import load_workbook
from fastapi.testclient import TestClient
import test_business as base


class ReportModelsApiTests(unittest.TestCase):
    setUp=base.BusinessTests.setUp
    tearDown=base.BusinessTests.tearDown
    create_company=base.BusinessTests.create_company
    scope=base.BusinessTests.scope
    activate=base.BusinessTests.activate
    journal=base.BusinessTests.journal
    document=base.BusinessTests.document
    post=base.BusinessTests.post
    reviewed=base.BusinessTests.reviewed
    booking=base.BusinessTests.booking

    def path(self,kind,extra=''):
        return self.scope(f'/business-reports/{kind}?start=2026-11-01&end=2026-11-30'+extra)

    def test_every_available_model_has_compatible_json_and_pdf(self):
        catalog=self.client.get(self.scope('/report-models')).json()
        self.assertGreaterEqual(len(catalog),17)
        ids=[m['id'] for m in catalog]
        self.assertEqual(len(ids),len(set(ids)))
        for model in catalog:
            if not model.get('supported',True):continue
            with self.subTest(model=model['id']):
                path=self.path(model['kind'],'&model='+model['id']+'&first_page=23')
                data=self.client.get(path)
                self.assertEqual(200,data.status_code,data.text)
                self.assertEqual(model['id'],data.json()['model'])
                response=self.client.get(path+'&format=pdf')
                self.assertEqual(200,response.status_code,response.text[:100] if response.status_code!=200 else '')
                self.assertTrue(response.content.startswith(b'%PDF'))
                self.assertTrue(response.headers['content-disposition'].startswith('attachment'))
                self.assertGreaterEqual(len(PdfReader(io.BytesIO(response.content)).pages),1)
                response=self.client.get(path+'&format=pdf&purpose=print')
                self.assertTrue(response.headers['content-disposition'].startswith('inline'))

    def test_unknown_model_wrong_kind_and_invalid_page_fail_before_export(self):
        for extra in ['&model=missing','&model=prosoft-ledger-v1',
                      '&model=internal-diary&first_page=0','&model=internal-diary&first_page=100000']:
            with self.subTest(extra=extra):
                self.assertEqual(400,self.client.get(self.path('diary',extra)).status_code)

    def test_accounting_filters_are_exported_and_ledger_balance_not_rebased_by_search(self):
        for key,amount,day,history in [('first','10.00','2026-11-05','Não selecionado'),('second','20.00','2026-11-06','Selecionar ABC')]:
            self.post('/journals',self.journal(key,amount,day)|{'history':history},201)
        path=self.path('ledger',f'&account_id={self.aid["3"]}&query=ABC&model=prosoft-ledger-v1')
        result=self.client.get(path).json()
        self.assertEqual(1,len(result['rows']))
        self.assertEqual(2000,result['totals']['debit_cents'])
        self.assertEqual(3000,result['rows'][0]['balance_cents'])
        self.assertEqual(3000,result['ledger_groups'][0]['closing_cents'])
        self.assertTrue(result['ledger_groups'][0]['filtered'])
        self.assertEqual('abc',result['filters']['query'])
        pdf=self.client.get(path+'&format=pdf')
        text='\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
        self.assertIn('30,00',text)
        self.assertIn('20,00',text)
        workbook=load_workbook(io.BytesIO(self.client.get(path+'&format=xlsx').content))
        self.assertIn('abc',str([r for r in workbook['Conferência'].values]))

    def test_book_filters_select_analytical_lines_and_keep_document_reference(self):
        doc=self.reviewed(extra={'items':[{'description':'A','cfop':'1102','ncm':'11111111','total':'30.00'},
                                         {'description':'B','cfop':'1403','ncm':'22222222','total':'70.00'}]})
        self.post(f'/documents/{doc["id"]}/book',self.booking(doc,generate_titles=False,lines=[]))
        result=self.client.get(self.path('fiscal-entries','&status=pending&direction=outgoing&ncm=11111111')).json()
        self.assertEqual('booked',result['filters']['status'])
        self.assertEqual('incoming',result['filters']['direction'])
        self.assertEqual(3000,result['totals']['total_cents'])
        self.assertEqual(10000,result['totals']['document_total_cents'])
        self.assertIn('linha fiscal permanece integral',result['scope_note'])
        selected=self.client.get(self.path('fiscal-items','&ncm=11111111')).json()
        self.assertEqual(3000,selected['totals']['item_total_cents'])

    def test_fiscal_filters_are_validated_instead_of_silently_ignored(self):
        for extra in ['&cfop=abc','&ncm=123','&status=cancelled','&direction=payable']:
            self.assertEqual(400,self.client.get(self.path('fiscal-documents',extra)).status_code)
        for extra in ['&query=ignored','&cfop=1102','&status=booked','&direction=incoming']:
            self.assertEqual(400,self.client.get(self.path('fiscal-assessments',extra)).status_code)
        report=self.client.get(self.path('fiscal-assessments')).json()
        self.assertIn('competências mensais',report['scope_note'])

    def test_model_print_permission_does_not_grant_download_or_other_area(self):
        cid=self.a['id']
        permissions=[{'company_id':cid,'routine':'accounting.reports','action':action,'effect':'allow'} for action in ['read','print']]
        response=self.client.post('/api/users',json={'username':'report-reader','password':'Senha-teste-12345','role':'custom','company_ids':[cid],'permissions':permissions})
        self.assertEqual(201,response.status_code,response.text)
        with TestClient(self.app) as client:
            session=client.post('/api/login',json={'username':'report-reader','password':'Senha-teste-12345'}).json()
            client.headers['X-CSRF-Token']=session['csrf_token']
            self.assertEqual(200,client.post('/api/context',json={'company_id':cid,'module':'accounting','period':'2026-11'}).status_code)
            catalog=client.get(self.scope('/report-models?module=accounting'))
            self.assertEqual(200,catalog.status_code,catalog.text)
            self.assertTrue(catalog.json())
            self.assertTrue(all(not m['kind'].startswith('fiscal-') for m in catalog.json()))
            self.assertEqual(403,client.get(self.scope('/report-models?module=fiscal')).status_code)
            path=self.path('diary','&model=internal-diary')
            self.assertEqual(200,client.get(path+'&format=pdf&purpose=print').status_code)
            for fmt in ['pdf','xlsx','csv']:
                self.assertEqual(403,client.get(path+'&format='+fmt).status_code)
            self.assertEqual(403,client.get(path+'&format=xlsx&purpose=print').status_code)
            self.assertEqual(403,client.get(self.path('fiscal-documents','&model=internal-fiscal-documents&format=pdf&purpose=print')).status_code)

    def test_preview_policy_allows_only_own_frames_and_pdf_blobs(self):
        response=self.client.get('/api/health')
        policy=response.headers['content-security-policy']
        self.assertIn("frame-src 'self' blob:",policy)
        self.assertIn("script-src 'self'",policy)
        self.assertIn("object-src 'none'",policy)
        self.assertIn("frame-ancestors 'none'",policy)
        self.assertEqual('DENY',response.headers['x-frame-options'])


if __name__=='__main__':unittest.main()
