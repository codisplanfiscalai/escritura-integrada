"""Synthetic regression for narrowing the existing book-cancellation guard."""
import unittest
import test_book_cancellation as base


class CancellationIdentityLookupTests(unittest.TestCase):
    setUp=base.BookCancellationTests.setUp
    tearDown=base.BookCancellationTests.tearDown
    scope=base.BookCancellationTests.scope
    activate=base.BookCancellationTests.activate
    create_company=base.BookCancellationTests.create_company
    document=base.BookCancellationTests.document
    post=base.BookCancellationTests.post
    payload=base.BookCancellationTests.payload

    def test_numeric_padding_and_nonnumeric_distinctions_are_preserved(self):
        for old,new,expected in [('12','00012',409),('0','000',409),('002','2',409),
                                 ('0A','A',201),('٠١','0٠١',201)]:
            with self.subTest(old=old,new=new):
                self.post('/documents',self.payload(number=old,model='65'),201)
                self.post('/documents',self.document(new)|{'direction':'outgoing','model':'65'},expected)

    def test_lookup_preserves_series_model_direction_issuer_company_and_period(self):
        self.post('/documents',self.payload(number='00042',model='65'),201)
        normal=self.document('42')|{'direction':'outgoing','model':'65'}
        self.post('/documents',normal|{'series':'002'},201)
        self.post('/documents',normal|{'model':'55'},201)
        self.post('/documents',normal|{'direction':'incoming'},201)
        self.post('/documents',normal,409)
        self.post('/documents',normal|{'issue_date':'2026-12-05','posting_date':'2026-12-05'},409)
        self.activate(self.b['id'])
        response=self.client.post(self.scope('/documents',self.b['id']),json=normal)
        self.assertEqual(201,response.status_code,response.text)
        self.activate(self.a['id'])
        self.post('/documents',self.payload(number='00077',model='65',direction='incoming',partner_tax_id='11111111111'),201)
        incoming=self.document('77')|{'model':'65','direction':'incoming','partner_tax_id':'22222222222'}
        self.post('/documents',incoming,201)
        self.post('/documents',incoming|{'partner_tax_id':'111.111.111-11'},409)

    def test_legacy_long_padding_and_actual_query_plan(self):
        cancelled=self.post('/documents',self.payload(number='7',model='65'),201)
        with self.core.db.transaction() as conn:
            # Existing TEXT rows may predate the current 250-character input cap.
            conn.execute('UPDATE documents SET number=? WHERE id=?',('0'*300+'7',cancelled['id']))
        queries=[];original=self.core.db.connect
        def traced():
            conn=original();conn.set_trace_callback(queries.append);return conn
        self.core.db.connect=traced
        try:self.post('/documents',self.document('0007')|{'direction':'outgoing','model':'65'},409)
        finally:self.core.db.connect=original
        query=next(q for q in queries if q.startswith('SELECT * FROM documents WHERE company_id=') and 'book_cancellation' in q)
        self.assertIn("ltrim(number,'0')",query)
        with self.core.db.read() as conn:
            plan=' '.join(str(tuple(row)) for row in conn.execute('EXPLAIN QUERY PLAN '+query))
        self.assertIn('idx_documents_cancellation_identity',plan)

    def test_startup_adds_index_to_populated_database_without_changing_rows(self):
        item=self.post('/documents',self.payload(number='301',model='65'),201)
        with self.core.db.transaction() as conn:
            row=dict(conn.execute('SELECT * FROM documents WHERE id=?',(item['id'],)).fetchone())
            conn.execute('DROP INDEX idx_documents_cancellation_identity')
        from app.db import Database
        for _ in range(2):Database(self.core.db.data_dir)
        with self.core.db.read() as conn:
            self.assertEqual(row,dict(conn.execute('SELECT * FROM documents WHERE id=?',(item['id'],)).fetchone()))
            self.assertEqual('ok',conn.execute('PRAGMA quick_check').fetchone()[0])
            self.assertIsNotNone(conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_documents_cancellation_identity'").fetchone())
