"""Synthetic reclassification with existing identities, titles and journals."""
import io
import re
import unittest
import zipfile
from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch

import test_fiscal_import as fiscal
from app.core import DomainError


class ReprocessingLinkedEffectsTests(unittest.TestCase):
    setUp = fiscal.FiscalImportTests.setUp
    tearDown = fiscal.FiscalImportTests.tearDown
    create_company = fiscal.FiscalImportTests.create_company
    activate = fiscal.FiscalImportTests.activate
    scope = fiscal.FiscalImportTests.scope
    post = fiscal.FiscalImportTests.post
    xml = fiscal.FiscalImportTests.xml
    preview = fiscal.FiscalImportTests.preview
    prepared = fiscal.FiscalImportTests.prepared
    confirm = fiscal.FiscalImportTests.confirm
    mapping = fiscal.FiscalImportTests.mapping

    MOVEMENTS = ('documents', 'document_sources', 'titles', 'settlements',
                 'journals', 'journal_lines', 'bank_transactions', 'bank_allocations')

    def snapshot(self, tables=None):
        with self.core.db.read(snapshot=True) as conn:
            return {table: [dict(row) for row in conn.execute(f'SELECT * FROM {table} ORDER BY rowid')]
                    for table in tables or (*self.MOVEMENTS, 'imports', 'operations', 'audit')}

    def two_items(self, number=42):
        raw = self.xml()
        original = re.search(rb'<det .*?</det>', raw).group()
        items = []
        for index, amount, tax in [(1, b'40.00', b'7.20'), (2, b'60.00', b'10.80')]:
            item = original.replace(b'nItem="1"', f'nItem="{index}"'.encode())
            item = item.replace(b'<qCom>2.0000</qCom>', b'<qCom>1.0000</qCom>')
            item = item.replace(b'<vUnCom>50.00</vUnCom>', b'<vUnCom>' + amount + b'</vUnCom>')
            item = item.replace(b'100.00', amount).replace(b'<vICMS>18.00</vICMS>', b'<vICMS>' + tax + b'</vICMS>')
            items.append(item)
        return raw.replace(original, b''.join(items)).replace(
            b'35261187654321000198550010000000421000000420', str(10**43 + number).encode()).replace(
            b'<nNF>42</nNF>', f'<nNF>{number}</nNF>'.encode())

    def imported(self, *, titles=False, count=1):
        if count == 1:
            batch = self.preview(self.two_items())
        else:
            output = io.BytesIO()
            with zipfile.ZipFile(output, 'w') as archive:
                for number in range(42, 42 + count):
                    archive.writestr(f'synthetic-{number}.xml', self.two_items(number))
            batch = self.preview(output.getvalue(), 'synthetic-reprocessing.zip')
        overrides = {d['_selection']: {'cfop': '1102', 'posting_date': '2026-11-08'}
                     for d in batch['documents']}
        self.confirm(batch, self.prepared(batch, create_payables=titles, document_overrides=overrides))
        return batch, self.core.documents(self.a['id'])

    def split_options(self):
        return {'document_overrides': {'documents:0': {
            'item_destinations': {'1': 'resale', '2': 'consumption'},
            'posting_group_review': {'mode': 'split', 'item_groups': {'1': 'Revenda', '2': 'Consumo'},
                'source': 'Itens sintéticos', 'responsible': 'Teste', 'reason': 'Desdobramento explícito'}}}}

    def split_rules(self):
        self.mapping(target_cfop='1102', purchase_destination='resale')
        self.mapping(target_cfop='1556', purchase_destination='consumption')

    def plan(self, batch, options):
        return self.post(f"/imports/{batch['id']}/reprocess-preview", options)

    def apply(self, batch, plan, options, *, key='synthetic-linked-reprocess', status=200):
        return self.post(f"/imports/{batch['id']}/reprocess-confirm", {
            **options, 'reprocess_hash': plan['reprocess_hash'], 'idempotency_key': key,
            'reason': 'Reclassificação sintética preservando vínculos'}, status)

    def assert_preserved_document(self, old, new):
        for field in ('id', 'company_id', 'key', 'number', 'series', 'model', 'direction',
                      'total_cents', 'taxes', 'issue_date', 'posting_date', 'period', 'source',
                      'source_hash', 'sources', 'participant_id', 'billing', 'invoices', 'journal_id'):
            self.assertEqual(old.get(field), new.get(field), field)
        strip = lambda items: [{k: v for k, v in row.items() if k not in {'cfop', 'purchase_destination'}}
                               for row in items]
        self.assertEqual(strip(old['items']), strip(new['items']))

    def test_new_rule_preserves_existing_cfop_until_explicit_item_choice(self):
        batch, (old,) = self.imported()
        self.mapping(target_cfop='1556', purchase_destination='consumption')
        before = self.snapshot()
        preserved = self.plan(batch, {})
        self.assertTrue(preserved['can_confirm'], preserved)
        doc = preserved['documents'][0]['document']
        self.assertEqual(['1102', '1102'], [i['cfop'] for i in doc['items']])
        self.assertTrue(all(m['origin'] == 'existing_document' for m in doc['import_posting']['mappings']))
        self.assertEqual(before, self.snapshot(), 'a prévia não grava a regra na nota')
        options = {'document_overrides': {'documents:0': {'item_destinations': {'2': 'consumption'}}}}
        plan = self.plan(batch, options)
        self.assertTrue(plan['can_confirm'], plan)
        self.assertEqual(['1102', '1556'], [i['cfop'] for i in plan['documents'][0]['document']['items']])
        self.apply(batch, plan, options)
        new = self.core.documents(self.a['id'])[0]
        self.assert_preserved_document(old, new)
        self.assertEqual(['1102', '1556'], [i['cfop'] for i in new['items']])

    def test_split_multiple_cfops_preserves_open_xml_title_and_retry_identity(self):
        batch, (old,) = self.imported(titles=True)
        self.split_rules()
        options = self.split_options() | {'create_payables': True}
        before = self.snapshot()
        plan = self.plan(batch, options)
        self.assertTrue(plan['can_confirm'], plan)
        self.assertEqual(before, self.snapshot())
        lines = plan['documents'][0]['posting_lines']
        self.assertEqual({('1102', 'Revenda', '40.00'), ('1556', 'Consumo', '60.00')},
            {(line['cfop'], line['posting_group'], line['document_total']) for line in lines})
        result = self.apply(batch, plan, options)
        self.assertEqual((0, 1, 0, 1), (result['documents_created'], result['documents_updated'],
                                      result['titles_created'], result['titles_duplicate']))
        new = self.core.documents(self.a['id'])[0]
        self.assert_preserved_document(old, new)
        self.assertEqual('', new['cfop'])  # The document has two item-level CFOPs.
        self.assertEqual(Decimal('100.00'), sum(Decimal(line['document_total']) for line in new['posting_lines']))
        untouched = tuple(table for table in self.MOVEMENTS if table != 'documents')
        after = self.snapshot()
        self.assertEqual({t: before[t] for t in untouched}, {t: after[t] for t in untouched})
        self.assertTrue(self.apply(batch, plan, options)['duplicate'])
        self.assertEqual(after, self.snapshot(), 'a mesma intenção não grava versão nem auditoria adicional')
        fresh = self.plan(batch, options)
        again = self.apply(batch, fresh, options, key='synthetic-linked-new-intent')
        self.assertEqual((0, 1), (again['titles_created'], again['titles_duplicate']))
        self.assertEqual([old['id']], again['document_ids'])
        self.assertEqual(before['titles'], self.snapshot()['titles'])
        self.assertEqual(before['document_sources'], self.snapshot()['document_sources'])

    def test_split_group_cannot_mix_cfops_and_block_is_atomic(self):
        batch, _ = self.imported(titles=True)
        self.split_rules()
        options = self.split_options()
        options['document_overrides']['documents:0']['posting_group_review']['item_groups'] = {'1': 'A', '2': 'A'}
        before = self.snapshot()
        plan = self.plan(batch, options)
        self.assertFalse(plan['can_confirm'])
        self.assertIn('misturar CFOPs', plan['documents'][0]['reason'])
        self.assertEqual('reprocess_blocked', self.apply(batch, plan, options, status=409)['code'])
        self.assertEqual(before, self.snapshot())

    def test_partial_and_full_settlement_block_reprocessing_and_stale_preview(self):
        batch, _ = self.imported(titles=True)
        self.split_rules()
        options = self.split_options()
        ready = self.plan(batch, options)
        self.assertTrue(ready['can_confirm'], ready)
        title = self.core.titles(self.a['id'])[0]
        for index, amount in enumerate(('40.00', '60.00')):
            self.post(f"/titles/{title['id']}/settle", {'amount': amount, 'date': '2026-11-10',
                'reason': 'Baixa exclusivamente sintética', 'idempotency_key': f'synthetic-linked-settle-{index}'})
            before = self.snapshot()
            self.assertEqual('reprocess_stale', self.apply(batch, ready, options, status=409)['code'])
            blocked = self.plan(batch, options)
            self.assertFalse(blocked['can_confirm'])
            self.assertIn('efeitos', blocked['documents'][0]['reason'])
            self.assertEqual('reprocess_blocked', self.apply(batch, blocked, options, status=409)['code'])
            self.assertEqual(before, self.snapshot())
        self.assertEqual(10000, self.core.titles(self.a['id'])[0]['paid_cents'])

    def test_linked_journal_blocks_even_when_preview_precedes_accounting(self):
        batch, (doc,) = self.imported()
        self.split_rules()
        options = self.split_options()
        ready = self.plan(batch, options)
        self.assertTrue(ready['can_confirm'], ready)
        lines = fiscal.base.CoreApiTests.journal(self, amount='100.00')['lines']
        result = self.post(f"/documents/{doc['id']}/account", {'version': doc['version'],
            'reason': 'Contabilização exclusivamente sintética', 'lines': lines, 'idempotency_key': 'synthetic-linked-journal'})
        self.assertIsNotNone(result['document']['journal_id'])
        before = self.snapshot()
        self.assertEqual('reprocess_stale', self.apply(batch, ready, options, status=409)['code'])
        blocked = self.plan(batch, options)
        self.assertFalse(blocked['can_confirm'])
        self.assertIn('efeitos', blocked['documents'][0]['reason'])
        self.assertEqual('reprocess_blocked', self.apply(batch, blocked, options, status=409)['code'])
        self.assertEqual(before, self.snapshot())

    def test_manual_open_title_does_not_gain_xml_safe_reclassification(self):
        batch, (doc,) = self.imported()
        self.split_rules()
        title = self.post('/titles', {'kind': 'payable', 'document_id': doc['id'],
            'description': 'Título manual exclusivamente sintético', 'partner_name': doc['partner_name'],
            'document': 'MANUAL-SYNTHETIC', 'issue_date': doc['issue_date'],
            'due_date': '2026-12-05', 'amount': '100.00'}, status=201)
        self.assertEqual((0, []), (title['paid_cents'], title['settlements']))
        before = self.snapshot()
        options = self.split_options()
        blocked = self.plan(batch, options)
        self.assertFalse(blocked['can_confirm'])
        self.assertIn('efeitos', blocked['documents'][0]['reason'])
        self.assertEqual('reprocess_blocked', self.apply(batch, blocked, options, status=409)['code'])
        self.assertEqual(before, self.snapshot())

    def test_cleaned_original_keeps_normalized_reprocessing_and_financial_links(self):
        batch, (doc,) = self.imported(titles=True)
        self.split_rules()
        before = self.snapshot(self.MOVEMENTS)
        cleanup = self.post('/import-packages/cleanup-preview', {'ids': [batch['id']], 'mode': 'originals_and_hide_history'})
        self.assertEqual([], cleanup['blocked_ids'])
        self.post('/import-packages/cleanup-confirm', {'ids': cleanup['ids'], 'mode': cleanup['mode'],
            'preview_hash': cleanup['preview_hash'], 'acknowledge_irreversible': True})
        self.assertEqual(before, self.snapshot(self.MOVEMENTS))
        self.assertEqual(410, self.client.get(self.scope(f"/imports/{batch['id']}/original")).status_code)
        self.assertNotIn(batch['id'], [b['id'] for b in self.client.get(self.scope('/imports')).json()])
        options = self.split_options()
        plan = self.plan(batch, options)
        self.assertTrue(plan['can_confirm'], plan)
        result = self.apply(batch, plan, options)
        self.assertEqual([doc['id']], result['document_ids'])
        self.assertEqual(0, result['documents_created'])
        self.assert_preserved_document(doc, self.core.documents(self.a['id'])[0])
        after = self.snapshot()
        for table in self.MOVEMENTS[1:]:
            self.assertEqual(before[table], after[table], table)
        self.assertEqual(b'', after['imports'][0]['original'])

    def test_failure_after_second_document_update_rolls_back_links_and_can_retry(self):
        batch, docs = self.imported(titles=True, count=2)
        self.split_rules()
        revision = self.split_options()['document_overrides']['documents:0']
        options = {'create_payables': True, 'document_overrides': {
            d['_selection']: deepcopy(revision) for d in batch['documents']}}
        plan = self.plan(batch, options)
        self.assertTrue(plan['can_confirm'], plan)
        before = self.snapshot()
        original = self.core.update_document
        calls = []

        def fail_second(cid, item_id, payload, actor, **kwargs):
            result = original(cid, item_id, payload, actor, **kwargs)
            calls.append(item_id)
            if len(calls) == 2:
                raise DomainError('Falha sintética após alterar a segunda nota.', 409, 'synthetic_second_update')
            return result

        with patch.object(self.core, 'update_document', side_effect=fail_second):
            error = self.apply(batch, plan, options, status=409)
        self.assertEqual('synthetic_second_update', error['code'])
        self.assertEqual(2, len(set(calls)))
        self.assertEqual(before, self.snapshot(), 'rollback inclui documentos, vínculos, operações e auditoria')
        result = self.apply(batch, plan, options)
        self.assertEqual((0, 2, 0, 2), (result['documents_created'], result['documents_updated'],
                                      result['titles_created'], result['titles_duplicate']))
        saved = {d['id']: d for d in self.core.documents(self.a['id'])}
        self.assertEqual({d['id'] for d in docs}, set(saved))
        for doc in docs:
            self.assert_preserved_document(doc, saved[doc['id']])
        self.assertEqual(before['titles'], self.snapshot()['titles'])
        with self.core.db.read() as conn:
            self.assertEqual([], conn.execute('PRAGMA foreign_key_check').fetchall())
