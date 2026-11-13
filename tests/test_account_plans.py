"""Planos sintéticos: isolamento, origem, concorrência e intercâmbio HTTP."""
import base64
import json
import unittest
from fastapi.testclient import TestClient
import test_core as base
from app.account_plans import default_plan
from app.account_plan_codec import encode_plan


class AccountPlanTests(unittest.TestCase):
    setUp=base.CoreApiTests.setUp
    tearDown=base.CoreApiTests.tearDown
    create_company=base.CoreApiTests.create_company
    activate=base.CoreApiTests.activate
    scope=base.CoreApiTests.scope

    def post(self,path,payload,status=200):
        r=self.client.post(self.scope(path),json=payload)
        self.assertEqual(status,r.status_code,r.text)
        return r.json()

    def preview(self,plan=None,**extra):
        raw=json.dumps(plan or default_plan(),ensure_ascii=False).encode()
        return self.post('/account-plans/preview',{'format':'native','filename':'ficticio.json','content_base64':base64.b64encode(raw).decode(),**extra})

    def confirm(self,p,status=200):
        return self.post(f"/account-plans/{p['id']}/confirm",{'preview_hash':p['preview_hash'],'reason':'Importação sintética revisada','properties_reviewed':True},status)

    def empty_company(self):
        payload={'code':'EMPTY','name':'Empresa sintética sem plano','tax_id':'TEST00030001'+base.cnpj_digits('TEST00030001'),'regime':'outros','state':'SP','create_default_accounts':False}
        r=self.client.post('/api/companies',json=payload);self.assertEqual(201,r.status_code,r.text)
        self.activate(r.json()['id']);self.a=r.json()

    def test_template_preserves_legacy_repeat_and_original(self):
        before=self.core.accounts(self.a['id'])
        p=self.post('/account-plans/preview',{'format':'default'})
        self.assertEqual((67,6),(p['created'],p['preserved']))
        self.assertTrue(p['can_confirm']);r=self.confirm(p)
        self.assertEqual(67,r['created']);self.assertTrue(self.confirm(p)['duplicate'])
        self.assertEqual(73,len(self.core.accounts(self.a['id'])))
        for row in before:self.assertEqual(row,next(x for x in self.core.accounts(self.a['id']) if x['id']==row['id']))
        p2=self.post('/account-plans/preview',{'format':'default'})
        self.assertEqual((0,73),(p2['created'],p2['preserved']));self.confirm(p2)
        original=self.client.get(self.scope(f"/account-plans/{p['id']}/original"))
        self.assertEqual(default_plan(),original.json());self.assertEqual(6,len(self.core.accounts(self.b['id'])))

    def test_native_exact_roundtrip_metadata_original(self):
        self.empty_company();plan=json.loads(json.dumps(default_plan()));plan['accounts'][0]['prosoft']['currency_conversion']='N'
        plan['future']={'synthetic':'retained'};plan['accounts'][0]['custom_tag']={'value':'future synthetic metadata'}
        p=self.preview(plan);self.confirm(p)
        payload={'format':'native','plan_code':'0050'}
        ep=self.post('/account-plans/export-preview',payload)
        out=self.post('/account-plans/export-confirm',payload|{'preview_hash':ep['preview_hash'],'destination_reviewed':True})
        decoded=json.loads(base64.b64decode(out['content_base64']))
        self.assertEqual(plan['accounts'],decoded['accounts']);self.assertEqual(plan['properties'],decoded['properties'])
        self.assertEqual(plan['future'],decoded['future'])
        again=self.preview(decoded);self.assertEqual(73,again['preserved']);self.confirm(again)
        self.post('/account-plans/export-preview',{'format':'prosoft-import','plan_code':'0050'},400)

    def test_conflicts_are_atomic_and_do_not_overwrite(self):
        p=self.preview();self.assertFalse(p['can_confirm']);self.assertEqual(6,len(p['conflicts']))
        self.confirm(p,409);self.assertEqual(6,len(self.core.accounts(self.a['id'])))

    def test_duplicate_classifiers_preserved_as_reference_without_activation(self):
        self.empty_company();plan=json.loads(json.dumps(default_plan()))
        duplicate=dict(plan['accounts'][0],access_code='99000',prosoft_code='99000',name='Conta sintética repetida')
        plan['accounts'].append(duplicate)
        p=self.preview(plan);self.assertFalse(p['can_confirm']);self.assertEqual(1,p['conflict_count'])
        self.confirm(p,409);self.assertEqual([],self.core.accounts(self.a['id']))
        payload={'preview_hash':p['preview_hash'],'reason':'Guardar a referência sintética completa','properties_reviewed':True,'activation_mode':'reference'}
        r=self.post(f"/account-plans/{p['id']}/confirm",payload);self.assertTrue(r['reference_only']);self.assertEqual(74,r['record_count'])
        self.assertEqual([],self.core.accounts(self.a['id']));self.assertTrue(self.post(f"/account-plans/{p['id']}/confirm",payload)['duplicate'])
        native=self.client.get(self.scope(f"/account-plans/{p['id']}/native"));self.assertEqual(200,native.status_code)
        self.assertEqual(plan['accounts'],native.json()['accounts'])
        self.assertEqual('reference',self.client.get(self.scope('/account-plans')).json()[0]['status'])

    def test_stale_preview_on_account_change_and_wrong_hash(self):
        p=self.post('/account-plans/preview',{'format':'default'})
        row=self.core.accounts(self.a['id'])[0]
        self.client.put(self.scope('/accounts/'+str(row['id'])),json=row|{'name':'Caixa sintético alterado'})
        self.confirm(p,409)
        self.post(f"/account-plans/{p['id']}/confirm",{'preview_hash':'wrong','reason':'Teste','properties_reviewed':True},409)
        self.assertEqual(6,len(self.core.accounts(self.a['id'])))

    def test_prosoft_import_file_and_export_204_with_explicit_padding(self):
        self.empty_company();raw,_=encode_plan(default_plan(),'prosoft-import')
        opts={'trailing_zero_policy':'trim_groups'}
        p=self.post('/account-plans/preview',{'format':'prosoft-import','filename':'CTBPLANO0050.TXT','content_base64':base64.b64encode(raw).decode(),'options':opts})
        self.assertEqual(73,p['record_count']);self.assertEqual(73,p['created']);self.confirm(p)
        for format in ('prosoft-import','prosoft-export'):
            payload={'format':format,'plan_code':'0050'}
            ep=self.post('/account-plans/export-preview',payload)
            out=self.post('/account-plans/export-confirm',payload|{'preview_hash':ep['preview_hash'],'destination_reviewed':True})
            lines=base64.b64decode(out['content_base64']).splitlines()
            self.assertTrue(all(len(x)==204 for x in (lines[1:] if format=='prosoft-import' else lines)))
            if format=='prosoft-import':self.assertEqual(103,len(lines[0]))

    def test_invalid_inputs_return_400_not_500(self):
        for payload in ({'format':'native','filename':'x','content_base64':'!!!'},
                        {'format':'native','filename':'x','content_base64':base64.b64encode(b'{}').decode()},
                        {'format':'prosoft-export','filename':'x','content_base64':base64.b64encode(b'bad').decode()},
                        {'format':'default','options':[]}):
            self.post('/account-plans/preview',payload,400)
        self.post('/account-plans/export-preview',{'format':'bad'},400)

    def test_company_context_auth_and_import_create_rights(self):
        p=self.post('/account-plans/preview',{'format':'default'})
        with TestClient(self.app) as anonymous:self.assertEqual(401,anonymous.get(self.scope('/account-plans/default')).status_code)
        permissions=[{'company_id':self.a['id'],'routine':routine,'action':action,'effect':'allow'} for routine,action in [('accounting.accounts','read'),('accounting.imports','import')]]
        r=self.client.post('/api/users',json={'username':'plan-importer','password':'Senha-sintetica-2026','role':'custom','company_ids':[self.a['id']],'permissions':permissions})
        self.assertEqual(201,r.status_code,r.text)
        with TestClient(self.app) as limited:
            s=limited.post('/api/login',json={'username':'plan-importer','password':'Senha-sintetica-2026'}).json();limited.headers['X-CSRF-Token']=s['csrf_token']
            self.activate(self.a['id'],client=limited)
            self.assertEqual(200,limited.post(self.scope('/account-plans/preview'),json={'format':'default'}).status_code)
            self.assertEqual(403,limited.post(self.scope(f"/account-plans/{p['id']}/confirm"),json={'preview_hash':p['preview_hash'],'reason':'Teste','properties_reviewed':True}).status_code)
            self.assertEqual(403,limited.get(self.scope(f"/account-plans/{p['id']}/original")).status_code)
        self.activate(self.b['id']);self.confirm(p,409)
        self.assertEqual(404,self.client.get(self.scope(f"/account-plans/{p['id']}/original",self.b['id'])).status_code)

    def test_ascii_changes_and_export_stale_are_explicit(self):
        row=self.core.accounts(self.a['id'])[0]
        r=self.client.put(self.scope('/accounts/'+str(row['id'])),json=row|{'name':'Caixa acentuação'})
        self.assertEqual(200,r.status_code,r.text)
        payload={'format':'prosoft-import','plan_code':'0050'};p=self.post('/account-plans/export-preview',payload)
        self.assertTrue(p['manifest']['needs_ascii_review'])
        self.post('/account-plans/export-confirm',payload|{'preview_hash':p['preview_hash'],'destination_reviewed':True},400)
        ok=self.post('/account-plans/export-confirm',payload|{'preview_hash':p['preview_hash'],'destination_reviewed':True,'allow_ascii':True})
        self.assertIn(b'Caixa acentuacao',base64.b64decode(ok['content_base64']))
        row=self.core.accounts(self.a['id'])[0];self.client.put(self.scope('/accounts/'+str(row['id'])),json=row|{'name':'Outro nome'})
        self.post('/account-plans/export-confirm',payload|{'preview_hash':p['preview_hash'],'destination_reviewed':True,'allow_ascii':True},409)


if __name__=='__main__':unittest.main()
