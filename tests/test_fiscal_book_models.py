"""Synthetic contracts for reference book presentation; no client fixtures."""
from copy import deepcopy
from io import BytesIO
import unittest
from pypdf import PdfReader
from app.core import DomainError
from app.fiscal_book_models import BOOK_MODELS, ENTRY_CODE_LEGEND, fiscal_book_pdf, _book_values, _series


def sample(incoming=True,count=1):
    row={'document_id':1,'document':'81234','model':'55','series':'4','date':'2026-09-09','issue_date':'2026-08-21',
         'partner_name':'Fornecedor sintético de teste','partner_tax_id':'12345678000199','partner_state':'ES','partner_ie':'IE-TESTE',
         'cfop':'2102' if incoming else '5102','total_cents':123456,'book_base_cents':0,'book_icms_cents':0,'book_other_cents':123456,
         'book_ipi_cents':0,'declared_icms_cents':19999,'rate':'18','treatment':{'book_mode':'other_excluding_ipi'},'pending':[]}
    return {'kind':'fiscal-entries' if incoming else 'fiscal-outputs','company_name':'Empresa sintética','company_code':'TESTE',
            'company_tax_id':'99887766000111','company_ie':'IE-EMPRESA','start':'2026-09-01','end':'2026-09-30',
            'rows':[dict(deepcopy(row),document=str(81234+i),document_id=i+1) for i in range(count)],
            'filters':{'cfop':row['cfop'],'status':'booked','direction':'incoming' if incoming else 'outgoing'}}


def render(result,first_page=2):
    model='reference-entries-p1a-v1' if result['kind']=='fiscal-entries' else 'reference-outputs-p2a-v1'
    raw,mime=fiscal_book_pdf(result,model,first_page)
    assert mime=='application/pdf'
    pdf=PdfReader(BytesIO(raw));return pdf,'\n'.join(p.extract_text() for p in pdf.pages)


