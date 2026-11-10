"""Explicit, expiring, all-or-nothing batches; never reopens a period implicitly.

Movement rows and their exclusive SQL children are physically deleted. Immutable
import/export/auditor snapshots and shared content-addressed files remain evidence,
not live movements. This is deliberately not a disk/backups secure-erasure API.
"""
import json
import re
import secrets
import time

from .core import DomainError, audit, digest, ensure_open, now, pack, period, text
from .permissions import require
from .db import request_context
from .tax_ledger import ensure_unfinalized


def initialize_bulk_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS bulk_deleted_movements (
        kind TEXT NOT NULL, record_id INTEGER NOT NULL, company_id INTEGER NOT NULL REFERENCES companies(id),
        idempotency_key TEXT, deleted_at TEXT NOT NULL, PRIMARY KEY(kind,record_id))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS bulk_previews (
        id TEXT PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
        user_id INTEGER NOT NULL REFERENCES users(id), token_hash TEXT NOT NULL DEFAULT '', request_json TEXT NOT NULL,
        preview_hash TEXT NOT NULL, expires_at REAL NOT NULL, result_json TEXT,
        confirmation_hash TEXT, created_at REAL NOT NULL)''')
    if 'token_hash' not in {r['name'] for r in conn.execute('PRAGMA table_info(bulk_previews)')}:
        conn.execute("ALTER TABLE bulk_previews ADD COLUMN token_hash TEXT NOT NULL DEFAULT ''")


def utf8_text(value, label, required=True, maximum=1000):
    value = text(value, label, required, maximum)
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise DomainError(f'{label}: texto Unicode inválido.') from None
    return value


def normalize(payload):
    if set(payload) - {'kind', 'action', 'period', 'ids', 'scope', 'changes', 'include_linked_journals', 'include_reversal_pairs'}:
        raise DomainError('Campos não permitidos na operação em lote.')
    kind, action = payload.get('kind'), payload.get('action')
    if not isinstance(kind, str) or not isinstance(action, str) or kind not in {'documents', 'journals'} or action not in {'delete', 'review', 'book', 'update'}:
        raise DomainError('Tipo ou ação inválidos.')
    if kind == 'journals' and action not in {'delete', 'update'}:
        raise DomainError('Lançamentos permitem apenas excluir ou alterar histórico/documento.')
    include = payload.get('include_linked_journals', False)
    if type(include) is not bool or (include and (kind != 'documents' or action != 'delete')):
        raise DomainError('Inclusão contábil explícita disponível somente para exclusão fiscal.')
    reversals = payload.get('include_reversal_pairs', False)
    if type(reversals) is not bool or (reversals and (action != 'delete' or (kind == 'documents' and not include))):
        raise DomainError('Inclua pares de estorno somente na exclusão contábil ou fiscal com inclusão contábil explícita.')
    scope = payload.get('scope', 'selection')
    if not isinstance(scope, str) or scope not in {'selection', 'company'} or (scope == 'company' and action != 'delete'):
        raise DomainError('Escopo da empresa disponível somente para limpeza/exclusão.')
    ids = payload.get('ids', [])
    if scope == 'company':
        if ids != []:
            raise DomainError('Limpeza da empresa não aceita seleção de IDs.')
    elif not isinstance(ids, list) or not 1 <= len(ids) <= 5000 or any(type(i) is not int or not 1 <= i <= 9223372036854775807 for i in ids) or len(set(ids)) != len(ids):
        raise DomainError('Selecione de 1 a 5000 identificadores inteiros distintos ou escolha limpar a empresa.')
    changes = payload.get('changes', {})
    allowed = {'cfop'} if kind == 'documents' else {'history', 'document'}
    if not isinstance(changes, dict) or (action != 'update' and changes) or set(changes) - allowed or (action == 'update' and not changes):
        raise DomainError('Alteração restrita a CFOP fiscal ou histórico/documento contábil.')
    changes = {k: utf8_text(v, k, True, 1000 if k == 'history' else 100 if k == 'document' else 250) for k, v in changes.items()}
    if 'cfop' in changes and not re.fullmatch(r'[0-9]{4}', changes['cfop']):
        raise DomainError('CFOP deve conter quatro dígitos.')
    return {'kind': kind, 'action': action, 'scope': scope, 'period': period(payload.get('period')), 'ids': sorted(ids), 'changes': changes, 'include_linked_journals': include, 'include_reversal_pairs': reversals}


class BulkOperations:
    def __init__(self, core):
        self.core, self.db = core, core.db

    def _authorize(self, conn, cid, uid, req):
        module = 'fiscal' if req['kind'] == 'documents' else 'accounting'
        routine = module + ('.documents' if module == 'fiscal' else '.journals')
        require(conn, uid, cid, routine, 'read')
        require(conn, uid, cid, routine, {'review': 'edit', 'update': 'edit'}.get(req['action'], req['action']))
        if req.get('include_linked_journals'):
            require(conn, uid, cid, 'accounting.journals', 'read')
            require(conn, uid, cid, 'accounting.journals', 'delete')
        ctx = request_context.get()
        if ctx:
            if ctx.get('user_id') != uid or ctx.get('company_id') != cid or ctx.get('module') != module or str(ctx.get('period', ''))[:4] != req['period'][:4]:
                raise DomainError('Ative a empresa, módulo e competência exatos da seleção.', 409, 'stale_context')
            session = conn.execute('SELECT * FROM sessions WHERE token_hash=?', (ctx['token_hash'],)).fetchone()
            if not session or session['period'][:4] != req['period'][:4] or session['module'] != module or session['active_company_id'] != cid or session['user_id'] != uid or session['expires_at'] <= time.time():
                raise DomainError('A sessão ou competência mudou. Gere nova prévia.', 409, 'stale_context')

    def _reversal_closure(self, conn, cid, rows):
        """Expand only the explicit reversal graph, including incoming references."""
        found = {row['id']: row for row in rows}
        frontier = set(found)
        while frontier:
            marks = 'SELECT value FROM json_each(?)'
            outgoing = {row[field] for rid, row in found.items() if rid in frontier
                        for field in ('reversal_of', 'reversed_by') if row[field]}
            candidates = [dict(r) for r in conn.execute(
                f'SELECT * FROM journals WHERE company_id=? AND (reversal_of IN ({marks}) OR reversed_by IN ({marks}))',
                (cid, pack(sorted(frontier)), pack(sorted(frontier))))]
            if outgoing:
                placeholders = 'SELECT value FROM json_each(?)'
                candidates += [dict(r) for r in conn.execute(
                    f'SELECT * FROM journals WHERE company_id=? AND id IN ({placeholders})', (cid, pack(sorted(outgoing))))]
            frontier = {row['id'] for row in candidates if row['id'] not in found}
            found.update({row['id']: row for row in candidates})
        return [found[rid] for rid in sorted(found)]

    def _inspect_company(self, conn, cid, req):
        """Converge on a dependency-safe subset, without mutating any movement.

        A blocked movement is preserved; its dependants are inspected again so
        removing a candidate cannot leave an incomplete reversal/shared set.
        """
        all_rows = [dict(r) for r in conn.execute(
            f"SELECT * FROM {req['kind']} WHERE company_id=? ORDER BY id", (cid,))]
        candidates = {r['id'] for r in all_rows}
        preserved = {}
        inspections = []
        while candidates:
            selected = req | {'scope': 'company_selection', 'ids': sorted(candidates)}
            result, rows = self._inspect(conn, cid, selected)
            inspections.append(result['preview_hash'])
            if not result['blockers']:
                break
            removed = set()
            for blocker in result['blockers']:
                affected = {blocker['id']} if blocker.get('id') in candidates else set(candidates)
                for rid in affected:
                    preserved.setdefault(rid, []).append(blocker['message'])
                removed.update(affected)
            candidates.difference_update(removed)
        else:
            result, rows = self._inspect(conn, cid, req | {'scope': 'company_selection', 'ids': []})
        result['scope'] = 'company'
        result['total_count'] = len(all_rows)
        result['preserved_count'] = len(preserved)
        result['preserved_rows'] = [{'id': r['id'], 'period': r['period'], 'reasons': preserved[r['id']]}
                                    for r in all_rows if r['id'] in preserved]
        # Include preserved state too: new movements and changed locks/dependencies
        # always require a new preview, even if the eligible count is unchanged.
        result['preview_hash'] = digest({'request': req, 'all_rows': all_rows,
                                        'inspections': inspections, 'result': result})
        if preserved:
            result['warnings'].append(f"{len(preserved)} movimento(s) preservado(s) por períodos fechados ou dependências. Somente os elegíveis serão excluídos.")
        return result, rows

    def _inspect(self, conn, cid, req, selected_documents=()):
        if req.get('scope') == 'company':
            return self._inspect_company(conn, cid, req)
        kind, action, ids = req['kind'], req['action'], req['ids']
        module = 'fiscal' if kind == 'documents' else 'accounting'
        marks = 'SELECT value FROM json_each(?)'
        rows = [dict(r) for r in conn.execute(f'SELECT * FROM {kind} WHERE company_id=? AND id IN ({marks}) ORDER BY id', (cid, pack(ids)))]
        original_ids = list(ids)
        original_id_set = set(ids)
        selection_complete = len(rows) == len(ids)
        if selection_complete and kind == 'journals' and req.get('include_reversal_pairs') and (req.get('scope') != 'company_selection' or selected_documents):
            rows = self._reversal_closure(conn, cid, rows)
            ids = [row['id'] for row in rows]
            marks = 'SELECT value FROM json_each(?)'
        effective_id_set = set(ids)
        blockers, children, linked_preview = [], {}, None
        def block(code, message, item_id=None):
            blockers.append({'code': code, 'message': message, 'id': item_id})
        if not ids:
            block('empty_selection', 'Não há movimentos para limpar neste módulo e empresa.')
        if not selection_complete:
            block('selection_missing', 'Há registros inexistentes ou fora da empresa; nenhuma linha será alterada.')
        affected_periods = sorted({row['period'] for row in rows} | ({req['period']} if req.get('scope') != 'company_selection' else set()))
        for competence in affected_periods:
            try:
                ensure_open(conn, cid, competence, module)
                if kind == 'documents':
                    ensure_unfinalized(conn, cid, competence)
            except DomainError as exc:
                for row in rows:
                    if row['period'] == competence:
                        block(exc.code, exc.detail + ' Reabra a competência ou reverta a finalização antes de continuar.', row['id'])
        for row in rows:
            rid = row['id']
            if row['period'] != req['period'] and row['id'] in original_id_set and not selected_documents and req.get('scope') != 'company_selection':
                block('period_mismatch', 'Registro fora da competência explicitamente selecionada.', rid)
            if kind == 'documents':
                if row['journal_id'] and action != 'review' and not req.get('include_linked_journals'):
                    block('linked_journal', f"Documento vinculado ao lançamento #{row['journal_id']}; esta operação não remove efeitos contábeis implicitamente.", rid)
                if action == 'review':
                    pending = json.loads(row['extra_json']).get('import_posting', {}).get('review_pending')
                    if row['status'] != 'pending' and not (row['status'] == 'booked' and pending):
                        block('invalid_status', 'Somente pendente ou escrituração importada aguardando conferência pode ser conferido.', rid)
                if action == 'book':
                    if row['status'] != 'reviewed':
                        block('invalid_status', 'Confira o documento antes de escriturá-lo.', rid)
                    try:
                        doc = self.core._document(conn, cid, rid)
                        self.core._validate_document_links(conn, cid, doc)
                        if doc['model'] in {'55', '65', '57'}:
                            classifications = doc['items'] if doc['items'] and doc['model'] in {'55', '65'} else doc.get('analytics', [])
                            if (classifications and any(not isinstance(i, dict) or not re.fullmatch(r'\d{4}', str(i.get('cfop', ''))) for i in classifications)) or (not classifications and not doc['cfop']):
                                raise DomainError('Confira o CFOP em cada item/registro analítico.', 409, 'cfop_required')
                    except DomainError as exc:
                        block(exc.code, exc.detail, rid)
                if action == 'update':
                    if row['status'] == 'booked' or json.loads(row['items_json']) or json.loads(row['extra_json']).get('analytics'):
                        block('unsafe_cfop_update', 'CFOP em lote restrito a documentos não escriturados sem itens/analíticos. Use a edição detalhada para manter as classificações consistentes.', rid)
                    try:
                        doc = self.core._document(conn, cid, rid) | req['changes']
                        self.core._validate_document_links(conn, cid, doc)
                        self.core._validate_posted_classification(conn, cid, doc)
                    except DomainError as exc:
                        block(exc.code, exc.detail, rid)
            elif action == 'delete':
                for field in ('reversal_of', 'reversed_by'):
                    if row[field] and row[field] not in effective_id_set:
                        block('reversal_set_required', f"Selecione também o lançamento vinculado #{row[field]} ou marque a inclusão explícita da cadeia de estornos, conferindo todos os períodos.", rid)
        if action == 'delete' and selection_complete:
            # Enumerate actual FKs, including new migrations: unknown dependencies fail closed.
            owned = ('document_sources', 'document_id') if kind == 'documents' else ('journal_lines', 'journal_id')
            children[owned[0]] = [dict(r) for r in conn.execute(f'SELECT * FROM {owned[0]} WHERE {owned[1]} IN ({marks}) ORDER BY id', (pack(ids),))]
            for table_row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                table = table_row[0]
                safe_table = '"' + table.replace('"', '""') + '"'
                for fk in conn.execute(f'PRAGMA foreign_key_list({safe_table})'):
                    if fk['table'] != kind or fk['to'] != 'id' or table == owned[0]:
                        continue
                    field = '"' + fk['from'].replace('"', '""') + '"'
                    references = list(conn.execute(f'SELECT rowid AS ref_id, {field} AS target_id FROM {safe_table} WHERE {field} IN ({marks})', (pack(ids),)))
                    if table == 'documents' and kind == 'journals' and selected_documents:
                        references = [r for r in references if r['ref_id'] not in selected_documents]
                    if table == 'journals' and kind == 'journals':
                        references = [r for r in references if r['ref_id'] not in effective_id_set]
                    if references:
                        for target_id in sorted({r['target_id'] for r in references}):
                            block('dependent_records', f"{table}.{fk['from']}: {len(references)} dependência(s), IDs {', '.join(str(r['ref_id']) for r in references[:10])}. Resolva explicitamente; não serão apagadas implicitamente.", target_id)
        linked_ids = sorted({r['journal_id'] for r in rows if kind == 'documents' and r['journal_id']}) if req.get('include_linked_journals') else []
        if linked_ids:
            linked_req = {'scope': req.get('scope', 'selection'), 'kind': 'journals', 'action': 'delete', 'ids': linked_ids, 'period': req['period'], 'changes': {}, 'include_reversal_pairs': req.get('include_reversal_pairs', False)}
            linked_preview, linked_rows = self._inspect(conn, cid, linked_req, ids)
            # Map linked blockers to their complete reversal component, keeping
            # unrelated, eligible linked documents available for cleanup.
            parents = {row['id']: row['id'] for row in linked_rows}
            def root(rid):
                while parents[rid] != rid:
                    parents[rid] = parents[parents[rid]]
                    rid = parents[rid]
                return rid
            for row in linked_rows:
                for field in ('reversal_of', 'reversed_by'):
                    if row[field] in parents:
                        parents[root(row['id'])] = root(row[field])
            component_documents = {}
            for row in rows:
                if row['journal_id'] in parents:
                    component_documents.setdefault(root(row['journal_id']), []).append(row['id'])
            for blocker in linked_preview['blockers']:
                affected = component_documents.get(root(blocker['id']), []) if blocker.get('id') in parents else [row['id'] for row in rows if row['journal_id']]
                for rid in affected:
                    block(blocker['code'], blocker['message'], rid)
            children['linked_journals'] = linked_rows
            linked_ids = [row['id'] for row in linked_rows]
            affected_periods = sorted(set(affected_periods) | set(linked_preview['affected_periods']))
        affected = {kind: len(rows)}
        affected.update({table: len(values) for table, values in children.items()})
        if linked_preview:
            affected.pop('linked_journals', None)
            affected.update(linked_preview['affected_counts'])
        warnings = ['Exclusão física dos movimentos e filhos exclusivos, sem apagamento seguro de discos, WAL ou backups.'] if action == 'delete' else []
        retained = {}
        if action == 'delete':
            for table in ('imports', 'module_imports', 'tax_assessments', 'tax_ledgers', 'export_batches', 'auditor_jobs', 'stored_files', 'operations', 'audit'):
                retained[table] = conn.execute(f'SELECT count(*) FROM {table} WHERE company_id=?', (cid,)).fetchone()[0]
            warnings.append('Lotes antigos e chaves de operações afetadas deixam de poder ser reutilizados; originais e evidências permanecem.')
            warnings.append('Originais/importações, snapshots de apuração e Auditor, exportações, operações históricas, trilha de auditoria e arquivos compartilhados/materializados permanecem. São evidências históricas, não movimentos ativos; cópias exportadas e backups não são alterados.')
        if action == 'book':
            warnings.append('Escrituração exclusivamente fiscal: não gera lançamentos, títulos ou parcelas.')
        fingerprint = digest({'request': req, 'rows': rows, 'children': children, 'blockers': blockers, 'retained': retained, 'linked_preview': linked_preview})
        if linked_preview:
            warnings.append(f"Inclui explicitamente {len(linked_ids)} lançamento(s) contábil(is): {', '.join(map(str, linked_ids))}.")
        phrase = f"EXCLUIR DEFINITIVAMENTE {len(original_ids)} REGISTROS DA EMPRESA {cid} EM {req['period']}" if action == 'delete' else f"CONFIRMAR {len(original_ids)} REGISTROS DA EMPRESA {cid} EM {req['period']}"
        if linked_ids:
            phrase += f' E {len(linked_ids)} LANCAMENTOS CONTABEIS'
        if req.get('include_reversal_pairs'):
            phrase += f"; TOTAL CONTABIL {affected.get('journals', 0)} EM {', '.join(affected_periods)}"
            warnings.append('A inclusão explícita cobre a cadeia de estornos listada, inclusive competências e exercícios diferentes; todos devem estar abertos.')
        return {'preview_hash': fingerprint, 'effective_ids': ids, 'affected_periods': affected_periods, 'linked_journal_ids': linked_ids, **{k: req[k] for k in ('kind', 'action', 'period')}, 'scope': req.get('scope', 'selection'), 'selected_count': len(original_ids), 'affected_counts': affected, 'retained_counts': retained, 'blockers': blockers, 'warnings': warnings, 'rows': [{k: r[k] for k in ('id', 'number', 'period') if k in r} for r in rows[:100]], 'can_confirm': not blockers, 'confirmation_phrase': phrase}, rows

    @staticmethod
    def _operation_mentions(op, kind, ids):
        if kind == 'documents' and any(op['scope'] == f'{prefix}:{i}' for prefix in ('book-document', 'reverse-document') for i in ids):
            return True
        def walk(value, context=''):
            if isinstance(value, list):
                return any(walk(v, context) for v in value)
            if not isinstance(value, dict):
                return False
            if context in ({'document', 'documents'} if kind == 'documents' else {'journal', 'journals'}) and value.get('id') in ids:
                return True
            field = 'document_id' if kind == 'documents' else 'journal_id'
            if value.get(field) in ids or (kind == 'journals' and value.get('reversal_journal_id') in ids):
                return True
            return any(walk(v, k) for k, v in value.items())
        value = json.loads(op['result_json'])
        return walk(value, 'document' if kind == 'documents' and op['scope'] == 'manual-document' else '')

    def preview(self, cid, payload, uid, actor):
        req = normalize(payload)
        with self.db.transaction() as conn:
            self._authorize(conn, cid, uid, req)
            result, _ = self._inspect(conn, cid, req)
            nonce, expires = secrets.token_urlsafe(32), time.time() + 900
            conn.execute('INSERT INTO bulk_previews(id,company_id,user_id,token_hash,request_json,preview_hash,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?)', (nonce, cid, uid, (request_context.get() or {}).get('token_hash', ''), pack(req), result['preview_hash'], expires, time.time()))
            return result | {'id': nonce, 'expires_at': expires}

    def confirm(self, cid, payload, uid, actor):
        if set(payload) - {'preview_id', 'preview_hash', 'reason', 'confirmation_phrase', 'irreversible_acknowledged'}:
            raise DomainError('A confirmação não pode alterar a seleção ou os campos da prévia.')
        for field in ('preview_id', 'preview_hash'):
            utf8_text(payload.get(field), field, True, 10000 if field == 'confirmation_phrase' else 300)
        if 'confirmation_phrase' in payload:
            utf8_text(payload['confirmation_phrase'], 'confirmation_phrase', False, 10000)
        if 'irreversible_acknowledged' in payload and type(payload['irreversible_acknowledged']) is not bool:
            raise DomainError('O reconhecimento de irreversibilidade deve ser booleano.')
        reason = utf8_text(payload.get('reason'), 'Justificativa', False, 1000) or 'Operação em lote confirmada pelo usuário.'
        with self.db.transaction() as conn:
            saved = conn.execute('SELECT * FROM bulk_previews WHERE id=? AND company_id=? AND user_id=?', (payload.get('preview_id'), cid, uid)).fetchone()
            if not saved:
                raise DomainError('Prévia não encontrada para este usuário e empresa.', 404, 'preview_missing')
            if saved['token_hash'] != (request_context.get() or {}).get('token_hash', ''):
                raise DomainError('Prévia pertence a outra sessão. Gere uma nova.', 409, 'preview_session_mismatch')
            req = json.loads(saved['request_json'])
            self._authorize(conn, cid, uid, req)
            if payload.get('preview_hash') != saved['preview_hash']:
                raise DomainError('Hash da prévia divergente.', 409, 'stale_preview')
            confirmation_hash = digest(payload)
            if saved['result_json']:
                if saved['confirmation_hash'] != confirmation_hash:
                    raise DomainError('Esta prévia já foi usada com outra confirmação.', 409, 'idempotency_conflict')
                return json.loads(saved['result_json']) | {'duplicate': True}
            if saved['expires_at'] <= time.time():
                raise DomainError('Prévia expirada. Gere outra antes de confirmar.', 409, 'preview_expired')
            result, rows = self._inspect(conn, cid, req)
            if result['blockers']:
                raise DomainError(result['blockers'][0]['message'], 409, result['blockers'][0]['code'])
            if result['preview_hash'] != saved['preview_hash']:
                raise DomainError('Registros ou dependências mudaram. Gere e confira outra prévia.', 409, 'stale_preview')
            if req['action'] == 'delete' and payload.get('irreversible_acknowledged') is not True:
                raise DomainError('Confirme a exclusão irreversível dos movimentos apresentados na prévia.', 400, 'confirmation_required')
            # All rows and dependencies validated under BEGIN IMMEDIATE before first mutation.
            effective_req = req | {'ids': result['effective_ids'], 'linked_journal_ids': result['linked_journal_ids']}
            if req['action'] == 'delete':
                self._invalidate_replays(conn, cid, effective_req, rows, saved['id'])
            self._apply(conn, cid, effective_req, rows, actor, reason)
            if conn.execute('PRAGMA foreign_key_check').fetchone():
                raise DomainError('Integridade referencial inválida; lote revertido.', 409, 'foreign_key_integrity')
            outcome = {'id': saved['id'], 'kind': req['kind'], 'action': req['action'], 'period': req['period'], 'scope': req.get('scope', 'selection'), 'selected_count': result['selected_count'], 'affected_periods': result['affected_periods'], 'affected_counts': result['affected_counts'], 'warnings': result['warnings'], 'preserved_count': result.get('preserved_count', 0), 'preserved_rows': result.get('preserved_rows', []), 'completed': True, 'duplicate': False}
            audit(conn, cid, actor, 'bulk-' + req['action'], req['kind'], saved['id'], {'scope': req.get('scope', 'selection'), 'ids': result['effective_ids'], 'effective_ids': result['effective_ids'], 'linked_journal_ids': result['linked_journal_ids'], 'affected_periods': result['affected_periods'], 'reason': reason, 'preview_hash': saved['preview_hash'], 'affected_counts': result['affected_counts'], 'changes': req['changes'], 'irreversible_acknowledged': req['action'] == 'delete'})
            conn.execute('UPDATE bulk_previews SET result_json=?,confirmation_hash=? WHERE id=?', (pack(outcome), confirmation_hash, saved['id']))
            return outcome

    def _invalidate_replays(self, conn, cid, req, rows, preview_id):
        movements = {req['kind']: set(req['ids'])}
        if req.get('include_linked_journals'):
            movements['journals'] = set(req['linked_journal_ids'])
        deleted = [{'kind': kind, 'id': rid} for kind, ids in movements.items() for rid in sorted(ids)]
        for kind, ids in movements.items():
            for rid in ids:
                key = conn.execute('SELECT idempotency_key FROM journals WHERE id=? AND company_id=?', (rid, cid)).fetchone()[0] if kind == 'journals' else None
                conn.execute('INSERT INTO bulk_deleted_movements(kind,record_id,company_id,idempotency_key,deleted_at) VALUES(?,?,?,?,?)', (kind, rid, cid, key, now()))
        def mark(value):
            previous = value.get('deleted_movements', [])
            return value | {'movement_deleted': True, 'deleted_movements': previous + [r for r in deleted if r not in previous], 'deleted_by_bulk_id': preview_id}
        for op in conn.execute('SELECT * FROM operations WHERE company_id=?', (cid,)).fetchall():
            if any(self._operation_mentions(op, kind, ids) for kind, ids in movements.items()):
                conn.execute('UPDATE operations SET result_json=? WHERE company_id=? AND scope=? AND key=?', (pack(mark(json.loads(op['result_json']))), cid, op['scope'], op['key']))
        for batch in conn.execute('SELECT id,confirmation_json FROM imports WHERE company_id=? AND confirmation_json IS NOT NULL', (cid,)).fetchall():
            result = json.loads(batch['confirmation_json'])
            if set(result.get('document_ids', [])) & movements.get('documents', set()):
                conn.execute('UPDATE imports SET confirmation_json=? WHERE id=?', (pack(mark(result)), batch['id']))
        for batch in conn.execute('SELECT id,layout,result_json FROM module_imports WHERE company_id=? AND result_json IS NOT NULL', (cid,)).fetchall():
            result = json.loads(batch['result_json'])
            if batch['layout'] in {'journals-v1', 'openings-v1'} and {r['id'] for r in result.get('written', [])} & movements.get('journals', set()):
                conn.execute('UPDATE module_imports SET result_json=? WHERE id=?', (pack(mark(result)), batch['id']))

    def _apply(self, conn, cid, req, rows, actor, reason):
        kind, action, ids = req['kind'], req['action'], req['ids']
        marks = 'SELECT value FROM json_each(?)'
        if action == 'delete':
            table, fk = ('document_sources', 'document_id') if kind == 'documents' else ('journal_lines', 'journal_id')
            conn.execute(f'DELETE FROM {table} WHERE {fk} IN ({marks})', (pack(ids),))
            if kind == 'journals':
                conn.execute(f'UPDATE journals SET reversal_of=NULL,reversed_by=NULL WHERE company_id=? AND id IN ({marks})', (cid, pack(ids)))
            conn.execute(f'DELETE FROM {kind} WHERE company_id=? AND id IN ({marks})', (cid, pack(ids)))
            linked_ids = req.get('linked_journal_ids', []) if kind == 'documents' else []
            if linked_ids:
                self._apply(conn, cid, {'kind': 'journals', 'action': 'delete', 'ids': linked_ids}, [], actor, reason)
            return
        for row in rows:
            rid = row['id']
            if action == 'book':
                # Existing business helper, no model/lines/generate_titles options accepted.
                self.core._book_document(conn, cid, rid, {'version': row['version'], 'reason': reason}, actor)
            elif action == 'review':
                if row['status'] == 'booked':
                    extra = json.loads(row['extra_json'])
                    extra['import_posting']['review_pending'] = False
                    conn.execute('UPDATE documents SET extra_json=?,reviewed_by=?,review_reason=?,version=version+1 WHERE id=? AND company_id=?', (pack(extra), actor, reason, rid, cid))
                else:
                    conn.execute("UPDATE documents SET status='reviewed',reviewed_by=?,review_reason=?,version=version+1 WHERE id=? AND company_id=?", (actor, reason, rid, cid))
            elif kind == 'journals':
                conn.execute('UPDATE journals SET ' + ','.join(k + '=?' for k in req['changes']) + ' WHERE id=? AND company_id=?', (*req['changes'].values(), rid, cid))
            else:
                # Header-only CFOP edit invalidates review, preserving values and identity.
                from .core import semantic_value
                values = {k: row[k] for k in ('direction', 'number', 'series', 'model', 'partner_name', 'partner_tax_id', 'key', 'cfop', 'issue_date', 'posting_date', 'total_cents')}
                values.update(req['changes'])
                hashed = digest(values | {'taxes': json.loads(row['taxes_json']), 'items': semantic_value(json.loads(row['items_json']))})
                conn.execute("UPDATE documents SET cfop=?,payload_hash=?,status='pending',reviewed_by=NULL,review_reason=NULL,version=version+1 WHERE id=? AND company_id=?", (req['changes']['cfop'], hashed, rid, cid))
            if action in {'review', 'update'}:
                fields = list(req['changes']) if action == 'update' else ['status', 'reviewed_by', 'review_reason']
                if kind == 'documents' and action == 'update':
                    fields += ['status', 'reviewed_by', 'review_reason']
                current = dict(conn.execute(f'SELECT * FROM {kind} WHERE company_id=? AND id=?', (cid, rid)).fetchone())
                before = {field: row[field] for field in fields if row[field] != current[field]}
                after = {field: current[field] for field in before}
                if action == 'review' and row['status'] == 'booked':
                    before['import_posting.review_pending'] = True
                    after['import_posting.review_pending'] = False
                details = {'reason': reason, 'before': before, 'after': after, 'bulk': True}
                if 'version' in row:
                    details['previous_version'] = row['version']
                audit(conn, cid, actor, action, 'document' if kind == 'documents' else 'journal', rid, details)

