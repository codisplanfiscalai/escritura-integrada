"""Synthetic regressions for optional operational grouping during generation."""
import base64
import copy
import hashlib
import unittest

from fastapi.testclient import TestClient
from app.core import DomainError
from app.importers import parse_file
from app.sped_generator.bookkeeping import generate_nfce_block_c
from app.sped_generator.bookkeeping_native import consolidate_generated_block_c
import test_sped_bookkeeping as base
import test_sped_native_export as native


class GeneratedConsolidationTests(unittest.TestCase):
    def test_default_and_disabled_retain_whole_individual_result(self):
        rows = [base.document(2), base.document(1)]
        expected = base.generate(rows)
        self.assertEqual(expected, base.generate(rows, consolidate_nfce=False))
        self.assertEqual(expected, base.generate(rows, consolidate_nfce=False, segment_on_gap=False))
        self.assertEqual(2, len(base.records(expected, 'C100')))

    def test_actual_group_totals_keys_dates_counts_encoding_and_complete_trace(self):
        rows = [base.document(2), base.document(1)]
        before = copy.deepcopy(rows)
        individual = base.generate(rows)
        result = base.generate(rows, consolidate_nfce=True)
        self.assertEqual(before, rows)
        self.assertTrue(result['consolidated'])
        self.assertEqual('native_operational_nfce_groups', result['representation'])
        self.assertEqual('ISO-8859-1', result['encoding'])
        self.assertIn('AÇÃO', result['payload'].decode('latin-1'))
        self.assertEqual(['0000', '0460', 'C001', 'C100', 'C190', 'C195', 'C990'],
                         [line.split('|')[1] for line in result['payload'].decode('latin-1').splitlines()])
        row, = base.records(result, 'C100')
        self.assertEqual(30, len(row))  # Native representation, not the official C100.
        self.assertEqual(['1', base.access_key(1)], row[7:9])
        self.assertEqual(['05112026', '05112026', '200,00'], row[9:12])
        self.assertEqual('36,00', base.records(result, 'C190')[0][6])
        self.assertEqual(['C990', '5'], base.records(result, 'C990')[0])
        self.assertEqual(20000, result['summary']['total_cents'])
        self.assertEqual(2, result['summary']['exported_documents'])
        self.assertEqual(1, result['summary']['output_c100_records'])
        self.assertEqual(1, result['summary']['c190_records'])
        self.assertEqual(2, result['summary']['individual_c190_records'])
        self.assertEqual([1, 2], [t['document_id'] for t in result['trace']])
        self.assertEqual([4, 4], [t['c100_line'] for t in result['trace']])
        self.assertEqual([3, 5], [t['source_c100_line'] for t in result['trace']])
        self.assertEqual(hashlib.sha256(individual['payload']).hexdigest(), result['individual_result_sha256'])
        self.assertEqual(hashlib.sha256(result['payload']).hexdigest(), result['result_sha256'])
        group, = result['consolidation_trace']
        self.assertEqual(4, group['output_c100_line'])
        self.assertEqual([base.access_key(1), base.access_key(2)], [m['key'] for m in group['members']])
        lines = individual['payload'].decode('latin-1').splitlines()
        for member in group['members']:
            self.assertEqual('a' * 64, member['source_hash'])
            self.assertEqual(1, member['version'])
            self.assertEqual('2026-11-06', member['posting_date'])
            self.assertEqual(hashlib.sha256(lines[member['source_line'] - 1].encode()).hexdigest(),
                             member['source_c100_sha256'])

    def test_unknown_monetary_fields_never_become_zero_or_known_partial_sum(self):
        rows = [base.document(1), base.document(2)]
        rows[0]['analytics'][0]['taxes'].pop('VL_BC_ICMS')  # Existing domain treats an absent key as unknown.
        rows[0]['analytics'][0]['taxes']['VL_ICMS_ST'] = None
        rows[0]['raw_fields']['VL_DESC'] = ''
        result = base.generate(rows, consolidate_nfce=True)
        c100 = base.records(result, 'C100')[0]
        c190 = base.records(result, 'C190')[0]
        self.assertEqual('', c100[13])  # Unknown discount despite known zero in the other member.
        self.assertEqual('', c100[20])  # One unknown base makes the aggregate unknown.
        self.assertEqual([''] * 8, c100[22:30])  # Prohibited fields and native extension stay blank.
        self.assertEqual('', c190[5])
        self.assertEqual('', c190[8])
        self.assertEqual('0,00', c190[7])  # Explicit known ST base zeros stay zero.
        self.assertIn('BOOK_VALUE_MISSING', base.warning_codes(result))
        self.assertTrue(result['can_export'])

    def test_unknown_and_explicit_zero_rates_are_not_coalesced(self):
        a, b = base.document(1), base.document(2)
        a['analytics'][0]['rate'] = None
        b['analytics'][0]['rate'] = '0.00'
        result = base.generate([a, b], consolidate_nfce=True)
        rows = base.records(result, 'C190')
        self.assertEqual(['', '0,00'], [r[3] for r in rows])
        self.assertEqual(['100,00', '100,00'], [r[4] for r in rows])

    def test_gap_option_is_independent_and_day_series_boundaries_remain(self):
        rows = [base.document(1), base.document(3), base.document(4, issue_date='2026-11-06'),
                base.document(5, series='002')]
        separated = base.generate(rows, consolidate_nfce=True)
        compact = base.generate(rows, consolidate_nfce=True, segment_on_gap=False)
        self.assertEqual(4, len(separated['consolidation_trace']))
        self.assertEqual(3, len(compact['consolidation_trace']))
        self.assertEqual([1, 3], [m['document_id'] for m in compact['consolidation_trace'][0]['members']])

    def test_business_warnings_do_not_prevent_generation_and_non2026_stays_unverified(self):
        row = base.document()
        row['analytics'][0].update(cst_icms='', cfop='', rate=None)
        result = generate_nfce_block_c([row], company=base.COMPANY, competence='2026-11',
                                      options={'consolidate_nfce': True})
        self.assertTrue(result['can_export'])
        self.assertTrue(result['consolidated'])
        self.assertIn('HEADER_VALUE_MISSING', base.warning_codes(result))
        self.assertIn('CST_REVIEW', base.warning_codes(result))
        older = base.document(period='2025-11', issue_date='2025-11-05', posting_date='2025-11-06')
        result = generate_nfce_block_c([older], company=base.COMPANY, competence='2025-11',
                                      options={'consolidate_nfce': True})
        self.assertEqual('', base.records(result, '0000')[0][1])
        self.assertIn('LAYOUT_PERIOD_NOT_VERIFIED', base.warning_codes(result))
        self.assertTrue(result['can_export'])

    def test_duplicate_or_invalid_key_falls_back_without_blocking_export(self):
        for rows in ([base.document(1), base.document(2, key=base.access_key(1))],
                     [base.document(1, key='INVALIDA')]):
            individual = base.generate(rows)
            result = base.generate(rows, consolidate_nfce=True)
            self.assertEqual(individual['payload'], result['payload'])
            self.assertFalse(result['consolidated'])
            self.assertTrue(result['can_export'])
            self.assertIn('BOOKKEEPING_CONSOLIDATION_NOT_APPLIED', base.warning_codes(result))

    def test_empty_or_non_regular_situation_returns_individual_without_false_group(self):
        for rows in ([], [base.document(raw_fields={'IND_EMIT': '0', 'COD_SIT': ''})]):
            individual = base.generate(rows)
            result = base.generate(rows, consolidate_nfce=True)
            self.assertEqual(individual['payload'], result['payload'])
            self.assertFalse(result['consolidated'])
            self.assertEqual([], result['consolidation_trace'])

    def test_scope_still_excludes_entries_other_models_cancelled_and_unbooked(self):
        rows = [base.document(1), base.document(2, model='55'),
                base.document(3, direction='incoming'), base.document(4, status='pending'),
                base.document(5, book_cancellation={'reason': 'Fixture sintética'})]
        result = base.generate(rows, consolidate_nfce=True)
        self.assertEqual(1, result['summary']['exported_documents'])
        self.assertEqual([2, 3, 4, 5], [d['document_id'] for d in result['skipped']])
        self.assertEqual([1], [m['document_id'] for g in result['consolidation_trace'] for m in g['members']])
        for changes in ({'company_id': 8}, {'period': '2026-10'}):
            with self.assertRaises(DomainError):
                base.generate([base.document(**changes)], consolidate_nfce=True)

    def test_original_issue_and_posting_dates_remain_in_trace_across_periods(self):
        row = base.document(issue_date='2026-10-31', posting_date='2026-11-06')
        result = base.generate([row], consolidate_nfce=True)
        self.assertEqual('2026-11', result['period'])
        self.assertEqual('2026-10-31', result['trace'][0]['issue_date'])
        self.assertEqual('2026-11-06', result['trace'][0]['posting_date'])
        self.assertEqual('31102026', base.records(result, 'C100')[0][9])

    def test_deterministic_order_and_no_grid_truncation(self):
        rows = [base.document(n) for n in range(1, 5002)]
        expected = base.generate(rows, consolidate_nfce=True)
        self.assertEqual(expected, base.generate(reversed(rows), consolidate_nfce=True))
        self.assertEqual(5001, expected['summary']['exported_documents'])
        self.assertEqual(5001, len(expected['consolidation_trace'][0]['members']))
        self.assertEqual(50010000, expected['summary']['total_cents'])

    def test_partial_adapter_refuses_unknown_records_but_preserves_individual_bytes(self):
        result = base.generate([base.document()])
        result['payload'] = result['payload'].replace(b'|C190|', b'|C170|')
        result['result_sha256'] = hashlib.sha256(result['payload']).hexdigest()
        original = copy.deepcopy(result)
        output = consolidate_generated_block_c(result, company_tax_id=base.COMPANY['tax_id'],
                                               competence='2026-11')
        self.assertEqual(original, result)
        self.assertEqual(original['payload'], output['payload'])
        self.assertFalse(output['consolidated'])
        self.assertTrue(output['can_export'])
        for changes in ({'company_tax_id': '99999999999999'}, {'competence': '2026-10'}):
            with self.assertRaises(DomainError):
                consolidate_generated_block_c(base.generate([]),
                    **({'company_tax_id': base.COMPANY['tax_id'], 'competence': '2026-11'} | changes))

    def test_nonboolean_options_fail_without_changing_input(self):
        rows = [base.document()]
        before = copy.deepcopy(rows)
        for key in ('consolidate_nfce', 'segment_on_gap'):
            for value in ('true', 1, None, [], {}):
                with self.assertRaises(DomainError):
                    base.generate(rows, **{key: value})
        self.assertEqual(before, rows)

    def test_operational_flags_and_reader_limitation_remain_explicit(self):
        result = base.generate([base.document(1), base.document(2)], consolidate_nfce=True)
        self.assertFalse(result['complete_efd'])
        self.assertFalse(result['pva_validated'])
        self.assertFalse(result['transmitted'])
        self.assertFalse(result['official_pva_replacement'])
        self.assertEqual('NATIVE_NFCE_OPERATIONAL_PARTIAL_BLOCK_C', result['kind'])
        parsed = parse_file('operacional.txt', result['payload'],
                            base.COMPANY | {'import_options': {'encoding': 'ISO-8859-1'}})
        self.assertIn('SPED_FIELD_COUNT', {x['code'] for x in parsed['issues']})
        self.assertTrue(result['can_export'])


