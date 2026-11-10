"""Analytical ledger/export integration, with exclusively synthetic fiscal data."""
import io
import unittest
from openpyxl import load_workbook
from pypdf import PdfReader
import test_business as base


class AnalyticalReportTests(unittest.TestCase):
    setUp = base.BusinessTests.setUp
    tearDown = base.BusinessTests.tearDown
    create_company = base.BusinessTests.create_company
    scope = base.BusinessTests.scope
    activate = base.BusinessTests.activate
    document = base.BusinessTests.document
    post = base.BusinessTests.post
    reviewed = base.BusinessTests.reviewed
    booking = base.BusinessTests.booking
    journal = base.BusinessTests.journal

    def book(self, direction='incoming', same_cfop=False):
        items = []
        for index, (total, cfop, origin, rate, ncm) in enumerate([
            ('30.00', '1102', '1', '4.00', '11111111'),
            ('70.00', '1102' if same_cfop else '1403', '0', '12.00', '22222222')], 1):
            items.append({'number': str(index), 'description': 'Item sintético', 'total': total,
                          'cfop': cfop, 'ncm': ncm, 'cst_icms': '00',
                          'taxes': {'ICMS/ICMS00/orig': origin, 'ICMS/ICMS00/pICMS': rate,
                                    'ICMS/ICMS00/vBC': total, 'ICMS/ICMS00/vICMS': '1.20'}})
        d = self.reviewed(extra={'direction': direction, 'items': items})
        self.post(f"/documents/{d['id']}/book", self.booking(d, generate_titles=False, lines=[]))
        return d

    def report(self, extra='', kind='fiscal-entries'):
        response = self.client.get(self.scope(f'/business-reports/{kind}?start=2026-11-01&end=2026-11-30' + extra))
        self.assertEqual(200, response.status_code, response.text[:200] if response.status_code != 200 else '')
        return response

    def test_document_header_once_and_split_cfop_totals(self):
        self.book()
        r = self.report().json()
        self.assertEqual('analytical_posting_lines', r['row_scope'])
        self.assertEqual(1, r['totals']['documents'])
        self.assertEqual(2, r['totals']['lines'])
        self.assertEqual([3000, 7000], [x['total_cents'] for x in r['rows']])
        self.assertEqual(10000, r['totals']['total_cents'])
        self.assertEqual(10000, r['document_headers'][0]['total_cents'])
        self.assertTrue(all(x['book_icms_cents'] is None for x in r['rows']))
        self.assertIsNone(r['totals']['book_other_cents'])
        self.assertIsNone(r['totals']['declared_ipi_cents'])
        self.assertEqual(0, r['totals']['ipi_allocated_cents'])
        self.assertEqual(240, r['totals']['declared_icms_cents'])
        self.assertEqual(10000, r['totals']['declared_icms_base_cents'])
        filtered = self.report('&cfop=1403').json()
        self.assertEqual(1, filtered['totals']['lines'])
        self.assertEqual(7000, filtered['totals']['total_cents'])
        self.assertEqual(10000, filtered['totals']['document_total_cents'])
        self.assertEqual([], self.report('&cfop=9999').json()['rows'])

    def test_same_cfop_origin_and_rate_stay_distinct_and_output(self):
        self.book(direction='outgoing', same_cfop=True)
        self.assertEqual([], self.report().json()['rows'])
        result = self.report(kind='fiscal-outputs').json()
        self.assertEqual(2, result['totals']['lines'])
        self.assertEqual({'0', '1'}, {x['origin'] for x in result['rows']})
        self.assertEqual(1, result['totals']['documents'])
        by_ncm = self.report('&ncm=11111111', 'fiscal-outputs').json()
        self.assertEqual(3000, by_ncm['totals']['total_cents'])
        self.assertIn('Não há rateio adicional por NCM', by_ncm['scope_note'])

    def test_analytical_pdf_and_excel_keep_book_and_source_separate(self):
        self.book()
        pdf = self.report('&format=pdf').content
        text = ' '.join(' '.join(p.extract_text().split()) for p in PdfReader(io.BytesIO(pdf)).pages)
        for label in ['Cabeçalhos dos documentos', 'Linhas analíticas do livro', 'Outras livro',
                      'IPI livro', 'IPI declarado', 'não são crédito do livro', 'Origem ICMS']:
            self.assertIn(label, text)
        wb = load_workbook(io.BytesIO(self.report('&format=xlsx').content))
        self.assertEqual(2, wb['Cabeçalhos documentos'].max_row)
        self.assertEqual(3, wb['Dados'].max_row)
        headers = [c.value for c in wb['Dados'][1]]
        self.assertIn('Valor contábil da linha (R$)', headers)
        self.assertIn('ICMS livro (R$)', headers)
        self.assertIn('ICMS declarado (R$)', headers)
        values = [wb['Dados'].cell(row, headers.index('Valor contábil da linha (R$)') + 1).value for row in [2, 3]]
        self.assertEqual([30, 70], values)

    def test_operational_document_report_remains_documental(self):
        self.book()
        result = self.report('&cfop=1403', 'fiscal-documents').json()
        self.assertEqual(1, len(result['rows']))
        self.assertEqual(10000, result['totals']['total_cents'])
        self.assertNotIn('row_scope', result)
        self.assertIn('valores documentais permanecem integrais', result['scope_note'])

    def test_reversal_excludes_document_from_book(self):
        d = self.book()
        current = self.core.documents(self.a['id'])[0]
        self.post(f"/documents/{d['id']}/reverse", {'version': current['version'],
                  'reason': 'Revisão sintética', 'date': '2026-11-07', 'idempotency_key': 'reverse-book'})
        result = self.report().json()
        self.assertEqual(0, result['totals']['documents'])
        self.assertEqual(0, result['totals']['lines'])
        self.assertEqual([], result['document_headers'])
        self.assertIsNone(result['totals']['book_icms_cents'])

    def test_ncm_selects_whole_fiscal_line_and_preserves_both_ncms(self):
        d = self.reviewed(extra={'items': [
            {'description': 'A', 'total': '30.00', 'cfop': '1102', 'ncm': '11111111'},
            {'description': 'B', 'total': '70.00', 'cfop': '1102', 'ncm': '22222222'}]})
        self.post(f"/documents/{d['id']}/book", self.booking(d, generate_titles=False, lines=[]))
        result = self.report('&ncm=11111111').json()
        self.assertEqual(1, result['totals']['lines'])
        self.assertEqual(10000, result['totals']['total_cents'])
        self.assertEqual(['11111111', '22222222'], result['rows'][0]['ncms'])

    def test_explicit_profile_keeps_ipi_disclosure_separate_from_book_credit(self):
        profile = {'code': 'synthetic', 'book_mode': 'other_excluding_ipi',
                   'source': 'Decisão sintética para teste', 'responsible': 'Teste',
                   'valid_from': '2026-01-01', 'valid_to': ''}
        d = self.reviewed(extra={'total': '110.00', 'fiscal_treatment': profile,
            'items': [{'description': 'Item com IPI', 'cfop': '1102', 'total': '100.00',
                       'taxes': {'IPI/IPITrib/vIPI': '10.00', 'ICMS/ICMS00/vICMS': '12.00'}}]})
        self.post(f"/documents/{d['id']}/book", self.booking(d, generate_titles=False, lines=[]))
        result = self.report().json()
        row = result['rows'][0]
        self.assertEqual(11000, row['total_cents'])
        self.assertEqual(1000, row['declared_ipi_cents'])
        self.assertEqual(1200, row['declared_icms_cents'])
        self.assertEqual(0, row['book_ipi_cents'])
        self.assertEqual(0, row['book_icms_cents'])
        self.assertEqual(0, row['book_base_cents'])
        self.assertEqual(10000, row['book_other_cents'])
        self.assertEqual(profile, row['treatment'])

    def test_reviewed_consolidation_preserves_complete_classifications_and_exports(self):
        profile = {'code': 'synthetic', 'book_mode': 'other_excluding_ipi',
                   'source': 'Decisão sintética', 'responsible': 'Teste',
                   'valid_from': '2026-01-01', 'valid_to': ''}
        review = {'mode': 'consolidate', 'item_groups': {'1': 'GRUPO-A', '2': 'GRUPO-A'},
                  'source': 'Fonte sintética de agrupamento', 'responsible': 'Revisor sintético',
                  'reason': 'Consolidação revisada de duas classificações'}
        items = [{'number': str(i), 'description': 'Item sintético', 'cfop': '1102',
                  'total': amount, 'taxes': {'ICMS/ICMS00/CST': cst, 'ICMS/ICMS00/orig': origin,
                  'ICMS/ICMS00/pICMS': rate, 'ICMS/ICMS00/vBC': amount, 'ICMS/ICMS00/vICMS': '1.00'}}
                 for i, amount, cst, origin, rate in [(1, '30.00', '00', '1', '4.00'),
                                                     (2, '70.00', '20', '0', '12.00')]]
        d = self.reviewed(extra={'fiscal_treatment': profile, 'posting_group_review': review, 'items': items})
        self.post(f"/documents/{d['id']}/book", self.booking(d, generate_titles=False, lines=[]))
        result = self.report().json()
        row, = result['rows']
        self.assertEqual(1, result['totals']['lines'])
        self.assertEqual(10000, row['total_cents'])
        self.assertEqual(10000, row['book_other_cents'])
        self.assertEqual(200, row['declared_icms_cents'])
        self.assertEqual('GRUPO-A', row['posting_group'])
        self.assertEqual('consolidate', row['grouping_mode'])
        self.assertEqual(review, row['posting_group_review'])
        for key in ['rate', 'origin', 'cst_icms']:
            self.assertIsNone(row[key])
        self.assertEqual(2, len(row['declared_classifications']))
        self.assertEqual({'4', '12'}, {c['rate'] for c in row['declared_classifications']})
        self.assertEqual({'00', '20'}, {c['cst_icms'] for c in row['declared_classifications']})
        wb = load_workbook(io.BytesIO(self.report('&format=xlsx').content))
        headers = [c.value for c in wb['Dados'][1]]
        import json
        classes = json.loads(wb['Dados'].cell(2, headers.index('Classificações declaradas preservadas') + 1).value)
        self.assertEqual(row['declared_classifications'], classes)
        self.assertEqual(3, wb['Classificações declaradas'].max_row)
        self.assertEqual({'4', '12'}, {wb['Classificações declaradas'].cell(i,9).value for i in [2,3]})
        text = ' '.join(' '.join(p.extract_text().split()) for p in PdfReader(io.BytesIO(self.report('&format=pdf').content)).pages)
        for expected in ['Grupos de escrituração revisados', 'GRUPO-A', "'rate': '4'", "'rate': '12'", 'Fonte sintética de agrupamento', 'Revisor sintético']:
            self.assertIn(expected, text)

    def test_excel_classification_detail_survives_single_cell_limit(self):
        from app.report_exports import export_report
        self.book()
        result = self.report().json()
        classes = [{'cfop': '1102', 'cst_icms': str(i), 'csosn': '', 'origin': '0', 'rate': str(i)}
                   for i in range(600)]
        result['rows'] = [dict(result['rows'][0], declared_classifications=classes)]
        payload, _ = export_report(result, 'xlsx')
        wb = load_workbook(io.BytesIO(payload))
        headers = [c.value for c in wb['Dados'][1]]
        self.assertIn('Classificações completas na aba', wb['Dados'].cell(2, headers.index('Classificações declaradas preservadas') + 1).value)
        self.assertEqual(601, wb['Classificações declaradas'].max_row)
        self.assertEqual('599', wb['Classificações declaradas'].cell(601, 6).value)
