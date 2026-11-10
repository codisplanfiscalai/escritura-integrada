"""Atomic XML master creation, identity isolation and anonymous consumers."""
import unittest
from fastapi.testclient import TestClient
import test_core as base


class ImportMastersTests(unittest.TestCase):
    setUp = base.CoreApiTests.setUp
    tearDown = base.CoreApiTests.tearDown
    create_company = base.CoreApiTests.create_company
    activate = base.CoreApiTests.activate
    scope = base.CoreApiTests.scope
    document = base.CoreApiTests.document

    def payload(self, number='XML1', issuer='87654321000198'):
        return self.document(number) | {
            'partner_tax_id': issuer, 'partner_name': 'Fornecedor XML',
            'document_type': 'goods', 'issuer': {'tax_id': issuer, 'name': 'Fornecedor XML'},
            'recipient': {'tax_id': self.a['tax_id'], 'name': self.a['name']},
            'items': [{'code': 'SKU1', 'description': 'Produto XML', 'unit': 'UN', 'ncm': '99999999'}]}

    def create(self, payload):
        r = self.client.post(self.scope('/documents'), json=payload)
        self.assertEqual(201, r.status_code, r.text)
        return r.json()

    def test_links_idempotence_and_no_tax_defaults(self):
        p = self.payload()
        doc = self.create(p)
        self.assertTrue(doc['participant_id'])
        self.assertTrue(doc['items'][0]['master_id'])
        self.assertTrue(self.create(p)['duplicate'])
        self.create(self.payload('XML2'))
        self.assertEqual(1, len(self.core.masters(self.a['id'], 'participant')))
        products = self.core.masters(self.a['id'], 'product')
        self.assertEqual(1, len(products))
        self.assertNotIn('cfop', products[0]['data'])
        self.assertNotIn('price', products[0]['data'])
        self.assertEqual([], self.core.masters(self.b['id'], 'product'))

    def test_supplier_codes_are_namespaced_and_services_separate(self):
        first = self.create(self.payload())
        second = self.create(self.payload('XML2', '11222333000181'))
        self.assertNotEqual(first['items'][0]['master_id'], second['items'][0]['master_id'])
        service = self.create(self.payload('XML3') | {'document_type': 'service'})
        self.assertNotEqual(first['items'][0]['master_id'], service['items'][0]['master_id'])
        self.assertEqual(1, len(self.core.masters(self.a['id'], 'service')))

    def test_nfe_service_item_uses_explicit_issqn_source_and_keeps_products_separate(self):
        from pathlib import Path
        from app.importers import parse_file
        product = self.payload()
        product['items'][0]['code'] = 'TESTE-001'
        goods = self.create(product)
        raw = (Path(__file__).parent / 'fixtures/nfe_ficticia.xml').read_bytes()
        raw = raw.replace(b'12345678000195', self.a['tax_id'].encode())
        start, end = raw.index(b'<imposto>'), raw.index(b'</imposto>') + len(b'</imposto>')
        raw = raw[:start] + b'<imposto><ISSQN><vBC>100.00</vBC><vAliq>2.00</vAliq><vISSQN>2.00</vISSQN><cMunFG>3550308</cMunFG><cListServ>01.01</cListServ></ISSQN></imposto>' + raw[end:]
        raw = raw.replace(b'<CFOP>5102</CFOP>', b'<CFOP>5933</CFOP>')
        parsed = parse_file('service-item.xml', raw, self.a)['documents'][0]
        self.assertEqual('goods', parsed['document_type'])  # NF-e header may mix item types.
        service = self.create(parsed)
        self.assertNotEqual(goods['items'][0]['master_id'], service['items'][0]['master_id'])
        services = self.core.masters(self.a['id'], 'service')
        self.assertEqual(1, len(services))
        self.assertEqual('01.01', services[0]['data']['service_code'])
        self.assertEqual(1, len(self.core.masters(self.a['id'], 'product')))
        self.assertEqual(parsed['items'][0]['taxes'], service['items'][0]['taxes'])
        self.assertNotIn('rate', services[0]['data'])
        self.assertNotIn('cfop', services[0]['data'])
        self.assertTrue(self.create(parsed)['duplicate'])
        self.assertEqual([], self.core.masters(self.b['id'], 'service'))

    def test_conflicting_item_tax_groups_keep_source_without_inventing_master_kind(self):
        payload = self.payload()
        payload['items'][0]['number'] = '1'
        payload['items'][0]['taxes'] = {'ICMS/ICMS00/vICMS': '18.00', 'ISSQN/vISSQN': '2.00'}
        doc = self.create(payload)
        self.assertNotIn('master_id', doc['items'][0])
        self.assertEqual(payload['items'][0]['taxes'], doc['items'][0]['taxes'])
        self.assertEqual([], self.core.masters(self.a['id'], 'product'))
        self.assertEqual([], self.core.masters(self.a['id'], 'service'))
        self.assertTrue(any('ICMS e ISSQN' in warning for warning in doc['master_import_warnings']))

    def test_participant_roles_preserve_reviewed_master_and_carrier(self):
        master = self.core.save_master(self.a['id'], 'participant', {
            'code': 'CUSTOM', 'name': 'Nome revisado', 'tax_id': '87654321000198',
            'data': {'roles': ['customer'], 'address': 'Endereço revisado'}}, 'teste')
        p = self.payload() | {'transport': {'carrier': {'tax_id': '87654321000198', 'name': 'Transportador XML'}}}
        doc = self.create(p)
        updated = self.core.masters(self.a['id'], 'participant')[0]
        self.assertEqual(master['id'], doc['participant_id'])
        self.assertEqual(master['id'], doc['carrier_id'])
        self.assertEqual('Nome revisado', updated['name'])
        self.assertEqual('Endereço revisado', updated['data']['address'])
        self.assertEqual({'supplier', 'carrier', 'customer'}, set(updated['data']['roles']))

    def test_anonymous_nfce_creates_product_not_fake_person(self):
        p = self.payload() | {'direction': 'outgoing', 'model': '65',
            'partner_tax_id': '', 'partner_name': 'Consumidor não identificado',
            'issuer': {'tax_id': self.a['tax_id'], 'name': self.a['name']}, 'recipient': {}}
        doc = self.create(p)
        self.assertFalse(doc.get('participant_id'))
        self.assertEqual([], self.core.masters(self.a['id'], 'participant'))
        self.assertEqual(1, len(self.core.masters(self.a['id'], 'product')))

    def test_conflicting_document_does_not_create_orphan_masters(self):
        p = self.payload() | {'key': 'synthetic-key'}
        self.create(p)
        changed = self.payload('CONFLICT', '11222333000181') | {'key': 'synthetic-key'}
        result = self.client.post(self.scope('/documents'), json=changed)
        self.assertEqual(409, result.status_code)
        self.assertEqual(1, len(self.core.masters(self.a['id'], 'participant')))
        self.assertEqual(1, len(self.core.masters(self.a['id'], 'product')))

    def test_denied_master_effects_preserve_document_without_writes(self):
        master = self.core.save_master(self.a['id'], 'participant', {
            'code': 'EXISTING', 'name': 'Revisado', 'tax_id': '87654321000198',
            'data': {'roles': ['customer']}}, 'teste')
        permissions = [{'company_id': self.a['id'], 'routine': 'fiscal.documents',
                        'action': action, 'effect': 'allow'} for action in ('read', 'create')]
        permissions += [{'company_id': self.a['id'], 'routine': 'fiscal.masters',
                         'action': action, 'effect': 'deny'} for action in ('create', 'edit')]
        result = self.client.post('/api/users', json={
            'username': 'documents-only', 'password': 'Senha-sintetica-2026', 'role': 'custom',
            'company_ids': [self.a['id']], 'permissions': permissions})
        self.assertEqual(201, result.status_code, result.text)
        with TestClient(self.app) as client:
            login = client.post('/api/login', json={'username': 'documents-only', 'password': 'Senha-sintetica-2026'}).json()
            client.headers['X-CSRF-Token'] = login['csrf_token']
            result = client.post('/api/context', json={'company_id': self.a['id'], 'module': 'fiscal', 'period': '2026-11'})
            self.assertEqual(200, result.status_code, result.text)
            result = client.post(self.scope('/documents'), json=self.payload())
            self.assertEqual(201, result.status_code, result.text)
            doc = result.json()
            self.assertEqual(master['id'], doc['participant_id'])
            self.assertNotIn('master_id', doc['items'][0])
            self.assertEqual(2, len(doc['master_import_warnings']))
            result = client.post(self.scope('/documents'), json=self.payload('XML2', '11222333000181'))
            self.assertEqual(201, result.status_code, result.text)
            self.assertFalse(result.json().get('participant_id'))
            self.assertTrue(result.json()['master_import_warnings'])
        self.assertEqual([master], self.core.masters(self.a['id'], 'participant'))
        self.assertEqual([], self.core.masters(self.a['id'], 'product'))
        self.assertEqual(2, len(self.core.documents(self.a['id'])))
