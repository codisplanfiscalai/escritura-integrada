"""Rotas nativas do Auditor. Compartilham sessão, contexto, autorização e armazenamento."""
import base64
import json
from fastapi import Body, Request, Response
from .core import DomainError, digest, iso_date, pack, select_one


def register_auditor_routes(app,core,actor,year):
    from . import auditor_catalogs as catalogs

    @app.get('/api/companies/{cid}/auditor/available-catalogs')
    def available_catalogs(cid:int,include_drafts:bool=False):
        with core.db.read() as conn:
            rows = [dict(r) for r in conn.execute("SELECT id,name,sha256,source,valid_from,valid_to,state FROM auditor_catalogs WHERE company_id=? AND (state='published' OR ?) ORDER BY id DESC",(cid,include_drafts))]
        if include_drafts:
            for row in rows:
                if row['state'] != 'draft':
                    continue
                detail = catalogs.catalog_detail(core,cid,row['id'])
                row.update(error_count=detail['error_count'],entry_count=detail['entry_count'])
        return rows

    @app.get('/api/companies/{cid}/auditor/jobs/{jid}/progress')
    def progress(cid:int,jid:int,request:Request):
        with core.db.read() as conn:row=select_one(conn,'auditor_jobs',cid,jid)
        year(request,row['year'])
        return {k:row[k] for k in ('id','status','stage','progress','processed_files','total_files','version','error')}

    @app.get('/api/companies/{cid}/auditor/sources')
    def sources(cid:int,request:Request,start:str,end:str):
        start=iso_date(start);end=iso_date(end);year(request,int(start[:4]));year(request,int(end[:4]))
        if start>end:raise DomainError('Período inválido.')
        with core.db.read(snapshot=True) as conn:
            rows=[core._document(conn,cid,r['id']) for r in conn.execute('SELECT id FROM documents WHERE company_id=? AND posting_date BETWEEN ? AND ? ORDER BY posting_date,id',(cid,start,end))]
            closed={r['period'] for r in conn.execute("SELECT period FROM period_locks WHERE company_id=? AND module='fiscal' AND closed=1",(cid,))}
        return [{'id':r['id'],'version':r['version'],'number':r['number'],'key':r.get('key'),'model':r['model'],'posting_date':r['posting_date'],'issue_date':r['issue_date'],'total_cents':r['total_cents'],'status':r['status'],'partner_name':r.get('partner_name'),'closed':r['posting_date'][:7] in closed,'sources':r['sources']} for r in rows]

    @app.get('/api/companies/{cid}/auditor/catalogs/{iid}')
    def catalog(cid:int,iid:int):return catalogs.catalog_detail(core,cid,iid)

    @app.get('/api/companies/{cid}/auditor/catalogs/{iid}/entries')
    def entries(cid:int,iid:int,search:str='',status:str='',page:int=1,per_page:int=50,kind:str='parameters'):
        return catalogs.catalog_entries(core,cid,iid,search,status,page,per_page,kind)

    @app.post('/api/companies/{cid}/auditor/catalogs/reference',status_code=201)
    def reference(cid:int,request:Request,payload:dict=Body(...)):
        return catalogs.revise_catalog(core,cid,payload,actor(request))

    @app.post('/api/companies/{cid}/auditor/catalogs/{iid}/revision',status_code=201)
    def revision(cid:int,iid:int,request:Request,payload:dict=Body(...)):
        return catalogs.revise_catalog(core,cid,payload,actor(request),iid)

    @app.post('/api/companies/{cid}/auditor/catalogs/{iid}/entries',status_code=201)
    def add_entry(cid:int,iid:int,request:Request,payload:dict=Body(...)):
        return catalogs.edit_entry(core,cid,iid,payload,actor(request))

    @app.put('/api/companies/{cid}/auditor/catalogs/{iid}/entries/{index}')
    def update_entry(cid:int,iid:int,index:int,request:Request,payload:dict=Body(...)):
        return catalogs.edit_entry(core,cid,iid,payload,actor(request),index)

    @app.delete('/api/companies/{cid}/auditor/catalogs/{iid}/entries/{index}')
    def delete_entry(cid:int,iid:int,index:int,request:Request,payload:dict=Body(...)):
        return catalogs.edit_entry(core,cid,iid,payload,actor(request),index,True)

    @app.get('/api/companies/{cid}/auditor/catalogs/{iid}/compare/{other}')
    def compare(cid:int,iid:int,other:int):return catalogs.compare_catalogs(core,cid,iid,other)

    @app.get('/api/companies/{cid}/auditor/jobs/{jid}/logs/export')
    def logs(cid:int,jid:int,request:Request):
        job=core.auditor_job(cid,jid);year(request,job['year'])
        raw='\n'.join(pack(r) for r in job['logs']).encode()
        return Response(raw,media_type='application/x-ndjson',headers={'Content-Disposition':f'attachment; filename="auditoria-{jid}-logs.jsonl"'})

    @app.get('/api/companies/{cid}/auditor/jobs/{jid}/documents')
    def documents(cid:int,jid:int,request:Request,search:str='',direction:str='',status:str='',page:int=1,per_page:int=50):
        job=core.auditor_job(cid,jid);year(request,job['year'])
        if not 1<=per_page<=200 or page<1:raise DomainError('Paginação inválida.')
        rows=(job['result'] or {}).get('documents',[])
        if direction:rows=[r for r in rows if r['direction']==direction]
        if status:rows=[r for r in rows if r['status']==status]
        if search:rows=[r for r in rows if search.casefold() in json.dumps(r,ensure_ascii=False).casefold()]
        return {'rows':rows[(page-1)*per_page:page*per_page],'total':len(rows),'page':page,'per_page':per_page}

    @app.get('/api/companies/{cid}/auditor/jobs/{jid}/reports/{rid}')
    def historical_report(cid:int,jid:int,rid:int,request:Request):
        from .file_store import read_file
        job=core.auditor_job(cid,jid);year(request,job['year'])
        with core.db.read() as conn:
            row=select_one(conn,'auditor_reports',cid,rid)
            if row['job_id']!=jid:raise DomainError('Relatório fora da auditoria.',404)
            f=read_file(conn,cid,row['file_id'])
        mime='application/pdf' if row['format']=='pdf' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        return Response(f['content'],media_type=mime,headers={'Content-Disposition':f'attachment; filename="auditoria-{jid}-versao-{rid}.{row["format"]}"','X-Content-SHA256':f['sha256']})

    @app.post('/api/companies/{cid}/auditor/jobs/{jid}/attachments',status_code=201)
    def attach(cid:int,jid:int,request:Request,payload:dict=Body(...)):
        from .core import audit,now,text,integer
        from .file_store import read_file
        from .permissions import effect
        job=core.auditor_job(cid,jid);year(request,job['year'])
        if job['deleted_at'] or job['status'] not in {'completed','failed'} or not job['result']:
            raise DomainError('Conclua ou restaure a auditoria antes de vincular arquivos.',409)
        ref=payload.get('document_ref');fid=integer(payload.get('file_id'),'Arquivo')
        if ref not in {d['document_ref'] for d in job['result']['documents']}:
            raise DomainError('Documento fora da auditoria.',404)
        if fid not in {f['id'] for f in job['snapshot']['files'] if f['name'].lower().endswith('.pdf')}:
            raise DomainError('PDF não pertence à auditoria.',404)
        reason=text(payload.get('reason'),'Justificativa da associação',True,1000)
        with core.db.transaction() as conn:
            effect(conn,cid,'auditor.analyses','edit')
            current=select_one(conn,'auditor_jobs',cid,jid)
            if current['deleted_at']:raise DomainError('Auditoria excluída.',409)
            f=read_file(conn,cid,fid)
            if not f['content'].startswith(b'%PDF'):raise DomainError('Arquivo não é PDF.')
            conn.execute('INSERT OR IGNORE INTO auditor_attachments(company_id,job_id,document_ref,file_id,reason,created_at,created_by) VALUES(?,?,?,?,?,?,?)',(cid,jid,ref,fid,reason,now(),actor(request)))
            audit(conn,cid,actor(request),'associate_pdf','auditor_job',jid,{'file_id':fid,'document_ref':ref,'reason':reason,'sha256':f['sha256']})
        return {'document_ref':ref,'file_id':fid,'sha256':f['sha256']}
