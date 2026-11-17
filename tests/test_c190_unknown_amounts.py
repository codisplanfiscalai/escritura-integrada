"""Unknown C190 ICMS amounts must not become known zero in projections."""
import copy
import unittest
from app.fiscal_analytics import fiscal_posting_lines
import test_sped_bookkeeping as base

class C190UnknownAmountsTests(unittest.TestCase):
    def test_absent_null_and_blank_remain_unknown_without_mutating_source(self):
        for value in ('absent', None, ''):
            with self.subTest(value=value):
                doc = base.document()
                taxes = doc['analytics'][0]['taxes']
                for field in ('VL_BC_ICMS', 'VL_ICMS'):
                    if value == 'absent': taxes.pop(field)
                    else: taxes[field] = value
                before = copy.deepcopy(doc)
                line, = fiscal_posting_lines(doc)
                self.assertIsNone(line['book_base'])
                self.assertIsNone(line['book_icms'])
                self.assertEqual(taxes, line['declared_taxes'])
                result = base.generate([doc])
                self.assertEqual(['', ''], base.records(result, 'C190')[0][5:7])
                self.assertEqual(['', ''], base.records(result, 'C100')[0][20:22])
                self.assertIn('BOOK_VALUE_MISSING', base.warning_codes(result))
                self.assertTrue(result['can_export'])
                self.assertEqual(before, doc)

    def test_unknown_member_prevents_known_partial_sum_in_operational_group(self):
        for value in (None, ''):
            with self.subTest(value=value):
                rows = [base.document(1), base.document(2)]
                rows[0]['analytics'][0]['taxes'].update(VL_BC_ICMS=value, VL_ICMS=value)
                before = copy.deepcopy(rows)
                result = base.generate(rows, consolidate_nfce=True)
                self.assertTrue(result['consolidated'])
                self.assertEqual(['', ''], base.records(result, 'C190')[0][5:7])
                self.assertEqual(['', ''], base.records(result, 'C100')[0][20:22])
                self.assertEqual(2, len(result['trace']))
                self.assertEqual(before, rows)

    def test_explicit_zeros_and_known_amounts_remain_known(self):
        for value, expected in ((0, '0.00'), ('0', '0.00'), ('0.00', '0.00'), ('12.34', '12.34')):
            with self.subTest(value=value):
                doc = base.document()
                doc['analytics'][0]['taxes'].update(VL_BC_ICMS=value, VL_ICMS=value)
                line, = fiscal_posting_lines(doc)
                self.assertEqual([expected, expected], [line['book_base'], line['book_icms']])
                result = base.generate([doc])
                self.assertEqual([expected.replace('.', ',')]*2, base.records(result, 'C190')[0][5:7])

if __name__=='__main__': unittest.main()
