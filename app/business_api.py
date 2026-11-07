"""Rotas adicionais sob a mesma sessão, CSRF e contexto transacional."""
import csv
import io
import json
from pathlib import Path
from typing import Any
from fastapi import Body, Request
from fastapi.responses import Response
from .core import DomainError, iso_date, select_one, decimal_text


def register_business_routes(app,core,db,actor,check_date,check_period):
    @app.get('/api/companies/{cid}/journals/{item_id}')
    def journal_origin(cid:int,item_id:int):
        with db.read(snapshot=True) as conn:return core._journal(conn,cid,item_id)

    @app.get('/api/lookups/{kind}/{value}')
    def lookup(kind:str,value:str,request:Request,provider:str='auto',refresh:bool=False):
        return app.state.lookups.query(kind,value,provider,refresh)

    @app.get('/api/users')
    def users():return core.users()

    @app.post('/api/users',status_code=201)
    def create_user(request:Request,payload:dict[str,Any]=Body(...)):
        return core.save_user(payload,actor(request))

    @app.put('/api/users/{item_id}')
    def update_user(item_id:int,request:Request,payload:dict[str,Any]=Body(...)):
        return core.save_user(payload,actor(request),item_id)

    @app.get('/api/companies/{cid}/masters/{kind}')
    def masters(cid:int,kind:str):return core.masters(cid,kind)

    @app.post('/api/companies/{cid}/masters/{kind}',status_code=201)
    def create_master(cid:int,kind:str,request:Request,payload:dict[str,Any]=Body(...)):
        return core.save_master(cid,kind,payload,actor(request))

    @app.put('/api/companies/{cid}/masters/{kind}/{item_id}')
    def update_master(cid:int,kind:str,item_id:int,request:Request,payload:dict[str,Any]=Body(...)):
        return core.save_master(cid,kind,payload,actor(request),item_id)

    @app.get('/api/companies/{cid}/documents/{item_id}/trace')
    def trace(cid:int,item_id:int):return core.trace_document(cid,item_id)

    @app.post('/api/companies/{cid}/documents/{item_id}/reverse')
    def reverse_document(cid:int,item_id:int,request:Request,payload:dict[str,Any]=Body(...)):
        check_date(request,payload.get('date'))
        with db.read() as conn:check_period(request,select_one(conn,'documents',cid,item_id)['period'])
        return core.reverse_document(cid,item_id,payload,actor(request))

    @app.post('/api/companies/{cid}/settlements/{item_id}/reverse')
    def reverse_settlement(cid:int,item_id:int,request:Request,payload:dict[str,Any]=Body(...)):
        check_date(request,payload.get('date'))
        return core.reverse_settlement(cid,item_id,payload,actor(request))

    @app.post('/api/companies/{cid}/opening-balances',status_code=201)
    def opening(cid:int,request:Request,payload:dict[str,Any]=Body(...)):
        check_date(request,payload.get('date'))
        return core.create_opening(cid,payload,actor(request))

    @app.get('/api/companies/{cid}/renegotiations')
    def agreements(cid:int):return core.renegotiations(cid)

    @app.post('/api/companies/{cid}/renegotiations/{item_id}/reverse')
    def reverse_agreement(cid:int,item_id:int,request:Request,payload:dict[str,Any]=Body(...)):
        check_date(request,payload.get('date'))
        return core.reverse_renegotiation(cid,item_id,payload,actor(request))

    @app.post('/api/companies/{cid}/titles/renegotiate')
    def renegotiate(cid:int,request:Request,payload:dict[str,Any]=Body(...)):
        check_date(request,payload.get('date'))
        return core.renegotiate(cid,payload,actor(request))

    @app.post('/api/companies/{cid}/banks/{item_id}/allocate')
    def allocate(cid:int,item_id:int,request:Request,payload:dict[str,Any]=Body(...)):
        if payload.get('settle'):
            with db.read() as conn:check_date(request,select_one(conn,'bank_transactions',cid,item_id)['date'])
        return core.allocate_bank(cid,item_id,payload,actor(request))

    @app.post('/api/companies/{cid}/allocations/{item_id}/reverse')
    def reverse_allocation(cid:int,item_id:int,request:Request,payload:dict[str,Any]=Body(...)):
        return core.reverse_allocation(cid,item_id,payload,actor(request))

    @app.get('/api/companies/{cid}/partner-reconciliation')
    def partner_reconciliation(cid:int):return core.partner_reconciliation(cid)

    @app.get('/api/companies/{cid}/business-reports/{kind}')
    def report(cid:int,kind:str,start:str,end:str,account_id:int|None=None,cost_center_id:int|None=None,query:str='',status:str='',direction:str='',format:str='json'):
        result=core.business_report(cid,kind,start,end,account_id,cost_center_id,query,status,direction)
        if format=='json':return result
        if format!='csv':raise DomainError('Formato inválido.')
        output=io.StringIO();keys=list(dict.fromkeys(k for r in result['rows'] for k in r))
        writer=csv.writer(output,delimiter=';',lineterminator='\r\n');writer.writerow(keys)
        for r in result['rows']:
            row=[]
            for k in keys:
                value=r.get(k,'')
                if k.endswith('_cents'):value=decimal_text(value)
                if isinstance(value,list):value=','.join(str(x) for x in value)
                if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@','\t')) and not k.endswith('_cents'):value="'"+value
                row.append(value)
            writer.writerow(row)
        return Response(('\ufeff'+output.getvalue()).encode(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{kind}-{start}-{end}.csv"'})

    @app.get('/api/companies/{cid}/assessments')
    def assessments(cid:int,period:str):return core.assessments(cid,period)

    @app.post('/api/companies/{cid}/assessments')
    def assess(cid:int,request:Request,payload:dict[str,Any]=Body(...)):
        check_period(request,payload.get('period'));return core.assess_tax(cid,payload,actor(request))

    @app.get('/api/companies/{cid}/tax-adjustments')
    def adjustments(cid:int,period:str):return core.tax_adjustments(cid,period)

    @app.post('/api/companies/{cid}/tax-adjustments/{item_id}/reverse')
    def reverse_adjustment(cid:int,item_id:int,request:Request,payload:dict[str,Any]=Body(...)):
        check_period(request,payload.get('period'))
        return core.reverse_tax_adjustment(cid,item_id,payload,actor(request))

    @app.post('/api/companies/{cid}/tax-adjustments')
    def adjust(cid:int,request:Request,payload:dict[str,Any]=Body(...)):
        check_period(request,payload.get('period'));return core.save_tax_adjustment(cid,payload,actor(request))

    @app.post('/api/companies/{cid}/prosoft/preview')
    def export_preview(cid:int,request:Request,payload:dict[str,Any]=Body(...)):
        check_period(request,payload.get('period'));return core.export_prosoft(cid,payload,actor(request))

    @app.post('/api/companies/{cid}/prosoft/confirm')
    def export_confirm(cid:int,request:Request,payload:dict[str,Any]=Body(...)):
        check_period(request,payload.get('period'));return core.export_prosoft(cid,payload,actor(request),True)

    @app.get('/api/companies/{cid}/exports/{item_id}/download')
    def export_download(cid:int,item_id:int):
        with db.read() as conn:r=select_one(conn,'export_batches',cid,item_id)
        return Response(r['content'],media_type='application/octet-stream',headers={'Content-Disposition':f'attachment; filename="{r["filename"]}"'})

    @app.get('/api/companies/{cid}/imports/{item_id}/original')
    def original(cid:int,item_id:int):
        with db.read() as conn:r=select_one(conn,'imports',cid,item_id)
        # Original filenames are displayed by the UI; download header uses a safe stable ID.
        extension=Path(r['filename']).suffix.lower()
        if extension not in {'.xml','.txt','.efd','.sped','.zip','.rar','.7z','.csv','.ofx','.qfx','.qif','.ofc'}:extension='.bin'
        return Response(r['original'],media_type='application/octet-stream',headers={'Content-Disposition':f'attachment; filename="import-{item_id}{extension}"'})
