"""Contrato de impressão baseado em campos; não testa paridade Prosoft ausente."""
from copy import deepcopy
from io import BytesIO
import unittest
from pypdf import PdfReader
from app.accounting_report_models import COLUMNS, accounting_pdf
from app.report_models import CATALOG, report_model_pdf
from app.fiscal_reports import FISCAL_REPORTS
from app.core import DomainError


def fixture(kind='diary', count=2):
    return {'kind':kind, 'company_name':'EMPRESA SINTÉTICA DE TESTE', 'company_code':'123',
            'company_tax_id':'12345678000190', 'start':'2026-01-01', 'end':'2026-01-31',
            'scope_note':'ESCOPO CONFERÍVEL', 'filters':{'query':'DOCUMENTO-TESTE'},
            'rows':[{'date':'2026-01-02', 'number':i, 'document':'DOCUMENTO-TESTE',
                     'access_code':'001', 'classifier':'1.01.001', 'account_name':'Caixa',
                     'history':'Histórico completo <sem marcação> & válido', 'debit_cents':12345,
                     'credit_cents':0, 'opening_cents':-200, 'closing_cents':12145,
                     'balance_cents':12145, 'result_cents':-12345, 'report_group':'asset',
                     'cost_center_id':1, 'cost_center_name':'Administração', 'journal_ids':[i],
                     'custom_trace':'RASTRO FINAL '+str(i)} for i in range(1,count+1)],
            'totals':{'debit_cents':count*12345, 'credit_cents':0}}


def extract(data):
    return '\n'.join(page.extract_text() for page in PdfReader(BytesIO(data)).pages)


class AccountingModelTests(unittest.TestCase):
    def test_all_kinds_keep_values_filters_and_extra_fields(self):
        for kind in COLUMNS:
            with self.subTest(kind=kind):
                result=fixture(kind); before=deepcopy(result)
                data,mime=report_model_pdf(result,'internal-'+kind,first_page=7)
                text=extract(data)
                for expected in ['Folha: 00007','layout não homologado','ESCOPO CONFERÍVEL',
                                 'DOCUMENTO-TESTE','RASTRO FINAL 2','123,45','246,90','Caixa']:
                    self.assertIn(expected,text)
                self.assertEqual(mime,'application/pdf')
                self.assertEqual(result,before)

    def test_catalog_supported_and_unique(self):
        ids=[m['id'] for m in CATALOG]
        self.assertEqual(len(ids),len(set(ids)))
        for kind in list(COLUMNS)+list(FISCAL_REPORTS):
            model=next(m for m in CATALOG if m['id']=='internal-'+kind)
            self.assertTrue(model['supported'])
            self.assertEqual(model['status'],'field_based_not_homologated')

    def test_invalid_selection_and_page(self):
        for page in [0,100000,True,1.5,'2']:
            with self.assertRaises(DomainError):
                report_model_pdf(fixture(),'internal-diary',first_page=page)
        for model in ['missing','internal-trial-balance','prosoft-ledger-v1']:
            with self.assertRaises(DomainError):
                report_model_pdf(fixture(),model)

    def test_page_continuation_and_long_history(self):
        result=fixture(count=48)
        result['rows'][0]['history']='INICIO ' + 'histórico longo ' * 600 + ' FIM-HISTORICO'
        data,_=accounting_pdf(result,first_page=41)
        pages=PdfReader(BytesIO(data)).pages
        self.assertGreater(len(pages),3)
        for number,page in enumerate(pages,41):
            self.assertIn(f'Folha: {number:05d}',page.extract_text())
        text=extract(data)
        self.assertIn('FIM-HISTORICO',text)
        self.assertIn('RASTRO FINAL 48',text)
        self.assertIn('Continuação',text)

    def test_empty_has_header_and_totals(self):
        text=extract(accounting_pdf(fixture(count=0))[0])
        self.assertIn('Nenhum registro',text)
        self.assertIn('Totais do escopo',text)

    def test_page_overflow_rejected(self):
        with self.assertRaises(DomainError):
            accounting_pdf(fixture(count=48),first_page=99999)

    def test_filtered_ledger_uses_full_balance(self):
        result=fixture('ledger',count=1)
        row=result['rows'][0]
        row['balance_cents']=99999
        result['ledger_groups']=[{'access_code':'001','classifier':'1.01','account_name':'Caixa',
                                  'opening_cents':200,'closing_cents':88888,'filtered':True,'rows':[row]}]
        text=extract(report_model_pdf(result,'prosoft-ledger-v1')[0])
        self.assertIn('999,99',text)
        self.assertIn('888,88',text)
        self.assertIn('Pesquisa restringe movimentos exibidos',text)


if __name__=='__main__':
    unittest.main()
