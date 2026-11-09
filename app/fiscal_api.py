"""Fiscal reference, mappings and preparation, under the existing session/RBAC."""
from fastapi import Body, Request


def register_fiscal_routes(app, core, actor):
    @app.get('/api/companies/{cid}/cfop-reference')
    def cfops(cid: int, search: str = '', direction: str = '', date: str = '', page: int = 1):
        return core.cfop_reference(cid, search, direction, date, page)

    @app.post('/api/companies/{cid}/cfop-reference/apply')
    def apply(cid: int, request: Request, payload: dict = Body(...)):
        return core.apply_cfop_reference(cid, payload, actor(request))

    @app.get('/api/companies/{cid}/fiscal-import-mappings')
    def mappings(cid: int): return core.import_cfop_mappings(cid)

    @app.post('/api/companies/{cid}/fiscal-import-mappings')
    def create_mapping(cid: int, request: Request, payload: dict = Body(...)):
        return core.save_import_cfop_mapping(cid, payload, actor(request))

    @app.put('/api/companies/{cid}/fiscal-import-mappings/{item_id}')
    def update_mapping(cid: int, item_id: int, request: Request, payload: dict = Body(...)):
        return core.save_import_cfop_mapping(cid, payload, actor(request), item_id)

    @app.post('/api/companies/{cid}/imports/{item_id}/posting-preview')
    def prepare(cid: int, item_id: int, payload: dict = Body(...)):
        return core.fiscal_posting_preview(cid, item_id, payload)
