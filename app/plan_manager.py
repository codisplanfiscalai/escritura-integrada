"""Editable global-plan drafts; saving yields an immutable, traceable version.

Operational company accounts continue to use existing services and IDs. Editing
one global definition never silently rewrites another company's journals.
"""
import json
import re
from copy import deepcopy
from uuid import uuid4
from fastapi import Body, Request
from .account_plans import FIELDS, account_values, default_plan
from .account_plan_codec import decode_plan, PlanCodecError
from .core import DomainError, audit, company_row, digest, integer, now, pack, text
from .global_account_plans import admin, global_plan, summary
from .permissions import effect

PREFIX='global-plan-draft:'


def usage(conn, gid):
    if gid is None:return []
    return [dict(r) for r in conn.execute('''SELECT c.id,c.code,c.name,b.mode,b.version AS binding_version,
        (SELECT COUNT(*) FROM journal_lines l WHERE l.company_id=c.id AND (
         EXISTS(SELECT 1 FROM accounts a JOIN global_account_entries e ON e.id=a.shared_entry_id WHERE a.id=l.account_id AND a.company_id=l.company_id AND e.global_plan_id=?)
         OR EXISTS(SELECT 1 FROM global_account_plan_links x WHERE x.company_id=l.company_id AND x.account_id=l.account_id AND x.global_plan_id=?))) AS journal_lines
        FROM company_account_plan_bindings b JOIN companies c ON c.id=b.company_id
        WHERE b.global_plan_id=? ORDER BY c.code,c.id''',(gid,gid,gid))]


def load(conn, iid):
    if not isinstance(iid,str) or not re.fullmatch(r'[a-f0-9]{32}',iid):raise DomainError('Rascunho não encontrado.',404,'not_found')
    r=conn.execute('SELECT value FROM meta WHERE key=?',(PREFIX+iid,)).fetchone()
    if not r:raise DomainError('Rascunho não encontrado.',404,'not_found')
    return json.loads(r['value'])


def verify_version(draft, payload, editable=True):
    if type(payload.get('version')) is not int or payload['version']!=draft['version']:
        raise DomainError('O plano mudou. Atualize a versão antes de salvar.',409,'stale_version')
    if editable and draft.get('published_id'):
        raise DomainError('Este plano já foi salvo na biblioteca. Abra uma nova edição da versão publicada.',409,'published_draft')


def store(conn, draft):
    conn.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(PREFIX+draft['id'],pack(draft)))


def describe(conn,draft,search='',page=1,per_page=100):
    page=integer(page,'Página');per_page=integer(per_page,'Registros por página')
    if page<1 or per_page not in (50,100,250,500,1000,2500,5000):raise DomainError('Paginação inválida.')
    query=text(search,'Pesquisa',False,200).casefold()
    accounts=draft['plan']['accounts']
    filtered=[a for a in accounts if not query or query in (a['access_code']+' '+a['classifier']+' '+a['name']).casefold()]
    classifiers={a['classifier'] for a in accounts}
    missing=set()
    for a in accounts:
        parts=a['classifier'].split('.')
        for n in range(1,len(parts)):
            parent='.'.join(parts[:n])
            if parent not in classifiers:missing.add(parent)
    return {k:v for k,v in draft.items() if k!='plan'}|{'properties':draft['plan']['properties'],'record_count':len(accounts),'accounts':filtered[(page-1)*per_page:page*per_page],'total':len(filtered),'page':page,'per_page':per_page,'missing_parent_classifiers':sorted(missing)[:100],'companies_on_source':usage(conn,draft.get('source_global_id'))}


