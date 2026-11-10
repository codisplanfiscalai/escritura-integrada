"""Layout contracts use synthetic data, never client fiscal records."""
import copy
from io import BytesIO
import unittest

from pypdf import PdfReader

from app.core import DomainError
from app.fiscal_report_models import fiscal_pdf, FISCAL_MODEL_IDS
from app.fiscal_reports import FISCAL_REPORTS, TAXES


def sample(kind, count=1):
    row = {'document_id': 157, 'date': '2026-07-02', 'issue_date': '2026-07-01', 'document': 'NF-8871', 'model': '55',
           'series': '003', 'partner_name': 'Fornecedor <especial> & Filhos',
           'partner_tax_id': '12.345.678/0001-00', 'direction': 'incoming', 'cfop': '1102',
           'total_cents': 123456, 'status': 'booked', 'item': 1, 'description': 'Calçado <azul> & verde',
           'ncm': '64029990', 'quantity': '12.5000', 'unit': 'PAR', 'item_total_cents': 123456,
           'items': 3, 'items_without_value': 1, 'document_ids': [157, 158], 'documents': 2,
           'code': 'ITEM_VALUE', 'message': 'Conferir <total> & componentes', 'ledger_id': 99,
           'period': '2026-07', 'tax': 'ICMS', 'assessment_id': 79, 'opening_credit_cents': 103,
           'debit_cents': 200, 'credit_cents': 100, 'payable_cents': 0, 'carry_credit_cents': 3,
           'responsible': 'Operador <fiscal>', 'reason': 'Conferência & revisão concluídas'}
    for tax in TAXES:
        row[tax + '_base_cents'] = 10000 if tax == 'icms' else None
        row[tax + '_cents'] = 1800 if tax == 'icms' else None
    return {'kind': kind, 'title': FISCAL_REPORTS[kind], 'company_id': 7,
            'company_name': 'Empresa <teste> & Comércio', 'start': '2026-07-01', 'end': '2026-07-31',
            'rows': [copy.deepcopy(row) for _ in range(count)],
            'totals': {'documents': count, 'total_cents': 123456 * count},
            'scope_note': 'Relatório auxiliar. Valores declarados.',
            'filters': {'query': '<teste> & NF', 'status': 'booked', 'direction': 'incoming',
                        'cfop': '1102', 'ncm': '64029990'}}


def extract(result, **options):
    payload, mime = fiscal_pdf(result, **options)
    assert mime == 'application/pdf'
    doc = PdfReader(BytesIO(payload))
    return doc.pages, '\n'.join(page.extract_text() for page in doc.pages)


class FiscalModelTests(unittest.TestCase):
    def test_all_ten_models_titles_values_and_escape(self):
        self.assertEqual(len(FISCAL_MODEL_IDS), 10)
        for kind, title in FISCAL_REPORTS.items():
            with self.subTest(kind=kind):
                result = sample(kind)
                before = copy.deepcopy(result)
                doc, text = extract(result, first_page=42, show_numbers=True)
                self.assertIn(title, text)
                self.assertIn('Folha: 00042', text)
                self.assertIn('Empresa <teste> & Comércio', text)
                self.assertIn('Layout de referência não homologado Prosoft', text)
                self.assertIn('Totalizadores da seleção', text)
                self.assertIn('Seq.', text)
                self.assertEqual(result, before)
                self.assertEqual(doc[0].mediabox.width > doc[0].mediabox.height, True)

    def test_columns_and_tax_coverage(self):
        result = sample('fiscal-taxes', 2)
        result['rows'][1]['icms_cents'] = None
        result['rows'][1]['icms_base_cents'] = 0
        doc, text = extract(result)
        for expected in ['CPF/CNPJ', 'Série', 'Modelo', '1.234,56', '100,00', '18,00',
                         'Não informado', '1 / 2', '2 / 2', '0 / 2', 'IBS', 'CBS',
                         'Fornecedor <especial> & Filhos', 'Filtros efetivos: Busca: <teste> & NF']:
            self.assertIn(expected, text)
        self.assertNotIn('icms_base_cents', text)

    def test_entry_and_output_issue_dates_and_declared_taxes(self):
        for kind in ['fiscal-entries', 'fiscal-outputs']:
            result = sample(kind)
            result['rows'][0]['ipi_cents'] = 0
            _, text = extract(result)
            for expected in ['Emissão', '01/07/2026', '02/07/2026', 'ICMS', 'IPI',
                             '100,00', '18,00', '0,00', 'Não informado']:
                self.assertIn(expected, text)
            self.assertNotIn('COFINS', text)

    def test_all_missing_items_never_presented_as_zero(self):
        for kind in ['fiscal-items', 'fiscal-operations', 'fiscal-classifications']:
            result = sample(kind)
            result['rows'][0].update(item_total_cents=None if kind == 'fiscal-items' else 0,
                                     items=3, items_without_value=3)
            result['totals'] = {'items': 3, 'items_without_value': 3, 'item_total_cents': 0}
            _, text = extract(result)
            self.assertIn('Não informado', text)
            self.assertNotIn('0,00', text)

    def test_assessments_show_actual_selection_and_traceability(self):
        _, text = extract(sample('fiscal-assessments'))
        for expected in ['Competência', 'Crédito anterior', 'Débitos', 'Créditos', 'A recolher',
                         'Crédito a transportar', 'Responsável', 'Justificativa',
                         'Operador <fiscal>', 'Conferência & revisão concluídas',
                         'não se aplicam a este livro', '2026-07 a 2026-07']:
            self.assertIn(expected, text)
        self.assertNotIn('Busca: <teste>', text)

    def test_multipage_repeated_headers(self):
        for kind in FISCAL_REPORTS:
            with self.subTest(kind=kind):
                result = sample(kind, 70)
                doc, text = extract(result, first_page=8)
                self.assertGreater(len(doc), 1)
                for index, page in enumerate(doc):
                    page_text = page.extract_text()
                    self.assertIn(FISCAL_REPORTS[kind], page_text)
                    self.assertIn('Empresa <teste> & Comércio', page_text)
                    self.assertIn(f'Folha: {8 + index:05d}', page_text)
                self.assertNotIn('Seq.', text)

    def test_extra_long_cells_split_across_pages_without_losing_tail(self):
        for kind, key in [('fiscal-items', 'description'), ('fiscal-inconsistencies', 'message'),
                          ('fiscal-assessments', 'reason'), ('fiscal-documents', 'partner_name')]:
            result = sample(kind)
            result['rows'][0][key] = ('Descrição extensa & <campo> ' * 500) + 'MARCADOR_FINAL'
            doc, text = extract(result)
            self.assertGreater(len(doc), 1)
            self.assertIn('MARCADOR_FINAL', text)

    def test_empty_results_and_validation(self):
        for kind in FISCAL_REPORTS:
            result = sample(kind, 0)
            _, text = extract(result)
            self.assertIn('Sem registros para a seleção efetiva.', text)
        for first_page in [0, 100000, -1, 1.5, True, '1', None]:
            with self.assertRaises(DomainError):
                fiscal_pdf(sample('fiscal-documents'), first_page=first_page)
        _, text = extract(sample('fiscal-documents'), first_page=99999)
        self.assertIn('Folha: 99999', text)
        with self.assertRaises(DomainError):
            fiscal_pdf({'kind': 'unsupported'})
        with self.assertRaisesRegex(DomainError, 'excede o limite'):
            fiscal_pdf(sample('fiscal-documents', 70), first_page=99999)


if __name__ == '__main__':
    unittest.main()
