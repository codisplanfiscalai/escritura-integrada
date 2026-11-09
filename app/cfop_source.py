"""Lossless report references; declared parameters never become tax rules."""
from collections import Counter
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

from .cfop import reference, cfop_at
from .core import DomainError, audit, company_row, digest, integer, iso_date, now, pack, select_one, text
from .permissions import effect

SOURCE_KIND = 'cfop_source_load'
SCHEMA = 'escritura-cfop-source/1'
FIELDS = {
    'revenue': r'Faturamento:[ \t]*([^\n]+)',
    'revenue_tax_base': r'Coluna Base de Cálculo IPI ou ICMS:[ \t]*([^\n]+?)(?:[ \t]{2,}|$)',
    'revenue_exempt': r'Coluna Isentas IPI ou ICMS:[ \t]*([^\n]+?)(?:[ \t]{2,}|$)',
    'revenue_other': r'Coluna Outras IPI ou ICMS:[ \t]*([^\n]+?)(?:[ \t]{2,}|$)',
    'icms_declared': r'Tributa ICMS:[ \t]*(Sim|Não)',
    'ipi_declared': r'Tributa IPI:[ \t]*(Sim|Não)',
    'gi_declared': r'Entra para GI:[ \t]*(Sim|Não)',
    'me_epp_purchases': r'Enquadramento Base de Cálculo ME/EPP por Compras:[ \t]*([^\n]+?)(?:[ \t]{2,}|$)',
}


def _sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _report_records(content, pdf):
    heads = list(re.finditer(r'^[ \t]*(\d{3,4})[ \t]*-[ \t]*(.+)$', content, re.M))
    if not heads: raise ValueError('Nenhum registro reconhecido no relatório.')
    records = []
    for i, head in enumerate(heads):
        end = heads[i+1].start() if i+1 < len(heads) else len(content)
        body = content[head.end():end]
        values = {}
        if pdf:
            for key, pattern in FIELDS.items():
                found = re.search(pattern, body, re.M)
                if not found: raise ValueError(f'{head[1]}: campo {key} não extraído do PDF.')
                values[key] = found[1].strip()
        else:
            for key, pattern in [('icms_declared', r'Tributa IC(Sim|Năo|Não)'), ('ipi_declared', r'Tributa IP(Sim|Năo|Não)'), ('gi_declared', r'Entra para(Sim|Năo|Não)')]:
                found = re.search(pattern, body)
                if not found: raise ValueError(f'{head[1]}: indicador {key} não extraído do TXT.')
                values[key] = found[1]
        rates = re.findall(r'\b\d+\.\d{4}\b', body)
        prefix = body.split('Faturamento:' if pdf else 'Faturame', 1)[0]
        continuation = [line.strip() for line in prefix.splitlines() if line.strip()
                        and not re.match(r'^(<PARSED TEXT|RELATÓRIO|\d+$)', line.strip())]
        title = ' '.join([head[2].strip(), *continuation])
        records.append({'code': head[1], 'title': title, 'fields': values, 'rates': rates,
                        'span': {'start_line': content.count('\n', 0, head.start())+1,
                                 'end_line': content.count('\n', 0, max(0, end-1))+1}})
    duplicates = [code for code, count in Counter(r['code'] for r in records).items() if count != 1]
    if duplicates: raise ValueError('Códigos repetidos na origem: ' + ', '.join(duplicates))
    return records


