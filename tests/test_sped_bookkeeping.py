"""Synthetic tests for bookkeeping-to-EFD partial Block C, independent of PVA."""
import base64
import copy
import unittest
from decimal import Decimal

import test_sped_generator as existing
import test_sped_native_export as native
from app.core import DomainError
from app.importers import parse_file
from app.sped_generator.bookkeeping import generate_nfce_block_c

COMPANY = dict(id=7, name='EMPRESA FICTICIA AÇÃO', tax_id='12345678000195',
               state='SP', ie='000000000000', ibge='3550308', im='')
OPTIONS = dict(profile='A', activity='1', purpose='0')


def access_key(number, tax_id=COMPANY['tax_id']):
    first = '352611' + tax_id + '65001' + f'{number:09d}' + '1' + f'{number:08d}'
    if first.isdigit():
        total = sum(int(c) * (2 + i % 8) for i, c in enumerate(reversed(first)))
        digit = 11 - total % 11
        return first + str(0 if digit >= 10 else digit)
    return first + '0'  # Alphanumeric identity tests are not PVA/key validation fixtures.


def analytic(amount='100.00', cfop='5102', cst='000', rate='18.00'):
    return dict(cst_icms=cst, cfop=cfop, rate=rate, operation_total=amount,
        taxes=dict(VL_OPR=amount, VL_BC_ICMS=amount, VL_ICMS='18.00',
                   VL_BC_ICMS_ST='0.00', VL_ICMS_ST='0.00', VL_RED_BC='0.00', VL_IPI='0.00'),
        raw_fields={'COD_OBS': ''})


def document(index=1, **changes):
    number = index
    raw = dict(IND_EMIT='0', COD_SIT='00', IND_PGTO='0', IND_FRT='9', DT_E_S='06112026',
               VL_DOC='100,00', VL_MERC='100,00', VL_DESC='0,00', VL_FRT='0,00', VL_SEG='0,00', VL_OUT_DA='0,00')
    return dict(id=number, version=1, company_id=7, period='2026-11', model='65',
        direction='outgoing', number=str(number), series='001', key=access_key(number),
        issue_date='2026-11-05', posting_date='2026-11-06', total_cents=10000,
        status='booked', source_hash='a' * 64, source={'record': 'C100', 'file': 'sintetico.efd', 'line': 4},
        raw_fields=raw, analytics=[analytic()], items=[], taxes={}, reviewed_by='Teste') | changes


def generate(rows, **changes):
    return generate_nfce_block_c(rows, company=COMPANY, competence='2026-11', options=OPTIONS | changes)


def records(result, code):
    return [line[1:-1].split('|') for line in result['payload'].decode('latin-1').splitlines()
            if line.startswith('|' + code + '|')]


def warning_codes(result):
    return {row['code'] for row in result['warnings']}


