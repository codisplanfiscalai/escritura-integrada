"""Pinned sources and explicit synthetic master declarations, with no application."""
import copy
import unittest
from fastapi.testclient import TestClient
import test_contributions_snapshot as previous
from app.core import digest, pack
from app.sped_generator.contributions_contracts import NAMESPACE, load_catalog, select_reference

REFERENCE_ID = 'contributions-2026-11-review-20261116'


def declaration(cid, scope='item', **changes):
    fields = {'CST_PIS': '50', 'CST_COFINS': '70'} if scope == 'item' else {'COD_INC_TRIB': '2'}
    value = {'id': 'synthetic-declaration', 'revision': '1', 'company_id': cid,
        'scope': scope, 'valid_from': '2026-11', 'valid_to': '2026-11',
        'reference_id': REFERENCE_ID, 'source': 'Memória declarada sintética',
        'source_sha256': 'b' * 64, 'responsible': 'Fixture', 'declared_on': '2026-11-16', 'fields': fields}
    if scope == 'item':
        value['direction'] = 'incoming'
    return value | changes


class ContributionsReferenceTests(unittest.TestCase):
    def test_known_and_unknown_reference_and_period_boundaries_never_choose_latest(self):
        catalog = load_catalog()
        selected = select_reference('2026-11', REFERENCE_ID, catalog)
        self.assertEqual('pinned_for_preparation', selected['status'])
        self.assertFalse(selected['official_applicability_validated'])
        for period in ('2026-10', '2026-12', '2027-01', '2025-11'):
            result = select_reference(period, REFERENCE_ID, catalog)
            self.assertIsNone(result['reference'])
            self.assertEqual('PERIOD_NOT_REVIEWED_FOR_REFERENCE', result['diagnostics'][0]['code'])
        for revision in (None, 'latest', 'old-unknown'):
            self.assertIsNone(select_reference('2026-11', revision, catalog)['reference'])
        self.assertEqual('INVALID_REFERENCE_PERIOD', select_reference('2026-13', REFERENCE_ID, catalog)['diagnostics'][0]['code'])
        before = copy.deepcopy(catalog)
        later = copy.deepcopy(catalog['revisions'][0]); later['id'] = 'future-explicit-revision'
        catalog['revisions'].append(later)
        self.assertEqual(selected, select_reference('2026-11', REFERENCE_ID, catalog))
        self.assertEqual(before['revisions'][0], catalog['revisions'][0])
        catalog['revisions'].append(copy.deepcopy(catalog['revisions'][0]))
        self.assertEqual('AMBIGUOUS_REFERENCE', select_reference('2026-11', REFERENCE_ID, catalog)['diagnostics'][0]['code'])

    def test_source_revision_dates_are_unknown_without_using_portal_migration_date(self):
        catalog = load_catalog()
        by_id = {source['id']: source for source in catalog['sources']}
        for tax in ('pis', 'cofins'):
            source = by_id['cst-' + tax + '-1.0.0']
            self.assertEqual(33, len(source['codes']))
            self.assertEqual(33, len(set(source['codes'])))
            self.assertIn('01', source['codes']); self.assertIn('99', source['codes'])
            self.assertIsNone(source['content_revision_date'])
            self.assertIsNone(source['official_valid_from'])
            self.assertIsNone(source['official_valid_to'])
        self.assertEqual('1eca9b37057ba71989e0813dc112df0b578e3ce74d44099f81b2c4f554202130', by_id['nt11-2026']['sha256'])
        self.assertFalse(catalog['publisher_signature_verified'])
        self.assertFalse(catalog['transition_notice']['classification_coverage_verified'])
        for change in ({'sha256': None}, {'bytes': True}, {'verified_payload': False},
                       {'url': 'https://www.gov.br.attacker.invalid/sped/table'}):
            bad = copy.deepcopy(catalog); bad['sources'][0].update(change)
            self.assertEqual('UNVERIFIED_REFERENCE_PROVENANCE', select_reference('2026-11', REFERENCE_ID, bad)['diagnostics'][0]['code'])


