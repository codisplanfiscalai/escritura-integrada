"""A substituted identity keeps historical workflows, never authorizes new links."""
import unittest
import test_third_parties as fixtures
import test_import_payables as import_fixtures


class ThirdPartyHistoryTests(unittest.TestCase):
    setUp = fixtures.ThirdPartyTests.setUp
    tearDown = fixtures.ThirdPartyTests.tearDown
    create_company = fixtures.ThirdPartyTests.create_company
    activate = fixtures.ThirdPartyTests.activate
    scope = fixtures.ThirdPartyTests.scope
    document = fixtures.ThirdPartyTests.document
    party = fixtures.ThirdPartyTests.party
    post = fixtures.ThirdPartyTests.post
    limited = fixtures.ThirdPartyTests.limited

    def historical_doc(self, party, number='OLD'):
        return self.post('/documents', self.document(number) | {
            'participant_id': party['id'], 'partner_tax_id': party['tax_id'],
            'partner_name': 'Nome preservado no documento'}, 201)

    def title_payload(self, party, doc=None):
        return {'kind': 'payable', 'description': 'Obrigação sintética', 'partner_name': party['name'],
            'participant_id': party['id'], 'document_id': doc['id'] if doc else None, 'document': 'OLD',
            'issue_date': '2026-11-06', 'due_date': '2026-12-10', 'amount': '100.00'}

    def replace(self, party):
        successor = self.party(code='CORRECT', tax_id='87654321000198')
        return self.post(f"/third-parties/{party['id']}/identity-correction", {
            'replacement_master_id': successor['id'], 'version': party['version'], 'reason': 'Correção sintética'})

    def review(self, doc):
        return self.post(f"/documents/{doc['id']}/review", {'version': doc['version'], 'reason': 'Conferência sintética'})

    def booking(self, doc, titles=False, **extra):
        return {'version': doc['version'], 'reason': 'Escrituração histórica', 'generate_titles': titles,
            **({'installments': [{'due_date': '2026-12-10', 'amount': '100.00'}]} if titles else {}), **extra}

    def agreement(self, title, key='agreement'):
        return {'date': '2026-11-10', 'title_ids': [title['id']], 'versions': {str(title['id']): title['version']},
            'reason': 'Renegociação da obrigação original', 'idempotency_key': key,
            'installments': [{'due_date': '2026-12-30', 'amount': '100.00'}]}

    def test_historical_edit_and_book_keep_local_id_and_tax_identity(self):
        party = self.party()
        doc = self.historical_doc(party)
        replaced = self.replace(party)
        response = self.client.put(self.scope(f"/documents/{doc['id']}"), json={
            'version': doc['version'], 'reason': 'Revisão de classificação', 'cfop': '1102'})
        self.assertEqual(200, response.status_code, response.text)
        updated = response.json()
        self.assertEqual(party['id'], updated['participant_id'])
        self.assertEqual(party['tax_id'], updated['partner_tax_id'])
        reviewed = self.review(updated)
        booked = self.post(f"/documents/{doc['id']}/book", self.booking(reviewed))
        self.assertEqual('booked', booked['document']['status'])
        self.assertEqual(party['id'], booked['document']['participant_id'])
        self.assertEqual([], booked['titles'])
        self.assertFalse(self.core.third_party(self.a['id'], party['id'])['active'])
        self.assertEqual(replaced['version'], self.core.third_party(self.a['id'], party['id'])['version'])

    def test_book_generate_reverse_and_rebook_preserve_historical_partner(self):
        party = self.party()
        doc = self.review(self.historical_doc(party))
        replaced = self.replace(party)
        # A later edit of the inactive registration must not rename old movements.
        self.core.save_master(self.a['id'], 'participant', replaced | {'name': 'Nome cadastral posterior'}, 'teste', party['id'])
        booked = self.post(f"/documents/{doc['id']}/book", self.booking(doc, True, idempotency_key='old-book'))
        self.assertEqual(party['id'], booked['titles'][0]['participant_id'])
        self.assertEqual(doc['partner_name'], booked['titles'][0]['partner_name'])
        self.assertEqual(doc['id'], booked['titles'][0]['document_id'])
        self.assertTrue(self.post(f"/documents/{doc['id']}/book", self.booking(doc, True, idempotency_key='old-book'))['duplicate'])
        reversed_doc = self.post(f"/documents/{doc['id']}/reverse", {'version': booked['document']['version'],
            'reason': 'Reversão sintética', 'date': '2026-11-07', 'idempotency_key': 'old-reverse'})['document']
        rebook = self.post(f"/documents/{doc['id']}/book", self.booking(self.review(reversed_doc), True))
        self.assertEqual(party['id'], rebook['titles'][0]['participant_id'])
        self.assertNotEqual(booked['titles'][0]['id'], rebook['titles'][0]['id'])
        old = next(t for t in self.core.titles(self.a['id']) if t['id'] == booked['titles'][0]['id'])
        self.assertTrue(old['cancelled'])
        self.assertEqual(party['id'], old['participant_id'])

    def test_renegotiation_and_reversal_continue_original_obligation(self):
        party = self.party()
        title = self.post('/titles', self.title_payload(party), 201)
        replaced = self.replace(party)
        self.core.save_master(self.a['id'], 'participant', replaced | {'name': 'Nome cadastral posterior'}, 'teste', party['id'])
        request = self.agreement(title)
        result = self.post('/titles/renegotiate', request)
        new_title = result['titles'][0]
        self.assertEqual(party['id'], new_title['participant_id'])
        self.assertEqual(title['partner_name'], new_title['partner_name'])
        self.assertTrue(self.post('/titles/renegotiate', request)['duplicate'])
        self.post(f"/renegotiations/{result['id']}/reverse", {'date': '2026-11-11', 'reason': 'Correção do acordo', 'idempotency_key': 'undo-agreement'})
        original = next(t for t in self.core.titles(self.a['id']) if t['id'] == title['id'])
        self.assertFalse(original['cancelled'])
        self.assertEqual(party['id'], original['participant_id'])
        self.assertFalse(self.core.third_party(self.a['id'], party['id'])['active'])
        self.post('/titles/renegotiate', self.agreement(original, 'next-agreement'))

    def test_forged_payload_flags_and_existing_ids_cannot_create_new_links(self):
        party = self.party()
        doc = self.historical_doc(party)
        title = self.post('/titles', self.title_payload(party, doc), 201)
        other_doc = self.post('/documents', self.document('UNLINKED'), 201)
        self.replace(party)
        forged = {'id': doc['id'], '_existing_document_id': doc['id'], '_historical_document_id': doc['id'],
            '_historical_title_ids': [title['id']], 'allow_inactive': True, 'historical': True}
        self.post('/documents', self.document('NEW') | {'participant_id': party['id'], 'partner_tax_id': party['tax_id'], **forged}, 400)
        self.post('/titles', self.title_payload(party, doc) | forged, 400)
        inherited = self.title_payload(party, doc) | forged
        inherited.pop('participant_id')
        self.post('/titles', inherited, 400)  # Public document_id alone is not trusted lineage.
        response = self.client.put(self.scope(f"/documents/{other_doc['id']}"), json={
            'version': other_doc['version'], 'reason': 'Tentativa de vínculo novo', 'participant_id': party['id'],
            'partner_tax_id': party['tax_id'], **forged})
        self.assertEqual(400, response.status_code, response.text)
        self.assertEqual(2, len(self.core.documents(self.a['id'])))
        self.assertEqual(1, len(self.core.titles(self.a['id'])))
        response = self.client.put(self.scope(f"/documents/{doc['id']}"), json={
            'version': doc['version'], 'reason': 'CPF/CNPJ diferente', 'partner_tax_id': '87654321000198'})
        self.assertEqual(400, response.status_code, response.text)

    def test_removed_historical_link_cannot_be_reattached(self):
        party = self.party()
        doc = self.historical_doc(party)
        self.replace(party)
        response = self.client.put(self.scope(f"/documents/{doc['id']}"), json={
            'version': doc['version'], 'reason': 'Remoção explícita', 'participant_id': None})
        self.assertEqual(200, response.status_code, response.text)
        response = self.client.put(self.scope(f"/documents/{doc['id']}"), json={
            'version': response.json()['version'], 'reason': 'Novo vínculo não permitido', 'participant_id': party['id']})
        self.assertEqual(400, response.status_code, response.text)

    def test_establishment_history_preserves_exact_local_branch(self):
        branch_base = self.a['tax_id'][:8] + '0002'
        branch_cnpj = branch_base + fixtures.cnpj_digits(branch_base)
        old = self.core.save_master(self.a['id'], 'establishment', {'code': 'OLD-BRANCH', 'name': 'Filial antiga',
            'tax_id': self.a['tax_id'], 'data': {}}, 'teste')
        successor = self.core.save_master(self.a['id'], 'establishment', {'code': 'NEW-BRANCH', 'name': 'Filial correta',
            'tax_id': branch_cnpj, 'data': {}}, 'teste')
        doc = self.post('/documents', self.document('BRANCH') | {'establishment_id': old['id']}, 201)
        self.post(f"/third-parties/{old['id']}/identity-correction", {'version': old['version'],
            'replacement_master_id': successor['id'], 'reason': 'Correção da filial'})
        booked = self.post(f"/documents/{doc['id']}/book", self.booking(self.review(doc)))
        self.assertEqual(old['id'], booked['document']['establishment_id'])
        self.post('/documents', self.document('NEW-BRANCH-LINK') | {'establishment_id': old['id']}, 400)

    def test_ordinary_inactive_master_is_not_a_historical_exception(self):
        party = self.party()
        doc = self.review(self.historical_doc(party))
        title = self.post('/titles', self.title_payload(party), 201)
        self.core.save_master(self.a['id'], 'participant', party | {'active': False}, 'teste', party['id'])
        self.post(f"/documents/{doc['id']}/book", self.booking(doc), 400)
        response = self.client.put(self.scope(f"/documents/{doc['id']}"), json={
            'version': doc['version'], 'reason': 'Revisão', 'cfop': '1102'})
        self.assertEqual(400, response.status_code, response.text)
        self.post('/titles/renegotiate', self.agreement(title), 400)

    def test_permissions_and_periods_still_block_and_roll_back(self):
        party = self.party()
        doc = self.review(self.historical_doc(party))
        title = self.post('/titles', self.title_payload(party), 201)
        self.replace(party)
        reader, _ = self.limited('historical-reader', [self.a['id']], [(self.a['id'], 'fiscal.documents', 'read')])
        self.post(f"/documents/{doc['id']}/book", self.booking(doc), 403, reader)
        booker, _ = self.limited('historical-booker', [self.a['id']], [
            (self.a['id'], 'fiscal.documents', 'read'), (self.a['id'], 'fiscal.documents', 'book')])
        self.post(f"/documents/{doc['id']}/book", self.booking(doc, True), 403, booker)
        self.assertEqual('reviewed', self.core.documents(self.a['id'])[0]['status'])
        self.assertEqual(1, len(self.core.titles(self.a['id'])))
        renegotiator, _ = self.limited('historical-renegotiator', [self.a['id']], [
            (self.a['id'], 'fiscal.documents', 'read'), (self.a['id'], 'financial.titles', 'read'),
            (self.a['id'], 'financial.titles', 'edit')])
        self.post('/titles/renegotiate', self.agreement(title), 403, renegotiator)
        self.assertFalse(self.core.titles(self.a['id'])[0]['cancelled'])
        with self.core.db.read() as conn:
            self.assertEqual(0, conn.execute('SELECT COUNT(*) FROM renegotiations').fetchone()[0])
        # A persisted closed-period fixture proves the historical exception does
        # not bypass period guards even when the original is still reviewed.
        with self.core.db.transaction() as conn:
            conn.execute("INSERT INTO period_locks VALUES(?,?,'fiscal',1,'Teste','teste','2026-11-10',1)", (self.a['id'], '2026-11'))
        blocked = self.post(f"/documents/{doc['id']}/book", self.booking(doc), 409)
        self.assertEqual('period_closed', blocked['code'])
        with self.core.db.transaction() as conn:
            conn.execute("DELETE FROM period_locks WHERE company_id=? AND module='fiscal'", (self.a['id'],))
        self.core.set_period(self.a['id'], {'module': 'financial', 'period': '2026-10', 'reason': 'Fechamento sintético'}, 'teste', True)
        self.post(f"/documents/{doc['id']}/book", self.booking(doc, True), 409)
        self.assertEqual('reviewed', self.core.documents(self.a['id'])[0]['status'])
        self.core.set_period(self.a['id'], {'module': 'financial', 'period': '2026-11', 'reason': 'Fechamento sintético'}, 'teste', True)
        self.post('/titles/renegotiate', self.agreement(title), 409)
        self.assertFalse(self.core.titles(self.a['id'])[0]['cancelled'])
        self.post(f"/documents/{doc['id']}/book", self.booking(doc))
        self.core.set_period(self.a['id'], {'module': 'fiscal', 'period': '2026-11', 'reason': 'Fechamento sintético'}, 'teste', True)
        response = self.client.put(self.scope(f"/documents/{doc['id']}"), json={
            'version': self.core.documents(self.a['id'])[0]['version'], 'reason': 'Revisão bloqueada', 'cfop': '1102'})
        self.assertEqual(409, response.status_code, response.text)

    def test_bulk_existing_links_work_but_cannot_change_participant(self):
        party = self.party()
        doc = self.historical_doc(party)
        self.replace(party)
        self.post('/catalogs', {'kind': 'cfop', 'code': '1556', 'description': 'Consumo sintético', 'source': 'Teste'}, 201)
        def bulk(action, changes=None, status=200):
            return self.post('/bulk-operations/preview', {'kind': 'documents', 'action': action,
                'period': '2026-11', 'ids': [doc['id']], **({'changes': changes} if changes else {})}, status)
        def confirm(preview):
            self.assertTrue(preview['can_confirm'], preview)
            return self.post('/bulk-operations/confirm', {'preview_id': preview['id'], 'preview_hash': preview['preview_hash'],
                'reason': 'Revisão sintética em lote', 'confirmation_phrase': preview['confirmation_phrase'], 'irreversible_acknowledged': True})
        confirm(bulk('update', {'cfop': '1556'}))
        self.assertEqual(party['id'], self.core.documents(self.a['id'])[0]['participant_id'])
        bulk('update', {'participant_id': party['id'], 'cfop': '1556'}, 400)
        confirm(bulk('review'))
        confirm(bulk('book'))
        self.assertEqual('booked', self.core.documents(self.a['id'])[0]['status'])
        self.assertEqual(party['id'], self.core.documents(self.a['id'])[0]['participant_id'])

    def test_new_xml_keeps_source_without_inactive_link_and_reimport_preserves_history(self):
        party = self.party()
        raw = self.document('ORIGINAL') | {'partner_tax_id': party['tax_id'], 'partner_name': party['name'],
            'issuer': {'tax_id': party['tax_id'], 'name': party['name']}, 'recipient': {'tax_id': self.a['tax_id']}}
        original = self.post('/documents', raw, 201)
        self.assertEqual(party['id'], original['participant_id'])
        self.replace(party)
        before = self.core.third_party_history(self.a['id'], party['id'])
        repeated = self.post('/documents', raw, 201)
        self.assertTrue(repeated['duplicate'])
        self.assertEqual(original['id'], repeated['id'])
        self.assertEqual(party['id'], repeated['participant_id'])
        new_doc = self.post('/documents', raw | {'number': 'NEW-XML', 'source_hash': 'new-synthetic-source'}, 201)
        self.assertFalse(new_doc.get('participant_id'))
        self.assertTrue(any('inativo' in w for w in new_doc['master_import_warnings']))
        self.assertEqual(party['tax_id'], new_doc['partner_tax_id'])
        self.assertEqual(before, self.core.third_party_history(self.a['id'], party['id']))
        self.assertEqual(2, len(self.core.masters(self.a['id'], 'participant')))
        self.post('/documents', raw | {'number': 'FORGED-IMPORT', 'participant_id': party['id'], '_existing_document_id': original['id']}, 400)


