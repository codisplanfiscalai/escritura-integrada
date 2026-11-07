"""HTTP API e frontend no mesmo processo — Windows, Linux e contêiner."""
from __future__ import annotations

import hmac
import os
import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import Body, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response

from . import __version__
from .business import BusinessCore as Core
from .core import DomainError, digest, iso_date, period, select_one
from .db import ContextConflict, Database, request_context

COOKIE = "escritura_session"


def create_app(data_dir=None, demo=False):
    demo = bool(demo or os.environ.get("ESCRITURA_DEMO") == "1")
    database = Database(data_dir)
    core = Core(database, demo)
    application = FastAPI(title="Escritura Integrada", version=__version__, docs_url=None, redoc_url=None)
    application.state.core = core
    application.state.db = database
    application.state.demo = demo
    from .lookups import LookupService
    application.state.lookups = LookupService(database)
    frontend = Path(__file__).resolve().parents[1] / "frontend" / "dist"

    @application.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse({"detail": exc.detail, "code": exc.code}, status_code=exc.status)

    @application.exception_handler(ContextConflict)
    async def context_error(request, exc):
        return JSONResponse({"detail": str(exc), "code": "stale_context"}, status_code=409)

    @application.exception_handler(sqlite3.IntegrityError)
    async def integrity_error(request, exc):
        return JSONResponse({"detail": "Código, CNPJ, identificação ou vínculo já utilizado, ou referência incompatível. Confira os dados antes de salvar.", "code": "constraint_conflict"}, status_code=409)

    @application.exception_handler(sqlite3.OperationalError)
    async def database_error(request, exc):
        # No paths, SQL, or stored personal data in public error responses.
        return JSONResponse({"detail": "O banco não concluiu a operação. Tente novamente; se persistir, confira disponibilidade e permissões do diretório de dados.", "code": "database_unavailable"}, status_code=503)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        fields = ", ".join(".".join(str(x) for x in e["loc"][1:]) or "corpo" for e in exc.errors())
        return JSONResponse({"detail": "Dados inválidos ou incompletos: " + fields + ".", "code": "invalid_request"}, status_code=422)

    @application.middleware("http")
    async def session_and_security(request: Request, call_next):
        path, method = request.url.path, request.method
        mutating = method in {"POST", "PUT", "PATCH", "DELETE"}
        public = {"/api/health", "/api/session", "/api/setup", "/api/login", "/api/demo-login"}
        ctx_token = None
        if path.startswith("/api/"):
            if mutating:
                content_length = request.headers.get("content-length")
                if content_length and (not content_length.isdigit() or int(content_length) > 30_000_000):
                    return JSONResponse({"detail": "Requisição excede o limite de tamanho.", "code": "request_too_large"}, 413)
                origin = request.headers.get("origin")
                if origin and urlsplit(origin).netloc != request.headers.get("host"):
                    return JSONResponse({"detail": "Origem da requisição não autorizada.", "code": "invalid_origin"}, 403)
                if request.headers.get("sec-fetch-site") == "cross-site":
                    return JSONResponse({"detail": "Origem da requisição não autorizada.", "code": "invalid_origin"}, 403)
            token = request.cookies.get(COOKIE, "")
            session = core.session(token)
            request.state.session = session
            request.state.token = token
            if path not in public:
                if not session["authenticated"]:
                    return JSONResponse({"detail": "Entre no aplicativo para acessar os dados.", "code": "unauthenticated"}, 401)
                match_permission = re.match(r"^/api/companies/(\d+)(?:/|$)", path)
                permission_cid = int(match_permission.group(1)) if match_permission else None
                from .permissions import route_policy
                payload = {}
                if mutating and 'application/json' in request.headers.get('content-type', ''):
                    try:
                        parsed = await request.json()
                        payload = parsed if isinstance(parsed, dict) else {}
                    except ValueError:
                        pass
                if path=='/api/templates' and mutating and payload.get('source_company_id')!=session['active_company_id']:
                    return JSONResponse({'detail':'Ative a empresa de origem antes de criar o modelo.','code':'stale_context'},409)
                routine, action, privileged = route_policy(path, method, request.query_params, payload, session)
                if permission_cid is None and routine:
                    permission_cid = session['active_company_id']
                if routine and permission_cid is None and not (routine=='lookup' and session['user']['role']=='admin'):
                    return JSONResponse({'detail':'Ative uma empresa antes de acessar esta rotina.','code':'no_company'},409)
                writing = mutating and path not in {'/api/context', '/api/logout'}
                try:
                    core.authorize(session['user'], permission_cid, writing, privileged, routine, action or 'read')
                except DomainError as exc:
                    return JSONResponse({'detail': exc.detail, 'code': exc.code}, exc.status)
                if mutating:
                    csrf = request.headers.get("x-csrf-token", "")
                    if not csrf or not hmac.compare_digest(csrf, session["csrf_token"]):
                        return JSONResponse({"detail": "Confirmação de sessão inválida. Atualize a página.", "code": "invalid_csrf"}, 403)
                    expected = {"token_hash": digest(token.encode()), "user_id": session["user"]["id"], "write": writing, "admin": privileged, "permission_company_id": permission_cid, "routine": routine, "action": action or 'read'}
                    match = re.match(r"^/api/companies/(\d+)/", path)
                    if match:
                        cid = int(match.group(1))
                        if session["active_company_id"] != cid:
                            return JSONResponse({"detail": "A empresa ativa mudou. Reabra o lançamento no contexto correto.", "code": "stale_context"}, 409)
                        for header, value in [('x-company-id',str(cid)),('x-period',session['period']),('x-module',session.get('module','fiscal'))]:
                            if request.headers.get(header) and request.headers[header] != value:
                                return JSONResponse({'detail':'O contexto mudou. Reabra a operação na empresa, módulo e competência apresentados.','code':'stale_context'},409)
                        expected.update(company_id=cid, period=session["period"], module=session.get('module','fiscal'))
                    ctx_token = request_context.set(expected)
                else:
                    ctx_token = request_context.set({"token_hash":digest(token.encode()),"user_id":session["user"]["id"],"write":False,"permission_company_id":permission_cid,"routine":routine,"action":action or "read"})
        try:
            response = await call_next(request)
        finally:
            if ctx_token is not None:
                request_context.reset(ctx_token)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def actor(request):
        return request.state.session["user"]["username"]

    def active_period(request, supplied=None):
        return period(supplied or request.state.session["period"])

    def check_period(request, competence):
        competence = period(competence)
        if competence != request.state.session["period"]:
            raise DomainError("A data pertence a outra competência. Ative a competência correta e reabra o lançamento.", 409, "stale_context")
        return competence

    def check_date(request, value, label="Data"):
        check_period(request, iso_date(value, label)[:7])

    def check_document_period(request, cid, item_id):
        with database.read() as conn:
            doc = select_one(conn, "documents", cid, item_id)
            check_period(request, doc["period"])

    def login_response(request, token):
        old = request.cookies.get(COOKIE)
        if old and old != token:
            core.logout(old)
        response = JSONResponse(core.session(token))
        response.set_cookie(COOKIE, token, max_age=43200, httponly=True, secure=request.url.scheme == "https" or os.environ.get("ESCRITURA_COOKIE_SECURE") == "1", samesite="strict", path="/")
        return response

    @application.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__, "demo": demo}

    @application.get("/api/session")
    def session(request: Request):
        return request.state.session

    @application.post("/api/setup")
    def setup(request: Request, payload: dict[str, Any] = Body(...)):
        return login_response(request, core.setup(payload))

    @application.post("/api/login")
    def login(request: Request, payload: dict[str, Any] = Body(...)):
        remote = request.client.host if request.client else "local"
        return login_response(request, core.login(payload, remote))

    @application.post("/api/demo-login")
    def demo_login(request: Request):
        return login_response(request, core.demo_login())

    @application.post("/api/logout")
    def logout(request: Request):
        core.logout(request.state.token)
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict")
        return response

    @application.post("/api/context")
    def context(request: Request, payload: dict[str, Any] = Body(...)):
        core.authorize(request.state.session["user"], payload.get("company_id"))
        return core.context(request.state.token, payload)

    @application.get("/api/companies")
    def companies(request: Request):
        all_companies = core.companies()
        if request.state.session['user']['role'] == 'admin':
            return all_companies
        allowed = set(core.allowed_companies(request.state.session['user']['id']))
        from .permissions import decision
        with database.read() as conn:
            return [c|{'can_edit':decision(conn,request.state.session['user']['id'],c['id'],'system.companies','edit')['allowed']} for c in all_companies if c['id'] in allowed]

    @application.post("/api/companies", status_code=201)
    def create_company(request: Request, payload: dict[str, Any] = Body(...)):
        return core.create_company(payload, actor(request))

    @application.put("/api/companies/{cid}")
    def update_company(cid: int, request: Request, payload: dict[str, Any] = Body(...)):
        return core.update_company(cid, payload, actor(request))

    @application.get("/api/companies/{cid}/accounts")
    def accounts(cid: int):
        return core.accounts(cid)

    @application.post("/api/companies/{cid}/accounts", status_code=201)
    def create_account(cid: int, request: Request, payload: dict[str, Any] = Body(...)):
        return core.save_account(cid, payload, actor(request))

    @application.put("/api/companies/{cid}/accounts/{item_id}")
    def update_account(cid: int, item_id: int, request: Request, payload: dict[str, Any] = Body(...)):
        return core.save_account(cid, payload, actor(request), item_id)

    @application.get("/api/companies/{cid}/cost-centers")
    def cost_centers(cid: int):
        return core.cost_centers(cid)

    @application.post("/api/companies/{cid}/cost-centers", status_code=201)
    def create_cost_center(cid: int, request: Request, payload: dict[str, Any] = Body(...)):
        return core.save_cost_center(cid, payload, actor(request))

    @application.put("/api/companies/{cid}/cost-centers/{item_id}")
    def update_cost_center(cid: int, item_id: int, request: Request, payload: dict[str, Any] = Body(...)):
        return core.save_cost_center(cid, payload, actor(request), item_id)

    @application.get("/api/companies/{cid}/journals")
    def journals(cid: int, request: Request, period: str | None = None):
        return core.journals(cid, active_period(request, period))

    @application.post("/api/companies/{cid}/journals", status_code=201)
    def create_journal(cid: int, request: Request, payload: dict[str, Any] = Body(...)):
        check_date(request, payload.get("date"))
        return core.create_journal(cid, payload, actor(request))

    @application.post("/api/companies/{cid}/journals/{item_id}/reverse")
    def reverse_journal(cid: int, item_id: int, request: Request, payload: dict[str, Any] = Body(...)):
        check_date(request, payload.get("date"))
        return core.reverse_journal(cid, item_id, payload, actor(request))

    @application.get("/api/companies/{cid}/documents")
    def documents(cid: int, request: Request, period: str | None = None):
        return core.documents(cid, active_period(request, period))

    @application.post("/api/companies/{cid}/documents", status_code=201)
    def create_document(cid: int, request: Request, payload: dict[str, Any] = Body(...)):
        check_date(request, payload.get("posting_date"), "Escrituração")
        return core.create_document(cid, payload, actor(request))

    @application.put("/api/companies/{cid}/documents/{item_id}")
    def update_document(cid: int, item_id: int, request: Request, payload: dict[str, Any] = Body(...)):
        if payload.get("posting_date"):
            check_date(request, payload["posting_date"], "Escrituração")
        else:
            check_document_period(request, cid, item_id)
        return core.update_document(cid, item_id, payload, actor(request))

    @application.post("/api/companies/{cid}/documents/{item_id}/review")
    def review_document(cid: int, item_id: int, request: Request, payload: dict[str, Any] = Body(...)):
        check_document_period(request, cid, item_id)
        return core.review_document(cid, item_id, payload, actor(request))

    @application.post("/api/companies/{cid}/documents/{item_id}/book")
    def book_document(cid: int, item_id: int, request: Request, payload: dict[str, Any] = Body(...)):
        check_document_period(request, cid, item_id)
        return core.book_document(cid, item_id, payload, actor(request))

    @application.get("/api/companies/{cid}/titles")
    def titles(cid: int, kind: str | None = None):
        return core.titles(cid, kind)

    @application.post("/api/companies/{cid}/titles", status_code=201)
    def create_title(cid: int, request: Request, payload: dict[str, Any] = Body(...)):
        check_date(request,payload.get("issue_date"),"Emissão do título")
        return core.create_title(cid, payload, actor(request))

    @application.post("/api/companies/{cid}/titles/{item_id}/settle")
    def settle_title(cid: int, item_id: int, request: Request, payload: dict[str, Any] = Body(...)):
        check_date(request, payload.get("date"), "Baixa financeira")
        return core.settle_title(cid, item_id, payload, actor(request))

    @application.get("/api/companies/{cid}/banks")
    def banks(cid: int, request: Request, period: str | None = None):
        return core.banks(cid, active_period(request, period))

    @application.get("/api/companies/{cid}/banks/{item_id}/suggestions")
    def bank_suggestions(cid: int, item_id: int):
        return core.bank_suggestions(cid, item_id)

    @application.post("/api/companies/{cid}/banks/{item_id}/reconcile")
    def reconcile(cid: int, item_id: int, request: Request, payload: dict[str, Any] = Body(...)):
        with database.read() as conn:check_date(request,select_one(conn,"bank_transactions",cid,item_id)["date"])
        return core.reconcile(cid, item_id, payload, actor(request))

    @application.post("/api/companies/{cid}/banks/{item_id}/unreconcile")
    def unreconcile(cid: int, item_id: int, request: Request, payload: dict[str, Any] = Body(...)):
        with database.read() as conn:check_date(request,select_one(conn,"bank_transactions",cid,item_id)["date"])
        return core.unreconcile(cid, item_id, payload, actor(request))

    @application.get("/api/companies/{cid}/catalogs")
    def catalogs(cid: int, kind: str | None = None):
        return core.catalogs(cid, kind)

    @application.post("/api/companies/{cid}/catalogs", status_code=201)
    def create_catalog(cid: int, request: Request, payload: dict[str, Any] = Body(...)):
        return core.save_catalog(cid, payload, actor(request))

    @application.put("/api/companies/{cid}/catalogs/{item_id}")
    def update_catalog(cid: int, item_id: int, request: Request, payload: dict[str, Any] = Body(...)):
        return core.save_catalog(cid, payload, actor(request), item_id)

    @application.delete("/api/companies/{cid}/catalogs/{item_id}")
    def delete_catalog(cid: int, item_id: int, version: int, request: Request):
        return core.save_catalog(cid, {"version": version, "active": False}, actor(request), item_id)

    @application.get("/api/companies/{cid}/rules")
    def rules(cid: int):
        return core.rules(cid)

    @application.get("/api/companies/{cid}/rules/{item_id}/versions")
    def rule_versions(cid: int, item_id: int):
        return core.rule_versions(cid, item_id)

    @application.post("/api/companies/{cid}/rules", status_code=201)
    def create_rule(cid: int, request: Request, payload: dict[str, Any] = Body(...)):
        return core.save_rule(cid, payload, actor(request))

    @application.put("/api/companies/{cid}/rules/{item_id}")
    def update_rule(cid: int, item_id: int, request: Request, payload: dict[str, Any] = Body(...)):
        return core.save_rule(cid, payload, actor(request), item_id)

    @application.delete("/api/companies/{cid}/rules/{item_id}")
    def delete_rule(cid: int, item_id: int, version: int, request: Request):
        return core.save_rule(cid, {"version": version, "active": False}, actor(request), item_id)

    @application.post("/api/companies/{cid}/rules/{item_id}/simulate")
    def simulate_rule(cid: int, item_id: int, request: Request, payload: dict[str, Any] = Body(...)):
        return core.simulate_rule(cid, item_id, payload, actor(request))

    @application.get("/api/templates")
    def templates(request: Request):
        allowed = {c['id'] for c in companies(request)}
        return [t for t in core.templates() if t['source_company_id'] in allowed]

    @application.post("/api/templates", status_code=201)
    def create_template(request: Request, payload: dict[str, Any] = Body(...)):
        if payload.get("source_company_id") != request.state.session["active_company_id"]:
            raise DomainError("Ative a empresa de origem para salvar seu modelo.", 409, "stale_context")
        return core.create_template(payload, actor(request))

    @application.post("/api/companies/{cid}/templates/{item_id}/apply")
    def apply_template(cid: int, item_id: int, request: Request, payload: dict[str, Any] = Body(...)):
        visible = {t['id'] for t in templates(request)}
        if item_id not in visible:
            raise DomainError('Modelo não disponível para este usuário.', 403, 'forbidden')
        return core.apply_template(cid, item_id, payload, actor(request))

    @application.get("/api/companies/{cid}/imports")
    def imports(cid: int):
        return core.imports(cid)

    @application.post("/api/companies/{cid}/imports/preview")
    def preview_import(cid: int, request: Request, payload: dict[str, Any] = Body(...)):
        check_period(request, payload.get("period"))
        return core.preview_import(cid, payload, actor(request))

    @application.get("/api/companies/{cid}/imports/{item_id}")
    def import_detail(cid: int, item_id: int):
        return core.import_detail(cid, item_id)

    @application.post("/api/companies/{cid}/imports/{item_id}/confirm")
    def confirm_import(cid: int, item_id: int, request: Request, payload: dict[str, Any] = Body(...)):
        with database.read() as conn:
            batch = select_one(conn, "imports", cid, item_id)
            check_period(request, batch["period"])
        return core.confirm_import(cid, item_id, payload, actor(request))

    @application.get("/api/companies/{cid}/periods")
    def periods(cid: int, request: Request, period: str | None = None):
        return core.periods(cid, active_period(request, period))

    @application.post("/api/companies/{cid}/periods/close")
    def close_period(cid: int, request: Request, payload: dict[str, Any] = Body(...)):
        return core.set_period(cid, payload, actor(request), True)

    @application.post("/api/companies/{cid}/periods/reopen")
    def reopen_period(cid: int, request: Request, payload: dict[str, Any] = Body(...)):
        return core.set_period(cid, payload, actor(request), False)

    @application.get("/api/companies/{cid}/reports/{kind}")
    def report(cid: int, kind: str, request: Request, period: str | None = None, account_id: int | None = None, cost_center_id: int | None = None):
        return core.report(cid, kind, active_period(request, period), account_id, cost_center_id)

    @application.get("/api/companies/{cid}/dashboard")
    def dashboard(cid: int, request: Request, period: str | None = None):
        result = core.dashboard(cid, active_period(request, period))
        from .permissions import decision
        with database.read() as conn:
            for key,routine in [('documents','fiscal.documents'),('accounting','accounting.journals'),('financial','financial.titles'),('reconciliation','financial.reconciliation')]:
                if not decision(conn,request.state.session['user']['id'],cid,routine,'read')['allowed']:
                    result[key] = {k:0 for k in result[key]} | {'restricted':True}
        return result

    @application.get("/api/companies/{cid}/audit")
    def audit_entries(cid: int, limit: int = 100):
        return core.audit(cid, limit)

    from .business_api import register_business_routes
    register_business_routes(application, core, database, actor, check_date, check_period)
    from .management_api import register_management_routes
    register_management_routes(application, core, database, actor)

    @application.get("/{resource_path:path}")
    def frontend_asset(resource_path: str):
        if resource_path.startswith("api/"):
            return JSONResponse({"detail": "Recurso não encontrado.", "code": "not_found"}, status_code=404)
        target = (frontend / resource_path).resolve()
        if target.is_relative_to(frontend.resolve()) and target.is_file():
            return FileResponse(target)
        if resource_path and Path(resource_path).suffix:
            return JSONResponse({"detail": "Arquivo não encontrado."}, status_code=404)
        index = frontend / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return JSONResponse({"detail": "Interface ainda não compilada. Execute o build do frontend conforme README.", "version": __version__}, status_code=503)

    return application


app = create_app()
