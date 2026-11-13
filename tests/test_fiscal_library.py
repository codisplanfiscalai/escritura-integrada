"""Global fiscal references are informational; imported rules remain company drafts."""
from copy import deepcopy
import json
import unittest
import test_core as base
from app.cfop_source import default_source_bundle
from app.db import Database


class FiscalLibraryTests(unittest.TestCase):
    setUp=base.CoreApiTests.setUp
    tearDown=base.CoreApiTests.tearDown
    create_company=base.CoreApiTests.create_company
    activate=base.CoreApiTests.activate
    scope=base.CoreApiTests.scope

    def request(self,method,path,payload=None,status=200):
        response=getattr(self.client,method)(self.scope(path),**({'json':payload} if payload is not None else {}))
        self.assertEqual(status,response.status_code,response.text[:1500]);return response.json()

    def pattern(self,**changes):
        payload={'code':'estrutura-revisavel','name':'Comércio fictício','regime':'outros','segment':'commerce','source':'Fundamento fictício revisável','reason':'Publicação de estrutura sintética','rules':[{'name':'ICMS proposto','tax':'icms','rate':'18.0000','cfop':'5102'}]}
        payload.update(changes)
        return self.request('post','/fiscal-patterns',payload,201)

    def apply_payload(self,pattern,**changes):
        result={'version':pattern['version'],'segment':'commerce','valid_from':'2026-11-01','valid_to':'2026-11-30','responsible':'Revisor fictício','reason':'Importar e conferir sem aplicar automaticamente'}
        result.update(changes);return result

    def apply(self,pattern,payload=None):
        payload=payload or self.apply_payload(pattern)
        preview=self.request('post',f"/fiscal-patterns/{pattern['id']}/preview",payload)
        return self.request('post',f"/fiscal-patterns/{pattern['id']}/apply",payload|{'preview_hash':preview['preview_hash']})

    def test_official_global_cfop_and_source_rates_not_company_data(self):
        result=self.request('get','/global-fiscal-catalogs?kind=cfop')
        self.assertEqual(619,result['total']);self.assertEqual([],self.core.catalogs(self.a['id']))
        cfop=self.request('get','/global-fiscal-catalogs?search=1102')['rows'][0]
        source=next(r for r in default_source_bundle()['records'] if r['code']=='1102')
        self.assertEqual(source['rates_declared'],cfop['rates_declared']);self.assertTrue(cfop['informational_only'])
        self.assertEqual('',cfop['valid_from']);self.assertTrue(cfop['official_wordings'])
        self.assertEqual([],self.core.rules(self.a['id']))
        self.activate(self.b['id'])
        other=self.client.get(self.scope('/global-fiscal-catalogs?search=1102',self.b['id'])).json()['rows'][0]
        self.assertEqual(cfop['id'],other['id']);self.assertEqual([],self.core.catalogs(self.b['id']))

    def test_cfop_edit_is_versioned_preserves_original_and_never_changes_company_catalog(self):
        local=self.request('post','/catalogs',{'kind':'cfop','code':'1102','description':'Minha descrição','active':False},201)
        row=self.request('get','/global-fiscal-catalogs?search=1102')['rows'][0]
        edited=self.request('put',f"/global-fiscal-catalogs/{row['id']}",{'version':row['version'],'rates_declared':['17.5','0'],'reason':'Informação revisada'})
        self.assertEqual(['17.5','0'],edited['rates_declared']);self.assertEqual(row['rates_declared'],edited['source_rates_declared'])
        self.request('put',f"/global-fiscal-catalogs/{row['id']}",{'version':row['version'],'rates_declared':['2'],'reason':'Concorrência'},409)
        versions=self.request('get',f"/global-fiscal-catalogs/{row['id']}/versions")
        self.assertEqual([2,1],[r['version'] for r in versions]);self.assertEqual(row['rates_declared'],versions[-1]['snapshot']['rates_declared'])
        self.assertEqual(local,self.core.catalogs(self.a['id'])[0]);self.assertEqual([],self.core.rules(self.a['id']))
        Database(self.tmp.name)
        again=self.request('get','/global-fiscal-catalogs?search=1102')['rows'][0]
        self.assertEqual(['17.5','0'],again['rates_declared'])

    def test_service_identity_includes_table_and_jurisdiction(self):
        base={'kind':'service','code':'01.01','description':'Serviço de referência','source':'Tabela declarada','service_system':'lc116','jurisdiction':'BR','reason':'Cadastro global'}
        a=self.request('post','/global-fiscal-catalogs',base,201)
        b=self.request('post','/global-fiscal-catalogs',base|{'service_system':'municipal','jurisdiction':'3550308'},201)
        self.assertNotEqual(a['id'],b['id'])
        self.request('post','/global-fiscal-catalogs',base,409)
        self.request('post','/global-fiscal-catalogs',base|{'service_system':'municipal','jurisdiction':'BR'},400)
        self.assertEqual(2,self.request('get','/global-fiscal-catalogs?kind=service')['total'])
        self.assertEqual([],self.core.masters(self.a['id'],'service'))

    def test_pattern_requires_preview_and_creates_independent_inactive_company_drafts(self):
        pattern=self.pattern();payload=self.apply_payload(pattern)
        self.request('post',f"/fiscal-patterns/{pattern['id']}/apply",payload,409)
        result=self.apply(pattern,payload);rules=self.core.rules(self.a['id'])
        self.assertEqual(1,len(rules));self.assertFalse(rules[0]['active']);self.assertEqual('draft',rules[0]['status'])
        self.assertEqual([],self.core.rules(self.b['id']))
        again=self.apply(pattern,payload);self.assertTrue(again['duplicate']);self.assertEqual(result['id'],again['id'])
        imports=self.request('get','/fiscal-patterns/imports');self.assertEqual('commerce',imports[0]['snapshot']['segment_confirmed'])
        updated=self.request('put',f"/rules/{rules[0]['id']}",rules[0]|{'rate':'12','name':'Minha adaptação','active':False})
        self.assertEqual('12',updated['rate'])
        global_row=self.request('get','/fiscal-patterns')['rows'][0];self.assertEqual('18.0000',global_row['rules'][0]['rate'])
        newer=self.request('put',f"/fiscal-patterns/{pattern['id']}",pattern|{'rules':[{'name':'Proposta nova','tax':'pis','rate':'1.65'}],'reason':'Nova versão global'})
        self.assertEqual(2,newer['version']);self.assertEqual('12',self.core.rules(self.a['id'])[0]['rate'])
        self.assertEqual(1,imports[0]['snapshot']['version'])
        self.assertEqual(2,len(self.request('get',f"/fiscal-patterns/{pattern['id']}/versions")))

    def test_stale_preview_rolls_back_and_regime_segment_validity_are_enforced(self):
        pattern=self.pattern(valid_from='2026-01-01',valid_to='2026-12-31');payload=self.apply_payload(pattern)
        preview=self.request('post',f"/fiscal-patterns/{pattern['id']}/preview",payload)
        self.request('post','/rules',{'name':'Nova regra local','tax':'pis','valid_from':'2026-01-01'},201)
        self.request('post',f"/fiscal-patterns/{pattern['id']}/apply",payload|{'preview_hash':preview['preview_hash']},409)
        self.assertEqual(1,len(self.core.rules(self.a['id'])));self.assertEqual([],self.request('get','/fiscal-patterns/imports'))
        for change in [{'segment':'services'},{'valid_from':'2025-12-01'},{'valid_to':''}]:
            self.request('post',f"/fiscal-patterns/{pattern['id']}/preview",payload|change,400)
        other=self.pattern(code='regime-incompativel',regime='lucro_real')
        self.request('post',f"/fiscal-patterns/{other['id']}/preview",self.apply_payload(other),400)

    def test_invalid_rates_and_fields_are_rejected_without_mutation(self):
        row=self.request('get','/global-fiscal-catalogs?search=1102')['rows'][0]
        for rates in [['101'],['NaN'],[18],['-1'],['1e2'],[True],None]:
            self.request('put',f"/global-fiscal-catalogs/{row['id']}",{'version':row['version'],'rates_declared':rates,'reason':'Teste inválido'},400)
        self.assertEqual(row,self.request('get','/global-fiscal-catalogs?search=1102')['rows'][0])
        self.pattern(rules=[{'name':'Sem regra aprovada','tax':'pis','rate':None,'status':'validated','active':True,'company_id':self.b['id']}])
        published=self.request('get','/fiscal-patterns')['rows'][0]
        self.assertNotIn('company_id',published['rules'][0]);self.assertNotIn('status',published['rules'][0])
        self.apply(published);self.assertFalse(self.core.rules(self.a['id'])[0]['active'])

    def test_global_write_requires_admin_and_company_permission_is_not_global_authority(self):
        from fastapi.testclient import TestClient
        pattern=self.pattern();payload=self.apply_payload(pattern)
        permissions=[{'company_id':self.a['id'],'routine':routine,'action':'*','effect':'allow'} for routine in ['fiscal.masters','fiscal.parameters']]
        response=self.client.post('/api/users',json={'username':'fiscal-local','password':'Senha-ficticia-global-123','role':'custom','company_ids':[self.a['id']],'permissions':permissions})
        self.assertEqual(201,response.status_code,response.text)
        with TestClient(self.app) as client:
            response=client.post('/api/login',json={'username':'fiscal-local','password':'Senha-ficticia-global-123'})
            client.headers['X-CSRF-Token']=response.json()['csrf_token']
            client.post('/api/context',json={'company_id':self.a['id'],'period':'2026-11','module':'fiscal'})
            self.assertEqual(200,client.get(self.scope('/global-fiscal-catalogs')).status_code)
            self.assertEqual(403,client.get(self.scope('/fiscal-patterns',self.b['id'])).status_code)
            self.assertEqual(403,client.post(self.scope('/global-fiscal-catalogs'),json={}).status_code)
            self.assertEqual(403,client.put(self.scope(f"/fiscal-patterns/{pattern['id']}"),json=pattern).status_code)
            preview=client.post(self.scope(f"/fiscal-patterns/{pattern['id']}/preview"),json=payload)
            self.assertEqual(200,preview.status_code,preview.text)
            applied=client.post(self.scope(f"/fiscal-patterns/{pattern['id']}/apply"),json=payload|{'preview_hash':preview.json()['preview_hash']})
            self.assertEqual(200,applied.status_code,applied.text)
            self.assertFalse(self.core.rules(self.a['id'])[0]['active'])

    def test_backup_roundtrip_retains_global_source_versions_and_company_snapshot(self):
        from pathlib import Path
        from app.snapshots import create_snapshot,restore_snapshot,manifest
        pattern=self.pattern();self.apply(pattern)
        archive=Path(self.tmp.name)/'fiscal-backup.zip';target=Path(self.tmp.name)/'restored'
        before=create_snapshot(self.app.state.db.path,archive)
        self.assertEqual(5,len(before['fiscal_library']))
        restored=restore_snapshot(archive,target)
        self.assertEqual(before['fiscal_library'],restored['fiscal_library'])
        db=Database(target)
        with db.read() as conn:
            self.assertEqual(1,conn.execute('SELECT COUNT(*) FROM company_fiscal_pattern_imports').fetchone()[0])
            self.assertEqual(619,conn.execute('SELECT COUNT(*) FROM global_fiscal_catalogs').fetchone()[0])
            self.assertEqual(default_source_bundle(),json.loads(conn.execute('SELECT data_json FROM global_fiscal_sources').fetchone()[0]))
        with self.app.state.db.transaction() as conn:
            conn.execute("UPDATE global_fiscal_sources SET data_json='{}'")
        with self.assertRaisesRegex(RuntimeError,'Fonte fiscal global'):
            manifest(self.app.state.db.path)

    def test_derivation_preserves_parent_version_and_allows_pharmacy_specialization(self):
        parent=self.pattern()
        child=self.pattern(code='farmacia-especializada',name='Farmácia fictícia',base_pattern_id=parent['id'],base_version=1,activity='Farmácia',cnae_prefix='4771',rules=[{'name':'Regra de trabalho farmacêutica sem alíquota','tax':'pis','rate':None}])
        self.assertEqual({'id':parent['id'],'version':1,'code':parent['code']},{k:child['derived_from'][k] for k in ('id','version','code')})
        self.assertEqual('4771',child['cnae_prefix']);self.assertEqual('Farmácia',child['activity'])
        self.request('put',f"/fiscal-patterns/{parent['id']}",parent|{'reason':'Alterar somente origem','name':'Origem revisada'})
        current=self.request('get','/fiscal-patterns')['rows'];saved=next(r for r in current if r['id']==child['id'])
        self.assertEqual(1,saved['derived_from']['version']);self.assertEqual('Farmácia fictícia',saved['name'])
        payload=self.apply_payload(child,activity_confirmed='Farmácia')
        self.request('post',f"/fiscal-patterns/{child['id']}/preview",payload,400)
        with self.app.state.db.transaction() as conn:
            conn.execute("UPDATE companies SET cnae='4771701',version=version+1 WHERE id=?",(self.a['id'],))
        self.request('post',f"/fiscal-patterns/{child['id']}/preview",payload|{'activity_confirmed':'Outra'},400)
        self.apply(child,payload)
        self.assertFalse(self.core.rules(self.a['id'])[0]['active']);self.assertIsNone(self.core.rules(self.a['id'])[0]['rate'])
        changed=self.request('put',f"/fiscal-patterns/{child['id']}",child|{'name':'Adaptação farmacêutica revisada','reason':'Ajustar derivado','derived_from':{'id':999,'version':99}})
        self.assertEqual(child['derived_from'],changed['derived_from'])
        self.assertEqual('Origem revisada',next(r for r in self.request('get','/fiscal-patterns')['rows'] if r['id']==parent['id'])['name'])
        self.request('post','/fiscal-patterns',{'code':'origem-ausente','name':'Padrão inválido','regime':'outros','segment':'commerce','source':'Teste','reason':'Teste','base_pattern_id':999,'base_version':1,'rules':[{'name':'Teste','tax':'pis'}]},404)

    def test_duplicate_confirmation_requires_current_preview_and_cnae_change_invalidates_it(self):
        pattern=self.pattern();payload=self.apply_payload(pattern)
        preview=self.request('post',f"/fiscal-patterns/{pattern['id']}/preview",payload)
        confirmed=payload|{'preview_hash':preview['preview_hash']}
        self.request('post',f"/fiscal-patterns/{pattern['id']}/apply",confirmed)
        self.request('post',f"/fiscal-patterns/{pattern['id']}/apply",confirmed,409)
        self.assertTrue(self.apply(pattern)['duplicate']);self.assertEqual(1,len(self.core.rules(self.a['id'])))
        current=self.request('post',f"/fiscal-patterns/{pattern['id']}/preview",payload)
        self.request('post',f"/fiscal-patterns/{pattern['id']}/apply",payload|{'reason':'Outra confirmação','preview_hash':current['preview_hash']},409)

        filtered=self.pattern(code='cnae-conferido',cnae_prefix='47')
        with self.app.state.db.transaction() as conn:
            conn.execute("UPDATE companies SET cnae='4771701',version=version+1 WHERE id=?",(self.a['id'],))
        request=self.apply_payload(filtered)
        preview=self.request('post',f"/fiscal-patterns/{filtered['id']}/preview",request)
        with self.app.state.db.transaction() as conn:
            conn.execute("UPDATE companies SET cnae='4772500',version=version+1 WHERE id=?",(self.a['id'],))
        self.request('post',f"/fiscal-patterns/{filtered['id']}/apply",request|{'preview_hash':preview['preview_hash']},409)

    def test_review_surfaces_changed_cnae_and_regime_without_mutating_copied_rules(self):
        pattern=self.pattern(cnae_prefix='47',activity='Farmácia')
        with self.app.state.db.transaction() as conn:
            conn.execute("UPDATE companies SET cnae='4771701',version=version+1 WHERE id=?",(self.a['id'],))
        self.apply(pattern,self.apply_payload(pattern,activity_confirmed='Farmácia'))
        imports=self.request('get','/fiscal-patterns/imports');self.assertEqual([],imports[0]['warnings'])
        self.assertEqual('4771701',imports[0]['snapshot']['company_cnae']);self.assertEqual('Farmácia',imports[0]['snapshot']['activity_confirmed'])
        before=deepcopy(self.core.rules(self.a['id']))
        with self.app.state.db.transaction() as conn:
            conn.execute("UPDATE companies SET cnae='6201501',regime='lucro_real',version=version+1 WHERE id=?",(self.a['id'],))
        reviewed=self.request('get','/fiscal-patterns/imports')
        self.assertEqual({'regime_changed','cnae_mismatch'},{w['code'] for w in reviewed[0]['warnings']})
        self.assertFalse(reviewed[0]['activity_enforced_in_assessment']);self.assertEqual(before,self.core.rules(self.a['id']))
