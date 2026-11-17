"""Integration projections and event boundaries exercised with synthetic business data."""
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import test_integrations as legacy
from app.integration_resources import RESOURCES, event_type
from app.integrations import MAX_ATTEMPTS


class DomainIntegrationTests(unittest.TestCase):
    setUp = legacy.IntegrationTests.setUp
    activate = legacy.IntegrationTests.activate
    issue = legacy.IntegrationTests.issue
    internal = legacy.IntegrationTests.internal
    external = legacy.IntegrationTests.external
    center = legacy.IntegrationTests.center

    def token(self,*scopes):
        return {'Authorization':'Bearer '+self.issue(list(scopes))['token']}

    def get(self,name,headers,tail=''):
        return self.client.get(self.external('resources/'+name)+tail,headers=headers)

    def post(self,tail,payload,status=201):
        response=self.client.post(f'/api/companies/{self.cid}/'+tail,json=payload)
        self.assertEqual(response.status_code,status,response.text)
        return response.json()

    def document(self,number='SYNTHETIC'):
        return self.post('documents',{'direction':'incoming','number':number,'series':'1','model':'55',
            'issue_date':'2026-11-06','posting_date':'2026-11-06','partner_name':'Synthetic participant',
            'partner_tax_id':'','key':'','cfop':'1102','total':'100.00','taxes':{},'items':[]})

    def title(self):
        return self.post('titles',{'kind':'payable','description':'Synthetic title','partner_name':'Synthetic participant',
            'document':'SYNTHETIC','issue_date':'2026-11-06','due_date':'2026-11-20','amount':'100.00'})

    def accounts(self):
        return [self.post('accounts',{'access_code':code,'classifier':code,'name':'Synthetic account '+code,
            'nature':nature,'analytical':True,'requires_cost_center':False,'active':True}) for code,nature in [('1','debit'),('2','credit')]]

    def hook(self,resource):
        with patch('app.integrations.public_addresses',return_value=['93.184.216.34']):
            response=self.client.post(self.internal('webhooks'),json={'credential_id':self.credential['id'],
                'resource':resource,'url':'https://receiver.invalid/events'})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def test_every_projection_is_paged_and_has_no_unlisted_fields(self):
        self.document()
        self.title()
        headers=self.token(*(name+':read' if name!='cost-centers' else 'cost-centers:read' for name in RESOURCES))
        with self.db.read() as conn:
            count=conn.execute('SELECT count(*) FROM integration_events').fetchone()[0]
        for name,spec in RESOURCES.items():
            with self.subTest(resource=name):
                response=self.get(name,headers,'?limit=1')
                self.assertEqual(response.status_code,200,response.text)
                result=response.json()
                self.assertLessEqual(len(result['items']),1)
                for row in result['items']:
                    self.assertEqual(set(row),{'id',*spec.fields.split()})
                    self.assertFalse({'source_json','data_json','original','content','error','snapshot_json','token_hash'} & set(row))
                self.assertEqual(self.get(name,headers,'?limit=101').status_code,422)
        with self.db.read() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM integration_events').fetchone()[0],count)
        caps=self.client.get(self.external('capabilities'),headers=headers).json()
        self.assertEqual({row['resource'] for row in caps['resources']},set(RESOURCES))
        self.assertEqual(self.get('users',headers).status_code,404)
        self.assertEqual(self.client.post(self.external('resources/documents'),headers=headers,json={}).status_code,405)

    def test_documents_titles_scopes_and_cross_company_item_are_separate(self):
        document=self.document()
        title=self.title()
        documents=self.token('documents:read','documents:events')
        titles=self.token('titles:read')
        self.assertEqual(self.get('documents',documents).json()['items'][0]['id'],document['id'])
        self.assertEqual(self.get('titles',titles).json()['items'][0]['amount_cents'],10000)
        self.assertEqual(self.get('titles',documents).status_code,401)
        self.assertEqual(self.get('documents',titles).status_code,401)
        self.assertEqual(self.get('documents',documents,'?period=2026-10').json()['items'],[])
        self.assertEqual(self.get('documents',documents,'?period=2026-13').status_code,422)
        self.assertEqual(self.get('documents',documents,'?after=999999999999999999999999').status_code,422)
        self.assertEqual(self.get('documents',documents,'?after=0%20OR%201=1').status_code,422)
        caps=self.client.get(self.external('capabilities'),headers=documents).json()
        self.assertEqual([r['resource'] for r in caps['resources']],['documents'])
        self.assertEqual(self.get('documents',self.headers).status_code,401)
        self.assertEqual(self.client.get(self.external('events'),headers=self.headers).json()['events'],[])
        self.activate(self.cids[1])
        # Known item ID in another company must never be returned to the first company's credential.
        original_cid=self.cid
        self.cid=self.cids[1]
        other=self.document('OTHER')
        self.cid=original_cid
        self.assertEqual(self.get('documents',documents,'/'+str(other['id'])).status_code,404)
        self.assertEqual(self.client.get(self.external('resources/documents',self.cids[1]),headers=documents).status_code,401)
        self.activate(self.cid)
        self.assertEqual(self.get('titles',titles,'/'+str(title['id'])).status_code,200)

    def test_nonadmin_domain_grants_do_not_require_cost_center_or_grant_other_domains(self):
        with self.db.transaction() as conn:
            conn.execute("UPDATE users SET role='operator' WHERE id=?",(self.uid,))
            conn.execute('INSERT OR IGNORE INTO user_companies VALUES(?,?)',(self.uid,self.cid))
            for routine,action in [('system.integrations','create'),('fiscal.documents','read'),('fiscal.documents','export')]:
                conn.execute("INSERT INTO user_permissions VALUES(?,?,?,?,'allow')",(self.uid,self.cid,routine,action))
        headers=self.token('documents:read','documents:events')
        self.assertEqual(self.get('documents',headers).status_code,200)
        rejected=self.client.post(self.internal('credentials'),json={'scopes':['journals:read']})
        self.assertEqual(rejected.status_code,403,rejected.text)
        with self.db.transaction() as conn:
            conn.execute("UPDATE user_permissions SET effect='deny' WHERE routine='fiscal.documents' AND action='export'")
        self.assertEqual(self.get('documents',headers).status_code,403)
        self.assertEqual(self.client.get(self.external('capabilities'),headers=headers).status_code,403)

    def test_integrated_booking_and_replay_preserve_atomic_multidomain_outbox(self):
        accounts=self.accounts()
        document=self.document()
        reviewed=self.post(f'documents/{document["id"]}/review',{'version':document['version'],'reason':'Synthetic review'},200)
        payload={'version':reviewed['version'],'reason':'Synthetic booking','idempotency_key':'synthetic-book',
            'lines':[{'account_id':accounts[0]['id'],'debit':'100.00','credit':'0.00'},
                     {'account_id':accounts[1]['id'],'debit':'0.00','credit':'100.00'}],
            'generate_titles':True,'installments':[{'due_date':'2026-11-20','amount':'100.00'}]}
        before=self.event_count()
        failed=self.client.post(f'/api/companies/{self.cid}/documents/{document["id"]}/book',json={**payload,'installments':[{'due_date':'2026-11-20','amount':'99.00'}]})
        self.assertEqual(failed.status_code,409,failed.text)
        self.assertEqual(self.event_count(),before)
        booked=self.post(f'documents/{document["id"]}/book',payload,200)
        self.assertEqual(len(booked['titles']),1)
        after=self.event_count()
        replay=self.post(f'documents/{document["id"]}/book',payload,200)
        self.assertTrue(replay['duplicate'])
        self.assertEqual(self.event_count(),after)
        headers=self.token('documents:events','journals:events','journal-lines:events','titles:events')
        for resource in ('documents','journals','journal-lines','titles'):
            events=self.client.get(self.external('events')+'?resource='+resource,headers=headers).json()['events']
            self.assertTrue(events,resource)
            self.assertTrue(all(event['type']==event_type(resource) for event in events))
            self.assertTrue(all(event['company_id']==self.cid for event in events))
        no_read=self.get('documents',headers)
        self.assertEqual(no_read.status_code,401)

    def event_count(self):
        with self.db.read() as conn:
            return conn.execute('SELECT count(*) FROM integration_events').fetchone()[0]

    def test_filtered_master_tombstones_and_compound_period_keys(self):
        product=self.post('masters/product',{'code':'SYNTHETIC','name':'Synthetic product','data':{}})
        headers=self.token('products:events','participants:events','products:read','participants:read','accounting-periods:read','accounting-periods:events')
        self.assertEqual(self.get('participants',headers).json()['items'],[])
        with self.db.transaction() as conn:
            conn.execute("UPDATE masters SET kind='participant',version=version+1 WHERE id=?",(product['id'],))
        events=self.client.get(self.external('events')+'?resource=products',headers=headers).json()['events']
        self.assertEqual([r['data']['operation'] for r in events],['created','deleted'])
        other=self.client.get(self.external('events')+'?resource=participants',headers=headers).json()['events']
        self.assertEqual([r['data']['operation'] for r in other],['created'])
        self.assertEqual(self.get('products',headers).json()['items'],[])
        self.post('periods/close',{'module':'accounting','period':'2026-11','reason':'Synthetic closure'},200)
        response=self.get('accounting-periods',headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn('accounting:2026-11',[r['id'] for r in response.json()['items']])
        detail=self.get('accounting-periods',headers,'/accounting:2026-11')
        self.assertEqual(detail.json()['item']['closed'],1)

    def test_subscriptions_select_resource_and_revalidate_acl(self):
        self.credential=self.issue(['documents:webhooks','titles:webhooks','documents:events'])
        self.hook('documents')
        self.hook('titles')
        self.document()
        self.title()
        sent=[]
        self.service.sender=lambda url,body,headers,allowed: sent.append(json.loads(body)) or 204
        for _ in range(5):
            if not self.service.dispatch_one(): break
        self.assertEqual({e['type'] for e in sent},{'documents.changed.v1','titles.changed.v1'})
        self.assertEqual(len(sent),2)
        with self.client.websocket_connect('/integrations/v1/stream',headers={'Origin':'https://client.invalid'}) as ws:
            ws.send_json({'token':self.credential['token'],'company_id':self.cid,'resource':'documents','after':0})
            batch=ws.receive_json()
            self.assertTrue(all(e['type']=='documents.changed.v1' for e in batch['events']))
            cursor=batch['next_cursor']
        self.document('NEXT')
        with self.client.websocket_connect('/integrations/v1/stream',headers={'Origin':'https://client.invalid'}) as ws:
            ws.send_json({'token':self.credential['token'],'company_id':self.cid,'resource':'documents','after':cursor})
            resumed=ws.receive_json()
            self.assertEqual(len(resumed['events']),1)
            self.client.delete(self.internal('credentials/'+self.credential['id']))
            ws.send_json({'ack':resumed['next_cursor']})
            with self.assertRaises(WebSocketDisconnect): ws.receive_json()
        self.service.sender=lambda *args: self.fail('revoked subscriptions must not deliver')
        self.assertFalse(self.service.dispatch_one())

    def test_redrive_keeps_identity_requires_owner_and_is_idempotent(self):
        self.credential=self.issue(['documents:webhooks'])
        hook=self.hook('documents')
        self.document()
        sent=[]
        self.service.sender=lambda url,body,headers,allowed: sent.append(json.loads(body)) or 503
        for _ in range(MAX_ATTEMPTS):
            self.service.dispatch_one()
            with self.db.transaction() as conn: conn.execute('UPDATE integration_deliveries SET next_at=0')
        delivery=self.client.get(self.internal('deliveries')).json()[0]
        self.assertEqual(delivery['state'],'dead')
        path=self.internal('webhooks/'+hook['id']+'/redrive')
        payload={'event_sequence':delivery['event_seq'],'idempotency_key':'synthetic-redrive-1','reason':'Synthetic receiver repaired'}
        self.assertEqual(self.client.post(path,json=payload,headers={'X-CSRF-Token':''}).status_code,403)
        other=self.client.post('/api/users',json={'username':'other-synthetic','password':'Synthetic-other-password-123!',
            'role':'operator','company_ids':[self.cid],'permissions':[
                {'company_id':self.cid,'routine':'system.integrations','action':'create','effect':'allow'},
                {'company_id':self.cid,'routine':'fiscal.documents','action':'read','effect':'allow'},
                {'company_id':self.cid,'routine':'fiscal.documents','action':'export','effect':'allow'}]})
        self.assertEqual(other.status_code,201,other.text)
        with TestClient(self.app) as client:
            session=client.post('/api/login',json={'username':'other-synthetic','password':'Synthetic-other-password-123!'}).json()
            client.headers['X-CSRF-Token']=session['csrf_token']
            response=client.post('/api/context',json={'company_id':self.cid,'period':'2026-11','module':'fiscal'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(client.post(path,json=payload).status_code,404)
        first=self.client.post(path,json=payload)
        self.assertEqual(first.status_code,200,first.text)
        self.assertFalse(first.json()['duplicate'])
        self.assertTrue(self.client.post(path,json=payload).json()['duplicate'])
        self.assertEqual(self.client.post(path,json={**payload,'reason':'Another synthetic reason'}).status_code,409)
        with self.db.read() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM integration_redrives').fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT attempts FROM integration_deliveries').fetchone()[0],0)
        self.service.sender=lambda url,body,headers,allowed: sent.append(json.loads(body)) or 204
        self.service.dispatch_one()
        self.assertTrue(all(e==sent[0] for e in sent))
        self.assertEqual(self.client.get(self.internal('deliveries')).json()[0]['state'],'delivered')
        self.assertEqual(self.client.post(path,json={**payload,'idempotency_key':'synthetic-redrive-2'}).status_code,409)

    def test_all_supported_event_sources_capture_synthetic_commits(self):
        title=self.title()
        accounts=self.accounts()
        self.center()
        self.document()
        self.post('journals',{'date':'2026-11-06','document':'SYNTHETIC','history':'Synthetic journal',
            'idempotency_key':'synthetic-matrix-journal','lines':[
                {'account_id':accounts[0]['id'],'debit':'1.00','credit':'0.00'},
                {'account_id':accounts[1]['id'],'debit':'0.00','credit':'1.00'}]})
        self.post(f'titles/{title["id"]}/settle',{'date':'2026-11-07','amount':'1.00',
            'reason':'Synthetic payment','idempotency_key':'synthetic-matrix-payment','version':title['version']},200)
        with self.db.transaction() as conn:
            def seed(table,**values):
                # Synthetic schema fixtures test triggers, not business validation rules.
                payload={}
                for col in conn.execute('PRAGMA table_info('+table+')'):
                    key=col['name']
                    if key in values:
                        payload[key]=values[key]
                    elif key=='company_id': payload[key]=self.cid
                    elif key=='id' or not col['notnull'] or col['dflt_value'] is not None: continue
                    elif key=='year': payload[key]=2026
                    elif key=='version': payload[key]=1
                    elif key.endswith('_json'): payload[key]='{}'
                    elif key=='period': payload[key]='2026-11'
                    elif col['type']=='INTEGER': payload[key]=0
                    elif col['type']=='BLOB': payload[key]=b'Synthetic fixture'
                    else: payload[key]='Synthetic fixture'
                return conn.execute('INSERT INTO '+table+'('+','.join(payload)+') VALUES('+','.join('?' for _ in payload)+')',tuple(payload.values())).lastrowid
            bank=seed('bank_transactions',amount_cents=10000,date='2026-11-06')
            seed('reconciliations',transaction_id=bank,title_id=title['id'])
            seed('bank_allocations',transaction_id=bank,title_id=title['id'],amount_cents=100)
            seed('renegotiations',date='2026-11-07',principal_cents=10000)
            seed('catalogs',kind='cfop',code='5102',direction='outgoing')
            seed('rules',direction='incoming',status='draft',active=1)
            seed('imports',status='preview')
            assessment=seed('tax_assessments')
            seed('tax_adjustments',amount_cents=100,kind='credit')
            seed('tax_ledgers',assessment_id=assessment)
            seed('auditor_jobs',mode='internal',start='2026-11-01',end='2026-11-30')
            seed('auditor_catalogs')
            for kind in ('participant','product','service','establishment','history','accounting_model'):
                seed('masters',kind=kind)
            for module in ('fiscal','accounting','financial','social'):
                seed('exercises',module=module,year=2027)
                seed('period_locks',module=module,period='2027-01')
            file_id=seed('stored_files')
            for module in ('accounting','financial'):
                seed('module_imports',module=module,file_id=file_id)
        from app.integration_resources import scope_for
        names=[name for name,spec in RESOURCES.items() if spec.events]
        headers=self.token(*(scope_for(name,'events') for name in names))
        for name in names:
            with self.subTest(resource=name):
                response=self.client.get(self.external('events')+'?resource='+name,headers=headers)
                self.assertEqual(response.status_code,200,response.text)
                self.assertTrue(response.json()['events'],name)
                self.assertTrue(all(e['type']==event_type(name) and e['company_id']==self.cid for e in response.json()['events']))

    def test_negative_account_cursor_and_deleted_auditor_job(self):
        self.accounts()
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO accounts(id,company_id,access_code,classifier,name,nature,analytical,requires_cost_center) VALUES(-100,?,'SYNTHETIC-NEG','1','Synthetic negative ID','debit',1,0)",(self.cid,))
            conn.execute("INSERT INTO auditor_jobs(company_id,year,mode,start,end,request_key,request_hash,snapshot_json,created_at,created_by) VALUES(?,2026,'internal','2026-11-01','2026-11-30','synthetic-job','synthetic','{}','2026-11-01','fixture')",(self.cid,))
            job=conn.execute('SELECT id FROM auditor_jobs').fetchone()[0]
        headers=self.token('accounts:read','auditor-jobs:read','auditor-jobs:events')
        first=self.get('accounts',headers,'?limit=1').json()
        self.assertEqual(first['items'][0]['id'],-100)
        self.assertEqual(len(self.get('accounts',headers,'?after=-100').json()['items']),2)
        with self.db.transaction() as conn:
            conn.execute("UPDATE auditor_jobs SET deleted_at='2026-11-17' WHERE id=?",(job,))
        self.assertEqual(self.get('auditor-jobs',headers).json()['items'],[])
        events=self.client.get(self.external('events')+'?resource=auditor-jobs',headers=headers).json()['events']
        self.assertEqual(events[-1]['data']['operation'],'deleted')

    def test_redrive_lifetime_limit_expiry_and_company_boundary(self):
        self.credential=self.issue(['documents:webhooks'])
        hook=self.hook('documents')
        self.document()
        self.service.sender=lambda *args: 503
        self.service.dispatch_one()
        delivery=self.client.get(self.internal('deliveries')).json()[0]
        path=self.internal('webhooks/'+hook['id']+'/redrive')
        for n in range(3):
            with self.db.transaction() as conn:
                conn.execute("UPDATE integration_deliveries SET state='dead',attempts=5")
            response=self.client.post(path,json={'event_sequence':delivery['event_seq'],
                'idempotency_key':'synthetic-redrive-'+str(n),'reason':'Synthetic retry after repair'})
            self.assertEqual(response.status_code,200,response.text)
        with self.db.transaction() as conn: conn.execute("UPDATE integration_deliveries SET state='dead'")
        payload={'event_sequence':delivery['event_seq'],'idempotency_key':'synthetic-redrive-4','reason':'Synthetic retry after repair'}
        self.assertEqual(self.client.post(path,json=payload).status_code,409)
        self.activate(self.cids[1])
        other_path=path.replace('/companies/'+str(self.cid)+'/', '/companies/'+str(self.cids[1])+'/')
        self.assertEqual(self.client.post(other_path,json=payload).status_code,404)
        self.activate(self.cid)
        with self.db.transaction() as conn: conn.execute('UPDATE integration_credentials SET expires=0 WHERE id=?',(self.credential['id'],))
        self.assertEqual(self.client.post(path,json=payload).status_code,401)

    def test_multiplexed_events_and_stream_require_every_selected_scope(self):
        self.document()
        self.title()
        headers=self.token('documents:events','titles:events')
        response=self.client.get(self.external('events')+'?resources=documents&resources=titles',headers=headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual({r['type'] for r in response.json()['events']},{'documents.changed.v1','titles.changed.v1'})
        denied=self.client.get(self.external('events')+'?resources=documents&resources=journals',headers=headers)
        self.assertEqual(denied.status_code,401)
        self.assertNotIn('events',denied.json())
        with self.client.websocket_connect('/integrations/v1/stream',headers={'Origin':'https://client.invalid'}) as ws:
            ws.send_json({'token':headers['Authorization'][7:],'company_id':self.cid,'resources':['documents','titles'],'after':0})
            batch=ws.receive_json()
            self.assertEqual({r['type'] for r in batch['events']},{'documents.changed.v1','titles.changed.v1'})
        with self.client.websocket_connect('/integrations/v1/stream',headers={'Origin':'https://client.invalid'}) as ws:
            ws.send_json({'token':headers['Authorization'][7:],'company_id':self.cid,'resources':['documents','journals'],'after':0})
            with self.assertRaises(WebSocketDisconnect): ws.receive_json()

    def test_migration_preserves_legacy_pending_delivery_and_identity(self):
        import tempfile
        import hashlib
        import time
        from app.db import Database
        from app.integrations import SCHEMA, Integrations
        with tempfile.TemporaryDirectory() as folder:
            database=Database(folder)
            with database.read() as conn:
                conn.executescript(SCHEMA)
                conn.execute("INSERT INTO users(id,username,password_hash,created_at) VALUES(1,'synthetic','not-a-real-password-hash','2026-11-17')")
                conn.execute("INSERT INTO companies(id,code,name,tax_id,regime,created_at,updated_at) VALUES(1,'SYNTHETIC','Synthetic','SYNTHETIC','outros','2026-11-17','2026-11-17')")
                conn.execute('INSERT INTO integration_credentials VALUES(?,?,?,?,?,?,0,?)',
                    ('b'*32,1,1,hashlib.sha256(b'synthetic-legacy-token').hexdigest(),json.dumps(['events:read','webhooks:deliver']),time.time()+3600,time.time()))
                conn.execute("INSERT INTO integration_events VALUES(42,?,1,7,3,'updated','2026-11-17T00:00:00Z')",('a'*32,))
                conn.execute('INSERT INTO integration_webhooks VALUES(?,?,?,?,0)',('c'*32,'b'*32,'https://receiver.invalid/events',0))
                conn.execute('INSERT INTO integration_deliveries(webhook_id,event_seq) VALUES(?,42)',('c'*32,))
            service=Integrations(database)
            service=Integrations(database)  # migration is restart-safe
            with database.read() as conn:
                events=service.events(conn,1,0)
                self.assertEqual(events[0]['id'],'a'*32)
                self.assertEqual(events[0]['sequence'],42)
                self.assertEqual(events[0]['type'],'cost-center.changed.v1')
                self.assertEqual(conn.execute('SELECT count(*) FROM integration_deliveries').fetchone()[0],1)
            sent=[]
            service.sender=lambda url,body,headers,allowed: sent.append(json.loads(body)) or 204
            self.assertTrue(service.dispatch_one())
            self.assertEqual(sent[0]['id'],'a'*32)
            self.assertFalse(service.dispatch_one())

    def test_account_and_audit_events_are_explicitly_unavailable(self):
        for scope in ('accounts:events','audit:webhooks','documents:*','users:read'):
            response=self.client.post(self.internal('credentials'),json={'scopes':[scope]})
            self.assertEqual(response.status_code,422,response.text)
        response=self.client.get(self.external('events')+'?resource=accounts',headers=self.headers)
        self.assertEqual(response.status_code,422)
        with self.client.websocket_connect('/integrations/v1/stream',headers={'Origin':'https://client.invalid'}) as ws:
            ws.send_json({'token':self.credential['token'],'company_id':self.cid,'resource':[]})
            with self.assertRaises(WebSocketDisconnect): ws.receive_json()


if __name__ == '__main__': unittest.main()
