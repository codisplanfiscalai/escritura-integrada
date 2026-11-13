from .fiscal_series import find_document
"""Atomic reclassification of existing imported documents, without replaying inserts."""
from copy import deepcopy
import json

from .core import DomainError, audit, company_row, digest, ensure_open, pack, select_one, text
from .fiscal_import import original_business_key
from .permissions import effect
from .tax_ledger import ensure_unfinalized


class ImportReprocessingMixin:
    def _reprocess_plan(self, conn, cid, item_id, payload):
        from .operational_settings import ensure_import_allowed
        ensure_import_allowed(conn, cid)
        from .import_payables import requested_payables
        create_payables = requested_payables(payload)
        preserve_fiscal = payload.get('preserve_fiscal', False)
        if type(preserve_fiscal) is not bool: raise DomainError('Preservar escrituração deve ser uma escolha booleana.')
        effect(conn, cid, 'fiscal.imports', 'import')
        effect(conn, cid, 'fiscal.documents', 'edit')
        batch = select_one(conn, 'imports', cid, item_id)
        parsed = json.loads(batch['parsed_json'])
        # Legacy batches are enriched from their exact retained original, never by
        # replaying document insertion or replacing manually revised fiscal data.
        enriched = {}
        if any('billing' not in d for d in parsed['documents']) and batch['original']:
            from .importers import parse_file
            reread = parse_file(batch['filename'], batch['original'], company_row(conn, cid))
            for source in reread.get('documents', []):
                enriched[(original_business_key(source), source.get('source_hash'))] = source
            for raw in parsed['documents']:
                source = enriched.get((original_business_key(raw), raw.get('source_hash')))
                if 'billing' not in raw and source and 'billing' in source:
                    raw['billing'] = deepcopy(source['billing'])
                    raw['invoices'] = deepcopy(source.get('invoices', []))
        valid = [f'documents:{i}' for i in range(len(parsed['documents']))]
        generated_options = self._generated_payables_options(payload, set(valid))
        selected = payload.get('selected', valid)
        if (not isinstance(selected, list) or not selected or
                any(not isinstance(x, str) or x not in valid for x in selected) or len(set(selected)) != len(selected)):
            raise DomainError('Seleção de documentos inválida.')
        if preserve_fiscal:
            if not create_payables or generated_options['enabled']:
                raise DomainError('Preservar escrituração está disponível para gerar somente a cobrança XML original.')
            if any(payload.get(k) for k in ('document_overrides', 'cfop_mappings', 'purchase_destination', 'total_review')):
                raise DomainError('Geração de cobrança com escrituração preservada não aceita alterações fiscais.')
            return self._reprocess_billing_plan(conn, cid, batch, parsed, selected, 'selected' in payload)
        overrides = payload.get('document_overrides', {})
        if not isinstance(overrides, dict): raise DomainError('Revisões inválidas.')
        effective = deepcopy(payload)
        effective['document_overrides'] = deepcopy(overrides)
        seeded = deepcopy(parsed)
        existing, blocked = {}, {}
        for index, raw in enumerate(parsed['documents']):
            key = valid[index]
            row = find_document(conn,cid,raw)
            if row is None:
                blocked[key] = 'Documento não existe mais ou não foi importado. Não será recriado.'
                continue
            old = self._document(conn, cid, row['id'])
            existing[key] = old
            try:
                if old.get('book_cancellation'):
                    raise DomainError('Cancelada conforme livro não pode ser reprocessada como XML.')
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
                linked = conn.execute('SELECT 1 FROM titles WHERE company_id=? AND document_id=?', (cid, old['id'])).fetchone()
                if old['journal_id'] or (linked and not self._safe_payables_classification(conn, cid, old, {})):
                    raise DomainError('Documento possui efeitos vinculados; reverta-os antes de reprocessar.')
                revision = overrides.get(key, {})
                if not isinstance(revision, dict): raise DomainError('Revisão inválida.')
                confirmed = old.get('posting_date_confirmed') or old.get('import_posting', {}).get('document_revision', {}).get('posting_date_confirmed') or old.get('import_posting', {}).get('document_revision', {}).get('posting_date')
                if (old['status'] != 'booked' or (old.get('posting_date_proposed') and not confirmed)) and not (revision.get('posting_date_confirmed') is True or revision.get('posting_date')):
                    raise DomainError('Confirme explicitamente recebimento e competência antes de reprocessar.')
                doc = deepcopy(old)
                if 'billing' not in doc and 'billing' in raw:
                    doc['billing'] = deepcopy(raw['billing'])
                    doc['invoices'] = deepcopy(raw.get('invoices', []))
                    doc['_billing_enriched'] = True
                elif 'billing' not in doc and doc.get('invoices'):
                    doc['billing'] = {'present': True, 'installments': [], 'financial_rules_pending': True, 'issues': [{'message': 'Original indisponível para recuperar cobrança legada.'}]}
                if 'total_review' in revision and revision['total_review'] is None:
                    doc.pop('total_review', None)
                elif 'total_review' not in revision and 'total_review' not in payload:
                    previous_total = old.get('total_review') or old.get('import_posting', {}).get('total_review') or old.get('import_posting', {}).get('document_revision', {}).get('total_review')
                    if previous_total:
                        effective['document_overrides'].setdefault(key, {})['total_review'] = deepcopy(previous_total)
                doc['posting_date_proposed'] = False
                doc.pop('_import_revision', None)
                doc.pop('import_posting', None)
                for field in ('fiscal_treatment', 'posting_group_review'):
                    if field in revision and revision[field] is None:
                        doc.pop(field, None)
                        effective['document_overrides'][key].pop(field)
                # Keep current decisions unless an explicit new mapping/destination overrides them.
                originals = {str(i['number']): i for i in raw['items']}
                for item in doc['items']:
                    source = originals[str(item['number'])]
                    if item.get('source_cfop') != source.get('source_cfop'):
                        raise DomainError('CFOP de origem divergente; revisão individual necessária.')
                seeded['documents'][index] = doc
            except DomainError as exc:
                blocked[key] = exc.detail
        prepared = self._prepare_fiscal_import(conn, cid, dict(batch, parsed_json=pack(seeded)), effective, preserve_item_cfops=True)
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
            finance = proposed.get('financial_posting', {})
            if create_payables and finance.get('status') != 'not_applicable' and not finance.get('eligible'):
                reason = reason or finance.get('reason', 'Cobrança financeira bloqueada.')
            generated = proposed.get('generated_financial_posting', {})
            if generated.get('requested') and generated.get('status') != 'not_applicable' and not generated.get('eligible'):
                reason = reason or generated.get('reason', 'Regra financeira bloqueada.')
            update = {}
            if old and not reason:
                update = {k: deepcopy(proposed[k]) for k in ('cfop', 'posting_date', 'items', 'fiscal_treatment', 'posting_group_review', 'total_review', 'receipt_date') if k in proposed}
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
            if len(chosen) > 1 and len({digest({'update': row['_update'], 'generated': row['document'].get('generated_financial_posting', {}).get('terms')}) for row in chosen}) > 1:
                for row in duplicates:
                    row['eligible'] = False
                    row['reason'] = 'Cópias do mesmo documento possuem decisões conflitantes. Uniformize as revisões ou selecione apenas uma cópia.'
        fingerprint = digest({'batch': batch['preview_hash'], 'prepared': prepared['posting_hash'],
                              'existing': existing, 'rows': rows, 'selected': selected,
                              'company': company_row(conn, cid), 'mappings': self.import_cfop_mappings(cid, conn),
                              'catalogs': self._company_cfop_catalogs(conn, cid)})
        return {'import_id': item_id, 'reprocess_hash': fingerprint, 'documents': rows,
                'can_confirm': all(r['eligible'] for r in rows if r['selected'])}

    def _reprocess_billing_plan(self, conn, cid, batch, parsed, selected, explicit_selection):
        """Plan XML receivables without reclassifying or updating any fiscal row."""
        effect(conn, cid, 'financial.titles', 'create')
        rows = []
        for index, raw in enumerate(parsed['documents']):
            key = f'documents:{index}'
            row = find_document(conn,cid,raw)
            old = self._document(conn, cid, row['id']) if row else None
            proposed = deepcopy(old or raw)
            reason = ''
            try:
                if not old: raise DomainError('Documento não existe; a cobrança não recria a escrituração.')
                if old['status'] != 'booked' or old.get('book_cancellation'):
                    raise DomainError('Escolha uma nota já escriturada e não cancelada.')
                if not raw.get('source_hash') or not any(s['source_hash'] == raw['source_hash'] for s in old['sources']):
                    raise DomainError('Origem não corresponde ao documento existente.')
                if any(old.get(k) != raw.get(k) for k in ('key', 'direction', 'model')):
                    raise DomainError('Identidade original divergente; revisão individual necessária.')
                if 'billing' not in proposed and 'billing' in raw:
                    proposed['billing'] = deepcopy(raw['billing'])
                    proposed['invoices'] = deepcopy(raw.get('invoices', []))
                    proposed['_billing_enriched'] = True
                plan = self._payables_plan(conn, cid, proposed, True)
                proposed['financial_posting'] = plan
                if plan['status'] == 'not_applicable':
                    raise DomainError('Esta nota não possui cobrança XML de compra para gerar.')
                if not plan['eligible']: raise DomainError(plan['reason'])
            except DomainError as exc:
                reason = exc.detail
            chosen = key in selected and (explicit_selection or not reason)
            rows.append({'index': index, '_selection': key, 'id': old['id'] if old else None,
                         'version': old['version'] if old else None, 'selected': chosen,
                         'eligible': not bool(reason), 'reason': reason, 'before': {}, 'after': {},
                         'diffs': {}, 'posting_lines': proposed.get('posting_lines', []),
                         'document': proposed, '_update': {}})
        selected_rows = [r for r in rows if r['selected']]
        from .import_payables import billing_signature
        grouped = {}
        for row in selected_rows:
            grouped.setdefault(row['id'], []).append(row)
        unique = {}
        for document_id, copies in grouped.items():
            first = unique[document_id] = copies[0]
            if len({billing_signature(r['document']) for r in copies}) > 1:
                for row in copies:
                    row['eligible'] = False
                    row['reason'] = 'Cópias da mesma nota contêm cobranças divergentes. Confira a origem e selecione apenas uma versão.'
            for row in copies[1:]: row['duplicate_of'] = first['_selection']
        installments = [p for r in unique.values() for p in r['document'].get('financial_posting', {}).get('installments', [])]
        from .operational_settings import get_settings
        fingerprint = digest({'batch': batch['preview_hash'], 'preserve_fiscal': True, 'rows': rows,
                              'operational_settings': get_settings(conn, cid)})
        return {'import_id': batch['id'], 'preserve_fiscal': True, 'reprocess_hash': fingerprint,
                'documents': rows, 'can_confirm': bool(selected_rows) and all(r['eligible'] for r in selected_rows),
                'billing_summary': {'documents': len(unique), 'installments': len(installments),
                                    'amount_cents': sum(p['amount_cents'] for p in installments)}}

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
            generated_options = self._generated_payables_options(payload)
            if payload.get('create_payables') or generated_options['enabled']:
                effect(conn, cid, 'financial.titles', 'create')
            if previous:
                for doc_id in previous['document_ids']:
                    doc = select_one(conn, 'documents', cid, doc_id)
                    if doc['status'] == 'booked' and not payload.get('preserve_fiscal'): effect(conn, cid, 'fiscal.documents', 'book')
                return previous
            plan = self._reprocess_plan(conn, cid, item_id, payload)
            if payload.get('reprocess_hash') != plan['reprocess_hash']:
                raise DomainError('Prévia desatualizada. Revise novamente antes de confirmar.', 409, 'reprocess_stale')
            if not plan['can_confirm']:
                raise DomainError('Há documentos selecionados bloqueados; nenhum foi alterado.', 409, 'reprocess_blocked')
            ids, titles = [], []
            for row in plan['documents']:
                if not row['selected'] or row['id'] in ids: continue
                if plan.get('preserve_fiscal'):
                    # Pass the verified source enrichment without rewriting the fiscal row.
                    titles.extend(self._create_import_payables(conn, cid, row['document'], row['document'], actor))
                    ids.append(row['id'])
                    continue
                self.update_document(cid, row['id'], dict(row['_update'], reason=reason), actor, _conn=conn)
                saved = select_one(conn, 'documents', cid, row['id'])
                extras = json.loads(saved['extra_json'])
                if row['document'].get('_billing_enriched'):
                    extras['billing'] = deepcopy(row['document']['billing'])
                    extras['invoices'] = deepcopy(row['document'].get('invoices', []))
                extras['import_posting'] = deepcopy(row['document']['import_posting'])
                extras['import_posting'].update(review_pending=True, last_edit_reason=reason, reprocessed_from_import=item_id)
                conn.execute('UPDATE documents SET extra_json=? WHERE id=? AND company_id=?', (pack(extras), row['id'], cid))
                if payload.get('create_payables'):
                    titles.extend(self._create_import_payables(conn, cid, self._document(conn, cid, row['id']), row['document'], actor))
                if generated_options['enabled']:
                    titles.extend(self._create_generated_payables(conn, cid, self._document(conn, cid, row['id']), row['document'], generated_options, actor))
                ids.append(row['id'])
            result = {'import_id': item_id, 'document_ids': ids, 'documents_updated': 0 if plan.get('preserve_fiscal') else len(ids), 'documents_created': 0, 'fiscal_preserved': bool(plan.get('preserve_fiscal'))}
            result.update(create_payables=payload.get('create_payables', False), generated_payables=generated_options, title_ids=[t['id'] for t in titles], titles_created=sum(not t.get('duplicate', False) for t in titles), titles_duplicate=sum(bool(t.get('duplicate')) for t in titles))
            audit(conn, cid, actor, 'reprocess', 'import', item_id, {'reason': reason, 'reprocess_hash': plan['reprocess_hash'], 'document_ids': ids})
            self._record_operation(conn, cid, scope, key, hashed, result)
            return result
