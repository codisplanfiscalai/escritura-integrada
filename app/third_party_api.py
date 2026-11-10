"""Company-scoped routes, protected by the existing session/CSRF/RBAC middleware."""
from fastapi import Body, Request


def register_third_party_routes(app, core, actor):
    @app.get('/api/companies/{cid}/third-parties')
    def parties(cid: int):
        return core.third_parties(cid)

    @app.get('/api/companies/{cid}/third-parties/{master_id}')
    def party(cid: int, master_id: int):
        return core.third_party(cid, master_id)

    @app.get('/api/companies/{cid}/third-parties/{master_id}/history')
    def history(cid: int, master_id: int):
        return core.third_party_history(cid, master_id)

    @app.put('/api/companies/{cid}/third-parties/{master_id}/registrations')
    def registrations(cid: int, master_id: int, request: Request, payload: dict = Body(...)):
        return core.save_third_party_registrations(cid, master_id, payload, actor(request))

    @app.post('/api/companies/{cid}/third-parties/{master_id}/reuse-preview')
    def preview(cid: int, master_id: int, payload: dict = Body(...)):
        return core.third_party_reuse_preview(cid, master_id, payload)

    @app.post('/api/companies/{cid}/third-parties/{master_id}/reuse-confirm')
    def reuse(cid: int, master_id: int, request: Request, payload: dict = Body(...)):
        return core.reuse_third_party(cid, master_id, payload, actor(request))

    @app.post('/api/companies/{cid}/third-parties/{master_id}/identity-correction')
    def replace(cid: int, master_id: int, request: Request, payload: dict = Body(...)):
        return core.replace_third_party_identity(cid, master_id, payload, actor(request))

    @app.get('/api/companies/{cid}/master-movements/{master_id}')
    def movements(cid: int, master_id: int):
        return core.master_movements(cid, master_id)
