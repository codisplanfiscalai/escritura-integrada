"""Company-specific opt-in policy, using synthetic data only."""
import base64
import unittest
from unittest.mock import patch
import test_core as base
from app.core import DomainError, ensure_open
from app.operational_settings import DEFAULTS, decode_import_content, get_settings
from app.bulk_operations import normalize


class OperationalSettingsTests(unittest.TestCase):
    operational_defaults=True
    setUp=base.CoreApiTests.setUp
    tearDown=base.CoreApiTests.tearDown
    create_company=base.CoreApiTests.create_company
    activate=base.CoreApiTests.activate
    scope=base.CoreApiTests.scope
    document=base.CoreApiTests.document

    def settings(self):
        response=self.client.get(self.scope('/operational-settings'))
        self.assertEqual(200,response.status_code,response.text)
        return response.json()

    def save(self,**values):
        old=self.settings()
        response=self.client.put(self.scope('/operational-settings'),json={'version':old['version'],'settings':old['settings']|values})
        self.assertEqual(200,response.status_code,response.text)
        return response.json()

    def test_defaults_no_business_restrictions_and_independent_companies(self):
        result=self.settings()
        self.assertEqual(DEFAULTS,result['settings'])
        self.assertFalse(any(v for v in result['settings'].values() if type(v) is bool))
        self.save(block_imports=True,limit_batch_selection=True,batch_selection_limit=2)
        other=self.client.get(self.scope('/operational-settings',self.b['id'])).json()
        self.assertEqual(DEFAULTS,other['settings'])
        self.assertEqual(0,other['version'])

    def test_version_and_validation_are_atomic(self):
        self.save(block_imports=True)
        for payload,status in [({'version':0,'settings':DEFAULTS},409),({'version':1,'settings':{'block_imports':'false'}},400),({'version':1,'settings':{'unknown':True}},400),({'version':1,'settings':{'import_size_mb':129}},400)]:
            result=self.client.put(self.scope('/operational-settings'),json=payload)
            self.assertEqual(status,result.status_code,result.text)
        self.assertTrue(self.settings()['settings']['block_imports'])
        self.assertEqual(1,self.settings()['version'])

    def test_reusable_model_and_default_reset(self):
        self.save(enforce_period_locks=True,block_imports=True)
        result=self.client.post(self.scope('/operational-settings/templates'),json={'name':'Modelo sintético','description':'Teste de reutilização'})
        self.assertEqual(200,result.status_code,result.text)
        template=result.json()['created_template_id']
        self.activate(self.b['id'])
        result=self.client.post(self.scope('/operational-settings/apply-template',self.b['id']),json={'template_id':template,'version':0})
        self.assertEqual(200,result.status_code,result.text)
        self.assertTrue(result.json()['settings']['block_imports'])
        result=self.client.post(self.scope('/operational-settings/apply-template',self.b['id']),json={'template_id':'unrestricted','version':1})
        self.assertEqual(200,result.status_code,result.text)
        self.assertEqual(DEFAULTS,result.json()['settings'])
        self.assertTrue(self.settings()['settings']['block_imports'])

    def test_period_lock_is_optional_but_missing_exercise_is_not(self):
        with self.core.db.transaction() as conn:
            conn.execute("INSERT INTO period_locks VALUES(?,?,?,1,'teste','teste','2026-11-11',1)",(self.a['id'],'2026-11','fiscal'))
            ensure_open(conn,self.a['id'],'2026-11','fiscal')
        self.save(enforce_period_locks=True)
        with self.core.db.read() as conn:
            with self.assertRaises(DomainError) as caught: ensure_open(conn,self.a['id'],'2026-11','fiscal')
            self.assertEqual('period_closed',caught.exception.code)
        self.save(enforce_period_locks=False)
        with self.core.db.read() as conn:
            self.assertEqual(1,conn.execute('SELECT closed FROM period_locks WHERE company_id=?',(self.a['id'],)).fetchone()[0])
            with self.assertRaises(DomainError) as caught: ensure_open(conn,self.a['id'],'2199-11','fiscal')
            self.assertEqual('exercise_missing',caught.exception.code)

    def test_import_switch_and_size_only_when_enabled(self):
        raw=b'x'*(1024*1024+1)
        encoded=base64.b64encode(raw).decode()
        with self.core.db.read() as conn: self.assertEqual(raw,decode_import_content(conn,self.a['id'],encoded))
        self.save(limit_import_size=True,import_size_mb=1)
        with self.core.db.read() as conn:
            with self.assertRaises(DomainError) as caught: decode_import_content(conn,self.a['id'],encoded)
            self.assertEqual('file_too_large',caught.exception.code)
        self.save(limit_import_size=False,block_imports=True)
        response=self.client.post(self.scope('/imports/preview'),json={'filename':'teste.xml','period':'2026-11','content_base64':'eA=='})
        self.assertEqual(409,response.status_code,response.text)
        self.assertEqual('operational_restriction',response.json()['code'])

    def test_selection_and_delete_are_controlled_in_backend(self):
        from app.bulk_operations import BulkOperations
        request={'kind':'documents','action':'delete','period':'2026-11','ids':list(range(1,5002))}
        self.assertEqual(5001,len(normalize(request)['ids']))
        self.save(limit_batch_selection=True,batch_selection_limit=1)
        result=self.client.post(self.scope('/bulk-operations/preview'),json=request)
        self.assertEqual(409,result.status_code,result.text)
        self.assertEqual('selection_limit',result.json()['code'])
        self.save(limit_batch_selection=False,block_movement_deletion=True)
        result=self.client.post(self.scope('/bulk-operations/preview'),json=request|{'ids':[1]})
        self.assertEqual(409,result.status_code,result.text)
        self.assertEqual('operational_restriction',result.json()['code'])

    def test_non_admin_cannot_change_settings_or_templates(self):
        user=self.client.post('/api/users',json={'username':'operador-parametros','password':'Senha-ficticia-123!','role':'operator','company_ids':[self.a['id']]})
        self.assertEqual(201,user.status_code,user.text)
        from fastapi.testclient import TestClient
        with TestClient(self.app) as client:
            r=client.post('/api/login',json={'username':'operador-parametros','password':'Senha-ficticia-123!'})
            client.headers['X-CSRF-Token']=r.json()['csrf_token']
            self.activate(self.a['id'],client=client)
            self.assertEqual(200,client.get(self.scope('/operational-settings')).status_code)
            self.assertEqual(403,client.get(self.scope('/operational-settings',self.b['id'])).status_code)
            for suffix,method,body in [('',client.put,{'version':0,'settings':DEFAULTS}),('/templates',client.post,{'name':'Não permitido'}),('/apply-template',client.post,{'template_id':'unrestricted','version':0})]:
                self.assertEqual(403,method(self.scope('/operational-settings'+suffix),json=body).status_code)

    def test_cleanup_switch_and_limit_and_recheck(self):
        import test_fiscal_import
        raw=(__import__('pathlib').Path('tests/fixtures/nfe_ficticia.xml').read_bytes().replace(b'12345678000195',self.a['tax_id'].encode()))
        batch=self.client.post(self.scope('/imports/preview'),json={'filename':'sintetica.xml','period':'2026-11','content_base64':base64.b64encode(raw).decode()}).json()
        body={'ids':[batch['id']],'mode':'hide_history'}
        preview=self.client.post(self.scope('/import-packages/cleanup-preview'),json=body)
        self.assertEqual(200,preview.status_code,preview.text)
        self.save(block_package_cleanup=True)
        response=self.client.post(self.scope('/import-packages/cleanup-confirm'),json=body|{'preview_hash':preview.json()['preview_hash']})
        self.assertEqual(409,response.status_code,response.text)
        self.assertEqual('operational_restriction',response.json()['code'])
        with self.core.db.read() as conn: self.assertGreater(len(conn.execute('SELECT original FROM imports WHERE id=?',(batch['id'],)).fetchone()[0]),0)

    def test_upload_larger_than_previous_twenty_mib_limit(self):
        from pathlib import Path
        raw=Path('tests/fixtures/nfe_ficticia.xml').read_bytes().replace(b'12345678000195',self.a['tax_id'].encode())
        raw += b' ' * (21*1024*1024-len(raw))
        response=self.client.post(self.scope('/imports/preview'),json={'filename':'large-synthetic.xml','period':'2026-11','content_base64':base64.b64encode(raw).decode()})
        self.assertEqual(200,response.status_code,response.text[:1000])
        self.assertNotIn('FILE_SIZE',[issue['code'] for issue in response.json()['issues']])
        self.assertTrue(response.json()['original_available'])
        with self.core.db.read() as conn:
            self.assertEqual(len(raw),conn.execute('SELECT length(original) FROM imports WHERE id=?',(response.json()['id'],)).fetchone()[0])

    def test_session_and_context_return_company_specific_policy(self):
        self.save(enforce_period_locks=True)
        first=self.client.get('/api/session').json()
        self.assertTrue(first['operational_settings']['enforce_period_locks'])
        second=self.activate(self.b['id'])
        self.assertFalse(second['operational_settings']['enforce_period_locks'])
        self.assertEqual(self.b['id'],second['active_company_id'])

    def test_edit_inactive_company_does_not_change_active_context(self):
        response=self.client.put(self.scope('/operational-settings',self.b['id']),json={'version':0,'settings':{'block_imports':True}})
        self.assertEqual(200,response.status_code,response.text)
        session=self.client.get('/api/session').json()
        self.assertEqual(self.a['id'],session['active_company_id'])
        self.assertFalse(session['operational_settings']['block_imports'])
        self.assertTrue(self.client.get(self.scope('/operational-settings',self.b['id'])).json()['settings']['block_imports'])

    def test_account_plan_import_rechecks_operational_policy(self):
        preview=self.client.post(self.scope('/account-plans/preview'),json={'format':'default'})
        self.assertEqual(200,preview.status_code,preview.text)
        self.save(block_imports=True)
        blocked=self.client.post(self.scope('/account-plans/preview'),json={'format':'default'})
        self.assertEqual(409,blocked.status_code,blocked.text)
        blocked=self.client.post(self.scope(f"/account-plans/{preview.json()['id']}/confirm"),json={'preview_hash':preview.json()['preview_hash'],'reason':'Teste','properties_reviewed':True})
        self.assertEqual(409,blocked.status_code,blocked.text)
        self.assertEqual('operational_restriction',blocked.json()['code'])
        self.save(block_imports=False,limit_import_size=True,import_size_mb=1)
        import json
        from app.account_plans import default_plan
        raw=json.dumps(default_plan()).encode()+b' '*(1024*1024)
        blocked=self.client.post(self.scope('/account-plans/preview'),json={'format':'native','filename':'large-plan.json','content_base64':base64.b64encode(raw).decode()})
        self.assertEqual(413,blocked.status_code,blocked.text)

    def test_combined_review_and_booking_is_atomic_and_optional(self):
        doc=self.client.post(self.scope('/documents'),json=self.document('COMBINED')).json()
        result=self.client.post(self.scope(f"/documents/{doc['id']}/book"),json={'version':doc['version'],'idempotency_key':'combined-one'})
        self.assertEqual(200,result.status_code,result.text)
        self.assertEqual('booked',result.json()['document']['status'])
        self.assertEqual(doc['posting_date'],result.json()['document']['posting_date'])
        self.assertEqual(doc['issue_date'],result.json()['document']['issue_date'])
        self.assertTrue(result.json()['document']['reviewed_by'])
        repeat=self.client.post(self.scope(f"/documents/{doc['id']}/book"),json={'version':doc['version'],'idempotency_key':'combined-one'})
        self.assertEqual(200,repeat.status_code,repeat.text)
        self.assertEqual(result.json()['document']['id'],repeat.json()['document']['id'])
        with self.core.db.read() as conn:
            self.assertEqual(1,conn.execute("SELECT count(*) FROM audit WHERE entity='document' AND entity_id=? AND action='review'",(str(doc['id']),)).fetchone()[0])
        self.save(require_separate_document_review=True)
        doc=self.client.post(self.scope('/documents'),json=self.document('SEPARATE')).json()
        refused=self.client.post(self.scope(f"/documents/{doc['id']}/book"),json={'version':doc['version']})
        self.assertEqual(409,refused.status_code,refused.text)
        self.assertEqual('invalid_status',refused.json()['code'])
        self.save(require_separate_document_review=False)
        broken=self.client.post(self.scope('/documents'),json=self.document('INVALID-CFOP')|{'cfop':''}).json()
        rejected=self.client.post(self.scope(f"/documents/{broken['id']}/book"),json={'version':broken['version']})
        self.assertEqual(409,rejected.status_code,rejected.text)
        with self.core.db.read() as conn:
            row=conn.execute('SELECT status,version,reviewed_by FROM documents WHERE id=?',(broken['id'],)).fetchone()
            self.assertEqual('pending',row['status'])
            self.assertEqual(broken['version'],row['version'])
            self.assertIsNone(row['reviewed_by'])

    def test_combined_bulk_booking_and_policy_recheck(self):
        ids=[self.client.post(self.scope('/documents'),json=self.document('BATCH-'+str(i))).json()['id'] for i in range(2)]
        request={'kind':'documents','action':'book','period':'2026-11','ids':ids}
        preview=self.client.post(self.scope('/bulk-operations/preview'),json=request).json()
        self.assertTrue(preview['can_confirm'],preview)
        self.save(require_separate_document_review=True)
        failed=self.client.post(self.scope('/bulk-operations/confirm'),json={'preview_id':preview['id'],'preview_hash':preview['preview_hash']})
        self.assertEqual(409,failed.status_code,failed.text)
        self.save(require_separate_document_review=False)
        preview=self.client.post(self.scope('/bulk-operations/preview'),json=request).json()
        done=self.client.post(self.scope('/bulk-operations/confirm'),json={'preview_id':preview['id'],'preview_hash':preview['preview_hash']})
        self.assertEqual(200,done.status_code,done.text)
        self.assertTrue(done.json()['completed'])
        with self.core.db.read() as conn:
            self.assertEqual(2,conn.execute("SELECT count(*) FROM documents WHERE company_id=? AND status='booked' AND reviewed_by IS NOT NULL",(self.a['id'],)).fetchone()[0])

    def test_combined_booking_requires_review_permission(self):
        doc=self.client.post(self.scope('/documents'),json=self.document('AUTH-COMBINED')).json()
        user=self.client.post('/api/users',json={'username':'escriturador','password':'Senha-ficticia-123!','role':'operator','company_ids':[self.a['id']]}).json()
        with self.core.db.transaction() as conn:
            conn.execute("DELETE FROM user_permissions WHERE user_id=? AND company_id=?",(user['id'],self.a['id']))
            for action,effect in [('read','allow'),('book','allow'),('edit','deny')]:
                conn.execute("INSERT INTO user_permissions(user_id,company_id,routine,action,effect) VALUES(?,?,?,?,?)",(user['id'],self.a['id'],'fiscal.documents',action,effect))
        from fastapi.testclient import TestClient
        with TestClient(self.app) as client:
            logged=client.post('/api/login',json={'username':'escriturador','password':'Senha-ficticia-123!'})
            client.headers['X-CSRF-Token']=logged.json()['csrf_token']
            self.activate(self.a['id'],client=client)
            failed=client.post(self.scope(f"/documents/{doc['id']}/book"),json={'version':doc['version']})
            self.assertEqual(403,failed.status_code,failed.text)
            failed=client.post(self.scope('/bulk-operations/preview'),json={'kind':'documents','action':'book','period':'2026-11','ids':[doc['id']]})
            self.assertEqual(403,failed.status_code,failed.text)
        with self.core.db.read() as conn:
            self.assertEqual('pending',conn.execute('SELECT status FROM documents WHERE id=?',(doc['id'],)).fetchone()[0])
