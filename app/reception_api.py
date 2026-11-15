"""Manual one-page reception; no automatic booking or fiscal event routes."""
from fastapi import Body, Request
from fastapi.responses import Response
from .reception_service import ReceptionService


def register(app,core,actor,check_period):
    app.state.reception = ReceptionService(core)

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
            'Content-Disposition':f'attachment; filename="adn-{key}-{metadata["nsu"]}.xml"'})

    @app.post('/api/companies/{cid}/imports/reception/receipts/{key}/preview')
    def preview(cid:int,key:str,request:Request,payload:dict=Body(...)):
        check_period(request,payload.get('period'))
        return app.state.reception.preview(cid,key,payload,actor(request),request.state.session['user']['id'])
