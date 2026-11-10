"""Synthetic cobrança examples; billing problems must not hide fiscal evidence."""
import re
import io
import zipfile
import unittest
from pathlib import Path

from app.importers import parse_file

XML = (Path(__file__).parent / 'fixtures' / 'nfe_ficticia.xml').read_text()
COMPANY = {'tax_id': '12345678000195'}


def parse(billing, *, nfce=False):
    text = re.sub(r'<cobr>.*?</cobr>', billing, XML)
    company = COMPANY
    if nfce:
        text = text.replace('<mod>55</mod>', '<mod>65</mod>')
        text = re.sub(r'<dest>.*?</dest>', '', text)
        company = {'tax_id': '87654321000198'}
    return parse_file('synthetic.xml', text.encode(), company)


class BillingParserTests(unittest.TestCase):
    def test_preserves_header_discount_and_two_installments(self):
        result = parse('<cobr><fat><nFat>F-1</nFat><vOrig>110.00</vOrig><vDesc>10.00</vDesc><vLiq>100.00</vLiq></fat>'
                       '<dup><nDup>001</nDup><dVenc>2026-12-05</dVenc><vDup>40.00</vDup></dup>'
                       '<dup><nDup>002</nDup><dVenc>2027-01-05</dVenc><vDup>60.00</vDup></dup></cobr>')
        doc = result['documents'][0]
        billing = doc['billing']
        self.assertTrue(result['can_confirm'])
        self.assertEqual(billing['invoice']['original_amount'], '110.00')
        self.assertEqual(billing['invoice']['discount'], '10.00')
        self.assertEqual(billing['invoice']['net_amount'], '100.00')
        self.assertEqual(billing['installments'][1]['sequence'], 2)
        self.assertEqual(doc['invoices'], billing['installments'])
        self.assertFalse(billing['financial_rules_pending'])
        self.assertEqual(billing['issues'], [])

    def test_missing_billing_is_not_an_error_even_for_unidentified_nfce(self):
        for nfce in (False, True):
            with self.subTest(nfce=nfce):
                result = parse('', nfce=nfce)
                doc = result['documents'][0]
                self.assertTrue(result['can_confirm'])
                self.assertFalse(doc['billing']['present'])
                self.assertIsNone(doc['billing']['invoice'])
                self.assertEqual(doc['invoices'], [])
                self.assertEqual(doc['billing']['issues'], [])

    def test_missing_fields_are_not_invented(self):
        doc = parse('<cobr><dup><vDup>100.00</vDup></dup></cobr>')['documents'][0]
        part = doc['invoices'][0]
        self.assertEqual(part['sequence'], 1)
        self.assertEqual(part['number'], '')
        self.assertIsNone(part['due_date'])
        self.assertTrue(doc['financial_rules_pending'])
        self.assertEqual(part['raw_fields'], {'nDup': '', 'dVenc': '', 'vDup': '100.00'})

    def test_invalid_financial_values_do_not_drop_fiscal_document(self):
        for tag, value in [('vDup', 'NaN'), ('vDup', '-2'), ('vDup', '1.234'),
                           ('dVenc', '2026-02-30'), ('dVenc', 'tomorrow')]:
            with self.subTest(tag=tag, value=value):
                cobr = '<cobr><dup><nDup>1</nDup><dVenc>2026-12-05</dVenc><vDup>100.00</vDup></dup></cobr>'
                cobr = re.sub(fr'<{tag}>.*?</{tag}>', f'<{tag}>{value}</{tag}>', cobr)
                result = parse(cobr)
                self.assertTrue(result['can_confirm'])
                doc = result['documents'][0]
                self.assertEqual(doc['total'], '100.00')
                self.assertTrue(doc['financial_rules_pending'])
                self.assertEqual(doc['invoices'][0]['raw_fields'][tag], value)
                self.assertTrue(all(x['severity'] == 'warning' for x in doc['billing']['issues']))

    def test_bad_invoice_amount_and_mismatch_are_financial_warnings(self):
        for original, code in [('oops', 'FINANCIAL_BILLING_INVALID_VALUE'),
                               ('120', 'FINANCIAL_BILLING_TOTAL_MISMATCH')]:
            result = parse(f'<cobr><fat><nFat>F1</nFat><vOrig>{original}</vOrig><vDesc>10</vDesc><vLiq>100</vLiq></fat>'
                           '<dup><nDup>1</nDup><dVenc>2026-12-05</dVenc><vDup>90</vDup></dup></cobr>')
            self.assertTrue(result['can_confirm'])
            codes = {x['code'] for x in result['documents'][0]['billing']['issues']}
            self.assertIn(code, codes)
            self.assertIn('FINANCIAL_BILLING_INSTALLMENT_TOTAL_MISMATCH', codes)

    def test_duplicate_numbers_and_header_only_need_financial_review(self):
        part = '<dup><nDup>1</nDup><dVenc>2026-12-05</dVenc><vDup>50</vDup></dup>'
        doc = parse('<cobr>' + part + part + '</cobr>')['documents'][0]
        self.assertIn('FINANCIAL_BILLING_DUPLICATE_INSTALLMENT', {x['code'] for x in doc['billing']['issues']})
        doc = parse('<cobr><fat><nFat>F</nFat><vOrig>100</vOrig><vLiq>100</vLiq></fat></cobr>')['documents'][0]
        self.assertEqual(doc['invoices'], [])
        self.assertIsNone(doc['billing']['invoice']['discount'])
        self.assertTrue(doc['financial_rules_pending'])

    def test_structural_ambiguity_is_still_rejected(self):
        result = parse('<cobr><dup><nDup>1</nDup><vDup>50</vDup><vDup>50</vDup></dup></cobr>')
        self.assertFalse(result['can_confirm'])
        self.assertEqual(result['documents'], [])
        self.assertIn('XML_DUPLICATE_FIELD', {x['code'] for x in result['issues']})

    def test_large_batch_aggregates_financial_warnings_without_blocking_fiscal(self):
        data = XML.replace('2026-12-05', '2026-02-30').encode()
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
            for index in range(300):
                zipped.writestr(f'synthetic-{index}.xml', data)
        result = parse_file('batch.zip', archive.getvalue(), COMPANY)
        self.assertTrue(result['can_confirm'])
        self.assertEqual(len(result['documents']), 300)
        self.assertNotIn('ISSUE_LIMIT', {issue['code'] for issue in result['issues']})
        warning = next(issue for issue in result['issues']
                       if issue['code'] == 'FINANCIAL_BILLING_INVALID_VALUE')
        self.assertEqual(warning['count'], 300)
        self.assertEqual(len(warning['sources']), 300)
        for document in result['documents']:
            self.assertTrue(document['financial_rules_pending'])
            self.assertEqual(len(document['billing']['issues']), 1)
            self.assertEqual(document['billing']['issues'][0]['source']['file'], document['source']['file'])

    def test_payment_group_is_not_billing_or_proof_of_settlement(self):
        result = parse('<pag><detPag><tPag>01</tPag><vPag>100.00</vPag></detPag></pag>')
        doc = result['documents'][0]
        self.assertFalse(doc['billing']['present'])
        self.assertEqual(doc['invoices'], [])
        self.assertNotIn('payments', doc)
