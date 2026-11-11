"""Direct fiscal posting from a checked import, without implicit cross-module effects."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json

from .cfop import cfop_at, company_cfop_at, mapping_key, reference, purchase_destination, select_import_mapping
from .core import DomainError, audit, check_version, digest, ensure_open, iso_date, now, pack, semantic_value, select_one, text, company_row
from .import_scope import classify
from .permissions import effect
from .tax_ledger import ensure_unfinalized


def original_business_key(document):
    if document.get('key'): return 'key:' + document['key']
    return digest({k: document.get(k, '') for k in ('direction', 'model', 'series', 'number', 'partner_tax_id', 'partner_name', 'issue_date')})


def validate_total_review(value):
    fields = {'basis', 'source', 'responsible', 'reason'}
    if not isinstance(value, dict) or set(value) != fields or value.get('basis') != 'vNF':
        raise DomainError('Revisão de totalizadores: informe basis=vNF, fonte, responsável e motivo. Outras bases não estão implementadas.')
    return {'basis': 'vNF', 'source': text(value['source'], 'Fonte da decisão dos totalizadores', True, 1000),
            'responsible': text(value['responsible'], 'Responsável pelos totalizadores', True, 200),
            'reason': text(value['reason'], 'Motivo da decisão dos totalizadores', True, 1000)}


def total_comparison(doc):
    if not doc.get('declared_new_total'): return {}
    try:
        current = Decimal(str(doc['total'])) if 'total' in doc else Decimal(str(doc['total_cents'])) / 100
        taxes = doc.get('taxes', {})
        original = [v for k, v in taxes.items() if k.replace('.', '/') == 'ICMSTot/vNF']
        value = Decimal(str(original[0])) if len(original) == 1 else current
        declared = Decimal(str(doc['declared_new_total']))
        if not all(v.is_finite() for v in (value, current, declared)): raise InvalidOperation()
    except (InvalidOperation, ValueError, KeyError, TypeError, AttributeError):
        raise DomainError('Totalizadores declarados inválidos; confira o XML original.') from None
    return {'vNF': format(value, '.2f'), 'document_total': format(current, '.2f'),
            'declared_new_total': str(doc['declared_new_total']), 'difference': format(declared - value, '.2f')}


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

    def _prepare_fiscal_import(self, conn, cid, batch, payload, *, preserve_item_cfops=False):
        from .import_payables import requested_payables
        create_payables = requested_payables(payload)
        parsed = json.loads(batch['parsed_json'])
        batch_total_review = validate_total_review(payload['total_review']) if 'total_review' in payload else None
        document_overrides = payload.get('document_overrides', {})
        valid_keys = {f'documents:{i}' for i in range(len(parsed['documents']))}
        generated_options = self._generated_payables_options(payload, valid_keys)
        if not isinstance(document_overrides, dict) or any(key not in valid_keys for key in document_overrides):
            raise DomainError('Revisões devem identificar documentos desta prévia.')
        for key, values in document_overrides.items():
            if not isinstance(values, dict) or set(values) - {'posting_date', 'cfop', 'purchase_destination', 'item_destinations', 'posting_date_confirmed', 'fiscal_treatment', 'posting_group_review', 'total_review', 'receipt_date'}:
                raise DomainError('Revise somente data de escrituração e CFOP; a origem permanece preservada.')
            doc = parsed['documents'][int(key.split(':')[1])]
            revision = {'original_posting_date': doc['posting_date'], 'original_cfop': doc.get('cfop', '')}
            if 'receipt_date' in values:
                doc['receipt_date'] = None if values['receipt_date'] in (None, '') else iso_date(values['receipt_date'], 'Chegada efetiva')
                revision['receipt_date'] = doc['receipt_date']
            if 'posting_date' in values:
                doc['posting_date'] = iso_date(values['posting_date'], 'Escrituração')
                doc['posting_date_proposed'] = False
                revision['posting_date'] = doc['posting_date']
            if values.get('cfop'):
                revision['cfop'] = text(values['cfop'], 'CFOP', True, 4)
            elif 'cfop' in values and not isinstance(values['cfop'], str):
                raise DomainError('CFOP: informe texto.')
            if 'posting_date_confirmed' in values:
                if not isinstance(values['posting_date_confirmed'], bool): raise DomainError('Confirmação de competência deve ser booleana.')
                revision['posting_date_confirmed'] = values['posting_date_confirmed']
            if 'purchase_destination' in values:
                revision['purchase_destination'] = purchase_destination(values['purchase_destination'])
            if 'item_destinations' in values:
                destinations = values['item_destinations']
                numbers = {str(i.get('number')) for i in doc.get('items', [])}
                if not isinstance(destinations, dict) or set(destinations) - numbers:
                    raise DomainError('Destinações devem identificar itens deste documento.')
                revision['item_destinations'] = {k: purchase_destination(v) for k, v in destinations.items()}
            if 'fiscal_treatment' in values:
                from .fiscal_analytics import validate_fiscal_treatment
                revision['fiscal_treatment'] = validate_fiscal_treatment(values['fiscal_treatment'], doc['posting_date'])
                doc['fiscal_treatment'] = revision['fiscal_treatment']
            if 'total_review' in values:
                revision['total_review'] = None if values['total_review'] is None else validate_total_review(values['total_review'])
            if 'posting_group_review' in values:
                revision['posting_group_review'] = values['posting_group_review']
            doc['_import_revision'] = revision
        parsed = classify(conn, cid, parsed, batch['period'][:4])
        overrides = payload.get('cfop_mappings', {})
        if not isinstance(overrides, dict) or len(overrides) > 200 or any(not isinstance(k, str) or not isinstance(v, str) for k, v in overrides.items()):
            raise DomainError('Associações do lote devem relacionar origem e CFOP de destino.')
        batch_destination = purchase_destination(payload.get('purchase_destination', ''))
        settings = self.fiscal_import_settings(cid, conn)
        company = company_row(conn, cid)
        saved = self.import_cfop_mappings(cid, conn)
        catalogs = self._company_cfop_catalogs(conn, cid)
        prepared = []
        for raw in parsed['documents']:
            doc = deepcopy(raw)
            info = {'eligible': False, 'reason': '', 'mappings': [], 'reference_edition': reference()['edition'], 'original_business_key': original_business_key(raw), 'review_pending': True, 'document_revision': doc.get('_import_revision', {})}
            try:
                doc['total_comparison'] = total_comparison(doc)
                info['total_comparison'] = doc['total_comparison']
                decision = doc.get('_import_revision', {}).get('total_review', batch_total_review)
                if decision:
                    doc['total_review'] = deepcopy(decision)
                    info['total_review'] = deepcopy(decision)
                    info['total_review_origin'] = 'document' if 'total_review' in doc.get('_import_revision', {}) else 'batch'
                if doc['_eligibility']['status'] != 'eligible': raise DomainError(doc['_eligibility']['reason'])
                if doc['direction'] == 'incoming' and doc.get('posting_date_proposed') and not doc.get('_import_revision', {}).get('posting_date_confirmed'):
                    raise DomainError('Confira recebimento e competência: a data de escrituração foi sugerida pela emissão e precisa de confirmação explícita.')
                ensure_unfinalized(conn, cid, doc['posting_date'][:7])
                if doc.get('environment') == '2': raise DomainError('XML de homologação: mantenha em conferência, sem escrituração direta.')
                # These warnings require a document decision, not a silent batch assumption.
                related = [i for i in parsed['issues'] if i.get('source', {}).get('file') == doc.get('source', {}).get('file')]
                if any(i.get('code') in {'XML_NO_PROTOCOL', 'THIRD_PARTY_ENTRY_REVIEW'} for i in related):
                    raise DomainError('Documento exige conferência individual de autorização, direção ou totalizadores antes de escriturar.')
                if any(i.get('code') == 'RTC_TOTAL_REVIEW' for i in related) and not decision:
                    raise DomainError('Confira vNF e vNFTot: declare fonte, responsável e motivo para escriturar pela base vNF. A decisão não certifica o tratamento legal RTC.')
                rows = doc.get('items') if doc.get('items') and doc['model'] in {'55', '65'} else doc.get('analytics') or [doc]
                for item in rows:
                    source = item.get('source_cfop') or item.get('cfop') or (doc.get('source_cfops') or [''])[0]
                    if source: cfop_at(source, doc['posting_date'])
                    target = item.get('cfop') or doc.get('cfop') or ''
                    revision = doc.get('_import_revision', {})
                    destination, destination_origin = '', ''
                    for value, origin in ((revision.get('item_destinations', {}).get(str(item.get('number'))), 'item'), (revision.get('purchase_destination'), 'document'), (batch_destination, 'batch'), (settings['purchase_destination'], 'company')):
                        if value:
                            destination, destination_origin = value, origin
                            break
                    explicit_destination = revision.get('item_destinations', {}).get(str(item.get('number'))) or revision.get('purchase_destination') or batch_destination
                    if preserve_item_cfops and target and not explicit_destination:
                        destination, destination_origin = item.get('purchase_destination', ''), 'existing_document'
                    item['purchase_destination'] = destination
                    key = mapping_key(doc['direction'], doc['model'], source)
                    if doc.get('_import_revision', {}).get('cfop'):
                        target = doc['_import_revision']['cfop']
                        info['mappings'].append({'source_cfop': source, 'target_cfop': target, 'origin': 'document', 'key': key})
                    elif key in overrides:
                        target = overrides[key]
                        info['mappings'].append({'source_cfop': source, 'target_cfop': target, 'origin': 'batch', 'key': key})
                    elif preserve_item_cfops and target and not explicit_destination:
                        info['mappings'].append({'source_cfop': source, 'target_cfop': target, 'origin': 'existing_document', 'key': key})
                    elif not target or (doc['direction'] == 'incoming' and source.startswith(('5', '6', '7'))):
                        mapping = select_import_mapping(saved, doc, item, source, destination)
                        if mapping:
                            target = mapping['data']['target_cfop']
                            issuer_state, company_state = doc.get('issuer', {}).get('state', ''), company['state']
                            states = set('AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO'.split())
                            if doc['direction'] == 'incoming' and issuer_state in states | {'EX'} and company_state in states:
                                expected = '3' if issuer_state == 'EX' else ('1' if issuer_state == company_state else '2')
                                if not target.startswith(expected):
                                    raise DomainError('Regra específica incompatível com UF do emitente e da empresa; revise o CFOP e o contexto da operação.')
                            info['mappings'].append({'source_cfop': source, 'target_cfop': target, 'origin': 'company', 'mapping_id': mapping['id'], 'version': mapping['version'], 'responsible': mapping['data']['responsible'], 'mapping_snapshot': mapping['data']})
                        else:
                            matches = [m for m in settings['fallback_mappings'] if doc['direction'] == 'incoming' and destination and m['purchase_destination'] == destination and m['source_cfop'] == source and m['valid_from'] <= doc['posting_date'] <= (m['valid_to'] or '9999-12-31')]
                            if len(matches) != 1:
                                raise DomainError(f'CFOP de origem {source or "ausente"}: informe a associação da operação da empresa e a destinação da compra.')
                            if source not in {'5101', '5102', '6101', '6102', '5401', '5403', '5405', '6401', '6403', '6404'}:
                                raise DomainError('Natureza da operação exige regra específica e revisão: padrão de compra não converte devolução, remessa, bonificação, transferência ou frete.')
                            fallback = matches[0]
                            target = fallback['target_cfop']
                            issuer_state = doc.get('issuer', {}).get('state', '')
                            company_state = company['state']
                            brazil_states = set('AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO'.split())
                            if issuer_state not in brazil_states | {'EX'} or company_state not in brazil_states:
                                raise DomainError('Padrão de compra exige UF do emitente e da empresa; revise o documento.')
                            prefix = '3' if issuer_state == 'EX' else ('1' if issuer_state == company_state else '2')
                            if not target.startswith(prefix) or (source.startswith(('5', '6', '7')) and source[0] != {'1': '5', '2': '6', '3': '7'}[prefix]):
                                raise DomainError('Padrão de compra incompatível com UF do emitente/empresa e natureza interna, interestadual ou importação.')
                            info['mappings'].append({'source_cfop': source, 'target_cfop': target, 'origin': 'fallback', 'version': settings['version'], 'responsible': settings.get('responsible', ''), 'reason': settings.get('reason', ''), 'mapping_snapshot': fallback, 'source_catalog_version': settings.get('source_catalog_version', ''), 'catalog_imported_by': settings.get('catalog_imported_by', ''), 'catalog_imported_at': settings.get('catalog_imported_at', ''), 'issuer_state': issuer_state, 'company_state': company_state})
                    if info['mappings'] and info['mappings'][-1].get('item_number') is None:
                        info['mappings'][-1].update(item_number=str(item.get('number', '')), purchase_destination=destination, destination_origin=destination_origin)
                    company_cfop_at(target, doc['posting_date'], doc['direction'], catalogs)
                    item['cfop'] = target
                codes = sorted({r['cfop'] for r in rows})
                doc['cfop'] = codes[0] if len(codes) == 1 else ''
                if doc.get('_import_revision', {}).get('posting_group_review') is not None:
                    from .fiscal_analytics import validate_posting_group_review
                    doc['posting_group_review'] = validate_posting_group_review(doc['_import_revision']['posting_group_review'], doc)
                info.update(eligible=True, reason='Pronto para escrituração fiscal direta')
            except DomainError as exc:
                info['reason'] = exc.detail
            from .fiscal_analytics import fiscal_posting_lines
            doc['posting_lines'] = fiscal_posting_lines(doc)
            info['posting_line_count'] = len(doc['posting_lines'])
            info['posting_pending'] = sorted({reason for line in doc['posting_lines'] for reason in line.get('pending', [])})
            doc['generated_financial_posting'] = self._generated_payables_plan(conn, cid, doc, generated_options)
            doc['financial_posting'] = self._payables_plan(conn, cid, doc, create_payables)
            doc['import_posting'] = info
            prepared.append(doc)
        parsed['documents'] = prepared
        parsed['posting_hash'] = digest({'preview_hash': batch['preview_hash'], 'generated_payables': generated_options, 'documents': semantic_value(prepared), 'edition': reference()['edition'], 'mappings': overrides, 'document_overrides': document_overrides, 'purchase_destination': batch_destination, 'settings': settings, 'total_review': batch_total_review})
        return parsed

    def fiscal_posting_preview(self, cid, item_id, payload):
        with self.db.read(snapshot=True) as conn:
            batch = select_one(conn, 'imports', cid, item_id)
            effect(conn, cid, 'fiscal.imports', 'read')
            return self._prepare_fiscal_import(conn, cid, batch, payload)

    def fiscal_import_auxiliary(self, cid, item_id, index):
        from .auditor_sources import original_xmls
        from .auxiliary import render_danfe
        with self.db.read(snapshot=True) as conn:
            batch = select_one(conn, 'imports', cid, item_id)
            effect(conn, cid, 'fiscal.imports', 'read')
            effect(conn, cid, 'fiscal.imports', 'export')
            documents = json.loads(batch['parsed_json'])['documents']
            if not 0 <= index < len(documents):
                raise DomainError('Documento não pertence à prévia.', 404, 'not_found')
            document = documents[index]
            if document.get('model') not in {'55', '65', '57'} or not document.get('source', {}).get('file', '').lower().endswith('.xml'):
                raise DomainError('Documento auxiliar disponível somente para XML de NF-e, NFC-e ou CT-e suportado.', 422, 'renderer_not_validated')
            raw, filename = batch['original'], batch['filename']
        # Reuse bounded archive readers and verify the exact source, even for
        # repeated member basenames. Nothing is written or imported by viewing.
        for _, content in original_xmls(filename, raw):
            if digest(content) == document.get('source_hash'):
                pdf, renderer = render_danfe(content)
                return pdf, renderer, document['number']
        raise DomainError('XML original correspondente indisponível.', 422, 'source_unavailable')

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
        # Actual arrival is independent metadata. The normal version, date,
        # period, assessment and audit guards still run in update_document.
        if 'receipt_date' in payload and set(payload) <= {'receipt_date', 'version', 'reason'}:
            return
        linked = conn.execute('SELECT 1 FROM titles WHERE company_id=? AND document_id=?', (cid, old['id'])).fetchone()
        if old['journal_id'] or (linked and not self._safe_payables_classification(conn, cid, old, payload)):
            raise DomainError('Há efeitos contábeis ou financeiros vinculados. Reverta a escrituração e seus efeitos antes de editar.', 409, 'document_linked_effects')
        if old['source_hash'] and any(payload.get(k, old[k]) != old[k] for k in ('key', 'direction', 'model')):
            raise DomainError('A identidade e o sentido do documento importado devem ser preservados. Corrija a origem ou reverta a escrituração.', 409, 'import_identity_preserved')

    def _validate_posted_classification(self, conn, cid, document):
        catalogs = self._company_cfop_catalogs(conn, cid)
        if document.get('cfop'): company_cfop_at(document['cfop'], document['posting_date'], document['direction'], catalogs)
        rows = document['items'] if document.get('items') and document['model'] in {'55', '65'} else document.get('analytics') or [document]
        for row in rows: company_cfop_at(row.get('cfop') or document.get('cfop'), document['posting_date'], document['direction'], catalogs)
