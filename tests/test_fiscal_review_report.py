"""Operational fiscal diagnostics use synthetic data only."""
import io
import unittest
from pypdf import PdfReader
import test_business as base
from app.fiscal_review_messages import fiscal_review


class FiscalReviewReportTests(unittest.TestCase):
    setUp=base.BusinessTests.setUp;tearDown=base.BusinessTests.tearDown
    create_company=base.BusinessTests.create_company;scope=base.BusinessTests.scope
    activate=base.BusinessTests.activate;document=base.BusinessTests.document
    journal=base.BusinessTests.journal;post=base.BusinessTests.post
    reviewed=base.BusinessTests.reviewed;booking=base.BusinessTests.booking

    def report(self,kind,extra=''):
        response=self.client.get(self.scope(f'/business-reports/{kind}?start=2026-11-01&end=2026-11-30'+extra))
        self.assertEqual(200,response.status_code,response.text[:200]);return response

    def create_book(self,number,split=False,profile=None,second_cfop='6202'):
        values=[('40.00','4.00'),('60.00','7.00')] if split else [('100.00','7.00')]
        data={'number':number,'direction':'outgoing','items':[{'number':str(i),'description':'Item sintético',
            'cfop':'6202' if i==1 else second_cfop,'ncm':'61091000' if i==1 else '61099000','total':amount,'taxes':{'ICMS/ICMS00/pICMS':rate,'ICMS/ICMS00/vBC':amount,'ICMS/ICMS00/vICMS':'1.00'}}
            for i,(amount,rate) in enumerate(values,1)]}
        if profile:data['fiscal_treatment']=profile
        d=self.reviewed(extra=data)
        self.post(f'/documents/{d["id"]}/book',self.booking(d,generate_titles=False,lines=[]))
        return d

    def test_booked_lifecycle_and_unconfigured_fiscal_lines_are_distinct(self):
        for i in range(4):self.create_book(str(800+i),split=i==0)
        book=self.report('fiscal-outputs').json();before=self.core.documents(self.a['id'])
        self.assertEqual(4,book['totals']['documents']);self.assertEqual(5,book['totals']['lines_with_pending'])
        self.assertTrue(all(d['status']=='booked' for d in before))
        findings=self.report('fiscal-inconsistencies').json()
        missing=[r for r in findings['rows'] if r['code']=='FISCAL_TREATMENT_REQUIRED']
        self.assertEqual(4,len(missing));self.assertEqual(5,sum(len(r['line_numbers']) for r in missing))
        self.assertEqual(4,findings['totals']['documents_with_findings'])
        self.assertFalse(any(r['code']=='NOT_BOOKED' for r in findings['rows']))
        self.assertTrue(all('perfil de escrituração' in r['next_step'] for r in missing))
        self.assertEqual(before,self.core.documents(self.a['id']))
        self.assertTrue(all(r['book_icms_cents'] is None for r in book['rows']))

    def test_findings_preserve_book_line_filters(self):
        self.create_book('850',split=True,second_cfop='5102')
        for extra in ('&cfop=6202','&ncm=61091000'):
            with self.subTest(extra=extra):
                selection=extra+'&status=booked&direction=outgoing'
                book=self.report('fiscal-outputs',selection).json()
                findings=self.report('fiscal-inconsistencies',selection).json()
                pending=[r for r in findings['rows'] if r['code']=='FISCAL_TREATMENT_REQUIRED']
                self.assertEqual(1,len(book['rows']))
                self.assertEqual([book['rows'][0]['line']],pending[0]['line_numbers'])

    def test_explicit_treatment_removes_only_that_criticism(self):
        profile={'code':'synthetic','book_mode':'other_excluding_ipi','source':'Fonte sintética',
            'responsible':'Teste','valid_from':'2026-01-01','valid_to':''}
        self.create_book('900',profile=profile)
        findings=self.report('fiscal-inconsistencies').json()
        self.assertFalse(any(r['code']=='FISCAL_TREATMENT_REQUIRED' for r in findings['rows']))
        row=self.report('fiscal-outputs').json()['rows'][0]
        self.assertEqual(0,row['book_icms_cents'])
        self.assertGreater(row['declared_icms_cents'],0)

    def test_default_and_retired_urls_resolve_to_reference_book(self):
        self.create_book('901')
        catalog=self.client.get(self.scope('/report-models')).json()
        self.assertNotIn('internal-fiscal-outputs',[m['id'] for m in catalog])
        self.assertNotIn('internal-fiscal-entries',[m['id'] for m in catalog])
        original=self.report('fiscal-outputs').json()
        self.assertEqual('reference-outputs-p2a-v1',original['model'])
        for model in ('internal','internal-fiscal-outputs','reference-outputs-p2a-v1'):
            data=self.report('fiscal-outputs','&model='+model).json()
            self.assertEqual(original['rows'],data['rows']);self.assertEqual(original['totals'],data['totals'])
            pdf=self.report('fiscal-outputs','&model='+model+'&format=pdf').content
            text=' '.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
            self.assertIn('MODELO P2/A',text);self.assertIn('Tratamento fiscal do livro não definido.',text)
            self.assertNotIn('FISCAL_TREATMENT_REQUIRED',text)
        self.assertEqual(200,self.report('fiscal-outputs','&format=xlsx').status_code)

    def test_unknown_and_partial_review_messages_are_not_false_zero(self):
        self.assertIn('não reconhecida',fiscal_review('FUTURE_CODE')['message'])
        self.assertIn('base do ICMS',fiscal_review('DECLARED_ICMS_BASE_INCOMPLETE')['message'])
        self.assertIn('parcial',fiscal_review('DECLARED_IPI_INCOMPLETE')['next_step'])
