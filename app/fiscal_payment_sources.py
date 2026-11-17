"""Read-only legacy payment evidence from company-owned retained import bytes.

Never reimport or backfill a reviewed document. Cache only parsed identities and
payment snapshots within one operation; archives are decoded once per operation.
"""
import hashlib
import json
import re
from zipfile import BadZipFile

from .core import DomainError, company_row


class RetainedPaymentSources:
    def __init__(self, conn, cid):
        self.conn, self.cid = conn, cid
        self.index, self.batches = None, {}

    def _index(self):
        if self.index is not None:
            return self.index
        self.index = {}
        for batch in self.conn.execute('SELECT id,parsed_json FROM imports WHERE company_id=? AND original IS NOT NULL ORDER BY id DESC', (self.cid,)):
            try:
                parsed = json.loads(batch['parsed_json'])
                documents = parsed.get('documents', []) if isinstance(parsed, dict) else []
                if not isinstance(documents, list):
                    continue
                for doc in documents:
                    if not isinstance(doc, dict):
                        continue
                    identity = (doc.get('source_hash'), doc.get('key'), doc.get('model'))
                    if not all(isinstance(x, str) for x in identity):
                        continue
                    batches = self.index.setdefault(identity, [])
                    if batch['id'] not in batches:
                        batches.append(batch['id'])
            except (ValueError, TypeError):
                continue
        return self.index

    def _batch(self, ident):
        if ident in self.batches:
            return self.batches[ident]
        from .auditor_sources import original_xmls
        from .importers import parse_file
        sources = self.batches[ident] = {}
        batch = self.conn.execute('SELECT filename,original,sha256 FROM imports WHERE company_id=? AND id=? AND original IS NOT NULL', (self.cid, ident)).fetchone()
        if batch is None or not isinstance(batch['original'], (bytes, bytearray, memoryview)):
            return sources
        raw_batch = bytes(batch['original'])
        if hashlib.sha256(raw_batch).hexdigest() != batch['sha256']:
            return sources
        company = company_row(self.conn, self.cid)
        try:
            originals = original_xmls(batch['filename'], raw_batch)
            for filename, raw in originals:
                source_hash = hashlib.sha256(raw).hexdigest()
                parsed = parse_file(filename, raw, company)
                documents = parsed.get('documents', [])
                if len(documents) != 1:
                    continue
                doc = documents[0]
                if doc.get('source_hash') != source_hash or doc.get('model') not in {'55', '65'}:
                    continue
                # Explicitly non-authorized/cancelled protocol cannot become
                # payment evidence, even if an old stored status is inconsistent.
                status = doc.get('authorization', {}).get('status')
                if status and status not in {'100', '150'}:
                    continue
                # Keep only the payment subtree, not every item/address/XML byte.
                fields = doc.get('declared_document_fields') or {}
                sources[source_hash] = {
                    'key': doc.get('key'), 'model': doc.get('model'), 'direction': doc.get('direction'),
                    'fields': {'tag': fields.get('tag'), 'children': [n for n in fields.get('children', []) if n.get('tag') == 'pag']}}
        except (ValueError, OSError, DomainError, BadZipFile):
            # Invalid/missing/unsafe source is unavailable, never a successful
            # accounting fallback. A second exact retained copy may still exist.
            sources.clear()
        return sources

    def snapshot(self, doc):
        source_hash, key, model = doc.get('source_hash'), doc.get('key'), doc.get('model')
        if not isinstance(source_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', source_hash) or not isinstance(key, str) or not re.fullmatch(r'[A-Z0-9]{44}', key):
            raise DomainError('Nota sem identidade/hash de XML original preservado para recuperar pagamentos.', 400, 'payment_source_unavailable')
        for ident in self._index().get((source_hash, key, model), []):
            source = self._batch(ident).get(source_hash)
            if source and (source['key'], source['model'], source['direction']) == (key, model, doc['direction']):
                return source['fields']
        raise DomainError('XML original íntegro e correspondente à nota/empresa indisponível para recuperar pagamentos. Nenhum dado foi alterado.', 422, 'payment_source_unavailable')
