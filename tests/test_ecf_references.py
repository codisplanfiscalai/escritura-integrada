"""ECF reference metadata only: public normative descriptors and synthetic fixtures."""
import copy
import hashlib
import unittest

# Reuse isolated, temporary app/database setup, never the operator's data directory.
import test_sped_generator as existing
from fastapi.testclient import TestClient
from app.core import digest
from app.permissions import route_policy
from app.sped_generator.ecf_references import (
    API_PATH, load_catalog, official_url, reference_response, select_reference,
    verify_artifact_bytes,
)

REVISION = 'ecf12-tables-2026-09-24'
QUERY = {'start': '2025-01-01', 'end': '2025-12-31', 'situation': '0',
         'revision_id': REVISION, 'sheet': 'L100B'}


def codes(result):
    return {warning['code'] for warning in result['warnings']}


def synthetic_catalog():
    content = b'synthetic reference bytes, not an official workbook'
    return {'scope_rules': [{'layout': 'synthetic', 'calendar_year': 2025,
                            'situation_codes': ['0']}],
            'revisions': [{'id': 'synthetic-v1', 'layout': 'synthetic',
                'revision_date': '2026-01-20', 'kind': 'dynamic_tables_and_reference_charts',
                'source_page': 'https://www.gov.br/sped/synthetic-fixture',
                'download_url': 'https://www.gov.br/sped/synthetic-fixture/@@download/file',
                'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content),
                'verified_payload': True, 'archive_bundled': False,
                'sheets': {'L100B': {'dimension_max_row': 2, 'has_validity_columns': True}}}]}


