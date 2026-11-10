"""Atomic reclassification of existing imported documents, without replaying inserts."""
from copy import deepcopy
import json

from .core import DomainError, audit, company_row, digest, ensure_open, pack, select_one, text
from .fiscal_import import original_business_key
from .permissions import effect
from .tax_ledger import ensure_unfinalized


class ImportReprocessingMixin:
    def _reprocess_plan(self, conn, cid, item_id, payload):
        effect(conn, cid, 'fiscal.imports', 'import')
        effect(conn, cid, 'fiscal.documents', 'edit')
        batch = select_one(conn, 'imports', cid, item_id)
        parsed = json.loads(batch['parsed_json'])
        valid = [f'documents:{i}' for i in range(len(parsed['documents']))]
        selected = payload.get('selected', valid)
        if (not isinstance(selected, list) or not selected or
                any(not isinstance(x, str) or x not in valid for x in selected) or len(set(selected)) != len(selected)):
            raise DomainError('Seleção de documentos inválida.')
        overrides = payload.get('document_overrides', {})
        if not isinstance(overrides, dict): raise DomainError('Revisões inválidas.')
        effective = deepcopy(payload)
        effective['document_overrides'] = deepcopy(overrides)
        seeded = deepcopy(parsed)
        existing, blocked = {}, {}
        for index, raw in enumerate(parsed['documents']):
            key = valid[index]
            row = conn.execute('SELECT * FROM documents WHERE company_id=? AND business_key=?',
                               (cid, original_business_key(raw))).fetchone()
            if row is None:
                blocked[key] = 'Documento não existe mais ou não foi importado. Não será recriado.'
                continue
            old = self._document(conn, cid, row['id'])
            existing[key] = old
            try:
                if not raw.get('source_hash') or not any(s['source_hash'] == raw['source_hash'] for s in old['sources']):
                    raise DomainError('Origem não corresponde ao documento existente.')
                if any(old.get(k) != raw.get(k) for k in ('key', 'direction', 'model')):
                    raise DomainError('Identidade original divergente; revisão individual necessária.')
                if not old.get('items') or old['model'] not in {'55', '65'}:
                    raise DomainError('Reprocessamento automático exige itens NF-e/NFC-e; revise este documento individualmente.')
                numbers = lambda rows: [str(i.get('number')) for i in rows]
                current, original = numbers(old['items']), numbers(raw.get('items', []))
                if len(set(current)) != len(current) or set(current) != set(original) or len(current) != len(original):
                    raise DomainError('Itens alterados ou renumerados; reprocessamento seguro indisponível.')
                ensure_open(conn, cid, old['period'], 'fiscal')
                ensure_unfinalized(conn, cid, old['period'])
                self._validate_booked_edit(conn, cid, dict(row), {}) if old['status'] == 'booked' else None
                if old['journal_id'] or conn.execute('SELECT 1 FROM titles WHERE company_id=? AND document_id=? AND (cancelled=0 OR renegotiation_id IS NOT NULL)', (cid, old['id'])).fetchone():
                    raise DomainError('Documento possui efeitos vinculados; reverta-os antes de reprocessar.')
                revision = overrides.get(key, {})
                if not isinstance(revision, dict): raise DomainError('Revisão inválida.')
                confirmed = old.get('posting_date_confirmed') or old.get('import_posting', {}).get('document_revision', {}).get('posting_date_confirmed') or old.get('import_posting', {}).get('document_revision', {}).get('posting_date')
                if (old['status'] != 'booked' or (old.get('posting_date_proposed') and not confirmed)) and not (revision.get('posting_date_confirmed') is True or revision.get('posting_date')):
                    raise DomainError('Confirme explicitamente recebimento e competência antes de reprocessar.')
                doc = deepcopy(old)
                if 'total_review' in revision and revision['total_review'] is None:
                    doc.pop('total_review', None)
                elif 'total_review' not in revision and 'total_review' not in payload and old.get('total_review'):
                    effective['document_overrides'].setdefault(key, {})['total_review'] = deepcopy(old['total_review'])
                doc['posting_date_proposed'] = False
                doc.pop('_import_revision', None)
                doc.pop('import_posting', None)
                for field in ('fiscal_treatment', 'posting_group_review'):
                    if field in revision and revision[field] is None:
                        doc.pop(field, None)
                        effective['document_overrides'][key].pop(field)
                # Re-run rules from preserved issuer classification, retaining all manual amounts and product links.
                originals = {str(i['number']): i for i in raw['items']}
                for item in doc['items']:
                    source = originals[str(item['number'])]
                    if item.get('source_cfop') != source.get('source_cfop'):
                        raise DomainError('CFOP de origem divergente; revisão individual necessária.')
                    item['cfop'] = source.get('source_cfop') or source.get('cfop', '')
                doc['cfop'] = raw.get('cfop', '')
                seeded['documents'][index] = doc
            except DomainError as exc:
                blocked[key] = exc.detail
        prepared = self._prepare_fiscal_import(conn, cid, dict(batch, parsed_json=pack(seeded)), effective)
        rows = []
        for index, proposed in enumerate(prepared['documents']):
            key = valid[index]
            old = existing.get(key)
            reason = blocked.get(key) or ('' if proposed['import_posting']['eligible'] else proposed['import_posting']['reason'])
            if old and not reason:
                from .fiscal_analytics import validate_fiscal_treatment, validate_posting_group_review
                try:
                    if 'fiscal_treatment' in proposed:
                        validate_fiscal_treatment(proposed['fiscal_treatment'], proposed['posting_date'])
                    if 'posting_group_review' in proposed:
                        validate_posting_group_review(proposed['posting_group_review'], proposed)
                except DomainError as exc:
                    reason = exc.detail
            update = {}
            if old and not reason:
                update = {k: deepcopy(proposed[k]) for k in ('cfop', 'posting_date', 'items', 'fiscal_treatment', 'posting_group_review', 'total_review') if k in proposed}
                # Eligibility above requires a confirmed existing date or an explicit new decision.
                update['posting_date_confirmed'] = True
                for field in ('fiscal_treatment', 'posting_group_review', 'total_review'):
                    if field in overrides.get(key, {}) and overrides[key][field] is None:
                        update[field] = None
                update['version'] = old['version']
            before = {k: deepcopy(old.get(k)) for k in update if k != 'version'} if old else {}
            after = {k: v for k, v in update.items() if k != 'version'}
            rows.append({'index': index, '_selection': key, 'id': old['id'] if old else None,
                         'version': old['version'] if old else None, 'selected': key in selected,
                         'eligible': not bool(reason), 'reason': reason, 'before': before, 'after': after,
                         'diffs': {k: {'old': before.get(k), 'new': v} for k, v in after.items() if before.get(k) != v},
                         'posting_lines': proposed.get('posting_lines', []), 'document': proposed, '_update': update})
        # A ZIP can contain several copies of one source document. Decisions are
        # compared per existing movement, while selection remains source-index based.
        grouped = {}
        for row in rows:
            if row['id'] is not None:
                grouped.setdefault(row['id'], []).append(row)
        for duplicates in grouped.values():
            chosen = [row for row in duplicates if row['selected']]
            representative = (chosen or duplicates)[0]
            for row in duplicates:
                if row is not representative:
                    row['duplicate_of'] = representative['_selection']
            if len(chosen) > 1 and len({digest(row['_update']) for row in chosen}) > 1:
                for row in duplicates:
                    row['eligible'] = False
                    row['reason'] = 'Cópias do mesmo documento possuem decisões conflitantes. Uniformize as revisões ou selecione apenas uma cópia.'
        fingerprint = digest({'batch': batch['preview_hash'], 'prepared': prepared['posting_hash'],
                              'existing': existing, 'rows': rows, 'selected': selected,
                              'company': company_row(conn, cid), 'mappings': self.import_cfop_mappings(cid, conn),
                              'catalogs': self._company_cfop_catalogs(conn, cid)})
        return {'import_id': item_id, 'reprocess_hash': fingerprint, 'documents': rows,
                'can_confirm': all(r['eligible'] for r in rows if r['selected'])}

    def reprocess_import_preview(self, cid, item_id, payload):
        with self.db.read(snapshot=True) as conn:
            plan = self._reprocess_plan(conn, cid, item_id, payload)
            for row in plan['documents']: row.pop('_update')
            return plan

    def reprocess_import_confirm(self, cid, item_id, payload, actor):
        reason = text(payload.get('reason'), 'Motivo do reprocessamento', True, 1000)
        with self.db.transaction() as conn:
            effect(conn, cid, 'fiscal.imports', 'import')
            effect(conn, cid, 'fiscal.documents', 'edit')
            select_one(conn, 'imports', cid, item_id)
            scope = 'reprocess-import:' + str(item_id)
            key, hashed, previous = self._operation(conn, cid, scope, payload)
            if previous:
                for doc_id in previous['document_ids']:
                    doc = select_one(conn, 'documents', cid, doc_id)
                    if doc['status'] == 'booked': effect(conn, cid, 'fiscal.documents', 'book')
                return previous
            plan = self._reprocess_plan(conn, cid, item_id, payload)
            if payload.get('reprocess_hash') != plan['reprocess_hash']:
                raise DomainError('Prévia desatualizada. Revise novamente antes de confirmar.', 409, 'reprocess_stale')
            if not plan['can_confirm']:
                raise DomainError('Há documentos selecionados bloqueados; nenhum foi alterado.', 409, 'reprocess_blocked')
            ids = []
            for row in plan['documents']:
                if not row['selected'] or row['id'] in ids: continue
                self.update_document(cid, row['id'], dict(row['_update'], reason=reason), actor, _conn=conn)
                saved = select_one(conn, 'documents', cid, row['id'])
                extras = json.loads(saved['extra_json'])
                extras['import_posting'] = deepcopy(row['document']['import_posting'])
                extras['import_posting'].update(review_pending=True, last_edit_reason=reason, reprocessed_from_import=item_id)
                conn.execute('UPDATE documents SET extra_json=? WHERE id=? AND company_id=?', (pack(extras), row['id'], cid))
                ids.append(row['id'])
            result = {'import_id': item_id, 'document_ids': ids, 'documents_updated': len(ids), 'documents_created': 0}
            audit(conn, cid, actor, 'reprocess', 'import', item_id, {'reason': reason, 'reprocess_hash': plan['reprocess_hash'], 'document_ids': ids})
            self._record_operation(conn, cid, scope, key, hashed, result)
            return result