class BookkeepingBlockCTests(unittest.TestCase):
    def test_official_partial_structure_counts_field_positions_and_roundtrip(self):
        row = document()
        row['raw_fields'].update(COD_PART='PARTICIPANTE-FICTICIO', VL_BC_ICMS_ST='91,00', VL_ICMS_ST='92,00', VL_IPI='93,00', VL_PIS='94,00', VL_COFINS='95,00', VL_PIS_ST='96,00', VL_COFINS_ST='97,00')
        before = copy.deepcopy(row)
        result = generate([row])
        self.assertEqual(before, row)
        self.assertEqual(['0000', 'C001', 'C100', 'C190', 'C990'],
                         [line.split('|')[1] for line in result['payload'].decode('latin-1').splitlines()])
        self.assertEqual(['C990', '4'], records(result, 'C990')[0])
        header = records(result, '0000')[0]
        self.assertEqual(15, len(header))
        c100, = records(result, 'C100')
        self.assertEqual(29, len(c100))  # Official: code plus 28 data fields.
        self.assertEqual(['1', '0', '', '65', '00', '001', '1', access_key(1)], c100[1:9])
        self.assertEqual(['100,00', '0'], c100[11:13])
        self.assertEqual('100,00', c100[15])
        self.assertEqual(['100,00', '18,00'], c100[20:22])
        self.assertEqual([''] * 7, c100[22:29])  # C100 exception 9 for NFC-e.
        c190, = records(result, 'C190')
        self.assertEqual(12, len(c190))
        self.assertEqual(['000', '5102', '18,00', '100,00', '100,00', '18,00'], c190[1:7])
        parsed = parse_file('bloco-c.txt', result['payload'], COMPANY | {'import_options': {'encoding': 'ISO-8859-1'}})
        self.assertTrue(parsed['can_confirm'], parsed['issues'])
        self.assertNotIn('SPED_FIELD_COUNT', {i['code'] for i in parsed['issues']})
        self.assertEqual('100.00', parsed['documents'][0]['total'])
        self.assertFalse(result['complete_efd'])
        self.assertFalse(result['pva_validated'])
        self.assertFalse(result['transmitted'])
        self.assertTrue(result['can_export'])
        self.assertEqual([1], [row['document_id'] for row in result['trace']])

    def test_each_document_remains_individual_and_input_is_unchanged(self):
        rows = [document(2), document(1)]
        before = copy.deepcopy(rows)
        result = generate(rows)
        self.assertEqual(before, rows)
        self.assertEqual(result, generate(reversed(rows)))
        self.assertEqual(2, len(records(result, 'C100')))
        self.assertEqual([access_key(1), access_key(2)], [r[8] for r in records(result, 'C100')])
        self.assertEqual([3, 5], [t['c100_line'] for t in result['trace']])
        self.assertEqual(['C990', '6'], records(result, 'C990')[0])

    def test_current_book_values_override_original_header_without_resumming_c100(self):
        row = document(total_cents=12500)
        row['analytics'][0]['taxes']['VL_ICMS'] = '12.34'
        result = generate([row])
        c100, = records(result, 'C100')
        self.assertEqual('125,00', c100[11])
        self.assertEqual('12,34', c100[21])
        self.assertEqual('100,00', records(result, 'C190')[0][4])
        self.assertIn('POSTING_C190_TOTAL_MISMATCH', warning_codes(result))
        self.assertTrue(result['can_export'])

    def test_analytics_merge_only_same_cst_cfop_rate_with_exact_cents(self):
        row = document(total_cents=30)
        row['analytics'] = [analytic('0.10'), analytic('0.20')]
        result = generate([row])
        self.assertEqual(1, len(records(result, 'C190')))
        self.assertEqual('0,30', records(result, 'C190')[0][4])
        row['analytics'][1]['cfop'] = '5405'
        self.assertEqual(2, len(records(generate([row]), 'C190')))

    def test_missing_values_and_invalid_fiscal_classification_warn_without_blocking(self):
        row = document()
        row['analytics'][0] = analytic(cst='', cfop='6102')
        del row['analytics'][0]['taxes']['VL_ICMS']
        result = generate([row])
        self.assertTrue(result['can_export'])
        self.assertEqual('', records(result, 'C190')[0][6])
        self.assertTrue({'CST_REVIEW', 'NFCE_CFOP_REVIEW', 'BOOK_VALUE_MISSING'} <= warning_codes(result))
        self.assertTrue(all(w['severity'] == 'warning' for w in result['warnings']))

    def test_posting_issue_and_effective_movement_dates_remain_distinct(self):
        row = document(issue_date='2026-10-31')
        row['raw_fields']['DT_E_S'] = ''
        result = generate([row])
        self.assertEqual(['31102026', ''], records(result, 'C100')[0][9:11])
        self.assertEqual('2026-11-06', result['trace'][0]['posting_date'])
        self.assertIn('ISSUE_OUTSIDE_POSTING_PERIOD', warning_codes(result))
        row['movement_date'] = '2026-11-02'
        self.assertEqual('02112026', records(generate([row]), 'C100')[0][10])

    def test_scope_is_explicit_and_does_not_silently_treat_other_documents_as_generated(self):
        changes = [
            dict(status='pending'), dict(model='55'), dict(direction='incoming'),
            dict(book_cancellation={'source': 'livro sintético'}),
            dict(source={'record': 'manual'}, raw_fields={}),
        ]
        result = generate([document(i + 1, **change) for i, change in enumerate(changes)])
        self.assertEqual(5, result['summary']['skipped_documents'])
        self.assertEqual([], records(result, 'C100'))
        self.assertEqual([['C001', '1']], records(result, 'C001'))
        self.assertEqual([['C990', '2']], records(result, 'C990'))
        self.assertTrue(result['can_export'])
        for change in [dict(company_id=8), dict(period='2026-10')]:
            with self.assertRaises(DomainError):
                generate([document(**change)])

    def test_supplied_header_is_preserved_and_scoped_to_company_and_period(self):
        header = generate([])['payload'].decode('latin-1').splitlines()[0]
        result = generate([document()], header_0000=header)
        self.assertEqual(header, result['payload'].decode('latin-1').splitlines()[0])
        for changed in [header.replace(COMPANY['tax_id'], '87654321000198'),
                        header.replace('01112026', '01102026')]:
            with self.assertRaises(DomainError):
                generate([], header_0000=changed)

    def test_year_and_missing_header_metadata_warn_without_inventing_defaults(self):
        result = generate_nfce_block_c([], company=COMPANY, competence='2027-01')
        self.assertEqual('', records(result, '0000')[0][1])
        self.assertEqual('', records(result, '0000')[0][2])
        self.assertEqual(['', ''], records(result, '0000')[0][-2:])
        self.assertIn('LAYOUT_PERIOD_NOT_VERIFIED', warning_codes(result))
        self.assertIn('HEADER_VALUE_MISSING', warning_codes(result))

    def test_invalid_key_and_rtc_totals_do_not_prevent_export(self):
        row = document(declared_new_total='119.00')
        row['key'] = row['key'][:-1] + str((int(row['key'][-1]) + 1) % 10)
        result = generate([row])
        self.assertEqual(row['key'], records(result, 'C100')[0][8])
        self.assertIn('KEY_CHECK_DIGIT_REVIEW', warning_codes(result))
        self.assertIn('RTC_TOTAL_REVIEW', warning_codes(result))

    def test_duplicate_identities_are_reported_without_merging_or_deleting_records(self):
        row = document(2, key=access_key(1), number='1')
        result = generate([document(), row])
        self.assertEqual(2, len(records(result, 'C100')))
        self.assertIn('DUPLICATE_IDENTITY_REVIEW', warning_codes(result))

    def test_nonrepresentable_fields_warn_and_do_not_inject_records_or_change_database_values(self):
        company = COMPANY | {'name': 'NOME|\r\n|C100|\U0001f642'}
        result = generate_nfce_block_c([], company=company, competence='2026-11', options=OPTIONS)
        self.assertEqual('', records(result, '0000')[0][5])
        self.assertIn('FIELD_NOT_REPRESENTABLE', warning_codes(result))
        self.assertEqual([], records(result, 'C100'))
        self.assertIn('|', company['name'])
        self.assertIn(b'\xc7\xc3', generate([])['payload'])  # Latin-1 preserves AÇÃO.

    def test_more_than_grid_capacity_is_exported_with_complete_trace(self):
        result = generate(document(n) for n in range(1, 5002))
        self.assertEqual(5001, result['summary']['exported_documents'])
        self.assertEqual(5001, len(result['trace']))
        self.assertEqual(5001, len(records(result, 'C100')))
        self.assertEqual(50010000, result['summary']['total_cents'])

    def test_xml_uses_book_treatment_not_automatic_credit_from_declared_tax(self):
        row = document()
        row.pop('analytics')
        row['source'] = {'record': 'infNFe', 'file': 'synthetic.xml'}
        row['issuer'] = {'tax_id': COMPANY['tax_id']}
        row['raw_fields'] = {}
        row['authorization'] = {'status': '100'}
        row['environment'] = '2'
        row['items'] = [dict(number='1', total='100.00', cfop='5102',
            declared_product_fields={'vProd': '100.00'},
            taxes={'ICMS/ICMS00/orig': '0', 'ICMS/ICMS00/CST': '00', 'ICMS/ICMS00/pICMS': '18',
                   'ICMS/ICMS00/vBC': '100.00', 'ICMS/ICMS00/vICMS': '18.00'})]
        row['fiscal_treatment'] = dict(code='outros', book_mode='other_excluding_ipi',
            source='Decisão sintética', responsible='Teste', valid_from='2026-01-01', valid_to='')
        row['taxes'] = {'ICMSTot/vProd': '100.00'}
        result = generate([row])
        self.assertEqual('000', records(result, 'C190')[0][1])
        self.assertEqual(['0,00', '0,00'], records(result, 'C190')[0][5:7])
        self.assertIn('XML_ENVIRONMENT_REVIEW', warning_codes(result))
        self.assertTrue(result['can_export'])

    def test_non_active_source_situation_is_not_recast_as_regular_movement(self):
        row = document()
        row['raw_fields']['COD_SIT'] = '02'
        result = generate([row])
        self.assertEqual([], records(result, 'C100'))
        self.assertEqual('NON_ACTIVE_SITUATION_NOT_COVERED', result['skipped'][0]['reason'])
        self.assertTrue(result['can_export'])

    def test_header_abatement_and_invalid_fiscal_indicators_are_preserved_with_warnings(self):
        row = document()
        row['raw_fields'].update(VL_ABAT_NT='1,23', IND_PGTO='9', IND_FRT='7')
        result = generate([row])
        self.assertEqual('1,23', records(result, 'C100')[0][14])
        self.assertEqual('9', records(result, 'C100')[0][12])
        self.assertEqual('7', records(result, 'C100')[0][16])
        self.assertTrue({'PAYMENT_INDICATOR_REVIEW', 'FREIGHT_INDICATOR_REVIEW'} <= warning_codes(result))