class ContributionsDeclarationTests(unittest.TestCase):
    setUp = previous.ContributionsSnapshotApiTests.setUp
    tearDown = previous.ContributionsSnapshotApiTests.tearDown
    scope = previous.ContributionsSnapshotApiTests.scope
    activate = previous.ContributionsSnapshotApiTests.activate
    create_company = previous.ContributionsSnapshotApiTests.create_company
    database_hash = previous.ContributionsSnapshotApiTests.database_hash
    import_xmls = previous.ContributionsSnapshotApiTests.import_xmls
    own_xml = previous.ContributionsSnapshotApiTests.own_xml
    endpoint = previous.ContributionsSnapshotApiTests.endpoint
    get = previous.ContributionsSnapshotApiTests.get

    def master(self, declarations, kind='product', code='DECL', cid=None, active=True):
        payload = {'code': code, 'name': 'Cadastro sintético', 'data': {NAMESPACE: declarations}, 'active': active}
        if kind == 'establishment':
            payload['tax_id'] = (self.a if cid is None or cid == self.a['id'] else self.b)['tax_id']
        response = self.client.post(self.scope('/masters/' + kind, cid), json=payload)
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    def review(self):
        response = self.get(); self.assertEqual(200, response.status_code, response.text)
        return response.json()['snapshot']['preparation_review']

    def test_existing_master_api_preserves_explicit_fields_and_snapshot_is_readonly(self):
        company = declaration(self.a['id'], 'company')
        item = declaration(self.a['id'], id='ITEM-SYNTHETIC')
        self.master([company], 'establishment', 'HQ')
        self.master([item])
        self.import_xmls(1)
        before = self.database_hash()
        first, second = self.get(), self.get()
        self.assertEqual(first.content, second.content)
        self.assertEqual(before, self.database_hash())
        snapshot = first.json()['snapshot']; review = snapshot['preparation_review']
        self.assertEqual(2, snapshot['schema_version'])
        self.assertEqual(2, len(review['records']))
        self.assertTrue(all(row['eligible_for_preparation_review'] for row in review['records']))
        self.assertEqual(company, review['records'][0]['declaration'])
        self.assertEqual(digest(company), review['records'][0]['declaration_sha256'])
        self.assertIn('IND_REG_CUM', review['records'][0]['missing_fields'])
        self.assertIsNone(review['resolved_company_fields'])
        self.assertIsNone(snapshot['unattested']['regime_0110'])
        self.assertFalse(review['classification_applied'])
        self.assertFalse(review['records'][1]['operation_applicability_validated'])
        self.assertEqual('50', review['records'][1]['declared_fields']['CST_PIS'])
        # Declared CST is not propagated to the stored XML item or tax evidence.
        self.assertNotIn('CST_PIS', snapshot['documents'][0]['items'][0])
        self.assertFalse(snapshot['generates_efd'])

    def test_absence_never_uses_generic_company_regime_or_product_cst(self):
        response = self.client.post(self.scope('/masters/product'), json={'code': 'GENERIC', 'name': 'Genérico sintético',
            'data': {'cst': '01', 'crt': '3', 'pis': '9.99'}})
        self.assertEqual(201, response.status_code)
        result = self.review()
        self.assertEqual('absent', result['status']); self.assertEqual([], result['records'])
        self.assertIsNone(result['resolved_company_fields'])

    def test_company_isolation_inactive_masters_and_declared_direction(self):
        self.activate(self.b['id'])
        self.master([declaration(self.b['id'])], cid=self.b['id'], code='OTHER')
        self.activate(self.a['id'])
        self.assertEqual([], self.review()['records'])
        self.master([declaration(self.a['id'], direction=None)], active=False)
        row = self.review()['records'][0]
        codes = {d['code'] for d in row['diagnostics']}
        self.assertTrue({'EXPLICIT_DIRECTION_REQUIRED', 'INACTIVE_DECLARATION_MASTER'} <= codes)
        self.assertFalse(row['eligible_for_preparation_review'])

    def test_unknown_values_missing_provenance_invalid_periods_and_scopes_remain_exportable(self):
        variants = [({'company_id': self.b['id']}, 'DECLARATION_COMPANY_MISMATCH'),
            ({'source': ''}, 'MISSING_OR_NONCANONICAL_SOURCE'),
            ({'source_sha256': 'unknown'}, 'DECLARATION_SOURCE_HASH_REQUIRED'),
            ({'declared_on': '2026-02-30'}, 'DECLARATION_DATE_REQUIRED'),
            ({'valid_from': '2026-12', 'valid_to': '2026-11'}, 'EXPLICIT_DECLARATION_PERIOD_REQUIRED'),
            ({'valid_to': None}, 'EXPLICIT_DECLARATION_PERIOD_REQUIRED'),
            ({'scope': 'company'}, 'DECLARATION_SCOPE_MISMATCH'),
            ({'fields': {'CST_PIS': 50, 'CST_COFINS': '00'}}, 'CODE_NOT_LISTED_IN_PINNED_REFERENCE_CST_PIS'),
            ({'fields': {'credit': '0.00'}}, 'UNSUPPORTED_CLASSIFICATION_FIELDS'),
            ({'fields': {'CST_PIS': None, 'CST_COFINS': ''}}, 'FIELDS_MISSING_FOR_REVIEW'),
            ({'reference_id': 'latest'}, 'REFERENCE_NOT_RESOLVED')]
        for index, (change, expected) in enumerate(variants):
            self.master([declaration(self.a['id'], id=f'INVALID-{index}', **change)], code=f'INVALID-{index}')
        before = self.database_hash(); result = self.review()
        self.assertEqual(before, self.database_hash())
        by_id = {row['declaration']['id']: row for row in result['records']}
        for index, (_, expected) in enumerate(variants):
            row = by_id[f'INVALID-{index}']
            self.assertIn(expected, {d['code'] for d in row['diagnostics']})
            self.assertTrue(all(not d['blocking_export'] for d in row['diagnostics']))
            self.assertFalse(row['eligible_for_preparation_review'])

    def test_overlap_duplicate_revision_and_disjoint_period_never_choose_latest(self):
        rows = [declaration(self.a['id'], id='SAME', revision='1'), declaration(self.a['id'], id='SAME', revision='2')]
        self.master(rows)
        result = self.review(); self.assertEqual('ambiguous', result['groups'][0]['status'])
        self.assertTrue(all(not row['eligible_for_preparation_review'] for row in result['records']))
        self.master([rows[0]], code='DUPLICATE')
        result = self.review()
        self.assertEqual(2, sum(any(d['code'] == 'DUPLICATE_DECLARATION_REVISION' for d in row['diagnostics']) for row in result['records']))
        self.master([declaration(self.a['id'], id='OUTSIDE', valid_from='2026-10', valid_to='2026-10')], code='OUTSIDE')
        row = next(r for r in self.review()['records'] if r['declaration']['id'] == 'OUTSIDE')
        self.assertIn('OUTSIDE_DECLARED_PERIOD', {d['code'] for d in row['diagnostics']})

    def test_nonobject_namespace_duplicate_json_and_unhashable_identifiers_are_diagnostics(self):
        master = self.master({'id': 'not-a-list'})
        self.master([declaration(self.a['id'], id=['bad'], revision={})], code='BAD-ID')
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE masters SET data_json=? WHERE company_id=? AND id=?',
                ('{"contributions_preparation_v1":[],"contributions_preparation_v1":[]}', self.a['id'], master['id']))
        before = self.database_hash(); result = self.review()
        self.assertEqual(before, self.database_hash())
        self.assertTrue(any(any(d['code'] == 'UNREADABLE_OR_AMBIGUOUS_MASTER_METADATA' for d in row['diagnostics']) for row in result['records']))
        self.assertTrue(any(any(d['code'] == 'MISSING_OR_NONCANONICAL_ID' for d in row['diagnostics']) for row in result['records']))

    def test_declarations_read_in_closed_reopened_period_and_boundary_without_mutation(self):
        self.master([declaration(self.a['id'], valid_from='2026-10', valid_to='2026-11')])
        initial = self.get().content
        for action in ('close', 'reopen'):
            response = self.client.post(self.scope('/periods/' + action), json={'period':'2026-11',
                'module':'fiscal', 'reason':'Fixture de leitura declarativa'})
            self.assertEqual(200, response.status_code, response.text)
            before = self.database_hash()
            self.assertEqual(initial, self.get().content)
            self.assertEqual(before, self.database_hash())
        record = self.review()['records'][0]
        self.assertTrue(record['eligible_for_preparation_review'])
        self.assertFalse(record['classification_applied'])

    def test_document_export_without_master_read_keeps_metadata_private_and_does_not_block(self):
        self.master([declaration(self.a['id'])])
        permissions = [{'company_id': self.a['id'], 'routine': 'fiscal.documents', 'action': action, 'effect': 'allow'} for action in ('read','export')]
        user = self.client.post('/api/users', json={'username': 'somente-documentos', 'password': 'Fixture-ficticia-123!',
            'role': 'custom', 'company_ids': [self.a['id']], 'permissions': permissions})
        self.assertEqual(201, user.status_code)
        with TestClient(self.app) as reader:
            login = reader.post('/api/login', json={'username': 'somente-documentos','password': 'Fixture-ficticia-123!'})
            reader.headers['X-CSRF-Token'] = login.json()['csrf_token']; self.activate(self.a['id'], client=reader)
            response = self.get(client=reader); self.assertEqual(200, response.status_code)
            result = response.json()['snapshot']['preparation_review']
            self.assertEqual('not_authorized', result['status']); self.assertIsNone(result['records'])
            self.assertNotIn('Memória declarada sintética', response.text)
