"""Company mapping persistence and permissions; no vendor or operational data."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import unittest
from fastapi.testclient import TestClient
from app.business import BusinessCore
from app.core import DomainError
import test_core as base
import test_prosoft_increment as prior
import test_global_account_plans as plans


class ProsoftSettingsTests(unittest.TestCase):
    setUp=base.CoreApiTests.setUp
    tearDown=base.CoreApiTests.tearDown
    create_company=base.CoreApiTests.create_company
    activate=base.CoreApiTests.activate
    scope=base.CoreApiTests.scope
    document=base.CoreApiTests.document
    journal=base.CoreApiTests.journal
    post=prior.ProsoftApiTests.post
    booked=prior.ProsoftApiTests.booked
    economic_snapshot=prior.ProsoftApiTests.economic_snapshot

    def get(self,mode='fiscal',cid=None):
        r=self.client.get(self.scope(('/prosoft-fiscal' if mode=='fiscal' else '/prosoft')+'/settings',cid))
        self.assertEqual(200,r.status_code,r.text);return r.json()

    def put(self,settings,version=0,mode='fiscal',status=200,cid=None):
        r=self.client.put(self.scope(('/prosoft-fiscal' if mode=='fiscal' else '/prosoft')+'/settings',cid),json={'version':version,'settings':settings})
        self.assertEqual(status,r.status_code,r.text);return r.json()

    def cfg(self):return self.get()['settings']|{'company_code':'99','plan_code':'52','species':{'55':{'code':'NFE','confirmed':True}}}

    def test_roundtrip_is_company_and_mode_scoped_and_survives_service_restart(self):
        self.assertEqual(0,self.get()['version']);self.assertEqual('0050',self.get()['settings']['plan_code'])
        r=self.put(self.cfg());self.assertEqual(1,r['version']);self.assertEqual('0052',r['settings']['plan_code'])
        self.assertIn('65',r['settings']['species'])
        self.assertEqual(r,BusinessCore(self.core.db).prosoft_settings(self.a['id'],'fiscal'))
        self.assertEqual(0,self.get('accounting')['version']);self.assertEqual(0,self.get(cid=self.b['id'])['version'])

    def test_version_conflict_invalid_input_and_audit_failure_are_atomic(self):
        cfg=self.cfg();saved=self.put(cfg)
        self.put(cfg,0,status=409)
        for changed in [{'plan_code':'0'},{'company_code':'abc'},{'unknown':True},{'species':{'99':{'code':'X','confirmed':True}}},
                        {'species':{'55':{'code':'','confirmed':True}}},{'cfop_accounts':{'1102':{'code':'00000','confirmed':False}}}]:
            self.put(cfg|changed,1,status=400)
        self.assertEqual(saved,self.get())
        with patch('app.prosoft_settings.audit',side_effect=RuntimeError('Synthetic audit failure')):
            with self.assertRaises(RuntimeError):self.core.save_prosoft_settings(self.a['id'],'fiscal',{'version':1,'settings':cfg},'teste')
        self.assertEqual(saved,self.get())

    def test_concurrent_save_has_one_winner(self):
        cfg=self.cfg()
        def save(_):
            try:return self.core.save_prosoft_settings(self.a['id'],'fiscal',{'version':0,'settings':cfg},'teste')
            except DomainError as e:return e.code
        with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(save,range(2)))
        self.assertEqual(1,sum(isinstance(v,dict) for v in result));self.assertIn('stale_version',result)

    def test_fiscal_record_selection_persists_and_exports_only_requested_direction(self):
        self.booked();self.booked('222',direction='outgoing',cfop='5102')
        saved=self.put(self.cfg()|{'record_types':['outgoing_notes']})
        self.assertEqual(['outgoing_notes'],self.get()['settings']['record_types'])
        pre=self.post('/prosoft-fiscal/preview',saved['settings']|{'period':'2026-11','settings_version':1})
        self.assertEqual({'SAIDAS.TXT'},set(pre['manifest']['files']))
        self.assertEqual('layout_not_selected',pre['manifest']['skipped'][0]['reason'])
        for selection in [[],['inventario'],['outgoing_notes','outgoing_notes'],'incoming_notes',[{}]]:
            self.put(saved['settings']|{'record_types':selection},1,status=400)

    def test_accounting_record_selection_can_exclude_configured_cta(self):
        self.core.create_journal(self.a['id'],self.journal()|{'document':'SYN','history':'Synthetic'},'teste')
        cfg=self.get('accounting')['settings']|{'company_code':'99','accounts':{str(a['id']):{'code':a['access_code'],'confirmed':True} for a in self.accounts}}
        cfg['accounts'][str(self.aid['3'])].update(third_mode='none',create_account={'destination_missing':True,'classifier':'1.01','name':'Synthetic','cost_center_mode':'0','reconciliation':'0'})
        saved=self.put(cfg,mode='accounting')
        self.assertEqual(['LC1','LC2'],saved['settings']['record_types'])
        pre=self.post('/prosoft/preview',saved['settings']|{'period':'2026-11','settings_version':1})
        self.assertEqual(0,pre['manifest']['record_counts']['CTA'])
        saved=self.put(saved['settings']|{'record_types':['CTA','LC2','LC1']},1,mode='accounting')
        pre=self.post('/prosoft/preview',saved['settings']|{'period':'2026-11','settings_version':2})
        self.assertEqual(1,pre['manifest']['record_counts']['CTA'])
        self.assertEqual(['LC1','LC2','CTA'],pre['manifest']['selected_record_types'])
        self.put(saved['settings']|{'record_types':['SLD']},2,mode='accounting',status=400)

    def test_saved_changes_invalidate_export_version_and_legacy_payload_remains_valid(self):
        self.booked();saved=self.put(self.cfg())
        payload=saved['settings']|{'period':'2026-11','settings_version':1}
        pre=self.post('/prosoft-fiscal/preview',payload)
        self.put(saved['settings']|{'plan_code':'53'},1)
        self.post('/prosoft-fiscal/confirm',payload|{'preview_hash':pre['preview_hash'],'destination_reviewed':True},409)
        payload.pop('settings_version')
        self.post('/prosoft-fiscal/confirm',payload|{'preview_hash':pre['preview_hash'],'destination_reviewed':True})

    def test_accounting_version_also_invalidates_previews(self):
        self.core.create_journal(self.a['id'],self.journal()|{'document':'SYN','history':'Synthetic'},'teste')
        cfg=self.get('accounting')['settings']|{'company_code':'99','accounts':{str(a['id']):{'code':a['access_code'],'confirmed':True} for a in self.accounts}}
        saved=self.put(cfg,mode='accounting');p=saved['settings']|{'period':'2026-11','settings_version':1}
        pre=self.post('/prosoft/preview',p)
        self.put(saved['settings'],1,mode='accounting')
        self.post('/prosoft/confirm',p|{'preview_hash':pre['preview_hash'],'destination_reviewed':True},409)

    def test_foreign_references_and_unknown_properties_rejected_without_accounts_changed(self):
        before=self.economic_snapshot();cfg=self.get('accounting')['settings']|{'company_code':'99'}
        foreign=next(a for a in self.core.accounts(self.b['id']) if a['analytical'])
        for changed in [{'accounts':{str(foreign['id']):{'code':'3','confirmed':True}}},
                        {'accounts':{str(self.aid['3']):{'code':'3','confirmed':True,'unknown':True}}},
                        {'participants':{'999999':{'code':'1','confirmed':False}}},
                        {'centers':{'999999':{'code':'1','confirmed':False}}},
                        {'accounts':{str(self.aid['3']):{'code':'3','confirmed':True,'third_mode':[]}}}]:
            self.put(cfg|changed,mode='accounting',status=400 if 'accounts' not in changed or str(foreign['id']) not in changed.get('accounts',{}) else 404)
        self.assertEqual(before,self.economic_snapshot());self.assertEqual(0,self.get('accounting')['version'])

    def test_saving_closed_period_preserves_economic_data_and_locks(self):
        self.booked();before=self.economic_snapshot()
        self.post('/periods/close',{'period':'2026-11','module':'fiscal','reason':'Synthetic close'})
        self.put(self.cfg());self.assertEqual(before,self.economic_snapshot())
        with self.core.db.read() as c:self.assertEqual(1,c.execute("SELECT closed FROM period_locks WHERE company_id=? AND module='fiscal'",(self.a['id'],)).fetchone()[0])

    def test_settings_permissions_csrf_active_context_and_generic_master_bypass(self):
        cfg=self.cfg()
        for action in ['read','export','edit']:
            username='synthetic-'+action
            r=self.client.post('/api/users',json={'username':username,'password':'Senha-ficticia-123!','role':'operator',
              'company_ids':[self.a['id']],'permissions':[{'company_id':self.a['id'],'routine':'fiscal.prosoft','action':a,'effect':'allow'} for a in set(['read',action])]})
            self.assertEqual(201,r.status_code,r.text)
            with TestClient(self.app) as other:
                login=other.post('/api/login',json={'username':username,'password':'Senha-ficticia-123!'}).json();other.headers['X-CSRF-Token']=login['csrf_token'];self.activate(self.a['id'],client=other)
                self.assertEqual(200,other.get(self.scope('/prosoft-fiscal/settings')).status_code)
                result=other.put(self.scope('/prosoft-fiscal/settings'),json={'version':0,'settings':cfg})
                self.assertEqual(200 if action=='edit' else 403,result.status_code,result.text)
                self.assertEqual(403,other.get(self.scope('/prosoft/settings')).status_code)
        self.assertEqual(403,self.client.put(self.scope('/prosoft-fiscal/settings'),headers={'X-CSRF-Token':''},json={'version':1,'settings':cfg}).status_code)
        self.activate(self.b['id']);self.put(cfg,1,status=409)
        self.activate(self.a['id'])
        self.post('/masters/prosoft_export_settings',{'code':'fiscal','name':'bypass','data':cfg},404)


class SharedMappingTests(unittest.TestCase):
    setUp=base.CoreApiTests.setUp
    tearDown=base.CoreApiTests.tearDown
    create_company=base.CoreApiTests.create_company
    activate=base.CoreApiTests.activate
    scope=base.CoreApiTests.scope
    post=plans.GlobalAccountPlanTests.post
    publish=plans.GlobalAccountPlanTests.publish
    prepare=plans.GlobalAccountPlanTests.prepare
    confirm=plans.GlobalAccountPlanTests.confirm

    def adopt(self):
        g,_,_=self.publish();self.activate(self.b['id']);self.confirm(self.prepare(g['id']))
        return {a['access_code']:a for a in self.core.accounts(self.b['id'])}

    def save(self,refs):
        settings={'company_code':'99','accounts':{str(refs['00101']['id']):{'code':'123','confirmed':True,'third_mode':'none'}}}
        return self.core.save_prosoft_settings(self.b['id'],'accounting',{'version':0,'settings':settings},'teste')

    def test_global_alias_materialization_keeps_mapping_without_copy_on_save(self):
        refs=self.adopt()
        with self.core.db.read() as c:before=c.execute('SELECT count(*) FROM accounts WHERE company_id=?',(self.b['id'],)).fetchone()[0]
        self.save(refs)
        with self.core.db.read() as c:self.assertEqual(before,c.execute('SELECT count(*) FROM accounts WHERE company_id=?',(self.b['id'],)).fetchone()[0])
        self.core.create_journal(self.b['id'],{'date':'2026-11-06','document':'SYN','history':'Synthetic','idempotency_key':'synthetic','lines':[
            {'account_id':refs['00101']['id'],'debit':'1.00','credit':'0'}, {'account_id':refs['00102']['id'],'debit':'0','credit':'1.00'}]},'teste')
        current={a['access_code']:a for a in self.core.accounts(self.b['id'])}
        saved=self.core.prosoft_settings(self.b['id'],'accounting')
        self.assertEqual('123',saved['settings']['accounts'][str(current['00101']['id'])]['code'])
        self.assertFalse(saved['unavailable_accounts'])

    def test_another_global_identity_does_not_inherit_mapping_by_access_code(self):
        refs=self.adopt();self.save(refs)
        newer=plans.synthetic_plan();newer['accounts'][1]['name']='Outra identidade sintetica'
        g,_,_=self.publish(newer);self.confirm(self.prepare(g['id']))
        read=self.core.prosoft_settings(self.b['id'],'accounting')
        self.assertFalse(read['settings']['accounts']);self.assertEqual(1,len(read['unavailable_accounts']))
        saved=self.core.save_prosoft_settings(self.b['id'],'accounting',{'version':1,'settings':read['settings']},'teste')
        self.assertEqual(read['unavailable_accounts'],saved['unavailable_accounts'])


if __name__=='__main__':unittest.main()
