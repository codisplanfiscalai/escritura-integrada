"""Direct fiscal posting from a checked import, without implicit cross-module effects."""
from copy import deepcopy
import json

from .cfop import cfop_at, company_cfop_at, mapping_key, reference
from .core import DomainError, audit, check_version, digest, ensure_open, now, pack, semantic_value, select_one, text
from .import_scope import classify
from .permissions import effect
from .tax_ledger import ensure_unfinalized


def original_business_key(document):
    if document.get('key'): return 'key:' + document['key']
    return digest({k: document.get(k, '') for k in ('direction', 'model', 'series', 'number', 'partner_tax_id', 'partner_name', 'issue_date')})


class FiscalImportMixin:
    def _preserve_import_item_origins(self, old_items, items):
        immutable = ('source_cfop', 'source', 'declared_product_fields')
        originals = {str(row['number']): row for row in old_items if isinstance(row, dict) and row.get('number') is not None}
        for row in items:
            if not isinstance(row, dict): raise DomainError('Item fiscal inválido.')
            original = originals.get(str(row.get('number')))
            for field in immutable:
                if original and field in original:
                    if field in row and row[field] != original[field]:
                        raise DomainError('CFOP e metadados de origem do item devem permanecer preservados. Altere os campos de escrituração.', 409, 'item_origin_preserved')
                    row[field] = deepcopy(original[field])
                elif field in row:
                    raise DomainError('Item acrescentado ou renumerado não pode declarar outra origem de importação.', 409, 'item_origin_preserved')
        return items

    def _prepare_fiscal_import(self, conn, cid, batch, payload):
        parsed = classify(conn, cid, json.loads(batch['parsed_json']), batch['period'][:4])
        overrides = payload.get('cfop_mappings', {})
        if not isinstance(overrides, dict) or len(overrides) > 200 or any(not isinstance(k, str) or not isinstance(v, str) for k, v in overrides.items()):
            raise DomainError('Associações do lote devem relacionar origem e CFOP de destino.')
        saved = self.import_cfop_mappings(cid, conn)
        catalogs = self._company_cfop_catalogs(conn, cid)
        prepared = []
        for raw in parsed['documents']:
            doc = deepcopy(raw)
            info = {'eligible': False, 'reason': '', 'mappings': [], 'reference_edition': reference()['edition'], 'original_business_key': original_business_key(raw), 'review_pending': True}
            try:
                if doc['_eligibility']['status'] != 'eligible': raise DomainError(doc['_eligibility']['reason'])
                ensure_unfinalized(conn, cid, doc['posting_date'][:7])
                if doc.get('environment') == '2': raise DomainError('XML de homologação: mantenha em conferência, sem escrituração direta.')
                # These warnings require a document decision, not a silent batch assumption.
                related = [i for i in parsed['issues'] if i.get('source', {}).get('file') == doc.get('source', {}).get('file')]
                if any(i.get('code') in {'XML_NO_PROTOCOL', 'RTC_TOTAL_REVIEW', 'THIRD_PARTY_ENTRY_REVIEW'} for i in related):
                    raise DomainError('Documento exige conferência individual de autorização, direção ou totalizadores antes de escriturar.')
                rows = doc.get('items') if doc.get('items') and doc['model'] in {'55', '65'} else doc.get('analytics') or [doc]
                for item in rows:
                    source = item.get('source_cfop') or item.get('cfop') or (doc.get('source_cfops') or [''])[0]
                    if source: cfop_at(source, doc['posting_date'])
                    target = item.get('cfop') or doc.get('cfop') or ''
                    key = mapping_key(doc['direction'], doc['model'], source)
                    if key in overrides:
                        target = overrides[key]
                        info['mappings'].append({'source_cfop': source, 'target_cfop': target, 'origin': 'batch', 'key': key})
                    elif not target:
                        matches = [m for m in saved if m['active'] and m['data']['source_cfop'] == source and m['data']['direction'] == doc['direction'] and m['data']['model'] in {'', doc['model']} and m['data']['valid_from'] <= doc['posting_date'] and (not m['data']['valid_to'] or doc['posting_date'] <= m['data']['valid_to'])]
                        specific = [m for m in matches if m['data']['model'] == doc['model']]
                        matches = specific or matches
                        if len(matches) != 1: raise DomainError(f'CFOP de origem {source or "ausente"}: informe a associação da operação da empresa.')
                        mapping = matches[0]; target = mapping['data']['target_cfop']
                        info['mappings'].append({'source_cfop': source, 'target_cfop': target, 'origin': 'company', 'mapping_id': mapping['id'], 'version': mapping['version'], 'responsible': mapping['data']['responsible'], 'mapping_snapshot': mapping['data']})
                    company_cfop_at(target, doc['posting_date'], doc['direction'], catalogs)
                    item['cfop'] = target
                codes = sorted({r['cfop'] for r in rows})
                doc['cfop'] = codes[0] if len(codes) == 1 else ''
                info.update(eligible=True, reason='Pronto para escrituração fiscal direta')
            except DomainError as exc:
                info['reason'] = exc.detail
            doc['import_posting'] = info
            prepared.append(doc)
        parsed['documents'] = prepared
        parsed['posting_hash'] = digest({'preview_hash': batch['preview_hash'], 'documents': semantic_value(prepared), 'edition': reference()['edition'], 'mappings': overrides})
        return parsed

    def fiscal_posting_preview(self, cid, item_id, payload):
        with self.db.read(snapshot=True) as conn:
            batch = select_one(conn, 'imports', cid, item_id)
            effect(conn, cid, 'fiscal.imports', 'read')
            return self._prepare_fiscal_import(conn, cid, batch, payload)

    def _fiscal_import_index(self, conn, cid, documents):
        hashes = sorted({d.get('source_hash', '') for d in documents if d.get('source_hash')})
        found = {}
        for start in range(0, len(hashes), 500):
            chunk = hashes[start:start+500]
            for row in conn.execute('SELECT id,source_hash,extra_json FROM documents WHERE company_id=? AND source_hash IN (' + ','.join('?' for _ in chunk) + ')', (cid, *chunk)):
                info = json.loads(row['extra_json']).get('import_posting', {})
                if info.get('original_business_key'): found[(row['source_hash'], info['original_business_key'])] = row['id']
        return found

    def _existing_fiscal_import(self, conn, cid, document, existing):
        info = document.get('import_posting', {})
        item_id = existing.get((document.get('source_hash', ''), info.get('original_business_key')))
        if item_id: return self._document(conn, cid, item_id) | {'duplicate': True, 'preserved_revision': True}
        return None

    def _post_fiscal_import(self, conn, cid, document, actor, reason):
        if document.get('duplicate'): return document
        effect(conn, cid, 'fiscal.documents', 'book')
        # No assertion that a human reviewed the source: the import consent is
        # recorded separately and the document remains flagged for later review.
        conn.execute("UPDATE documents SET status='reviewed' WHERE id=? AND company_id=?", (document['id'], cid))
        self._book_document(conn, cid, document['id'], {'version': document['version'], 'reason': reason}, actor)
        conn.execute('UPDATE documents SET reviewed_by=NULL,review_reason=NULL WHERE id=? AND company_id=?', (document['id'], cid))
        audit(conn, cid, actor, 'import-book', 'document', document['id'], {'reason': reason, 'source_hash': document['source_hash'], 'posting': document['import_posting'], 'legal_validation': False, 'accounting_created': False, 'financial_created': False})
        return self._document(conn, cid, document['id'])

    def _validate_booked_edit(self, conn, cid, old, payload):
        effect(conn, cid, 'fiscal.documents', 'book')
        if old['journal_id'] or conn.execute('SELECT 1 FROM titles WHERE company_id=? AND document_id=? AND (cancelled=0 OR renegotiation_id IS NOT NULL)', (cid, old['id'])).fetchone():
            raise DomainError('Há efeitos contábeis ou financeiros vinculados. Reverta a escrituração e seus efeitos antes de editar.', 409, 'document_linked_effects')
        if old['source_hash'] and any(payload.get(k, old[k]) != old[k] for k in ('key', 'direction', 'model')):
            raise DomainError('A identidade e o sentido do documento importado devem ser preservados. Corrija a origem ou reverta a escrituração.', 409, 'import_identity_preserved')

    def _validate_posted_classification(self, conn, cid, document):
        catalogs = self._company_cfop_catalogs(conn, cid)
        if document.get('cfop'): company_cfop_at(document['cfop'], document['posting_date'], document['direction'], catalogs)
        rows = document['items'] if document.get('items') and document['model'] in {'55', '65'} else document.get('analytics') or [document]
        for row in rows: company_cfop_at(row.get('cfop') or document.get('cfop'), document['posting_date'], document['direction'], catalogs)
