"""Explicit company parameters, separate from correction of existing records."""
from fastapi import Body,Request
from .core import DomainError,audit,now,pack
from .fiscal_series import SETTINGS_KIND,settings
from .permissions import require

def save_settings(conn,cid,payload,uid,actor):
    require(conn,uid,cid,'fiscal.parameters','edit')
    if set(payload)-{'digits','version'}:raise DomainError('Informe somente dígitos e versão do parâmetro de série.')
    digits=payload.get('digits')
    if type(digits) is not int or not 1<=digits<=20:raise DomainError('Dígitos da série: informe inteiro entre 1 e 20. O tamanho é mínimo e não trunca séries existentes.')
    before=settings(conn,cid)
    if type(payload.get('version')) is not int or payload['version']!=before['version']:raise DomainError('Os parâmetros mudaram. Atualize antes de salvar.',409,'stale_version')
    row=conn.execute('SELECT id FROM masters WHERE company_id=? AND kind=? AND code=?',(cid,SETTINGS_KIND,'default')).fetchone()
    if row:conn.execute('UPDATE masters SET data_json=?,version=version+1,updated_at=? WHERE id=? AND company_id=?',(pack({'digits':digits}),now(),row['id'],cid))
    else:conn.execute('INSERT INTO masters(company_id,kind,code,name,data_json,active,created_at,updated_at) VALUES(?,?,?,?,?,1,?,?)',(cid,SETTINGS_KIND,'default','Dígitos da série fiscal',pack({'digits':digits}),now(),now()))
    audit(conn,cid,actor,'configure','fiscal-series',cid,{'before':before,'after':settings(conn,cid),'movements_changed':False})
    return settings(conn,cid)


import json
import secrets
import time
from .bulk_operations import BulkOperations
from .core import digest,ensure_open,period
from .db import request_context
from .fiscal_series import normalize_series,numeric_series,business_key,stored_payload_hash
from .tax_ledger import ensure_unfinalized

