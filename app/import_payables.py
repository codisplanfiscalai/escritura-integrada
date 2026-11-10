"""Explicit, atomic XML billing import. Never creates payments or settlements."""
from decimal import Decimal
from .core import DomainError, digest, ensure_open, iso_date, money
from .permissions import effect


def requested_payables(payload):
    value = payload.get('create_payables', False)
    if not isinstance(value, bool):
        raise DomainError('Gerar contas a pagar deve ser uma escolha booleana explícita.')
    return value


def billing_signature(doc):
    billing = doc.get('billing') or {}
    invoice = billing.get('invoice') or {}
    return digest({'invoice': {k: invoice.get(k) for k in ('number', 'original_amount', 'discount', 'net_amount')},
                   'installments': [{k: row.get(k) for k in ('number', 'due_date', 'amount')} for row in billing.get('installments', [])],
                   'issue_date': doc.get('issue_date'), 'partner_tax_id': doc.get('partner_tax_id'),
                   'direction': doc.get('direction')})


class ImportPayablesMixin:
    def _billing_rows(self, doc):
        billing = doc.get('billing') or {}
        if doc.get('direction') != 'incoming' or not billing.get('present'):
            return []
        if billing.get('issues') or billing.get('financial_rules_pending'):
            raise DomainError('Cobrança XML exige revisão financeira: confira os avisos, valores e vencimentos.')
        rows = billing.get('installments') or []
        if not rows:
            raise DomainError('Cobrança sem duplicatas completas: não é possível inventar parcelas ou vencimentos.')
        seen, result = set(), []
        issue = iso_date(doc.get('issue_date'), 'Emissão')
        for index, row in enumerate(rows, 1):
            number = row.get('number')
            if not isinstance(number, str) or not number.strip() or number in seen:
                raise DomainError('Número da duplicata ausente ou repetido; revise a cobrança.')
            seen.add(number)
            due = iso_date(row.get('due_date'), 'Vencimento')
            if due < issue: raise DomainError('Vencimento da duplicata anterior à emissão.')
            cents = money(row.get('amount'), 'Valor da duplicata', positive=True)
            result.append({'number': number, 'due_date': due, 'amount_cents': cents,
                           'amount': format(Decimal(cents) / 100, '.2f'), 'installment': index})
        return result

    def _matching_import_payables(self, conn, cid, doc, rows):
        titles = [dict(r) for r in conn.execute('SELECT * FROM titles WHERE company_id=? AND document_id=? ORDER BY installment,id', (cid, doc['id']))]
        if not titles: return []
        expected = {(f"generated-billing:{doc['id']}:single" if r.get("origin") == "generated_rule" else f"xml-billing:{doc['id']}:{digest(r['number'])}"): r for r in rows}
        if len(titles) != len(expected): raise DomainError('Títulos vinculados divergem da cobrança XML; revisão manual necessária.')
        for title in titles:
            row = expected.get(title.get('source_key'))
            if (not row or title['cancelled'] or title.get('renegotiation_id') or
                title['kind'] != 'payable' or title['document'] != row['number'] or
                title['installment'] != row['installment'] or
                title['description'] != (f"NF {doc['number']} / condição de compra definida pelo usuário" if row.get("origin") == "generated_rule" else f"NF {doc['number']} / duplicata {row['number']}") or
                title['amount_cents'] != row['amount_cents'] or title['due_date'] != row['due_date'] or
                title['issue_date'] != doc['issue_date'] or title.get('participant_id') != doc.get('participant_id') or
                conn.execute('SELECT 1 FROM settlements WHERE company_id=? AND title_id=?', (cid, title['id'])).fetchone() or
                conn.execute('SELECT 1 FROM bank_allocations WHERE company_id=? AND title_id=? AND reversed_at IS NULL', (cid, title['id'])).fetchone()):
                raise DomainError('Título manual, alterado, baixado, cancelado ou renegociado exige revisão manual; nada será recriado.')
        return titles

    def _payables_plan(self, conn, cid, doc, requested=False):
        plan = {'requested': requested, 'eligible': False, 'reason': '', 'installments': [], 'title_ids': [], 'status': 'not_applicable', 'payments_created': False}
        if doc.get('direction') != 'incoming' or not (doc.get('billing') or {}).get('present'): return plan
        plan['status'] = 'blocked'
        try:
            effect(conn, cid, 'financial.titles', 'create')
            rows = self._billing_rows(doc)
            plan['installments'] = rows
            ensure_open(conn, cid, iso_date(doc['issue_date'])[:7], 'financial')
            existing = None
            if doc.get('id'):
                existing = self._document(conn, cid, doc['id'])
            else:
                from .fiscal_import import original_business_key
                match = conn.execute('SELECT id FROM documents WHERE company_id=? AND business_key=?', (cid, original_business_key(doc))).fetchone()
                if match: existing = self._document(conn, cid, match['id'])
            if existing:
                legacy_enrichment = (doc.get('_billing_enriched') and 'billing' not in existing and
                                     any(s['source_hash'] == doc.get('source_hash') for s in existing.get('sources', [])))
                if not legacy_enrichment and billing_signature(existing) != billing_signature(doc):
                    raise DomainError('Cobrança ou origem financeira divergente do documento existente; revisão manual necessária.')
                titles = self._matching_import_payables(conn, cid, existing, rows)
                plan['title_ids'] = [t['id'] for t in titles]
            plan.update(eligible=True, status='existing' if plan['title_ids'] else 'ready')
        except DomainError as exc:
            plan['reason'] = exc.detail
        return plan

    def _create_import_payables(self, conn, cid, doc, source, actor):
        if billing_signature(doc) != billing_signature(source):
            raise DomainError('Cobrança divergente da nota existente; revisão manual necessária.', 409, 'import_payables_blocked')
        proposed = dict(source, id=doc['id'])
        plan = self._payables_plan(conn, cid, proposed, True)
        if plan['status'] == 'not_applicable': return []
        if not plan['eligible']: raise DomainError(plan['reason'], 409, 'import_payables_blocked')
        effect(conn, cid, 'financial.titles', 'create')
        if plan['title_ids']: return [self._title(conn, cid, i) | {'duplicate': True} for i in plan['title_ids']]
        return [self._create_title(conn, cid, {
            'kind': 'payable', 'document_id': doc['id'], 'participant_id': doc.get('participant_id'),
            'partner_name': doc['partner_name'], 'document': row['number'],
            'description': f"NF {doc['number']} / duplicata {row['number']}",
            'issue_date': doc['issue_date'], 'due_date': row['due_date'], 'amount': row['amount'],
            'installment': row['installment'], 'source_key': f"xml-billing:{doc['id']}:{digest(row['number'])}"
        }, actor, _historical_document_id=doc['id']) for row in plan['installments']]

    def _safe_payables_classification(self, conn, cid, old, payload):
        doc = self._document(conn, cid, old['id'])
        try:
            rows = (doc.get('generated_payment_terms') or {}).get('installments') or self._billing_rows(doc)
            titles = self._matching_import_payables(conn, cid, doc, rows)
        except DomainError:
            return False
        if not titles: return False
        allowed = {'cfop', 'posting_date', 'posting_date_confirmed', 'purchase_destination', 'items',
                   'fiscal_treatment', 'posting_group_review', 'total_review', 'version', 'reason', 'receipt_date'}
        if set(payload) - allowed: return False
        if 'items' in payload:
            strip = lambda items: [{k: v for k, v in i.items() if k not in {'cfop', 'purchase_destination'}} for i in items]
            if strip(payload['items']) != strip(doc['items']): return False
        return True

    def _generated_payables_options(self, payload, valid=None):
        from .core import text
        options = payload.get('generated_payables', {})
        if not isinstance(options, dict) or set(options) - {'enabled', 'selected', 'supplier_tax_ids', 'term_days', 'date_basis', 'responsible', 'reason', 'overrides'}:
            raise DomainError('Regra de contas a pagar inválida.')
        if not isinstance(options.get('enabled', False), bool): raise DomainError('Habilitação da regra deve ser booleana.')
        if not options.get('enabled'): return {'enabled': False}
        selected, suppliers = options.get('selected', []), options.get('supplier_tax_ids', [])
        if not isinstance(selected, list) or any(not isinstance(k, str) or (valid is not None and k not in valid) for k in selected):
            raise DomainError('Selecione notas desta prévia para a regra financeira.')
        if isinstance(suppliers, list):
            suppliers = [k.replace('.', '').replace('/', '').replace('-', '').strip() if isinstance(k, str) else k for k in suppliers]
        if not isinstance(suppliers, list) or any(not isinstance(k, str) or len(k) != 14 or not k.isdigit() for k in suppliers):
            raise DomainError('Informe CNPJs de fornecedores com 14 dígitos.')
        if not selected and not suppliers: raise DomainError('Escolha explicitamente notas ou CNPJs para aplicar o prazo.')
        days = options.get('term_days', 30)
        if isinstance(days, bool) or not isinstance(days, int) or not 0 <= days <= 3650:
            raise DomainError('Prazo deve ser inteiro entre 0 e 3650 dias.')
        basis = options.get('date_basis')
        if basis not in {'issue', 'receipt'}: raise DomainError('Escolha emissão ou chegada efetiva como base do prazo.')
        overrides = options.get('overrides', {})
        if not isinstance(overrides, dict) or any((valid is not None and k not in valid) or not isinstance(v, dict) or set(v) - {'amount', 'due_date', 'reason'} for k, v in overrides.items()):
            raise DomainError('Revisões financeiras devem identificar notas desta prévia.')
        return {'enabled': True, 'selected': selected, 'supplier_tax_ids': suppliers, 'term_days': days,
                'date_basis': basis, 'responsible': text(options.get('responsible'), 'Responsável pela condição', True, 200),
                'reason': text(options.get('reason'), 'Motivo da condição', True, 1000), 'overrides': overrides}

    def _generated_payables_plan(self, conn, cid, doc, options):
        from datetime import date, timedelta
        from .core import text
        plan = {'requested': False, 'eligible': False, 'status': 'not_applicable', 'reason': '',
                'origin': 'generated_rule', 'installments': [], 'title_ids': [], 'payments_created': False}
        selected = options.get('enabled') and (doc.get('_selection') in options['selected'] or doc.get('partner_tax_id') in options['supplier_tax_ids'])
        if not selected: return plan
        plan['requested'] = True
        if doc.get('direction') != 'incoming':
            plan['reason'] = 'Regra disponível somente para entradas de compra.'
            plan['status'] = 'blocked'
            return plan
        if (doc.get('billing') or {}).get('present') or doc.get('invoices'):
            plan['reason'] = 'Cobrança original existente, mesmo incompleta: use a revisão da cobrança XML, sem substituir por regra.'
            return plan
        plan['status'] = 'blocked'
        if not isinstance(doc.get('billing'), dict) or doc['billing'].get('present') is not False:
            plan['reason'] = 'Ausência de cobrança não verificada no XML original. Recupere a origem antes de gerar uma parcela por regra.'
            return plan
        try:
            effect(conn, cid, 'financial.titles', 'create')
            purchases = {'1101','1102','2101','2102','3101','3102','1401','1403','2401','2403','3401','3403','1551','2551','3551','1556','2556','3556','1406','1407','2406','2407'}
            codes = {i.get('cfop') or doc.get('cfop') for i in doc.get('items', [])} or {doc.get('cfop')}
            if not codes <= purchases:
                raise DomainError('Natureza não reconhecida como compra: bonificação, devolução, remessa e outras operações exigem revisão manual, sem título automático.')
            base = iso_date(doc.get('issue_date') if options['date_basis'] == 'issue' else doc.get('receipt_date'), 'Data de chegada efetiva' if options['date_basis'] == 'receipt' else 'Emissão')
            due = (date.fromisoformat(base) + timedelta(days=options['term_days'])).isoformat()
            override = options['overrides'].get(doc.get('_selection'), {})
            amount = doc.get('total') if 'total' in doc else format(Decimal(doc['total_cents']) / 100, '.2f')
            if override:
                override_reason = text(override.get('reason'), 'Motivo da revisão financeira', True, 1000)
                due = iso_date(override.get('due_date', due), 'Vencimento revisado')
                amount = override.get('amount', amount)
            else: override_reason = ''
            if due < doc['issue_date'] or due < base: raise DomainError('Vencimento não pode anteceder emissão ou base escolhida.')
            cents = money(amount, 'Valor revisado da parcela', positive=True)
            ensure_open(conn, cid, iso_date(doc['issue_date'])[:7], 'financial')
            row = {'number': f"{doc['number']}/1", 'due_date': due, 'amount_cents': cents, 'amount': format(Decimal(cents)/100, '.2f'), 'installment': 1, 'origin': 'generated_rule'}
            terms = {'source': 'user_purchase_terms', 'origin': 'generated_rule', 'date_basis': options['date_basis'], 'base_date': base,
                     'term_days': options['term_days'], 'responsible': options['responsible'], 'reason': options['reason'],
                     'override_reason': override_reason, 'installments': [row]}
            plan.update(installments=[row], terms=terms)
            from .fiscal_import import original_business_key
            found = conn.execute('SELECT id FROM documents WHERE company_id=? AND business_key=?', (cid, original_business_key(doc))).fetchone()
            if found:
                old = self._document(conn, cid, found['id'])
                if (old.get('billing') or {}).get('present') or old.get('invoices'):
                    raise DomainError('Documento existente possui cobrança original; regra alternativa não será aplicada.')
                if ((old.get('billing') or {}).get('present') is not False and
                    not any(s['source_hash'] == doc.get('source_hash') for s in old.get('sources', []))):
                    raise DomainError('Cobrança do documento existente não verificada. Recupere o mesmo XML original antes de gerar uma parcela por regra.')
                titles = self._matching_import_payables(conn, cid, old, [row])
                if titles:
                    previous = old.get('generated_payment_terms') or {}
                    if any(previous.get(k) != terms.get(k) for k in ('date_basis', 'base_date', 'term_days', 'installments')):
                        raise DomainError('Condições do título existente divergentes; revisão manual necessária.')
                    plan['title_ids'] = [t['id'] for t in titles]
            plan.update(eligible=True, status='existing' if plan['title_ids'] else 'ready')
        except DomainError as exc:
            plan['reason'] = exc.detail
        return plan

    def _create_generated_payables(self, conn, cid, doc, source, options, actor):
        from .core import audit, pack
        plan = self._generated_payables_plan(conn, cid, source, options)
        if plan['status'] == 'not_applicable': return []
        if not plan['eligible']: raise DomainError(plan['reason'], 409, 'generated_payables_blocked')
        effect(conn, cid, 'financial.titles', 'create')
        if plan['title_ids']: return [self._title(conn, cid, i) | {'duplicate': True} for i in plan['title_ids']]
        row = plan['installments'][0]
        title = self._create_title(conn, cid, {
            'kind': 'payable', 'document_id': doc['id'], 'participant_id': doc.get('participant_id'),
            'partner_name': doc['partner_name'], 'document': row['number'],
            'description': f"NF {doc['number']} / condição de compra definida pelo usuário",
            'issue_date': doc['issue_date'], 'due_date': row['due_date'], 'amount': row['amount'],
            'installment': 1, 'source_key': f"generated-billing:{doc['id']}:single"}, actor, _historical_document_id=doc['id'])
        import json
        saved = conn.execute('SELECT extra_json FROM documents WHERE company_id=? AND id=?', (cid, doc['id'])).fetchone()
        extras = json.loads(saved['extra_json']); extras['generated_payment_terms'] = plan['terms']
        conn.execute('UPDATE documents SET extra_json=? WHERE company_id=? AND id=?', (pack(extras), cid, doc['id']))
        audit(conn, cid, actor, 'generate-purchase-payable', 'document', doc['id'], {'terms': plan['terms'], 'title_id': title['id'], 'payments_created': False})
        return [title]