class BookkeepingBlockCApiTests(unittest.TestCase):
    setUp = existing.SpedGeneratorApiTests.setUp
    tearDown = existing.SpedGeneratorApiTests.tearDown
    scope = existing.SpedGeneratorApiTests.scope
    activate = existing.SpedGeneratorApiTests.activate
    create_company = existing.SpedGeneratorApiTests.create_company
    own_xml = existing.SpedGeneratorApiTests.own_xml
    import_xmls = existing.SpedGeneratorApiTests.import_xmls
    database_hash = existing.SpedGeneratorApiTests.database_hash

    def export(self, **changes):
        return self.client.post(self.scope('/sped-generator/bookkeeping-block-c'),
            json={'period': '2026-11'} | OPTIONS | changes)

    def test_booked_xml_data_generates_partial_block_and_preserves_full_database(self):
        self.import_xmls(1, 2, book=True)
        before = self.database_hash()
        response = self.export()
        self.assertEqual(200, response.status_code, response.text)
        result = response.json()
        self.assertEqual(2, result['summary']['exported_documents'])
        self.assertFalse(result['complete_efd'])
        self.assertFalse(result['pva_validated'])
        self.assertTrue(result['can_export'])
        self.assertEqual(result, self.export().json())
        self.assertEqual(before, self.database_hash())
        self.assertEqual(2, len(self.core.documents(self.a['id'])))
        self.assertEqual(2, base64.b64decode(result['content_base64']).count(b'|C100|'))
        self.assertTrue(result['warnings'])  # Missing metadata/treatment remains informational.

    def test_closed_and_reopened_periods_allow_read_only_generation(self):
        self.import_xmls(1, book=True)
        for state in ('open', 'closed', 'reopened'):
            if state != 'open':
                r = self.client.post(self.scope('/periods/' + ('close' if state == 'closed' else 'reopen')),
                    json={'period': '2026-11', 'module': 'fiscal', 'reason': 'Teste sintético'})
                self.assertEqual(200, r.status_code, r.text)
            before = self.database_hash()
            self.assertEqual(200, self.export().status_code)
            self.assertEqual(before, self.database_hash())

    def test_company_module_year_csrf_and_header_isolation(self):
        self.import_xmls(1, book=True)
        self.assertEqual(403, self.client.post(self.scope('/sped-generator/bookkeeping-block-c'),
            json={'period': '2026-11'}, headers={'X-CSRF-Token': ''}).status_code)
        self.assertEqual(409, self.export(period='2025-11').status_code)
        header = generate([])['payload'].decode('latin-1').splitlines()[0]
        self.assertEqual(409, self.export(header_0000=header).status_code)
        self.assertEqual(400, self.export(consolidate_nfce=True).status_code)
        self.activate(self.b['id'])
        self.assertEqual(409, self.export().status_code)
        r = self.client.post('/api/context', json={'company_id': self.a['id'], 'period': '2026-11', 'module': 'accounting'})
        self.assertEqual(200, r.status_code, r.text)
        self.assertEqual(409, self.export().status_code)

    def test_document_export_permission_does_not_require_original_import_export(self):
        from fastapi.testclient import TestClient
        self.import_xmls(1, book=True)
        grants = [{'company_id': self.a['id'], 'routine': 'fiscal.documents', 'action': action, 'effect': 'allow'}
                  for action in ('read', 'export')]
        r = self.client.post('/api/users', json={'username': 'gerador-escritura', 'password': 'Senha-ficticia-789!',
            'role': 'custom', 'company_ids': [self.a['id']], 'permissions': grants})
        self.assertEqual(201, r.status_code, r.text)
        uid = r.json()['id']
        endpoint = self.scope('/sped-generator/bookkeeping-block-c')
        with TestClient(self.app) as reader:
            login = reader.post('/api/login', json={'username': 'gerador-escritura', 'password': 'Senha-ficticia-789!'})
            self.assertEqual(200, login.status_code, login.text)
            reader.headers['X-CSRF-Token'] = login.json()['csrf_token']
            self.activate(self.a['id'], client=reader)
            response = reader.post(endpoint, json={'period': '2026-11'} | OPTIONS)
            self.assertEqual(200, response.status_code, response.text)
            with self.app.state.db.transaction() as conn:
                conn.execute("UPDATE user_permissions SET effect='deny' WHERE user_id=? AND action='export'", (uid,))
            self.assertEqual(403, reader.post(endpoint, json={'period': '2026-11'}).status_code)
        with TestClient(self.app) as anonymous:
            self.assertEqual(401, anonymous.post(endpoint, json={'period': '2026-11'}).status_code)

    def test_client_sped_and_native_optional_path_remain_available(self):
        batch, raw = native.NativeExportApiTests.source_batch(self)
        before = self.database_hash()
        endpoint = self.scope('/sped-generator/consolidation-export')
        for enabled in (False, True):
            r = self.client.post(endpoint, json={'period': '2026-11', 'import_id': batch['id'], 'consolidate_nfce': enabled})
            self.assertEqual(200, r.status_code, r.text)
            if not enabled:
                self.assertEqual(raw, base64.b64decode(r.json()['content_base64']))
            else:
                self.assertTrue(r.json()['consolidated'])
        self.assertEqual(before, self.database_hash())

    def test_later_bookkeeping_edit_is_exported_without_reparsing_original_xml(self):
        batch, original = self.import_xmls(1, book=True)
        doc = self.core.documents(self.a['id'])[0]
        response = self.client.put(self.scope(f"/documents/{doc['id']}"), json=doc | {
            'total': '125.00', 'reason': 'Correção sintética na escrituração, com origem preservada'})
        self.assertEqual(200, response.status_code, response.text)
        edited = response.json()
        result = self.export().json()
        line = next(line for line in base64.b64decode(result['content_base64']).decode('latin-1').splitlines()
                    if line.startswith('|C100|'))
        self.assertEqual('125,00', line[1:-1].split('|')[11])
        self.assertEqual(edited['version'], result['trace'][0]['version'])
        self.assertEqual(doc['source_hash'], result['trace'][0]['source_hash'])
        with self.app.state.db.read() as conn:
            self.assertEqual(original, conn.execute('SELECT original FROM imports WHERE id=?', (batch['id'],)).fetchone()[0])
