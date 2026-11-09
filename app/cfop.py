"""CFOP wording reference and explicit company import mappings."""
from functools import lru_cache
import json
from pathlib import Path
import re

from .core import DomainError, audit, boolean, check_version, company_row, digest, integer, iso_date, now, pack, select_one, text
from .permissions import effect

MAPPING_KIND = 'fiscal_import_cfop'


@lru_cache(maxsize=1)
def reference():
    return json.loads((Path(__file__).parent / 'data/cfop-confaz-20261109.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def reference_index():
    result = {}
    for row in reference()['entries']: result.setdefault(row['code'], []).append(row)
    return result


def cfop_at(code, day, direction=None):
    code = text(code, 'CFOP de escrituração', True, 4)
    day = iso_date(day)
    rows = [r for r in reference_index().get(code, []) if r['wording_valid_from'] <= day and (not r['wording_valid_to'] or day <= r['wording_valid_to'])]
    if len(rows) != 1:
        raise DomainError(f'CFOP {code}: não há uma redação única na fonte para {day}. Confira a tabela e o período.', 409, 'cfop_reference_missing')
    row = rows[0]
    if direction and row['direction'] != direction:
        raise DomainError(f'CFOP {code} incompatível com entrada/saída da empresa.', 409, 'cfop_direction')
    return row


def mapping_key(direction, model, source):
    return f'{direction}:{model}:{source}'


def company_cfop_at(code, day, direction, catalogs):
    row = cfop_at(code, day, direction)
    local = catalogs.get(code)
    if local and (not local['active'] or local['direction'] not in {'both', direction} or (local['valid_from'] and day < local['valid_from']) or (local['valid_to'] and day > local['valid_to'])):
        raise DomainError(f'CFOP {code} inativo ou fora dos parâmetros desta empresa na data informada.', 409, 'company_cfop_unavailable')
    return row


class CfopMixin:
    def _company_cfop_catalogs(self, conn, cid):
        return {r['code']: dict(r) for r in conn.execute("SELECT * FROM catalogs WHERE company_id=? AND kind='cfop'", (cid,))}

    def cfop_reference(self, cid, search='', direction='', day='', page=1):
        with self.db.read() as conn:
            company_row(conn, cid)
            custom = {r['code']: dict(r) for r in conn.execute("SELECT * FROM catalogs WHERE company_id=? AND kind='cfop'", (cid,))}
        source = reference()
        day = iso_date(day) if day else '2026-11-09'
        page = integer(page, 'Página')
        if direction not in {'', 'incoming', 'outgoing'}: raise DomainError('Sentido de CFOP inválido.')
        query = search.casefold().strip()
        records = [r | {'company_catalog': custom.get(r['code'])} for r in source['entries']
                   if r['wording_valid_from'] <= day and (not r['wording_valid_to'] or day <= r['wording_valid_to'])
                   and (not direction or r['direction'] == direction)
                   and (not query or query in (r['code'] + ' ' + r['title'] + ' ' + r['note']).casefold())]
        records.sort(key=lambda r: r['code'])
        return {k: source[k] for k in ('edition', 'source', 'retrieved_on', 'source_text_sha256', 'scope', 'code_count', 'wording_count')} | {
            'date': day, 'total': len(records), 'page': page, 'per_page': 50, 'rows': records[(page-1)*50:page*50]}

    def apply_cfop_reference(self, cid, payload, actor):
        reason = text(payload.get('reason'), 'Motivo da importação da tabela', True, 1000)
        source = reference()
        if payload.get('edition') != source['edition']: raise DomainError('A referência mudou. Reabra a tabela.', 409, 'stale_reference')
        day = iso_date(payload.get('date'))
        with self.db.transaction() as conn:
            company_row(conn, cid); effect(conn, cid, 'fiscal.masters', 'create')
            created = preserved = 0
            for row in source['entries']:
                if row['wording_valid_from'] > day or (row['wording_valid_to'] and day > row['wording_valid_to']): continue
                if conn.execute("SELECT 1 FROM catalogs WHERE company_id=? AND kind='cfop' AND code=?", (cid, row['code'])).fetchone():
                    preserved += 1
                    continue
                conn.execute('INSERT INTO catalogs(company_id,kind,code,description,direction,valid_from,valid_to,source,active) VALUES(?,?,?,?,?,?,?,?,1)',
                             (cid, 'cfop', row['code'], row['title'], row['direction'], row['wording_valid_from'], row['wording_valid_to'], source['source'] + ' · ' + source['edition']))
                created += 1
            audit(conn, cid, actor, 'import-reference', 'cfop_catalog', source['edition'], {'reason': reason, 'date': day, 'created': created, 'preserved': preserved, 'source_text_sha256': source['source_text_sha256']})
            return {'created': created, 'preserved': preserved, 'edition': source['edition']}

    def import_cfop_mappings(self, cid, conn=None):
        if conn is None:
            with self.db.read() as connection: return self.import_cfop_mappings(cid, connection)
        company_row(conn, cid)
        return [dict(r) | {'data': json.loads(r['data_json']), 'active': bool(r['active'])}
                for r in conn.execute('SELECT * FROM masters WHERE company_id=? AND kind=? ORDER BY code', (cid, MAPPING_KIND))]

    def save_import_cfop_mapping(self, cid, payload, actor, item_id=None):
        direction = payload.get('direction')
        if not isinstance(direction, str) or direction not in {'incoming', 'outgoing'}: raise DomainError('Escolha entrada ou saída.')
        model = text(payload.get('model', ''), 'Modelo', False, 10)
        if model not in {'', '55', '65', '57', 'NFSE', '99'}: raise DomainError('Modelo inválido.')
        source = text(payload.get('source_cfop'), 'CFOP da origem', True, 4)
        if not re.fullmatch(r'[123567]\d{3}', source): raise DomainError('CFOP da origem deve ter quatro dígitos.')
        start = iso_date(payload.get('valid_from')); end = iso_date(payload['valid_to']) if payload.get('valid_to') else ''
        if end and end < start: raise DomainError('Fim da vigência anterior ao início.')
        cfop_at(source, start)
        target = cfop_at(payload.get('target_cfop'), start, direction)
        if end: cfop_at(payload.get('target_cfop'), end, direction)
        reason = text(payload.get('reason'), 'Fundamento da associação', True, 1000)
        responsible = text(payload.get('responsible'), 'Responsável pela associação', True, 200)
        values = {'direction': direction, 'model': model, 'source_cfop': source, 'target_cfop': target['code'], 'valid_from': start, 'valid_to': end, 'reason': reason, 'responsible': responsible, 'reference_edition': reference()['edition']}
        code = mapping_key(direction, model, source) + ':' + start
        with self.db.transaction() as conn:
            company_row(conn, cid)
            effect(conn, cid, 'fiscal.parameters', 'edit' if item_id else 'create')
            old = select_one(conn, 'masters', cid, item_id) if item_id else None
            if old:
                if old['kind'] != MAPPING_KIND: raise DomainError('Associação fiscal não localizada.', 404)
                check_version(old, payload)
            active = boolean(payload.get('active'), True)
            for other in self.import_cfop_mappings(cid, conn):
                d = other['data']
                if other['id'] != item_id and active and other['active'] and (d['direction'], d['model'], d['source_cfop']) == (direction, model, source) and start <= (d['valid_to'] or '9999-12-31') and d['valid_from'] <= (end or '9999-12-31'):
                    raise DomainError('Já existe associação ativa com vigência sobreposta.', 409, 'mapping_overlap')
            if old:
                conn.execute('UPDATE masters SET code=?,name=?,data_json=?,active=?,version=version+1,updated_at=? WHERE id=? AND company_id=?', (code, source + ' → ' + target['code'], pack(values), active, now(), item_id, cid))
            else:
                item_id = conn.execute("INSERT INTO masters(company_id,kind,code,name,data_json,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (cid, MAPPING_KIND, code, source + ' → ' + target['code'], pack(values), active, now(), now())).lastrowid
            audit(conn, cid, actor, 'update' if old else 'create', 'fiscal_import_cfop', item_id, {'before': old, 'after': values, 'active': active})
            return next(r for r in self.import_cfop_mappings(cid, conn) if r['id'] == item_id)