class ReplacedImportPayablesTests(unittest.TestCase):
    setUp = import_fixtures.ImportPayablesTests.setUp
    tearDown = import_fixtures.ImportPayablesTests.tearDown
    create_company = import_fixtures.ImportPayablesTests.create_company
    activate = import_fixtures.ImportPayablesTests.activate
    scope = import_fixtures.ImportPayablesTests.scope
    document = import_fixtures.ImportPayablesTests.document
    post = import_fixtures.ImportPayablesTests.post
    xml = import_fixtures.ImportPayablesTests.xml
    preview = import_fixtures.ImportPayablesTests.preview
    mapping = import_fixtures.ImportPayablesTests.mapping
    prepared = import_fixtures.ImportPayablesTests.prepared
    confirm = import_fixtures.ImportPayablesTests.confirm

    def test_reprocess_original_xml_creates_payable_with_preserved_party(self):
        self.mapping()
        batch = self.preview()
        result = self.confirm(batch, self.prepared(batch))
        doc = self.core.documents(self.a['id'])[0]
        party = self.core.third_party(self.a['id'], doc['participant_id'])
        successor = self.core.save_master(self.a['id'], 'participant', {'code': 'FIXED', 'name': 'Cadastro corrigido',
            'tax_id': '52998224725', 'data': {'roles': ['supplier']}}, 'teste')
        self.post(f"/third-parties/{party['id']}/identity-correction", {'version': party['version'],
            'replacement_master_id': successor['id'], 'reason': 'Correção sintética'})
        options = {'create_payables': True}
        plan = self.post(f"/imports/{batch['id']}/reprocess-preview", options)
        self.assertTrue(plan['can_confirm'], plan)
        confirmed = self.post(f"/imports/{batch['id']}/reprocess-confirm", {**options,
            'reason': 'Recuperação da cobrança original', 'idempotency_key': 'historic-billing', 'reprocess_hash': plan['reprocess_hash']})
        self.assertEqual(1, confirmed['titles_created'])
        title = self.core.titles(self.a['id'])[0]
        self.assertEqual(party['id'], title['participant_id'])
        self.assertEqual(result['document_ids'][0], title['document_id'])
        self.assertEqual(doc['partner_name'], title['partner_name'])
