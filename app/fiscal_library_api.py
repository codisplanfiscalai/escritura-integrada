"""Company-authorized reads, explicit administrator writes for shared references."""
from fastapi import Body, Request


def register_fiscal_library_routes(app,core,actor):
    root='/api/companies/{cid}'
    @app.get(root+'/global-fiscal-catalogs')
    def catalogs(cid:int,kind:str='cfop',search:str='',page:int=1):
        return core.global_fiscal_catalogs(cid,kind,search,page)

    @app.post(root+'/global-fiscal-catalogs',status_code=201)
    def create_catalog(cid:int,request:Request,payload:dict=Body(...)):
        return core.save_global_fiscal_catalog(cid,payload,actor(request))

    @app.put(root+'/global-fiscal-catalogs/{item_id}')
    def update_catalog(cid:int,item_id:int,request:Request,payload:dict=Body(...)):
        return core.save_global_fiscal_catalog(cid,payload,actor(request),item_id)

    @app.get(root+'/global-fiscal-catalogs/{item_id}/versions')
    def catalog_versions(cid:int,item_id:int):
        return core.fiscal_library_versions(cid,'catalog',item_id)

    @app.get(root+'/fiscal-patterns')
    def patterns(cid:int): return core.fiscal_pattern_library(cid)

    @app.post(root+'/fiscal-patterns',status_code=201)
    def create_pattern(cid:int,request:Request,payload:dict=Body(...)):
        return core.save_fiscal_pattern(cid,payload,actor(request))

    @app.put(root+'/fiscal-patterns/{item_id}')
    def update_pattern(cid:int,item_id:int,request:Request,payload:dict=Body(...)):
        return core.save_fiscal_pattern(cid,payload,actor(request),item_id)

    @app.get(root+'/fiscal-patterns/imports')
    def imports(cid:int): return core.company_fiscal_pattern_imports(cid)

    @app.get(root+'/fiscal-patterns/{item_id}/versions')
    def pattern_versions(cid:int,item_id:int):
        return core.fiscal_library_versions(cid,'pattern',item_id)

    @app.post(root+'/fiscal-patterns/{item_id}/preview')
    def preview(cid:int,item_id:int,payload:dict=Body(...)):
        return core.preview_fiscal_pattern(cid,item_id,payload)

    @app.post(root+'/fiscal-patterns/{item_id}/apply')
    def apply(cid:int,item_id:int,request:Request,payload:dict=Body(...)):
        return core.apply_fiscal_pattern(cid,item_id,payload,actor(request))
