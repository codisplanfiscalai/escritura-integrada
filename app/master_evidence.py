"""Read-only documentary evidence scoped to a company's own fiscal records."""
from copy import deepcopy
import hashlib
import json
import re
from zipfile import BadZipFile

from .core import DomainError, company_row, integer, select_one
from .permissions import effect

DOCUMENT_FIELDS = ('issuer', 'recipient', 'transport', 'billing', 'authorization',
                   'taxes', 'items', 'declared_xml', 'declared_document_fields', 'declared_protocol',
                   'source_cfops', 'movement_date', 'declared_new_total')


def xml_details(core, conn, cid, document):
    """Recover legacy details only from bytes matching the retained source hash.

    No backfill, reimport, permission expansion, or changes to posted values.
    """
    source_hash = document.get('source_hash')
    result = {'document_id': document['id'], 'source_hash': source_hash,
              'source': document.get('source'), 'available': False, 'origin': 'stored',
              'document': {k: deepcopy(document[k]) for k in DOCUMENT_FIELDS if k in document}}
    if document.get('declared_xml'):
        result['document'].update(deepcopy(document.get('declared_source') or {}))
        result['available'] = True
        return result
    if not isinstance(source_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', source_hash):
        result['message'] = 'Documento sem XML de origem identificado; dados informados permanecem disponíveis.'
        return result
    from .auditor_sources import original_xmls
    from .importers import parse_file
    # A hash match is only a candidate locator. Verify the actual XML bytes and
    # document key before using an original, including nested import packages.
    for batch in conn.execute('SELECT filename,original FROM imports WHERE company_id=? AND original IS NOT NULL AND parsed_json LIKE ? ORDER BY id DESC',
                              (cid, '%' + source_hash + '%')):
        try:
            originals = original_xmls(batch['filename'], batch['original'])
        except (ValueError, DomainError, OSError, BadZipFile):
            continue
        for filename, raw in originals:
            if hashlib.sha256(raw).hexdigest() != source_hash:
                continue
            parsed = parse_file(filename, raw, company_row(conn, cid))
            candidates = [d for d in parsed.get('documents', []) if d.get('source_hash') == source_hash
                          and d.get('key') == document.get('key')]
            if len(candidates) != 1:
                continue
            source = candidates[0]
            result.update(available=True, origin='retained_xml',
                          document={k: source[k] for k in DOCUMENT_FIELDS if k in source})
            return result
    result['message'] = 'XML integral não localizado pelo hash retido. Os campos já armazenados continuam disponíveis; nenhum dado foi presumido.'
    return result


def document_xml_details(core, cid, item_id):
    with core.db.read(snapshot=True) as conn:
        effect(conn, cid, 'fiscal.documents', 'read')
        document = core._document(conn, cid, item_id)
        return xml_details(core, conn, cid, document)


def master_evidence(core, cid, kind, item_id, *, offset=0, limit=25):
    """Page linked local documentary observations, never global private data."""
    offset = integer(offset, 'Início', 0)
    limit = integer(limit, 'Limite', 1)
    if limit > 100:
        raise DomainError('Consulte até 100 ocorrências por página.')
    with core.db.read(snapshot=True) as conn:
        effect(conn, cid, 'fiscal.masters', 'read')
        effect(conn, cid, 'fiscal.documents', 'read')
        master = core._master(conn, cid, item_id, kind)
        if kind not in {'participant', 'establishment', 'product', 'service'}:
            raise DomainError('Cadastro não possui observações fiscais.')
        observations, total = [], 0
        identity = master['data'].get('import_identity') or {}
        initial_hash = master['data'].get('import_source_hash')
        if not initial_hash and identity:
            event = conn.execute("SELECT details_json FROM audit WHERE company_id=? AND entity=? AND entity_id=? AND action='create' ORDER BY id LIMIT 1",
                                 (cid, kind, str(item_id))).fetchone()
            if event:
                details = json.loads(event['details_json'])
                if details.get('imported'):
                    initial_hash = details.get('source_hash')
        if kind in {'product', 'service'}:
            sql = """SELECT * FROM documents WHERE company_id=? AND (EXISTS (
                SELECT 1 FROM json_each(documents.items_json) item
                WHERE json_extract(item.value, '$.master_id')=?) OR source_hash=?)
                ORDER BY issue_date DESC,id DESC"""
            parameters = (cid, item_id, initial_hash or '')
        else:
            # Candidate narrowing only. The full CPF/CNPJ is checked below.
            sql = 'SELECT * FROM documents WHERE company_id=? AND extra_json LIKE ? ORDER BY issue_date DESC,id DESC'
            parameters = (cid, '%' + master['tax_id'] + '%')
        from .fiscal_series import settings
        digits=settings(conn,cid)["digits"]
        for row in conn.execute(sql, parameters):
            doc = core._document_values(row,digits)
            summary = {k: doc.get(k) for k in ('id', 'number', 'series', 'model', 'issue_date', 'posting_date', 'key', 'direction', 'source', 'source_hash')}
            entries = []
            if kind in {'product', 'service'}:
                for item in doc.get('items', []):
                    if item.get('master_id') == item_id:
                        entries.append({'role': 'item', 'item_number': item.get('number'), 'values': item})
                # A reviewed relink must not erase the creation evidence of the
                # former master. Show it explicitly as origin, not a current link.
                if (initial_hash and doc.get('source_hash') == initial_hash
                        and (doc.get('issuer') or {}).get('tax_id') == identity.get('issuer')):
                    source_items = (doc.get('declared_source') or {}).get('items')
                    if source_items is None:
                        source_items = [{'number': item.get('number'), 'code': item.get('code'),
                                         'declared_product_fields': item.get('declared_product_fields'),
                                         'source_cfop': item.get('source_cfop'), 'source': item.get('source')}
                                        for item in doc.get('items', [])]
                    current_numbers = {str(entry['item_number']) for entry in entries}
                    for item in source_items:
                        if item.get('code') == identity.get('code') and str(item.get('number')) not in current_numbers:
                            entries.append({'role': 'initial_origin', 'item_number': item.get('number'),
                                            'values': item, 'notice': 'Origem de criação do cadastro; não representa vínculo atual do item.'})
            else:
                candidates = [('issuer', doc.get('issuer')), ('recipient', doc.get('recipient'))]
                candidates += [(f'transport/{key}', value) for key, value in (doc.get('transport') or {}).items() if isinstance(value, dict)]
                seen = set()
                for role, party in candidates:
                    if not isinstance(party, dict) or not master['tax_id'] or party.get('tax_id') != master['tax_id']:
                        continue
                    # Same issuer may appear twice in a CT-e; keep distinct roles
                    # only once, without joining branches by their CNPJ root.
                    key = (role, json.dumps(party, sort_keys=True))
                    if key not in seen:
                        entries.append({'role': role, 'values': party})
                        seen.add(key)
            for entry in entries:
                if offset <= total < offset + limit:
                    observations.append({'document': summary, **entry})
                total += 1
        return {'master_id': item_id, 'company_id': cid, 'kind': kind, 'items': observations,
                'total': total, 'offset': offset, 'limit': limit,
                'notice': 'Dados declarados em documentos desta empresa. Valores e tributos históricos não são regras automáticas do cadastro.'}