class EcfReferenceContractTests(unittest.TestCase):
    def select(self, **changes):
        return select_reference(QUERY | changes)

    def unresolved(self, result, code):
        self.assertEqual('unresolved', result['status'])
        self.assertIsNone(result['selected_reference'])
        self.assertIsNone(result['selection_sha256'])
        self.assertIn(code, codes(result))
        self.assertTrue(result['can_export_catalog'])
        self.assertTrue(all(not w['blocking_export'] for w in result['warnings']))

    def test_verified_public_manifest_matches_examined_artifacts(self):
        catalog = load_catalog()
        self.assertEqual('julho/2026', catalog['manual']['content_revision_label'])
        self.assertIsNone(catalog['manual']['revision_date'])  # day not attested
        self.assertEqual('942877bdd3d443444f35758e531b1ab30ce965a62ad148707ef2d68061b9f657', catalog['manual']['sha256'])
        revision = next(r for r in catalog['revisions'] if r['id'] == REVISION)
        self.assertEqual('2a4c9688df7a86c1d9e4c179e8d0547c84b56746742ef7b6a73581fdff3b9ec7', revision['sha256'])
        self.assertEqual(1750838, revision['bytes'])
        self.assertEqual(79, len(revision['sheets']))
        self.assertEqual(76, sum(s['has_validity_columns'] for s in revision['sheets'].values()))
        self.assertIn('24_09_2026', revision['filename_from_resource'])
        self.assertIn('28_05_2026', revision['download_url'])
        self.assertFalse(catalog['publisher_signature_verified'])
        self.assertFalse(catalog['official_program_validated'])
        self.assertEqual({'2026-07-08', '2026-07-15', '2026-07-20', '2026-07-23', '2026-07-25', '2026-09-24'},
                         {r['revision_date'] for r in catalog['revisions']})

    def test_normal_year_boundaries_and_single_day_intervals(self):
        for start, end in [('2025-01-01', '2025-12-31'), ('2025-01-01', '2025-01-01'),
                           ('2025-12-31', '2025-12-31')]:
            with self.subTest(start=start, end=end):
                result = self.select(start=start, end=end)
                self.assertEqual('selected_manifest', result['status'])
                self.assertFalse(result['selected_reference']['row_effectivity_validated'])
        for year in (2024, 2026):
            self.unresolved(self.select(start=f'{year}-01-01', end=f'{year}-12-31'), 'LAYOUT_SCOPE_NOT_CATALOGUED')

    def test_special_situations_are_2026_and_events_7_to_9_are_2025(self):
        for code in range(1, 10):
            year = 2026 if code <= 6 else 2025
            with self.subTest(code=code):
                result = self.select(start=f'{year}-01-01', end=f'{year}-06-30',
                                     situation=str(code), event_date=f'{year}-06-30')
                self.assertEqual('selected_manifest', result['status'])
                other = 2025 if year == 2026 else 2026
                self.unresolved(self.select(start=f'{other}-01-01', end=f'{other}-06-30',
                    situation=str(code), event_date=f'{other}-06-30'), 'LAYOUT_SCOPE_NOT_CATALOGUED')

    def test_event_date_is_explicit_and_must_be_in_query_slice(self):
        for event in (None, '', '2025-12-31', '2026-07-01', '2026-02-30'):
            self.unresolved(self.select(start='2026-01-01', end='2026-06-30', situation='1', event_date=event),
                            'EVENT_DATE_REQUIRED_OR_OUTSIDE_SCOPE')
        self.unresolved(self.select(event_date='2025-06-30'), 'NORMAL_WITH_EVENT_DATE')

    def test_invalid_empty_reversed_and_overlapping_exercises_are_warnings(self):
        for start, end in [(None, None), ('', ''), ('2025-02-30', '2025-12-31'),
                           ('2025-12-31', '2025-01-01'), ('2025-12-31', '2026-01-01'),
                           ('2025-1-1', '2025-12-31')]:
            with self.subTest(start=start, end=end):
                self.unresolved(self.select(start=start, end=end), 'INVALID_OR_UNCOVERED_INTERVAL')
        for situation in (None, '', '10', 'normal'):
            self.unresolved(self.select(situation=situation), 'SITUATION_REQUIRED_OR_UNKNOWN')

    def test_missing_unknown_and_historical_revision_never_use_latest(self):
        self.unresolved(self.select(revision_id=None), 'EXPLICIT_REVISION_REQUIRED')
        for revision in ('latest', 'ecf12-tables-2026-09-25', 'ecf11-tables-2025-01-01'):
            self.unresolved(self.select(revision_id=revision), 'UNKNOWN_REVISION')
        for r in load_catalog()['revisions']:
            if r['id'] == REVISION:
                continue
            self.assertIsNone(r['sha256'])
            self.assertIsNone(r['bytes'])
            self.unresolved(self.select(revision_id=r['id']), 'HISTORICAL_BYTES_NOT_VERIFIED')

    def test_input_and_catalog_ambiguity_have_explicit_contracts(self):
        for value, expected in [(None, 'INVALID_REQUEST'), ({'regime': 'real'}, 'UNKNOWN_SELECTION_FIELDS'),
                                (QUERY | {'situation': 0}, 'INVALID_FIELD_TYPE'),
                                (QUERY | {'revision_id': [REVISION, 'other']}, 'AMBIGUOUS_SELECTION_VALUE')]:
            self.unresolved(select_reference(value), expected)
        self.unresolved(select_reference(QUERY, []), 'INVALID_CATALOG_METADATA')
        catalog = load_catalog()
        catalog['revisions'].append(copy.deepcopy(catalog['revisions'][-1]))
        self.unresolved(select_reference(QUERY, catalog), 'AMBIGUOUS_REVISION')

    def test_new_revision_does_not_change_pinned_historical_selection(self):
        catalog = synthetic_catalog()
        query = QUERY | {'revision_id': 'synthetic-v1'}
        before = copy.deepcopy(catalog)
        selected = select_reference(query, catalog)
        self.assertEqual(before, catalog)
        later = copy.deepcopy(catalog['revisions'][0])
        later.update(id='synthetic-v2', revision_date='2026-12-31', sha256='f' * 64)
        catalog['revisions'].append(later)
        self.assertEqual(selected, select_reference(dict(reversed(list(query.items()))), catalog))
        self.assertNotEqual(selected['selection_sha256'], select_reference(query | {'revision_id': 'synthetic-v2'}, catalog)['selection_sha256'])
        selected['selected_reference']['sha256'] = 'mutated result'
        self.assertEqual(before['revisions'][0], catalog['revisions'][0])

    def test_source_host_scheme_hash_and_size_are_checked_without_network(self):
        good = synthetic_catalog()
        query = QUERY | {'revision_id': 'synthetic-v1'}
        for change in [{'download_url': 'https://www.gov.br.attacker.invalid/sped/test'},
                       {'source_page': 'http://www.gov.br/sped/test'},
                       {'download_url': 'https://user:password@www.gov.br/sped/test'},
                       {'download_url': 'https://www.gov.br:8443/sped/test'},
                       {'download_url': 'https://www.gov.br:bad/sped/test'},
                       {'sha256': 'not-a-sha'}, {'bytes': True}, {'bytes': 0}]:
            with self.subTest(change=change):
                catalog = copy.deepcopy(good)
                catalog['revisions'][0].update(change)
                self.unresolved(select_reference(query, catalog), 'UNTRUSTED_OR_INCOMPLETE_PROVENANCE')
        self.assertFalse(official_url(None))
        self.assertFalse(official_url('https://www.gov.br/another-service/file'))
        self.assertTrue(official_url('https://sped.rfb.gov.br/arquivo/public-example'))

    def test_artifact_integrity_uses_actual_bytes_and_does_not_claim_signature(self):
        reference = synthetic_catalog()['revisions'][0]
        content = b'synthetic reference bytes, not an official workbook'
        before = copy.deepcopy(reference)
        verified = verify_artifact_bytes(content, reference)
        self.assertTrue(verified['matches_pinned_reference'])
        self.assertFalse(verified['publisher_signature_verified'])
        self.assertEqual(before, reference)
        for payload, changes in [(content + b'x', {}), (None, {}), (content, {'bytes': True}),
                                 (content, {'sha256': '0' * 64}), (content, {'download_url': 'https://example.invalid/file'})]:
            self.assertFalse(verify_artifact_bytes(payload, reference | changes)['matches_pinned_reference'])
        self.assertFalse(verify_artifact_bytes(content, None)['matches_pinned_reference'])

    def test_sheets_are_explicit_and_row_effectivity_is_not_invented(self):
        self.unresolved(self.select(sheet='missing'), 'UNKNOWN_SHEET')
        self.unresolved(self.select(sheet='INDICE'), 'INDEX_IS_NOT_REFERENCE_TABLE')
        for sheet in ('PARTEB_PADRAO', 'PARTEB_PARTEA'):
            result = self.select(sheet=sheet)
            self.assertEqual('selected_manifest', result['status'])
            self.assertIn('NO_ROW_DATE_COLUMNS', codes(result))
        result = self.select(sheet=None)
        self.assertIn('SHEET_NOT_SELECTED', codes(result))
        self.assertEqual('selected_manifest', result['status'])
        self.assertIsNone(result['selected_reference']['selected_sheet'])
        for result in (result, self.select()):
            self.assertIn('ROW_EFFECTIVITY_NOT_SELECTED', codes(result))
            self.assertIn('ARCHIVE_NOT_BUNDLED', codes(result))
            self.assertFalse(result['rows_selected'])
            self.assertFalse(result['client_plan_materialized'])
            self.assertFalse(result['generates_ecf'])
            self.assertFalse(result['official_program_validated'])

    def test_malformed_reference_and_sheet_metadata_never_selects(self):
        for change, code in [({'layout': None}, 'INVALID_REFERENCE_METADATA'),
                             ({'kind': 'tax_calculation'}, 'REFERENCE_KIND_NOT_SUPPORTED'),
                             ({'sheets': None}, 'SHEET_INVENTORY_UNAVAILABLE'),
                             ({'sheets': {'L100B': {}}}, 'INVALID_SHEET_METADATA')]:
            catalog = synthetic_catalog()
            catalog['revisions'][0].update(change)
            self.unresolved(select_reference(QUERY | {'revision_id': 'synthetic-v1'}, catalog), code)

    def test_catalog_response_and_selection_are_deterministic_without_shared_mutation(self):
        first = reference_response(QUERY)
        self.assertEqual(digest(first['catalog']), first['catalog_sha256'])
        self.assertEqual(first, reference_response(QUERY))
        first['catalog']['scope_rules'].clear()
        self.assertTrue(reference_response(QUERY)['catalog']['scope_rules'])


