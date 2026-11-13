"""Shared tax identity, company-owned registrations and explicit audited reuse.

Global rows contain identifiers only. A matching CPF/CNPJ never grants access to
another company's master, contacts, roles, documents, or registrations.
"""
import json

from .cadastros import tax_identity
from .core import (DomainError, audit, check_version, company_row, digest, integer,
                   now, pack, select_one, text)
from .permissions import effect

PARTY_KINDS = {'participant', 'establishment'}
# Deliberately exclude contacts, notes, roles, tax/accounting defaults and payment terms.
REUSABLE_FIELDS = frozenset({'name', 'trade_name', 'address', 'number', 'district',
                            'city', 'state', 'postal_code', 'ibge', 'im', 'cnae',
                            'state_registrations'})
UFS = set('AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO'.split())


def registration_values(rows):
    if not isinstance(rows, list) or len(rows) > 100:
        raise DomainError('Informe até 100 inscrições estaduais.')
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise DomainError('Inscrição estadual inválida.')
        uf = text(row.get('state'), 'UF da IE', True, 2).upper()
        if uf not in UFS:
            raise DomainError('UF da inscrição estadual inválida.')
        number = text(row.get('number'), 'Inscrição estadual', False, 30)
        status = text(row.get('status'), 'Situação da IE', False, 100)
        # Missing status stays absent, not "exempt" or "active".
        if not number and status not in {'exempt', 'not_applicable', 'not_found'}:
            raise DomainError('Informe a IE ou uma situação explícita sem inscrição.')
        active = row.get('active')
        if active is not None and not isinstance(active, bool):
            raise DomainError('Atividade da IE deve ser verdadeira, falsa ou não informada.')
        key = (uf, number, status)
        if key in seen:
            raise DomainError('Inscrição estadual repetida.')
        seen.add(key)
        result.append({'state': uf, 'number': number, 'status': status, 'active': active,
                       'source': text(row.get('source'), 'Fonte da IE', False, 100),
                       'updated_at': text(row.get('updated_at'), 'Atualização da IE', False, 100)})
    return result


def _snapshot(row):
    return {k: row[k] for k in ('id', 'company_id', 'kind', 'code', 'name', 'tax_id', 'active', 'version')} | {
        'data': json.loads(row['data_json'])}


def sync_third_party(conn, cid, master_id, actor, reason):
    """Called in the existing master/import transaction; never rewrites the master.

    Empty/invalid legacy identifiers remain local and untouched. Valid identifiers
    share an immutable identity; local data and audit history remain company-owned.
    """
    row = select_one(conn, 'masters', cid, master_id)
    if row['kind'] not in PARTY_KINDS:
        return
    try:
        tax_id = tax_identity(row['tax_id'])
    except DomainError:
        tax_id = ''
    pid, establishment_id = None, None
    if tax_id:
        kind, key = ('organization', tax_id[:8]) if len(tax_id) == 14 else ('person', tax_id)
        conn.execute('INSERT OR IGNORE INTO third_parties(entity_type,identity_key) VALUES(?,?)', (kind, key))
        pid = conn.execute('SELECT id FROM third_parties WHERE entity_type=? AND identity_key=?', (kind, key)).fetchone()['id']
        if kind == 'organization':
            conn.execute('INSERT OR IGNORE INTO third_party_establishments(third_party_id,tax_id) VALUES(?,?)', (pid, tax_id))
            establishment_id = conn.execute('SELECT id FROM third_party_establishments WHERE tax_id=?', (tax_id,)).fetchone()['id']
    old = conn.execute('SELECT * FROM third_party_company_links WHERE company_id=? AND master_id=?', (cid, master_id)).fetchone()
    snapshot = _snapshot(row)
    if old and (old['third_party_id'] != pid or old['establishment_id'] != establishment_id):
        raise DomainError('Identidade preservada. Crie o cadastro correto e registre a substituição auditada.', 409, 'immutable_identity')
    last = conn.execute("SELECT details_json FROM third_party_history WHERE company_id=? AND master_id=? AND event IN ('link','update','local') ORDER BY id DESC LIMIT 1", (cid, master_id)).fetchone()
    before = json.loads(last['details_json']).get('after') if last else None
    if before == snapshot:
        return
    stamp = now()
    if pid is not None:
        conn.execute('''INSERT INTO third_party_company_links(company_id,master_id,third_party_id,establishment_id,snapshot_json,updated_at)
            VALUES(?,?,?,?,?,?) ON CONFLICT(company_id,master_id) DO UPDATE SET snapshot_json=excluded.snapshot_json,updated_at=excluded.updated_at''',
            (cid, master_id, pid, establishment_id, pack(snapshot), stamp))
    event = ('update' if before else 'link') if pid is not None else 'local'
    details = {'reason': reason, 'before': before, 'after': snapshot}
    conn.execute('''INSERT INTO third_party_history(company_id,master_id,event,details_json,actor,created_at)
        VALUES(?,?,?,?,?,?)''', (cid, master_id, event, pack(details), actor, stamp))
    audit(conn, cid, actor, event, 'third_party', master_id, details)


