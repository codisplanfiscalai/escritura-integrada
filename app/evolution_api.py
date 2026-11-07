"""Pontos de integração da evolução modular 0.7."""
import base64
import json
from fastapi import Body, Request
from fastapi.responses import Response
from .core import DomainError, integer, select_one
from .module_imports import LAYOUTS
from .auditor import COVERAGE
from .file_store import read_file, inventory


def register_evolution_routes(app,core,db,actor,check_period):
    def year(request,value):
        value=integer(value if value is not None else int(request.state.session['period'][:4]),'Exercício',1900)
        check_period(request,f'{value:04d}-01');return value

    @app.get('/api/companies/{cid}/report-models')
    def report_models(cid:int,request:Request):
        from .report_models import CATALOG
        from .permissions import readable
        with db.read() as conn:return [m for m in CATALOG if readable(conn,cid,'fiscal.reports' if m['kind'].startswith('fiscal-') else 'accounting.reports')]

    @app.get('/api/companies/{cid}/module-imports/layouts')
    def layouts(cid:int,module:str):return [{'id':k,**v} for k,v in LAYOUTS.items() if v['module']==module]

    @app.get('/api/companies/{cid}/module-imports')
    def imports(cid:int,request:Request,module:str,year_value:int|None=None):return core.module_imports(cid,module,year(request,year_value))

    @app.post('/api/companies/{cid}/module-imports/preview')
    def preview(cid:int,request:Request,payload:dict=Body(...)):
        year(request,payload.get('year'));return core.preview_module_import(cid,payload,actor(request))

    @app.get('/api/companies/{cid}/module-imports/{iid}')
    def detail(cid:int,iid:int,request:Request,module:str):
        result=core.module_import_detail(cid,iid,module);year(request,result['year']);return result

    @app.post('/api/companies/{cid}/module-imports/{iid}/confirm')
    def confirm(cid:int,iid:int,request:Request,payload:dict=Body(...)):
        result=core.module_import_detail(cid,iid,payload.get('module'));year(request,result['year'])
        return core.confirm_module_import(cid,iid,payload,actor(request))

    @app.get('/api/companies/{cid}/module-imports/{iid}/original')
    def original(cid:int,iid:int,request:Request,module:str):
        result=core.module_import_detail(cid,iid,module);year(request,result['year'])
        with db.read() as conn:r=read_file(conn,cid,result['file_id'])
        return Response(r['content'],media_type='application/octet-stream',headers={'Content-Disposition':f'attachment; filename="original-{iid}.csv"'})

    @app.get('/api/companies/{cid}/auditor/coverage')
    def coverage(cid:int):return COVERAGE

    @app.get('/api/companies/{cid}/auditor/jobs')
    def jobs(cid:int,request:Request,year_value:int|None=None):return core.auditor_jobs(cid,year(request,year_value))

    @app.post('/api/companies/{cid}/auditor/jobs',status_code=201)
    def create_job(cid:int,request:Request,payload:dict=Body(...)):
        check_period(request,str(payload.get('start',''))[:7]);check_period(request,str(payload.get('end',''))[:7])
        result=core.create_auditor_job(cid,payload,actor(request));app.state.auditor.submit(cid,result['id']);return result

    @app.get('/api/companies/{cid}/auditor/jobs/{jid}')
    def job(cid:int,jid:int,request:Request):
        r=core.auditor_job(cid,jid);year(request,r['year']);return r

    @app.post('/api/companies/{cid}/auditor/jobs/{jid}/reprocess',status_code=201)
    def reprocess(cid:int,jid:int,request:Request,payload:dict=Body(...)):
        previous=core.auditor_job(cid,jid);year(request,previous['year'])
        if previous['status'] in {'queued','running'}:raise DomainError('Aguarde o processamento atual.',409)
        snap=previous['snapshot'];data=dict(snap['input']);data['idempotency_key']=payload.get('idempotency_key');data['catalog_id']=payload.get('catalog_id',data.get('catalog_id'))
        if data['mode']=='standalone':
            ids={f.get('package_id',f['id']) for f in snap['files']}
            with db.read() as conn:
                data['files']=[{'filename':r['filename'],'content_base64':base64.b64encode(r['content']).decode()} for r in [read_file(conn,cid,i) for i in ids]]
        result=core.create_auditor_job(cid,data,actor(request));app.state.auditor.submit(cid,result['id']);return result

    @app.post('/api/companies/{cid}/auditor/jobs/{jid}/auxiliary')
    def auxiliary(cid:int,jid:int,request:Request,payload:dict=Body(...)):
        from .auxiliary import render_danfe
        from .file_store import store_file
        from .core import now,audit
        job=core.auditor_job(cid,jid);year(request,job['year'])
        if job['status']!='completed':raise DomainError('Aguarde a conclusão da auditoria.',409)
        document=next((d for d in job['result']['documents'] if d['document_ref']==payload.get('document_ref')),None)
        if not document:raise DomainError('Documento não pertence à auditoria.',404)
        # O PDF importado permanece preferencial; gerar é sempre uma ação explícita.
        with db.read() as conn:r=read_file(conn,cid,document['original_file_id'])
        content,renderer=render_danfe(r['content'])
        with db.transaction() as conn:
            old=conn.execute('SELECT * FROM auditor_auxiliary WHERE company_id=? AND job_id=? AND document_ref=?',(cid,jid,document['document_ref'])).fetchone()
            if old:return dict(old)
            fid=store_file(db,conn,cid,job['year'],'auxiliary','DANFE-'+str(document.get('number'))+'.pdf',content,actor(request))
            conn.execute('INSERT INTO auditor_auxiliary(company_id,job_id,document_ref,file_id,renderer,source_sha256,created_at) VALUES(?,?,?,?,?,?,?)',(cid,jid,document['document_ref'],fid,renderer,r['sha256'],now()))
            audit(conn,cid,actor(request),'render','auditor_auxiliary',fid,{'job_id':jid,'renderer':renderer,'source_sha256':r['sha256']})
        return {'file_id':fid,'renderer':renderer}

    @app.post('/api/companies/{cid}/auditor/jobs/{jid}/{action}')
    def action(cid:int,jid:int,action:str,request:Request,payload:dict=Body(...)):
        r=core.auditor_job(cid,jid);year(request,r['year']);return core.auditor_action(cid,jid,action,payload,actor(request))

    @app.put('/api/companies/{cid}/auditor/findings/{fid}/treatment')
    def treatment(cid:int,fid:int,request:Request,payload:dict=Body(...)):
        with db.read() as conn:
            finding=select_one(conn,'auditor_findings',cid,fid);job=select_one(conn,'auditor_jobs',cid,finding['job_id'])
        year(request,job['year']);return core.treat_finding(cid,fid,payload,actor(request))

    @app.get('/api/companies/{cid}/auditor/catalogs')
    def catalogs(cid:int):return core.auditor_catalogs(cid)

    @app.post('/api/companies/{cid}/auditor/catalogs/import-preview')
    def catalog_preview(cid:int,request:Request,payload:dict=Body(...)):
        from .auditor_catalog_import import normalize_xlsx
        from .file_store import store_file
        from .core import now,pack,audit
        encoded=payload.get('content_base64','')
        if not isinstance(encoded,str) or len(encoded)>28_000_000:raise DomainError('Limite de 20 MiB.')
        try:raw=base64.b64decode(encoded,validate=True)
        except ValueError:raise DomainError('Conteúdo base64 inválido.')
        preview=normalize_xlsx(raw)
        with db.transaction() as conn:
            fid=store_file(db,conn,cid,year(request,None),'audit',payload.get('filename','catalogo.xlsx'),raw,actor(request))
            sid=conn.execute('INSERT INTO auditor_catalog_sources(company_id,file_id,preview_json,created_at) VALUES(?,?,?,?)',(cid,fid,pack(preview),now())).lastrowid
            audit(conn,cid,actor(request),'preview','auditor_catalog_source',sid,{'file_id':fid,'rows':preview['rows'],'excluded':preview['excluded']})
        return preview|{'source_id':sid,'file_id':fid}

    @app.get('/api/companies/{cid}/auditor/catalogs/{iid}/original')
    def catalog_original(cid:int,iid:int):
        with db.read() as conn:
            catalog=select_one(conn,'auditor_catalogs',cid,iid)
            if not catalog['source_id']:raise DomainError('Catálogo informado manualmente, sem XLSX de origem.',404)
            source=select_one(conn,'auditor_catalog_sources',cid,catalog['source_id']);r=read_file(conn,cid,source['file_id'])
        return Response(r['content'],media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f'attachment; filename="catalogo-{iid}.xlsx"'})

    @app.post('/api/companies/{cid}/auditor/catalogs',status_code=201)
    def create_catalog(cid:int,request:Request,payload:dict=Body(...)):return core.save_auditor_catalog(cid,payload,actor(request))

    @app.put('/api/companies/{cid}/auditor/catalogs/{iid}')
    def update_catalog(cid:int,iid:int,request:Request,payload:dict=Body(...)):return core.save_auditor_catalog(cid,payload,actor(request),iid)

    @app.post('/api/companies/{cid}/auditor/catalogs/{iid}/publish')
    def publish_catalog(cid:int,iid:int,request:Request,payload:dict=Body(...)):return core.publish_auditor_catalog(cid,iid,payload,actor(request))

    @app.get('/api/companies/{cid}/auditor/jobs/{jid}/files')
    def audit_file(cid:int,jid:int,file_id:int,request:Request):
        job=core.auditor_job(cid,jid);year(request,job['year'])
        if file_id not in {f['id'] for f in job['snapshot']['files']}|{f.get('package_id') for f in job['snapshot']['files']}|{f['file_id'] for f in job['auxiliary']}:raise DomainError('Arquivo não pertence à auditoria.',404)
        with db.read() as conn:r=read_file(conn,cid,file_id)
        ext='pdf' if r['content'].startswith(b'%PDF-') else 'xml' if r['filename'].lower().endswith('.xml') else 'zip'
        return Response(r['content'],media_type='application/octet-stream',headers={'Content-Disposition':f'attachment; filename="original-{file_id}.{ext}"'})

    @app.get('/api/companies/{cid}/auditor/jobs/{jid}/report')
    def report(cid:int,jid:int,request:Request,format:str='pdf'):
        from .auditor_reports import export_audit
        result=core.auditor_job(cid,jid);year(request,result['year'])
        if result['status']!='completed':raise DomainError('Relatório disponível após conclusão.',409)
        content,mime=export_audit(result,format)
        return Response(content,media_type=mime,headers={'Content-Disposition':f'attachment; filename="auditoria-{jid}.{format}"'})

    @app.get('/api/storage/backup')
    def backup():
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from .snapshots import create_snapshot
        with TemporaryDirectory(prefix='escritura-export-') as tmp:
            path=Path(tmp)/'escritura-backup.zip';create_snapshot(db.path,path)
            return Response(path.read_bytes(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="escritura-backup-integral.zip"'})

    @app.get('/api/companies/{cid}/storage')
    def storage(cid:int,request:Request,year_value:int|None=None):return inventory(db,cid,year(request,year_value))