class SeriesOperations(BulkOperations):
    def _authorize(self,conn,cid,uid,req):
        if req.get('action')!='normalize_series' or req.get('kind')!='documents':raise DomainError('Prévia não pertence à correção de séries.',409,'preview_type_mismatch')
        super()._authorize(conn,cid,uid,req|{'action':'update'})

    def preview(self,cid,payload,uid,actor):
        if set(payload)-{'period'}:raise DomainError('A prévia de séries abrange somente a empresa ativa, em todos os exercícios.')
        req={'kind':'documents','action':'normalize_series','scope':'company','period':period(payload.get('period')),'ids':[],'changes':{},'include_linked_journals':False,'include_reversal_pairs':False}
        with self.db.transaction() as conn:
            self._authorize(conn,cid,uid,req)
            result,_=self._inspect(conn,cid,req)
            nonce,expires=secrets.token_urlsafe(32),time.time()+900
            conn.execute('INSERT INTO bulk_previews(id,company_id,user_id,token_hash,request_json,preview_hash,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?)',(nonce,cid,uid,(request_context.get() or {}).get('token_hash',''),pack(req),result['preview_hash'],expires,time.time()))
            return result|{'id':nonce,'expires_at':expires}

    def _inspect(self,conn,cid,req,selected_documents=()):
        from .operational_settings import ensure_selection_allowed,get_settings
        cfg=settings(conn,cid)
        rows=[dict(r) for r in conn.execute('SELECT * FROM documents WHERE company_id=? ORDER BY id',(cid,))]
        ensure_selection_allowed(conn,cid,len(rows))
        identities={}
        for row in rows:identities.setdefault(business_key(row),[]).append(row['id'])
        changes,blockers,preserved=[],[],[]
        for row in rows:
            before,after=row['series'],normalize_series(row['series'],cfg['digits'])
            reason=('Série ausente: permanece vazia.' if not before else 'Série não numérica: preservada.' if not numeric_series(before) else 'Já atende ao mínimo de dígitos; sem truncamento.' if before==after else '')
            if json.loads(row['extra_json']).get('book_cancellation') and before!=after:reason='Cancelamento pelo livro: registro imutável preservado.'
            if reason:
                preserved.append({'id':row['id'],'period':row['period'],'series':before,'reasons':[reason]});continue
            if len(identities[business_key(row)])>1:blockers.append({'id':row['id'],'code':'series_identity_conflict','message':'Identidade equivalente entre documentos '+', '.join(map(str,identities[business_key(row)]))+'. Revise sem mesclar registros.'})
            for guard in (lambda:ensure_open(conn,cid,row['period'],'fiscal'),lambda:ensure_unfinalized(conn,cid,row['period'])):
                try:guard()
                except DomainError as exc:blockers.append({'id':row['id'],'code':exc.code,'message':exc.detail})
            changes.append(row)
        result={'kind':'documents','action':'normalize_series','scope':'company','digits':cfg['digits'],'total_count':len(rows),'selected_count':len(changes),
                'rows':[{'id':r['id'],'number':r['number'],'period':r['period'],'before':r['series'],'after':normalize_series(r['series'],cfg['digits'])} for r in changes],
                'preserved_count':len(preserved),'preserved_rows':preserved,'blockers':blockers,'affected_periods':sorted({r['period'] for r in changes}),
                'affected_counts':{'documents':len(changes)},'effective_ids':[r['id'] for r in changes],'linked_journal_ids':[],
                'warnings':['Somente série e hashes de identidade são padronizados. Originais, valores, itens, datas, chaves e vínculos permanecem preservados. Evidências históricas e exportações anteriores não são reescritas.'],
                'can_confirm':bool(changes) and not blockers}
        if not changes:result['blockers'].append({'code':'empty_selection','message':'Nenhuma série numérica precisa de correção.'})
        result['preview_hash']=digest({'request':req,'settings':cfg,'operational_settings':get_settings(conn,cid),'rows':rows,'result':result})
        return result,changes

    def _apply(self,conn,cid,req,rows,actor,reason):
        digits=settings(conn,cid)['digits']
        for row in rows:
            extras=json.loads(row['extra_json']);extras.setdefault('declared_series',row['series'])
            after=row|{'series':normalize_series(row['series'],digits),'extra_json':pack(extras)}
            conn.execute('UPDATE documents SET series=?,business_key=?,payload_hash=?,extra_json=?,version=version+1 WHERE id=? AND company_id=?',(after['series'],business_key(after),stored_payload_hash(after),after['extra_json'],row['id'],cid))
            audit(conn,cid,actor,'normalize-series','document',row['id'],{'before':{'series':row['series'],'business_key':row['business_key'],'payload_hash':row['payload_hash']},'after':{'series':after['series'],'business_key':business_key(after),'payload_hash':stored_payload_hash(after)},'previous_version':row['version'],'reason':reason,'bulk':True,'digits':digits})


def register(app,core,actor):
    service=SeriesOperations(core)
    @app.post('/api/companies/{cid}/fiscal-series/preview')
    def preview(cid:int,request:Request,payload:dict=Body(...)):
        return service.preview(cid,payload,request.state.session['user']['id'],actor(request))
    @app.post('/api/companies/{cid}/fiscal-series/confirm')
    def confirm(cid:int,request:Request,payload:dict=Body(...)):
        return service.confirm(cid,payload,request.state.session['user']['id'],actor(request))
    @app.get('/api/companies/{cid}/fiscal-series/settings')
    def read(cid:int,request:Request):
        with core.db.read() as conn:
            require(conn,request.state.session['user']['id'],cid,'fiscal.parameters','read')
            return settings(conn,cid)
    @app.put('/api/companies/{cid}/fiscal-series/settings')
    def save(cid:int,request:Request,payload:dict=Body(...)):
        with core.db.transaction() as conn:
            return save_settings(conn,cid,payload,request.state.session['user']['id'],actor(request))
