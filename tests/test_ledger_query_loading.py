"""Razão: contrapartidas completas sem consulta por linha, só dados sintéticos."""
from contextlib import contextmanager
import hashlib
import unittest
from unittest.mock import patch
import test_account_pagination as pagination


class LedgerQueryLoadingTests(unittest.TestCase):
    setUp = pagination.AccountPaginationTests.setUp
    tearDown = pagination.AccountPaginationTests.tearDown

    def seed(self):
        self.accounts={a['access_code']:a['id'] for a in self.core.accounts(self.cid) if a['id']>0}
        self.center=self.core.save_cost_center(self.cid,{'code':'SYN','name':'Centro sintético'},'synthetic')['id']
        self.core.create_exercise(self.cid,{'module':'accounting','year':2025},'synthetic')
        for day,key in [('2025-09-01','old'),('2026-08-01','opening'),('2026-09-01','first'),('2026-09-02','second')]:
            self.core.create_journal(self.cid,{'date':day,'document':key,'history':'Synthetic '+key,'idempotency_key':key,'lines':[
                {'account_id':self.accounts['3'],'cost_center_id':self.center,'debit':'10.00','credit':'0'},
                {'account_id':self.accounts['5'],'debit':'0','credit':'6.00'},
                {'account_id':self.accounts['6'],'debit':'0','credit':'4.00'}]},'synthetic')

    def hashes(self):
        with self.core.db.read() as conn:
            return {t:hashlib.sha256(repr([tuple(r) for r in conn.execute(f'SELECT * FROM {t} ORDER BY id')]).encode()).hexdigest() for t in ['journals','journal_lines','audit','accounts','documents']}

    def test_filtered_counterparts_match_legacy_and_balances_include_hidden_movements(self):
        self.seed();before=self.hashes()
        for options in [{},{'account_id':self.accounts['3']},{'cost_center_id':self.center},{'query':'second'},{'account_id':self.accounts['3'],'cost_center_id':self.center,'query':'second'}]:
            with self.subTest(options=options):
                r=self.core.business_report(self.cid,'ledger','2026-09-01','2026-09-30',**options)
                with self.core.db.read() as conn:
                    for row in r['rows']:
                        codes=[x['access_code'] for x in conn.execute('SELECT DISTINCT a.access_code FROM journal_lines l JOIN effective_accounts a ON a.id=l.account_id WHERE l.company_id=? AND l.journal_id=? AND l.account_id<>?',(self.cid,row['journal_id'],row['account_id']))]
                        self.assertEqual(codes[0] if len(codes)==1 else 'Diversos' if codes else '',row['counterpart'])
                if options.get('query'):
                    self.assertTrue(all(x['document']=='second' for x in r['rows']))
                group=next(g for g in r['ledger_groups'] if g['account_id']==self.accounts['3'])
                self.assertEqual(2000,group['opening_cents']);self.assertEqual(4000,group['closing_cents'])
                self.assertEqual([x for x in r['rows'] if x['account_id']==group['account_id']],group['rows'])
        self.assertEqual(before,self.hashes())
        self.assertEqual([],self.core.business_report(self.other,'ledger','2026-09-01','2026-09-30')['rows'])
        self.assertEqual([],self.core.business_report(self.cid,'ledger','2026-10-01','2026-10-31')['rows'])

    def test_select_count_does_not_grow_with_report_rows_and_csv_keeps_all_rows(self):
        self.seed();original=self.core.db.read;queries=[]
        @contextmanager
        def trace(*a,**kw):
            with original(*a,**kw) as conn:
                conn.set_trace_callback(lambda sql:queries.append(sql) if sql.lstrip().upper().startswith('SELECT') else None)
                try:yield conn
                finally:conn.set_trace_callback(None)
        with patch.object(self.core.db,'read',trace):
            report=self.core.business_report(self.cid,'ledger','2026-09-01','2026-09-30')
        self.assertEqual(5,len(queries),queries)
        self.assertEqual(6,len(report['rows']))
        url=f'/api/companies/{self.cid}/business-reports/ledger?start=2026-09-01&end=2026-09-30'
        response=self.client.get(url);self.assertEqual(200,response.status_code,response.text)
        self.assertEqual(report,{k:response.json()[k] for k in report})
        csv=self.client.get(url+'&format=csv');self.assertEqual(200,csv.status_code,csv.text)
        self.assertEqual(7,len(csv.text.splitlines()))
        self.assertEqual(409,self.client.get(url.replace('2026-09','2025-09')).status_code)

    def test_single_counterpart_repeated_lines_and_reversal_keep_order(self):
        self.seed()
        j=self.core.create_journal(self.cid,{'date':'2026-09-03','document':'repeat','history':'Synthetic repeat','idempotency_key':'repeat','lines':[
            {'account_id':self.accounts['3'],'debit':'2.00','credit':'0'},
            {'account_id':self.accounts['3'],'debit':'3.00','credit':'0'},
            {'account_id':self.accounts['5'],'debit':'0','credit':'5.00'}]},'synthetic')
        reverse=self.core.reverse_journal(self.cid,j['id'],{'date':'2026-09-04','reason':'Synthetic reversal','idempotency_key':'reverse'},'synthetic')
        result=self.core.business_report(self.cid,'ledger','2026-09-03','2026-09-04')
        self.assertEqual(6,len(result['rows']))
        for row in result['rows']:
            self.assertEqual('5' if row['account_id']==self.accounts['3'] else '3',row['counterpart'])
        group=next(g for g in result['ledger_groups'] if g['account_id']==self.accounts['3'])
        self.assertEqual([j['id'],j['id'],reverse['id'],reverse['id']],[r['journal_id'] for r in group['rows']])
        self.assertEqual(group['opening_cents'],group['closing_cents'])
