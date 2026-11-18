"""Domain reads and explicit recovery, composed with the integration transport."""
import hashlib
import json
import re
import time

from fastapi import Body, Query, Request
from fastapi.responses import JSONResponse

from .core import DomainError, audit
from .integration_resources import RESOURCES, authorize_scope, page, scope_for


def register(application, database, service, bearer):
    @application.get('/integrations/v1/companies/{cid}/resources/{name}')
    def collection(cid: int, name: str, request: Request, after: str | None = None,
                   limit: int = Query(100,ge=1,le=100), period: str | None = None):
        with database.transaction() as conn:
            service.authenticate(conn,bearer(request),cid,scope_for(name,'read'),limited=True)
            result = page(conn,cid,name,after,limit,period)
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @application.get('/integrations/v1/companies/{cid}/resources/{name}/{item_id}')
    def item(cid: int, name: str, item_id: str, request: Request):
        with database.transaction() as conn:
            service.authenticate(conn,bearer(request),cid,scope_for(name,'read'),limited=True)
            result = page(conn,cid,name,item=item_id,limit=1)
        if not result['items']:
            raise DomainError('Registro não encontrado nesta empresa.',404,'not_found')
        return JSONResponse({'version':'1','resource':name,'item':result['items'][0]},headers={'Cache-Control':'no-store'})

    @application.get('/integrations/v1/companies/{cid}/capabilities')
    def capabilities(cid: int, request: Request):
        token = bearer(request)
        if len(token) > 256:
            raise DomainError('Credencial inválida.',401,'integration_unauthorized')
        with database.transaction() as conn:
            credential = conn.execute('SELECT * FROM integration_credentials WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
            if not credential:
                raise DomainError('Credencial inválida.',401,'integration_unauthorized')
            scopes = []
            for scope in json.loads(credential['scopes']):
                try:
                    service.check(conn,credential,cid,scope)
                    scopes.append(scope)
                except DomainError as error:
                    if error.status != 403:
                        raise
            if not scopes:
                raise DomainError('Permissões de integração removidas.',403,'forbidden')
            service.authenticate(conn,token,cid,scopes[0],limited=True)
            resources = []
            for name,spec in RESOURCES.items():
                modes = [mode for mode in ('read','events','webhooks')
                         if (mode == 'read' or spec.events) and scope_for(name,mode) in scopes]
                if modes:
                    resources.append({'resource':name,'modes':modes,'fields':['id',*spec.fields.split()],
                                      'period_filter':bool(spec.period)})
        return JSONResponse({'version':'1','company_id':cid,'resources':resources},headers={'Cache-Control':'no-store'})

    @application.get('/api/companies/{cid}/integrations/webhooks')
    def hooks(cid: int):
        with database.read() as conn:
            return [dict(row) for row in conn.execute('''SELECT w.id,w.credential_id,w.resource,w.url,w.start_seq,w.revoked
                FROM integration_webhooks w JOIN integration_credentials c ON c.id=w.credential_id
                WHERE c.company_id=? ORDER BY w.start_seq DESC,w.id DESC LIMIT 100''',(cid,))]

    @application.post('/api/companies/{cid}/integrations/webhooks/{ident}/redrive')
    def redrive(cid: int, ident: str, request: Request, payload: dict = Body(...)):
        event_seq,key,reason = payload.get('event_sequence'),payload.get('idempotency_key'),payload.get('reason')
        if (type(event_seq) is not int or not 0 < event_seq < 2**63
                or not isinstance(key,str) or not re.fullmatch('[A-Za-z0-9_-]{16,128}',key)
                or not isinstance(reason,str) or not 8 <= len(reason) <= 500):
            raise DomainError('Informe evento, chave idempotente e motivo válidos.',422,'invalid_redrive')
        fingerprint = hashlib.sha256(reason.encode()).hexdigest()
        with database.transaction() as conn:
            row = conn.execute('''SELECT d.*,w.credential_id,w.revoked,w.resource FROM integration_deliveries d
                JOIN integration_webhooks w ON w.id=d.webhook_id JOIN integration_credentials c ON c.id=w.credential_id
                WHERE d.webhook_id=? AND d.event_seq=? AND c.company_id=? AND c.user_id=?''',
                (ident,event_seq,cid,request.state.session['user']['id'])).fetchone()
            if not row or row['revoked']:
                raise DomainError('Entrega não disponível para recuperação.',404,'not_found')
            credential = conn.execute('SELECT * FROM integration_credentials WHERE id=?',(row['credential_id'],)).fetchone()
            scope = scope_for(row['resource'],'webhooks')
            service.check(conn,credential,cid,scope)
            authorize_scope(conn,request.state.session['user']['id'],cid,scope)
            prior = conn.execute('SELECT request_hash FROM integration_redrives WHERE webhook_id=? AND event_seq=? AND key=?',(ident,event_seq,key)).fetchone()
            if prior:
                if prior['request_hash'] != fingerprint:
                    raise DomainError('Chave já usada com outro motivo.',409,'idempotency_conflict')
                return {'event_sequence':event_seq,'duplicate':True,'state':row['state']}
            if row['state'] != 'dead':
                raise DomainError('Somente entregas esgotadas podem ser recuperadas.',409,'redrive_state')
            count = conn.execute('SELECT count(*) FROM integration_redrives WHERE webhook_id=? AND event_seq=?',(ident,event_seq)).fetchone()[0]
            if count >= 3:
                raise DomainError('Limite de três recuperações atingido.',409,'redrive_limit')
            conn.execute('INSERT INTO integration_redrives VALUES(?,?,?,?,?)',(ident,event_seq,key,fingerprint,time.time()))
            conn.execute("UPDATE integration_deliveries SET attempts=0,next_at=0,state='pending',last_result='manual_redrive' WHERE webhook_id=? AND event_seq=?",(ident,event_seq))
            audit(conn,cid,request.state.session['user']['username'],'redrive','webhook',ident,
                  {'event_sequence':event_seq,'reason_hash':fingerprint,'redrive':count+1})
        return {'event_sequence':event_seq,'duplicate':False,'state':'pending'}
