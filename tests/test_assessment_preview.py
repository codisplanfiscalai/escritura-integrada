"""Synthetic read-only preview, exact rounding and concurrent revision guards."""
import unittest
import test_fiscal_expansion as base

class AssessmentPreviewTests(unittest.TestCase):
    setUp=base.FiscalExpansionTests.setUp;tearDown=base.FiscalExpansionTests.tearDown
    create_company=base.FiscalExpansionTests.create_company
    scope=base.FiscalExpansionTests.scope;activate=base.FiscalExpansionTests.activate;document=base.FiscalExpansionTests.document
    journal=base.FiscalExpansionTests.journal;post=base.FiscalExpansionTests.post;reviewed=base.FiscalExpansionTests.reviewed;booking=base.FiscalExpansionTests.booking
    rule=base.FiscalExpansionTests.rule;memory=base.FiscalExpansionTests.memory;finalize=base.FiscalExpansionTests.finalize

    def booked(self,number='ONE',**extra):
        doc=self.reviewed(number,extra)
        return self.post(f"/documents/{doc['id']}/book",self.booking(doc,key='book-'+number,generate_titles=False,lines=[]))['document']

    def request(self):
        doc=self.booked();rule=self.rule()
        return self.memory(entries=[{'document_id':doc['id'],'rule_id':rule['id'],'base':'40.05','reason':'Base sintética','effect':'credit','item_indices':[]}])

    def confirmed(self,payload):
        preview=self.post('/assessments/preview',payload)
        return payload|{'preview_fingerprint':preview['fingerprint'],'coverage_fingerprint':preview['coverage']['fingerprint']}

    def test_preview_does_not_write_and_exact_rounding_matches_save(self):
        payload=self.request()
        with self.core.db.read() as conn:
            before={t:conn.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['tax_assessments','tax_ledgers','audit','operations']}
        preview=self.post('/assessments/preview',payload)
        self.assertEqual([],preview['coverage']['omitted_document_ids'])
        self.assertEqual(401,preview['snapshot']['credit_cents'])
        self.assertEqual(1,preview['coverage']['included_documents'])
        with self.core.db.read() as conn:
            after={t:conn.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in before}
        self.assertEqual(before,after)
        confirmed=payload|{'preview_fingerprint':preview['fingerprint'],'coverage_fingerprint':preview['coverage']['fingerprint']}
        result=self.post('/assessments',confirmed)
        self.assertEqual(preview['snapshot'],result['snapshot'])
        self.assertEqual(result['id'],self.post('/assessments',confirmed)['id'])

    def test_adjustment_after_preview_blocks_save_without_partial_write(self):
        payload=self.confirmed(self.request())
        self.post('/tax-adjustments',{'period':'2026-11','tax':'icms','kind':'debit','amount':'1.00','source':'Teste','reason':'Ajuste novo','idempotency_key':'adjust'})
        self.post('/assessments',payload,409)
        self.assertEqual([],self.core.assessments(self.a['id'],'2026-11'))

    def test_added_document_blocks_save_and_marks_saved_memory_stale(self):
        payload=self.confirmed(self.request());saved=self.post('/assessments',payload)
        self.post('/documents',self.document('AFTER'),201)
        self.post('/assessments',payload|{'idempotency_key':'new'},409)
        self.assertTrue(self.core.assessments(self.a['id'],'2026-11')[0]['stale'])
        self.post(f"/assessments/{saved['id']}/finalize",{'period':'2026-11','coverage_reviewed':True,'reason':'Teste','idempotency_key':'final'},409)

    def test_preview_reports_omissions_partial_items_and_pending(self):
        doc=self.booked(items=[{'description':'A','cfop':'1102','total':'40.00'},{'description':'B','cfop':'1102','total':'60.00'}]);self.booked('TWO')
        self.post('/documents',self.document('PENDING'),201);rule=self.rule()
        payload=self.memory(entries=[{'document_id':doc['id'],'rule_id':rule['id'],'base':'40.00','reason':'Item parcial','effect':'credit','item_indices':[0]}])
        coverage=self.post('/assessments/preview',payload)['coverage']
        self.assertEqual(2,coverage['booked_documents']);self.assertEqual(1,len(coverage['omitted_document_ids']))
        self.assertEqual([doc['id']],coverage['partial_document_ids']);self.assertEqual(1,coverage['pending_documents'])

    def test_opening_manual_and_previous_balance_remain_separate_by_tax(self):
        manual=self.memory(opening_mode='manual',opening_credit='123.45',opening_reason='Memória anterior sintética')
        self.assertEqual(12345,self.post('/assessments/preview',manual)['snapshot']['carry_credit_cents'])
        saved=self.post('/assessments',self.confirmed(manual));self.finalize(saved)
        self.activate(self.a['id'],'2026-12');payload=self.memory(period='2026-12',idempotency_key='next')
        self.assertEqual(12345,self.post('/assessments/preview',payload)['snapshot']['opening_credit_cents'])
        self.assertEqual(0,self.post('/assessments/preview',payload|{'tax':'pis'})['snapshot']['opening_credit_cents'])

    def test_invalid_and_cross_company_preview_preserve_guards(self):
        payload=self.request()
        self.post('/assessments/preview',payload|{'entries':[], 'no_movement_confirmed':False},400)
        self.post('/assessments/preview',payload|{'tax':'pis'},400)
        self.post('/assessments/preview',payload|{'entries':[payload['entries'][0]|{'document_id':'1'}]},400)
        self.activate(self.b['id'])
        result=self.client.post(self.scope('/assessments/preview',self.b['id']),json=payload)
        self.assertEqual(404,result.status_code,result.text)

    def test_preview_route_uses_create_permission_and_csrf(self):
        from app.permissions import route_policy
        self.assertEqual(('fiscal.assessments','create',False),route_policy(self.scope('/assessments/preview'),'POST',{}, {},{'module':'fiscal'}))
        self.assertEqual(403,self.client.post(self.scope('/assessments/preview'),json=self.memory(),headers={'X-CSRF-Token':''}).status_code)

    def test_book_cancellation_cannot_be_used_as_tax_base(self):
        import json
        payload=self.request();did=payload['entries'][0]['document_id']
        with self.core.db.transaction() as conn:
            row=conn.execute('SELECT extra_json FROM documents WHERE id=?',(did,)).fetchone()
            extra=json.loads(row['extra_json']);extra['book_cancellation']={'source':'Fixture sintética'}
            conn.execute('UPDATE documents SET extra_json=?,version=version+1 WHERE id=?',(json.dumps(extra),did))
        self.post('/assessments/preview',payload,400)
        self.assertEqual([],self.core.assessments(self.a['id'],'2026-11'))

    def test_series_correction_invalidates_saved_assessment_without_changing_values(self):
        payload=self.request();did=payload['entries'][0]['document_id']
        with self.core.db.transaction() as conn:conn.execute("UPDATE documents SET series='1' WHERE id=?",(did,))
        payload=self.confirmed(payload);saved=self.post('/assessments',payload)
        before=self.core.documents(self.a['id'])[0]
        pre=self.post('/fiscal-series/preview',{'period':'2026-11'})
        self.assertTrue(pre['can_confirm'],pre)
        self.post('/fiscal-series/confirm',{'preview_id':pre['id'],'preview_hash':pre['preview_hash'],'reason':'Teste sintético'})
        after=self.core.documents(self.a['id'])[0]
        self.assertEqual(before['version']+1,after['version'])
        for field in ('total_cents','items','taxes','posting_date','journal_id','status'):self.assertEqual(before[field],after[field])
        self.post('/assessments',payload|{'idempotency_key':'after-series'},409)
        self.assertTrue(self.core.assessments(self.a['id'],'2026-11')[0]['stale'])
        self.post(f"/assessments/{saved['id']}/finalize",{'period':'2026-11','coverage_reviewed':True,'reason':'Teste sintético','idempotency_key':'final-after-series'},409)
