"""Native optional export regression; all input is synthetic."""
import base64
import unittest
from pathlib import Path

from app.core import DomainError
from app.sped_generator.native_export import consolidate_native_sped
import test_sped_generator as preview_tests

TAX_ID = '12ABC34501DE35'


def native_source(tax_id=TAX_ID, *, numbers=(100, 101), direction='1', issuer='0', gap=False):
    source = (Path(__file__).parent / 'fixtures/sped_ficticio_020.txt').read_text()
    source = source.replace('12345678000195', tax_id)
    source = source.replace('|C100|0|1|BETA|01|00|1|42||', '|C100|0|1|BETA|55|00|1|42|' + '9' * 44 + '|')
    # Preserve original model 55, FAT/DUP and unrelated records.
    lines = [line for line in source.splitlines() if not line.startswith(('|C990|', '|9'))]
    for index, number in enumerate(numbers):
        total = 10 * (index + 1)
        fields = [direction, issuer, '', '65', '00', '130', str(number), str(index + 1) * 44,
                  '05112026', '05112026', f'{total},00']
        fields += [''] * (28 - len(fields))
        lines += ['|C100|' + '|'.join(fields) + '|',
                  f'|C190|000|5102|18,00|{total},00|{total},00|{total * 18 // 100},{total * 18 % 100:02d}|0,00|0,00|0,00|0,00||',
                  '|C191|0,10|0,20|0,30|']
    lines += ['|C990|1|', '|9001|0|', '|9990|1|', '|9999|1|']
    return ('\r\n'.join(lines) + '\r\n').encode()


def export(payload, **options):
    return consolidate_native_sped(payload, company_tax_id=TAX_ID, competence='2026-11', **options)


def records(payload, code):
    return [line[1:-1].split('|') for line in payload.decode().splitlines() if line.startswith(f'|{code}|')]


