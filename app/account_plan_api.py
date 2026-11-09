"""Rotas do plano de contas, sob sessão, contexto, CSRF e permissões usuais."""
from typing import Any
from fastapi import Body, Request
from fastapi.responses import Response
from .account_plans import default_plan
from .core import select_one


def register_account_plan_routes(app,core,actor):
    root='/api/companies/{cid}/account-plans'
    @app.get(root+'/default')
    def default(cid:int):
        with core.db.read() as conn:
            from .core import company_row
            company_row(conn,cid)
        return default_plan()
    @app.get(root)
    def batches(cid:int):return core.account_plan_batches(cid)
    @app.post(root+'/preview')
    def preview(cid:int,request:Request,payload:dict[str,Any]=Body(...)):
        return core.preview_account_plan(cid,payload,actor(request))
    @app.post(root+'/{item_id}/confirm')
    def confirm(cid:int,item_id:int,request:Request,payload:dict[str,Any]=Body(...)):
        return core.confirm_account_plan(cid,item_id,payload,actor(request))
    @app.post(root+'/export-preview')
    def export_preview(cid:int,request:Request,payload:dict[str,Any]=Body(...)):
        return core.export_account_plan(cid,payload,actor(request))
    @app.post(root+'/export-confirm')
    def export_confirm(cid:int,request:Request,payload:dict[str,Any]=Body(...)):
        return core.export_account_plan(cid,payload,actor(request),True)
    @app.get(root+'/{item_id}/original')
    def original(cid:int,item_id:int):
        with core.db.read() as conn:r=select_one(conn,'account_plan_batches',cid,item_id)
        extension='.json' if r['format'] in {'native','default'} else '.txt'
        return Response(r['original'],media_type='application/octet-stream',headers={'Content-Disposition':f'attachment; filename="plano-original-{item_id}{extension}"'})
    @app.get(root+'/{item_id}/native')
    def native(cid:int,item_id:int):
        import json
        from .account_plan_codec import encode_plan
        with core.db.read() as conn:r=select_one(conn,'account_plan_batches',cid,item_id)
        raw,_=encode_plan(json.loads(r['plan_json']),'native')
        return Response(raw,media_type='application/json',headers={'Content-Disposition':f'attachment; filename="plano-referencia-{item_id}.json"'})
