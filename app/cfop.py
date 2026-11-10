"""CFOP wording reference and explicit company import mappings."""
from functools import lru_cache
import json
from pathlib import Path
import re

from .core import DomainError, audit, boolean, check_version, company_row, digest, integer, iso_date, now, pack, select_one, text
from .permissions import effect

MAPPING_KIND = 'fiscal_import_cfop'
SETTINGS_KIND = 'fiscal_import_settings'
IMPORT_CATALOG_VERSION = 'purchase-context-2026-11-10-v1'
PURCHASE_DESTINATIONS = {'', 'resale', 'industrialization', 'consumption', 'fixed_asset', 'other'}


def purchase_destination(value):
    if not isinstance(value, str) or value not in PURCHASE_DESTINATIONS:
        raise DomainError('Destinação da compra inválida.')
    return value


def mapping_context(payload):
    destination = purchase_destination(payload.get('purchase_destination', ''))
    ncm = text(payload.get('ncm', ''), 'NCM da regra', False, 8)
    if ncm and not re.fullmatch(r'\d{8}', ncm): raise DomainError('NCM da regra deve ter oito dígitos.')
    product = text(payload.get('product_code', ''), 'Código do produto da regra', False, 100)
    return {'purchase_destination': destination, 'ncm': ncm, 'product_code': product}


def select_import_mapping(saved, doc, item, source, destination):
    matches = []
    for mapping in saved:
        data = mapping['data']
        if not mapping['active'] or data['direction'] != doc['direction'] or data['source_cfop'] != source: continue
        if data['model'] not in {'', doc['model']}: continue
        if not data['valid_from'] <= doc['posting_date'] <= (data['valid_to'] or '9999-12-31'): continue
        if data.get('purchase_destination') and data['purchase_destination'] != destination: continue
        if data.get('ncm') and data['ncm'] != item.get('ncm'): continue
        if data.get('product_code') and data['product_code'] != item.get('code'): continue
        matches.append(mapping)
    if not matches: return None
    # All explicit item/destination constraints outrank a model-only mapping.
    def rank(m):
        d = m['data']
        return (sum(bool(d.get(k)) for k in ('purchase_destination', 'ncm', 'product_code')), bool(d['model']))
    best = max(map(rank, matches))
    matches = [m for m in matches if rank(m) == best]
    if len(matches) != 1:
        raise DomainError(f'CFOP {source}: regras igualmente específicas; revise a ambiguidade.', 409, 'mapping_ambiguous')
    return matches[0]



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