class NativeExportTests(unittest.TestCase):
    def test_disabled_is_byte_identical_and_default_is_off(self):
        source = native_source()
        self.assertEqual(source, export(source)['payload'])
        self.assertEqual([], export(source)['trace'])
        self.assertFalse(export(source)['consolidated'])

    def test_native_c100_first_key_analytics_fcp_trace_and_model55_billing(self):
        source = native_source()
        result = export(source, enabled=True)
        nfce = [r for r in records(result['payload'], 'C100') if r[4] == '65']
        self.assertEqual(1, len(nfce))
        self.assertEqual(['100', '1' * 44], nfce[0][7:9])
        self.assertEqual('30,00', nfce[0][11])
        self.assertEqual([['C191', '0,20', '0,40', '0,60']], records(result['payload'], 'C191'))
        self.assertEqual(2, len(result['trace'][0]['members']))
        self.assertEqual(['1' * 44, '2' * 44], [m['key'] for m in result['trace'][0]['members']])
        self.assertEqual(records(source, 'C140'), records(result['payload'], 'C140'))
        self.assertEqual(records(source, 'C141'), records(result['payload'], 'C141'))
        self.assertEqual([r for r in records(source, 'C100') if r[4] == '55'],
                         [r for r in records(result['payload'], 'C100') if r[4] == '55'])
        self.assertFalse(result['official_pva_replacement'])
        self.assertTrue(result['warnings'])
        self.assertIn('NFCE 100 A 101; QTD 2', result['payload'].decode())

    def test_counters_references_and_closures(self):
        result = export(native_source(), enabled=True)['payload']
        lines = result.decode().splitlines()
        codes = [line.split('|')[1] for line in lines]
        self.assertEqual(len(lines), int(records(result, '9999')[0][1]))
        self.assertEqual(sum(c.startswith('C') for c in codes), int(records(result, 'C990')[0][1]))
        self.assertEqual(sum(c.startswith('0') for c in codes), int(records(result, '0990')[0][1]))
        self.assertEqual(sum(c.startswith('9') and c != '9999' for c in codes), int(records(result, '9990')[0][1]))
        for row in records(result, '9900'):
            self.assertEqual(codes.count(row[1]), int(row[2]))
        self.assertEqual(records(result, '0460')[0][1], records(result, 'C195')[0][1])

    def test_only_outgoing_own_issued_model65_changes(self):
        for direction, issuer in [('0', '0'), ('1', '1'), ('0', '1')]:
            source = native_source(direction=direction, issuer=issuer)
            self.assertEqual(source, export(source, enabled=True)['payload'])

    def test_optional_compact_profile_and_gap_segments(self):
        source = native_source(numbers=(100, 103))
        self.assertEqual(2, len(export(source, enabled=True)['trace']))
        self.assertEqual(1, len(export(source, enabled=True, segment_on_gap=False)['trace']))

    def test_unknown_child_warns_and_exports_original_without_losing_evidence(self):
        source = native_source().replace(b'|C191|0,10|0,20|0,30|', b'|C170|DADO_NAO_AGREGADO|')
        result = export(source, enabled=True)
        self.assertFalse(result['consolidated'])
        self.assertEqual(source, result['payload'])
        self.assertIn('filhos ainda', result['warnings'][0])

    def test_company_period_duplicate_and_non_boolean_options(self):
        source = native_source()
        for payload, changes in [
            (source, {'company_tax_id': 'OUTRAEMPRESA01'}),
            (source, {'competence': '2026-10'}),
            (source, {'enabled': 'true'}),
        ]:
            with self.subTest(changes=changes):
                with self.assertRaises(DomainError):
                    consolidate_native_sped(payload, **({'company_tax_id': TAX_ID,
                        'competence': '2026-11', 'enabled': True} | changes))

    def test_reference_golden_bytes_for_six_synthetic_cases(self):
        from hashlib import sha256
        expected = {
            ('consecutive', False): 'bfc854a4dfdf916aedbb8577dbf020dd4839c43e34f56d0f157b1e4e1838ce70',
            ('consecutive', True): 'bfc854a4dfdf916aedbb8577dbf020dd4839c43e34f56d0f157b1e4e1838ce70',
            ('gap', False): 'c008cb7e58a6889b602eb85727a2d996708a8cad0f947658966d191f71148bb8',
            ('gap', True): 'ff17fb3437cfdab93b84c25abb32918b623fc7c119b37f5fb1e7449592023eea',
            ('multiple', False): 'be2f7bdac67adcf21a78e9cad134eaea33e7a612bfc14c451c448df41b4a8d2a',
            ('multiple', True): '474e3784afc81887979e1f5aecd22b9f77b04742f74abd36766f1d81d3653fac',
        }
        # Recorded by executing buildCompleteNfceSped from the materialized ZIP.
        for name, numbers in [('consecutive', (100, 101)), ('gap', (100, 103)), ('multiple', (100, 101, 103))]:
            for split in (False, True):
                source = native_source(tax_id='12345678000195', numbers=numbers)
                result = consolidate_native_sped(source, company_tax_id='12345678000195',
                    competence='2026-11', enabled=True, segment_on_gap=split)
                self.assertEqual(expected[name, split], sha256(result['payload']).hexdigest())

    def test_native_field_count_preserved_and_current_reader_limit_warned(self):
        from app.importers import parse_file
        result = export(native_source(), enabled=True)
        aggregate = next(r for r in records(result['payload'], 'C100') if r[4] == '65')
        self.assertEqual(30, len(aggregate))  # Record code plus 29 data fields, as in the reference.
        parsed = parse_file('derivado.efd', result['payload'], {'tax_id': TAX_ID})
        self.assertIn('SPED_FIELD_COUNT', {i['code'] for i in parsed['issues']})
        self.assertTrue(any('leitor' in warning for warning in result['warnings']))


