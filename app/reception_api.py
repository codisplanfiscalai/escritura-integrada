"""Manual one-page reception; no automatic booking or fiscal event routes."""
import json
from fastapi import Body, Request
from starlette.concurrency import run_in_threadpool
from starlette.formparsers import MultiPartException
from .core import DomainError
from .reception_workspace import ReceptionWorkspace
from .reception_vault import CompanyA1Vault
from fastapi.responses import Response
from .reception_service import ReceptionService


def register(app,core,actor,check_period):
    app.state.reception = ReceptionService(core)

    def workspace():
        return ReceptionWorkspace(core,app.state.reception)

    @app.get('/api/companies/{cid}/reception/{provider}')
    def overview(cid:int,provider:str,request:Request,year:int,environment:str|None=None,query:str='',offset:int=0,direction:str='',competence:str=''):
        return workspace().overview(cid,request.state.session['user']['id'],provider,environment,year,query,offset,direction,competence)

    @app.get('/api/companies/{cid}/reception/{provider}/receipts')
    def receipt_history(cid:int,provider:str,request:Request,environment:str,year:int,offset:int=0):
        return workspace().receipt_history(cid,request.state.session['user']['id'],provider,environment,year,offset)

    @app.get('/api/companies/{cid}/reception/{provider}/report')
    def report(cid:int,provider:str,request:Request,environment:str,year:int,query:str='',direction:str='',competence:str='',view:str='documents'):
        raw=workspace().report(cid,request.state.session['user']['id'],provider,environment,year,query,direction,competence,view)
        return Response(raw,media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="acervo-'+provider+'-'+str(year)+'.csv"'})

    @app.get('/api/companies/{cid}/reception/{provider}/documents/{rid}')
    def versions(cid:int,provider:str,rid:str,request:Request,environment:str,year:int,offset:int=0):
        return workspace().versions(cid,request.state.session['user']['id'],provider,environment,year,rid,offset)

    @app.post('/api/companies/{cid}/reception/{provider}/check')
    def check(cid:int,provider:str,request:Request,payload:dict=Body(...)):
        return workspace().check(cid,request.state.session['user']['id'],provider,payload)

    @app.post('/api/companies/{cid}/reception/{provider}/query')
    def capture(cid:int,provider:str,request:Request,payload:dict=Body(...)):
        check_period(request,payload.get('period'))
        return workspace().capture(cid,request.state.session['user']['id'],actor(request),provider,payload)

    @app.get('/api/companies/{cid}/reception-settings')
    def settings(cid:int,request:Request):
        return workspace().settings(cid,request.state.session['user']['id'])

    @app.put('/api/companies/{cid}/reception-settings')
    def save_settings(cid:int,request:Request,payload:dict=Body(...)):
        return workspace().save_settings(cid,request.state.session['user']['id'],actor(request),payload)

    @app.put('/api/companies/{cid}/reception-credential')
    def update_credential(cid:int,request:Request,payload:dict=Body(...)):
        return CompanyA1Vault(core.db).update(cid,request.state.session['user']['id'],actor(request),payload)

    @app.post('/api/companies/{cid}/reception-credential')
    async def upload(cid:int,request:Request):
        loopback=request.client and request.client.host in {'127.0.0.1','::1'} and request.url.hostname in {'127.0.0.1','::1','localhost'}
        if request.url.scheme!='https' and not loopback:
            raise DomainError('Use HTTPS para configurar o A1.',400,'reception_https_required')
        received=0
        async def limited_receive():
            nonlocal received
            message=await request.receive();received+=len(message.get('body',b''))
            if received>6000000:raise MultiPartException('Upload A1 excede o limite de 5 MB.')
            return message
        bounded=Request(request.scope,receive=limited_receive)
        try:
            async with bounded.form(max_files=1,max_fields=2,max_part_size=6000000) as form:
                if set(form)!={'certificate','password','options'} or len(form.multi_items())!=3:raise ValueError()
                file=form['certificate']
                if not hasattr(file,'read') or not isinstance(form['password'],str) or not isinstance(form['options'],str) or len(form['options'])>4096:raise ValueError()
                raw=await file.read(5000001);options=json.loads(form['options'])
                return await run_in_threadpool(CompanyA1Vault(core.db).save,cid,request.state.session['user']['id'],actor(request),raw,form['password'],options)
        except (ValueError,TypeError,KeyError):raise DomainError('Confira o arquivo A1 e os parâmetros.') from None

    @app.post('/api/companies/{cid}/imports/reception/query')
    def query(cid:int,request:Request,payload:dict=Body(...)):
        check_period(request,payload.get('period'))
        return app.state.reception.query(cid,payload,actor(request),request.state.session['user']['id'])

    @app.get('/api/companies/{cid}/imports/reception/receipts/{key}')
    def receipt(cid:int,key:str,request:Request):
        return app.state.reception.receipt(cid,key,request.state.session['user']['id'])

    @app.get('/api/companies/{cid}/imports/reception/receipts/{key}/download')
    def download(cid:int,key:str,request:Request):
        metadata,raw=app.state.reception.receipt(cid,key,request.state.session['user']['id'],export=True)
        extension='.xml' if metadata['provider']=='nfe_distribution' else '.json'
        return Response(raw,media_type='application/octet-stream',headers={
            'Content-Disposition':f'attachment; filename="recepcao-{key}{extension}"'})

    @app.get('/api/companies/{cid}/imports/reception/receipts/{key}/documents/{nsu}/download')
    def document(cid:int,key:str,nsu:str,request:Request):
        metadata,raw=app.state.reception.document(cid,key,nsu,request.state.session['user']['id'])
        return Response(raw,media_type='application/octet-stream',headers={
            'Content-Disposition':f'attachment; filename="documento-{key}-{metadata["nsu"]}.xml"'})

    @app.post('/api/companies/{cid}/imports/reception/receipts/{key}/preview')
    def preview(cid:int,key:str,request:Request,payload:dict=Body(...)):
        check_period(request,payload.get('period'))
        return app.state.reception.preview(cid,key,payload,actor(request),request.state.session['user']['id'])