class EcfReferenceApiTests(unittest.TestCase):
    setUp = existing.SpedGeneratorApiTests.setUp
    tearDown = existing.SpedGeneratorApiTests.tearDown
    scope = existing.SpedGeneratorApiTests.scope
    activate = existing.SpedGeneratorApiTests.activate
    create_company = existing.SpedGeneratorApiTests.create_company
    database_hash = existing.SpedGeneratorApiTests.database_hash
    journal = existing.base.CoreApiTests.journal
    import_xmls = existing.SpedGeneratorApiTests.import_xmls
    own_xml = existing.SpedGeneratorApiTests.own_xml

    def get_reference(self, client=None, params=None):
        return (client or self.client).get(API_PATH, params=QUERY if params is None else params)

    def test_authenticated_download_is_deterministic_and_changes_no_database_state(self):
        # Include synthetic source BLOBs, accounts, postings and audit records in the hash.
        self.import_xmls(1, 2)
        self.assertEqual(201, self.client.post(self.scope('/journals'), json=self.journal()).status_code)
        before = self.database_hash()
        first, second = self.get_reference(), self.get_reference()
        self.assertEqual(200, first.status_code, first.text)
        self.assertEqual(first.content, second.content)
        self.assertEqual(before, self.database_hash())
        self.assertEqual('no-store', first.headers['cache-control'])
        self.assertIn('attachment', first.headers['content-disposition'])
        self.assertEqual('application/json', first.headers['content-type'])
        result = first.json()
        self.assertEqual(digest(result['catalog']), result['catalog_sha256'])
        self.assertTrue(result['read_only'])
        self.assertNotIn(self.a['tax_id'], first.text)
        self.assertNotIn(self.a['name'], first.text)

    def test_company_switch_and_closed_or_reopened_period_do_not_change_global_metadata(self):
        initial = self.get_reference().content
        for module in ('accounting', 'fiscal'):
            lock = {'period': '2026-11', 'module': module, 'reason': 'Fixture sintética'}
            for operation in ('close', 'reopen'):
                response = self.client.post(self.scope('/periods/' + operation), json=lock)
                self.assertEqual(200, response.status_code, response.text)
                before = self.database_hash()
                self.assertEqual(initial, self.get_reference().content)
                self.assertEqual(before, self.database_hash())
        self.activate(self.b['id'])
        before = self.database_hash()
        self.assertEqual(initial, self.get_reference().content)
        self.assertEqual(before, self.database_hash())

    def test_warnings_unknown_and_repeated_query_fields_are_exportable(self):
        for params, code in [(QUERY | {'revision_id': 'latest'}, 'UNKNOWN_REVISION'),
                             (QUERY | {'regime': 'real'}, 'UNKNOWN_SELECTION_FIELDS'),
                             (list(QUERY.items()) + [('revision_id', 'other')], 'AMBIGUOUS_SELECTION_VALUE'),
                             ({}, 'INVALID_OR_UNCOVERED_INTERVAL')]:
            response = self.get_reference(params=params)
            self.assertEqual(200, response.status_code, response.text)
            result = response.json()['selection']
            self.assertIn(code, codes(result))
            self.assertTrue(result['can_export_catalog'])
            self.assertTrue(all(not w['blocking_export'] for w in result['warnings']))

    def test_authentication_still_required_and_metadata_does_not_grant_domain_permissions(self):
        with TestClient(self.app) as reader:
            self.assertEqual(401, self.get_reference(client=reader).status_code)
            user = self.client.post('/api/users', json={'username': 'referencias',
                'password': 'Leitor-ficticio-123!', 'role': 'custom', 'company_ids': [], 'permissions': []})
            self.assertEqual(201, user.status_code, user.text)
            login = reader.post('/api/login', json={'username': 'referencias', 'password': 'Leitor-ficticio-123!'})
            self.assertEqual(200, login.status_code, login.text)
            reader.headers['X-CSRF-Token'] = login.json()['csrf_token']
            before = self.database_hash()
            self.assertEqual(200, self.get_reference(client=reader).status_code)
            self.assertEqual(before, self.database_hash())
            self.assertEqual(403, reader.get(self.scope('/journals')).status_code)
            self.assertEqual(403, reader.get(self.scope('/sped-generator/native-export')).status_code)
        self.assertEqual((None, None, False), route_policy(API_PATH, 'GET', {}, {}, {}))
        self.assertNotEqual((None, None, False), route_policy(API_PATH, 'POST', {}, {}, {}))
