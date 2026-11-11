"""Synthetic imported-document corrections never replace amounts or movement IDs."""
import json
import unittest
from unittest.mock import patch
import test_fiscal_import as base


class ImportReprocessingTests(unittest.TestCase):
    setUp = base.FiscalImportTests.setUp
    tearDown = base.FiscalImportTests.tearDown
    create_company = base.FiscalImportTests.create_company
    activate = base.FiscalImportTests.activate
    scope = base.FiscalImportTests.scope
    post = base.FiscalImportTests.post
    xml = base.FiscalImportTests.xml
    preview = base.FiscalImportTests.preview
    prepared = base.FiscalImportTests.prepared
    confirm = base.FiscalImportTests.confirm

    def imported(self, pending=False):
        batch = self.preview()
        if pending:
            self.post(f"/imports/{batch['id']}/confirm", {'preview_hash': batch['preview_hash'], 'posting_mode': 'pending'})
        else:
            options = {'document_overrides': {'documents:0': {'posting_date': '2026-12-02', 'cfop': '1102'}}}
            ready = self.prepared(batch, **options)
            self.confirm(batch, ready, **options)
        return batch, self.core.documents(self.a['id'])[0]

    def plan(self, batch, **options):
        return self.post(f"/imports/{batch['id']}/reprocess-preview", options)

    def apply(self, batch, plan, status=200, **options):
        return self.post(f"/imports/{batch['id']}/reprocess-confirm", {
            'reprocess_hash': plan['reprocess_hash'], 'idempotency_key': 'synthetic-reprocessing',
            'reason': 'Reclassificação sintética sem recriação', **options}, status)

    def test_preview_readonly_preserves_dates_amounts_identity_and_retry(self):
        batch, old = self.imported()
        edited_items = old['items']
        edited_items[0]['description'] = 'Descrição manual preservada'
        response = self.client.put(self.scope(f"/documents/{old['id']}"), json={
            'version': old['version'], 'reason': 'Correção sintética', 'total': '125.67', 'items': edited_items})
        self.assertEqual(200, response.status_code, response.text)
        old = response.json()
        options = {'document_overrides': {'documents:0': {'cfop': '1556'}}}
        preview = self.plan(batch, **options)
        self.assertTrue(preview['can_confirm'], preview)
        self.assertEqual(old['version'], self.core.documents(self.a['id'])[0]['version'])
        self.assertEqual('2026-12-02', preview['documents'][0]['after']['posting_date'])
        from decimal import Decimal
        self.assertEqual(Decimal('125.67'), sum(Decimal(r['document_total']) for r in preview['documents'][0]['posting_lines']))
        result = self.apply(batch, preview, **options)
        new = self.core.documents(self.a['id'])[0]
        self.assertEqual([old['id']], result['document_ids'])
        self.assertEqual(old['total_cents'], new['total_cents'])
        self.assertEqual(Decimal('125.67'), sum(Decimal(r['document_total']) for r in new['posting_lines']))
        self.assertEqual('Descrição manual preservada', new['items'][0]['description'])
        self.assertEqual(old['source'], new['source'])
        self.assertEqual(old['items'][0]['source_cfop'], new['items'][0]['source_cfop'])
        self.assertEqual('1556', new['items'][0]['cfop'])
        self.assertTrue(self.apply(batch, preview, **options)['duplicate'])
        self.assertEqual(new['version'], self.core.documents(self.a['id'])[0]['version'])

    def test_stale_version_and_closed_period_block_every_write(self):
        batch, old = self.imported()
        options = {'document_overrides': {'documents:0': {'cfop': '1102'}}}
        preview = self.plan(batch, **options)
        self.client.put(self.scope(f"/documents/{old['id']}"), json={'version': old['version'], 'reason': 'Mudança concorrente'})
        self.apply(batch, preview, 409, **options)
        self.post('/periods/close', {'module': 'fiscal', 'period': '2026-12', 'reason': 'Fechamento sintético'})
        blocked = self.plan(batch, **options)
        self.assertFalse(blocked['can_confirm'])
        self.apply(batch, blocked, 409, **options)

    def test_pending_date_requires_explicit_confirmation(self):
        batch, old = self.imported(pending=True)
        options = {'document_overrides': {'documents:0': {'cfop': '1102'}}}
        self.assertFalse(self.plan(batch, **options)['can_confirm'])
        options['document_overrides']['documents:0']['posting_date_confirmed'] = True
        preview = self.plan(batch, **options)
        self.assertTrue(preview['can_confirm'], preview)
        self.apply(batch, preview, **options)
        self.assertEqual('pending', self.core.documents(self.a['id'])[0]['status'])

    def test_missing_document_never_recreated(self):
        batch, old = self.imported()
        with self.app.state.db.transaction() as conn:
            conn.execute('DELETE FROM document_sources WHERE document_id=?', (old['id'],))
            conn.execute('DELETE FROM documents WHERE id=?', (old['id'],))
        options = {'document_overrides': {'documents:0': {'cfop': '1102'}}}
        preview = self.plan(batch, **options)
        self.assertFalse(preview['can_confirm'])
        self.apply(batch, preview, 409, **options)
        self.assertEqual([], self.core.documents(self.a['id']))

    def test_atomic_rollback_when_update_fails(self):
        batch, old = self.imported()
        options = {'document_overrides': {'documents:0': {'cfop': '1102'}}}
        preview = self.plan(batch, **options)
        original = self.core.update_document
        from app.core import DomainError
        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise DomainError('Falha sintética após alteração', 409)
        with patch.object(self.core, 'update_document', side_effect=fail):
            self.apply(batch, preview, 409, **options)
        self.assertEqual(old['version'], self.core.documents(self.a['id'])[0]['version'])

    def test_settings_change_invalidates_preview(self):
        batch, old = self.imported()
        options = {'document_overrides': {'documents:0': {'cfop': '1102'}}}
        preview = self.plan(batch, **options)
        with self.app.state.db.transaction() as conn:
            conn.execute("UPDATE companies SET state='RJ' WHERE id=?", (self.a['id'],))
        # A company state changes the applicable origin/destination context.
        # Explicit classifications still preserve a stale snapshot barrier.
        fresh = self.plan(batch, **options)
        self.assertNotEqual(preview['reprocess_hash'], fresh['reprocess_hash'])

    def test_removed_item_and_source_mismatch_block(self):
        batch, old = self.imported()
        options = {'document_overrides': {'documents:0': {'cfop': '1102'}}}
        with self.app.state.db.transaction() as conn:
            items = json.loads(conn.execute('SELECT items_json FROM documents WHERE id=?', (old['id'],)).fetchone()[0])
            items[0]['number'] = '999'
            conn.execute('UPDATE documents SET items_json=? WHERE id=?', (json.dumps(items), old['id']))
        self.assertFalse(self.plan(batch, **options)['can_confirm'])
        with self.app.state.db.transaction() as conn:
            conn.execute('DELETE FROM document_sources WHERE document_id=?', (old['id'],))
        self.assertIn('Origem', self.plan(batch, **options)['documents'][0]['reason'])

    def test_null_removes_decisions_and_refreshes_provenance(self):
        batch, old = self.imported()
        treatment = {'code': 'Teste', 'book_mode': 'no_credit', 'source': 'Decisão sintética',
                     'responsible': 'Teste', 'valid_from': '2026-01-01', 'valid_to': ''}
        with self.app.state.db.transaction() as conn:
            extras = json.loads(conn.execute('SELECT extra_json FROM documents WHERE id=?', (old['id'],)).fetchone()[0])
            extras['fiscal_treatment'] = treatment
            conn.execute('UPDATE documents SET extra_json=? WHERE id=?', (json.dumps(extras), old['id']))
        options = {'document_overrides': {'documents:0': {'cfop': '1556', 'fiscal_treatment': None}}}
        preview = self.plan(batch, **options)
        self.assertTrue(preview['can_confirm'], preview)
        self.apply(batch, preview, **options)
        new = self.core.documents(self.a['id'])[0]
        self.assertNotIn('fiscal_treatment', new)
        self.assertEqual('1556', new['import_posting']['mappings'][0]['target_cfop'])
        self.assertTrue(new['import_posting']['review_pending'])

    def test_company_isolation(self):
        batch, old = self.imported()
        self.activate(self.b['id'])
        response = self.client.post(self.scope(f"/imports/{batch['id']}/reprocess-preview", self.b['id']), json={})
        self.assertEqual(404, response.status_code)

    def test_reprocessing_can_be_repeated_with_new_intent_and_date_confirmation_survives(self):
        batch, old = self.imported()
        options = {'document_overrides': {'documents:0': {'cfop': '1556'}}}
        first = self.plan(batch, **options)
        self.apply(batch, first, **options)
        second = self.plan(batch, **options)
        self.assertTrue(second['can_confirm'], second)
        self.apply(batch, second, idempotency_key='another-intent', **options)
        self.assertEqual(old['id'], self.core.documents(self.a['id'])[0]['id'])

    def test_import_permission_does_not_grant_edit_or_book(self):
        from fastapi.testclient import TestClient
        batch, old = self.imported()
        permissions = [{'company_id': self.a['id'], 'routine': 'fiscal.imports', 'action': a, 'effect': 'allow'} for a in ('read', 'import')]
        response = self.client.post('/api/users', json={'username': 'reprocess-reader', 'password': 'Senha-sintetica-2026',
            'role': 'custom', 'company_ids': [self.a['id']], 'permissions': permissions})
        self.assertEqual(201, response.status_code, response.text)
        with TestClient(self.app) as client:
            login = client.post('/api/login', json={'username': 'reprocess-reader', 'password': 'Senha-sintetica-2026'}).json()
            client.headers['X-CSRF-Token'] = login['csrf_token']
            self.activate(self.a['id'], client=client)
            response = client.post(self.scope(f"/imports/{batch['id']}/reprocess-preview"), json={})
            self.assertEqual(403, response.status_code, response.text)
        self.assertEqual(old['version'], self.core.documents(self.a['id'])[0]['version'])

    def duplicate_batch(self):
        import io
        import zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('a.xml', self.xml())
            archive.writestr('b.xml', self.xml())
        batch = self.preview(buffer.getvalue(), 'copias-sinteticas.zip')
        options = {'document_overrides': {f'documents:{i}': {'posting_date': '2026-12-02', 'cfop': '1102'} for i in range(2)}}
        self.confirm(batch, self.prepared(batch, **options), **options)
        self.assertEqual(1, len(self.core.documents(self.a['id'])))
        return batch

    def test_identical_duplicate_sources_update_once(self):
        batch = self.duplicate_batch()
        old = self.core.documents(self.a['id'])[0]
        options = {'document_overrides': {f'documents:{i}': {'cfop': '1556'} for i in range(2)}}
        preview = self.plan(batch, **options)
        self.assertTrue(preview['can_confirm'], preview)
        self.assertEqual('documents:0', preview['documents'][1]['duplicate_of'])
        result = self.apply(batch, preview, **options)
        self.assertEqual(1, result['documents_updated'])
        self.assertEqual([old['id']], result['document_ids'])
        self.assertEqual(old['version'] + 1, self.core.documents(self.a['id'])[0]['version'])

    def test_conflicting_duplicate_sources_block_until_subset_selected(self):
        batch = self.duplicate_batch()
        options = {'document_overrides': {'documents:0': {'cfop': '1556'}, 'documents:1': {'cfop': '1102'}}}
        preview = self.plan(batch, **options)
        self.assertFalse(preview['can_confirm'])
        self.assertTrue(all(not row['eligible'] and 'conflitantes' in row['reason'] for row in preview['documents']))
        self.apply(batch, preview, 409, **options)
        options['selected'] = ['documents:1']
        subset = self.plan(batch, **options)
        self.assertTrue(subset['can_confirm'], subset)
        self.assertNotEqual(preview['reprocess_hash'], subset['reprocess_hash'])
        result = self.apply(batch, subset, **options)
        self.assertEqual(1, result['documents_updated'])

    def test_rtc_review_preserved_replaced_and_explicit_null_blocks(self):
        decision = {'basis': 'vNF', 'source': 'Revisão sintética', 'responsible': 'Teste', 'reason': 'Conferência vNF fictícia'}
        raw = self.xml().replace(b'</ICMSTot></total>', b'</ICMSTot><vNFTot>105.00</vNFTot></total>')
        batch = self.preview(raw, 'rtc-sintetico.xml')
        options = {'total_review': decision, 'document_overrides': {'documents:0': {'posting_date': '2026-12-02', 'cfop': '1102'}}}
        self.confirm(batch, self.prepared(batch, **options), **options)
        options = {'document_overrides': {'documents:0': {'cfop': '1556'}}}
        preserved = self.plan(batch, **options)
        self.assertTrue(preserved['can_confirm'], preserved)
        self.assertEqual(decision, preserved['documents'][0]['after']['total_review'])
        self.assertEqual('100.00', preserved['documents'][0]['document']['total_comparison']['vNF'])
        revised = dict(decision, reason='Nova revisão sintética')
        options['document_overrides']['documents:0']['total_review'] = revised
        preview = self.plan(batch, **options)
        self.assertTrue(preview['can_confirm'], preview)
        self.apply(batch, preview, **options)
        saved = self.core.documents(self.a['id'])[0]
        self.assertEqual(revised, saved['total_review'])
        self.assertEqual(10000, saved['total_cents'])
        options['document_overrides']['documents:0']['total_review'] = None
        options['total_review'] = decision
        blocked = self.plan(batch, **options)
        self.assertFalse(blocked['can_confirm'], blocked)
        self.assertIn('vNF', blocked['documents'][0]['reason'])

    def test_partial_item_destination_preserves_other_items_decisions(self):
        import re
        raw=self.xml()
        original=re.search(rb'<det .*?</det>',raw).group()
        first=original.replace(b'<vProd>100.00</vProd>',b'<vProd>50.00</vProd>').replace(b'<qCom>2.0000</qCom>',b'<qCom>1.0000</qCom>')
        raw=raw.replace(original,first+first.replace(b'nItem="1"',b'nItem="2"'))
        batch=self.preview(raw)
        initial=self.prepared(batch,document_overrides={'documents:0':{'cfop':'1556','posting_date':'2026-11-08'}})
        self.confirm(batch,initial)
        old=self.core.documents(self.a['id'])[0]
        with self.core.db.transaction() as conn:
            items=json.loads(conn.execute('SELECT items_json FROM documents WHERE id=?',(old['id'],)).fetchone()[0])
            for item in items:item['purchase_destination']='consumption'
            conn.execute('UPDATE documents SET items_json=? WHERE id=?',(json.dumps(items),old['id']))
        self.post('/fiscal-import-mappings',{'direction':'incoming','model':'55','source_cfop':'5102','target_cfop':'1102','purchase_destination':'resale','valid_from':'2026-01-01','valid_to':'','reason':'Teste','responsible':'Teste'})
        plan=self.plan(batch,document_overrides={'documents:0':{'item_destinations':{'1':'resale'}}})
        self.assertTrue(plan['can_confirm'],plan)
        items=plan['documents'][0]['document']['items']
        self.assertEqual([('1102','resale'),('1556','consumption')],[(i['cfop'],i['purchase_destination']) for i in items])
