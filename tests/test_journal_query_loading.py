"""Complete journal-list contracts and bounded reads on a large synthetic plan."""
from contextlib import contextmanager
import unittest
from unittest.mock import patch
import test_account_pagination as pagination


class JournalQueryLoadingTests(unittest.TestCase):
    setUp = pagination.AccountPaginationTests.setUp
    tearDown = pagination.AccountPaginationTests.tearDown

    def journal(self, cid, day, key):
        accounts={a['access_code']:a['id'] for a in self.core.accounts(cid) if a['id']>0}
        center=self.core.save_cost_center(cid, {'code':key,'name':'Synthetic center '+key}, 'synthetic')
        return self.core.create_journal(cid, {'date':day,'history':'Synthetic '+key,'document':key,'idempotency_key':key,
            'lines':[{'account_id':accounts['3'],'cost_center_id':center['id'],'debit':'12.34','credit':'0'},
                     {'account_id':accounts['5'],'debit':'0','credit':'12.34'}]}, 'synthetic')

    def test_year_month_order_and_full_details_match_single_record_contract(self):
        self.core.create_exercise(self.cid,{'module':'accounting','year':2025},'synthetic')
        old=self.journal(self.cid,'2025-09-01','old')
        august=self.journal(self.cid,'2026-08-01','august')
        september=self.journal(self.cid,'2026-09-01','september')
        same_day=self.journal(self.cid,'2026-09-01','same-day')
        other=self.journal(self.other,'2026-09-01','other-company')
        reverse=self.core.reverse_journal(self.cid,september['id'],{'date':'2026-09-02','reason':'Synthetic reversal','idempotency_key':'reverse'},'synthetic')
        annual=self.core.journals(self.cid,year=2026)
        with self.core.db.read() as conn:
            ids=[r['id'] for r in conn.execute('SELECT id FROM journals WHERE company_id=? AND period BETWEEN ? AND ? ORDER BY date DESC,id DESC',(self.cid,'2026-01','2026-12'))]
            expected=[self.core._journal(conn,self.cid,i) for i in ids]
        self.assertEqual(expected,annual)
        self.assertNotIn(old['id'],ids);self.assertNotIn(other['id'],ids)
        self.assertEqual([reverse['id'],same_day['id'],september['id']],[j['id'] for j in self.core.journals(self.cid,'2026-09')])
        self.assertEqual([august['id']],[j['id'] for j in self.core.journals(self.cid,'2026-08')])
        self.assertEqual('reversed',next(j for j in annual if j['id']==september['id'])['status'])
        self.assertTrue(all('request_hash' not in j for j in annual))

    def test_read_query_count_is_bounded_and_api_year_filters_in_sql(self):
        for i in range(8):self.journal(self.cid,'2026-09-01',f'load-{i}')
        original=self.core.db.read;queries=[]
        @contextmanager
        def traced(*args,**kwargs):
            with original(*args,**kwargs) as conn:
                conn.set_trace_callback(lambda q:queries.append(q) if q.lstrip().upper().startswith('SELECT') else None)
                try:yield conn
                finally:conn.set_trace_callback(None)
        with patch.object(self.core.db,'read',traced):
            records=self.core.journals(self.cid,year=2026)
        self.assertEqual(3,len(queries),queries)
        self.assertTrue(all(len(j['lines'])==2 for j in records))
        self.assertEqual(2,sum('BETWEEN' in q for q in queries))
        self.assertEqual(records,self.client.get(f'/api/companies/{self.cid}/journals?year=2026').json())
        self.assertEqual(409,self.client.get(f'/api/companies/{self.cid}/journals?year=2025').status_code)
        with self.core.db.read() as conn:
            before={t:conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ['journals','journal_lines','accounts','audit']}
        self.core.journals(self.cid,year=2026);self.core.journals(self.other,'2026-08')
        with self.core.db.read() as conn:
            self.assertEqual(before,{t:conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in before})

    def test_dashboard_fiscal_and_accounting_values_are_scoped_by_company_and_month(self):
        self.journal(self.cid,'2026-08-01','august');self.journal(self.cid,'2026-09-01','september')
        self.journal(self.other,'2026-09-01','other-company')
        for month,total in [('08','10.00'),('09','20.00')]:
            self.core.create_document(self.cid,{'direction':'incoming','number':month,'series':'1','model':'55','issue_date':f'2026-{month}-01','posting_date':f'2026-{month}-01','partner_name':'Synthetic','total':total},'synthetic')
        for month,total in [('08',1000),('09',2000)]:
            r=self.client.get(f'/api/companies/{self.cid}/dashboard?period=2026-{month}');self.assertEqual(200,r.status_code,r.text)
            d=r.json();self.assertEqual(1,d['documents']['count']);self.assertEqual(total,d['documents']['total_cents']);self.assertEqual(1,d['accounting']['journals']);self.assertEqual(1234,d['accounting']['debit_cents'])
        other=self.core.dashboard(self.other,'2026-09');self.assertEqual(0,other['documents']['count']);self.assertEqual(1,other['accounting']['journals'])
        empty=self.core.dashboard(self.cid,'2026-10');self.assertEqual(0,empty['documents']['count']);self.assertEqual(0,empty['accounting']['journals'])
