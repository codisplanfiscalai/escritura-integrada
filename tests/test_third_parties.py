"""Synthetic identities only: shared identity never shares company permissions/data."""
import json
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi.testclient import TestClient
import test_core as base
from app.core import DomainError, cnpj_digits
from app.db import Database
from app.maintenance import sqlite_backup
from app.migration_third_parties import migrate_third_parties


class ThirdPartyTests(unittest.TestCase):
    setUp = base.CoreApiTests.setUp
    tearDown = base.CoreApiTests.tearDown
    create_company = base.CoreApiTests.create_company
    activate = base.CoreApiTests.activate
    scope = base.CoreApiTests.scope
    document = base.CoreApiTests.document

    def party(self, cid=None, code='PARTY', tax_id='11222333000181', **data):
        return self.core.save_master(cid or self.a['id'], 'participant', {
            'code': code, 'name': 'Terceiro sintético ' + code, 'tax_id': tax_id,
            'data': {'roles': ['supplier'], **data}}, 'synthetic')

    def post(self, path, payload, status=200, client=None, cid=None):
        r = (client or self.client).post(self.scope(path, cid), json=payload)
        self.assertEqual(status, r.status_code, r.text)
        return r.json()

    def limited(self, name, company_ids, permissions):
        r = self.client.post('/api/users', json={'username': name, 'password': 'Senha-sintetica-2026',
            'role': 'custom', 'company_ids': company_ids, 'permissions': [
                {'company_id': cid, 'routine': routine, 'action': action, 'effect': 'allow'}
                for cid, routine, action in permissions]})
        self.assertEqual(201, r.status_code, r.text)
        client = TestClient(self.app)
        self.addCleanup(client.close)
        login = client.post('/api/login', json={'username': name, 'password': 'Senha-sintetica-2026'})
        self.assertEqual(200, login.status_code, login.text)
        client.headers['X-CSRF-Token'] = login.json()['csrf_token']
        self.activate(self.a['id'], client=client)
        return client, r.json()

    def test_reused_identity_keeps_local_roles_contacts_ids_and_lists(self):
        a = self.party(email='private-a@example.invalid', roles=['supplier', 'carrier'])
        b = self.party(self.b['id'], email='private-b@example.invalid', roles=['customer'])
        with self.app.state.db.read() as conn:
            self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM third_parties').fetchone()[0])
            self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM third_party_establishments').fetchone()[0])
            self.assertEqual(2, conn.execute('SELECT COUNT(*) FROM third_party_company_links').fetchone()[0])
        self.assertNotEqual(a['id'], b['id'])
        response = self.client.get(self.scope('/third-parties')).json()
        self.assertEqual([a['id']], [r['id'] for r in response])
        self.assertNotIn('private-b', json.dumps(response))
        self.assertEqual(['supplier', 'carrier'], response[0]['data']['roles'])
        self.assertEqual(404, self.client.get(self.scope(f"/third-parties/{b['id']}")).status_code)
        self.assertEqual(404, self.client.get(self.scope(f"/third-parties/{b['id']}/history")).status_code)
        self.assertEqual(a['id'], self.core.masters(self.a['id'], 'participant')[0]['id'])

    def test_alphanumeric_branches_share_entity_not_establishments_or_access(self):
        root = 'SYNTH001'
        a_cnpj = root + '0001' + cnpj_digits(root + '0001')
        b_cnpj = root + '0002' + cnpj_digits(root + '0002')
        a = self.party(tax_id=a_cnpj)
        b = self.party(self.b['id'], tax_id=b_cnpj)
        cpf = self.party(code='CPF', tax_id='52998224725')
        with self.app.state.db.read() as conn:
            self.assertEqual(2, conn.execute('SELECT COUNT(*) FROM third_parties').fetchone()[0])
            self.assertEqual(2, conn.execute('SELECT COUNT(*) FROM third_party_establishments').fetchone()[0])
        self.assertEqual(root, self.core.third_party(self.a['id'], a['id'])['identity']['identity_key'])
        self.assertEqual('person', self.core.third_party(self.a['id'], cpf['id'])['identity']['entity_type'])
        client, _ = self.limited('only-a', [self.a['id']], [(self.a['id'], 'fiscal.masters', 'read')])
        self.assertEqual(403, client.get(self.scope('/third-parties', self.b['id'])).status_code)
        self.post(f"/third-parties/{a['id']}/reuse-preview", {'source_company_id': self.b['id'], 'source_master_id': b['id'], 'fields': ['name']}, 403, client)
        self.post(f"/third-parties/{a['id']}/reuse-preview", {'source_company_id': self.b['id'], 'source_master_id': b['id'], 'fields': ['name']}, 400)

    def test_registration_history_retains_multiple_ufs_and_absent_status(self):
        a = self.party(profile={'state_registrations': [{'state': 'SP', 'number': '123456789', 'active': None}]})
        old_reg = a['data']['profile']['state_registrations'][0]
        self.assertEqual('', old_reg['status'])
        self.assertIsNone(old_reg['active'])
        payload = {'version': a['version'], 'reason': 'Conferência sintética de inscrições', 'state_registrations': [
            {'state': 'SP', 'number': '123456789', 'status': 'suspended', 'active': False},
            {'state': 'MG', 'number': '987654321', 'status': 'registered', 'active': True},
            {'state': 'MG', 'number': '987654322', 'active': None}]}
        r = self.client.put(self.scope(f"/third-parties/{a['id']}/registrations"), json=payload)
        self.assertEqual(200, r.status_code, r.text)
        updated = r.json()
        self.assertEqual(3, len(updated['data']['profile']['state_registrations']))
        self.assertEqual(409, self.client.put(self.scope(f"/third-parties/{a['id']}/registrations"), json=payload).status_code)
        history = self.core.third_party_history(self.a['id'], a['id'])
        self.assertEqual(2, len(history))
        self.assertEqual([old_reg], history[-1]['details']['before']['data']['profile']['state_registrations'])
        self.assertEqual('suspended', history[-1]['details']['after']['data']['profile']['state_registrations'][0]['status'])
        # An explicit exception is permitted; missing number+status is not invented.
        self.assertEqual(400, self.client.put(self.scope(f"/third-parties/{a['id']}/registrations"), json=payload | {
            'version': updated['version'], 'state_registrations': [{'state': 'RJ'}]}).status_code)
        self.assertEqual(200, self.client.put(self.scope(f"/third-parties/{a['id']}/registrations"), json=payload | {
            'version': updated['version'], 'state_registrations': [{'state': 'RJ', 'status': 'exempt'}]}).status_code)

    def test_explicit_reuse_keeps_private_fields_and_never_silently_propagates(self):
        a = self.party(address='Endereço revisado A', email='private-a@example.invalid', roles=['carrier'])
        b = self.party(self.b['id'], address='Novo endereço cadastral B', email='private-b@example.invalid', roles=['customer'])
        self.assertEqual('Endereço revisado A', self.core.third_party(self.a['id'], a['id'])['data']['address'])
        payload = {'source_company_id': self.b['id'], 'source_master_id': b['id'], 'fields': ['address']}
        preview = self.post(f"/third-parties/{a['id']}/reuse-preview", payload)
        self.assertEqual({'address': 'Novo endereço cadastral B'}, preview['values'])
        result = self.post(f"/third-parties/{a['id']}/reuse-confirm", preview | {'reason': 'Atualização cadastral revisada'})
        self.assertEqual(a['id'], result['id'])
        self.assertEqual('Novo endereço cadastral B', result['data']['address'])
        self.assertEqual('private-a@example.invalid', result['data']['email'])
        self.assertEqual(['carrier'], result['data']['roles'])
        self.assertEqual(b, self.core.masters(self.b['id'], 'participant')[0])
        self.post(f"/third-parties/{a['id']}/reuse-preview", payload | {'fields': ['email']}, 400)
        self.post(f"/third-parties/{a['id']}/reuse-preview", payload | {'fields': ['roles']}, 400)
        self.post(f"/third-parties/{a['id']}/reuse-confirm", preview | {'reason': 'Repetição'}, 409)
        local_history = self.core.third_party_history(self.a['id'], a['id'])
        self.assertNotIn('source_company_id', json.dumps(local_history))
        self.assertNotIn('private-b', json.dumps(local_history))

    def test_reuse_requires_source_read_target_edit_and_rechecks_revocations(self):
        a = self.party()
        b = self.party(self.b['id'])
        preview_payload = {'source_company_id': self.b['id'], 'source_master_id': b['id'], 'fields': ['name']}
        read = [(cid, 'fiscal.masters', 'read') for cid in [self.a['id'], self.b['id']]]
        reader, _ = self.limited('reader', [self.a['id'], self.b['id']], read)
        preview = self.post(f"/third-parties/{a['id']}/reuse-preview", preview_payload, client=reader)
        self.post(f"/third-parties/{a['id']}/reuse-confirm", preview | {'reason': 'Teste'}, 403, reader)
        editor, user = self.limited('editor', [self.a['id'], self.b['id']], read + [(self.a['id'], 'fiscal.masters', 'edit')])
        preview = self.post(f"/third-parties/{a['id']}/reuse-preview", preview_payload, client=editor)
        with self.app.state.db.transaction() as conn:
            conn.execute("UPDATE user_permissions SET effect='deny' WHERE user_id=? AND company_id=?", (user['id'], self.b['id']))
        self.post(f"/third-parties/{a['id']}/reuse-confirm", preview | {'reason': 'Teste'}, 403, editor)
        self.assertEqual(a, self.core.masters(self.a['id'], 'participant')[0])

    def test_source_changes_and_selected_fields_invalidate_preview(self):
        a = self.party()
        b = self.party(self.b['id'])
        payload = {'source_company_id': self.b['id'], 'source_master_id': b['id'], 'fields': ['name']}
        preview = self.post(f"/third-parties/{a['id']}/reuse-preview", payload)
        self.core.save_master(self.b['id'], 'participant', b | {'name': 'Revisão mais recente'}, 'synthetic', b['id'])
        self.post(f"/third-parties/{a['id']}/reuse-confirm", preview | {'reason': 'Teste'}, 409)
        preview = self.post(f"/third-parties/{a['id']}/reuse-preview", payload)
        self.post(f"/third-parties/{a['id']}/reuse-confirm", preview | {'reason': 'Teste', 'fields': ['address']}, 409)
        self.assertEqual(a, self.core.masters(self.a['id'], 'participant')[0])

    def test_identity_correction_preserves_document_and_title_ids(self):
        a = self.party()
        corrected = self.party(code='CORRECT', tax_id='87654321000198')
        doc = self.post('/documents', self.document() | {'participant_id': a['id'], 'partner_tax_id': a['tax_id']}, 201)
        title = self.post('/titles', {'kind': 'payable', 'description': 'Título sintético', 'partner_name': a['name'],
            'participant_id': a['id'], 'document_id': doc['id'], 'document': 'OLD', 'issue_date': '2026-11-06',
            'due_date': '2026-12-10', 'amount': '100.00'}, 201)
        replacement = self.post(f"/third-parties/{a['id']}/identity-correction", {'replacement_master_id': corrected['id'], 'version': a['version'], 'reason': 'Identidade original incorreta'})
        self.assertFalse(replacement['active'])
        self.assertEqual(corrected['id'], replacement['replacement_master_id'])
        current_doc = self.core.documents(self.a['id'])[0]
        current_title = self.core.titles(self.a['id'])[0]
        self.assertEqual(doc['id'], current_doc['id'])
        self.assertEqual(a['id'], current_doc['participant_id'])
        self.assertEqual(a['tax_id'], current_doc['partner_tax_id'])
        self.assertEqual(title['id'], current_title['id'])
        self.assertEqual(a['id'], current_title['participant_id'])
        self.assertEqual('replace', self.core.third_party_history(self.a['id'], a['id'])[-1]['event'])
        with self.assertRaises(DomainError):
            self.core.save_master(self.a['id'], 'participant', replacement | {'active': True}, 'synthetic', a['id'])
        foreign = self.party(self.b['id'], tax_id='52998224725')
        self.post(f"/third-parties/{corrected['id']}/identity-correction", {'replacement_master_id': foreign['id'], 'version': corrected['version'], 'reason': 'Teste'}, 404)

    def test_migration_preserves_local_rows_and_is_idempotent_and_backup_roundtrip(self):
        a = self.party()
        b = self.party(self.b['id'])
        db = self.app.state.db
        with db.transaction() as conn:
            for table in ['third_party_replacements', 'third_party_history', 'third_party_company_links', 'third_party_establishments', 'third_parties']:
                conn.execute('DELETE FROM ' + table)
        with db.read() as conn:
            before = [dict(r) for r in conn.execute('SELECT * FROM masters ORDER BY id')]
            migrate_third_parties(conn)
            counts = [conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] for table in ['third_parties', 'third_party_company_links', 'third_party_history']]
            migrate_third_parties(conn)
            self.assertEqual(counts, [conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] for table in ['third_parties', 'third_party_company_links', 'third_party_history']])
            self.assertEqual(before, [dict(r) for r in conn.execute('SELECT * FROM masters ORDER BY id')])
            self.assertEqual([], conn.execute('PRAGMA foreign_key_check').fetchall())
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'restored' / 'escritura.sqlite3'
            sqlite_backup(db.path, target)
            restored = Database(target.parent)
            with restored.read() as conn:
                self.assertEqual(before, [dict(r) for r in conn.execute('SELECT * FROM masters ORDER BY id')])
                self.assertEqual(counts, [conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] for table in ['third_parties', 'third_party_company_links', 'third_party_history']])
                self.assertEqual('ok', conn.execute('PRAGMA integrity_check').fetchone()[0])
                self.assertEqual([], conn.execute('PRAGMA foreign_key_check').fetchall())

    def test_products_services_stay_local_with_document_item_trace(self):
        product = self.core.save_master(self.a['id'], 'product', {'code': 'SAME', 'name': 'Produto sintético', 'data': {}}, 'synthetic')
        service = self.core.save_master(self.a['id'], 'service', {'code': 'SAME', 'name': 'Serviço sintético', 'data': {}}, 'synthetic')
        foreign = self.core.save_master(self.b['id'], 'product', {'code': 'SAME', 'name': 'Produto B', 'data': {}}, 'synthetic')
        doc = self.post('/documents', self.document() | {'items': [{'master_id': product['id'], 'quantity': '3.000', 'description': 'Descrição da origem preservada'}, {'master_id': service['id'], 'quantity': '1.000'}]}, 201)
        with self.app.state.db.read() as conn:
            self.assertEqual(0, conn.execute('SELECT COUNT(*) FROM third_party_company_links').fetchone()[0])
        trace = self.client.get(self.scope(f"/master-movements/{product['id']}"))
        self.assertEqual(200, trace.status_code, trace.text)
        movements = trace.json()['movements']
        self.assertEqual(1, len(movements))
        self.assertEqual(doc['id'], movements[0]['id'])
        self.assertEqual(1, movements[0]['item_position'])
        self.assertEqual('3.000', movements[0]['item']['quantity'])
        self.assertEqual(404, self.client.get(self.scope(f"/master-movements/{foreign['id']}" )).status_code)
        client, _ = self.limited('master-reader', [self.a['id']], [(self.a['id'], 'fiscal.masters', 'read')])
        self.assertEqual(403, client.get(self.scope(f"/master-movements/{product['id']}" )).status_code)

    def test_missing_identity_remains_local_with_audited_history(self):
        a = self.party(tax_id='')
        self.assertIsNone(self.core.third_party(self.a['id'], a['id'])['identity'])
        with self.app.state.db.read() as conn:
            self.assertEqual(0, conn.execute('SELECT COUNT(*) FROM third_parties').fetchone()[0])
        self.assertEqual('local', self.core.third_party_history(self.a['id'], a['id'])[0]['event'])

    def test_concurrent_creation_reuses_identity_without_master_duplicate(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda cid: self.party(cid), [self.a['id'], self.b['id']]))
        self.assertEqual(2, len({r['id'] for r in results}))
        with self.app.state.db.read() as conn:
            self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM third_parties').fetchone()[0])
            self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM third_party_establishments').fetchone()[0])
            self.assertEqual(2, conn.execute('SELECT COUNT(*) FROM third_party_company_links').fetchone()[0])

    def test_import_roles_preserve_local_registrations_and_denied_writes_do_not_link(self):
        master = self.party(tax_id='87654321000198', roles=['customer'], profile={
            'state_registrations': [{'state': 'SP', 'number': 'REVIEWED', 'status': 'registered'}]})
        payload = self.document('IMPORTED') | {'partner_tax_id': master['tax_id'], 'partner_name': 'Origem XML',
            'issuer': {'tax_id': master['tax_id'], 'name': 'Origem XML', 'ie': 'NEW-UNREVIEWED'},
            'recipient': {'tax_id': self.a['tax_id']}, 'document_type': 'goods'}
        doc = self.post('/documents', payload, 201)
        self.assertEqual(master['id'], doc['participant_id'])
        updated = self.core.masters(self.a['id'], 'participant')[0]
        self.assertEqual(master['data']['profile'], updated['data']['profile'])
        self.assertEqual({'supplier', 'customer'}, set(updated['data']['roles']))
        self.assertEqual(2, len(self.core.third_party_history(self.a['id'], master['id'])))
        # Same note and a later note for the unchanged party create no false event.
        self.assertTrue(self.post('/documents', payload, 201)['duplicate'])
        self.post('/documents', payload | {'number': 'SECOND-NOTE'}, 201)
        self.assertEqual(2, len(self.core.third_party_history(self.a['id'], master['id'])))
        client, _ = self.limited('documents-only', [self.a['id']], [
            (self.a['id'], 'fiscal.documents', 'read'), (self.a['id'], 'fiscal.documents', 'create')])
        payload['number'] = 'DENIED-MASTER'
        payload['partner_tax_id'] = '11222333000181'
        payload['issuer']['tax_id'] = '11222333000181'
        doc = self.post('/documents', payload, 201, client)
        self.assertFalse(doc.get('participant_id'))
        with self.app.state.db.read() as conn:
            self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM third_parties').fetchone()[0])
            self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM third_party_company_links').fetchone()[0])

    def test_failed_sync_rolls_back_master_write(self):
        with patch('app.third_parties.sync_third_party', side_effect=DomainError('Falha sintética')):
            with self.assertRaises(DomainError):
                self.party()
        self.assertEqual([], self.core.masters(self.a['id'], 'participant'))
        self.assertEqual([], self.core.third_parties(self.a['id']))
