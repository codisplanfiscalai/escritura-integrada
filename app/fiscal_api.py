"""Fiscal reference, mappings and preparation, under the existing session/RBAC."""
from fastapi import Body, Request
from fastapi.responses import JSONResponse, Response


def register_fiscal_routes(app, core, actor):
    @app.get('/api/companies/{cid}/cfop-source-loads/default')
    def default_load(cid: int):
        return JSONResponse(core.cfop_source_default(cid), headers={'Content-Disposition': 'attachment; filename="cfop-carga-tabcfop-20261109.json"'})

    @app.get('/api/companies/{cid}/cfop-source-loads')
    def source_loads(cid: int): return core.cfop_source_loads(cid)

    @app.post('/api/companies/{cid}/cfop-source-loads/preview')
    def source_preview(cid: int, payload: dict = Body(...)): return core.cfop_source_preview(cid, payload)

    @app.post('/api/companies/{cid}/cfop-source-loads')
    def source_import(cid: int, request: Request, payload: dict = Body(...)):
        return core.import_cfop_source(cid, payload, actor(request))

    @app.get('/api/companies/{cid}/cfop-source-loads/{item_id}/rows')
    def source_rows(cid: int, item_id: int, search: str = '', page: int = 1):
        return core.cfop_source_rows(cid, item_id, search, page)

    @app.get('/api/companies/{cid}/cfop-source-loads/{item_id}/original')
    def source_original(cid: int, item_id: int):
        return JSONResponse(core.cfop_source_original(cid, item_id), headers={'Content-Disposition': 'attachment; filename="cfop-carga-preservada.json"'})

    @app.get('/api/companies/{cid}/cfop-reference')
    def cfops(cid: int, search: str = '', direction: str = '', date: str = '', page: int = 1):
        return core.cfop_reference(cid, search, direction, date, page)

    @app.post('/api/companies/{cid}/cfop-reference/apply')
    def apply(cid: int, request: Request, payload: dict = Body(...)):
        return core.apply_cfop_reference(cid, payload, actor(request))

    @app.get('/api/companies/{cid}/fiscal-import-settings/catalog')
    def import_catalog(cid: int): return core.fiscal_import_catalog(cid)

    @app.get('/api/companies/{cid}/fiscal-import-settings')
    def import_settings(cid: int): return core.fiscal_import_settings(cid)

    @app.put('/api/companies/{cid}/fiscal-import-settings')
    def save_import_settings(cid: int, request: Request, payload: dict = Body(...)):
        return core.save_fiscal_import_settings(cid, payload, actor(request))

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

    @app.get('/api/companies/{cid}/imports/{item_id}/documents/{index}/download')
    def import_xml(cid: int, item_id: int, index: int):
        import json
        from .core import DomainError, digest, select_one
        from .permissions import effect
        from .import_package_cleanup import require_original
        from .auditor_sources import original_xmls
        with core.db.read(snapshot=True) as conn:
            effect(conn, cid, 'fiscal.imports', 'read')
            effect(conn, cid, 'fiscal.imports', 'export')
            batch = select_one(conn, 'imports', cid, item_id)
            require_original(conn, cid, item_id)
            documents = json.loads(batch['parsed_json']).get('documents', [])
            if not 0 <= index < len(documents):
                raise DomainError('Documento não pertence à prévia.', 404, 'not_found')
            source_hash = documents[index].get('source_hash')
            raw, filename = batch['original'], batch['filename']
        for _, content in original_xmls(filename, raw):
            if digest(content) == source_hash:
                return Response(content, media_type='application/xml', headers={
                    'Content-Disposition': f'attachment; filename="documento-{item_id}-{index}.xml"'})
        raise DomainError('XML íntegro correspondente indisponível.', 422, 'source_unavailable')

    @app.get('/api/companies/{cid}/imports/{item_id}/documents/{index}/danfe')
    def import_auxiliary(cid: int, item_id: int, index: int):
        with core.db.read() as conn:
            from .import_package_cleanup import require_original
            require_original(conn, cid, item_id)
        pdf, renderer, number = core.fiscal_import_auxiliary(cid, item_id, index)
        return Response(pdf, media_type='application/pdf', headers={
            'Content-Disposition': 'inline; filename="documento-auxiliar.pdf"',
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'X-Document-Renderer': renderer})

    @app.post('/api/companies/{cid}/imports/{item_id}/reprocess-preview')
    def reprocess_preview(cid: int, item_id: int, payload: dict = Body(...)):
        return core.reprocess_import_preview(cid, item_id, payload)

    @app.post('/api/companies/{cid}/imports/{item_id}/reprocess-confirm')
    def reprocess_confirm(cid: int, item_id: int, request: Request, payload: dict = Body(...)):
        return core.reprocess_import_confirm(cid, item_id, payload, actor(request))
