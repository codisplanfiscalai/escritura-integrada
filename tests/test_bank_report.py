"""Banco sintético: isolamento, limites, rastros e ausência explícita de saldos."""
import unittest
import test_core as base

class BankReportTests(unittest.TestCase):
    setUp=base.CoreApiTests.setUp
    tearDown=base.CoreApiTests.tearDown
    scope=base.CoreApiTests.scope
    activate=base.CoreApiTests.activate
    create_company=base.CoreApiTests.create_company

    def test_filters_traceability_unknown_balance_and_exports(self):
        with self.core.db.transaction() as conn:
            for i,(cid,account,day,amount) in enumerate([
                (self.a['id'],'A','2026-10-31',50000),
                (self.a['id'],'A','2026-11-01',12345),
                (self.a['id'],'A','2026-11-30',-2345),
                (self.a['id'],'A','2026-12-01',777),
                (self.a['id'],'B','2026-11-01',888),
                (self.b['id'],'A','2026-11-01',999)]):
                conn.execute("INSERT INTO bank_transactions(company_id,bank_account,date,amount_cents,description,reference,external_id,source_json,source_hash,fingerprint,payload_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(cid,account,day,amount,'Sintético','REF-'+str(i),str(i),'{}','HASH-'+str(i),str(i),str(i),'2026-11-01'))
        url=self.scope('/business-reports/bank-movements?start=2026-11-01&end=2026-11-30&bank_account=A')
        response=self.client.get(url);self.assertEqual(response.status_code,200,response.text)
        result=response.json();self.assertEqual(len(result['rows']),2)
        self.assertEqual(result['totals']['net_movement_cents'],10000)
        self.assertEqual(result['totals']['inflow_cents'],12345)
        self.assertEqual(result['totals']['outflow_cents'],2345)
        self.assertIsNone(result['totals']['opening_cents'])
        self.assertIsNone(result['totals']['closing_cents'])
        self.assertTrue(all(r['balance_cents'] is None and r['source_hash'].startswith('HASH-') for r in result['rows']))
        for fmt in ['pdf','xlsx','csv']:
            exported=self.client.get(url+'&format='+fmt+'&purpose=print')
            self.assertEqual(exported.status_code,200,exported.text if fmt=='csv' else '')
        empty=self.client.get(url.replace('bank_account=A','bank_account=ausente')).json()
        self.assertEqual(empty['rows'],[]);self.assertIsNone(empty['totals']['opening_cents'])
        invalid=self.client.get(url+'&account_id='+str(self.aid['3']))
        self.assertEqual(invalid.status_code,400)