def build_source_bundle(texts, metadata):
    if not isinstance(texts, dict) or set(texts) != {'pdf', 'txt'} or any(not isinstance(v, str) for v in texts.values()) or sum(map(len, texts.values())) > 8_000_000:
        raise ValueError('Informe as duas extrações textuais completas, até 8 milhões de caracteres.')
    if not isinstance(metadata, dict) or set(metadata) != {'pdf', 'txt'} or any(not isinstance(v, dict) for v in metadata.values()):
        raise ValueError('Metadados das duas fontes são obrigatórios.')
    pdf = _report_records(texts['pdf'], True); txt = _report_records(texts['txt'], False)
    t = {r['code']: r for r in txt}
    if {r['code'] for r in pdf} != set(t): raise ValueError('PDF e TXT contêm conjuntos diferentes de códigos.')
    rows = []
    for p in pdf:
        other = t[p['code']]
        if p['rates'] != other['rates']: raise ValueError(p['code'] + ': alíquotas divergentes entre PDF e TXT; confira as fontes.')
        for key in ('icms_declared', 'ipi_declared', 'gi_declared'):
            if p['fields'][key] != other['fields'][key].replace('Năo', 'Não'):
                raise ValueError(p['code'] + ': indicadores divergentes; confira as fontes.')
        rows.append({'code': p['code'], 'source_description': p['title'], 'txt_description': other['title'],
                     'parameters_declared': p['fields'], 'txt_indicators_original': other['fields'],
                     'rates_declared': p['rates'], 'valid_from': '', 'valid_to': '',
                     'review_status': 'unreviewed', 'source_spans': {'pdf': p['span'], 'txt': other['span']}})
    pdf_pages = [int(n) for n in re.findall(r'<PARSED TEXT FOR PAGE: (\d+) / \d+>', texts['pdf'])]
    if pdf_pages and pdf_pages != list(range(1, max(pdf_pages)+1)):
        raise ValueError('Extração PDF com páginas ausentes ou repetidas.')
    result = {'schema': SCHEMA, 'name': 'Referência enviada · tabcfop', 'sources': deepcopy(metadata),
              'source_texts': texts, 'extracted_text_sha256': {k: _sha(v) for k, v in texts.items()},
              'record_count': len(rows), 'pdf_pages': len(pdf_pages), 'records': rows,
              'limitations': ['Parâmetros declarados pela origem, sem validação legal.',
                             'Emissão do relatório não é início de vigência dos parâmetros.',
                             'Códigos antigos ou sem correspondência não são convertidos automaticamente.']}
    result['bundle_id'] = digest({'texts': texts, 'records': rows, 'schema': SCHEMA})
    return result


def validate_source_bundle(bundle):
    if not isinstance(bundle, dict) or bundle.get('schema') != SCHEMA:
        raise DomainError('Formato da carga CFOP não reconhecido.')
    try:
        rebuilt = build_source_bundle(bundle.get('source_texts'), bundle.get('sources'))
    except (ValueError, TypeError, KeyError) as exc:
        raise DomainError(str(exc)) from exc
    if bundle != rebuilt: raise DomainError('A carga diverge das extrações de origem. Reconverta os relatórios.', 409, 'cfop_load_changed')
    return rebuilt


@lru_cache(maxsize=1)
def default_source_bundle():
    return json.loads((Path(__file__).parent / 'data/cfop-carga-tabcfop-20261109.json').read_text(encoding='utf-8'))


def load_comparison(bundle, day):
    known = {r['code'] for r in reference()['entries']}
    rows = []
    for source in bundle['records']:
        row = {k: v for k, v in source.items() if k != 'source_spans'}
        try:
            official = cfop_at(source['code'], day)
            row.update(match='official', official_description=official['title'])
        except DomainError:
            row.update(match='legacy' if len(source['code']) == 3 else 'unmatched', official_description='')
        rows.append(row)
    codes = {r['code'] for r in rows}
    return {'record_count': len(rows), 'official': sum(r['match'] == 'official' for r in rows),
            'legacy': sum(r['match'] == 'legacy' for r in rows), 'unmatched': sum(r['match'] == 'unmatched' for r in rows),
            'official_absent_from_sources': sorted(known-codes), 'without_rates': sum(not r['rates_declared'] for r in rows),
            'different_descriptions': sum(r['source_description'] != r['txt_description'] for r in rows), 'rows': rows}


