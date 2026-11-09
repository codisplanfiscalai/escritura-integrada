import unittest
import json
from copy import deepcopy

from app.account_plan_codec import SCHEMA, PlanCodecError, decode_plan, encode_plan


class AccountPlanCodecTests(unittest.TestCase):
    def setUp(self):
        self.properties = {'mask': '#.##.###', 'groups': {'asset': '1', 'liability': '2', 'compensation': '9', 'cost': '5', 'expense': '4', 'revenue': '3'}}
        self.plan = {'schema': SCHEMA, 'properties': self.properties, 'accounts': [
            {'prosoft_code': '00012', 'classifier': '1.01.001', 'name': 'Caixa', 'nature': 'debit', 'analytical': True, 'requires_cost_center': False, 'active': True, 'report_group': 'asset', 'prosoft': {}}]}

    def test_native_roundtrip_preserves_unknown_metadata(self):
        self.plan['future'] = {'unknown': ['ação', 7]}
        self.plan['accounts'][0]['prosoft']['other'] = 'N'
        raw, manifest = encode_plan(self.plan)
        result = decode_plan(raw)
        self.assertEqual(result['accounts'], self.plan['accounts'])
        self.assertEqual(result['future'], self.plan['future'])
        self.assertEqual(manifest['text_changes'], [])

    def test_native_schema_and_types_are_required(self):
        for raw in (b'{}', b'null', b'not json', b'{"schema":"unknown"}'):
            with self.assertRaises(PlanCodecError):
                decode_plan(raw)
        self.plan['accounts'][0]['analytical'] = 'false'
        with self.assertRaises(PlanCodecError):
            encode_plan(self.plan)

    def test_import_positions_and_roundtrip(self):
        raw, _ = encode_plan(self.plan, 'prosoft-import')
        p, c = raw.splitlines()
        self.assertEqual((len(p), len(c)), (103, 204))
        self.assertEqual(p[:30], b'P#.##.###                     ')
        self.assertEqual(c[:21], b'C00012101001000000000')
        self.assertEqual(c[51:57], b'100000')
        result = decode_plan(raw, 'prosoft-import')
        self.assertEqual(result['accounts'][0]['classifier'], '1.01.001')
        self.assertEqual(result['accounts'][0]['prosoft_code'], '00012')
        self.assertEqual(result['accounts'][0]['access_code'], '00012')
        regenerated, _ = encode_plan(result, 'prosoft-import')
        self.assertEqual(regenerated, raw)

    def test_export_roundtrip_with_properties(self):
        raw, _ = encode_plan(self.plan, 'prosoft-export')
        self.assertEqual(len(raw.splitlines()[0]), 204)
        result = decode_plan(raw, 'prosoft-export', {'properties': self.properties})
        self.assertEqual(result['accounts'][0]['name'], 'Caixa')
        again, _ = encode_plan(result, 'prosoft-export')
        self.assertEqual(raw, again)
        with self.assertRaises(PlanCodecError):
            decode_plan(raw, 'prosoft-export')

    def test_zero_ambiguity_requires_explicit_policy(self):
        self.plan['accounts'][0]['classifier'] = '1'
        raw, _ = encode_plan(self.plan, 'prosoft-import')
        with self.assertRaisesRegex(PlanCodecError, 'ambíguos'):
            decode_plan(raw, 'prosoft-import')
        decoded = decode_plan(raw, 'prosoft-import', {'trailing_zero_policy': 'trim_groups'})
        self.assertEqual(decoded['accounts'][0]['classifier'], '1')
        self.assertTrue(decoded['warnings'])
        decoded = decode_plan(raw, 'prosoft-import', {'classification_depths': {'00012': 3}})
        self.assertEqual(decoded['accounts'][0]['classifier'], '1.00.000')

    def test_depth_cannot_discard_meaningful_digits(self):
        raw, _ = encode_plan(self.plan, 'prosoft-import')
        with self.assertRaises(PlanCodecError):
            decode_plan(raw, 'prosoft-import', {'classification_depths': {'00012': 1}})

    def test_reducer_nature(self):
        self.plan['accounts'][0]['nature'] = 'credit'
        raw, _ = encode_plan(self.plan, 'prosoft-import')
        result = decode_plan(raw, 'prosoft-import')
        self.assertEqual(result['accounts'][0]['nature'], 'credit')
        self.assertEqual(result['accounts'][0]['prosoft']['reducer'], '1')

    def test_compensation_requires_nature(self):
        self.plan['accounts'][0]['classifier'] = '9.01.001'
        with self.assertRaisesRegex(PlanCodecError, 'natureza'):
            encode_plan(self.plan, 'prosoft-import')
        self.properties['group_natures'] = {'9': 'debit'}
        raw, _ = encode_plan(self.plan, 'prosoft-import')
        result = decode_plan(raw, 'prosoft-import', {'properties': self.properties})
        self.assertEqual(result['accounts'][0]['nature'], 'debit')

    def test_invalid_noncore_flags_preserved_but_not_reexported(self):
        raw, _ = encode_plan(self.plan, 'prosoft-export')
        raw = raw[:54] + b'N' + raw[55:]
        decoded = decode_plan(raw, 'prosoft-export', {'properties': self.properties})
        self.assertEqual(decoded['accounts'][0]['prosoft']['currency_conversion'], 'N')
        self.assertTrue(decoded['warnings'])
        native, _ = encode_plan(decoded)
        self.assertEqual(decode_plan(native)['accounts'], decoded['accounts'])
        with self.assertRaises(PlanCodecError):
            encode_plan(decoded, 'prosoft-import')

    def test_encoding_and_ascii_changes_are_explicit(self):
        self.plan['accounts'][0]['name'] = 'Aplicações'
        raw, manifest = encode_plan(self.plan, 'prosoft-import')
        self.assertIn(b'Aplicacoes', raw)
        self.assertEqual(manifest['text_changes'][0]['original'], 'Aplicações')
        base, _ = encode_plan(self.plan, 'prosoft-export')
        foreign = base[:20] + 'Aplicações'.encode('cp1252').ljust(30) + base[50:]
        decoded = decode_plan(foreign, 'prosoft-export', {'properties': self.properties})
        self.assertEqual(decoded['encoding'], 'cp1252')
        self.assertEqual(decoded['accounts'][0]['name'], 'Aplicações')
        self.assertTrue(decoded['warnings'])
        with self.assertRaises(PlanCodecError):
            decode_plan(foreign, 'prosoft-export', {'properties': self.properties, 'encoding': 'ascii'})

    def test_width_never_truncates(self):
        for key, value in [('name', 'x' * 31), ('prosoft_code', '123456')]:
            plan = deepcopy(self.plan)
            plan['accounts'][0][key] = value
            with self.assertRaisesRegex(PlanCodecError, 'truncamento'):
                encode_plan(plan, 'prosoft-import')

    def test_special_fields_and_filler_preserved(self):
        self.plan['accounts'][0]['prosoft'] = {'special_classifier': 'ABC123', 'special_name': 'Especial', 'import_filler': ' ' * 47}
        raw, _ = encode_plan(self.plan, 'prosoft-import')
        decoded = decode_plan(raw, 'prosoft-import')
        self.assertEqual(decoded['accounts'][0]['prosoft']['special_name'], 'Especial')
        self.assertEqual(encode_plan(decoded, 'prosoft-import')[0], raw)
        _, manifest = encode_plan(decoded, 'prosoft-export')
        self.assertTrue(manifest['changes'])

    def test_invalid_reducer_requires_explicit_override(self):
        raw, _ = encode_plan(self.plan, 'prosoft-export')
        raw = raw[:52] + b'-' + raw[53:]
        with self.assertRaisesRegex(PlanCodecError, 'redutora'):
            decode_plan(raw, 'prosoft-export', {'properties': self.properties})
        decoded = decode_plan(raw, 'prosoft-export', {'properties': self.properties, 'nature_overrides': {'00012': 'credit'}})
        self.assertEqual(decoded['accounts'][0]['nature'], 'credit')
        self.assertEqual(decoded['accounts'][0]['prosoft']['reducer'], '-')
        with self.assertRaises(PlanCodecError):
            encode_plan(decoded, 'prosoft-import')

    def test_malformed_options_are_codec_errors(self):
        raw, _ = encode_plan(self.plan, 'prosoft-import')
        malformed = [[], [1], 0, 'bad', False,
                     {'properties': []}, {'properties': None},
                     {'properties': {'group_natures': []}},
                     {'properties': {'groups': []}},
                     {'groups': []}, {'classification_depths': []},
                     {'nature_overrides': []}, {'encoding': 123}]
        for options in malformed:
            with self.subTest(options=options):
                with self.assertRaises(PlanCodecError):
                    decode_plan(raw, 'prosoft-import', options)
                with self.assertRaises(PlanCodecError):
                    encode_plan(self.plan, 'prosoft-import', options)

    def test_malformed_native_shapes_are_codec_errors(self):
        for key, value in [('prosoft', []), ('prosoft', None),
                           ('prosoft', {'export_filler': []})]:
            plan = deepcopy(self.plan)
            plan['accounts'][0][key] = value
            with self.assertRaises(PlanCodecError):
                encode_plan(plan)
            with self.assertRaises(PlanCodecError):
                encode_plan(plan, 'prosoft-import')
        for properties in ([], None, {'group_natures': []}, {'groups': []}):
            plan = deepcopy(self.plan)
            plan['properties'] = properties
            with self.assertRaises(PlanCodecError):
                encode_plan(plan)

    def test_normalized_access_codes_must_be_unique(self):
        self.plan['accounts'][0]['prosoft_code'] = '1'
        other = deepcopy(self.plan['accounts'][0])
        other.update(prosoft_code='00001', classifier='1.01.002')
        self.plan['accounts'].append(other)
        for format in ('prosoft-import', 'prosoft-export'):
            with self.assertRaisesRegex(PlanCodecError, 'duplicado após normalização'):
                encode_plan(self.plan, format)

    def test_control_and_emoji_changes_are_reported(self):
        self.plan['accounts'][0]['name'] = 'Caixa\n😀'
        raw, manifest = encode_plan(self.plan, 'prosoft-import')
        self.assertIn(b'Caixa??', raw)
        self.assertEqual(manifest['text_changes'][0]['original'], 'Caixa\n😀')
        self.assertEqual(manifest['text_changes'][0]['replacement'], 'Caixa??')
        self.assertEqual([len(line) for line in raw.splitlines()], [103, 204])
        self.assertTrue(all(32 <= c <= 126 for line in raw.splitlines() for c in line))

    def test_property_filler_width_is_enforced(self):
        self.plan['properties']['filler'] = ' ' * 37
        with self.assertRaisesRegex(PlanCodecError, 'property_filler'):
            encode_plan(self.plan, 'prosoft-import')
        self.plan['properties']['filler'] = 'X' + ' ' * 35
        with self.assertRaisesRegex(PlanCodecError, 'brancos'):
            encode_plan(self.plan, 'prosoft-import')

    def test_native_warnings_must_be_a_list(self):
        for warnings in (None, {}, 'warning', False, 0):
            plan = deepcopy(self.plan)
            plan['warnings'] = warnings
            with self.subTest(warnings=warnings):
                with self.assertRaisesRegex(PlanCodecError, 'warnings'):
                    decode_plan(json.dumps(plan))
                with self.assertRaisesRegex(PlanCodecError, 'warnings'):
                    encode_plan(plan)
        self.plan['warnings'] = ['Message', {'code': 'review', 'message': 'Check'}]
        raw, _ = encode_plan(self.plan)
        self.assertEqual(decode_plan(raw)['warnings'], self.plan['warnings'])

    def test_nonblank_fillers_preserved_but_block_prosoft_output(self):
        for format in ('prosoft-import', 'prosoft-export'):
            raw, _ = encode_plan(self.plan, format)
            lines = raw.splitlines()
            for row, offset, key in ([(0, 67, 'filler'), (1, 157, 'import_filler')] if format == 'prosoft-import' else [(0, 56, 'export_filler')]):
                changed = list(lines)
                changed[row] = changed[row][:offset] + b'X' + changed[row][offset + 1:]
                decoded = decode_plan(b'\r\n'.join(changed), format, {'properties': self.properties})
                self.assertTrue(any('filler' in w for w in decoded['warnings']))
                value = decoded['properties'][key] if key == 'filler' else decoded['accounts'][0]['prosoft'][key]
                self.assertTrue(value.startswith('X'))
                native, _ = encode_plan(decoded)
                self.assertEqual(decode_plan(native)['accounts'], decoded['accounts'])
                for output in ('prosoft-import', 'prosoft-export'):
                    with self.assertRaisesRegex(PlanCodecError, 'brancos'):
                        encode_plan(decoded, output)

    def test_conflicting_flags_rejected(self):
        self.plan['accounts'][0]['prosoft'] = {'entries': '0'}
        with self.assertRaisesRegex(PlanCodecError, 'conflitam'):
            encode_plan(self.plan, 'prosoft-import')

    def test_record_lengths_types_and_empty(self):
        raw, _ = encode_plan(self.plan, 'prosoft-import')
        for data in (b'', raw[:-5], raw.replace(b'\r\nC', b'\r\nX'), raw.splitlines()[0]):
            with self.assertRaises(PlanCodecError):
                decode_plan(data, 'prosoft-import')
        with self.assertRaises(PlanCodecError):
            decode_plan(raw, 'prosoft-export')


if __name__ == '__main__':
    unittest.main()
