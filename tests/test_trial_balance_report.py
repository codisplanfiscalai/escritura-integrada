"""Synthetic balances: zero suppression never changes totals or persisted data."""
import unittest
from io import BytesIO
from pypdf import PdfReader
import test_core as base

class TrialBalanceTests(unittest.TestCase):
    for name in ('setUp','tearDown','scope','activate','create_company','journal'):
        locals()[name]=getattr(base.CoreApiTests,name)

    def report(self,extra=''):
        r=self.client.get(self.scope('/business-reports/trial-balance?start=2026-11-01&end=2026-11-30'+extra))
        self.assertEqual(200,r.status_code,r.text[:200]);return r.json()

    def seed(self):
        with self.core.db.transaction() as c:
            c.execute("UPDATE accounts SET classifier='1.1.01.01.01.00' WHERE id=?",(self.aid['3'],))
            c.execute("INSERT INTO accounts(company_id,access_code,classifier,name,nature,analytical,active,requires_cost_center) VALUES(?,?,?,?,?,0,1,0)",(self.a['id'],'900','1.1.01.01.00.00','GRUPO SINTETICO','debit'))
            self.parent=c.execute("SELECT id FROM accounts WHERE company_id=? AND access_code='900'",(self.a['id'],)).fetchone()[0]
        response=self.client.post(self.scope('/journals'),json=self.journal());self.assertEqual(201,response.status_code,response.text)

    def test_default_hierarchy_no_zero_no_duplicate_totals(self):
        self.seed();r=self.report();a=[x for x in r['rows'] if x['analytical']]
        self.assertEqual(2,len(a));self.assertEqual(12345,r['totals']['debit_cents']);self.assertEqual(12345,r['totals']['credit_cents'])
        parent=next(x for x in r['rows'] if x['account_id']==self.parent)
        self.assertEqual(12345,parent['closing_cents']);self.assertGreater(next(x for x in a if x['account_id']==self.aid['3'])['depth'],0)
        full=self.report('&activity=all');self.assertGreater(len(full['rows']),len(r['rows']));self.assertEqual(full['totals'],r['totals'])

    def test_synthetic_selection_includes_descendants(self):
        self.seed();r=self.report('&account_id='+str(self.parent))
        self.assertEqual([self.aid['3']],[x['account_id'] for x in r['rows'] if x['analytical']])
        self.assertEqual(12345,r['totals']['closing_cents'])

    def test_opening_only_and_zero_closing_movement_retained(self):
        self.seed()
        with self.core.db.transaction() as c:c.execute("UPDATE journals SET date='2026-10-31' WHERE company_id=?",(self.a['id'],))
        r=self.report();self.assertEqual(2,len([x for x in r['rows'] if x['analytical']]))
        self.assertTrue(any(x['opening_cents'] for x in r['rows']));self.assertEqual(0,r['totals']['debit_cents'])
        payload=self.journal('reverse');payload['lines'][0]['debit']='0.00';payload['lines'][0]['credit']='123.45';payload['lines'][1]['credit']='0.00';payload['lines'][1]['debit']='123.45'
        self.assertEqual(201,self.client.post(self.scope('/journals'),json=payload).status_code)
        r=self.report();self.assertTrue(all(x['closing_cents']==0 for x in r['rows']));self.assertEqual(2,len([x for x in r['rows'] if x['analytical']]))

    def test_validation_company_isolation_and_formats(self):
        self.seed();other=self.client.get(self.scope('/accounts',self.b['id'])).json()[0]['id']
        for extra in ['&activity=bad','&account_id='+str(other)]:self.assertGreaterEqual(self.client.get(self.scope('/business-reports/trial-balance?start=2026-11-01&end=2026-11-30'+extra)).status_code,400)
        for fmt in ['pdf','csv','xlsx']:
            r=self.client.get(self.scope('/business-reports/trial-balance?start=2026-11-01&end=2026-11-30&format='+fmt));self.assertEqual(200,r.status_code)
            if fmt=='pdf':
                pdf=PdfReader(BytesIO(r.content));self.assertLess(len(pdf.pages),3)
                self.assertLess(float(pdf.pages[0].mediabox.width),float(pdf.pages[0].mediabox.height))
                text=' '.join(p.extract_text() for p in pdf.pages);self.assertIn('GRUPO SINTETICO',text);self.assertNotIn('Anexo de conferência',text)
                self.assertIn('123,45',text)

    def test_same_classifier_accounts_remain_distinct(self):
        self.seed()
        with self.core.db.transaction() as c:
            c.execute("UPDATE accounts SET classifier='1.1.01.01.01.00' WHERE id=?",(self.aid['5'],))
        r=self.report();analytical=[x for x in r['rows'] if x['analytical']]
        self.assertEqual(2,len(analytical));self.assertEqual(2,len({x['account_id'] for x in analytical}))
        parent=next(x for x in r['rows'] if x['account_id']==self.parent)
        self.assertEqual(0,parent['closing_cents']);self.assertEqual(12345,parent['debit_cents'])
        self.assertTrue(all(x['journal_ids'] for x in analytical))

    def test_empty_default_and_large_zero_plan(self):
        with self.core.db.transaction() as c:
            c.executemany("INSERT INTO accounts(company_id,access_code,classifier,name,nature,analytical,active,requires_cost_center) VALUES(?,?,?,?,?,1,1,0)",[(self.a['id'],'Z'+str(i),'1.9.'+str(i),'ZERADA '+str(i),'debit') for i in range(20000)])
        r=self.report();self.assertEqual([],r['rows']);self.assertFalse(any(r['totals'].values()))
