"""Optional synthetic purchase terms, never a replacement for source billing."""
import unittest
import test_fiscal_import as fixtures


class GeneratedPayablesTests(unittest.TestCase):
    setUp = fixtures.FiscalImportTests.setUp
    tearDown = fixtures.FiscalImportTests.tearDown
    create_company = fixtures.FiscalImportTests.create_company
    activate = fixtures.FiscalImportTests.activate
    scope = fixtures.FiscalImportTests.scope
    document = fixtures.FiscalImportTests.document
    post = fixtures.FiscalImportTests.post
    xml = fixtures.FiscalImportTests.xml
    preview = fixtures.FiscalImportTests.preview
    mapping = fixtures.FiscalImportTests.mapping
    prepared = fixtures.FiscalImportTests.prepared
    confirm = fixtures.FiscalImportTests.confirm

    def no_billing(self):
        raw = self.xml()
        return raw[:raw.index(b'<cobr>')] + raw[raw.index(b'</cobr>') + len(b'</cobr>'):]

    def options(self, **extra):
        return {'enabled': True, 'selected': ['documents:0'], 'term_days': 30, 'date_basis': 'issue',
                'responsible': 'Teste sintético', 'reason': 'Prazo de compra escolhido expressamente', **extra}

    def test_issue_default_thirty_and_idempotency(self):
        self.mapping(); batch = self.preview(self.no_billing())
        ready = self.prepared(batch, generated_payables=self.options())
        plan = ready['documents'][0]['generated_financial_posting']
        self.assertTrue(plan['eligible'], plan)
        self.assertEqual('generated_rule', plan['origin'])
        result = self.confirm(batch, ready)
        self.assertEqual(1, result['titles_created'])
        title = self.core.titles(self.a['id'])[0]
        self.assertEqual([], title['settlements'])
        self.assertTrue(title['source_key'].startswith('generated-billing:'))
        self.assertEqual(result['title_ids'], self.confirm(batch, ready)['title_ids'])
        next_batch = self.preview(self.no_billing(), filename='segunda.xml')
        repeated = self.confirm(next_batch, self.prepared(next_batch, generated_payables=self.options()))
        self.assertEqual(0, repeated['titles_created'])
        self.assertEqual(1, repeated['titles_duplicate'])

    def test_date_basis_must_be_explicit(self):
        self.mapping(); batch = self.preview(self.no_billing())
        options = self.options()
        options.pop('date_basis')
        self.post(f"/imports/{batch['id']}/posting-preview", {'generated_payables': options}, status=400)
        self.post(f"/imports/{batch['id']}/confirm", {
            'posting_mode': 'book', 'preview_hash': batch['preview_hash'],
            'generated_payables': options}, status=400)
        self.assertEqual([], self.core.documents(self.a['id']))
        self.assertEqual([], self.core.titles(self.a['id']))

    def test_receipt_explicit_and_independent_from_posting(self):
        self.mapping(); batch = self.preview(self.no_billing())
        missing = self.prepared(batch, generated_payables=self.options(date_basis='receipt'))
        self.assertFalse(missing['documents'][0]['generated_financial_posting']['eligible'])
        self.confirm(batch, missing, status=409)
        ready = self.prepared(batch, generated_payables=self.options(date_basis='receipt', term_days=45),
                              document_overrides={'documents:0': {'receipt_date': '2026-11-10', 'posting_date': '2026-12-02'}})
        result = self.confirm(batch, ready)
        doc = self.core.documents(self.a['id'])[0]
        title = self.core.titles(self.a['id'])[0]
        self.assertEqual('2026-12-25', title['due_date'])
        self.assertEqual('2026-11-10', doc['receipt_date'])
        self.assertEqual('2026-12-02', doc['posting_date'])
        old_issue = doc['issue_date']
        response = self.client.put(self.scope(f"/documents/{doc['id']}"), json={'version': doc['version'], 'reason': 'Corrigir chegada', 'receipt_date': '2026-11-12'})
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(old_issue, response.json()['issue_date'])
        self.assertEqual('2026-12-25', self.core.titles(self.a['id'])[0]['due_date'])
        plan = self.post(f"/imports/{batch['id']}/reprocess-preview", {'generated_payables': self.options(date_basis='receipt', term_days=45)})
        self.assertFalse(plan['can_confirm'])

    def test_original_billing_never_replaced(self):
        self.mapping(); batch = self.preview()
        ready = self.prepared(batch, generated_payables=self.options())
        self.assertEqual('not_applicable', ready['documents'][0]['generated_financial_posting']['status'])
        self.assertEqual(0, self.confirm(batch, ready)['titles_created'])

    def test_legacy_unknown_billing_requires_original_evidence(self):
        import json
        from app.core import pack
        self.mapping(); batch = self.preview(self.no_billing())
        result = self.confirm(batch, self.prepared(batch))
        with self.core.db.transaction() as conn:
            stored = conn.execute('SELECT parsed_json FROM imports WHERE id=?', (batch['id'],)).fetchone()
            parsed = json.loads(stored['parsed_json'])
            parsed['documents'][0].pop('billing', None)
            conn.execute('UPDATE imports SET parsed_json=?,original=? WHERE id=?', (pack(parsed), b'', batch['id']))
            stored = conn.execute('SELECT extra_json FROM documents WHERE id=?', (result['document_ids'][0],)).fetchone()
            extras = json.loads(stored['extra_json']); extras.pop('billing', None)
            conn.execute('UPDATE documents SET extra_json=? WHERE id=?', (pack(extras), result['document_ids'][0]))
        options = {'generated_payables': self.options()}
        plan = self.post(f"/imports/{batch['id']}/reprocess-preview", options)
        self.assertFalse(plan['can_confirm'])
        self.assertIn('não verificada', plan['documents'][0]['reason'])
        self.post(f"/imports/{batch['id']}/reprocess-confirm", {
            **options, 'reason': 'Conferência sintética', 'idempotency_key': 'unknown-billing',
            'reprocess_hash': plan['reprocess_hash']}, status=409)
        self.assertEqual([], self.core.titles(self.a['id']))
        # The exact retained original can establish the missing negative evidence.
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE imports SET original=? WHERE id=?', (self.no_billing(), batch['id']))
        recovered = self.post(f"/imports/{batch['id']}/reprocess-preview", options)
        self.assertTrue(recovered['can_confirm'], recovered)
        self.assertEqual('ready', recovered['documents'][0]['document']['generated_financial_posting']['status'])

    def test_receipt_and_posting_edit_require_open_fiscal_periods(self):
        self.mapping(); batch = self.preview(self.no_billing())
        self.confirm(batch, self.prepared(batch, generated_payables=self.options()))
        doc = self.core.documents(self.a['id'])[0]
        title = self.core.titles(self.a['id'])[0]
        payload = {'version': doc['version'], 'reason': 'Revisão de chegada e competência',
                   'receipt_date': '2026-11-12', 'posting_date': '2026-12-02'}
        self.post('/periods/close', {'module': 'fiscal', 'period': doc['period'], 'reason': 'Fechamento sintético'})
        response = self.client.put(self.scope(f"/documents/{doc['id']}"), json=payload)
        self.assertEqual(409, response.status_code, response.text)
        self.post('/periods/reopen', {'module': 'fiscal', 'period': doc['period'], 'reason': 'Reabertura sintética'})
        self.post('/periods/close', {'module': 'fiscal', 'period': '2026-12', 'reason': 'Destino fechado'})
        response = self.client.put(self.scope(f"/documents/{doc['id']}"), json=payload)
        self.assertEqual(409, response.status_code, response.text)
        self.post('/periods/reopen', {'module': 'fiscal', 'period': '2026-12', 'reason': 'Destino reaberto'})
        response = self.client.put(self.scope(f"/documents/{doc['id']}"), json=payload)
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual('2026-11-12', response.json()['receipt_date'])
        self.assertEqual('2026-12-02', response.json()['posting_date'])
        self.assertEqual(doc['issue_date'], response.json()['issue_date'])
        self.assertEqual(title, self.core.titles(self.a['id'])[0])

    def test_non_purchase_and_missing_selection_block(self):
        self.mapping(); batch = self.preview(self.no_billing())
        self.post(f"/imports/{batch['id']}/posting-preview", {'generated_payables': self.options(selected=[])}, status=400)
        ready = self.prepared(batch, generated_payables=self.options(), document_overrides={'documents:0': {'cfop': '1910', 'posting_date_confirmed': True}})
        self.assertFalse(ready['documents'][0]['generated_financial_posting']['eligible'])
        self.confirm(batch, ready, status=409)
        self.assertEqual([], self.core.documents(self.a['id']))

    def test_receipt_only_edit_after_settlement_preserves_financial_effects(self):
        self.mapping(); batch = self.preview(self.no_billing())
        self.confirm(batch, self.prepared(batch, generated_payables=self.options()))
        doc = self.core.documents(self.a['id'])[0]
        title = self.core.titles(self.a['id'])[0]
        self.post(f"/titles/{title['id']}/settle", {
            'amount': '100.00', 'date': '2026-11-10', 'reason': 'Baixa sintética', 'idempotency_key': 'settled-arrival'})
        titles_before = self.core.titles(self.a['id'])
        payload = {'version': doc['version'], 'reason': 'Corrigir somente chegada efetiva', 'receipt_date': '2026-11-12'}
        self.post('/periods/close', {'module': 'fiscal', 'period': doc['period'], 'reason': 'Fechamento sintético'})
        response = self.client.put(self.scope(f"/documents/{doc['id']}"), json=payload)
        self.assertEqual(409, response.status_code, response.text)
        self.post('/periods/reopen', {'module': 'fiscal', 'period': doc['period'], 'reason': 'Reabertura sintética'})
        response = self.client.put(self.scope(f"/documents/{doc['id']}"), json=payload)
        self.assertEqual(200, response.status_code, response.text)
        edited = response.json()
        self.assertEqual('2026-11-12', edited['receipt_date'])
        for key in ('posting_date', 'issue_date', 'period', 'total_cents', 'cfop', 'items', 'generated_payment_terms'):
            self.assertEqual(doc[key], edited[key], key)
        self.assertEqual(titles_before, self.core.titles(self.a['id']))
        for extra in ({'posting_date': '2026-12-02'}, {'total': '90.00'}):
            response = self.client.put(self.scope(f"/documents/{doc['id']}"), json={**payload, 'version': edited['version'], **extra})
            self.assertEqual(409, response.status_code, response.text)
            self.assertEqual('document_linked_effects', response.json()['code'])
        # Reprocessing still passes an unrestricted revision and cannot bypass linked effects.
        plan = self.post(f"/imports/{batch['id']}/reprocess-preview", {
            'document_overrides': {'documents:0': {'receipt_date': '2026-11-13'}}})
        self.assertFalse(plan['can_confirm'])
        self.assertEqual(titles_before, self.core.titles(self.a['id']))

    def test_receipt_only_edit_preserves_linked_journal(self):
        doc = self.post('/documents', self.document(), status=201)
        reviewed = self.post(f"/documents/{doc['id']}/review", {'version': doc['version'], 'reason': 'Conferência sintética'})
        lines = fixtures.base.CoreApiTests.journal(self, amount='100.00')['lines']
        self.post(f"/documents/{doc['id']}/book", {'version': reviewed['version'], 'reason': 'Escrituração sintética', 'lines': lines})
        doc = self.core.documents(self.a['id'])[0]
        self.assertIsNotNone(doc['journal_id'])
        journals_before = self.core.journals(self.a['id'])
        payload = {'version': doc['version'], 'reason': 'Chegada independente', 'receipt_date': '2026-11-12'}
        response = self.client.put(self.scope(f"/documents/{doc['id']}"), json=payload)
        self.assertEqual(200, response.status_code, response.text)
        edited = response.json()
        for key in ('posting_date', 'issue_date', 'period', 'total_cents', 'cfop', 'journal_id'):
            self.assertEqual(doc[key], edited[key], key)
        self.assertEqual(journals_before, self.core.journals(self.a['id']))
        response = self.client.put(self.scope(f"/documents/{doc['id']}"), json={**payload, 'version': edited['version'], 'posting_date': '2026-12-02'})
        self.assertEqual(409, response.status_code, response.text)
        self.assertEqual('document_linked_effects', response.json()['code'])
        self.assertEqual(journals_before, self.core.journals(self.a['id']))

    def test_supplier_selection_override_and_reprocessing_conditions(self):
        self.mapping(); batch = self.preview(self.no_billing())
        self.confirm(batch, self.prepared(batch))
        supplier = batch['documents'][0]['partner_tax_id']
        options = self.options(selected=[], supplier_tax_ids=[supplier],
                               overrides={'documents:0': {'amount': '90.50', 'due_date': '2026-12-20', 'reason': 'Condição revisada'}})
        plan = self.post(f"/imports/{batch['id']}/reprocess-preview", {'generated_payables': options})
        self.assertTrue(plan['can_confirm'], plan)
        result = self.post(f"/imports/{batch['id']}/reprocess-confirm", {
            'generated_payables': options, 'reason': 'Aplicar condição escolhida', 'idempotency_key': 'generated-in-reprocess', 'reprocess_hash': plan['reprocess_hash']})
        self.assertEqual(1, result['titles_created'])
        title = self.core.titles(self.a['id'])[0]
        self.assertEqual(9050, title['amount_cents'])
        self.assertEqual('2026-12-20', title['due_date'])
        options['term_days'] = 60
        changed = self.post(f"/imports/{batch['id']}/reprocess-preview", {'generated_payables': options})
        self.assertFalse(changed['can_confirm'])
        # Fiscal-only reclassification still preserves generated titles.
        fiscal = self.post(f"/imports/{batch['id']}/reprocess-preview", {'document_overrides': {'documents:0': {'cfop': '1556'}}})
        self.assertTrue(fiscal['can_confirm'], fiscal)

    def test_financial_permission_and_closed_period_roll_back(self):
        from unittest.mock import patch
        from app.core import DomainError
        self.mapping(); batch = self.preview(self.no_billing())
        with patch('app.import_payables.effect', side_effect=DomainError('Sem permissão financeira', 403)):
            ready = self.prepared(batch, generated_payables=self.options())
            self.assertFalse(ready['documents'][0]['generated_financial_posting']['eligible'])
            self.confirm(batch, ready, status=409)
        self.assertEqual([], self.core.documents(self.a['id']))
        issue_period = batch['documents'][0]['issue_date'][:7]
        self.post('/periods/close', {'module': 'financial', 'period': issue_period, 'reason': 'Fechamento sintético'})
        ready = self.prepared(batch, generated_payables=self.options())
        self.assertFalse(ready['documents'][0]['generated_financial_posting']['eligible'])
        self.confirm(batch, ready, status=409)
        self.assertEqual([], self.core.documents(self.a['id']))
