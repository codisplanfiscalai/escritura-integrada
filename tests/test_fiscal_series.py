"""Synthetic company/identity/read-budget regressions."""
import json
import unittest
import test_core as fixtures
from app.core import DomainError,digest
from app.fiscal_series import normalize_series,settings
from app.fiscal_series_operations import save_settings

class FiscalSeriesTests(unittest.TestCase):
    setUp=fixtures.CoreApiTests.setUp;tearDown=fixtures.CoreApiTests.tearDown
    create_company=fixtures.CoreApiTests.create_company;activate=fixtures.CoreApiTests.activate
    scope=fixtures.CoreApiTests.scope;document=fixtures.CoreApiTests.document
    def uid(self):
        with self.core.db.read() as c:return c.execute("SELECT id FROM users WHERE username='teste'").fetchone()[0]
    def config(self,digits,version=0):
        with self.core.db.transaction() as c:return save_settings(c,self.a['id'],{'digits':digits,'version':version},self.uid(),'teste')
    def doc(self,number='SERIES',series='1'):
        return self.core.create_document(self.a['id'],self.document(number)|{'series':series},'teste')
    def raw(self,did):
        with self.core.db.read() as c:return dict(c.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone())
    def legacy(self,number='SERIES',series='1'):
        row=self.doc(number,series);data=self.document(number)|{'series':series}
        key=digest({k:data.get(k,'') for k in ('direction','model','series','number','partner_tax_id','partner_name','issue_date')})
        with self.core.db.transaction() as c:c.execute("UPDATE documents SET series=?,business_key=?,extra_json=json_remove(extra_json,'$.declared_series') WHERE id=?",(series,key,row['id']))
        return row
    def test_padding_preserves_unknown_alphanumeric_and_long_values(self):
        for val,expected in [('1','001'),('01','001'),('0','000'),('00001','00001'),('',''),('A1','A1'),('١','١'),('-1','-1'),('1.0','1.0')]:self.assertEqual(expected,normalize_series(val))
        self.assertIsNone(normalize_series(None))
    def test_setting_is_scoped_versioned_and_not_a_migration(self):
        row=self.legacy();self.assertEqual({'digits':3,'version':0},self.client.get(self.scope('/fiscal-series/settings')).json())
        self.assertEqual({'digits':5,'version':1},self.config(5));self.assertEqual('1',self.raw(row['id'])['series'])
        self.assertEqual('00001',self.core.documents(self.a['id'])[0]['series'])
        with self.core.db.read() as c:self.assertEqual(3,settings(c,self.b['id'])['digits'])
        for val in [True,0,21,'3',2.5]:
            with self.assertRaises(DomainError):self.config(val,1)
        with self.assertRaises(DomainError):self.config(4,0)
    def test_defaults_and_company_validation_use_one_query(self):
        with self.core.db.read() as c:
            queries=[];c.set_trace_callback(queries.append)
            self.assertEqual({'digits':3,'version':0},settings(c,self.a['id']));self.assertEqual(1,len(queries));queries.clear()
            with self.assertRaises(DomainError) as e:settings(c,999999999)
            self.assertEqual('not_found',e.exception.code);self.assertEqual(1,len(queries))
    def test_numeric_identity_is_stable_for_new_and_legacy_documents(self):
        one=self.doc()
        for val in ['01','001','0001']:self.assertEqual(one['id'],self.doc(series=val)['id'])
        old=self.legacy('OLD','02');self.assertEqual(old['id'],self.doc('OLD','2')['id'])
        self.config(6);self.assertEqual(one['id'],self.doc()['id'])
        with self.assertRaises(DomainError):self.core.create_document(self.a['id'],self.document('SERIES')|{'series':'01','total':'101.00'},'teste')
    def test_edit_rejects_collision_and_preserves_declared_series(self):
        one=self.doc('ONE');two=self.doc('TWO')
        with self.assertRaises(DomainError):self.core.update_document(self.a['id'],two['id'],{'number':'ONE','series':'01','version':two['version'],'reason':'Teste'},'teste')
        saved=self.core.update_document(self.a['id'],one['id'],{'series':'01','version':one['version'],'reason':'Teste'},'teste')
        self.assertEqual('001',saved['series']);self.assertEqual('1',saved['declared_series'])
    def test_existing_ambiguous_identity_is_rejected_without_merging(self):
        one=self.legacy('ONE');two=self.legacy('TWO','01')
        with self.core.db.transaction() as c:c.execute("UPDATE documents SET number='ONE' WHERE id=?",(two['id'],))
        with self.assertRaises(DomainError) as e:self.doc('ONE','001')
        self.assertEqual('series_identity_conflict',e.exception.code);self.assertEqual('1',self.raw(one['id'])['series'])
    def test_report_and_original_series(self):
        one=self.legacy();self.config(4)
        result=self.client.get(self.scope('/business-reports/fiscal-book?start=2026-11-01&end=2026-11-30'))
        self.assertEqual(200,result.status_code,result.text);self.assertEqual('0001',result.json()['rows'][0]['series'])
        self.assertEqual('1',self.raw(one['id'])['series'])
    def preview(self):
        from app.fiscal_series_operations import SeriesOperations
        return SeriesOperations(self.core).preview(self.a['id'],{'period':'2026-11'},self.uid(),'teste')
    def confirm(self,p):
        from app.fiscal_series_operations import SeriesOperations
        return SeriesOperations(self.core).confirm(self.a['id'],{'preview_id':p['id'],'preview_hash':p['preview_hash'],'reason':'Correção sintética autorizada'},self.uid(),'teste')
    def test_bulk_is_read_only_until_explicit_confirm_and_repeat_is_idempotent(self):
        one=self.legacy();self.doc('EMPTY','');self.doc('ALPHA','A1');self.doc('LONG','0000123')
        before=self.raw(one['id']);p=self.preview();self.assertTrue(p['can_confirm']);self.assertEqual(1,p['selected_count'])
        self.assertEqual(before,self.raw(one['id']));self.assertEqual(3,p['preserved_count'])
        r=self.confirm(p);after=self.raw(one['id']);self.assertTrue(r['completed']);self.assertEqual('001',after['series']);self.assertEqual(before['version']+1,after['version'])
        for field in ['key','source_json','source_hash','total_cents','items_json','taxes_json','posting_date','journal_id','status']:self.assertEqual(before[field],after[field])
        self.assertEqual('1',json.loads(after['extra_json'])['declared_series'])
        self.assertTrue(self.confirm(p)['duplicate']);self.assertFalse(self.preview()['can_confirm'])
        self.assertEqual(one['id'],self.doc()['id'])
        with self.core.db.read() as c:self.assertEqual([],list(c.execute('PRAGMA foreign_key_check')))
    def test_bulk_conflict_blocks_every_change(self):
        one=self.legacy('ONE');two=self.legacy('TWO','01');safe=self.legacy('SAFE','2')
        with self.core.db.transaction() as c:c.execute("UPDATE documents SET number='ONE' WHERE id=?",(two['id'],))
        p=self.preview();self.assertFalse(p['can_confirm'])
        with self.assertRaises(DomainError):self.confirm(p)
        self.assertEqual('2',self.raw(safe['id'])['series']);self.assertEqual('1',self.raw(one['id'])['series'])
    def test_bulk_rejects_stale_settings_rows_inventory_and_expiry(self):
        from unittest.mock import patch
        one=self.legacy();p=self.preview();self.config(4)
        with self.assertRaises(DomainError) as e:self.confirm(p)
        self.assertEqual('stale_preview',e.exception.code)
        p=self.preview()
        with self.core.db.transaction() as c:c.execute('UPDATE documents SET version=version+1 WHERE id=?',(one['id'],))
        with self.assertRaises(DomainError):self.confirm(p)
        p=self.preview();self.doc('NEW','A')
        with self.assertRaises(DomainError):self.confirm(p)
        p=self.preview()
        with patch('app.bulk_operations.time.time',return_value=p['expires_at']+1):
            with self.assertRaises(DomainError) as e:self.confirm(p)
        self.assertEqual('preview_expired',e.exception.code)
    def test_bulk_guard_closed_period_and_finalized_tax(self):
        from unittest.mock import patch
        one=self.legacy();p=self.preview()
        with self.core.db.transaction() as c:c.execute("UPDATE documents SET status='booked' WHERE id=?",(one['id'],))
        self.core.set_period(self.a['id'],{'period':'2026-11','module':'fiscal','reason':'Teste'},'teste',True)
        with self.assertRaises(DomainError):self.confirm(p)
        self.assertFalse(self.preview()['can_confirm'])
        self.core.set_period(self.a['id'],{'period':'2026-11','module':'fiscal','reason':'Teste'},'teste',False)
        with patch('app.fiscal_series_operations.ensure_unfinalized',side_effect=DomainError('Finalizada',409,'tax_finalized')):self.assertFalse(self.preview()['can_confirm'])
    def test_http_csrf_foreign_company_wrong_preview_type(self):
        row=self.legacy();path=self.scope('/fiscal-series/preview')
        self.assertEqual(403,self.client.post(path,headers={'X-CSRF-Token':''},json={'period':'2026-11'}).status_code)
        response=self.client.post(path,json={'period':'2026-11'});self.assertEqual(200,response.status_code,response.text);p=response.json()
        self.activate(self.b['id'])
        r=self.client.post(self.scope('/fiscal-series/confirm'),json={'preview_id':p['id'],'preview_hash':p['preview_hash']});self.assertNotEqual(200,r.status_code)
        self.activate(self.a['id']);r=self.client.post(self.scope('/bulk-operations/confirm'),json={'preview_id':p['id'],'preview_hash':p['preview_hash']});self.assertNotEqual(200,r.status_code)
        self.assertEqual('1',self.raw(row['id'])['series'])
