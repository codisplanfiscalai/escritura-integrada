"""Reference-backed presentation rules using only synthetic records."""
from copy import deepcopy
import unittest

from app.fiscal_book_models import _book_observations, _cfop_wording
from test_fiscal_book_models import sample, render


class FiscalBookEvidenceTests(unittest.TestCase):
    def test_noncredited_ipi_stays_on_existing_partition(self):
        result=sample(True,6)
        for row,amount in zip(result['rows'],(111,222,333,444,555,666)):
            row['declared_ipi_cents']=amount
            row['book_ipi_cents']=0
            row['declared_tax_coverage']={'ipi':{'complete':True}}
        before=deepcopy(result)
        _,text=render(result)
        for amount in ('1,11','2,22','3,33','4,44','5,55','6,66'):
            self.assertIn('IPI não creditado: '+amount,text)
        self.assertEqual(before,result)
        self.assertEqual(6,text.count('IPI não creditado:'))
        self.assertEqual(1,text.count('0000081234'))
        self.assertIn('7.407,36',text)

    def test_noncredited_ipi_requires_complete_known_authorized_amount(self):
        base=sample()['rows'][0]
        base.update(declared_ipi_cents=1234,book_ipi_cents=0)
        for change in ({'declared_ipi_cents':None},{'declared_ipi_cents':0},
                       {'book_ipi_cents':None},{'book_ipi_cents':1234},
                       {'treatment':{}},{'treatment':'Cancelada conforme livro'},
                       {'treatment':{'book_mode':'declared_icms'}},
                       {'pending':['INVALID_FISCAL_TREATMENT']},
                       {'pending':['DECLARED_IPI_INCOMPLETE']},
                       {'declared_tax_coverage':{'ipi':{'complete':False}}},
                       {'document_state':'cancelled'}):
            with self.subTest(change=change):
                self.assertNotIn('IPI não creditado',_book_observations(base|change))
        # Never infer IPI from the difference between accounting and book amounts.
        self.assertNotIn('IPI não creditado',_book_observations(base|{'declared_ipi_cents':None,'book_other_cents':1}))

    def test_pending_messages_are_operational_and_codes_preserved_in_input(self):
        result=sample();result['rows'][0]['pending']=['FISCAL_TREATMENT_REQUIRED','UNKNOWN_FUTURE_CODE']
        before=deepcopy(result);_,text=render(result)
        self.assertIn('Tratamento fiscal do livro não definido.',text)
        self.assertIn('Pendência fiscal não reconhecida',' '.join(text.split()))
        self.assertNotIn('FISCAL_TREATMENT_REQUIRED',text)
        self.assertNotIn('UNKNOWN_FUTURE_CODE',text)
        self.assertNotIn('modelo auxiliar',text)
        self.assertEqual(before,result)

    def test_cfop_summary_groups_descriptions_and_subtotals(self):
        result=sample(False,3)
        result['rows'][0]['cfop']='5102'
        result['rows'][1]['cfop']='6202'
        result['rows'][2]['cfop']='6202'
        pdf,_=render(result)
        text='\n'.join(p.extract_text() for p in pdf.pages if 'RESUMO POR CFOP' in p.extract_text())
        self.assertIn('5000 - SAÍDAS',text);self.assertIn('6000 - SAÍDAS',text)
        self.assertIn('6202 - Devolução de compra para comercialização,',text)
        self.assertEqual(2,text.count('SUB-TOTAL'))
        self.assertIn('2.469,12',text);self.assertIn('3.703,68',text)
        # A missing amount invalidates its subtotal, not the accounting total.
        result['rows'][2]['book_other_cents']=None
        pdf,_=render(result);text=pdf.pages[-1].extract_text()
        self.assertEqual(2,text.count('2.469,12'))

    def test_catalog_wording_requires_period_coverage(self):
        self.assertEqual('',_cfop_wording('9999','2026-01-01','2026-01-31'))
        self.assertEqual('',_cfop_wording('2102','2020-01-01','2026-01-31'))
        self.assertIn('Compra para comercialização',_cfop_wording('2102','2026-01-01','2026-01-31'))