class GeneratedConsolidationApiTests(unittest.TestCase):
    setUp = base.BookkeepingBlockCApiTests.setUp
    tearDown = base.BookkeepingBlockCApiTests.tearDown
    scope = base.BookkeepingBlockCApiTests.scope
    activate = base.BookkeepingBlockCApiTests.activate
    create_company = base.BookkeepingBlockCApiTests.create_company
    own_xml = base.BookkeepingBlockCApiTests.own_xml
    import_xmls = base.BookkeepingBlockCApiTests.import_xmls
    database_hash = base.BookkeepingBlockCApiTests.database_hash
    export = base.BookkeepingBlockCApiTests.export

    def test_individual_xml_import_then_independent_generation_options_preserves_every_table(self):
        batch, raw = self.import_xmls(1, 2, book=True)
        before = self.database_hash()
        individual = self.export().json()
        grouped = self.export(consolidate_nfce=True).json()
        self.assertEqual(individual, self.export(consolidate_nfce=False).json())
        self.assertEqual(grouped, self.export(consolidate_nfce=True).json())
        self.assertEqual(2, base64.b64decode(individual['content_base64']).count(b'|C100|'))
        self.assertEqual(1, base64.b64decode(grouped['content_base64']).count(b'|C100|'))
        self.assertEqual(2, len(grouped['trace']))
        self.assertTrue(grouped['filename'].startswith('consolidacao-operacional-bloco-c-'))
        self.assertTrue(grouped['warnings'])
        self.assertTrue(grouped['can_export'])
        self.assertFalse(grouped['complete_efd'])
        self.assertEqual(before, self.database_hash())
        self.assertEqual(2, len(self.core.documents(self.a['id'])))
        self.assertEqual([], self.core.documents(self.b['id']))
        self.assertEqual([], self.core.titles(self.a['id']))
        self.assertEqual([], self.core.journals(self.a['id']))
        with self.app.state.db.read() as conn:
            self.assertEqual(raw, conn.execute('SELECT original FROM imports WHERE id=?', (batch['id'],)).fetchone()[0])
            self.assertEqual(2, conn.execute('SELECT count(*) FROM document_sources WHERE company_id=?', (self.a['id'],)).fetchone()[0])

    def test_open_closed_reopened_readonly_exports_and_closed_edits_remain_protected(self):
        self.import_xmls(1, 2, book=True)
        doc = self.core.documents(self.a['id'])[0]
        for state in ('open', 'closed', 'reopened'):
            if state != 'open':
                response = self.client.post(self.scope('/periods/' + ('close' if state == 'closed' else 'reopen')),
                    json={'period': '2026-11', 'module': 'fiscal', 'reason': 'Fixture sintética'})
                self.assertEqual(200, response.status_code, response.text)
            before = self.database_hash()
            for enabled in (False, True):
                response = self.export(consolidate_nfce=enabled)
                self.assertEqual(200, response.status_code, response.text)
            self.assertEqual(before, self.database_hash())
            if state == 'closed':
                response = self.client.put(self.scope(f"/documents/{doc['id']}"),
                    json=doc | {'description': 'Revisão sintética', 'reason': 'Fixture sintética'})
                self.assertEqual(409, response.status_code, response.text)
            if state == 'reopened':
                response = self.client.put(self.scope(f"/documents/{doc['id']}"),
                    json=doc | {'description': 'Revisão sintética', 'reason': 'Fixture sintética'})
                self.assertEqual(200, response.status_code, response.text)

    def test_scope_csrf_and_explicit_option_types(self):
        self.import_xmls(1, 2, book=True)
        endpoint = self.scope('/sped-generator/bookkeeping-block-c')
        self.assertEqual(403, self.client.post(endpoint, json={'period': '2026-11', 'consolidate_nfce': True},
                         headers={'X-CSRF-Token': ''}).status_code)
        for key in ('consolidate_nfce', 'segment_on_gap'):
            for value in ('true', 1, None):
                self.assertEqual(400, self.export(**{key: value}).status_code)
        self.assertEqual(400, self.export(unknown_option=True).status_code)
        self.assertEqual(409, self.export(period='2025-11', consolidate_nfce=True).status_code)
        self.activate(self.b['id'])
        self.assertEqual(409, self.export(consolidate_nfce=True).status_code)

    def test_permissions_are_live_and_original_import_export_is_not_required(self):
        self.import_xmls(1, 2, book=True)
        endpoint = self.scope('/sped-generator/bookkeeping-block-c')
        grants = [{'company_id': self.a['id'], 'routine': 'fiscal.documents', 'action': action, 'effect': 'allow'}
                  for action in ('read', 'export')]
        response = self.client.post('/api/users', json={'username': 'grupo-escrituracao',
            'password': 'Senha-sintetica-321!', 'role': 'custom', 'company_ids': [self.a['id']], 'permissions': grants})
        self.assertEqual(201, response.status_code, response.text)
        uid = response.json()['id']
        with TestClient(self.app) as reader:
            login = reader.post('/api/login', json={'username': 'grupo-escrituracao', 'password': 'Senha-sintetica-321!'})
            reader.headers['X-CSRF-Token'] = login.json()['csrf_token']
            self.activate(self.a['id'], client=reader)
            before = self.database_hash()
            response = reader.post(endpoint, json={'period': '2026-11', 'consolidate_nfce': True})
            self.assertEqual(200, response.status_code, response.text)
            self.assertTrue(response.json()['consolidated'])
            self.assertEqual(before, self.database_hash())
            with self.app.state.db.transaction() as conn:
                conn.execute("UPDATE user_permissions SET effect='deny' WHERE user_id=? AND action='export'", (uid,))
            self.assertEqual(403, reader.post(endpoint, json={'period': '2026-11', 'consolidate_nfce': True}).status_code)
        with TestClient(self.app) as anonymous:
            self.assertEqual(401, anonymous.post(endpoint, json={'period': '2026-11', 'consolidate_nfce': True}).status_code)

    def test_existing_client_sped_native_export_is_independent_and_byte_golden_is_preserved(self):
        batch, original = native.NativeExportApiTests.source_batch(self)
        before = self.database_hash()
        endpoint = self.scope('/sped-generator/consolidation-export')
        for enabled in (False, True):
            response = self.client.post(endpoint, json={'period': '2026-11', 'import_id': batch['id'],
                                                        'consolidate_nfce': enabled})
            self.assertEqual(200, response.status_code, response.text)
            if not enabled:
                self.assertEqual(original, base64.b64decode(response.json()['content_base64']))
            else:
                self.assertTrue(response.json()['consolidated'])
        self.assertEqual(before, self.database_hash())
