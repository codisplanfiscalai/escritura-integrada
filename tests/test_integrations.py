"""Synthetic integration contract/security tests; no external destinations contacted."""
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import create_app
from app.core import cnpj_digits
from app.integrations import (MAX_ATTEMPTS, public_addresses, validate_destination,
                              signature, verify_signature, deliver_https)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {
            'ESCRITURA_WEBHOOK_KEY':'synthetic-test-secret-'*3,
            'ESCRITURA_WEBHOOK_DESTINATIONS':'{"1":["https://receiver.invalid/events"]}',
            'ESCRITURA_INTEGRATION_ORIGINS':'https://client.invalid'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.app = create_app(self.tmp.name)
        self.service = self.app.state.integrations
        self.db = self.app.state.db
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        session = self.client.post('/api/setup', json={'username':'fixture','password':'Synthetic-password-123!'}).json()
        self.uid = session['user']['id']
        self.client.headers['X-CSRF-Token'] = session['csrf_token']
        self.cids = []
        for n in (1,2):
            base = f'TEST000{n}0001'
            r = self.client.post('/api/companies',json={'code':str(n),'name':'Synthetic company', 'tax_id':base+cnpj_digits(base),'regime':'outros'})
            self.assertEqual(r.status_code,201,r.text)
            self.cids.append(r.json()['id'])
        self.cid = self.cids[0]
        self.activate(self.cid)
        self.credential = self.issue()
        self.headers = {'Authorization':'Bearer '+self.credential['token']}

    def activate(self,cid):
        r = self.client.post('/api/context',json={'company_id':cid,'period':'2026-11','module':'accounting'})
        self.assertEqual(r.status_code,200,r.text)

    def internal(self,tail):
        return f'/api/companies/{self.cid}/integrations/{tail}'

    def external(self,tail,cid=None):
        return f'/integrations/v1/companies/{cid or self.cid}/{tail}'

    def issue(self,scopes=None):
        r = self.client.post(self.internal('credentials'),json={'scopes':scopes or ['cost-centers:read','events:read','webhooks:deliver'],'expires_in':3600})
        self.assertEqual(r.status_code,201,r.text)
        return r.json()

    def center(self,code='A'):
        r = self.client.post(f'/api/companies/{self.cid}/cost-centers',json={'code':code,'name':'Synthetic center','active':True})
        self.assertEqual(r.status_code,201,r.text)
        return r.json()

    def hook(self):
        with patch('app.integrations.public_addresses',return_value=['93.184.216.34']):
            r = self.client.post(self.internal('webhooks'),json={'credential_id':self.credential['id'],'url':'https://receiver.invalid/events'})
        self.assertEqual(r.status_code,201,r.text)
        return r.json()

    def test_api_auth_scope_isolation_pagination_and_revocation(self):
        self.center()
        self.center('B')
        route = self.external('cost-centers')
        self.assertEqual(self.client.get(route).status_code,401)  # session cookie never substitutes bearer
        self.assertEqual(self.client.get(route,headers={'Authorization':'Bearer invalid'}).status_code,401)
        page = self.client.get(route+'?limit=1',headers=self.headers)
        self.assertEqual(page.status_code,200,page.text)
        self.assertEqual(page.headers['cache-control'],'no-store')
        self.assertEqual(len(page.json()['items']),1)
        cursor = page.json()['next_cursor']
        self.assertEqual(len(self.client.get(route+f'?after={cursor}',headers=self.headers).json()['items']),1)
        self.assertEqual(self.client.get(route+'?limit=101',headers=self.headers).status_code,422)
        self.assertEqual(self.client.get(route+'?after='+str(2**64),headers=self.headers).status_code,422)
        self.assertEqual(self.client.get(self.external('cost-centers',self.cids[1]),headers=self.headers).status_code,401)
        restricted = self.issue(['events:read'])
        self.assertEqual(self.client.get(route,headers={'Authorization':'Bearer '+restricted['token']}).status_code,401)
        listed = self.client.get(self.internal('credentials')).text
        self.assertNotIn(self.credential['token'],listed)
        self.assertNotIn('token_hash',listed)
        self.assertEqual(self.client.delete(self.internal('credentials/'+self.credential['id'])).status_code,200)
        self.assertEqual(self.client.get(route,headers=self.headers).status_code,401)

    def test_management_csrf_context_and_scopes(self):
        self.assertEqual(self.client.post(self.internal('credentials'),json={'scopes':['*']}).status_code,422)
        self.assertEqual(self.client.post(self.internal('credentials'),json={'scopes':['events:read']},headers={'X-CSRF-Token':''}).status_code,403)
        self.activate(self.cids[1])
        self.assertEqual(self.client.post(self.internal('credentials'),json={'scopes':['events:read']}).status_code,409)

    def test_live_acl_and_disabled_owner(self):
        # Existing admin is changed into an explicitly delegated operator; no global integration rights.
        with self.db.transaction() as conn:
            conn.execute("UPDATE users SET role='operator' WHERE id=?",(self.uid,))
            conn.execute('INSERT INTO user_companies(user_id,company_id) VALUES(?,?) ON CONFLICT DO NOTHING',(self.uid,self.cid))
            for routine,action in [('system.integrations','create'),('accounting.cost_centers','read'),('accounting.cost_centers','export')]:
                conn.execute("INSERT INTO user_permissions(user_id,company_id,routine,action,effect) VALUES(?,?,?,?,'allow')",(self.uid,self.cid,routine,action))
        route = self.external('cost-centers')
        response = self.client.get(route,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        delegated = self.issue(['events:read'])
        self.assertIn('token',delegated)
        with self.db.transaction() as conn:
            conn.execute("UPDATE user_permissions SET effect='deny' WHERE user_id=? AND action='export'",(self.uid,))
        self.assertEqual(self.client.get(route,headers=self.headers).status_code,403)
        with self.db.transaction() as conn:
            conn.execute("UPDATE user_permissions SET effect='allow' WHERE user_id=?",(self.uid,))
            conn.execute('UPDATE users SET active=0 WHERE id=?',(self.uid,))
        self.assertEqual(self.client.get(route,headers=self.headers).status_code,403)

    def test_expiry_rate_and_transactional_outbox(self):
        before = self.client.get(self.external('events'),headers=self.headers).json()['events']
        with self.assertRaises(RuntimeError):
            with self.db.transaction() as conn:
                conn.execute("INSERT INTO cost_centers(company_id,code,name) VALUES(?,'ROLLBACK','Synthetic')",(self.cid,))
                raise RuntimeError('rollback')
        self.assertEqual(self.client.get(self.external('events'),headers=self.headers).json()['events'],before)
        center = self.center()
        r = self.client.put(f'/api/companies/{self.cid}/cost-centers/{center["id"]}',json={**center,'name':'Updated synthetic','active':True})
        self.assertEqual(r.status_code,200,r.text)
        events = self.client.get(self.external('events'),headers=self.headers).json()['events']
        self.assertEqual([e['data']['operation'] for e in events],['created','updated'])
        self.assertEqual(len({e['id'] for e in events}),2)
        self.assertNotIn('name',events[0]['data'])
        with self.db.transaction() as conn:
            conn.execute('UPDATE integration_limits SET requests=120,window=?',(int(time.time())//60,))
        self.assertEqual(self.client.get(self.external('events'),headers=self.headers).status_code,429)
        with self.db.transaction() as conn:
            conn.execute('UPDATE integration_credentials SET expires=0')
        self.assertEqual(self.client.get(self.external('events'),headers=self.headers).status_code,401)

    def test_webhook_delivery_retries_identity_signature_and_audit(self):
        hook = self.hook()
        self.center()
        sent = []
        def sender(url,body,headers,allowed):
            self.assertTrue(verify_signature(hook['signing_secret'],headers['X-Escritura-Timestamp'],body,headers['X-Escritura-Signature'][3:]))
            sent.append(json.loads(body))
            return 503 if len(sent)==1 else 204
        self.service.sender = sender
        self.assertTrue(self.service.dispatch_one())
        with self.db.transaction() as conn:
            delivery = dict(conn.execute('SELECT * FROM integration_deliveries').fetchone())
            self.assertEqual(delivery['state'],'pending')
            self.assertEqual(delivery['attempts'],1)
            self.assertGreater(delivery['next_at'],time.time())
            conn.execute('UPDATE integration_deliveries SET next_at=0')
        self.assertTrue(self.service.dispatch_one())
        self.assertEqual(sent[0],sent[1])
        self.assertFalse(self.service.dispatch_one())
        delivery = self.client.get(self.internal('deliveries')).json()[0]
        self.assertEqual(delivery['state'],'delivered')
        with self.db.read() as conn:
            entries = str([dict(r) for r in conn.execute("SELECT * FROM audit WHERE entity IN ('integration','webhook')")])
        self.assertNotIn(hook['signing_secret'],entries)
        self.assertNotIn(self.credential['token'],entries)
        self.assertNotIn('receiver.invalid',entries)
        # Receiver deduplication key is the stable event id (same body across retries).
        self.assertEqual(len({e['id'] for e in sent}),1)

    def test_worker_restart_dead_letter_revocation_and_crash_lease(self):
        self.hook()
        self.center()
        def fail(*args):
            raise OSError('do not log https://secret@destination/')
        self.service.sender = fail
        for _ in range(MAX_ATTEMPTS):
            self.assertTrue(self.service.dispatch_one())
            with self.db.transaction() as conn:
                conn.execute('UPDATE integration_deliveries SET next_at=0')
        self.assertEqual(self.client.get(self.internal('deliveries')).json()[0]['state'],'dead')
        self.center('B')
        self.service.dispatch_one()
        with self.db.transaction() as conn:
            conn.execute("UPDATE integration_deliveries SET state='inflight',attempts=?,next_at=0 WHERE state='pending'",(MAX_ATTEMPTS,))
        self.service.dispatch_one()
        self.assertTrue(all(x['state']=='dead' for x in self.client.get(self.internal('deliveries')).json()))
        self.client.delete(self.internal('credentials/'+self.credential['id']))
        self.center('C')
        self.assertFalse(self.service.dispatch_one())
        from app.integrations import Integrations
        restarted = Integrations(self.db)
        self.assertFalse(restarted.dispatch_one())

    def test_destination_and_signature_defenses(self):
        allowed = {'https://receiver.invalid/events'}
        for url in ['http://receiver.invalid/events','https://receiver.invalid/other','https://user@receiver.invalid/events','https://receiver.invalid/events?token=x','https://receiver.invalid:8443/events']:
            with self.assertRaises(ValueError): validate_destination(url,allowed)
        for address in ['127.0.0.1','10.0.0.1','169.254.169.254','::1','fc00::1','::ffff:127.0.0.1','224.0.0.1','ff02::1','64:ff9b::7f00:1','2002:7f00:1::']:
            with patch('socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',(address,443))]):
                with self.assertRaises(ValueError): public_addresses('receiver.invalid')
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443)),(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError): public_addresses('receiver.invalid')
        with patch('app.integrations.public_addresses',side_effect=ValueError('private')):
            self.assertEqual(self.client.post(self.internal('webhooks'),json={'credential_id':self.credential['id'],'url':'https://receiver.invalid/events'}).status_code,422)
            with patch('socket.create_connection') as connect:
                with self.assertRaises(ValueError): deliver_https('https://receiver.invalid/events',b'{}',{},allowed)
                connect.assert_not_called()
        body,stamp = b'{"synthetic":true}',int(time.time())
        sig = signature('synthetic',stamp,body)
        self.assertTrue(verify_signature('synthetic',stamp,body,sig))
        self.assertFalse(verify_signature('synthetic',stamp,body+b' ',sig))
        self.assertFalse(verify_signature('synthetic',stamp-301,body,sig))
        self.assertFalse(verify_signature('wrong',stamp,body,sig))

    def connect(self,after=0):
        ws = self.client.websocket_connect('/integrations/v1/stream',headers={'Origin':'https://client.invalid'})
        return ws

    def auth(self,ws,after=0,cid=None):
        ws.send_json({'token':self.credential['token'],'company_id':cid or self.cid,'after':after})

    def test_websocket_reconnect_revocation_and_isolation(self):
        self.center()
        with self.connect() as ws:
            self.auth(ws)
            first = ws.receive_json()
            self.assertEqual(len(first['events']),1)
        self.center('B')
        with self.connect() as ws:
            self.auth(ws,first['next_cursor'])
            resumed = ws.receive_json()
            self.assertEqual(len(resumed['events']),1)
            self.assertNotEqual(resumed['events'][0]['id'],first['events'][0]['id'])
            self.client.delete(self.internal('credentials/'+self.credential['id']))
            ws.send_json({'ack':resumed['next_cursor']})
            with self.assertRaises(WebSocketDisconnect): ws.receive_json()
        self.credential = self.issue()
        with self.connect() as ws:
            self.auth(ws,cid=self.cids[1])
            with self.assertRaises(WebSocketDisconnect): ws.receive_json()

    def test_websocket_origin_limits_bad_ack_and_expiry(self):
        for uri,origin in [('/integrations/v1/stream','https://evil.invalid'),('/integrations/v1/stream?token=no','https://client.invalid')]:
            with self.assertRaises(WebSocketDisconnect):
                with self.client.websocket_connect(uri,headers={'Origin':origin}): pass
        with self.connect() as ws:
            self.auth(ws)
            ws.receive_json()
            ws.send_json({'subscribe':self.cids[1]})
            with self.assertRaises(WebSocketDisconnect): ws.receive_json()
        with ExitStack() as stack:
            for _ in range(3):
                ws = stack.enter_context(self.connect())
                self.auth(ws)
                ws.receive_json()
            with self.connect() as denied:
                self.auth(denied)
                with self.assertRaises(WebSocketDisconnect): denied.receive_json()
        with self.connect() as ws:
            self.auth(ws)
            data = ws.receive_json()
            with self.db.transaction() as conn: conn.execute('UPDATE integration_credentials SET expires=0')
            ws.send_json({'ack':data['next_cursor']})
            with self.assertRaises(WebSocketDisconnect): ws.receive_json()
        self.assertEqual(self.service.connections,0)
        self.assertEqual(self.service.sockets,{})

    def test_credentials_do_not_cross_installations(self):
        with tempfile.TemporaryDirectory() as folder:
            other = create_app(folder)
            with TestClient(other) as client:
                response = client.get(self.external('events'),headers=self.headers)
                self.assertEqual(response.status_code,401)

    def test_reference_receiver_idempotency_and_atomic_rollback(self):
        import sqlite3
        from app.integrations import encode
        from scripts.integration_inbox import initialize, accept
        self.center()
        event = self.client.get(self.external('events'),headers=self.headers).json()['events'][0]
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        initialize(conn)
        conn.execute('CREATE TABLE effects(id TEXT PRIMARY KEY)')
        body,stamp = encode(event),str(int(time.time()))
        sig = 'v1='+signature('synthetic',stamp,body)
        def apply(db,event): db.execute('INSERT INTO effects VALUES(?)',(event['id'],))
        def fail(db,event):
            apply(db,event)
            raise RuntimeError('synthetic business failure')
        with self.assertRaises(RuntimeError): accept(conn,'synthetic',stamp,sig,body,self.cid,fail)
        self.assertEqual(conn.execute('SELECT count(*) FROM effects').fetchone()[0],0)
        self.assertTrue(accept(conn,'synthetic',stamp,sig,body,self.cid,apply))
        self.assertFalse(accept(conn,'synthetic',stamp,sig,body,self.cid,apply))
        self.assertEqual(conn.execute('SELECT count(*) FROM effects').fetchone()[0],1)
        altered = encode({**event,'data':{'id':999}})
        with self.assertRaises(ValueError):
            accept(conn,'synthetic',stamp,'v1='+signature('synthetic',stamp,altered),altered,self.cid,apply)
        with self.assertRaises(ValueError): accept(conn,'synthetic',stamp,sig,body,self.cids[1],apply)

    def test_webhook_revocation_and_restart_resume_pending(self):
        from app.integrations import Integrations
        self.hook()
        self.center()
        self.service.sender = lambda *args: 302
        self.service.dispatch_one()
        restarted = Integrations(self.db)
        sent=[]
        restarted.sender=lambda *args: sent.append(args) or 204
        with self.db.transaction() as conn: conn.execute('UPDATE integration_deliveries SET next_at=0')
        self.assertTrue(restarted.dispatch_one())
        self.assertEqual(len(sent),1)
        self.center('next')
        restarted.sender=lambda *args: 503
        restarted.dispatch_one()
        self.client.delete(self.internal('credentials/'+self.credential['id']))
        with self.db.transaction() as conn: conn.execute('UPDATE integration_deliveries SET next_at=0')
        restarted.sender=lambda *args: self.fail('revoked delivery must not be sent')
        restarted.dispatch_one()
        self.assertEqual(self.client.get(self.internal('deliveries')).json()[0]['state'],'cancelled')

    def test_destination_allowlist_is_company_scoped_and_rechecked(self):
        self.hook()
        self.center()
        self.service.destinations={}
        with patch('socket.create_connection') as dial:
            self.service.dispatch_one()
            dial.assert_not_called()
        self.assertEqual(self.client.get(self.internal('deliveries')).json()[0]['last_result'],'transport_error')
        self.service.destinations={str(self.cid):frozenset({'https://receiver.invalid/events'})}
        self.cid=self.cids[1]
        self.activate(self.cid)
        self.credential=self.issue()
        with patch('app.integrations.public_addresses',return_value=['93.184.216.34']):
            r=self.client.post(self.internal('webhooks'),json={'credential_id':self.credential['id'],'url':'https://receiver.invalid/events'})
        self.assertEqual(r.status_code,422)

    def test_delivery_pins_tls_and_does_not_follow_redirect(self):
        from unittest.mock import MagicMock
        connection,raw,tls = MagicMock(),MagicMock(),MagicMock()
        connection.getresponse.return_value.status=302
        with patch('app.integrations.public_addresses',return_value=['93.184.216.34']), \
             patch('socket.create_connection',return_value=raw) as dial, \
             patch('ssl.create_default_context',return_value=tls), \
             patch('http.client.HTTPSConnection',return_value=connection):
            self.assertEqual(deliver_https('https://receiver.invalid/events',b'{}',{}, {'https://receiver.invalid/events'}),302)
            dial.assert_called_once_with(('93.184.216.34',443),timeout=5)
            tls.wrap_socket.assert_called_once_with(raw,server_hostname='receiver.invalid')
            connection.request.assert_called_once()
            connection.close.assert_called_once()

    def test_websocket_invalid_frame_and_global_limit(self):
        with self.connect() as ws:
            ws.send_json([])
            with self.assertRaises(WebSocketDisconnect) as closed: ws.receive_json()
            self.assertEqual(closed.exception.code,1008)
        with self.connect() as ws:
            ws.send_text('x'*2049)
            with self.assertRaises(WebSocketDisconnect) as closed: ws.receive_json()
            self.assertEqual(closed.exception.code,1009)
        self.service.connections=100
        try:
            with self.assertRaises(WebSocketDisconnect):
                with self.connect(): pass
        finally:
            self.service.connections=0

    def test_lifespan_worker_delivers_without_manual_dispatch(self):
        self.hook()
        self.center()
        delivered=threading.Event()
        self.service.sender=lambda *args: delivered.set() or 204
        with TestClient(self.app):
            self.assertTrue(delivered.wait(5))

    def test_real_uvicorn_websocket_local_synthetic(self):
        # Real sockets must not be silently mocked/skipped; CI runs the same test.
        import uvicorn
        from websockets.sync.client import connect
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(('127.0.0.1',0))
        listener.listen(16)
        server = uvicorn.Server(uvicorn.Config(self.app,log_level='critical',lifespan='off',ws_max_size=2048,ws_max_queue=4))
        thread = threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True)
        thread.start()
        self.addCleanup(lambda: thread.join(5))
        self.addCleanup(lambda: setattr(server,'should_exit',True))
        deadline = time.time()+5
        while not server.started and time.time()<deadline: time.sleep(.02)
        self.assertTrue(server.started)
        self.center()
        with connect(f'ws://127.0.0.1:{listener.getsockname()[1]}/integrations/v1/stream',origin='https://client.invalid') as ws:
            ws.send(json.dumps({'token':self.credential['token'],'company_id':self.cid,'after':0}))
            batch=json.loads(ws.recv(timeout=5))
            self.assertEqual(len(batch['events']),1)
            self.center('BACKPRESSURE')
            with self.assertRaises(TimeoutError): ws.recv(timeout=.2)
            ws.send(json.dumps({'ack':batch['next_cursor']}))
            self.assertEqual(len(json.loads(ws.recv(timeout=5))['events']),1)


if __name__ == '__main__':
    unittest.main()