class NativeExportApiTests(unittest.TestCase):
    setUp = preview_tests.SpedGeneratorApiTests.setUp
    tearDown = preview_tests.SpedGeneratorApiTests.tearDown
    scope = preview_tests.SpedGeneratorApiTests.scope
    activate = preview_tests.SpedGeneratorApiTests.activate
    create_company = preview_tests.SpedGeneratorApiTests.create_company
    database_hash = preview_tests.SpedGeneratorApiTests.database_hash

    def source_batch(self, raw=None):
        raw = raw if raw is not None else native_source(self.a['tax_id'])
        r = self.client.post(self.scope('/imports/preview'), json={'filename': 'sintetico.efd',
            'period': '2026-11', 'content_base64': base64.b64encode(raw).decode()})
        self.assertEqual(200, r.status_code, r.text)
        return r.json(), raw

    def test_optional_internal_export_never_changes_import_or_movements(self):
        batch, raw = self.source_batch()
        self.assertTrue(batch['can_confirm'], batch['issues'])
        before = self.database_hash()
        body = {'period': '2026-11', 'import_id': batch['id']}
        endpoint = self.scope('/sped-generator/consolidation-export')
        disabled = self.client.post(endpoint, json=body)
        self.assertEqual(200, disabled.status_code, disabled.text)
        self.assertEqual(raw, base64.b64decode(disabled.json()['content_base64']))
        enabled = self.client.post(endpoint, json=body | {'consolidate_nfce': True})
        self.assertEqual(200, enabled.status_code, enabled.text)
        self.assertTrue(enabled.json()['consolidated'])
        self.assertEqual(2, len(enabled.json()['trace'][0]['members']))
        self.assertEqual(before, self.database_hash())
        self.assertEqual([], self.core.documents(self.a['id']))

    def test_export_context_csrf_and_option_guards(self):
        batch, _ = self.source_batch()
        endpoint = self.scope('/sped-generator/consolidation-export')
        body = {'period': '2026-11', 'import_id': batch['id'], 'consolidate_nfce': True}
        self.assertEqual(403, self.client.post(endpoint, json=body, headers={'X-CSRF-Token': ''}).status_code)
        self.assertEqual(400, self.client.post(endpoint, json=body | {'consolidate_nfce': 'true'}).status_code)
        self.assertEqual(409, self.client.post(endpoint, json=body | {'period': '2025-11'}).status_code)
        self.activate(self.b['id'])
        r = self.client.post(self.scope('/sped-generator/consolidation-export', self.b['id']), json=body)
        self.assertEqual(404, r.status_code, r.text)

    def test_fiscal_information_does_not_block_native_export(self):
        raw = native_source(self.a['tax_id']).replace(b'|C141|02|05012027|40,00|', b'|C141|02|05012027|39,00|')
        batch, _ = self.source_batch(raw)
        issue = next(i for i in batch['issues'] if i['code'] == 'SPED_INSTALLMENT_TOTAL_MISMATCH')
        self.assertEqual('info', issue['severity'])
        r = self.client.post(self.scope('/sped-generator/consolidation-export'), json={
            'period': '2026-11', 'import_id': batch['id'], 'consolidate_nfce': True})
        self.assertEqual(200, r.status_code, r.text)
        self.assertTrue(r.json()['consolidated'])
        self.assertIn(b'|C141|02|05012027|39,00|', base64.b64decode(r.json()['content_base64']))

    def test_open_closed_reopened_period_allows_readonly_exports(self):
        batch, _ = self.source_batch()
        endpoint = self.scope('/sped-generator/consolidation-export')
        body = {'period': '2026-11', 'import_id': batch['id']}
        for state in ('open', 'closed', 'reopened'):
            if state != 'open':
                r = self.client.post(self.scope('/periods/' + ('close' if state == 'closed' else 'reopen')),
                    json={'module': 'fiscal', 'period': '2026-11', 'reason': 'Teste sintético de estado da competência'})
                self.assertEqual(200, r.status_code, r.text)
            before = self.database_hash()
            for enabled in (False, True):
                r = self.client.post(endpoint, json=body | {'consolidate_nfce': enabled})
                self.assertEqual(200, r.status_code, r.text)
            self.assertEqual(before, self.database_hash())

    def test_export_requires_both_document_export_and_source_export(self):
        from fastapi.testclient import TestClient
        batch, _ = self.source_batch()
        grants = [{'company_id': self.a['id'], 'routine': 'fiscal.documents', 'action': action, 'effect': 'allow'}
                  for action in ('read', 'export')]
        r = self.client.post('/api/users', json={'username': 'exportador-sped', 'password': 'Exportador-ficticio-123!',
            'role': 'custom', 'company_ids': [self.a['id']], 'permissions': grants})
        self.assertEqual(201, r.status_code, r.text)
        uid = r.json()['id']
        endpoint = self.scope('/sped-generator/consolidation-export')
        body = {'period': '2026-11', 'import_id': batch['id'], 'consolidate_nfce': True}
        with TestClient(self.app) as reader:
            login = reader.post('/api/login', json={'username': 'exportador-sped', 'password': 'Exportador-ficticio-123!'})
            self.assertEqual(200, login.status_code, login.text)
            reader.headers['X-CSRF-Token'] = login.json()['csrf_token']
            self.activate(self.a['id'], client=reader)
            self.assertEqual(403, reader.post(endpoint, json=body).status_code)
            with self.app.state.db.transaction() as conn:
                conn.execute("INSERT INTO user_permissions(user_id,company_id,routine,action,effect) VALUES(?,?,'fiscal.imports','export','allow')", (uid, self.a['id']))
            self.assertEqual(200, reader.post(endpoint, json=body).status_code)
            with self.app.state.db.transaction() as conn:
                conn.execute("UPDATE user_permissions SET effect='deny' WHERE user_id=? AND routine='fiscal.documents' AND action='export'", (uid,))
            self.assertEqual(403, reader.post(endpoint, json=body).status_code)
