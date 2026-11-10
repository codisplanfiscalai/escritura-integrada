"""Declared XML dates and NFC-e consumer identity remain independent."""
import re
import unittest
from pathlib import Path

from app.importers import parse_file

XML = (Path(__file__).parent / 'fixtures/nfe_ficticia.xml').read_bytes()
COMPANY = {'tax_id': '12345678000195'}


class MovementDateTests(unittest.TestCase):
    def test_declared_movement_date_does_not_change_posting_date(self):
        for tag, value in [('dhSaiEnt', '2026-11-06T23:30:00-03:00'), ('dSaiEnt', '2026-11-06')]:
            with self.subTest(tag=tag):
                field = f'<{tag}>{value}</{tag}>'.encode()
                xml = XML.replace(b'</ide>', field + b'</ide>')
                result = parse_file('nota.xml', xml, COMPANY)
                self.assertTrue(result['can_confirm'], result['issues'])
                doc = result['documents'][0]
                self.assertEqual('2026-11-06', doc['movement_date'])
                self.assertEqual('2026-11-05', doc['issue_date'])
                self.assertEqual(doc['issue_date'], doc['posting_date'])
                explicit = parse_file('nota.xml', xml, {**COMPANY, 'import_options': {'posting_date': '2026-11-07'}})['documents'][0]
                self.assertEqual('2026-11-07', explicit['posting_date'])
                self.assertEqual('2026-11-06', explicit['movement_date'])

    def test_omitted_date_is_not_fabricated_and_invalid_date_is_rejected(self):
        self.assertNotIn('movement_date', parse_file('nota.xml', XML, COMPANY)['documents'][0])
        for value in ('2026-02-30', 'not-a-date'):
            xml = XML.replace(b'</ide>', f'<dSaiEnt>{value}</dSaiEnt></ide>'.encode())
            result = parse_file('nota.xml', xml, COMPANY)
            self.assertFalse(result['can_confirm'])
            self.assertIn('INVALID_DATE', {i['code'] for i in result['issues']})

    def test_nfce_without_recipient_is_valid_for_issuer_and_other_company_is_rejected(self):
        xml = re.sub(br'<dest>.*?</dest>', b'', XML, flags=re.S).replace(b'<mod>55</mod>', b'<mod>65</mod>')
        xml = xml.replace(b'35261187654321000198550010000000421000000420', b'35261187654321000198650010000000421000000420')
        result = parse_file('nfce.xml', xml, {'tax_id': '87654321000198'})
        self.assertTrue(result['can_confirm'], result['issues'])
        doc = result['documents'][0]
        self.assertEqual(('65', 'outgoing', 'Consumidor não identificado', ''),
                         (doc['model'], doc['direction'], doc['partner_name'], doc['partner_tax_id']))
        self.assertEqual('', doc['recipient']['tax_id'])
        wrong = parse_file('nfce.xml', xml, COMPANY)
        self.assertFalse(wrong['can_confirm'])
        self.assertIn('COMPANY_MISMATCH', {i['code'] for i in wrong['issues']})


if __name__ == '__main__':
    unittest.main()
