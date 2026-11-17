"""Explicit, atomic accounting of booked fiscal documents; no implicit chart or tax mapping.

The persisted mode applies only to this batch service. Each source contribution is
saved in the existing immutable audit trail, independently of import retention.
"""
import json
from fastapi import Body, Request
from .core import (DomainError, audit, check_version, company_row, decimal_text,
                   digest, ensure_open, integer, now, pack, text)
from .permissions import effect, readable
from .db import request_context

SCOPE = 'fiscal-sales-accounting'
SOURCE = 'sales-accounting-source'
REVERSAL = 'sales-accounting-reversal'
NOTICE = ('A escolha vale para novas notas desta integração. Notas já contabilizadas e '
          'lançamentos anteriores são preservados. Seleções posteriores geram lançamentos '
          'complementares, inclusive no mesmo dia. O Diário Consolidado é somente um relatório.')


def settings(conn, cid):
    company_row(conn, cid)
    row = conn.execute('SELECT value FROM meta WHERE key=?', (f'{SCOPE}:{cid}',)).fetchone()
    return (json.loads(row['value']) if row else {'version': 0, 'mode': 'individual'}) | {'notice': NOTICE}


def classification(doc):
    """Use the fiscal book normalizer for XML tax paths and SPED C190 fields.

    Keep heterogeneous signatures separate; never allocate totals across items.
    """
    from .fiscal_analytics import _base
    fields = ('cfop', 'cst_icms', 'csosn', 'origin', 'rate', 'treatment')
    signatures = set()
    for row in (doc.get('analytics') or doc.get('items') or [doc]):
        normalized = _base(doc, row, 'accounting_source')
        signature = {k: normalized[k] for k in fields}
        # Also preserve classifications outside the existing ICMS book normalizer.
        signature.update({k: row[k] for k in ('cst', 'ncm', 'cclass_trib', 'extipi') if row.get(k) is not None})
        signature['declared_tax_classifications'] = {
            path: value for path, value in row.get('taxes', {}).items()
            if path.replace('.', '/').split('/')[-1] in {'CST', 'CSOSN', 'cClassTrib', 'orig', 'cEnq'}}
        signatures.add(pack(signature))
    return {'model': doc['model'], 'cfop': doc['cfop'],
            'item_classifications': [json.loads(s) for s in sorted(signatures)]}


def ensure_sales_open(conn, cid, competence, module):
    # The new integration always honors an explicit closure, even when legacy
    # operational settings permit ignoring locks in older entry points.
    ensure_open(conn, cid, competence, module)
    row = conn.execute('SELECT closed FROM period_locks WHERE company_id=? AND period=? AND module=?',
                       (cid, competence, module)).fetchone()
    if row and row['closed']:
        raise DomainError(f'A competência {competence} está fechada no módulo {module}. Reabra antes de alterar.', 409, 'period_closed')


def source_events(conn, cid, item_id, *, include_model=True):
    events = [json.loads(r['details_json']) for r in conn.execute(
        "SELECT details_json FROM audit WHERE company_id=? AND entity='document' AND entity_id=? AND action=? ORDER BY id",
        (cid, str(item_id), SOURCE))]
    if not include_model:
        for event in events:
            event.pop('model_snapshot', None)
    return events


def journal_lines(lines, reverse=False):
    return [{'account_id': x['account_id'],
             'debit': decimal_text(x['credit_cents'] if reverse else x['debit_cents']),
             'credit': decimal_text(x['debit_cents'] if reverse else x['credit_cents']),
             'cost_center_id': x.get('cost_center_id'), 'participant_id': x.get('participant_id')}
            for x in lines]


