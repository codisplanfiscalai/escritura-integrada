"""Pre-import corrections use a fresh preview and never rewrite source identity."""
import json
import unittest
from pathlib import Path
from app.core import digest
from unittest.mock import patch
import test_fiscal_import as base


class ImportRevisionTests(unittest.TestCase):
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

    def test_individual_date_cfop_and_original_preserved(self):
        batch = self.preview()
        overrides = {'documents:0': {'posting_date': '2026-12-02', 'cfop': '1102'}}
        prepared = self.prepared(batch, document_overrides=overrides)
        doc = prepared['documents'][0]
        self.assertTrue(doc['import_posting']['eligible'])
        self.assertEqual('2026-12-02', doc['posting_date'])
        self.assertEqual(batch['documents'][0]['issue_date'], doc['issue_date'])
        self.assertEqual('5102', doc['items'][0]['source_cfop'])
        result = self.confirm(batch, prepared, document_overrides=overrides)
        saved = self.core.documents(self.a['id'], year=2026)[0]
        self.assertEqual('2026-12-02', saved['posting_date'])
        self.assertEqual('document', saved['import_posting']['mappings'][0]['origin'])
        with self.app.state.db.read() as conn:
            original = json.loads(conn.execute('SELECT parsed_json FROM imports WHERE id=?', (batch['id'],)).fetchone()[0])
        self.assertEqual(batch['documents'][0]['posting_date'], original['documents'][0]['posting_date'])
        self.assertTrue(self.confirm(batch, prepared, document_overrides=overrides)['duplicate'])
        self.confirm(batch, prepared, 409, document_overrides={'documents:0': {'posting_date': '2026-12-03', 'cfop': '1102'}})

    def test_changed_date_after_preparation_and_closed_period_are_blocked(self):
        batch = self.preview()
        first = {'documents:0': {'posting_date': '2026-12-02', 'cfop': '1102'}}
        second = {'documents:0': {'posting_date': '2026-12-03', 'cfop': '1102'}}
        prepared = self.prepared(batch, document_overrides=first)
        self.confirm(batch, prepared, 409, document_overrides=second)
        self.post('/periods/close', {'module': 'fiscal', 'period': '2026-12', 'reason': 'Teste'})
        blocked = self.prepared(batch, document_overrides=first)
        self.assertFalse(blocked['documents'][0]['import_posting']['eligible'])
        self.confirm(batch, blocked, 409, document_overrides=first)
        self.assertEqual([], self.core.documents(self.a['id']))

    def test_invalid_override_fields_targets_dates_and_cfops_are_rejected(self):
        batch = self.preview()
        for revision in [[], {'documents:9': {}}, {'documents:0': {'issue_date': '2026-11-01'}}, {'documents:0': {'posting_date': '2026-02-30'}}, {'documents:0': {'cfop': 1102}}]:
            self.post(f"/imports/{batch['id']}/posting-preview", {'document_overrides': revision}, 400)
        for revision in [{'posting_date': '2027-01-01', 'cfop': '1102'}, {'cfop': '5102'}, {'cfop': '9999'}]:
            overrides = {'documents:0': revision}
            prepared = self.prepared(batch, document_overrides=overrides)
            self.assertFalse(prepared['documents'][0]['import_posting']['eligible'])
            self.confirm(batch, prepared, 409, document_overrides=overrides)

    def test_auxiliary_uses_exact_original_and_is_read_only(self):
        batch = self.preview()
        with patch('app.auxiliary.render_danfe', return_value=(b'%PDF-test', 'test-renderer')) as renderer:
            response = self.client.get(self.scope(f"/imports/{batch['id']}/documents/0/danfe"))
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual(b'%PDF-test', response.content)
            renderer.assert_called_once_with(self.xml())
        self.assertEqual([], self.core.documents(self.a['id']))
        self.assertEqual(404, self.client.get(self.scope(f"/imports/{batch['id']}/documents/1/danfe")).status_code)
        self.activate(self.b['id'])
        self.assertEqual(404, self.client.get(self.scope(f"/imports/{batch['id']}/documents/0/danfe", self.b['id'])).status_code)

    def test_real_auxiliary_from_complete_xml_in_zip(self):
        import io, zipfile
        raw = (Path(__file__).parent / 'fixtures/auditor_demo.xml').read_bytes()
        raw = raw.replace(b'99999999000191', self.a['tax_id'].encode())
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('nota.xml', raw)
            archive.writestr('nota.pdf', b'%PDF-1.4\naccessory')
        batch = self.preview(output.getvalue(), 'visual.zip')
        response = self.client.get(self.scope(f"/imports/{batch['id']}/documents/0/danfe"))
        self.assertEqual(200, response.status_code, response.text)
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertEqual([], self.core.documents(self.a['id']))

    def test_new_parser_revision_reanalyzes_legacy_cached_preview(self):
        batch = self.preview()
        old_identity = digest({'sha256': digest(self.xml()), 'filename': 'origem.xml',
            'period': '2026-11', 'options': {}, 'company_tax_id': self.a['tax_id']})
        with self.app.state.db.transaction() as conn:
            conn.execute('UPDATE imports SET identity_hash=? WHERE id=?', (old_identity, batch['id']))
        refreshed = self.preview()
        self.assertNotEqual(batch['id'], refreshed['id'])
        self.assertTrue(refreshed['can_confirm'])

    def test_pending_reimport_after_noop_save_preserves_linked_master_identity(self):
        batch = self.preview()
        result = self.post(f"/imports/{batch['id']}/confirm", {'preview_hash': batch['preview_hash'], 'posting_mode': 'pending'})
        doc = self.core.documents(self.a['id'])[0]
        self.assertTrue(doc['items'][0]['master_id'])
        response = self.client.put(self.scope(f"/documents/{doc['id']}"), json={'version': doc['version'], 'reason': 'Salvar sem alterar conteúdo'})
        self.assertEqual(200, response.status_code, response.text)
        again = self.preview(filename='mesmo-conteudo.xml')
        repeated = self.post(f"/imports/{again['id']}/confirm", {'preview_hash': again['preview_hash'], 'posting_mode': 'pending'})
        self.assertEqual(1, repeated['documents_duplicate'])
        self.assertEqual(1, len(self.core.masters(self.a['id'], 'product')))

    def test_one_document_keeps_two_analytic_posting_lines_and_separate_dates(self):
        raw = (Path(__file__).parent / 'fixtures/sped_ficticio_020.txt').read_bytes()
        raw = raw.replace(b'12345678000195', self.a['tax_id'].encode())
        raw = raw.replace(b'05112026|06112026', b'30102026|06112026')
        original = b'|C190|000|1102|18,00|100,00|100,00|18,00|0,00|0,00|0,00|0,00||'
        split = b'|C190|000|1102|18,00|60,00|60,00|10,80|0,00|0,00|0,00|0,00||\n|C190|060|1403|0,00|40,00|0,00|0,00|0,00|0,00|0,00|0,00||'
        batch = self.preview(raw.replace(original, split), 'rateio-sintetico.txt')
        self.assertEqual(1, len(batch['documents']))
        self.assertEqual(2, len(batch['documents'][0]['analytics']))
        self.post(f"/imports/{batch['id']}/confirm", {'preview_hash': batch['preview_hash'], 'posting_mode': 'pending'})
        doc = self.core.documents(self.a['id'])[0]
        self.assertEqual('2026-10-30', doc['issue_date'])
        self.assertEqual('2026-11-06', doc['posting_date'])
        self.assertEqual(['60.00', '40.00'], [r['operation_total'] for r in doc['analytics']])
        self.assertEqual(['1102', '1403'], [r['cfop'] for r in doc['analytics']])

    def test_same_key_different_xml_bytes_warn_without_inventing_fiscal_difference(self):
        first = self.preview()
        self.post(f"/imports/{first['id']}/confirm", {'preview_hash': first['preview_hash'], 'posting_mode': 'pending'})
        second = self.preview(self.xml() + b'\n', 'outra-versao.xml')
        repeated = self.post(f"/imports/{second['id']}/confirm", {'preview_hash': second['preview_hash'], 'posting_mode': 'pending'})
        self.assertEqual((0, 1), (repeated['documents_created'], repeated['documents_duplicate']))
        self.assertEqual(1, len(repeated['source_version_warnings']))
        self.assertIn('não comprova divergência fiscal', repeated['source_version_warnings'][0])
        self.assertEqual(2, len(self.core.documents(self.a['id'])[0]['sources']))
        changed = self.preview(self.xml().replace(b'<vNF>100.00</vNF>', b'<vNF>101.00</vNF>'), 'total-alterado.xml')
        self.post(f"/imports/{changed['id']}/confirm", {'preview_hash': changed['preview_hash'], 'posting_mode': 'pending'}, 409)
        self.assertEqual(1, len(self.core.documents(self.a['id'])))

    def test_simultaneous_reimports_create_one_document(self):
        from concurrent.futures import ThreadPoolExecutor
        batches = [self.preview(filename=name) for name in ['lote-a.xml', 'lote-b.xml']]
        def confirm(batch):
            return self.core.confirm_import(self.a['id'], batch['id'], {'preview_hash': batch['preview_hash'], 'posting_mode': 'pending'}, 'synthetic-concurrent')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(confirm, batches))
        self.assertEqual(1, sum(r['documents_created'] for r in results))
        self.assertEqual(1, sum(r['documents_duplicate'] for r in results))
        self.assertEqual(results[0]['document_ids'], results[1]['document_ids'])
        self.assertEqual(1, len(self.core.documents(self.a['id'])))

    def test_same_key_is_isolated_per_company_and_model_conflict_does_not_duplicate(self):
        raw = self.xml().replace(b'87654321000198', self.b['tax_id'].encode())
        first = self.preview(raw)
        self.post(f"/imports/{first['id']}/confirm", {'preview_hash': first['preview_hash'], 'posting_mode': 'pending'})
        altered = self.preview(raw.replace(b'<mod>55</mod>', b'<mod>65</mod>'), 'modelo-divergente.xml')
        self.post(f"/imports/{altered['id']}/confirm", {'preview_hash': altered['preview_hash'], 'posting_mode': 'pending'}, 409)
        self.activate(self.b['id'])
        import base64
        response = self.client.post(self.scope('/imports/preview', self.b['id']), json={'filename': 'emitente.xml', 'period': '2026-11', 'content_base64': base64.b64encode(raw).decode()})
        self.assertEqual(200, response.status_code, response.text)
        second = response.json()
        response = self.client.post(self.scope(f"/imports/{second['id']}/confirm", self.b['id']), json={'preview_hash': second['preview_hash'], 'posting_mode': 'pending'})
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(1, len(self.core.documents(self.a['id'])))
        self.assertEqual(1, len(self.core.documents(self.b['id'])))

    def test_key_does_not_authorize_unapproved_xml_or_event(self):
        batch = self.preview()
        mappings = {'incoming:55:5102': '1102'}
        prepared = self.prepared(batch, cfop_mappings=mappings)
        self.confirm(batch, prepared, cfop_mappings=mappings)
        for raw, filename in [(self.xml().replace(b'<cStat>100</cStat>', b'<cStat>110</cStat>'), 'nao-autorizado.xml'),
            (b'<procEventoNFe xmlns="http://www.portalfiscal.inf.br/nfe"><evento><infEvento><chNFe>35261187654321000198550010000000421000000420</chNFe></infEvento></evento></procEventoNFe>', 'evento.xml')]:
            refused = self.preview(raw, filename)
            self.assertFalse(refused['can_confirm'])
            self.post(f"/imports/{refused['id']}/confirm", {'preview_hash': refused['preview_hash'], 'posting_mode': 'pending'}, 409)
        self.assertEqual(1, len(self.core.documents(self.a['id'])))

    def test_import_settings_routes_enforce_parameters_read_and_edit(self):
        from fastapi.testclient import TestClient
        permissions = [{'company_id': self.a['id'], 'routine': 'fiscal.parameters', 'action': action, 'effect': effect}
            for action, effect in [('read', 'allow'), ('edit', 'deny')]]
        response = self.client.post('/api/users', json={'username': 'settings-reader', 'password': 'Senha-ficticia-123!', 'role': 'custom', 'company_ids': [self.a['id']], 'permissions': permissions})
        self.assertEqual(201, response.status_code, response.text)
        with TestClient(self.app) as client:
            session = client.post('/api/login', json={'username': 'settings-reader', 'password': 'Senha-ficticia-123!'}).json()
            client.headers['X-CSRF-Token'] = session['csrf_token']
            self.activate(self.a['id'], client=client)
            self.assertEqual(200, client.get(self.scope('/fiscal-import-settings')).status_code)
            self.assertEqual(200, client.get(self.scope('/fiscal-import-settings/catalog')).status_code)
            denied = client.put(self.scope('/fiscal-import-settings'), json={'purchase_destination': 'resale', 'fallback_mappings': [], 'reason': 'Teste', 'responsible': 'Teste', 'version': 0})
            self.assertEqual(403, denied.status_code)
        self.assertEqual(0, self.core.fiscal_import_settings(self.a['id'])['version'])

    def test_total_comparison_uses_source_vnf_and_reports_current_amount_separately(self):
        from app.fiscal_import import total_comparison
        result = total_comparison({'total_cents': 12567, 'taxes': {'ICMSTot/vNF': '100.00'}, 'declared_new_total': '110.00'})
        self.assertEqual('100.00', result['vNF'])
        self.assertEqual('125.67', result['document_total'])
        self.assertEqual('10.00', result['difference'])