def preserved_document_party(conn, cid, master_id, document_id, field='participant_id'):
    """Only internal callers supply document_id; never infer it from a request body.

    The substitution exception preserves an already-stored link, not permission to
    select an inactive master. Ordinary inactive masters remain blocked.
    """
    if document_id is None or field not in {'participant_id', 'establishment_id'}:
        return None
    if not conn.execute('SELECT 1 FROM third_party_replacements WHERE company_id=? AND master_id=?', (cid, master_id)).fetchone():
        return None
    row = select_one(conn, 'documents', cid, integer(document_id, 'Documento de origem'))
    return row if json.loads(row['extra_json']).get(field) == master_id else None


def preserved_title_party(conn, cid, master_id, title_ids):
    """Validated originals of an internal renegotiation, reread in its transaction."""
    if not title_ids or not conn.execute('SELECT 1 FROM third_party_replacements WHERE company_id=? AND master_id=?', (cid, master_id)).fetchone():
        return None
    originals = [select_one(conn, 'titles', cid, integer(tid, 'Título de origem')) for tid in title_ids]
    if any(row['participant_id'] != master_id for row in originals):
        return None
    return originals[0]


class ThirdPartiesMixin:
    def _third_party(self, conn, cid, master_id):
        row = select_one(conn, 'masters', cid, master_id)
        if row['kind'] not in PARTY_KINDS:
            raise DomainError('Cadastro de terceiro não encontrado.', 404, 'not_found')
        result = self._master(conn, cid, master_id)
        link = conn.execute('''SELECT p.entity_type,p.identity_key,e.tax_id FROM third_party_company_links l
            JOIN third_parties p ON p.id=l.third_party_id
            LEFT JOIN third_party_establishments e ON e.id=l.establishment_id
            WHERE l.company_id=? AND l.master_id=?''', (cid, master_id)).fetchone()
        # No global IDs, relationship counts or other-company metadata in API output.
        result['identity'] = dict(link) if link else None
        result['replacement_master_id'] = None
        replacement = conn.execute('SELECT replacement_master_id FROM third_party_replacements WHERE company_id=? AND master_id=?', (cid, master_id)).fetchone()
        if replacement:
            result['replacement_master_id'] = replacement['replacement_master_id']
        return result

    def third_parties(self, cid):
        with self.db.read() as conn:
            company_row(conn, cid)
            effect(conn, cid, 'fiscal.masters', 'read')
            return [self._third_party(conn, cid, r['id']) for r in conn.execute(
                "SELECT id FROM masters WHERE company_id=? AND kind IN ('participant','establishment') ORDER BY code,id", (cid,))]

    def third_party(self, cid, master_id):
        with self.db.read() as conn:
            effect(conn, cid, 'fiscal.masters', 'read')
            return self._third_party(conn, cid, master_id)

    def third_party_history(self, cid, master_id):
        with self.db.read() as conn:
            effect(conn, cid, 'fiscal.masters', 'read')
            self._third_party(conn, cid, master_id)
            return [{k: r[k] for k in ('id', 'event', 'actor', 'created_at')} | {'details': json.loads(r['details_json'])} for r in conn.execute(
                'SELECT id,event,details_json,actor,created_at FROM third_party_history WHERE company_id=? AND master_id=? ORDER BY id', (cid, master_id))]

    def save_third_party_registrations(self, cid, master_id, payload, actor):
        rows = registration_values(payload.get('state_registrations'))
        reason = text(payload.get('reason'), 'Motivo da revisão', True, 1000)
        with self.db.transaction() as conn:
            effect(conn, cid, 'fiscal.masters', 'edit')
            master = self._third_party(conn, cid, master_id)
            check_version(master, payload)
            data = master['data']
            data.setdefault('profile', {})['state_registrations'] = rows
            conn.execute('UPDATE masters SET data_json=?,version=version+1,updated_at=? WHERE company_id=? AND id=?', (pack(data), now(), cid, master_id))
            sync_third_party(conn, cid, master_id, actor, reason)
            return self._third_party(conn, cid, master_id)

    def _reuse_preview(self, conn, cid, master_id, payload):
        source_cid = integer(payload.get('source_company_id'), 'Empresa de origem')
        source_id = integer(payload.get('source_master_id'), 'Cadastro de origem')
        # Permission is checked before reading or even reporting existence of the source.
        effect(conn, cid, 'fiscal.masters', 'read')
        effect(conn, source_cid, 'fiscal.masters', 'read')
        target = self._third_party(conn, cid, master_id)
        source = self._third_party(conn, source_cid, source_id)
        if not target['tax_id'] or target['tax_id'] != source['tax_id']:
            raise DomainError('Reutilização exige o mesmo CPF ou CNPJ completo; raiz não basta.')
        fields = payload.get('fields')
        if not isinstance(fields, list) or not fields or any(not isinstance(f, str) or f not in REUSABLE_FIELDS for f in fields):
            raise DomainError('Selecione somente campos cadastrais reutilizáveis.')
        fields = sorted(set(fields))
        values = {}
        for field in fields:
            if field == 'name':
                values[field] = source['name']
            elif field == 'state_registrations':
                values[field] = registration_values(source['data'].get('profile', {}).get(field, []))
            else:
                values[field] = text(source['data'].get(field), field, False, 500)
        preview = {'source_company_id': source_cid, 'source_master_id': source_id,
                   'source_version': source['version'], 'master_id': master_id,
                   'version': target['version'], 'fields': fields, 'values': values}
        preview['preview_hash'] = digest(preview | {'company_id': cid})
        return preview, target

    def third_party_reuse_preview(self, cid, master_id, payload):
        with self.db.read(snapshot=True) as conn:
            return self._reuse_preview(conn, cid, master_id, payload)[0]

    def reuse_third_party(self, cid, master_id, payload, actor):
        reason = text(payload.get('reason'), 'Motivo da atualização cadastral', True, 1000)
        with self.db.transaction() as conn:
            effect(conn, cid, 'fiscal.masters', 'edit')
            preview, target = self._reuse_preview(conn, cid, master_id, payload)
            check_version(target, payload)
            if payload.get('source_version') != preview['source_version'] or payload.get('preview_hash') != preview['preview_hash']:
                raise DomainError('A origem ou os campos mudaram. Confira uma nova prévia.', 409, 'stale_preview')
            data, name = target['data'], target['name']
            for field, value in preview['values'].items():
                if field == 'name':
                    name = text(value, 'Nome', True, 250)
                elif field == 'state_registrations':
                    data.setdefault('profile', {})[field] = value
                else:
                    data[field] = value
            conn.execute('UPDATE masters SET name=?,data_json=?,version=version+1,updated_at=? WHERE company_id=? AND id=?', (name, pack(data), now(), cid, master_id))
            sync_third_party(conn, cid, master_id, actor, reason)
            # Destination history does not reveal the source company's ID or relations.
            audit(conn, cid, actor, 'reuse', 'third_party', master_id,
                  {'reason': reason, 'fields': preview['fields'], 'source_version': preview['source_version'], 'preview_hash': preview['preview_hash']})
            return self._third_party(conn, cid, master_id)

    def replace_third_party_identity(self, cid, master_id, payload, actor):
        replacement_id = integer(payload.get('replacement_master_id'), 'Cadastro correto')
        reason = text(payload.get('reason'), 'Motivo da correção', True, 1000)
        with self.db.transaction() as conn:
            effect(conn, cid, 'fiscal.masters', 'edit')
            old = self._third_party(conn, cid, master_id)
            replacement = self._third_party(conn, cid, replacement_id)
            check_version(old, payload)
            if old['kind'] != replacement['kind'] or not replacement['active'] or not replacement['identity'] or old['tax_id'] == replacement['tax_id']:
                raise DomainError('Selecione um cadastro ativo do mesmo tipo com a identidade correta e diferente.')
            if old['replacement_master_id'] or replacement['replacement_master_id']:
                raise DomainError('Cadastro já substituído; confira o histórico.', 409, 'already_replaced')
            conn.execute('INSERT INTO third_party_replacements(company_id,master_id,replacement_master_id,reason,actor,created_at) VALUES(?,?,?,?,?,?)', (cid, master_id, replacement_id, reason, actor, now()))
            conn.execute('UPDATE masters SET active=0,version=version+1,updated_at=? WHERE company_id=? AND id=?', (now(), cid, master_id))
            sync_third_party(conn, cid, master_id, actor, reason)
            details = {'reason': reason, 'replacement_master_id': replacement_id, 'preserved_existing_links': True}
            conn.execute('INSERT INTO third_party_history(company_id,master_id,event,details_json,actor,created_at) VALUES(?,?,?,?,?,?)', (cid, master_id, 'replace', pack(details), actor, now()))
            audit(conn, cid, actor, 'replace', 'third_party', master_id, details)
            return self._third_party(conn, cid, master_id)

    def master_movements(self, cid, master_id):
        """Local movement lineage; immutable source details come from each document."""
        with self.db.read(snapshot=True) as conn:
            effect(conn, cid, 'fiscal.masters', 'read')
            effect(conn, cid, 'fiscal.documents', 'read')
            master = self._master(conn, cid, master_id)
            if master['kind'] not in {'product', 'service'}:
                raise DomainError('Selecione um produto ou serviço.')
            rows = []
            for document in conn.execute('SELECT id,number,model,issue_date,posting_date,direction,status,source_hash,items_json FROM documents WHERE company_id=? ORDER BY posting_date,id', (cid,)):
                for position, item in enumerate(json.loads(document['items_json']), 1):
                    if isinstance(item, dict) and item.get('master_id') == master_id:
                        rows.append({k: document[k] for k in ('id', 'number', 'model', 'issue_date', 'posting_date', 'direction', 'status', 'source_hash')} |
                                    {'item_position': position, 'item': item})
            return {'master_id': master_id, 'kind': master['kind'], 'company_id': cid, 'movements': rows}
