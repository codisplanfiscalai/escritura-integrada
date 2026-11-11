"""Complete XML consultation, company isolation and immutable source evidence."""
from copy import deepcopy
import hashlib
import base64
import json
from pathlib import Path
import unittest
from fastapi.testclient import TestClient
import test_core as base
from app.importers import parse_file

XML = (Path(__file__).parent / 'fixtures/nfe_ficticia.xml').read_bytes()


class MasterEvidenceTests(unittest.TestCase):
    setUp = base.CoreApiTests.setUp
    tearDown = base.CoreApiTests.tearDown
    create_company = base.CoreApiTests.create_company
    activate = base.CoreApiTests.activate
    scope = base.CoreApiTests.scope

    def xml(self, number='1'):
        raw = XML.replace(b'12345678000195', self.a['tax_id'].encode())
        raw = raw.replace(b'</emit>', b'<IE>001234</IE><CNAE>1234567</CNAE><CRT>3</CRT><enderEmit><xLgr>Rua Teste</xLgr><nro>10</nro><xCpl>Bloco A</xCpl><xMun>Cidade</xMun><UF>SP</UF><cPais>1058</cPais><xPais>BRASIL</xPais></enderEmit></emit>')
        raw = raw.replace(b'</prod>', b'<CEST>1234567</CEST><EXTIPI>01</EXTIPI><uTrib>CX</uTrib><qTrib>0.2500</qTrib><vUnTrib>400.0000000000</vUnTrib><cEANTrib>07891234567895</cEANTrib><rastro><nLote>A</nLote><qLote>1.000</qLote></rastro><rastro><nLote>B</nLote><qLote>2.000</qLote></rastro></prod>')
        return raw

    def create(self, *, legacy=False):
        raw = self.xml()
        parsed = parse_file('synthetic.xml', raw, self.a)
        self.assertTrue(parsed['can_confirm'], parsed['issues'])
        payload = parsed['documents'][0]
        payload['posting_date'] = '2026-11-06'
        if legacy:
            payload.pop('declared_xml')
            payload.pop('declared_document_fields')
        response = self.client.post(self.scope('/documents'), json=payload)
        self.assertEqual(201, response.status_code, response.text)
        return response.json(), raw

    def test_complete_xml_repeats_lexical_precision_and_imported_ie_grid(self):
        doc, raw = self.create()
        self.assertEqual('A', doc['items'][0]['declared_product_fields']['rastro[1]/nLote'])
        self.assertEqual('B', doc['items'][0]['declared_product_fields']['rastro[2]/nLote'])
        self.assertEqual('400.0000000000', doc['items'][0]['declared_product_fields']['vUnTrib'])
        party = self.core.masters(self.a['id'], 'participant')[0]
        self.assertEqual('Bloco A', party['data']['profile']['complement'])
        self.assertEqual('001234', party['data']['profile']['state_registrations'][0]['number'])
        self.assertIsNone(party['data']['profile']['state_registrations'][0]['active'])
        self.assertEqual('3', party['data']['crt'])
        product = self.core.masters(self.a['id'], 'product')[0]
        self.assertEqual('CX', product['data']['tax_unit'])
        self.assertNotIn('price', product['data'])
        self.assertNotIn('cfop', product['data'])
        saved = self.core.save_master(self.a['id'], 'product', product, 'teste', product['id'])
        self.assertNotIn('price', saved['data'], 'ordinary editing must not turn missing price into zero')
        product = saved
        response = self.client.get(self.scope(f"/masters/product/{product['id']}/evidence"))
        self.assertEqual(200, response.status_code, response.text)
        evidence = response.json()
        self.assertEqual(1, evidence['total'])
        self.assertEqual(doc['id'], evidence['items'][0]['document']['id'])
        self.assertEqual(doc['items'][0]['taxes'], evidence['items'][0]['values']['taxes'])
        before_taxes = deepcopy(doc['taxes'])
        revised = self.client.put(self.scope(f"/documents/{doc['id']}"), json={'version': doc['version'], 'reason': 'Revisão sintética', 'taxes': {'icms': '99.00'}})
        self.assertEqual(200, revised.status_code, revised.text)
        details = self.client.get(self.scope(f"/documents/{doc['id']}/xml-details")).json()
        self.assertEqual(before_taxes, details['document']['taxes'], 'consulted source must not follow operational tax edits')
        self.assertTrue(details['available'])
        self.assertEqual('stored', details['origin'])
        self.assertEqual('nfeProc', details['document']['declared_xml']['tag'])
        self.assertEqual('infProt', details['document']['declared_protocol']['tag'])
        self.assertFalse(any(c['tag'] == 'det' for c in details['document']['declared_document_fields']['children']))
        data = deepcopy(product['data']); data['import_identity']['code'] = 'Changed original'
        response = self.client.put(self.scope(f"/masters/product/{product['id']}"), json={**product, 'data': data})
        self.assertEqual(409, response.status_code)
        self.assertEqual('master_origin_preserved', response.json()['code'])
        self.assertEqual(404, self.client.get(self.scope(f"/masters/product/{product['id']}/evidence", self.b['id'])).status_code)

    def test_legacy_recovery_exact_hash_readonly_and_missing_original(self):
        doc, raw = self.create(legacy=True)
        before = self.core.documents(self.a['id'])
        endpoint = self.scope(f"/documents/{doc['id']}/xml-details")
        self.assertFalse(self.client.get(endpoint).json()['available'])
        # Preserve a genuine original via the supported import-preview flow.
        result = self.client.post(self.scope('/imports/preview'), json={'filename':'synthetic.xml','period':'2026-11','content_base64':base64.b64encode(raw).decode()})
        self.assertEqual(200, result.status_code, result.text)
        recovered = self.client.get(endpoint).json()
        self.assertTrue(recovered['available'])
        self.assertEqual('retained_xml', recovered['origin'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), recovered['source_hash'])
        self.assertEqual(before, self.core.documents(self.a['id']), 'read must not backfill or mutate posted documents')
        self.assertEqual(404, self.client.get(self.scope(f"/documents/{doc['id']}/xml-details", self.b['id'])).status_code)

    def test_initial_product_origin_survives_relinking(self):
        doc, _ = self.create()
        old_id = doc['items'][0]['master_id']
        new = self.core.save_master(self.a['id'], 'product', {'code': 'REVIEWED', 'name': 'Produto revisado', 'data': {}}, 'teste')
        items = deepcopy(doc['items']); items[0]['master_id'] = new['id']
        response = self.client.put(self.scope(f"/documents/{doc['id']}"), json={'version':doc['version'], 'reason':'Revisão do vínculo', 'items':items})
        self.assertEqual(200, response.status_code, response.text)
        previous = self.client.get(self.scope(f'/masters/product/{old_id}/evidence')).json()
        current = self.client.get(self.scope(f"/masters/product/{new['id']}/evidence")).json()
        self.assertEqual('initial_origin', previous['items'][0]['role'])
        self.assertEqual('item', current['items'][0]['role'])
        self.assertEqual(doc['items'][0]['taxes'], previous['items'][0]['values']['taxes'])
        # Older imported masters lack the hash field, but their create audit
        # already holds it. Recovery stays read-only and exact.
        with self.core.db.transaction() as conn:
            old_data = json.loads(conn.execute('SELECT data_json FROM masters WHERE id=?', (old_id,)).fetchone()['data_json'])
            old_data.pop('import_source_hash')
            conn.execute('UPDATE masters SET data_json=? WHERE id=?', (json.dumps(old_data), old_id))
        legacy = self.client.get(self.scope(f'/masters/product/{old_id}/evidence')).json()
        self.assertEqual('initial_origin', legacy['items'][0]['role'])

    def test_evidence_needs_both_master_and_document_read_permissions(self):
        doc, raw = self.create()
        mid = doc['items'][0]['master_id']
        result = self.client.post('/api/users', json={'username': 'masters-only', 'password': 'Senha-sintetica-2026',
            'role': 'custom', 'company_ids': [self.a['id']], 'permissions': [
                {'company_id': self.a['id'], 'routine': 'fiscal.masters', 'action': 'read', 'effect': 'allow'},
                {'company_id': self.a['id'], 'routine': 'fiscal.documents', 'action': 'read', 'effect': 'deny'}]})
        self.assertEqual(201, result.status_code, result.text)
        with TestClient(self.app) as client:
            client.post('/api/login', json={'username': 'masters-only', 'password': 'Senha-sintetica-2026'})
            master_result = client.get(self.scope('/masters/product'))
            self.assertEqual(200, master_result.status_code)
            self.assertNotIn('taxes', str(master_result.json()))
            self.assertNotIn('unit_price', str(master_result.json()))
            self.assertEqual(403, client.get(self.scope(f'/masters/product/{mid}/evidence')).status_code)
            self.assertEqual(403, client.get(self.scope(f"/documents/{doc['id']}/xml-details")).status_code)

    def test_attributes_preserved_without_changing_item_dedup_semantics(self):
        raw = self.xml()
        first = parse_file('test.xml', raw, self.a)['documents'][0]
        modified = raw.replace(b'<vProd>', b'<vProd source="declared">')
        second = parse_file('test.xml', modified, self.a)['documents'][0]
        self.assertEqual(first['items'], second['items'])
        self.assertNotEqual(first['declared_xml'], second['declared_xml'])

    def test_repeated_singleton_rejected_but_missing_ie_not_exempt(self):
        parsed = parse_file('bad.xml', self.xml().replace(b'</prod>', b'<cProd>Conflicting</cProd></prod>'), self.a)
        self.assertFalse(parsed['can_confirm'])
        self.assertTrue(any(i['code'] == 'XML_DUPLICATE_FIELD' for i in parsed['issues']))
        raw = self.xml().replace(b'<IE>001234</IE>', b'')
        parsed = parse_file('without-ie.xml', raw, self.a)
        payload = parsed['documents'][0] | {'posting_date': '2026-11-06'}
        result = self.client.post(self.scope('/documents'), json=payload)
        self.assertEqual(201, result.status_code, result.text)
        profile = self.core.masters(self.a['id'], 'participant')[0]['data']['profile']
        self.assertEqual('unknown', profile['ie_status'])
        self.assertEqual([], profile['state_registrations'])


if __name__ == '__main__':
    unittest.main()
