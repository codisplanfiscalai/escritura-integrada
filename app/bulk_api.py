"""HTTP adapter; standard session/CSRF/context middleware remains mandatory."""
from fastapi import Body, Request
from .bulk_operations import BulkOperations


def register_bulk_routes(app, core, actor):
    from .movement_exports import register_movement_export_routes
    register_movement_export_routes(app, core)
    service = BulkOperations(core)

    @app.post('/api/companies/{cid}/bulk-operations/preview')
    def preview(cid: int, request: Request, payload: dict = Body(...)):
        return service.preview(cid, payload, request.state.session['user']['id'], actor(request))

    @app.post('/api/companies/{cid}/bulk-operations/confirm')
    def confirm(cid: int, request: Request, payload: dict = Body(...)):
        return service.confirm(cid, payload, request.state.session['user']['id'], actor(request))
