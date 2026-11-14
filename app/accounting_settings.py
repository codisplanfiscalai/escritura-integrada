"""Company accounting configuration, independent from the active movement context.

Chart adoption delegates to the existing versioned account-plan services. Defaults
are suggestions for new manual journals only; no existing movement is rewritten.
"""
import json
from fastapi import Body, Request
from .core import DomainError, audit, company_row, now, pack, text
from .permissions import decision, effect

DEFAULTS = {'default_history': '', 'default_cost_center_id': None}


def read_defaults(conn, cid):
    company_row(conn, cid)
    row = conn.execute('SELECT value FROM meta WHERE key=?', (f'accounting-settings:{cid}',)).fetchone()
    saved = json.loads(row['value']) if row else {}
    return {'version': saved.get('version', 0), 'settings': DEFAULTS | saved.get('settings', {})}


def save_defaults(core, cid, payload, actor):
    with core.db.transaction() as conn:
        effect(conn, cid, 'accounting.accounts', 'edit')
        effect(conn, cid, 'accounting.accounts', 'read')
        old = read_defaults(conn, cid)
        if type(payload.get('version')) is not int or payload['version'] != old['version']:
            raise DomainError('Os parâmetros contábeis mudaram. Atualize antes de salvar.', 409, 'stale_version')
        values = payload.get('settings')
        if not isinstance(values, dict) or set(values) != set(DEFAULTS):
            raise DomainError('Parâmetros contábeis inválidos.')
        history = text(values['default_history'], 'Histórico padrão', False, 1000)
        center = values['default_cost_center_id']
        if center is not None:
            effect(conn, cid, 'accounting.cost_centers', 'read')
            if type(center) is not int or not conn.execute('SELECT 1 FROM cost_centers WHERE company_id=? AND id=? AND active=1', (cid, center)).fetchone():
                raise DomainError('Escolha um centro de custo ativo desta empresa.')
        saved = {'version': old['version'] + 1, 'settings': {'default_history': history, 'default_cost_center_id': center}, 'updated_at': now()}
        conn.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (f'accounting-settings:{cid}', pack(saved)))
        audit(conn, cid, actor, 'configure', 'accounting-settings', cid, {'before': old, 'after': saved})
        return saved


def describe(core, cid, uid):
    plans = core.global_account_plans(cid)
    with core.db.read() as conn:
        effect(conn, cid, 'accounting.accounts', 'read')
        data = read_defaults(conn, cid)
        permitted = lambda r, a: decision(conn, uid, cid, r, a)['allowed']
        centers = [dict(r) for r in conn.execute('SELECT id,code,name FROM cost_centers WHERE company_id=? AND active=1 ORDER BY code,id', (cid,))] if permitted('accounting.cost_centers', 'read') else []
        local_count = conn.execute('SELECT COUNT(*) FROM accounts WHERE company_id=?', (cid,)).fetchone()[0]
        return data | plans | {'cost_centers': centers, 'local_account_count': local_count, 'capabilities': {'edit': permitted('accounting.accounts', 'edit'), 'adopt': permitted('accounting.accounts', 'create')}}


def register(app, core, actor):
    root = '/api/companies/{cid}/accounting-settings'

    @app.get(root)
    def read(cid: int, request: Request):
        return describe(core, cid, request.state.session['user']['id'])

    @app.put(root)
    def save(cid: int, request: Request, payload: dict = Body(...)):
        save_defaults(core, cid, payload, actor(request))
        return describe(core, cid, request.state.session['user']['id'])

    @app.get('/api/companies/{cid}/accounting-entry-defaults')
    def entry_defaults(cid: int):
        with core.db.read() as conn:
            effect(conn, cid, 'accounting.journals', 'read')
            data = read_defaults(conn, cid)
            center = data['settings']['default_cost_center_id']
            if center is not None and not conn.execute('SELECT 1 FROM cost_centers WHERE company_id=? AND id=? AND active=1', (cid, center)).fetchone():
                data['settings']['default_cost_center_id'] = None
            return data

    @app.post(root + '/plans/{item_id}/preview')
    def preview(cid: int, item_id: int, request: Request, payload: dict = Body(...)):
        return core.preview_global_account_plan(cid, item_id, payload, actor(request))

    @app.post(root + '/previews/{preview_id}/confirm')
    def confirm(cid: int, preview_id: int, request: Request, payload: dict = Body(...)):
        return core.confirm_global_account_plan(cid, preview_id, payload, actor(request))

    @app.post(root + '/detach')
    def detach(cid: int, request: Request, payload: dict = Body(...)):
        return core.detach_global_account_plan(cid, payload, actor(request))