class FiscalSalesAccountingMixin:
    def fiscal_sales_accounting_settings(self, cid):
        with self.db.read() as conn:
            effect(conn, cid, 'accounting.accounts', 'read')
            return settings(conn, cid)

    def save_fiscal_sales_accounting_settings(self, cid, payload, actor):
        with self.db.transaction() as conn:
            effect(conn, cid, 'accounting.accounts', 'edit')
            old = settings(conn, cid)
            if set(payload) != {'version', 'mode'} or not isinstance(payload.get('mode'), str) or payload['mode'] not in {'individual', 'daily'}:
                raise DomainError('Informe versão e modo individual ou daily.')
            if type(payload.get('version')) is not int or payload['version'] != old['version']:
                raise DomainError('Os parâmetros mudaram. Atualize antes de salvar.', 409, 'stale_version')
            saved = {'version': old['version'] + 1, 'mode': payload['mode'], 'updated_at': now()}
            conn.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                         (f'{SCOPE}:{cid}', pack(saved)))
            audit(conn, cid, actor, 'configure', SCOPE, cid, {'before': old, 'after': saved})
            return saved | {'notice': NOTICE}

    def fiscal_accounting_payments(self, cid, payload):
        from .fiscal_payment_allocations import payment_evidence
        entries = payload.get('entries')
        if set(payload) != {'entries'} or not isinstance(entries, list) or not 1 <= len(entries) <= 1000:
            raise DomainError('Selecione de 1 a 1000 notas para consultar pagamentos.')
        with self.db.read(snapshot=True) as conn:
            effect(conn, cid, 'fiscal.documents', 'read')
            effect(conn, cid, 'accounting.accounts', 'read')
            from .fiscal_payment_sources import RetainedPaymentSources
            retained = RetainedPaymentSources(conn, cid)
            result = []
            for entry in entries:
                if not isinstance(entry, dict) or set(entry) != {'document_id', 'version'}:
                    raise DomainError('Seleção de nota inválida.')
                doc = self._document(conn, cid, integer(entry.get('document_id'), 'Documento'))
                check_version(doc, entry)
                ctx = request_context.get() or {}
                if ctx.get('year') and doc['period'][:4] != ctx['year']:
                    raise DomainError('Selecione o exercício da escrituração.', 409, 'stale_context')
                try:
                    evidence = payment_evidence(doc, retained=retained)
                    result.append({'document_id': doc['id'], 'version': doc['version'], **evidence, 'issue': ''})
                except DomainError as exc:
                    result.append({'document_id': doc['id'], 'version': doc['version'], 'payments': [], 'issue': str(exc)})
            return {'documents': result}

    def generate_sales_accounting(self, cid, payload, actor):
        return self._integrate_fiscal_accounting(cid, payload, actor)

    def generate_purchase_accounting(self, cid, payload, actor):
        return self._integrate_fiscal_accounting(cid, payload, actor, direction='incoming')

    def preview_fiscal_accounting(self, cid, payload, direction='outgoing'):
        return self._integrate_fiscal_accounting(cid, payload, None, direction=direction, preview=True)

    def _integrate_fiscal_accounting(self, cid, payload, actor, *, direction='outgoing', preview=False):
        incoming = direction == 'incoming'
        operation_scope = 'fiscal-purchases-accounting' if incoming else SCOPE
        if set(payload) - {'entries', 'settings_version', 'idempotency_key', 'reason'}:
            raise DomainError('Campos desconhecidos na integração contábil.')
        entries = payload.get('entries')
        if not isinstance(entries, list) or not 1 <= len(entries) <= 1000:
            raise DomainError('Selecione de 1 a 1000 notas com as contas ou modelos contábeis opcionais.')
        ids = []
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) - {'document_id', 'version', 'model_id', 'debit_account_id', 'credit_account_id', 'cost_center_id', 'payment_accounts', 'change_allocations'}:
                raise DomainError('Seleção de nota inválida.')
            if 'change_allocations' in entry and 'payment_accounts' not in entry:
                raise DomainError('Troco exige rateio por pagamentos.')
            if 'payment_accounts' in entry and (incoming or 'debit_account_id' in entry or entry.get('model_id') is not None):
                raise DomainError('Rateio por pagamentos é exclusivo de saídas, sem débito único ou modelo na mesma nota.')
            if entry.get('model_id') is not None and {'debit_account_id', 'credit_account_id', 'cost_center_id'} & set(entry):
                raise DomainError('Escolha contas diretas ou modelo para cada nota, sem misturar as duas formas.')
            ids.append(integer(entry.get('document_id'), 'Documento'))
        if len(set(ids)) != len(ids):
            raise DomainError('Selecione cada documento uma única vez.')
        with (self.db.read(snapshot=True) if preview else self.db.transaction()) as conn:
            effect(conn, cid, 'fiscal.documents', 'read')
            effect(conn, cid, 'accounting.journals', 'read' if preview else 'create')
            if any(entry.get('model_id') is not None for entry in entries):
                effect(conn, cid, 'accounting.histories', 'read')
            if not preview:
                key, hashed, previous = self._operation(conn, cid, operation_scope, payload)
                if previous:
                    return previous
            cfg = settings(conn, cid)
            if type(payload.get('settings_version')) is not int or payload['settings_version'] != cfg['version']:
                raise DomainError('O modo de integração mudou. Atualize os parâmetros antes de gerar.', 409, 'stale_version')
            cfg = cfg | {'mode': 'individual'} if incoming else cfg
            reason = text(payload.get('reason') or ('Integração contábil de entradas fiscais.' if incoming else 'Integração contábil de saídas fiscais.'), 'Histórico', True, 1000)
            from .fiscal_payment_sources import RetainedPaymentSources
            retained = RetainedPaymentSources(conn, cid)
            groups, skipped = {}, []
            ctx = request_context.get() or {}
            for entry, item_id in zip(entries, ids):
                doc = self._document(conn, cid, item_id)
                if ctx.get('year') and doc['period'][:4] != ctx['year']:
                    raise DomainError('Selecione o exercício da escrituração antes de integrar.', 409, 'stale_context')
                if doc['direction'] != direction:
                    raise DomainError('A seleção deve conter somente entradas fiscais.' if incoming else 'A integração selecionada aceita somente saídas fiscais.')
                if doc['journal_id']:
                    skipped.append({'document_id': item_id, 'journal_id': doc['journal_id'], 'reason': 'already_accounted'})
                    continue
                if doc['status'] != 'booked' or doc.get('book_cancellation') or doc.get('document_state') == 'cancelled' or not doc['total_cents']:
                    skipped.append({'document_id': item_id, 'reason': 'not_eligible', 'status': doc['status']})
                    continue
                check_version(doc, entry)
                ensure_sales_open(conn, cid, doc['period'], 'fiscal')
                ensure_sales_open(conn, cid, doc['period'], 'accounting')
                self._validate_document_links(conn, cid, doc, _existing_document_id=item_id)
                model, payment_snapshot, payment_dimensions = None, None, None
                if entry.get('model_id') is not None:
                    model_id = integer(entry['model_id'], 'Modelo contábil configurado')
                    model = self._master(conn, cid, model_id, 'accounting_model', True)
                    lines = self._model_lines(conn, cid, model_id, doc)
                elif 'payment_accounts' in entry:
                    from .fiscal_payment_allocations import payment_lines
                    lines, payment_snapshot, payment_dimensions = payment_lines(conn, cid, doc, entry, retained=retained)
                else:
                    # Values come from the booked note, never from a client total.
                    value = decimal_text(doc['total_cents'])
                    center = entry.get('cost_center_id')
                    lines = [{'account_id': entry.get('debit_account_id'), 'debit': value, 'credit': '0.00', 'cost_center_id': center},
                             {'account_id': entry.get('credit_account_id'), 'debit': '0.00', 'credit': value, 'cost_center_id': center}]
                lines = self._document_accounting_lines(conn, cid, doc, lines)
                normalized, total = self._normalize_lines(conn, cid, lines, materialize=not preview, actor=actor)
                if model is None and any(x['debit_cents'] and x['account_id'] == normalized[-1]['account_id'] for x in normalized):
                    raise DomainError('Selecione contas diferentes para débito e crédito.')
                if total != doc['total_cents']:
                    raise DomainError('O valor contabilizado deve corresponder ao total do documento.')
                dimensions = [(x['account_id'], bool(x['debit_cents']), x['cost_center_id'], x.get('participant_id')) for x in normalized]
                cls = classification(doc)
                if payment_snapshot is not None:
                    from .account_refs import resolve_account
                    credit = resolve_account(conn, cid, entry['credit_account_id'])
                    credit_ref = -credit['shared_entry_id'] if credit['shared_entry_id'] else credit['id']
                    # Identical explicit mapping consolidates cash-only and mixed
                    # notes together; participants, classification and centers stay separate.
                    dimensions = ['payments', payment_dimensions, credit_ref, entry.get('cost_center_id'),
                                  sorted({x.get('participant_id') or 0 for x in normalized})]
                signature = pack([doc['posting_date'], cls, dimensions])
                group_key = str(item_id) if cfg['mode'] == 'individual' else signature
                group = groups.setdefault(group_key, {'date': doc['posting_date'], 'classification': cls, 'sources': []})
                group['sources'].append({'document_id': item_id, 'document_number': doc['number'], 'document_key': doc['key'],
                    'document_series': doc['series'], 'participant_id': doc.get('participant_id'),
                    'document_version': doc['version'], 'posting_date': doc['posting_date'], 'issue_date': doc['issue_date'],
                    'direction': direction, 'source_hash': doc['source_hash'], 'total_cents': total, 'lines': normalized, 'model_snapshot': model, 'entry_method': 'payments' if payment_snapshot else 'model' if model else 'direct',
                    **({'payment_snapshot': payment_snapshot} if payment_snapshot else {})})
            journals, sources = [], []
            for group_key, group in groups.items():
                combined = {}
                for source in group['sources']:
                    for line in source['lines']:
                        dimension = (line['account_id'], bool(line['debit_cents']), line['cost_center_id'], line.get('participant_id'))
                        summed = combined.setdefault(dimension, line | {'debit_cents': 0, 'credit_cents': 0})
                        summed['debit_cents'] += line['debit_cents']
                        summed['credit_cents'] += line['credit_cents']
                if preview:
                    # Resolve aliases read-only: preview never allocates shared account FKs.
                    from .account_refs import resolve_account
                    planned, total = self._normalize_lines(conn, cid, journal_lines(combined.values()))
                    planned = [line | {k: resolve_account(conn, cid, line['account_id'])[v]
                               for k, v in (('account_code', 'access_code'), ('account_name', 'name'))}
                               for line in planned]
                    journals.append({'date': group['date'], 'total_cents': total, 'lines': planned,
                                     'document_ids': [s['document_id'] for s in group['sources']],
                                     'classification': group['classification']})
                    sources.extend(group['sources'])
                    continue
                journal = self._create_journal(conn, cid, {'date': group['date'], 'document': 'ENTRADAS-FISCAIS' if incoming else 'SAIDAS-FISCAIS',
                    'history': reason, 'lines': journal_lines(combined.values()),
                    'idempotency_key': ('purchases:' if incoming else 'sales:') + digest([key, group_key])}, actor)
                if journal.get('duplicate'):
                    raise DomainError('Chave contábil já utilizada fora desta operação; nenhum vínculo foi alterado.', 409, 'idempotency_conflict')
                journals.append(journal)
                for source in group['sources']:
                    snapshot = source | {'journal_id': journal['id'], 'mode': cfg['mode'], 'classification': group['classification']}
                    conn.execute('UPDATE documents SET journal_id=? WHERE company_id=? AND id=? AND journal_id IS NULL',
                                 (journal['id'], cid, source['document_id']))
                    audit(conn, cid, actor, SOURCE, 'document', source['document_id'], snapshot)
                    sources.append(snapshot)
            result = {'mode': cfg['mode'], 'settings_version': cfg['version'], 'journals': journals, 'sources': sources,
                      'created_count': len(journals), 'accounted_count': len(sources), 'skipped': skipped, 'notice': ('Entradas são contabilizadas individualmente. ' if incoming else '') + NOTICE}
            if preview:
                return result | {'preview': True}
            self._record_operation(conn, cid, operation_scope, key, hashed, result)
            return result

    def trace_sales_accounting_journal(self, cid, item_id):
        with self.db.read(snapshot=True) as conn:
            effect(conn, cid, 'accounting.journals', 'read')
            effect(conn, cid, 'fiscal.documents', 'read')
            journal = self._journal(conn, cid, item_id)
            events = [dict(r) for r in conn.execute(
                "SELECT action,details_json FROM audit WHERE company_id=? AND action IN (?,?) AND (json_extract(details_json,'$.journal_id')=? OR json_extract(details_json,'$.source_journal_id')=?) ORDER BY id",
                (cid, SOURCE, REVERSAL, item_id, item_id))]
            sources = [json.loads(r['details_json']) for r in events if r['action'] == SOURCE]
            if not readable(conn, cid, 'accounting.histories'):
                for source in sources:
                    source.pop('model_snapshot', None)
            return {'journal': journal,
                    'sources': sources,
                    'reversals': [json.loads(r['details_json']) for r in events if r['action'] == REVERSAL]}

    def _reverse_document_accounting(self, conn, cid, doc, day, reason, actor, key):
        jid = doc['journal_id']
        contributions = [s for s in source_events(conn, cid, doc['id']) if s['journal_id'] == jid]
        if not contributions:
            shared = conn.execute('SELECT COUNT(*) FROM documents WHERE company_id=? AND journal_id=?', (cid, jid)).fetchone()[0] > 1
            generated = conn.execute("SELECT 1 FROM journals WHERE company_id=? AND id=? AND (idempotency_key LIKE 'sales:%' OR idempotency_key LIKE 'purchases:%')", (cid, jid)).fetchone()
            if shared or generated:
                raise DomainError('Contribuição de origem ausente no lançamento compartilhado. Confira a integridade dos vínculos.', 409, 'source_evidence_missing')
            return self._reverse_linked_journal(conn, cid, jid, day, reason, actor, key)
        effect(conn, cid, 'accounting.journals', 'reverse')
        original = self._journal(conn, cid, jid)
        ensure_sales_open(conn, cid, doc['period'], 'fiscal')
        ensure_sales_open(conn, cid, original['period'], 'accounting')
        ensure_sales_open(conn, cid, day[:7], 'accounting')
        if original['reversed_by']:
            raise DomainError('Lançamento de origem já estornado. Confira o vínculo.', 409)
        source = contributions[-1]
        journal = self._create_journal(conn, cid, {'date': day, 'document': doc['number'], 'history': reason,
            'lines': journal_lines(source['lines'], reverse=True), 'idempotency_key': key}, actor, source_reversal=True)
        if journal.get('duplicate'):
            raise DomainError('Chave de estorno já utilizada fora desta operação.', 409, 'idempotency_conflict')
        audit(conn, cid, actor, REVERSAL, 'document', doc['id'],
              {'document_id': doc['id'], 'journal_id': journal['id'], 'source_journal_id': jid, 'total_cents': source['total_cents']})
        return journal

    def reverse_journal(self, cid, item_id, payload, actor):
        # Source journals and their compensations must stay under document control,
        # even after the last document has been reversed and detached.
        with self.db.read() as conn:
            if conn.execute("SELECT 1 FROM audit WHERE company_id=? AND action IN (?,?) AND json_extract(details_json,'$.journal_id')=? LIMIT 1",
                            (cid, SOURCE, REVERSAL, item_id)).fetchone():
                raise DomainError('Estorne pelo documento de origem para preservar a integração.', 409, 'linked_journal')
        return super().reverse_journal(cid, item_id, payload, actor)


