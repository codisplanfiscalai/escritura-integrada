import copy
from decimal import Decimal
import unittest
from app.fiscal_analytics import fiscal_posting_lines, validate_fiscal_treatment, validate_posting_group_review


def profile():
    return {'code': 'reviewed', 'book_mode': 'other_excluding_ipi', 'source': 'User decision', 'responsible': 'Reviewer', 'valid_from': '2026-01-01', 'valid_to': ''}


def item(number, total, cfop='2102', rate='4', origin='1', **kwargs):
    return dict(number=str(number), total=str(total), cfop=cfop, ncm='99999999',
                taxes={'ICMS/ICMS00/CST': '00', 'ICMS/ICMS00/orig': origin,
                       'ICMS/ICMS00/pICMS': rate, 'ICMS/ICMS00/vBC': str(total),
                       'ICMS/ICMS00/vICMS': '1.00'}, **kwargs)


class FiscalAnalyticsTests(unittest.TestCase):
    def test_grouping_origin_rate_cfop_and_discount(self):
        doc = dict(total='36.00', posting_date='2026-09-01', items=[
            item(1, 10, declared_product_fields={'vDesc': '1'}),
            item(2, 10, rate='4.0000', declared_product_fields={'vDesc': '1'}),
            item(3, 10, rate='12', origin='0', declared_product_fields={'vDesc': '1'}),
            item(4, 10, cfop='2910', declared_product_fields={'vDesc': '1'})])
        old = copy.deepcopy(doc)
        lines = fiscal_posting_lines(doc)
        self.assertEqual([x['document_total'] for x in lines], ['18.00', '9.00', '9.00'])
        self.assertEqual(lines[0]['item_numbers'], ['1', '2'])
        self.assertEqual(lines[0]['book_icms'], None)
        self.assertEqual(lines[0]['declared_taxes']['icms'], '2.00')
        self.assertIn('FISCAL_TREATMENT_REQUIRED', lines[0]['pending'])
        self.assertEqual(doc, old)

    def test_components_explicit_other_and_item_ipi(self):
        a = item(1, 10, declared_product_fields={'vFrete': '2', 'vDesc': '1'})
        a['taxes']['IPI/IPITrib/vIPI'] = '3'
        doc = dict(total='14', items=[a], fiscal_treatment=profile())
        line = fiscal_posting_lines(doc)[0]
        self.assertEqual(line['document_total'], '14.00')
        self.assertEqual(line['ipi'], '3.00')
        self.assertEqual(line['book_other'], '11.00')
        self.assertEqual(line['book_icms'], '0.00')
        self.assertEqual(line['book_ipi'], '0.00')

    def test_residual_cent_exact_deterministic_and_exclusion(self):
        doc = dict(total='30.01', items=[item(1, 10), item(2, 10, cfop='2910'), item(3, 10, cfop='2353'),
                                       item(4, 999, cfop='2949', declared_product_fields={'indTot': '0'})])
        lines = fiscal_posting_lines(doc)
        self.assertEqual([x['document_total'] for x in lines], ['10.01', '10.00', '10.00', '0.00'])
        self.assertEqual(sum(Decimal(x['document_total']) for x in lines), Decimal('30.01'))
        self.assertIn('TOTAL_ALLOCATION_REVIEW', lines[0]['pending'])

    def test_header_freight_proportional(self):
        doc = dict(total='33', taxes={'ICMSTot/vFrete': '3'}, items=[item(1, 10), item(2, 20, cfop='2910')])
        lines = fiscal_posting_lines(doc)
        self.assertEqual([x['document_total'] for x in lines], ['11.00', '22.00'])
        self.assertIn('HEADER_COMPONENT_ALLOCATED', lines[0]['pending'])
        self.assertNotIn('TOTAL_ALLOCATION_REVIEW', lines[0]['pending'])

    def test_c190_precedence_without_scaling_mismatch(self):
        doc = dict(total='30', items=[item(1, 30)], analytics=[
            {'cfop': '2102', 'cst_icms': '100', 'rate': '4', 'operation_total': '10', 'taxes': {'VL_BC_ICMS': '0', 'VL_ICMS': '0'}},
            {'cfop': '2102', 'cst_icms': '000', 'rate': '12', 'operation_total': '19', 'taxes': {'VL_BC_ICMS': '0', 'VL_ICMS': '0'}}])
        lines = fiscal_posting_lines(doc)
        self.assertEqual([x['document_total'] for x in lines], ['10.00', '19.00'])
        self.assertEqual(lines[0]['source_kind'], 'sped_c190')
        self.assertIn('C190_TOTAL_MISMATCH', lines[0]['pending'])
        self.assertIsNone(lines[0]['book_other'])

    def test_persisted_and_zero_product_fallback(self):
        lines = fiscal_posting_lines(dict(total_cents=101, items=[item(1, 0), item(2, 0, cfop='2910')]))
        self.assertEqual([x['document_total'] for x in lines], ['1.01', '0.00'])
        line = fiscal_posting_lines(dict(total_cents=1234, cfop='2353'))[0]
        self.assertEqual(line['document_total'], '12.34')
        self.assertIsNone(line['book_base'])

    def test_profile_validation_and_invalid_configuration_pending(self):
        from app.core import DomainError
        self.assertEqual(validate_fiscal_treatment(profile(), '2026-09-01')['code'], 'reviewed')
        for invalid in ({}, profile() | {'book_mode': 'explicit'}, profile() | {'valid_from': '2026-99-00'}):
            with self.assertRaises(DomainError): validate_fiscal_treatment(invalid)
        with self.assertRaises(DomainError): validate_fiscal_treatment(profile(), '2025-12-31')
        line = fiscal_posting_lines({'total': '10', 'fiscal_treatment': {'book_mode': 'other_excluding_ipi'}})[0]
        self.assertIsNone(line['book_other'])
        self.assertIn('INVALID_FISCAL_TREATMENT', line['pending'])

    def test_declared_ipi_base_aggregation_and_absent_disclosure(self):
        a, b = item(1, 100), item(2, 100)
        a['taxes'].update({'IPI/IPITrib/vBC': '80', 'IPI/IPITrib/vIPI': '4'})
        b['taxes'].update({'IPI/IPITrib/vBC': '90', 'IPI/IPITrib/vIPI': '4.5'})
        line, = fiscal_posting_lines({'total': '208.50', 'items': [a, b]})
        self.assertEqual(line['declared_taxes']['ipi_base'], '170.00')
        self.assertEqual(line['declared_taxes']['ipi'], '8.50')
        self.assertTrue(line['declared_tax_coverage']['ipi_base']['complete'])
        del b['taxes']['IPI/IPITrib/vBC']; del b['taxes']['IPI/IPITrib/vIPI']
        line, = fiscal_posting_lines({'total': '204', 'items': [a, b]})
        self.assertIsNone(line['declared_taxes']['ipi_base'])
        self.assertIsNone(line['declared_taxes']['ipi'])
        self.assertFalse(line['ipi_informed'])
        self.assertEqual(line['declared_tax_partial_totals']['ipi_base'], '80.00')
        line, = fiscal_posting_lines({'total': '100', 'items': [item(1, 100)]})
        self.assertEqual(line['ipi'], '0.00')
        self.assertIsNone(line['declared_taxes']['ipi'])
        self.assertFalse(line['ipi_informed'])

    def test_partial_declared_icms_cannot_be_presented_as_complete_credit(self):
        a, b = item(1, 100), item(2, 100)
        a['taxes']['ICMS/ICMS00/vICMS'] = '18'
        del b['taxes']['ICMS/ICMS00/vBC']; del b['taxes']['ICMS/ICMS00/vICMS']
        doc = {'total': '200', 'items': [a, b], 'fiscal_treatment': profile() | {'book_mode': 'declared_icms'}}
        line, = fiscal_posting_lines(doc)
        self.assertIsNone(line['declared_taxes']['icms_base'])
        self.assertIsNone(line['declared_taxes']['icms'])
        self.assertIsNone(line['book_base'])
        self.assertIsNone(line['book_icms'])
        self.assertEqual(line['declared_tax_partial_totals']['icms_base'], '100.00')
        self.assertEqual(line['declared_tax_partial_totals']['icms'], '18.00')
        self.assertEqual(line['declared_tax_coverage']['icms']['known'], 1)
        self.assertEqual(line['declared_tax_coverage']['icms']['expected'], 2)
        self.assertIn('DECLARED_ICMS_MISSING', line['pending'])
        self.assertIn('DECLARED_ICMS_INCOMPLETE', line['pending'])

    def review(self, mode='split', mapping=None):
        return {'source': 'Reviewed book', 'responsible': 'Reviewer', 'reason': 'Explicit item partition',
                'mode': mode, 'item_groups': mapping or {'1': 'A', '2': 'B'}}

    def test_review_split_keeps_default_and_totals(self):
        doc = dict(total='30', items=[item(1, 10), item(2, 20)])
        self.assertEqual(len(fiscal_posting_lines(doc)), 1)
        doc['posting_group_review'] = self.review()
        before = copy.deepcopy(doc)
        lines = fiscal_posting_lines(doc)
        self.assertEqual([x['document_total'] for x in lines], ['10.00', '20.00'])
        self.assertEqual([x['posting_group'] for x in lines], ['A', 'B'])
        self.assertTrue(all(x['grouping_mode'] == 'split' for x in lines))
        self.assertEqual(doc, before)

    def test_split_does_not_merge_fiscal_classifications(self):
        doc = dict(total='30', items=[item(1, 10), item(2, 20, rate='12')],
                   posting_group_review=self.review(mapping={'1': 'A', '2': 'A'}))
        self.assertEqual(len(fiscal_posting_lines(doc)), 2)

    def test_explicit_consolidation_preserves_heterogeneous_disclosure(self):
        a, b = item(1, 10), item(2, 20, origin='0', rate='12')
        b['taxes']['ICMS/ICMS00/CST'] = '20'
        doc = dict(total='30', posting_date='2026-09-01', items=[a, b], fiscal_treatment=profile(),
                   posting_group_review=self.review('consolidate', {'1': 'A', '2': 'A'}))
        line, = fiscal_posting_lines(doc)
        self.assertEqual(line['document_total'], '30.00')
        self.assertEqual(line['book_other'], '30.00')
        for name in ('origin', 'rate', 'cst_icms'): self.assertIsNone(line[name])
        self.assertEqual(line['cfop'], '2102')
        self.assertEqual(line['item_numbers'], ['1', '2'])
        self.assertEqual(len(line['declared_classifications']), 2)
        self.assertEqual(len(line['declared_tax_records']), 2)
        self.assertEqual(line['declared_taxes']['icms'], '2.00')

    def test_group_validation_rejects_incomplete_unknown_duplicate_and_large_labels(self):
        from app.core import DomainError
        doc = dict(total='30', items=[item(1, 10), item(2, 20)])
        for mapping in ({'1': 'A'}, {'1': 'A', '2': 'B', '3': 'C'}, {'1': ' ', '2': 'B'},
                        {'1': 'A' * 101, '2': 'B'}, {1: 'A', '2': 'B'}):
            with self.assertRaises(DomainError): validate_posting_group_review(self.review(mapping=mapping), doc)
        for change in ({'mode': 'auto'}, {'source': ''}, {'responsible': None}, {'reason': ''}, {'extra': 'x'}):
            with self.assertRaises(DomainError): validate_posting_group_review(self.review() | change, doc)
        with self.assertRaises(DomainError):
            validate_posting_group_review(self.review(), doc | {'items': [item(1, 10), item(1, 20)]})

    def test_group_validation_blocks_mixed_cfop_treatment_and_unauthorized_merge(self):
        from app.core import DomainError
        review = self.review('consolidate', {'1': 'A', '2': 'A'})
        base = dict(total='30', posting_date='2026-09-01', items=[item(1, 10), item(2, 20)])
        for profile_value in ({}, profile() | {'book_mode': 'declared_icms'}, profile() | {'valid_to': '2026-02-01'}):
            with self.assertRaises(DomainError): validate_posting_group_review(review, base | {'fiscal_treatment': profile_value})
        mixed_cfop = base | {'items': [item(1, 10), item(2, 20, cfop='2910')], 'fiscal_treatment': profile()}
        with self.assertRaises(DomainError): validate_posting_group_review(review, mixed_cfop)
        second = item(2, 20); second['fiscal_treatment'] = profile() | {'code': 'different'}
        with self.assertRaises(DomainError):
            validate_posting_group_review(review, base | {'items': [item(1, 10), second], 'fiscal_treatment': profile()})

    def test_invalid_group_review_falls_back_with_pending_and_c190_unchanged(self):
        from app.core import DomainError
        doc = dict(total='30', items=[item(1, 10), item(2, 20)], posting_group_review=self.review(mapping={'1': 'A'}))
        line, = fiscal_posting_lines(doc)
        self.assertEqual(line['document_total'], '30.00')
        self.assertEqual(line['grouping_mode'], 'automatic')
        self.assertIn('INVALID_POSTING_GROUP_REVIEW', line['pending'])
        doc['analytics'] = [{'operation_total': '30', 'cfop': '2102', 'taxes': {}}]
        with self.assertRaises(DomainError): validate_posting_group_review(self.review(), doc)
        line, = fiscal_posting_lines(doc)
        self.assertEqual(line['source_kind'], 'sped_c190')
        self.assertEqual(line['document_total'], '30.00')
        self.assertIn('INVALID_POSTING_GROUP_REVIEW', line['pending'])

    def test_csosn_and_treatment_keep_separate(self):
        a, b = item(1, 10), item(2, 20)
        a['taxes'] = {'ICMS/ICMSSN102/CSOSN': '102'}
        b['taxes'] = {'ICMS/ICMSSN900/CSOSN': '900'}
        lines = fiscal_posting_lines(dict(total='30', items=[a, b]))
        self.assertEqual([x['csosn'] for x in lines], ['102', '900'])
        b['taxes'] = a['taxes'].copy()
        b['fiscal_treatment'] = profile()
        self.assertEqual(len(fiscal_posting_lines(dict(total='30', items=[a, b]))), 2)


if __name__ == '__main__':
    unittest.main()