class FiscalBookModelTests(unittest.TestCase):
    def test_max_series_width_reserves_height_across_page_breaks(self):
        for incoming in (True,False):
            result=sample(incoming,40)
            result['series_digits']=20
            before=deepcopy(result)
            pdf,text=render(result)
            self.assertGreater(len(pdf.pages),2)
            parts=[]
            def visit(value,cm,tm,font,size):
                a,b=(121,140) if incoming else (99,130)
                if a <= tm[4] <= b and 70 <= tm[5] <= 440 and value.strip().isdigit():
                    parts.append(value.strip())
            for page in pdf.pages:
                page.extract_text(visitor_text=visit)
            self.assertEqual('4'.zfill(20)*40,''.join(parts))
            self.assertIn('49.382,40',text)
            self.assertIn('A Transportar',text)
            self.assertIn('De Transporte',text)
            self.assertEqual(before,result)

    def test_series_uses_company_width_in_both_books_without_mutation(self):
        for incoming in (True,False):
            for value,digits,expected in [('4',3,'004'),('4',5,'00004'),
                                          ('123456',3,'123456'),('0004',3,'0004'),
                                          ('',3,''),(None,3,''),('AB4',3,'AB4'),(0,3,'000')]:
                with self.subTest(incoming=incoming,value=value,digits=digits):
                    result=sample(incoming)
                    result['series_digits']=digits
                    result['rows'][0]['series']=value
                    before=deepcopy(result)
                    pdf,_=render(result)
                    self.assertEqual(expected,_series(value,digits))
                    # Read only the series cell; a blank must not become 000.
                    texts=[]
                    def visit(text,cm,tm,font,size):
                        a,b=(121,140) if incoming else (99,130)
                        if a <= tm[4] <= b and 420 <= tm[5] <= 440:
                            texts.append(text.strip())
                    pdf.pages[0].extract_text(visitor_text=visit)
                    self.assertEqual(expected,''.join(texts))
                    self.assertEqual(before,result)

    def test_entry_code_legend_repeats_without_assigning_missing_treatment(self):
        result=sample(True,90)
        result['rows'][0]['treatment']={}
        before=deepcopy(result)
        pdf,_=render(result)
        self.assertGreater(len(pdf.pages),2)
        for page in pdf.pages:
            text=page.extract_text()
            for label in ENTRY_CODE_LEGEND:
                self.assertEqual(1,text.count(label))
        self.assertEqual(before,result)
        self.assertEqual('',_book_values(result['rows'][0])['code'])
        # The codes are an entries-model key, not a new outgoing-book feature.
        _,text=render(sample(False))
        self.assertNotIn(ENTRY_CODE_LEGEND[0],text)

    def test_headers_identity_columns_and_no_mutation(self):
        for incoming in (True,False):
            result=sample(incoming);before=deepcopy(result);pdf,text=render(result)
            self.assertEqual(before,result)
            self.assertEqual((842,595),(pdf.pages[0].mediabox.width,pdf.pages[0].mediabox.height))
            for token in ('MODELO P1/A' if incoming else 'MODELO P2/A','0000081234','IE-EMPRESA','ES','EM HOMOLOGAÇÃO',
                          '1.234,56','0,0000','RESUMO POR CFOP','TOTAL GERAL','000002','000003'):
                self.assertIn(token,text)
            self.assertNotIn('199,99',text) # Declared XML ICMS is not a book credit.
            if incoming:
                for token in ('IE-TESTE','Fornecedor sintético de teste','09/09/2026','21/08/2026','ICMS'):
                    self.assertIn(token,text)
            self.assertIn('cfop='+result['rows'][0]['cfop'],text)

    def test_transport_is_cumulative_and_summary_does_not_duplicate_lines(self):
        for incoming in (True,False):
            result=sample(incoming,90);pdf,text=render(result)
            self.assertGreater(len(pdf.pages),2)
            self.assertIn('A Transportar',text);self.assertIn('De Transporte',text)
            self.assertIn('111.110,40',text)
            for i,page in enumerate(pdf.pages):
                self.assertIn(f'{i+2:06d}',page.extract_text())
                self.assertIn('EM HOMOLOGAÇÃO',page.extract_text())
            # One analytical identity per source line; P2/A intentionally repeats initial/final.
            self.assertEqual(1 if incoming else 2,text.count('0000081234'))

    def test_missing_is_not_zero_and_mixed_partial_total_is_blank(self):
        result=sample(True,2)
        for key in ('book_base_cents','book_icms_cents','book_other_cents','book_ipi_cents'):
            result['rows'][1][key]=None
        result['rows'][1]['treatment']={};result['rows'][1]['rate']='99'
        values=_book_values(result['rows'][1])
        self.assertIsNone(values['operation']);self.assertEqual('',values['rate'])
        pdf,text=render(result)
        self.assertNotIn('99,0000',text)
        # The CFOP summary leaves an incomplete amount blank rather than summing known rows.
        summary=pdf.pages[-1].extract_text()
        self.assertNotIn('1.234,56',summary)
        self.assertIn('2.469,12',summary)
        self.assertNotIn('0,00',summary)

    def test_declared_icms_requires_the_existing_explicit_treatment(self):
        row=sample()['rows'][0]
        row.update(treatment={'book_mode':'declared_icms'},book_base_cents=100000,book_icms_cents=18000,book_other_cents=None)
        v=_book_values(row)
        self.assertEqual('1',v['code']);self.assertEqual('18,0000',v['rate']);self.assertEqual(100000,v['operation'])
        row['treatment']={}
        self.assertEqual('',_book_values(row)['code']);self.assertEqual('',_book_values(row)['rate'])

    def test_cancelled_zero_remains_identified_without_claiming_electronic_source(self):
        result=sample(False);row=result['rows'][0]
        row.update(document_state='cancelled',treatment='Cancelada conforme livro validado; sem evento eletrônico',total_cents=0,book_base_cents=0,book_icms_cents=0,book_other_cents=0)
        _,text=render(result)
        self.assertIn('***CANCELADA***',text);self.assertIn('0,00',text)
        self.assertNotIn('18,0000',text);self.assertIn('sem validação eletrônica/SEFAZ',text)

    def test_print_order_is_date_numeric_number_series_and_stable_lines(self):
        result=sample(False,3)
        result['rows'][0].update(document='10',series='1')
        result['rows'][1].update(document='2',series='1')
        result['rows'][2].update(document='2',series='1')
        original=deepcopy(result)
        pdf,text=render(result)
        page=pdf.pages[0].extract_text()
        self.assertLess(page.index('0000000002'),page.index('0000000010'))
        self.assertEqual(4,page.count('0000000002'))
        self.assertEqual(original,result)

    def test_summary_continuations_repeat_titles_and_columns(self):
        result=sample(False,60)
        for i,row in enumerate(result['rows']):row['cfop']=str(5100+i)
        pdf,text=render(result)
        summaries=[p.extract_text() for p in pdf.pages if 'RESUMO POR CFOP' in p.extract_text()]
        self.assertGreater(len(summaries),1)
        for page in summaries:
            for token in ('CFOP','Valor Contábil','Base de Cálculo','Imposto','Outras'):
                self.assertIn(token,page)
        self.assertIn('CONTINUAÇÃO',summaries[-1])

    def test_large_amounts_are_atomic_and_oversize_headers_fail_explicitly(self):
        for incoming in (True,False):
            result=sample(incoming,2)
            for row in result['rows']:
                row.update(total_cents=123456789012,book_other_cents=123456789012)
            _,text=render(result)
            self.assertIn('1.234.567.890,12',text)
            self.assertIn('2.469.135.780,24',text)
            result['company_name']='Nome extenso ' * 100
            with self.assertRaisesRegex(DomainError,'cabeçalho'):render(result)
            result=sample(incoming);result['filters']['query']='Busca extensa ' * 300
            with self.assertRaisesRegex(DomainError,'rodapé'):render(result)

    def test_validation_empty_and_pagination_overflow(self):
        for incoming in (True,False):
            pdf,text=render(sample(incoming,0),99999)
            self.assertEqual(1,len(pdf.pages));self.assertIn('Sem registros',text)
            for value in (0,100000,True,1.2,'2'):
                with self.assertRaises(DomainError):render(sample(incoming),value)
            with self.assertRaisesRegex(DomainError,'excede'):render(sample(incoming),99999)
        with self.assertRaises(DomainError):fiscal_book_pdf(sample(), 'reference-outputs-p2a-v1')

    def test_long_source_text_is_not_truncated(self):
        result=sample();result['rows'][0]['partner_name']='Nome extenso '*35+'MARCADOR-FINAL'
        _,text=render(result);self.assertIn('MARCADOR-FINAL',text)
        result['rows'][0]['partner_name']='Nome extenso '*300
        with self.assertRaisesRegex(DomainError,'sem truncamento'):render(result)