def validate_plan(plan, require_properties=False):
    try:decode_plan(pack(plan).encode(),'native')
    except PlanCodecError as exc:raise DomainError(str(exc)) from None
    if require_properties:
        p=plan['properties'];mask=p.get('mask')
        if not isinstance(mask,str) or not re.fullmatch(r'#+(?:\.#+)*',mask) or len(mask)>200:
            raise DomainError('Informe uma máscara válida com # e pontos, por exemplo #.#.##.###.')
        groups=p.get('groups',{})
        if not isinstance(groups,dict) or any(str(groups.get(k,'')) not in '123456789' or len(str(groups.get(k,'')))!=1 for k in ('asset','liability','compensation','cost','expense','revenue')):
            raise DomainError('Informe os grupos contábeis de Ativo, Passivo, Compensação, Custo, Despesa e Receita.')
    seen=set()
    for a in plan['accounts']:
        normalized=account_values(a)
        if normalized['access_code'] in seen:raise DomainError('Código de acesso repetido no plano.')
        seen.add(normalized['access_code'])
    if len(plan['accounts'])>50000:raise DomainError('O plano excede 50.000 contas.')


def authorize(conn,cid,actor):
    company_row(conn,cid);admin(conn,actor);effect(conn,cid,'accounting.accounts','read')