def mapping_warnings(data):
    source = cfop_at(data['source_cfop'], data['valid_from'])['title']
    target = cfop_at(data['target_cfop'], data['valid_from'])['title']
    if any(term in source.casefold() for term in ('devolu', 'remessa', 'transfer', 'bonifica')) and target.casefold().startswith('compra'):
        return [{'code': 'OPERATION_CONTEXT_REVIEW', 'reason': f'Origem “{source}” e destino “{target}” têm naturezas distintas. Revise devolução, remessa, transferência ou bonificação e informe o contexto específico; não é conversão universal de compra.'}]
    return []


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
        return [dict(r) | {'data': json.loads(r['data_json']), 'active': bool(r['active']), 'warnings': mapping_warnings(json.loads(r['data_json']))}
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
        context = mapping_context(payload)
        values = context | {'direction': direction, 'model': model, 'source_cfop': source, 'target_cfop': target['code'], 'valid_from': start, 'valid_to': end, 'reason': reason, 'responsible': responsible, 'reference_edition': reference()['edition']}
        code = mapping_key(direction, model, source) + ':' + start
        if any(context.values()): code += ':' + digest(context)[:16]
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
                if other['id'] != item_id and active and other['active'] and (d['direction'], d['model'], d['source_cfop']) == (direction, model, source) and all(d.get(k, '') == v for k, v in context.items()) and start <= (d['valid_to'] or '9999-12-31') and d['valid_from'] <= (end or '9999-12-31'):
                    raise DomainError('Já existe associação ativa com vigência sobreposta.', 409, 'mapping_overlap')
            if old:
                conn.execute('UPDATE masters SET code=?,name=?,data_json=?,active=?,version=version+1,updated_at=? WHERE id=? AND company_id=?', (code, source + ' → ' + target['code'], pack(values), active, now(), item_id, cid))
            else:
                item_id = conn.execute("INSERT INTO masters(company_id,kind,code,name,data_json,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (cid, MAPPING_KIND, code, source + ' → ' + target['code'], pack(values), active, now(), now())).lastrowid
            audit(conn, cid, actor, 'update' if old else 'create', 'fiscal_import_cfop', item_id, {'before': old, 'after': values, 'active': active})
            return next(r for r in self.import_cfop_mappings(cid, conn) if r['id'] == item_id)

    def fiscal_import_settings(self, cid, conn=None):
        if conn is None:
            with self.db.read() as connection: return self.fiscal_import_settings(cid, connection)
        company_row(conn, cid)
        row = conn.execute('SELECT * FROM masters WHERE company_id=? AND kind=? AND code=?', (cid, SETTINGS_KIND, 'default')).fetchone()
        if not row: return {'purchase_destination': '', 'fallback_mappings': [], 'version': 0}
        data = json.loads(row['data_json'])
        warnings = [{'source_cfop': m['source_cfop'], 'reason': 'Natureza não coberta pelo padrão de compra; exige regra específica e revisão.'} for m in data['fallback_mappings'] if m['source_cfop'] not in {'5101', '5102', '6101', '6102', '5401', '5403', '5405', '6401', '6403', '6404'}]
        return data | {'version': row['version'], 'warnings': warnings}

    def save_fiscal_import_settings(self, cid, payload, actor):
        destination = purchase_destination(payload.get('purchase_destination', ''))
        reason = text(payload.get('reason'), 'Fundamento do padrão', True, 1000)
        responsible = text(payload.get('responsible'), 'Responsável pelo padrão', True, 200)
        fallbacks = payload.get('fallback_mappings', [])
        if not isinstance(fallbacks, list) or len(fallbacks) > 200: raise DomainError('Padrões de CFOP inválidos.')
        values = []; seen = set()
        for row in fallbacks:
            if not isinstance(row, dict): raise DomainError('Padrão de CFOP inválido.')
            purpose = purchase_destination(row.get('purchase_destination', ''))
            if not purpose: raise DomainError('Informe a destinação de cada padrão de compra.')
            start = iso_date(row.get('valid_from', '2026-01-01'))
            end = iso_date(row['valid_to']) if row.get('valid_to') else ''
            if end and end < start: raise DomainError('Fim da vigência anterior ao início.')
            source = cfop_at(row.get('source_cfop'), start)['code']
            target = cfop_at(row.get('target_cfop'), start, 'incoming')['code']
            if end: cfop_at(target, end, 'incoming')
            if (source, purpose) in seen: raise DomainError('Padrões duplicados para origem e destinação.')
            seen.add((source, purpose))
            values.append({'source_cfop': source, 'target_cfop': target, 'purchase_destination': purpose, 'valid_from': start, 'valid_to': end})
        catalog_version = payload.get('source_catalog_version', '')
        if catalog_version and catalog_version != IMPORT_CATALOG_VERSION: raise DomainError('Catálogo padrão mudou. Recarregue antes de importar.', 409)
        data = {'source_catalog_version': catalog_version, 'purchase_destination': destination, 'fallback_mappings': values, 'reason': reason, 'responsible': responsible}
        with self.db.transaction() as conn:
            company_row(conn, cid); effect(conn, cid, 'fiscal.parameters', 'edit')
            old = conn.execute('SELECT * FROM masters WHERE company_id=? AND kind=? AND code=?', (cid, SETTINGS_KIND, 'default')).fetchone()
            if catalog_version:
                data['catalog_imported_at'] = now()
                data['catalog_imported_by'] = actor
            elif old:
                previous = json.loads(old['data_json'])
                for key in ('source_catalog_version', 'catalog_imported_at', 'catalog_imported_by'): data[key] = previous.get(key, '')
            if old:
                check_version(old, payload)
                conn.execute('UPDATE masters SET data_json=?, version=version+1, updated_at=? WHERE id=? AND company_id=?', (pack(data), now(), old['id'], cid))
            else:
                if payload.get('version', 0) != 0: raise DomainError('Configuração alterada; recarregue.', 409)
                conn.execute('INSERT INTO masters(company_id,kind,code,name,data_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)', (cid, SETTINGS_KIND, 'default', 'Padrões de importação de compras', pack(data), now(), now()))
            audit(conn, cid, actor, 'update' if old else 'create', SETTINGS_KIND, cid, {'before': dict(old) if old else None, 'after': data})
            return self.fiscal_import_settings(cid, conn)

    def fiscal_import_catalog(self, cid):
        with self.db.read() as conn: company_row(conn, cid)
        rows = []
        # Deliberately enumerated pairs, not a first-digit conversion. These are
        # configurable accounting proposals conditioned on the buyer's purpose.
        for sources, targets, regime in [
            (('5101', '5102'), {'resale': '1102', 'industrialization': '1101', 'consumption': '1556', 'fixed_asset': '1551'}, 'regular'),
            (('6101', '6102'), {'resale': '2102', 'industrialization': '2101', 'consumption': '2556', 'fixed_asset': '2551'}, 'regular'),
            (('5401', '5403', '5405'), {'resale': '1403', 'industrialization': '1401', 'consumption': '1407', 'fixed_asset': '1406'}, 'substitution'),
            (('6401', '6403', '6404'), {'resale': '2403', 'industrialization': '2401', 'consumption': '2407', 'fixed_asset': '2406'}, 'substitution'),
        ]:
            for source in sources:
                for purpose, target in targets.items():
                    source_ref, target_ref = cfop_at(source, '2026-11-09'), cfop_at(target, '2026-11-09', 'incoming')
                    rows.append({'source_cfop': source, 'target_cfop': target, 'purchase_destination': purpose, 'valid_from': '2026-01-01', 'valid_to': '', 'source_title': source_ref['title'], 'target_title': target_ref['title'], 'tax_context': regime, 'requires_review': True, 'reason': 'Proposta de escrituração condicionada à destinação declarada pelo adquirente, UF e natureza da operação. Descrições oficiais não constituem de-para universal nem autorizam crédito tributário.', 'source': reference()['source'], 'reference_edition': reference()['edition']})
        return {'version': IMPORT_CATALOG_VERSION, 'rows': rows, 'source': reference()['source'], 'reference_edition': reference()['edition'], 'activation_required': True, 'excluded_scenarios': ['Bonificação', 'Remessa', 'Devolução', 'Transferência', 'Frete', 'Importação: conferir documentação e natureza específica'], 'warning': 'Ative somente regras compatíveis com a operação. CFOP não define crédito, CST, alíquota ou tributação automaticamente.'}
