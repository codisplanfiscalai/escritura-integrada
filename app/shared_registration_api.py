"""Scoped entry points retain existing session, CSRF and transaction guards."""
from fastapi import Body, Request


def register_routes(app, core, actor):
    @app.get('/api/companies/{cid}/registrations/{kind}')
    def listing(cid:int,kind:str):
        return core.registrations(cid,kind)

    @app.get('/api/companies/{cid}/registrations/{kind}/{rid}')
    def detail(cid:int,kind:str,rid:int):
        return core.registration(cid,kind,rid)

    @app.post('/api/companies/{cid}/registrations/{kind}',status_code=201)
    def create(cid:int,kind:str,request:Request,payload:dict=Body(...)):
        return core.save_registration(cid,kind,payload,actor(request))

    @app.put('/api/companies/{cid}/registrations/{kind}/{rid}')
    def update(cid:int,kind:str,rid:int,request:Request,payload:dict=Body(...)):
        return core.save_registration(cid,kind,payload,actor(request),rid)

    @app.post('/api/companies/{cid}/registrations/{kind}/{rid}/links')
    def link(cid:int,kind:str,rid:int,request:Request,payload:dict=Body(...)):
        return core.link_registration(cid,kind,rid,payload,actor(request))

    @app.post('/api/companies/{cid}/registrations/{kind}/{rid}/use')
    def use(cid:int,kind:str,rid:int,request:Request,payload:dict=Body(...)):
        return core.link_registration(cid,kind,rid,payload | {'company_id':cid},actor(request))

    @app.delete('/api/companies/{cid}/registrations/{kind}/{rid}')
    def deactivate(cid:int,kind:str,rid:int,request:Request,payload:dict=Body(...)):
        return core.deactivate_registration(cid,kind,rid,payload,actor(request))
