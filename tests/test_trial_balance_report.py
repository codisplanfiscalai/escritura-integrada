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

    def test_multiple_accounts_union_overlap_and_clear(self):
        self.seed()
        ids=f"{self.parent},{self.aid['3']},{self.aid['5']},{self.aid['3']}"
        r=self.report('&account_ids='+ids)
        self.assertEqual(2,len([x for x in r['rows'] if x['analytical']]))
        self.assertEqual(12345,r['totals']['debit_cents']);self.assertEqual(12345,r['totals']['credit_cents'])
        self.assertEqual(3,len(r['filters']['account_ids']))
        self.assertEqual(self.report()['totals'],r['totals'])
        self.assertEqual(r['totals'],self.report('&account_ids='+ids+'&activity=all')['totals'])
        for extra in ['&account_ids=bad','&account_ids=1,,2','&account_ids=0','&account_ids='+','.join(['1']*501)]:
            response=self.client.get(self.scope('/business-reports/trial-balance?start=2026-11-01&end=2026-11-30'+extra));self.assertGreaterEqual(response.status_code,400)

    def test_multiple_accounts_other_reports_and_exports(self):
        self.seed();ids=f"{self.parent},{self.aid['3']}"
        with self.core.db.transaction() as c:c.execute("UPDATE accounts SET report_group='asset' WHERE id=?",(self.aid['3'],))
        for kind in ['diary','ledger','consolidated-diary','cost-centers','balance-sheet','income-statement']:
            response=self.client.get(self.scope(f'/business-reports/{kind}?start=2026-11-01&end=2026-11-30&account_ids='+ids))
            self.assertEqual(200,response.status_code,response.text)
            r=response.json();self.assertEqual(2,len(r['filters']['account_ids']))
            self.assertTrue(all(x['account_id']==self.aid['3'] for x in r['rows']))
            if kind not in ['balance-sheet','income-statement']:
                self.assertEqual(12345,r['totals']['debit_cents']);self.assertEqual(0,r['totals']['credit_cents'])
        for fmt in ['pdf','csv','xlsx']:
            response=self.client.get(self.scope('/business-reports/trial-balance?start=2026-11-01&end=2026-11-30&account_ids='+ids+'&format='+fmt))
            self.assertEqual(200,response.status_code)
            if fmt=='pdf':
                text=' '.join(p.extract_text() for p in PdfReader(BytesIO(response.content)).pages)
                self.assertIn('Contas selecionadas',text);self.assertIn('GRUPO SINTETICO',text);self.assertNotIn('Receitas operacionais',text)
            elif fmt=='xlsx':
                from openpyxl import load_workbook
                wb=load_workbook(BytesIO(response.content));values=list(wb['Valores em centavos'].values)
                records=[dict(zip(values[0],r)) for r in values[1:]]
                expected=self.report('&account_ids='+ids)['rows']
                self.assertEqual([(r['account_id'],r['debit_cents'],r['credit_cents']) for r in expected],[(r['account_id'],r['debit_cents'],r['credit_cents']) for r in records])
            else:
                import csv,io
                from decimal import Decimal
                records=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig')),delimiter=';'))
                expected=self.report('&account_ids='+ids)['rows']
                self.assertEqual([(r['account_id'],r['debit_cents'],r['credit_cents']) for r in expected],[(int(r['account_id']),int(Decimal(r['debit_cents'])*100),int(Decimal(r['credit_cents'])*100)) for r in records])


    def test_multiple_accounts_reject_foreign_company(self):
        self.seed();other=self.client.get(self.scope('/accounts',self.b['id'])).json()[0]['id']
        for kind in ['trial-balance','ledger','diary']:
            response=self.client.get(self.scope(f'/business-reports/{kind}?start=2026-11-01&end=2026-11-30&account_ids={self.aid["3"]},{other}'))
            self.assertGreaterEqual(response.status_code,400)

    def test_mixed_classifiers_use_explicit_plan_mask(self):
        import json
        self.seed()
        with self.core.db.transaction() as c:
            c.execute("INSERT INTO account_plan_properties(company_id,properties_json,extras_json) VALUES(?,?,'{}') ON CONFLICT(company_id) DO UPDATE SET properties_json=excluded.properties_json",(self.a['id'],json.dumps({'mask':'#.#.##.##.##.##'})))
            c.execute("UPDATE accounts SET classifier='1101010100' WHERE id=?",(self.aid['3'],))
        r=self.report('&account_ids='+str(self.parent))
        self.assertEqual([self.aid['3']],[x['account_id'] for x in r['rows'] if x['analytical']])
        self.assertEqual(12345,next(x for x in r['rows'] if x['account_id']==self.parent)['closing_cents'])
