"""Company-scoped integration v1: explicit resources, durable events and credentials."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import secrets
import socket
import sqlite3
import ssl
import time
from urllib.parse import urlsplit

from fastapi import Body, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from .core import DomainError, audit
from .permissions import require

from .integration_resources import SCOPES, authorize_scope, event_type, migrate, scope_for, subscriptions
MAX_ATTEMPTS = 5
SCHEMA = """
CREATE TABLE IF NOT EXISTS integration_credentials (
 id TEXT PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 user_id INTEGER NOT NULL REFERENCES users(id), token_hash TEXT NOT NULL UNIQUE,
 scopes TEXT NOT NULL, expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
 created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS integration_events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
 company_id INTEGER NOT NULL REFERENCES companies(id), resource_id INTEGER NOT NULL,
 version INTEGER NOT NULL, operation TEXT NOT NULL, created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS integration_events_company ON integration_events(company_id,seq);
CREATE TABLE IF NOT EXISTS integration_webhooks (
 id TEXT PRIMARY KEY, credential_id TEXT NOT NULL REFERENCES integration_credentials(id),
 url TEXT NOT NULL, start_seq INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS integration_deliveries (
 webhook_id TEXT NOT NULL REFERENCES integration_webhooks(id),
 event_seq INTEGER NOT NULL REFERENCES integration_events(seq),
 attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL DEFAULT 0,
 state TEXT NOT NULL DEFAULT 'pending', last_result TEXT,
 PRIMARY KEY(webhook_id,event_seq)
);
CREATE TABLE IF NOT EXISTS integration_limits (
 credential_id TEXT PRIMARY KEY REFERENCES integration_credentials(id),
 window INTEGER NOT NULL, requests INTEGER NOT NULL
);
"""


def envelope(row):
    return {'specversion': '1.0', 'id': row['id'], 'sequence': row['seq'],
            'type': event_type(row['resource'] if 'resource' in row.keys() else 'cost-centers'), 'time': row['created'],
            'company_id': row['company_id'],
            'data': {'id': row['resource_id'], 'version': row['version'] or None, 'operation': row['operation']}}


def encode(value):
    return json.dumps(value, separators=(',', ':'), sort_keys=True).encode()


def signature(secret, timestamp, body):
    return hmac.new(secret.encode(), str(timestamp).encode() + b'.' + body, hashlib.sha256).hexdigest()


def verify_signature(secret, timestamp, body, supplied, now=None):
    try:
        return (abs((time.time() if now is None else now) - int(timestamp)) <= 300
                and hmac.compare_digest(signature(secret, timestamp, body), supplied))
    except (ValueError, TypeError):
        return False


def public_addresses(host):
    addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    def routable(address):
        ip = ipaddress.ip_address(address)
        if not ip.is_global or ip.is_multicast or ip.is_reserved:
            return False
        if ip.version == 6 and (ip.ipv4_mapped or ip.sixtofour or ip.teredo
                or ip in ipaddress.ip_network('64:ff9b::/96')
                or ip in ipaddress.ip_network('64:ff9b:1::/48')):
            return False
        return True
    if not addresses or any(not routable(addr) for addr in addresses):
        raise ValueError('non_public_destination')
    return addresses


def validate_destination(url, allowed):
    if not isinstance(url,str) or len(url) > 2048:
        raise ValueError('destination_not_allowed')
    parsed = urlsplit(url)
    if (url not in allowed or parsed.scheme != 'https' or not parsed.hostname
            or parsed.username or parsed.password or parsed.fragment or parsed.query
            or parsed.port not in (None, 443)):
        raise ValueError('destination_not_allowed')
    return parsed


def deliver_https(url, body, headers, allowed):
    """No proxy/redirects. Resolve all addresses, reject mixed DNS, pin TLS connection."""
    parsed = validate_destination(url, allowed)
    address = public_addresses(parsed.hostname)[0]
    conn = http.client.HTTPSConnection(parsed.hostname, 443, timeout=5)
    raw = socket.create_connection((address, 443), timeout=5)
    try:
        conn.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=parsed.hostname)
        conn.request('POST', parsed.path or '/', body=body, headers=headers)
        response = conn.getresponse()
        return response.status  # Never log/read untrusted response bodies or follow Location.
    finally:
        raw.close()
        conn.close()


class Integrations:
    def __init__(self, database):
        self.db = database
        self.master = os.environ.get('ESCRITURA_WEBHOOK_KEY', '')
        try:
            configured = json.loads(os.environ.get('ESCRITURA_WEBHOOK_DESTINATIONS', '{}'))
            self.destinations = {key: frozenset(urls) for key,urls in configured.items()
                                 if key.isdigit() and isinstance(urls,list)
                                 and all(isinstance(url,str) for url in urls)}
        except (ValueError,TypeError,AttributeError):
            self.destinations = {}
        self.origins = set(filter(None, os.environ.get('ESCRITURA_INTEGRATION_ORIGINS', '').split(',')))
        self.sender = deliver_https
        self.sockets = {}
        self.connections = 0
        with database.read() as conn:
            conn.executescript(SCHEMA)
            migrate(conn)
            for operation, sql_operation in [('created', 'INSERT'), ('updated', 'UPDATE')]:
                conn.executescript(f"""CREATE TRIGGER IF NOT EXISTS integration_center_{operation}
                AFTER {sql_operation} ON cost_centers BEGIN
                INSERT INTO integration_events(id,company_id,resource_id,version,operation,created)
                VALUES(lower(hex(randomblob(16))),NEW.company_id,NEW.id,NEW.version,'{operation}',
                       strftime('%Y-%m-%dT%H:%M:%fZ','now')); END;""")

    def check(self, conn, credential, cid, scope):
        if (not credential or credential['revoked'] or credential['expires'] <= time.time()
                or credential['company_id'] != cid or scope not in json.loads(credential['scopes'])):
            raise DomainError('Credencial inválida para este recurso.', 401, 'integration_unauthorized')
        authorize_scope(conn,credential['user_id'],cid,scope)
        # Removing delegation permission also stops previously issued credentials.
        require(conn, credential['user_id'], cid, 'system.integrations', 'create')
        return credential

    def authenticate(self, conn, token, cid, scope, limited=False):
        if not isinstance(token, str) or len(token) > 256:
            raise DomainError('Credencial inválida.', 401, 'integration_unauthorized')
        row = conn.execute('SELECT * FROM integration_credentials WHERE token_hash=?',
                           (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        self.check(conn, row, cid, scope)
        if limited:
            window = int(time.time()) // 60
            conn.execute('''INSERT INTO integration_limits VALUES(?,?,1) ON CONFLICT(credential_id)
                DO UPDATE SET window=excluded.window,requests=CASE WHEN window=excluded.window
                THEN requests+1 ELSE 1 END''', (row['id'], window))
            if conn.execute('SELECT requests FROM integration_limits WHERE credential_id=?', (row['id'],)).fetchone()[0] > 120:
                raise DomainError('Limite de requisições atingido.', 429, 'integration_rate_limit')
        return row

    def issue(self, cid, uid, scopes, expires_in):
        if not isinstance(scopes, list) or not scopes or len(scopes) > len(SCOPES) or any(not isinstance(s,str) or s not in SCOPES for s in scopes):
            raise DomainError('Escopos inválidos.', 422, 'invalid_scope')
        if type(expires_in) is not int or not 60 <= expires_in <= 2592000:
            raise DomainError('Validade deve ser de 60 segundos a 30 dias.', 422, 'invalid_expiry')
        token, ident = secrets.token_urlsafe(32), secrets.token_hex(16)
        with self.db.transaction() as conn:
            require(conn, uid, cid, 'system.integrations', 'create')
            for scope in scopes:
                authorize_scope(conn,uid,cid,scope)
            if conn.execute('SELECT count(*) FROM integration_credentials WHERE company_id=? AND revoked=0 AND expires>?', (cid, time.time())).fetchone()[0] >= 50:
                raise DomainError('Limite de credenciais ativas.', 409, 'credential_limit')
            conn.execute('INSERT INTO integration_credentials VALUES(?,?,?,?,?,?,0,?)',
                         (ident, cid, uid, hashlib.sha256(token.encode()).hexdigest(), json.dumps(sorted(set(scopes))), time.time()+expires_in, time.time()))
            audit(conn, cid, str(uid), 'issue', 'integration', ident, {'scopes': scopes})
        return {'id': ident, 'token': token, 'expires_in': expires_in, 'scopes': scopes}

    def secret(self, ident):
        if len(self.master) < 32:
            raise DomainError('Chave de webhooks não configurada.', 503, 'webhooks_unconfigured')
        return hmac.new(self.master.encode(), ident.encode(), hashlib.sha256).hexdigest()

    def events(self, conn, cid, after, limit=100, resource='cost-centers'):
        names = subscriptions(resource)
        placeholders = ','.join('?' for _ in names)
        return [envelope(r) for r in conn.execute('SELECT * FROM integration_events WHERE company_id=? AND seq>? AND resource IN ('+placeholders+') ORDER BY seq LIMIT ?', (cid, after, *names, limit))]

    def dispatch_one(self):
        """One writer lease, crash recovery, at-least-once delivery; no secret in audit."""
        with self.db.transaction() as conn:
            conn.execute("UPDATE integration_deliveries SET state='dead',last_result='lease_exhausted' WHERE state='inflight' AND attempts>=? AND next_at<=?", (MAX_ATTEMPTS,time.time()))
            # Bounded materialization per endpoint. Existing rows retain retry state.
            for hook in conn.execute('SELECT * FROM integration_webhooks WHERE revoked=0 LIMIT 100'):
                credential = conn.execute('SELECT * FROM integration_credentials WHERE id=?', (hook['credential_id'],)).fetchone()
                try:
                    self.check(conn, credential, credential['company_id'], scope_for(hook['resource'],'webhooks'))
                except DomainError:
                    continue
                pending = conn.execute("SELECT count(*) FROM integration_deliveries WHERE webhook_id=? AND state IN ('pending','inflight')", (hook['id'],)).fetchone()[0]
                if pending >= 100:
                    continue
                last = conn.execute('SELECT coalesce(max(event_seq),?) FROM integration_deliveries WHERE webhook_id=?', (hook['start_seq'], hook['id'])).fetchone()[0]
                conn.execute('''INSERT OR IGNORE INTO integration_deliveries(webhook_id,event_seq)
                    SELECT ?,seq FROM integration_events WHERE company_id=? AND seq>? AND resource=? ORDER BY seq LIMIT ?''', (hook['id'], credential['company_id'], last,hook['resource'],100-pending))
            row = conn.execute('''SELECT d.*,w.url,w.credential_id,w.revoked,w.resource FROM integration_deliveries d
                JOIN integration_webhooks w ON w.id=d.webhook_id
                WHERE d.state IN ('pending','inflight') AND d.next_at<=? AND w.revoked=0
                AND d.attempts<? ORDER BY d.next_at,d.event_seq LIMIT 1''', (time.time(), MAX_ATTEMPTS)).fetchone()
            if not row:
                return False
            credential = conn.execute('SELECT * FROM integration_credentials WHERE id=?', (row['credential_id'],)).fetchone()
            try:
                self.check(conn, credential, credential['company_id'], scope_for(row['resource'],'webhooks'))
            except DomainError:
                conn.execute("UPDATE integration_deliveries SET state='cancelled',last_result='authorization' WHERE webhook_id=? AND event_seq=?", (row['webhook_id'],row['event_seq']))
                return True
            secret = self.secret(row['webhook_id'])
            event = conn.execute('SELECT * FROM integration_events WHERE seq=?', (row['event_seq'],)).fetchone()
            conn.execute("UPDATE integration_deliveries SET state='inflight',attempts=attempts+1,next_at=? WHERE webhook_id=? AND event_seq=?", (time.time()+60,row['webhook_id'],row['event_seq']))
        body = encode(envelope(event))
        stamp = str(int(time.time()))
        try:
            status = self.sender(row['url'], body, {'Content-Type': 'application/json', 'X-Escritura-Event': event['id'], 'X-Escritura-Subscription': row['webhook_id'],
                'X-Escritura-Timestamp': stamp, 'X-Escritura-Signature': 'v1='+signature(secret,stamp,body)}, self.destinations.get(str(credential['company_id']),frozenset()))
            result = 'http_'+str(int(status))
            success = 200 <= status < 300
        except Exception:
            result, success = 'transport_error', False
        attempt = row['attempts']+1
        state = 'delivered' if success else 'dead' if attempt >= MAX_ATTEMPTS else 'pending'
        with self.db.transaction() as conn:
            conn.execute('UPDATE integration_deliveries SET state=?,last_result=?,next_at=? WHERE webhook_id=? AND event_seq=?',
                         (state,result,time.time()+min(3600, 30*2**(attempt-1)),row['webhook_id'],row['event_seq']))
            audit(conn,event['company_id'],'integration-worker',state,'webhook',row['webhook_id'],
                  {'event_id':event['id'],'attempt':attempt,'result':result})
        return True

    async def run(self):
        while True:
            try:
                await asyncio.to_thread(self.dispatch_one)
            except Exception:
                # Database/availability failures do not kill the scheduler. No raw exception/secret logging.
                pass
            await asyncio.sleep(1)


def register(application, database):
    service = Integrations(database)
    application.state.integrations = service

    @application.post('/api/companies/{cid}/integrations/credentials', status_code=201)
    def issue(cid: int, request: Request, payload: dict = Body(...)):
        return service.issue(cid,request.state.session['user']['id'],payload.get('scopes'),payload.get('expires_in',86400))

    @application.get('/api/companies/{cid}/integrations/credentials')
    def credentials(cid: int):
        with database.read() as conn:
            return [dict(r) for r in conn.execute('SELECT id,user_id,scopes,expires,revoked,created FROM integration_credentials WHERE company_id=? ORDER BY created DESC LIMIT 100', (cid,))]

    @application.delete('/api/companies/{cid}/integrations/credentials/{ident}')
    def revoke(cid: int, ident: str, request: Request):
        with database.transaction() as conn:
            conn.execute('UPDATE integration_credentials SET revoked=1 WHERE id=? AND company_id=?', (ident,cid))
            audit(conn,cid,request.state.session['user']['username'],'revoke','integration',ident)
        return {'revoked': True}

    @application.post('/api/companies/{cid}/integrations/webhooks', status_code=201)
    def webhook(cid: int, request: Request, payload: dict = Body(...)):
        ident = secrets.token_hex(16)
        if not isinstance(payload.get('credential_id'),str) or len(payload['credential_id']) != 32:
            raise DomainError('Identificador inválido.',422,'invalid_credential_id')
        secret = service.secret(ident)
        url = payload.get('url','')
        try:
            validate_destination(url,service.destinations.get(str(cid),frozenset()))
            public_addresses(urlsplit(url).hostname)
        except (ValueError,TypeError,OSError):
            raise DomainError('Destino HTTPS não autorizado ou não público.',422,'invalid_destination')
        with database.transaction() as conn:
            credential = conn.execute('SELECT * FROM integration_credentials WHERE id=? AND user_id=?', (payload.get('credential_id'),request.state.session['user']['id'])).fetchone()
            resource = payload.get('resource','cost-centers')
            service.check(conn,credential,cid,scope_for(resource,'webhooks'))
            if conn.execute('SELECT count(*) FROM integration_webhooks WHERE revoked=0').fetchone()[0] >= 100:
                raise DomainError('Limite de destinos.',409,'webhook_limit')
            start = conn.execute('SELECT coalesce(max(seq),0) FROM integration_events').fetchone()[0]
            conn.execute('INSERT INTO integration_webhooks(id,credential_id,url,start_seq,revoked,resource) VALUES(?,?,?,?,0,?)', (ident,credential['id'],url,start,resource))
            audit(conn,cid,str(credential['user_id']),'create','webhook',ident)
        return {'id':ident,'signing_secret':secret,'start_sequence':start}

    @application.delete('/api/companies/{cid}/integrations/webhooks/{ident}')
    def revoke_hook(cid: int, ident: str):
        with database.transaction() as conn:
            conn.execute('''UPDATE integration_webhooks SET revoked=1 WHERE id=? AND credential_id IN
                (SELECT id FROM integration_credentials WHERE company_id=?)''',(ident,cid))
        return {'revoked':True}

    @application.get('/api/companies/{cid}/integrations/deliveries')
    def deliveries(cid: int):
        with database.read() as conn:
            return [dict(r) for r in conn.execute('''SELECT d.* FROM integration_deliveries d
                JOIN integration_webhooks w ON w.id=d.webhook_id JOIN integration_credentials c ON c.id=w.credential_id
                WHERE c.company_id=? ORDER BY event_seq DESC LIMIT 100''',(cid,))]

    def bearer(request):
        value = request.headers.get('authorization','')
        if not value.startswith('Bearer ') or 'token' in request.query_params:
            raise DomainError('Use Authorization: Bearer.',401,'integration_unauthorized')
        return value[7:]

    @application.get('/integrations/v1/companies/{cid}/cost-centers')
    def centers(cid: int, request: Request, after: int = Query(0,ge=0,le=9223372036854775807), limit: int = Query(100,ge=1,le=100)):
        with database.transaction() as conn:
            service.authenticate(conn,bearer(request),cid,'cost-centers:read',limited=True)
            rows = [dict(r) for r in conn.execute('SELECT id,code,name,active,version FROM cost_centers WHERE company_id=? AND id>? ORDER BY id LIMIT ?', (cid,after,limit))]
        return JSONResponse({'version':'1','items':rows,'next_cursor':rows[-1]['id'] if rows else after},headers={'Cache-Control':'no-store'})

    @application.get('/integrations/v1/companies/{cid}/events')
    def events(cid: int, request: Request, resource: str = 'cost-centers', resources: list[str] | None = Query(None), after: int = Query(0,ge=0,le=9223372036854775807), limit: int = Query(100,ge=1,le=100)):
        if resources is not None and 'resource' in request.query_params:
            raise DomainError('Use resource ou resources, não ambos.',422,'invalid_subscription')
        names = subscriptions(resources if resources is not None else resource)
        with database.transaction() as conn:
            credential = service.authenticate(conn,bearer(request),cid,scope_for(names[0],'events'),limited=True)
            for name in names[1:]:
                service.check(conn,credential,cid,scope_for(name,'events'))
            rows = service.events(conn,cid,after,limit,names)
        return JSONResponse({'events':rows,'next_cursor':rows[-1]['sequence'] if rows else after},headers={'Cache-Control':'no-store'})

    def stream_auth(token, cid, resource):
        with database.transaction() as conn:
            credential = service.authenticate(conn,token,cid,scope_for(resource[0],'events'),limited=True)
            for name in resource[1:]:
                service.check(conn,credential,cid,scope_for(name,'events'))
            return credential['id']

    def stream_batch(token, cid, cursor, resource):
        with database.read(snapshot=True) as conn:
            credential = service.authenticate(conn,token,cid,scope_for(resource[0],'events'))
            for name in resource[1:]:
                service.check(conn,credential,cid,scope_for(name,'events'))
            return service.events(conn,cid,cursor,resource=resource)

    @application.websocket('/integrations/v1/stream')
    async def stream(ws: WebSocket):
        # Credential only in first frame; origin and query checked before accepting.
        if ws.query_params or ws.headers.get('origin') not in service.origins:
            await ws.close(code=1008)
            return
        if service.connections >= 100:
            await ws.close(code=1013)
            return
        key = None
        service.connections += 1
        try:
            await ws.accept()
            raw = await asyncio.wait_for(ws.receive_text(),5)
            if len(raw.encode()) > 2048:
                await ws.close(code=1009)
                return
            auth = json.loads(raw)
            if not isinstance(auth,dict):
                raise ValueError()
            cid, cursor, token = auth['company_id'],auth.get('after',0),auth['token']
            if type(cid) is not int or type(cursor) is not int or not 0 <= cursor <= 9223372036854775807:
                raise ValueError()
            if 'resource' in auth and 'resources' in auth:
                raise ValueError()
            resource = subscriptions(auth.get('resources',auth.get('resource','cost-centers')))
            key = await asyncio.to_thread(stream_auth,token,cid,resource)
            if service.sockets.get(key,0) >= 3:
                key = None
                await ws.close(code=1013)
                return
            service.sockets[key] = service.sockets.get(key,0)+1
            while True:
                rows = await asyncio.to_thread(stream_batch,token,cid,cursor,resource)
                if rows:
                    cursor = rows[-1]['sequence']
                await asyncio.wait_for(ws.send_json({'events':rows,'next_cursor':cursor}),5)
                # Bounded pull/ack protocol: no unbounded producer queue, no resubscribe.
                ack_raw = await asyncio.wait_for(ws.receive_text(),15)
                if len(ack_raw.encode()) > 128:
                    raise ValueError()
                ack = json.loads(ack_raw)
                if not isinstance(ack,dict) or type(ack.get('ack')) is not int or ack != {'ack':cursor}:
                    raise ValueError()
                await asyncio.sleep(.25)
        except (DomainError, ValueError, KeyError, TypeError, asyncio.TimeoutError):
            await ws.close(code=1008)
        except sqlite3.Error:
            await ws.close(code=1013)
        except WebSocketDisconnect:
            pass
        finally:
            service.connections -= 1
            if key:
                service.sockets[key] -= 1
                if not service.sockets[key]:
                    del service.sockets[key]

    from .integration_domain_api import register as register_domains
    register_domains(application,database,service,bearer)
