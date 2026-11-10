"""Synthetic XML billing integration; test databases are temporary."""
import unittest
import test_fiscal_import as fixtures


class ImportPayablesTests(unittest.TestCase):
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
    def test_explicit_billing_creates_linked_titles_only_once(self):
        self.mapping()
        batch = self.preview()
        prepared = self.prepared(batch, create_payables=True)
        plan = prepared['documents'][0]['financial_posting']
        self.assertTrue(plan['eligible'], plan)
        result = self.confirm(batch, prepared)
        self.assertEqual(1, result['titles_created'])
        self.assertEqual(0, result['transactions_created'])
        repeat = self.confirm(batch, prepared)
        self.assertEqual(result['title_ids'], repeat['title_ids'])
        titles = self.core.titles(self.a['id'])
        self.assertEqual(1, len(titles))
        self.assertEqual('001', titles[0]['document'])
        self.assertEqual('2026-12-05', titles[0]['due_date'])
        self.assertEqual(10000, titles[0]['amount_cents'])
        self.assertEqual([], titles[0]['settlements'])
        self.assertEqual(result['document_ids'][0], titles[0]['document_id'])
        second = self.preview(filename='outra-origem.xml')
        next_preview = self.prepared(second, create_payables=True)
        duplicate = self.confirm(second, next_preview)
        self.assertEqual(0, duplicate['titles_created'])
        self.assertEqual(1, duplicate['titles_duplicate'])

    def test_missing_due_date_blocks_atomically_but_opt_out_imports(self):
        self.mapping()
        batch = self.preview(self.xml().replace(b'<dVenc>2026-12-05</dVenc>', b''))
        prepared = self.prepared(batch, create_payables=True)
        self.assertFalse(prepared['documents'][0]['financial_posting']['eligible'])
        self.confirm(batch, prepared, status=409)
        self.assertEqual([], self.core.documents(self.a['id']))
        prepared = self.prepared(batch, create_payables=False)
        self.assertEqual(1, self.confirm(batch, prepared)['documents_created'])
        self.assertEqual([], self.core.titles(self.a['id']))

    def test_no_billing_is_not_an_error_and_old_api_stays_opt_out(self):
        self.mapping()
        batch = self.preview()
        result = self.confirm(batch, self.prepared(batch))
        self.assertEqual(0, result['titles_created'])
        with self.core.db.read() as conn:
            plan = self.core._payables_plan(conn, self.a['id'], {'direction': 'incoming'}, True)
        self.assertEqual('not_applicable', plan['status'])

    def test_reprocess_classification_preserves_titles_and_blocks_cancelled(self):
        self.mapping()
        batch = self.preview()
        result = self.confirm(batch, self.prepared(batch, create_payables=True))
        options = {'create_payables': True, 'document_overrides': {'documents:0': {'cfop': '1556'}}}
        plan = self.post(f"/imports/{batch['id']}/reprocess-preview", options)
        self.assertTrue(plan['can_confirm'], plan)
        result2 = self.post(f"/imports/{batch['id']}/reprocess-confirm", {
            **options, 'reason': 'Revisão sintética', 'idempotency_key': 'reclassify-billing', 'reprocess_hash': plan['reprocess_hash']})
        self.assertEqual(result['title_ids'], result2['title_ids'])
        self.assertEqual(0, result2['titles_created'])
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE titles SET cancelled=1 WHERE company_id=? AND id=?', (self.a['id'], result['title_ids'][0]))
        blocked = self.post(f"/imports/{batch['id']}/reprocess-preview", options)
        self.assertFalse(blocked['can_confirm'])
        self.assertEqual(1, len(self.core.titles(self.a['id'])))

    def test_reprocess_can_create_previously_declined_payables(self):
        self.mapping()
        batch = self.preview()
        self.confirm(batch, self.prepared(batch))
        options = {'create_payables': True}
        plan = self.post(f"/imports/{batch['id']}/reprocess-preview", options)
        self.assertTrue(plan['can_confirm'], plan)
        result = self.post(f"/imports/{batch['id']}/reprocess-confirm", {
            **options, 'reason': 'Gerar cobrança revisada', 'idempotency_key': 'generate-billing', 'reprocess_hash': plan['reprocess_hash']})
        self.assertEqual(1, result['titles_created'])
        self.assertEqual(0, result['documents_created'])

    def test_multiple_installments_preserve_numbers_dates_and_values(self):
        self.mapping()
        raw = self.xml().replace(b'<vDup>100.00</vDup>', b'<vDup>40.00</vDup>').replace(
            b'</cobr>', b'<dup><nDup>002</nDup><dVenc>2027-01-05</dVenc><vDup>60.00</vDup></dup></cobr>')
        batch = self.preview(raw)
        result = self.confirm(batch, self.prepared(batch, create_payables=True))
        self.assertEqual(2, result['titles_created'])
        titles = sorted(self.core.titles(self.a['id']), key=lambda title: title['installment'])
        self.assertEqual([('001', '2026-12-05', 4000), ('002', '2027-01-05', 6000)],
                         [(t['document'], t['due_date'], t['amount_cents']) for t in titles])
        self.assertTrue(all(t['company_id'] == self.a['id'] and not t['settlements'] for t in titles))

    def test_permission_denial_rolls_back_fiscal_and_is_visible_in_preview(self):
        from unittest.mock import patch
        from app.core import DomainError
        self.mapping()
        batch = self.preview()
        with patch('app.import_payables.effect', side_effect=DomainError('Sem permissão para gerar títulos.', 403, 'forbidden')):
            prepared = self.prepared(batch, create_payables=True)
            self.assertFalse(prepared['documents'][0]['financial_posting']['eligible'])
            self.assertIn('permissão', prepared['documents'][0]['financial_posting']['reason'])
            self.confirm(batch, prepared, status=409)
        self.assertEqual([], self.core.documents(self.a['id']))
        self.assertEqual([], self.core.titles(self.a['id']))

    def test_legacy_batch_recovers_billing_from_exact_original(self):
        import json
        from app.core import pack
        self.mapping()
        batch = self.preview()
        result = self.confirm(batch, self.prepared(batch))
        with self.core.db.transaction() as conn:
            stored = conn.execute('SELECT parsed_json FROM imports WHERE id=?', (batch['id'],)).fetchone()
            parsed = json.loads(stored['parsed_json'])
            for doc in parsed['documents']: doc.pop('billing', None)
            conn.execute('UPDATE imports SET parsed_json=? WHERE id=?', (pack(parsed), batch['id']))
            stored = conn.execute('SELECT extra_json FROM documents WHERE id=?', (result['document_ids'][0],)).fetchone()
            extras = json.loads(stored['extra_json']); extras.pop('billing', None)
            conn.execute('UPDATE documents SET extra_json=? WHERE id=?', (pack(extras), result['document_ids'][0]))
        for attempt in range(2):
            options = {'create_payables': True}
            plan = self.post(f"/imports/{batch['id']}/reprocess-preview", options)
            self.assertTrue(plan['can_confirm'], plan)
            result2 = self.post(f"/imports/{batch['id']}/reprocess-confirm", {
                **options, 'reason': 'Recuperação legada sintética', 'idempotency_key': f'legacy-billing-{attempt}', 'reprocess_hash': plan['reprocess_hash']})
            self.assertEqual(1 if attempt == 0 else 0, result2['titles_created'])
        self.assertEqual(1, len(self.core.titles(self.a['id'])))
        restored = self.core.documents(self.a['id'])[0]
        self.assertEqual('FICT-42', restored['billing']['invoice']['number'])
        self.assertEqual(result['document_ids'][0], restored['id'])
