"""Direct posting, source preservation, CFOP provenance and atomic guards."""
import base64
import io
import json
from pathlib import Path
import unittest
import zipfile

from fastapi.testclient import TestClient
import test_core as base
from app.cfop import cfop_at, reference
from scripts.build_cfop_reference import build, SOURCE


class FiscalImportTests(unittest.TestCase):
    setUp = base.CoreApiTests.setUp
    tearDown = base.CoreApiTests.tearDown
    create_company = base.CoreApiTests.create_company
    activate = base.CoreApiTests.activate
    scope = base.CoreApiTests.scope
    document = base.CoreApiTests.document

    def post(self, path, payload, status=200):
        r = self.client.post(self.scope(path), json=payload)
        self.assertEqual(status, r.status_code, r.text)
        return r.json()

    def xml(self, production=True):
        raw = (Path(__file__).parent / 'fixtures/nfe_ficticia.xml').read_bytes()
        raw = raw.replace(b'12345678000195', self.a['tax_id'].encode())
        return raw.replace(b'<tpAmb>2</tpAmb>', b'<tpAmb>1</tpAmb>') if production else raw

    def preview(self, raw=None, filename='origem.xml'):
        return self.post('/imports/preview', {'filename': filename, 'period': '2026-11', 'content_base64': base64.b64encode(raw or self.xml()).decode()})

    def mapping(self, **extra):
        return self.post('/fiscal-import-mappings', {'direction': 'incoming', 'model': '55', 'source_cfop': '5102', 'target_cfop': '1102', 'valid_from': '2026-01-01', 'valid_to': '', 'reason': 'Associação sintética, sem enquadramento fiscal real', 'responsible': 'Teste', **extra})

    def prepared(self, batch, **extra):
        return self.post(f"/imports/{batch['id']}/posting-preview", extra)

    def confirm(self, batch, prepared, status=200, **extra):
        return self.post(f"/imports/{batch['id']}/confirm", {'posting_mode': 'book', 'posting_hash': prepared['posting_hash'], 'preview_hash': batch['preview_hash'], 'selected': [d['_selection'] for d in prepared['documents']], **extra}, status)

    def test_reference_complete_reproducible_and_wording_versions(self):
        self.assertEqual(reference(), build(SOURCE.read_text(encoding='utf-8')))
        self.assertEqual(619, len({r['code'] for r in reference()['entries']}))
        self.assertEqual(620, len(reference()['entries']))
        self.assertEqual(76, len(reference()['groups']))
        self.assertTrue(cfop_at('7667', '2025-12-01')['title'].startswith('Venda'))
        self.assertTrue(cfop_at('7667', '2026-02-01')['title'].startswith('Saída'))
        r = self.client.get(self.scope('/cfop-reference?date=2026-11-01&search=1102')).json()
        self.assertEqual('1102', r['rows'][0]['code'])
        self.assertIn('confaz.fazenda.gov.br', r['source'])

    def test_copy_reference_is_per_company_and_preserves_local_records(self):
        self.post('/catalogs', {'kind': 'cfop', 'code': '1102', 'description': 'Descrição local sintética', 'source': 'Referência revisada do teste'}, 201)
        result = self.post('/cfop-reference/apply', {'edition': reference()['edition'], 'date': '2026-11-01', 'reason': 'Importação sintética'})
        self.assertEqual((618, 1), (result['created'], result['preserved']))
        rows = self.core.catalogs(self.a['id'], 'cfop')
        self.assertEqual('Descrição local sintética', next(r for r in rows if r['code'] == '1102')['description'])
        self.assertEqual([], self.core.catalogs(self.b['id'], 'cfop'))
        self.assertEqual(0, self.post('/cfop-reference/apply', {'edition': reference()['edition'], 'date': '2026-11-01', 'reason': 'Repetição'})['created'])

    def test_company_mapping_posts_without_financial_or_accounting_effects(self):
        mapping = self.mapping(); batch = self.preview(); prepared = self.prepared(batch)
        self.assertTrue(prepared['documents'][0]['import_posting']['eligible'])
        result = self.confirm(batch, prepared)
        self.assertEqual(1, result['documents_booked'])
        doc = self.core.documents(self.a['id'])[0]
        self.assertEqual('booked', doc['status']); self.assertEqual('1102', doc['items'][0]['cfop'])
        self.assertEqual('5102', doc['items'][0]['source_cfop'])
        self.assertIsNone(doc['reviewed_by']); self.assertTrue(doc['import_posting']['review_pending'])
        self.assertEqual(mapping['id'], doc['import_posting']['mappings'][0]['mapping_id'])
        self.assertEqual([], self.core.journals(self.a['id'])); self.assertEqual([], self.core.titles(self.a['id']))
        self.assertTrue(self.confirm(batch, prepared)['duplicate'])

    def test_edit_review_and_reimport_preserve_original_and_latest_revision(self):
        self.mapping(); batch = self.preview(); self.confirm(batch, self.prepared(batch))
        doc = self.core.documents(self.a['id'])[0]
        r = self.client.put(self.scope(f"/documents/{doc['id']}"), json=doc | {'partner_name': 'Contraparte corrigida no teste', 'reason': 'Correção rastreável posterior à importação'})
        self.assertEqual(200, r.status_code, r.text); edited = r.json()
        self.assertEqual('booked', edited['status']); self.assertEqual(doc['source_hash'], edited['source_hash'])
        self.assertEqual('5102', edited['items'][0]['source_cfop'])
        reviewed = self.post(f"/documents/{doc['id']}/review", {'version': edited['version'], 'reason': 'Conferência posterior sintética'})
        self.assertFalse(reviewed['import_posting']['review_pending'])
        again = self.preview(filename='mesmo-original-renomeado.xml')
        result = self.confirm(again, self.prepared(again))
        self.assertEqual(1, result['documents_duplicate']); self.assertEqual(0, result['documents_booked'])
        self.assertEqual('Contraparte corrigida no teste', self.core.documents(self.a['id'])[0]['partner_name'])
        self.assertEqual(self.xml(), self.app.state.db.connect().execute('SELECT original FROM imports WHERE id=?', (batch['id'],)).fetchone()[0])
        stale = self.client.put(self.scope(f"/documents/{doc['id']}"), json=doc | {'reason': 'Versão antiga'})
        self.assertEqual(409, stale.status_code)

    def test_missing_mapping_invalid_direction_and_unknown_code_block(self):
        batch = self.preview(); p = self.prepared(batch)
        self.assertFalse(p['documents'][0]['import_posting']['eligible']); self.confirm(batch, p, 409)
        for code in ['5102', '9999', '1000']:
            p = self.prepared(batch, cfop_mappings={'incoming:55:5102': code})
            self.assertFalse(p['documents'][0]['import_posting']['eligible'])
            self.confirm(batch, p, 409, cfop_mappings={'incoming:55:5102': code})
        self.assertEqual([], self.core.documents(self.a['id']))

    def test_one_off_mapping_does_not_change_company_parameters(self):
        batch = self.preview(); overrides = {'incoming:55:5102': '1102'}
        p = self.prepared(batch, cfop_mappings=overrides)
        self.confirm(batch, p, cfop_mappings=overrides)
        self.assertEqual([], self.core.import_cfop_mappings(self.a['id']))
        self.assertEqual('batch', self.core.documents(self.a['id'])[0]['import_posting']['mappings'][0]['origin'])

    def test_mapping_change_invalidates_prepared_posting(self):
        m = self.mapping(); batch = self.preview(); p = self.prepared(batch)
        r = self.client.put(self.scope('/fiscal-import-mappings/'+str(m['id'])), json=m['data'] | {'version': m['version'], 'target_cfop': '1403'})
        self.assertEqual(200, r.status_code, r.text)
        self.confirm(batch, p, 409)
        self.assertEqual([], self.core.documents(self.a['id']))

    def test_mapping_overlap_company_and_permission_guards(self):
        m = self.mapping()
        self.post('/fiscal-import-mappings', m['data'], 409)
        self.assertEqual([], self.core.import_cfop_mappings(self.b['id']))
        self.activate(self.b['id'])
        r = self.client.put(self.scope('/fiscal-import-mappings/'+str(m['id'])), json=m['data'] | {'version': m['version']})
        self.assertEqual(409, r.status_code)
        with TestClient(self.app) as anonymous:
            self.assertEqual(401, anonymous.get(self.scope('/cfop-reference')).status_code)

    def test_homologation_and_missing_protocol_require_individual_review(self):
        self.mapping()
        for raw, name in [(self.xml(False), 'homologacao.xml'), (self.xml().split(b'<protNFe')[0]+b'</nfeProc>', 'sem-protocolo.xml')]:
            batch = self.preview(raw, name); p = self.prepared(batch)
            self.assertFalse(p['documents'][0]['import_posting']['eligible']); self.confirm(batch, p, 409)
        self.assertEqual([], self.core.documents(self.a['id']))

    def test_closed_period_and_finalized_assessment_block_direct_posting(self):
        self.mapping(); batch = self.preview(); p = self.prepared(batch)
        self.post('/periods/close', {'module': 'fiscal', 'period': '2026-11', 'reason': 'Fechamento sintético'})
        self.confirm(batch, p, 409); self.assertEqual([], self.core.documents(self.a['id']))
        self.post('/periods/reopen', {'module': 'fiscal', 'period': '2026-11', 'reason': 'Reabrir teste'})
        a = self.post('/assessments', {'period': '2026-11', 'tax': 'icms', 'source': 'Cenário sintético', 'responsible': 'Teste', 'idempotency_key': 'empty', 'entries': [], 'no_movement_confirmed': True})
        self.post(f"/assessments/{a['id']}/finalize", {'period': '2026-11', 'reason': 'Finalização de teste', 'coverage_reviewed': True, 'idempotency_key': 'final'})
        self.confirm(batch, self.prepared(batch), 409)

    def test_mixed_batch_is_atomic_and_legacy_pending_mode_remains(self):
        self.mapping(); out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as z:
            z.writestr('a.xml', self.xml())
            z.writestr('b.xml', self.xml().replace(b'0000000421000000420', b'0000000431000000430').replace(b'<nNF>42</nNF>', b'<nNF>43</nNF>').replace(b'<CFOP>5102</CFOP>', b'<CFOP>5101</CFOP>'))
        batch = self.preview(out.getvalue(), 'lote.zip'); self.confirm(batch, self.prepared(batch), 409)
        self.assertEqual([], self.core.documents(self.a['id']))
        self.post(f"/imports/{batch['id']}/confirm", {'preview_hash': batch['preview_hash'], 'selected': ['documents:0'], 'posting_mode': 'pending'})
        self.assertEqual('pending', self.core.documents(self.a['id'])[0]['status'])

    def test_manual_input_cannot_forge_import_provenance(self):
        d = self.post('/documents', self.document() | {'import_posting': {'original_business_key': 'forged'}}, 201)
        self.assertNotIn('import_posting', d)

    def test_company_catalog_inactivation_blocks_posting_and_changed_preview(self):
        self.mapping(); batch = self.preview(); prepared = self.prepared(batch)
        self.post('/catalogs', {'kind': 'cfop', 'code': '1102', 'description': 'Cadastro sintético', 'active': False, 'source': 'Decisão do teste'}, 201)
        self.confirm(batch, prepared, 409)
        p = self.prepared(batch)
        self.assertFalse(p['documents'][0]['import_posting']['eligible'])
        self.confirm(batch, p, 409)
        self.assertEqual([], self.core.documents(self.a['id']))

    def test_invalid_json_types_are_rejected_without_server_errors(self):
        batch = self.preview()
        self.post(f"/imports/{batch['id']}/confirm", {'preview_hash': batch['preview_hash'], 'posting_mode': []}, 400)
        self.post('/fiscal-import-mappings', {'direction': {}}, 400)

    def test_item_origin_cannot_be_changed_or_forged_during_ledger_edit(self):
        self.mapping(); batch = self.preview(); self.confirm(batch, self.prepared(batch))
        doc = self.core.documents(self.a['id'])[0]
        for field, value in [('source_cfop', '5101'), ('source', {'file': 'forjado.xml'}), ('declared_product_fields', {})]:
            items = json.loads(json.dumps(doc['items'])); items[0][field] = value
            r = self.client.put(self.scope(f"/documents/{doc['id']}"), json={'version': doc['version'], 'reason': 'Tentativa sintética', 'items': items})
            self.assertEqual(409, r.status_code, r.text); self.assertEqual('item_origin_preserved', r.json()['code'])
        self.assertEqual('5102', self.core.documents(self.a['id'])[0]['items'][0]['source_cfop'])

    def test_import_right_does_not_grant_posting_or_parameter_edit(self):
        self.mapping(); batch = self.preview(); prepared = self.prepared(batch)
        permissions = [{'company_id': self.a['id'], 'routine': routine, 'action': action, 'effect': 'allow'}
                       for routine, actions in [('fiscal.imports', ['read', 'import']), ('fiscal.documents', ['read', 'create', 'edit'])] for action in actions]
        r = self.client.post('/api/users', json={'username': 'import-only', 'password': 'Senha-sintetica-2026', 'role': 'custom', 'company_ids': [self.a['id']], 'permissions': permissions})
        self.assertEqual(201, r.status_code, r.text)
        with TestClient(self.app) as client:
            s = client.post('/api/login', json={'username': 'import-only', 'password': 'Senha-sintetica-2026'}).json()
            client.headers['X-CSRF-Token'] = s['csrf_token']
            self.assertEqual(200, client.post('/api/context', json={'company_id': self.a['id'], 'module': 'fiscal', 'period': '2026-11'}).status_code)
            r = client.post(self.scope(f"/imports/{batch['id']}/confirm"), json={'preview_hash': batch['preview_hash'], 'posting_mode': 'book', 'posting_hash': prepared['posting_hash']})
            self.assertEqual(403, r.status_code, r.text)
            self.assertEqual([], self.core.documents(self.a['id']))
            self.assertEqual(403, client.post(self.scope('/fiscal-import-mappings'), json={}).status_code)
            self.assertEqual(403, client.get(self.scope('/cfop-reference', self.b['id'])).status_code)
            r = client.post(self.scope(f"/imports/{batch['id']}/confirm"), json={'preview_hash': batch['preview_hash'], 'posting_mode': 'pending'})
            self.assertEqual(200, r.status_code, r.text)
            self.assertEqual('pending', self.core.documents(self.a['id'])[0]['status'])

    def test_linked_effects_and_import_identity_prevent_inconsistent_edit(self):
        self.mapping(); batch = self.preview(); self.confirm(batch, self.prepared(batch))
        doc = self.core.documents(self.a['id'])[0]
        r = self.client.put(self.scope(f"/documents/{doc['id']}"), json={'version': doc['version'], 'reason': 'Não mover identidade', 'key': '8'*44})
        self.assertEqual(409, r.status_code); self.assertEqual('import_identity_preserved', r.json()['code'])
        with self.app.state.db.transaction() as conn:
            self.core._create_title(conn, self.a['id'], {'kind': 'payable', 'description': 'Vínculo sintético', 'partner_name': doc['partner_name'], 'document': doc['number'], 'document_id': doc['id'], 'issue_date': doc['issue_date'], 'due_date': '2026-12-05', 'amount': '100.00'}, 'teste')
        r = self.client.put(self.scope(f"/documents/{doc['id']}"), json={'version': doc['version'], 'reason': 'Preservar vínculo', 'total': '101.00'})
        self.assertEqual(409, r.status_code); self.assertEqual('document_linked_effects', r.json()['code'])
