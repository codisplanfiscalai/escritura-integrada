"""Administração de acessos e exercícios, sob a autorização central da API."""
import json
from typing import Any
from fastapi import Body, Request
from .permissions import catalog


def register_management_routes(app,core,db,actor):
    @app.get('/api/permissions/catalog')
    def permission_catalog():return catalog()

    @app.get('/api/permissions/me')
    def my_permissions(request:Request):
        # A visão detalhada global é exclusiva da administração.
        return {'permissions':request.state.session.get('permissions',{}),
                'company_ids':core.allowed_companies(request.state.session['user']['id'])}

    @app.get('/api/users/{item_id}/effective')
    def effective(item_id:int):return core.effective_access(item_id)

    @app.get('/api/groups')
    def groups():return core.groups()

    @app.post('/api/groups',status_code=201)
    def create_group(request:Request,payload:dict[str,Any]=Body(...)):
        return core.save_group(payload,actor(request))

    @app.put('/api/groups/{item_id}')
    def update_group(item_id:int,request:Request,payload:dict[str,Any]=Body(...)):
        return core.save_group(payload,actor(request),item_id)

    @app.get('/api/access-audit')
    def access_audit(limit:int=200):
        with db.read() as conn:
            return [dict(r)|{'details':json.loads(r['details_json'])} for r in conn.execute(
                "SELECT * FROM audit WHERE entity IN ('user','group') ORDER BY id DESC LIMIT ?",(min(max(limit,1),1000),))]

    @app.get('/api/companies/{cid}/exercises')
    def exercises(cid:int,module:str='fiscal',year:int|None=None):
        return core.exercises(cid,module,year)

    @app.post('/api/companies/{cid}/exercises',status_code=201)
    def create_exercise(cid:int,request:Request,payload:dict[str,Any]=Body(...)):
        return core.create_exercise(cid,payload,actor(request))

    @app.get('/api/companies/{cid}/exercises/history')
    def period_history(cid:int,module:str='fiscal',year:int=2026):
        from .periods import BUSINESS_MODULES
        from .core import DomainError
        if module not in BUSINESS_MODULES or not 1900<=year<=2199:raise DomainError('Módulo ou exercício inválido.')
        with db.read() as conn:
            return [dict(r)|{'details':json.loads(r['details_json'])} for r in conn.execute(
                "SELECT * FROM audit WHERE company_id=? AND entity='period' AND entity_id LIKE ? ORDER BY id DESC LIMIT 500",
                (cid,f'{year:04d}-%:{module}'))]

    @app.get('/api/companies/{cid}/settlements/workspace')
    def settlements_workspace(cid:int):
        return {'titles':core.titles(cid),'agreements':[]}
