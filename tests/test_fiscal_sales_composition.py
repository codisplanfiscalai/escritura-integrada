"""Composition of PR39 with dev.13 journal reads and SPED; synthetic databases only."""
import base64
import os
import tempfile
from contextlib import contextmanager
import unittest
from unittest.mock import patch

# Isolate app.api's module-level app before importing any application fixture.
_IMPORT_DATA = tempfile.TemporaryDirectory(prefix='escritura-compose-import-')
os.environ['ESCRITURA_DATA_DIR'] = _IMPORT_DATA.name
os.environ['ESCRITURA_DEMO'] = '0'

import test_fiscal_sales_accounting as sales
import test_sped_generator as sped
import test_sped_native_export as native
import test_prosoft_increment as prosoft


class FiscalSalesCompositionTests(unittest.TestCase):
    setUp = sales.FiscalSalesAccountingTests.setUp
    tearDown = sales.FiscalSalesAccountingTests.tearDown
    scope = sales.FiscalSalesAccountingTests.scope
    activate = sales.FiscalSalesAccountingTests.activate
    create_company = sales.FiscalSalesAccountingTests.create_company
    document = sales.FiscalSalesAccountingTests.document
    journal = sales.FiscalSalesAccountingTests.journal
    post = sales.FiscalSalesAccountingTests.post
    mode = sales.FiscalSalesAccountingTests.mode
    model = sales.FiscalSalesAccountingTests.model
    sale = sales.FiscalSalesAccountingTests.sale
    payload = sales.FiscalSalesAccountingTests.payload
    generate = sales.FiscalSalesAccountingTests.generate
    snapshot = sales.FiscalSalesAccountingTests.snapshot
    balances = sales.FiscalSalesAccountingTests.balances
    reverse = sales.FiscalSalesAccountingTests.reverse
    operator = sales.FiscalSalesAccountingTests.operator
    own_xml = sped.SpedGeneratorApiTests.own_xml
    import_xmls = sped.SpedGeneratorApiTests.import_xmls
    database_hash = sped.SpedGeneratorApiTests.database_hash
    source_batch = native.NativeExportApiTests.source_batch

    def block_c(self):
        return self.post('/sped-generator/bookkeeping-block-c',
                         {'period': '2026-11', 'profile': 'A', 'activity': '1', 'purpose': '0'})

    def consolidation_preview(self):
        result = self.client.get(self.scope('/sped-generator/nfce-consolidation?period=2026-11'))
        self.assertEqual(200, result.status_code, result.text)
        return result.json()

    def test_optimized_listing_matches_details_after_daily_individual_and_partial_reversal(self):
        self.mode(); model = self.model()
        daily = [self.sale('COMPOSE-D1', '0.01'), self.sale('COMPOSE-D2', '10.02')]
        original = self.generate(daily, model)['journals'][0]
        current = next(d for d in self.core.documents(self.a['id']) if d['id'] == daily[0]['id'])
        compensation = self.reverse(current)['journal']
        self.mode('individual')
        individual = [self.sale('COMPOSE-I1', '20.03', day='2026-11-07'), self.sale('COMPOSE-I2', '1.04', cfop='6102')]
        self.generate(individual, model, 'compose-individual')
        self.core.create_exercise(self.a['id'], {'module': 'accounting', 'year': 2025}, 'synthetic')
        historical = self.core.create_journal(self.a['id'], self.journal(key='compose-2025', day='2025-11-06'), 'synthetic')
        october = self.core.create_journal(self.a['id'], self.journal(key='compose-october', day='2026-10-06'), 'synthetic')
        self.activate(self.b['id'])
        bm = self.model('B', cid=self.b['id']); bd = self.sale('COMPOSE-B', cid=self.b['id'])
        other = self.post(sales.ROOT + '/generate', self.payload([bd], bm, 'compose-b', version=0), cid=self.b['id'])['journals'][0]
        self.activate(self.a['id'])
        before = self.database_hash(); queries = []
        read = self.core.db.read
        @contextmanager
        def traced(*args, **kwargs):
            with read(*args, **kwargs) as conn:
                conn.set_trace_callback(lambda q: queries.append(q) if q.lstrip().upper().startswith('SELECT') else None)
                try: yield conn
                finally: conn.set_trace_callback(None)
        with patch.object(self.core.db, 'read', traced):
            annual = self.core.journals(self.a['id'], year=2026)
        self.assertEqual(3, len(queries), queries)
        self.assertEqual(2, sum('BETWEEN' in q for q in queries))
        self.assertEqual(5, len(annual))
        self.assertNotIn(historical['id'], {j['id'] for j in annual})
        self.assertNotIn(other['id'], {j['id'] for j in annual})
        self.assertIn(october['id'], {j['id'] for j in annual})
        monthly = self.client.get(self.scope('/journals?period=2026-11')).json()
        self.assertEqual(4, len(monthly))
        for journal in annual:
            detail = self.client.get(self.scope(f"/journals/{journal['id']}")).json()
            self.assertEqual(detail, journal)
            self.assertEqual(sum(l['debit_cents'] for l in journal['lines']), sum(l['credit_cents'] for l in journal['lines']))
        self.assertEqual(annual, self.client.get(self.scope('/journals?year=2026')).json())
        self.assertEqual(original, next(j for j in monthly if j['id'] == original['id']))
        self.assertEqual(compensation, next(j for j in monthly if j['id'] == compensation['id']))
        self.assertEqual(before, self.database_hash(), 'All list/detail reads must remain read-only')

    def test_real_accounting_consolidation_does_not_consolidate_sped_book_documents(self):
        self.import_xmls(1, 2, 3, book=True)
        docs = self.core.documents(self.a['id']); before_block = self.block_c()
        self.mode(); model = self.model()
        result = self.generate(docs, model)
        self.assertEqual((1, 3), (result['created_count'], result['accounted_count']))
        self.assertEqual(30000, result['journals'][0]['total_cents'])
        before = self.database_hash()
        after_block = self.block_c()
        self.assertEqual(before_block, after_block)
        self.assertEqual(3, base64.b64decode(after_block['content_base64']).count(b'|C100|'))
        self.assertEqual('individual_nfce', after_block['representation'])
        self.assertFalse(after_block['complete_efd']); self.assertFalse(after_block['pva_validated']); self.assertFalse(after_block['transmitted'])
        self.assertEqual({d['id'] for d in docs}, {t['document_id'] for t in after_block['trace']})
        preview = self.consolidation_preview()
        self.assertEqual(3, preview['summary']['included_documents'])
        self.assertEqual(1, len(self.core.journals(self.a['id'], year=2026)))
        self.assertEqual(before, self.database_hash(), 'SPED preview/export cannot change accounting')

    def test_partial_reversal_changes_book_scope_only_through_existing_document_status(self):
        batch, raw = self.import_xmls(1, 2, 3, book=True)
        self.mode(); model = self.model(); docs = self.core.documents(self.a['id'])
        generated = self.generate(docs, model); original = generated['journals'][0]
        doc = next(d for d in self.core.documents(self.a['id']) if d['id'] == docs[0]['id'])
        reversed_doc = self.reverse(doc)['document']
        before = self.database_hash(); block = self.block_c(); preview = self.consolidation_preview()
        self.assertEqual((2, 20000), (block['summary']['exported_documents'], block['summary']['total_cents']))
        self.assertEqual([doc['id']], [s['document_id'] for s in block['skipped']])
        self.assertEqual(3, preview['summary']['included_documents'])
        # Imported booking retains the informational review-pending flag on all three.
        self.assertEqual(3, preview['summary']['review_pending_documents'])
        self.assertEqual(20000, next(r for r in self.balances()['rows'] if r['access_code'] == '3')['closing_cents'])
        self.assertEqual(original, self.client.get(self.scope(f"/journals/{original['id']}")).json())
        self.assertEqual(before, self.database_hash())
        reviewed = self.post(f"/documents/{doc['id']}/review", {'version': reversed_doc['version'], 'reason': 'Nova revisão sintética'})
        booked = self.post(f"/documents/{doc['id']}/book", {'version': reviewed['version'], 'reason': 'Nova escrituração sintética'})['document']
        self.mode('individual'); self.generate([booked], model, 'compose-rebook')
        self.assertEqual(3, self.block_c()['summary']['exported_documents'])
        self.assertEqual(30000, next(r for r in self.balances()['rows'] if r['access_code'] == '3')['closing_cents'])
        with self.core.db.read() as conn:
            self.assertEqual(raw, conn.execute('SELECT original FROM imports WHERE id=?', (batch['id'],)).fetchone()[0])
            self.assertEqual([], conn.execute('PRAGMA foreign_key_check').fetchall())

    def test_closed_period_allows_readonly_sped_and_report_but_preserves_accounting_guard(self):
        self.import_xmls(1, 2, book=True)
        self.mode(); model = self.model(); docs = self.core.documents(self.a['id'])
        self.generate(docs[:1], model)
        self.post('/periods/close', {'module': 'fiscal', 'period': '2026-11', 'reason': 'Fechamento sintético'})
        before = self.database_hash()
        self.assertEqual(2, self.block_c()['summary']['exported_documents'])
        self.consolidation_preview()
        self.core.business_report(self.a['id'], 'consolidated-diary', '2026-11-01', '2026-11-30')
        self.generate(docs[1:], model, 'compose-closed', status=409)
        self.assertEqual(before, self.database_hash())
        self.post('/periods/reopen', {'module': 'fiscal', 'period': '2026-11', 'reason': 'Reabertura sintética'})
        self.assertEqual(1, self.generate(docs[1:], model, 'compose-closed')['created_count'])
        self.assertEqual(2, self.block_c()['summary']['exported_documents'])

    def test_native_export_remains_independent_from_created_journals(self):
        self.import_xmls(1, 2, book=True)
        self.mode(); model = self.model(); self.generate(self.core.documents(self.a['id']), model)
        batch, raw = self.source_batch()
        before = self.database_hash()
        for enabled in (False, True):
            result = self.post('/sped-generator/consolidation-export', {'period': '2026-11', 'import_id': batch['id'], 'consolidate_nfce': enabled})
            if enabled: self.assertTrue(result['consolidated'])
            else: self.assertEqual(raw, base64.b64decode(result['content_base64']))
        self.assertEqual(2, self.block_c()['summary']['exported_documents'])
        self.assertEqual(1, len(self.core.journals(self.a['id'], year=2026)))
        self.assertEqual(before, self.database_hash())

    def test_export_grant_does_not_grant_accounting_generation_after_route_composition(self):
        self.import_xmls(1, book=True); self.mode(); model = self.model(); docs = self.core.documents(self.a['id'])
        payload = self.payload(docs, model)
        client, _ = self.operator({'fiscal.documents': ['read', 'export']})
        try:
            before = self.database_hash()
            response = client.post(self.scope('/sped-generator/bookkeeping-block-c'), json={'period': '2026-11'})
            self.assertEqual(200, response.status_code, response.text)
            response = client.post(self.scope(sales.ROOT + '/generate'), json=payload)
            self.assertEqual(403, response.status_code, response.text)
            self.assertEqual(before, self.database_hash())
        finally: client.close()


    def import_prosoft_xmls(self, *numbers):
        # Numeric synthetic issuer makes the XML access key representable in Prosoft.
        # Existing SPED fixtures intentionally also exercise alphanumeric tax IDs.
        self.a = self.create_company('PROSOFT001', '112223330001')
        self.activate(self.a['id'])
        self.accounts = self.client.get(self.scope('/accounts')).json()
        self.aid = {a['access_code']: a['id'] for a in self.accounts}
        return self.import_xmls(*numbers, book=True)

    def prosoft_economic_snapshot(self):
        economic = {'documents', 'document_sources', 'journals', 'journal_lines', 'titles', 'imports'}
        return {table: rows for table, rows in self.snapshot().items() if table in economic}

    def prosoft_fiscal_payload(self):
        return prosoft.configuration() | {'period': '2026-11', 'company_code': '99'}

    def prosoft_accounting_payload(self, *, cta=False, journal_ids=None):
        mappings = {str(a['id']): {'code': a['access_code'], 'confirmed': True} for a in self.accounts}
        if cta:
            mappings[str(self.aid['3'])].update(third_mode='none', create_account={
                'destination_missing': True, 'classifier': '1.01', 'name': 'Conta sintetica',
                'cost_center_mode': '0', 'reconciliation': '0'})
        return {'period': '2026-11', 'company_code': '99', 'plan_code': '52',
                'accounts': mappings, 'allow_ascii': True, **({'journal_ids': journal_ids} if journal_ids else {})}

    def test_prosoft_daily_accounting_keeps_individual_fiscal_records_and_stale_preview_guard(self):
        from io import BytesIO
        from zipfile import ZipFile
        self.import_prosoft_xmls(1, 2, 3)
        fiscal_payload = self.prosoft_fiscal_payload()
        old = self.post('/prosoft-fiscal/preview', fiscal_payload)
        block = self.block_c()
        self.mode(); model = self.model()
        result = self.generate(self.core.documents(self.a['id']), model)
        self.assertEqual((1, 3), (result['created_count'], result['accounted_count']))
        manual = self.core.create_journal(self.a['id'], {
            'date': '2026-11-06', 'document': 'COMP1', 'history': 'Synthetic', 'idempotency_key': 'compose-lc2',
            'lines': [{'account_id': self.aid['3'], 'debit': '0.01'},
                      {'account_id': self.aid['4'], 'debit': '0.02'},
                      {'account_id': self.aid['5'], 'credit': '0.03'}]}, 'synthetic')
        before = self.prosoft_economic_snapshot()
        self.post('/prosoft-fiscal/confirm', fiscal_payload | {
            'preview_hash': old['preview_hash'], 'destination_reviewed': True}, status=409)
        current = self.post('/prosoft-fiscal/preview', fiscal_payload)
        self.assertNotEqual(old['preview_hash'], current['preview_hash'])
        self.assertEqual(old['manifest']['files'], current['manifest']['files'])
        self.assertEqual((3, 3, 30000), tuple(current['manifest']['totals']['outgoing'][k]
                                            for k in ('documents', 'records', 'total_cents')))
        saved = self.post('/prosoft-fiscal/confirm', fiscal_payload | {
            'preview_hash': current['preview_hash'], 'destination_reviewed': True})
        response = self.client.get(self.scope(f"/prosoft-fiscal/exports/{saved['id']}/download"))
        self.assertEqual(200, response.status_code, response.text)
        with ZipFile(BytesIO(response.content)) as archive:
            self.assertEqual([2611] * 3, list(map(len, archive.read('SAIDAS.TXT').splitlines())))
        all_journals = self.post('/prosoft/preview', self.prosoft_accounting_payload())
        shortened = [r['document_reference'] for r in all_journals['manifest']['trace'] if 'document_reference' in r]
        self.assertEqual(['SAIDAS-FISCAIS'], [r['original'] for r in shortened])
        self.assertEqual(10, len(shortened[0]['exported']))
        accounting_payload = self.prosoft_accounting_payload(cta=True, journal_ids=[manual['id']])
        accounting = self.post('/prosoft/preview', accounting_payload)
        self.assertEqual({'CTA': 1, 'LC1': 1, 'LC2': 3}, accounting['manifest']['record_counts'])
        self.assertEqual(3, accounting['manifest']['debit_cents'])
        self.assertEqual(3, accounting['manifest']['credit_cents'])
        self.assertEqual('0052', accounting['manifest']['plan_code'])
        confirm = accounting_payload | {'preview_hash': accounting['preview_hash'], 'destination_reviewed': True}
        saved = self.post('/prosoft/confirm', confirm)
        self.assertEqual(saved['id'], self.post('/prosoft/confirm', confirm)['id'])
        response = self.client.get(self.scope(f"/exports/{saved['id']}/download"))
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual([208, 448, 342, 342, 342], list(map(len, response.content.splitlines())))
        self.assertEqual(block, self.block_c())
        self.assertEqual(before, self.prosoft_economic_snapshot())
        self.assertFalse(current['manifest']['homologated_in_destination'])
        self.assertFalse(accounting['manifest']['homologated_in_destination'])

    def test_prosoft_partial_daily_reversal_preserves_compensation_and_fiscal_scope(self):
        self.import_prosoft_xmls(1, 2, 3)
        self.mode(); model = self.model(); docs = self.core.documents(self.a['id'])
        original = self.generate(docs, model)['journals'][0]
        current = next(d for d in self.core.documents(self.a['id']) if d['id'] == docs[0]['id'])
        compensation = self.reverse(current)['journal']
        before = self.database_hash()
        fiscal = self.post('/prosoft-fiscal/preview', self.prosoft_fiscal_payload())['manifest']
        self.assertEqual(20000, fiscal['totals']['outgoing']['total_cents'])
        self.assertEqual([docs[0]['id']], [s['document_id'] for s in fiscal['skipped']])
        self.assertEqual('not_booked', fiscal['skipped'][0]['reason'])
        all_journals = self.post('/prosoft/preview', self.prosoft_accounting_payload())
        shortened = [r['document_reference'] for r in all_journals['manifest']['trace'] if 'document_reference' in r]
        self.assertEqual(['SAIDAS-FISCAIS'], [r['original'] for r in shortened])
        self.assertEqual(10, len(shortened[0]['exported']))
        journals = self.core.journals(self.a['id'])
        self.assertEqual(40000, sum(j['total_cents'] for j in journals))
        self.assertTrue(all(sum(l['debit_cents'] for l in j['lines']) ==
                            sum(l['credit_cents'] for l in j['lines']) for j in journals))
        self.assertEqual({original['id'], compensation['id']}, {j['id'] for j in self.core.journals(self.a['id'])})
        self.assertEqual(20000, self.block_c()['summary']['total_cents'])
        self.assertEqual(before, self.database_hash())

    def test_prosoft_exports_closed_period_without_weakening_daily_generation_guard(self):
        self.import_prosoft_xmls(1, 2)
        self.mode(); model = self.model(); docs = self.core.documents(self.a['id'])
        self.generate(docs[:1], model)
        manual = self.core.create_journal(self.a['id'], self.journal(key='compose-export-closed') |
                                          {'document': 'COMP2', 'history': 'Synthetic'}, 'synthetic')
        for module in ('fiscal', 'accounting'):
            self.post('/periods/close', {'module': module, 'period': '2026-11', 'reason': 'Fechamento sintetico'})
        before = self.prosoft_economic_snapshot()
        for root, payload in [('/prosoft-fiscal', self.prosoft_fiscal_payload()),
                              ('/prosoft', self.prosoft_accounting_payload(journal_ids=[manual['id']]))]:
            preview = self.post(root + '/preview', payload)
            self.post(root + '/confirm', payload | {'preview_hash': preview['preview_hash'], 'destination_reviewed': True})
        self.generate(docs[1:], model, 'prosoft-compose-closed', status=409)
        self.assertEqual(2, self.block_c()['summary']['exported_documents'])
        self.assertEqual(before, self.prosoft_economic_snapshot())


if __name__ == '__main__':
    unittest.main()
