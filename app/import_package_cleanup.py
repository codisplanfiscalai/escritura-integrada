"""Retire source packages, never movements or their normalized provenance.

Tombstones retain import identity; matching source bytes can restore it without
replaying movements. Company controls govern retention and fiscal-source
protection; shared evidence and integrity remain protected.
"""
import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from fastapi import Body, Request
from .core import DomainError, audit, company_row, digest, now, pack, select_one

MODES = {'originals', 'originals_and_hide_history', 'hide_history'}
DEFAULTS = {'enabled': False, 'retention_days': 1825, 'interval_hours': 24,
            'mode': 'hide_history', 'last_run': None}


def migrate(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS import_package_tombstones (
        import_id INTEGER PRIMARY KEY REFERENCES imports(id), company_id INTEGER NOT NULL,
        removed_at TEXT NOT NULL, removed_by TEXT NOT NULL, original_bytes INTEGER NOT NULL,
        history_hidden INTEGER NOT NULL DEFAULT 0, sha256 TEXT NOT NULL,
        FOREIGN KEY(company_id,import_id) REFERENCES imports(company_id,id))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS import_package_history (
        import_id INTEGER PRIMARY KEY REFERENCES imports(id), company_id INTEGER NOT NULL,
        hidden_at TEXT NOT NULL, hidden_by TEXT NOT NULL,
        FOREIGN KEY(company_id,import_id) REFERENCES imports(company_id,id))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS import_package_settings (
        company_id INTEGER PRIMARY KEY REFERENCES companies(id), payload_json TEXT NOT NULL,
        configured_by INTEGER REFERENCES users(id), last_run TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS stored_file_tombstones (
        file_id INTEGER PRIMARY KEY REFERENCES stored_files(id), removed_at TEXT NOT NULL)''')


def require_original(conn, cid, iid):
    select_one(conn, 'imports', cid, iid)
    if conn.execute('SELECT 1 FROM import_package_tombstones WHERE company_id=? AND import_id=?', (cid, iid)).fetchone():
        raise DomainError('Original removido por limpeza autorizada. Os movimentos e a origem normalizada permanecem preservados.', 410, 'original_removed')


def reject_removed_upload(conn, cid, sha256):
    # Other modules must not silently revive fiscal identities through store_file.
    if conn.execute('SELECT 1 FROM import_package_tombstones WHERE company_id=? AND sha256=?', (cid, sha256)).fetchone():
        raise DomainError('Reenvie o arquivo original em Importações para restaurar o lote existente sem recriar movimentos.', 409, 'removed_package_reupload')


def restore_upload(conn, cid, raw, actor):
    """Restore canonical bytes only, in the caller's write transaction."""
    from .permissions import import_access
    sha = hashlib.sha256(raw).hexdigest()
    rows = conn.execute("""SELECT i.* FROM imports i WHERE i.company_id=? AND i.sha256=?
        AND (EXISTS (SELECT 1 FROM import_package_tombstones t WHERE t.import_id=i.id)
        OR EXISTS (SELECT 1 FROM audit a WHERE a.company_id=i.company_id AND a.entity='import'
                   AND a.entity_id=CAST(i.id AS TEXT) AND a.action='restore-original')) ORDER BY i.id""", (cid, sha)).fetchall()
    if not rows:
        return None
    for row in rows:
        import_access(conn, cid, json.loads(row['parsed_json']), 'import')
        tomb = conn.execute('SELECT * FROM import_package_tombstones WHERE company_id=? AND import_id=?', (cid, row['id'])).fetchone()
        if not tomb:
            continue
        if tomb['sha256'] != sha or tomb['original_bytes'] != len(raw):
            raise DomainError('A evidência removida não corresponde ao arquivo reenviado.', 409, 'original_integrity_mismatch')
        for f in file_rows(conn, row):
            removed = conn.execute('SELECT 1 FROM stored_file_tombstones WHERE file_id=?', (f['id'],)).fetchone()
            if removed:
                conn.execute('UPDATE stored_files SET content=? WHERE company_id=? AND id=?', (raw, cid, f['id']))
                conn.execute('DELETE FROM stored_file_tombstones WHERE file_id=?', (f['id'],))
            elif hashlib.sha256(f['content']).hexdigest() != sha:
                raise DomainError('Integridade da cópia original comprometida.', 409, 'original_integrity_mismatch')
        if tomb['history_hidden']:
            conn.execute('INSERT OR IGNORE INTO import_package_history VALUES(?,?,?,?)', (row['id'], cid, tomb['removed_at'], tomb['removed_by']))
        conn.execute('UPDATE imports SET original=? WHERE company_id=? AND id=?', (raw, cid, row['id']))
        conn.execute('DELETE FROM import_package_tombstones WHERE company_id=? AND import_id=?', (cid, row['id']))
        audit(conn, cid, actor, 'restore-original', 'import', row['id'], {'sha256': sha, 'bytes': len(raw), 'movements_preserved': True, 'removed_at': tomb['removed_at']})
    return select_one(conn, 'imports', cid, rows[0]['id'])


def settings(conn, cid):
    company_row(conn, cid)
    row = conn.execute('SELECT * FROM import_package_settings WHERE company_id=?', (cid,)).fetchone()
    from .operational_settings import get_settings
    controls = get_settings(conn, cid)
    return DEFAULTS | (json.loads(row['payload_json']) | {'last_run': row['last_run']} if row else {}) | {k: controls[k] for k in ('enforce_package_retention', 'protect_fiscal_source')}


def authorize(conn, cid, action='delete'):
    from .db import request_context
    from .permissions import require
    context = request_context.get()
    if context and context.get('user_id'):
        require(conn, context['user_id'], cid, 'fiscal.imports', action)


def file_rows(conn, row):
    return conn.execute("SELECT * FROM stored_files WHERE company_id=? AND category='originals' AND sha256=?", (row['company_id'], row['sha256'])).fetchall()


def describe(conn, row, cfg):
    tomb = conn.execute('SELECT * FROM import_package_tombstones WHERE import_id=?', (row['id'],)).fetchone()
    reasons = []
    if tomb: reasons.append('original_already_removed')
    try:
        created = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
        if created.tzinfo is None: created = created.replace(tzinfo=timezone.utc)
        if cfg.get('enforce_package_retention', False) and created > datetime.now(timezone.utc) - timedelta(days=cfg['retention_days']): reasons.append('retention_period')
    except ValueError:
        if cfg.get('enforce_package_retention', False): reasons.append('invalid_creation_date')
    parsed = json.loads(row['parsed_json'])
    hashes = {d.get('source_hash') for d in parsed.get('documents', []) if d.get('source_hash')}
    linked = bool(json.loads(row['confirmation_json'] or '{}').get('document_ids'))
    for sha in hashes:
        linked = linked or bool(conn.execute('SELECT 1 FROM documents WHERE company_id=? AND source_hash=?', (row['company_id'], sha)).fetchone())
    if linked and cfg.get('protect_fiscal_source', False): reasons.append('sole_fiscal_source_evidence')
    files = file_rows(conn, row)
    for f in files:
        for table in ('module_imports', 'auditor_catalog_sources', 'auditor_auxiliary', 'auditor_attachments', 'auditor_reports'):
            if conn.execute(f'SELECT 1 FROM {table} WHERE company_id=? AND file_id=?', (row['company_id'], f['id'])).fetchone():
                reasons.append('shared_audit_or_module_evidence'); break
    # Other import identities can share exactly the same bytes: never damage them.
    if conn.execute('SELECT 1 FROM imports WHERE company_id=? AND sha256=? AND id<>? AND length(original)>0', (row['company_id'], row['sha256'], row['id'])).fetchone():
        reasons.append('shared_import_original')
    if not tomb and (hashlib.sha256(row['original']).hexdigest() != row['sha256'] or any(hashlib.sha256(f['content']).hexdigest() != f['sha256'] for f in files)):
        reasons.append('original_integrity_mismatch')
    return {k: row[k] for k in ('id', 'filename', 'status', 'period', 'created_at', 'sha256')} | {
        'available': not bool(tomb), 'history_hidden': bool((tomb and tomb['history_hidden']) or conn.execute('SELECT 1 FROM import_package_history WHERE company_id=? AND import_id=?', (row['company_id'], row['id'])).fetchone()),
        'original_bytes': len(row['original']), 'stored_bytes': sum(len(f['content']) for f in files),
        'blocked_reasons': sorted(set(reasons))}


def fiscal_package(parsed):
    return bool(parsed.get('documents')) or not parsed.get('transactions')


def preview(conn, cid, payload):
    authorize(conn, cid)
    ids = payload.get('ids')
    mode = payload.get('mode', 'hide_history')
    if not isinstance(ids, list) or not ids or any(type(i) is not int or i < 1 for i in ids) or len(set(ids)) != len(ids) or mode not in MODES:
        raise DomainError('Selecione um ou mais pacotes distintos e um modo de limpeza válido.')
    from .operational_settings import ensure_action_allowed, ensure_selection_allowed
    ensure_action_allowed(conn, cid, 'block_package_cleanup')
    ensure_selection_allowed(conn, cid, len(ids))
    cfg = settings(conn, cid)
    rows = [select_one(conn, 'imports', cid, iid) for iid in sorted(ids)]
    from .permissions import import_access
    for row in rows:
        parsed = json.loads(row['parsed_json'])
        if not fiscal_package(parsed):
            raise DomainError('Pacote exclusivamente financeiro fora do controle fiscal.', 409, 'non_fiscal_package')
        import_access(conn, cid, parsed, 'import')
    packages = [describe(conn, r, cfg) for r in rows]
    if mode == 'hide_history':
        for p in packages:
            p['blocked_reasons'] = []  # Manual, reversible archive needs no retention waiver.
            if p['history_hidden']: p['blocked_reasons'].append('history_already_hidden')
    eligible = [p for p in packages if not p['blocked_reasons']]
    result = {'company_id': cid, 'ids': sorted(ids), 'mode': mode, 'packages': packages,
              'eligible_ids': [p['id'] for p in eligible],
              'blocked_ids': [p['id'] for p in packages if p['blocked_reasons']],
              'estimated_bytes': 0 if mode == 'hide_history' else sum(p['original_bytes'] + p['stored_bytes'] for p in eligible),
              'warnings': ['Remoção irreversível dos originais ativos; backups existentes não são alterados.',
                           'Movimentos, documentos, títulos, identidade, dados normalizados e auditoria serão preservados.',
                           'O espaço físico do SQLite não diminui imediatamente. A proteção das fontes fiscais segue os parâmetros da empresa.']}
    if mode == 'hide_history':
        result['warnings'] = ['Somente o histórico será ocultado. Arquivos evidenciais e movimentos mantidos; 0 bytes liberados. O histórico pode ser restaurado.']
    result['preview_hash'] = digest({'preview': result, 'settings': cfg, 'versions': [{k: r[k] for k in r.keys() if k != 'original'} for r in rows]})
    return result


def confirm(db, conn, cid, payload, actor):
    result = preview(conn, cid, payload)
    if result['mode'] != 'hide_history' and payload.get('acknowledge_irreversible') is not True:
        raise DomainError('Confirme expressamente a remoção irreversível dos arquivos originais.')
    if payload.get('preview_hash') != result['preview_hash']:
        raise DomainError('A seleção ou os pacotes mudaram. Atualize a prévia.', 409, 'stale_cleanup_preview')
    if result['blocked_ids']:
        raise DomainError('A seleção contém pacotes protegidos. Selecione apenas os elegíveis.', 409, 'protected_import_package')
    from .file_store import file_path
    for iid in result['eligible_ids']:
        row = select_one(conn, 'imports', cid, iid)
        if result['mode'] == 'hide_history':
            conn.execute('INSERT INTO import_package_history VALUES(?,?,?,?)', (iid, cid, now(), actor))
            audit(conn, cid, actor, 'hide-import-history', 'import', iid, {'original_preserved': True, 'movements_preserved': True})
            continue
        for f in file_rows(conn, row):
            path = file_path(db, f)
            # A rollback leaves canonical SQLite bytes intact and regenerable.
            try: path.unlink(missing_ok=True)
            except OSError as exc: raise DomainError('Não foi possível remover a cópia local; nenhuma limpeza foi confirmada.', 409, 'package_file_busy') from exc
            conn.execute('UPDATE stored_files SET content=? WHERE id=?', (b'', f['id']))
            conn.execute('INSERT INTO stored_file_tombstones VALUES(?,?)', (f['id'], now()))
        conn.execute('INSERT INTO import_package_tombstones VALUES(?,?,?,?,?,?,?)',
                     (iid, cid, now(), actor, len(row['original']), int(result['mode'] == 'originals_and_hide_history'), row['sha256']))
        conn.execute('UPDATE imports SET original=? WHERE company_id=? AND id=?', (b'', cid, iid))
        audit(conn, cid, actor, 'cleanup-original', 'import', iid, {'sha256': row['sha256'], 'bytes': len(row['original']), 'mode': result['mode'], 'movements_preserved': True})
    return result | {'cleaned_ids': result['eligible_ids'], 'movements_preserved': True}


def save_settings(conn, cid, payload, actor, uid):
    authorize(conn, cid)
    company_row(conn, cid)
    cfg = {k: payload.get(k, v) for k, v in DEFAULTS.items() if k != 'last_run'}
    if type(cfg['enabled']) is not bool or type(cfg['retention_days']) is not int or not 1 <= cfg['retention_days'] <= 36500 or type(cfg['interval_hours']) is not int or not 1 <= cfg['interval_hours'] <= 8760 or cfg['mode'] not in MODES:
        raise DomainError('Configuração de retenção ou intervalo inválida.')
    if cfg['enabled'] and cfg['mode'] != 'hide_history' and payload.get('acknowledge_irreversible') is not True:
        raise DomainError('Confirme a limpeza periódica irreversível de originais elegíveis.')
    conn.execute('INSERT INTO import_package_settings(company_id,payload_json,configured_by) VALUES(?,?,?) ON CONFLICT(company_id) DO UPDATE SET payload_json=excluded.payload_json,configured_by=excluded.configured_by', (cid, pack(cfg), uid))
    audit(conn, cid, actor, 'configure-cleanup', 'import-packages', cid, cfg)
    return settings(conn, cid)


def run_due(db):
    from .permissions import require
    from .operational_settings import get_settings
    with db.transaction() as conn:
        for row in conn.execute('SELECT * FROM import_package_settings').fetchall():
            cid = row['company_id']; cfg = settings(conn, cid)
            if not cfg['enabled']: continue
            if row['last_run'] and datetime.fromisoformat(row['last_run']) > datetime.now(timezone.utc) - timedelta(hours=cfg['interval_hours']): continue
            conn.execute('UPDATE import_package_settings SET last_run=? WHERE company_id=?', (now(), cid))
            controls = get_settings(conn, cid)
            if controls['block_package_cleanup']:
                audit(conn, cid, 'scheduler', 'cleanup-skipped', 'import-packages', cid,
                      {'reason': 'operational_restriction', 'parameter': 'block_package_cleanup'})
                continue
            try:
                require(conn, row['configured_by'], cid, 'fiscal.imports', 'delete')
            except DomainError as exc:
                if exc.status != 403: raise
                audit(conn, cid, 'scheduler', 'cleanup-skipped', 'import-packages', cid, {'reason': 'permission_revoked'}); continue
            candidates = conn.execute('SELECT * FROM imports WHERE company_id=? AND length(original)>0 ORDER BY id', (cid,)).fetchall()
            ids = []
            for candidate in candidates:
                parsed = json.loads(candidate['parsed_json'])
                if not fiscal_package(parsed): continue
                try:
                    if parsed.get('documents'):
                        require(conn, row['configured_by'], cid, 'fiscal.imports', 'import')
                    if parsed.get('transactions'):
                        require(conn, row['configured_by'], cid, 'financial.reconciliation', 'import')
                except DomainError as exc:
                    if exc.status != 403: raise
                    audit(conn, cid, 'scheduler', 'cleanup-skipped', 'import', candidate['id'],
                          {'reason': 'permission_revoked', 'configured_by': row['configured_by']})
                    continue
                p = describe(conn, candidate, cfg | {'enforce_package_retention': True})
                reasons = p['blocked_reasons']
                if cfg['mode'] == 'hide_history':
                    reasons = [r for r in reasons if r in {'retention_period', 'invalid_creation_date'}]
                    if p['history_hidden']: reasons.append('history_already_hidden')
                if not reasons:
                    ids.append(candidate['id'])
                    if controls['limit_batch_selection'] and len(ids) >= controls['batch_selection_limit']:
                        break  # Remaining packages are reconsidered at the next configured interval.
            if ids:
                payload = {'ids': ids, 'mode': cfg['mode'], 'acknowledge_irreversible': True}
                payload['preview_hash'] = preview(conn, cid, payload)['preview_hash']
                confirm(db, conn, cid, payload, 'scheduler')


async def scheduler(db):
    import logging
    while True:
        try: await asyncio.to_thread(run_due, db)
        except Exception: logging.getLogger(__name__).exception('Package cleanup failed; transactional changes rolled back')
        await asyncio.sleep(60)


def register(app, core, actor):
    db = core.db
    @app.get('/api/companies/{cid}/import-packages')
    def packages(cid: int, request: Request):
        with db.read(snapshot=True) as conn:
            from .permissions import decision
            authorize(conn, cid, 'read'); cfg = settings(conn, cid)
            return {'settings': cfg, 'packages': [describe(conn, r, cfg) for r in conn.execute('SELECT * FROM imports WHERE company_id=? ORDER BY id DESC', (cid,)) if fiscal_package(json.loads(r['parsed_json'])) and (not json.loads(r['parsed_json']).get('transactions') or decision(conn, request.state.session['user']['id'], cid, 'financial.reconciliation', 'read')['allowed'])]}
    @app.put('/api/companies/{cid}/import-packages/settings')
    def configure(cid: int, request: Request, payload: dict = Body(...)):
        with db.transaction() as conn: return save_settings(conn, cid, payload, actor(request), request.state.session['user']['id'])
    @app.post('/api/companies/{cid}/import-packages/cleanup-preview')
    def cleanup_preview(cid: int, payload: dict = Body(...)):
        with db.read(snapshot=True) as conn: return preview(conn, cid, payload)
    @app.post('/api/companies/{cid}/import-packages/cleanup-confirm')
    def cleanup_confirm(cid: int, request: Request, payload: dict = Body(...)):
        with db.transaction() as conn: return confirm(db, conn, cid, payload, actor(request))

    @app.post('/api/companies/{cid}/import-packages/restore-history')
    def restore_history(cid: int, request: Request, payload: dict = Body(...)):
        ids = payload.get('ids')
        if not isinstance(ids, list) or not ids or any(type(i) is not int or i < 1 for i in ids):
            raise DomainError('Informe os pacotes a restaurar no histórico.')
        with db.transaction() as conn:
            authorize(conn, cid)
            for iid in sorted(set(ids)):
                row = select_one(conn, 'imports', cid, iid)
                from .permissions import import_access
                import_access(conn, cid, json.loads(row['parsed_json']), 'import')
                conn.execute('DELETE FROM import_package_history WHERE company_id=? AND import_id=?', (cid, iid))
                conn.execute('UPDATE import_package_tombstones SET history_hidden=0 WHERE company_id=? AND import_id=?', (cid, iid))
                audit(conn, cid, actor(request), 'restore-import-history', 'import', iid, {'original_restored': False})
            return {'restored_ids': sorted(set(ids)), 'original_restored': False}