def register(app, core, actor):
    root = '/api/companies/{cid}/fiscal-sales-accounting'

    @app.get(root + '/settings')
    def read_settings(cid: int):
        return core.fiscal_sales_accounting_settings(cid)

    @app.put(root + '/settings')
    def save_settings(cid: int, request: Request, payload: dict = Body(...)):
        return core.save_fiscal_sales_accounting_settings(cid, payload, actor(request))

    @app.post(root + '/payments')
    def payments(cid: int, payload: dict = Body(...)):
        return core.fiscal_accounting_payments(cid, payload)

    @app.post(root + '/generate')
    def generate(cid: int, request: Request, payload: dict = Body(...)):
        return core.generate_sales_accounting(cid, payload, actor(request))

    @app.get(root + '/journals/{item_id}/sources')
    def trace(cid: int, item_id: int):
        return core.trace_sales_accounting_journal(cid, item_id)

    @app.post(root + '/preview')
    def preview_sales(cid: int, payload: dict = Body(...)):
        return core.preview_fiscal_accounting(cid, payload)

    @app.post('/api/companies/{cid}/fiscal-purchases-accounting/preview')
    def preview_purchases(cid: int, payload: dict = Body(...)):
        return core.preview_fiscal_accounting(cid, payload, direction='incoming')

    @app.post('/api/companies/{cid}/fiscal-purchases-accounting/generate')
    def generate_purchases(cid: int, request: Request, payload: dict = Body(...)):
        return core.generate_purchase_accounting(cid, payload, actor(request))