def register(app,core,actor):
    root='/api/companies/{cid}/accounting-settings/plan-manager'

    @app.get(root)
    def listing(cid:int,request:Request):
        user=request.state.session['user'];data=core.global_account_plans(cid)
        if user['role']!='admin':return data|{'drafts':[],'can_manage':False}
        with core.db.read() as conn:
            authorize(conn,cid,actor(request));drafts=[]
            for r in conn.execute('SELECT value FROM meta WHERE key LIKE ?',(PREFIX+'%',)):
                d=json.loads(r['value'])
                if not d.get('published_id'):drafts.append({k:v for k,v in d.items() if k!='plan'}|{'record_count':len(d['plan']['accounts'])})
            plans=[p|{'companies':usage(conn,p['id'])} for p in data['plans']]
            return data|{'plans':plans,'drafts':sorted(drafts,key=lambda d:d['updated_at'],reverse=True),'can_manage':True}

    @app.post(root+'/drafts')
    def create(cid:int,request:Request,payload:dict=Body(...)):
        who=actor(request)
        with core.db.transaction() as conn:
            authorize(conn,cid,who)
            source=payload.get('source_global_id')
            if source is not None:
                source=integer(source,'Plano de origem');plan=json.loads(global_plan(conn,source)['plan_json'])
            else:plan={'schema':'escritura-account-plan/v1','properties':deepcopy(default_plan()['properties']),'accounts':[]}
            if 'properties' in payload:plan['properties']=payload['properties']
            validate_plan(plan)
            d={'id':uuid4().hex,'name':text(payload.get('name'),'Nome do plano',True,200),'description':text(payload.get('description',''),'Descrição',False,1000),'version':1,'source_global_id':source,'created_by':who,'created_at':now(),'updated_at':now(),'plan':plan}
            store(conn,d);audit(conn,cid,who,'create','global-plan-draft',d['id'],{'name':d['name'],'source_global_id':source})
            return describe(conn,d)

    @app.get(root+'/drafts/{iid}')
    def detail(cid:int,iid:str,request:Request,search:str='',page:int=1,per_page:int=100):
        with core.db.read() as conn:
            authorize(conn,cid,actor(request));return describe(conn,load(conn,iid),search,page,per_page)

    @app.put(root+'/drafts/{iid}')
    def update(cid:int,iid:str,request:Request,payload:dict=Body(...)):
        who=actor(request)
        with core.db.transaction() as conn:
            authorize(conn,cid,who);d=load(conn,iid);verify_version(d,payload)
            d['name']=text(payload.get('name'),'Nome do plano',True,200);d['description']=text(payload.get('description',''),'Descrição',False,1000)
            d['plan']['properties']=payload.get('properties');validate_plan(d['plan'],True)
            d['version']+=1;d['updated_at']=now();store(conn,d)
            audit(conn,cid,who,'update','global-plan-draft',iid,{'version':d['version'],'name':d['name']})
            return describe(conn,d)

    @app.post(root+'/drafts/{iid}/accounts')
    def save_account(cid:int,iid:str,request:Request,payload:dict=Body(...)):
        who=actor(request)
        with core.db.transaction() as conn:
            authorize(conn,cid,who);d=load(conn,iid);verify_version(d,payload)
            old_code=payload.get('previous_access_code');accounts=d['plan']['accounts'];old=next((a for a in accounts if a['access_code']==old_code),None) if old_code else None
            if old_code and old is None:raise DomainError('Conta do rascunho não encontrada.',404,'not_found')
            if not isinstance(payload.get('account'),dict):raise DomainError('Informe os dados da conta.')
            account=account_values((old or {})|payload['account'])
            if any(a['access_code']==account['access_code'] and a is not old for a in accounts):raise DomainError('Código de acesso já existente neste plano.',409,'duplicate_account')
            if old is not None:accounts[accounts.index(old)]=account
            else:accounts.append(account)
            validate_plan(d['plan']);d['version']+=1;d['updated_at']=now();store(conn,d)
            audit(conn,cid,who,'update' if old else 'create','global-plan-draft-account',iid,{'version':d['version'],'access_code':account['access_code']})
            return describe(conn,d)

    @app.delete(root+'/drafts/{iid}/accounts')
    def remove(cid:int,iid:str,access_code:str,request:Request,version:int):
        who=actor(request)
        with core.db.transaction() as conn:
            authorize(conn,cid,who);d=load(conn,iid);verify_version(d,{'version':version})
            before=len(d['plan']['accounts']);d['plan']['accounts']=[a for a in d['plan']['accounts'] if a['access_code']!=access_code]
            if len(d['plan']['accounts'])==before:raise DomainError('Conta não encontrada.',404,'not_found')
            d['version']+=1;d['updated_at']=now();store(conn,d)
            audit(conn,cid,who,'delete','global-plan-draft-account',iid,{'version':d['version'],'access_code':access_code})
            return describe(conn,d)

    @app.post(root+'/drafts/{iid}/publish')
    def publish(cid:int,iid:str,request:Request,payload:dict=Body(...)):
        who=actor(request)
        with core.db.transaction() as conn:
            authorize(conn,cid,who);d=load(conn,iid);verify_version(d,payload,False)
            if d.get('published_id'):return summary(global_plan(conn,d['published_id']))|{'duplicate':True,'companies_on_previous':usage(conn,d.get('source_global_id'))}
            validate_plan(d['plan'],True)
            if not d['plan']['accounts']:raise DomainError('Inclua pelo menos uma conta antes de salvar o plano na biblioteca.')
            raw=pack(d['plan']).encode();sha=digest(raw);stamp=now();filename='plano-gerenciado-'+iid+'.json'
            batch=conn.execute('''INSERT INTO account_plan_batches(company_id,filename,format,sha256,original,options_json,plan_json,preview_hash,state_hash,status,confirmation_json,created_at,created_by)
                VALUES(?,?,'native',?,?,?, ?,?,?,'reference',?,?,?)''',(cid,filename,sha,raw,pack({'global_manager_draft':iid}),pack(d['plan']),sha,sha,pack({'global_reference':True}),stamp,who)).lastrowid
            gid=conn.execute('''INSERT INTO global_account_plans(name,description,source_company_id,source_batch_id,parent_id,plan_json,filename,format,original,sha256,created_at,created_by)
                VALUES(?,?,?,?,?,?,?,'native',?,?,?,?)''',(d['name'],d['description'],cid,batch,d.get('source_global_id'),pack(d['plan']),filename,raw,sha,stamp,who)).lastrowid
            for raw_account in d['plan']['accounts']:
                a=account_values(raw_account);extras={k:v for k,v in a.items() if k not in {*FIELDS,'prosoft'}}
                conn.execute(f"INSERT INTO global_account_entries(global_plan_id,{','.join(FIELDS)},prosoft_json,extras_json) VALUES({','.join('?' for _ in range(len(FIELDS)+3))})",(gid,*(a[k] for k in FIELDS),pack(a['prosoft']),pack(extras)))
            d['published_id']=gid;d['updated_at']=stamp;store(conn,d)
            previous=usage(conn,d.get('source_global_id'))
            audit(conn,cid,who,'save-global-version','account_plan',gid,{'draft_id':iid,'source_global_id':d.get('source_global_id'),'companies_unchanged':[c['id'] for c in previous],'records':len(d['plan']['accounts'])})
            return summary(global_plan(conn,gid))|{'companies_on_previous':previous,'companies_updated':0}
