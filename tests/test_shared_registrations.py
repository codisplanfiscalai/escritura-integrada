"""Synthetic registry CRUD, explicit sharing, local FK preservation and RBAC."""
import json
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
import test_core as base
import test_third_parties as third
from app.db import Database
from app.shared_registrations import migrate


class SharedRegistrationTests(unittest.TestCase):
    setUp=base.CoreApiTests.setUp
    tearDown=base.CoreApiTests.tearDown
    create_company=base.CoreApiTests.create_company
    activate=base.CoreApiTests.activate
    scope=base.CoreApiTests.scope
    document=base.CoreApiTests.document
    def limited(self,name,company_ids,permissions,activate_cid=None):
        r=self.client.post('/api/users',json={'username':name,'password':'Senha-sintetica-2026','role':'custom','company_ids':company_ids,'permissions':[{'company_id':cid,'routine':routine,'action':action,'effect':'allow'} for cid,routine,action in permissions]})
        self.assertEqual(201,r.status_code,r.text)
        client=TestClient(self.app);self.addCleanup(client.close)
        login=client.post('/api/login',json={'username':name,'password':'Senha-sintetica-2026'})
        self.assertEqual(200,login.status_code,login.text)
        client.headers['X-CSRF-Token']=login.json()['csrf_token']
        self.activate(activate_cid or self.a['id'],client=client)
        return client,r.json()
    party=third.ThirdPartyTests.party

    def request(self,method,path,body=None,status=200,client=None,cid=None):
        response=(client or self.client).request(method,self.scope('/registrations/'+path,cid),**({'json':body} if body is not None else {}))
        self.assertEqual(status,response.status_code,response.text)
        return response.json()

    def accountant(self,cid=None,tax_id='52998224725'):
        return self.request('POST','accountant',{'name':'Contador sintético','tax_id':tax_id,'data':{'crc':'1SP000000','crc_state':'SP','category':'accountant','email':'teste@example.invalid'}},201,cid=cid)

    def test_accountant_crud_shares_one_profile_and_preserves_links(self):
        row=self.accountant()
        self.request('POST',f"accountant/{row['id']}/use",{'version':row['version']})
        linked=self.request('POST',f"accountant/{row['id']}/links",{'version':row['version'],'company_id':self.b['id']})
        self.assertEqual(2,len(linked['links']))
        self.assertEqual(row['id'],self.request('GET','accountant',cid=self.b['id'])[0]['id'])
        edited=self.request('PUT',f"accountant/{row['id']}",linked|{'name':'Nome revisado'})
        self.assertEqual('Nome revisado',self.request('GET',f"accountant/{row['id']}",cid=self.b['id'])['name'])
        self.request('PUT',f"accountant/{row['id']}",linked,status=409)
        disabled=self.request('DELETE',f"accountant/{row['id']}",{'version':edited['version']})
        self.assertFalse(disabled['active'])
        self.assertEqual(2,len(disabled['links']))
        with self.core.db.read() as conn:
            self.assertEqual(1,conn.execute("SELECT count(*) FROM shared_registrations WHERE kind='accountant'").fetchone()[0])
            self.assertEqual(0,conn.execute('SELECT count(*) FROM masters').fetchone()[0])

    def test_third_party_sharing_preserves_document_and_product_scope(self):
        row=self.request('POST','third-party',{'name':'Fornecedor fictício','tax_id':'11222333000181','code':'LOCAL-A','data':{'address':'Rua sintética'}},201)
        self.assertEqual([],row['links'])
        row=self.request('POST',f"third-party/{row['id']}/use",{'version':row['version']})
        mid=row['links'][0]['master_id']
        document=self.core.create_document(self.a['id'],self.document()|{'participant_id':mid,'partner_tax_id':row['tax_id']},'synthetic')
        product=self.core.save_master(self.a['id'],'product',{'code':'PROD','name':'Produto local','data':{}},'synthetic')
        linked=self.request('POST',f"third-party/{row['id']}/links",{'version':row['version'],'company_id':self.b['id'],'code':'LOCAL-B'})
        self.assertEqual(2,len(linked['links']))
        self.assertNotEqual(*[l['master_id'] for l in linked['links']])
        self.assertEqual([],self.core.masters(self.b['id'],'product'))
        self.assertEqual(product['id'],self.core.masters(self.a['id'],'product')[0]['id'])
        edited=self.request('PUT',f"third-party/{row['id']}",linked|{'name':'Nome comum revisado'})
        self.assertEqual('Nome comum revisado',self.request('GET','third-party',cid=self.b['id'])[0]['name'])
        self.request('DELETE',f"third-party/{row['id']}",{'version':edited['version']})
        with self.core.db.read() as conn:
            self.assertEqual(mid,self.core._document(conn,self.a['id'],document['id'])['participant_id'])
        self.assertEqual('Fornecedor fictício',self.core.third_party(self.a['id'],mid)['name'])

    def test_legacy_migration_idempotent_no_merge_or_private_data_export(self):
        a=self.party(email='private-a@example.invalid')
        b=self.party(self.b['id'],email='private-b@example.invalid')
        with self.core.db.read() as conn:
            # Simulate pre-feature installation, retaining all original masters.
            conn.execute('DELETE FROM shared_registration_links')
            conn.execute('DELETE FROM shared_registrations')
            before=[dict(r) for r in conn.execute('SELECT * FROM masters ORDER BY id')]
            migrate(conn)
            first=list(conn.iterdump())
            migrate(conn)
            self.assertEqual(first,list(conn.iterdump()))
            self.assertEqual(before,[dict(r) for r in conn.execute('SELECT * FROM masters ORDER BY id')])
            self.assertEqual(2,conn.execute('SELECT count(*) FROM shared_registrations').fetchone()[0])
        rows=self.request('GET','third-party')
        self.assertEqual(2,len(rows))
        self.assertNotIn('private-',json.dumps(rows))
        self.assertEqual(a['id'],rows[0]['links'][0]['master_id'])
        self.assertEqual(rows,self.request('GET','third-party',cid=self.b['id']))
        self.assertNotEqual(rows[0]['id'],rows[1]['id'])

    def test_permissions_hidden_links_cannot_edit_share_or_guess_other_scope(self):
        row=self.accountant()
        self.request('POST',f"accountant/{row['id']}/use",{'version':row['version']})
        linked=self.request('POST',f"accountant/{row['id']}/links",{'version':1,'company_id':self.b['id']})
        cid=self.a['id']
        client,_=self.limited('restricted-registry',[cid],[(cid,'accounting.accountants',a) for a in ('read','create','edit','delete')])
        visible=self.request('GET','accountant',client=client)[0]
        self.assertEqual([cid],[l['company_id'] for l in visible['links']])
        self.assertNotIn(str(self.b['id']),json.dumps(visible['links']))
        self.request('PUT',f"accountant/{row['id']}",linked|{'name':'Forbidden'},403,client)
        self.request('DELETE',f"accountant/{row['id']}",{'version':linked['version']},403,client)
        self.request('GET','accountant',status=403,client=client,cid=self.b['id'])
        self.activate(self.b['id'])
        other=self.accountant(self.b['id'],'11144477735')
        self.activate(cid)
        self.assertEqual(other['id'],self.request('GET',f"accountant/{other['id']}")['id'])

    def test_forbidden_destination_and_csrf_leave_no_partial_rows(self):
        row=self.accountant();cid=self.a['id']
        client,_=self.limited('source-only',[cid],[(cid,'accounting.accountants',a) for a in ('read','edit')])
        self.request('POST',f"accountant/{row['id']}/links",{'version':1,'company_id':self.b['id']},403,client)
        self.assertEqual(0,len(self.request('GET',f"accountant/{row['id']}")['links']))
        response=self.client.request('DELETE',self.scope(f"/registrations/accountant/{row['id']}"),headers={'X-CSRF-Token':''},json={'version':1})
        self.assertEqual(403,response.status_code)
        self.assertTrue(self.request('GET',f"accountant/{row['id']}")['active'])

    def test_duplicate_identity_not_merged_and_stale_link_rejected(self):
        a=self.party();b=self.party(self.b['id'])
        row=self.request('GET','third-party')[0]
        self.request('POST',f"third-party/{row['id']}/links",{'version':row['version'],'company_id':self.b['id'],'code':'NEW'},409)
        self.assertEqual([b['id']],[p['id'] for p in self.core.masters(self.b['id'],'participant')])
        self.request('POST','third-party',{'name':'Duplicado','tax_id':a['tax_id'],'code':'NEW'},409)
        self.assertEqual(2,len(self.request('GET','third-party')))
        row=self.accountant()
        self.request('POST',f"accountant/{row['id']}/links",{'version':99,'company_id':self.b['id']},409)
        self.assertEqual(0,len(self.request('GET',f"accountant/{row['id']}")['links']))

    def test_concurrent_update_has_one_winner_and_no_duplicate_accountant(self):
        row=self.accountant()
        def update(name):
            try:
                return self.core.save_registration(self.a['id'],'accountant',row|{'name':name},'synthetic',row['id'])['version']
            except Exception as exc:
                return getattr(exc,'status',str(exc))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(update,['A sintético','B sintético']))
        self.assertEqual([2,409],sorted(results))
        self.request('POST','accountant',row,409)
        self.assertEqual(1,len(self.request('GET','accountant')))

    def test_migration_failure_rolls_back_and_upgrade_has_backup(self):
        self.party()
        with self.core.db.read() as conn:
            conn.execute('DROP TABLE shared_registration_links')
            conn.execute('DROP TABLE shared_registrations')
            before=list(conn.iterdump())
            with patch('app.shared_registrations.register_local',side_effect=RuntimeError('synthetic failure')):
                with self.assertRaises(RuntimeError):migrate(conn)
            self.assertEqual(before,list(conn.iterdump()))
        reopened=Database(self.tmp.name)
        self.assertIsNotNone(reopened.upgrade_backup)
        with reopened.read() as conn:
            self.assertEqual(1,conn.execute('SELECT count(*) FROM shared_registrations').fetchone()[0])
        self.assertIsNone(Database(self.tmp.name).upgrade_backup)


    def test_global_consultation_without_links_and_use_without_source_access(self):
        legacy=self.party(email='private-source@example.invalid',roles=['carrier'])
        row=self.request('GET','third-party')[0]
        cid=self.a['id'];bid=self.b['id']
        reader,_=self.limited('global-reader-b',[bid],[(bid,'fiscal.shared_parties','read')],activate_cid=bid)
        rows=self.request('GET','third-party',client=reader,cid=bid)
        self.assertEqual([row['id']],[r['id'] for r in rows])
        self.assertEqual([],rows[0]['links'])
        self.assertNotIn('private-source',json.dumps(rows))
        self.assertNotIn('carrier',json.dumps(rows))
        self.assertEqual(403,reader.get(self.scope('/masters/participant',cid)).status_code)
        self.assertEqual(403,reader.get(self.scope('/masters/participant',bid)).status_code)
        self.request('POST',f"third-party/{row['id']}/use",{'version':row['version']},403,reader,bid)
        operator,_=self.limited('global-user-b',[bid],[(bid,'fiscal.shared_parties',a) for a in ('read','edit','create','delete')]+[(bid,'fiscal.masters',a) for a in ('read','create')],activate_cid=bid)
        before=self.core.third_party(cid,legacy['id'])
        result=self.request('POST',f"third-party/{row['id']}/use",{'version':row['version'],'company_id':cid},client=operator,cid=bid)
        # The /use route binds to its URL company, not a caller-supplied target.
        self.assertEqual([bid],[link['company_id'] for link in result['links']])
        second=self.request('POST',f"third-party/{row['id']}/use",{'version':row['version']},client=operator,cid=bid)
        self.assertEqual(result,second)
        self.assertEqual(1,len(self.core.masters(bid,'participant')))
        self.assertEqual(before,self.core.third_party(cid,legacy['id']))
        self.request('PUT',f"third-party/{row['id']}",row|{'name':'Forbidden global write'},403,operator,bid)
        self.request('DELETE',f"third-party/{row['id']}",{'version':row['version']},403,operator,bid)
        self.request('POST','third-party',{'name':'Forbidden'},403,operator,bid)
        local_only,_=self.limited('local-reader-b',[bid],[(bid,'fiscal.masters','read')],activate_cid=bid)
        self.request('GET','third-party',status=403,client=local_only,cid=bid)

    def test_accountant_visible_before_use_and_global_create_does_not_touch_masters(self):
        before_a=self.core.masters(self.a['id'],'participant')
        before_b=self.core.masters(self.b['id'],'participant')
        row=self.accountant()
        self.assertEqual([],row['links'])
        reader,_=self.limited('accountant-reader-b',[self.b['id']],[(self.b['id'],'accounting.accountants','read')],activate_cid=self.b['id'])
        self.assertEqual(row,self.request('GET',f"accountant/{row['id']}",client=reader,cid=self.b['id']))
        self.assertEqual(before_a,self.core.masters(self.a['id'],'participant'))
        self.assertEqual(before_b,self.core.masters(self.b['id'],'participant'))
        self.assertEqual(0,len(self.request('GET',f"accountant/{row['id']}")['links']))

    def test_global_reads_and_maintenance_leave_business_data_and_permissions_unchanged(self):
        legacy=self.party(email='private@example.invalid')
        self.core.create_document(self.a['id'],self.document()|{'participant_id':legacy['id'],'partner_tax_id':legacy['tax_id']},'synthetic')
        self.core.save_master(self.a['id'],'product',{'code':'LOCAL','name':'Produto local','data':{}},'synthetic')
        tables=('companies','accounts','masters','documents','journal_lines','titles','users','user_companies','user_company_access','user_permissions','access_groups','group_users','group_companies','group_permissions')
        def snapshot():
            with self.core.db.read() as conn:
                return {table:[dict(r) for r in conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')] for table in tables}
        before=snapshot()
        row=self.request('POST','third-party',{'name':'Global sem uso local','tax_id':'11144477735','data':{}},201)
        self.assertEqual([],row['links'])
        self.assertEqual(row,self.request('GET',f"third-party/{row['id']}",cid=self.b['id']))
        edited=self.request('PUT',f"third-party/{row['id']}",row|{'name':'Nome global revisado'})
        self.request('DELETE',f"third-party/{row['id']}",{'version':edited['version']})
        self.assertEqual(before,snapshot())

    def test_concurrent_global_creation_and_use_do_not_duplicate(self):
        payload={'name':'Terceiro global concorrente','tax_id':'11144477735','data':{}}
        def create(cid):
            try:
                return self.core.save_registration(cid,'third-party',payload,'synthetic')
            except Exception as exc:
                self.assertEqual(409,getattr(exc,'status',None))
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            created=list(pool.map(create,[self.a['id'],self.b['id']]))
        rows=[row for row in created if row]
        self.assertEqual(1,len(rows))
        row=rows[0]
        def use(_):
            return self.core.link_registration(self.b['id'],'third-party',row['id'],{'company_id':self.b['id'],'version':row['version']},'synthetic')
        with ThreadPoolExecutor(max_workers=2) as pool:
            first,second=list(pool.map(use,[1,2]))
        self.assertEqual(first,second)
        self.assertEqual(1,len(self.core.masters(self.b['id'],'participant')))
        self.assertEqual(1,len(self.request('GET','third-party')))

    def test_validation_and_installation_isolation(self):
        for body in ({'name':'X','tax_id':'invalid','data':{}},{'name':'X','tax_id':'52998224725','data':{'crc':'X','crc_state':'ZZ','category':'accountant'}}):
            self.request('POST','accountant',body,400)
        row=self.accountant()
        self.request('PUT',f"accountant/{row['id']}",row|{'tax_id':'11144477735'},400)
        with tempfile.TemporaryDirectory() as root:
            db=Database(root)
            with db.read() as conn:
                self.assertEqual(0,conn.execute('SELECT count(*) FROM shared_registrations').fetchone()[0])
                self.assertEqual(0,conn.execute('SELECT count(*) FROM shared_registration_links').fetchone()[0])


if __name__=='__main__':unittest.main()
