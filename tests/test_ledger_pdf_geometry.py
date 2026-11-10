"""Synthetic geometry regressions; no customer data or reference files required."""
from io import BytesIO
import unittest

from pypdf import PdfReader
from reportlab.pdfbase.pdfmetrics import stringWidth

from app.report_models import ledger_pdf


class LedgerGeometryTest(unittest.TestCase):
    def render(self, count=1, opening=123456):
        rows = [dict(date='2026-01-02', history='Synthetic entry', counterpart='TEST',
                     debit_cents=12345, credit_cents=6789) for _ in range(count)]
        result = dict(kind='ledger', company_name='Synthetic Company',
                      start='2026-01-01', end='2026-01-31', ledger_groups=[
                          dict(account_name='Synthetic account', opening_cents=opening, rows=rows)])
        raw, mime = ledger_pdf(result, first_page=2)
        self.assertEqual(mime, 'application/pdf')
        return PdfReader(BytesIO(raw))

    def runs(self, page):
        x = y = char_space = word_space = 0
        size = 9
        for operands, op in page.get_contents().operations:
            if op == b'Tm':
                x, y = map(float, operands[-2:])
            elif op == b'Tf':
                size = float(operands[1])
            elif op == b'Tc':
                char_space = float(operands[0])
            elif op == b'Tw':
                word_space = float(operands[0])
            elif op == b'Tj':
                value = str(operands[0])
                width = stringWidth(value, 'Courier', size)
                width += max(0, len(value)-1)*char_space + value.count(' ')*word_space
                yield value, x, y, x+width, char_space, word_space

    def test_money_edges_and_final_label_spacing(self):
        page = self.render().pages[0]
        runs = list(self.runs(page))
        for value, right in [('123,45', 560.4), ('67,89', 645.4), ('1.234,56', 733.4)]:
            matches = [r for r in runs if r[0] == value]
            self.assertTrue(matches)
            for run in matches:
                self.assertAlmostEqual(run[3], right, places=3)
        final = next(r for r in runs if r[0].startswith('SALDO FINAL'))
        self.assertEqual(final[4:], (-.321, -2.7))
        self.assertAlmostEqual(final[3], 465.991, places=3)
        credit = next(r for r in runs if r[0] == 'CRÉDITO')
        self.assertAlmostEqual(credit[1], 590.142, places=3)

    def test_final_rule_follows_total_even_on_continuation(self):
        for count in (0, 1, 63, 64, 65, 403):
            with self.subTest(count=count):
                pdf = self.render(count=count)
                finals = [(page, run) for page in pdf.pages for run in self.runs(page)
                          if run[0].startswith('SALDO FINAL')]
                self.assertEqual(len(finals), 1)
                page, final = finals[0]
                # Text baseline is top+7; the reference rule is 12 pt below it.
                rule_y = final[2]-12
                moves = [tuple(map(float, args)) for args, op in page.get_contents().operations if op == b'm']
                ends = [tuple(map(float, args)) for args, op in page.get_contents().operations if op == b'l']
                self.assertIn((43.0, rule_y), moves)
                self.assertIn((790.0, rule_y), ends)
                for earlier in pdf.pages[:-1]:
                    self.assertEqual(sum(op == b'l' for _, op in earlier.get_contents().operations), 5)
                if count == 403:
                    self.assertEqual(len(pdf.pages), 7)

    def test_credit_opening_keeps_nature(self):
        runs = list(self.runs(self.render(opening=-123456).pages[0]))
        opening = next(r for r in runs if r[0] == '1.234,56')
        self.assertAlmostEqual(opening[3], 733.4, places=3)
        self.assertTrue(any(r[0] == 'C' and r[1] == 750 and r[2] == opening[2] for r in runs))


if __name__ == '__main__':
    unittest.main()