class CfopSourceMixin:
    def cfop_source_default(self, cid):
        with self.db.read() as conn:
            company_row(conn, cid)
        return default_source_bundle()

    def cfop_source_preview(self, cid, payload):
        bundle = validate_source_bundle(payload.get('bundle')) if 'bundle' in payload else default_source_bundle()
        day = iso_date(payload.get('date'))
        with self.db.read() as conn:
            company_row(conn, cid); effect(conn, cid, 'fiscal.masters', 'read')
            comparison = load_comparison(bundle, day)
            existing = {r['code'] for r in conn.execute("SELECT code FROM catalogs WHERE company_id=? AND kind='cfop'", (cid,))}
            eligible = {r['code'] for r in reference()['entries'] if r['wording_valid_from'] <= day and (not r['wording_valid_to'] or day <= r['wording_valid_to'])}
            comparison['official_catalog_count'] = len(eligible)
            comparison['catalogs_create'] = len(eligible-existing)
            comparison['catalogs_preserve'] = len(eligible & existing)
            comparison['already_imported'] = bool(conn.execute('SELECT id FROM masters WHERE company_id=? AND kind=? AND code=?', (cid, SOURCE_KIND, bundle['bundle_id'])).fetchone())
        return comparison | {'bundle_id': bundle['bundle_id'], 'date': day, 'name': bundle['name'],
                             'sources': bundle['sources'], 'pdf_pages': bundle['pdf_pages'],
                             'preview_hash': digest({'bundle': bundle['bundle_id'], 'date': day, 'comparison': comparison}),
                             'parameters_active': False}

    def import_cfop_source(self, cid, payload, actor):
        bundle = validate_source_bundle(payload.get('bundle')) if 'bundle' in payload else default_source_bundle()
        day = iso_date(payload.get('date')); reason = text(payload.get('reason'), 'Motivo da carga', True, 1000)
        with self.db.transaction() as conn:
            company_row(conn, cid); effect(conn, cid, 'fiscal.masters', 'create')
            previous = conn.execute('SELECT id FROM masters WHERE company_id=? AND kind=? AND code=?', (cid, SOURCE_KIND, bundle['bundle_id'])).fetchone()
            if previous: return {'id': previous['id'], 'duplicate': True, 'created': 0, 'record_count': bundle['record_count']}
            preview = self.cfop_source_preview(cid, payload)
            if preview['preview_hash'] != payload.get('preview_hash'):
                raise DomainError('A prévia da carga mudou. Confira novamente.', 409, 'stale_cfop_source')
            created = preserved = 0
            for row in reference()['entries']:
                if row['wording_valid_from'] > day or (row['wording_valid_to'] and day > row['wording_valid_to']): continue
                official = cfop_at(row['code'], day)
                if conn.execute("SELECT 1 FROM catalogs WHERE company_id=? AND kind='cfop' AND code=?", (cid, row['code'])).fetchone():
                    preserved += 1; continue
                conn.execute('INSERT INTO catalogs(company_id,kind,code,description,direction,valid_from,valid_to,source,active) VALUES(?,?,?,?,?,?,?,?,1)',
                             (cid, 'cfop', row['code'], official['title'], official['direction'], official['wording_valid_from'], official['wording_valid_to'], reference()['source']))
                created += 1
            data = {'bundle': bundle, 'date': day, 'parameters_active': False, 'reason': reason, 'responsible': actor,
                    'comparison': {k: v for k, v in preview.items() if k != 'rows'}}
            item_id = conn.execute('INSERT INTO masters(company_id,kind,code,name,data_json,active,created_at,updated_at) VALUES(?,?,?,?,?,0,?,?)',
                                   (cid, SOURCE_KIND, bundle['bundle_id'], bundle['name'], pack(data), now(), now())).lastrowid
            audit(conn, cid, actor, 'import', 'cfop_source_load', item_id, {'bundle_id': bundle['bundle_id'], 'reason': reason, 'created': created, 'preserved': preserved, 'records': bundle['record_count'], 'parameters_active': False})
            return {'id': item_id, 'duplicate': False, 'created': created, 'preserved': preserved, 'record_count': bundle['record_count']}

    def cfop_source_loads(self, cid):
        with self.db.read() as conn:
            company_row(conn, cid)
            return [{'id': r['id'], 'created_at': r['created_at'], 'name': r['name'], 'bundle_id': r['code'],
                     'comparison': json.loads(r['data_json'])['comparison'], 'parameters_active': False}
                    for r in conn.execute('SELECT * FROM masters WHERE company_id=? AND kind=? ORDER BY id DESC', (cid, SOURCE_KIND))]

    def cfop_source_rows(self, cid, item_id, search='', page=1):
        page = integer(page, 'Página'); query = search.strip().casefold()
        with self.db.read() as conn:
            row = select_one(conn, 'masters', cid, item_id)
            if row['kind'] != SOURCE_KIND: raise DomainError('Carga CFOP não localizada.', 404)
            data = json.loads(row['data_json'])
        comparison = load_comparison(data['bundle'], data['date'])
        rows = [r for r in comparison['rows'] if not query or query in (r['code']+' '+r['source_description']).casefold()]
        return {'total': len(rows), 'page': page, 'rows': rows[(page-1)*50:page*50], 'parameters_active': False}

    def cfop_source_original(self, cid, item_id):
        with self.db.read() as conn:
            row = select_one(conn, 'masters', cid, item_id)
            if row['kind'] != SOURCE_KIND: raise DomainError('Carga CFOP não localizada.', 404)
            return json.loads(row['data_json'])['bundle']
