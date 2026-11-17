import unittest
from app.report_tables import table_chunks

class ReportTableBoundsTests(unittest.TestCase):
    def test_all_rows_and_header_preserved_in_order(self):
        rows=[['header']]+[[i] for i in range(1001)]
        chunks=list(table_chunks(rows))
        self.assertTrue(all(len(c)<=201 for c in chunks))
        self.assertTrue(all(c[0]==rows[0] for c in chunks))
        self.assertEqual([r for c in chunks for r in c[1:]],rows[1:])
    def test_empty_and_header_only(self):
        self.assertEqual(list(table_chunks([])),[])
        self.assertEqual(list(table_chunks([['H']])),[[['H']]])
