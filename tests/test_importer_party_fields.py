"""Preserve declared master-data fields without creating inferred values."""
from pathlib import Path
import unittest
from xml.etree import ElementTree as ET

from app.importers import _party, parse_file

XML = (Path(__file__).parent / 'fixtures/nfe_ficticia.xml').read_bytes()
COMPANY = {'tax_id': '12345678000195'}


class PartyFieldTests(unittest.TestCase):
    def test_nfce_nfe_parties_keep_declared_master_fields(self):
        extra = b'<xFant>Fantasia</xFant><IE>001234</IE><IM>00567</IM><email>synthetic@example.test</email><enderEmit><xLgr>Rua Teste</xLgr><nro>10</nro><xBairro>Centro</xBairro><xMun>Sao Paulo</xMun><UF>SP</UF><CEP>01001000</CEP><cMun>3550308</cMun><fone>1133334444</fone></enderEmit>'
        raw = XML.replace(b'</emit>', extra + b'</emit>')
        result = parse_file('nota.xml', raw, COMPANY)
        self.assertTrue(result['can_confirm'], result['issues'])
        issuer = result['documents'][0]['issuer']
        expected = {'trade_name': 'Fantasia', 'ie': '001234', 'im': '00567', 'email': 'synthetic@example.test',
                    'address': 'Rua Teste', 'number': '10', 'district': 'Centro', 'city': 'Sao Paulo',
                    'state': 'SP', 'postal_code': '01001000', 'ibge': '3550308', 'phone': '1133334444'}
        for key, value in expected.items():
            self.assertEqual(value, issuer[key])
        recipient = result['documents'][0]['recipient']
        self.assertEqual({'name', 'tax_id', 'foreign_id'}, set(recipient))
        self.assertEqual({'name': '', 'tax_id': '', 'foreign_id': ''}, _party(None))

    def test_cte_address_groups_keep_their_own_fields(self):
        for role, group in [('emit', 'enderEmit'), ('dest', 'enderDest'), ('rem', 'enderReme'),
                            ('exped', 'enderExped'), ('receb', 'enderReceb'), ('toma4', 'enderToma')]:
            with self.subTest(role=role):
                element = ET.fromstring(f'<{role} xmlns="http://www.portalfiscal.inf.br/cte"><xNome>Teste</xNome><{group}><xLgr>Rua {role}</xLgr><CEP>01001000</CEP></{group}></{role}>')
                party = _party(element)
                self.assertEqual(f'Rua {role}', party['address'])
                self.assertEqual('01001000', party['postal_code'])
                self.assertNotIn('number', party)

    def test_nfe_carrier_does_not_replace_items_or_source_cfops(self):
        transport = b'<transp><transporta><CNPJ>11222333000181</CNPJ><xNome>Transportadora teste</xNome><IE>00123</IE><xEnder>Rua Teste 42</xEnder><xMun>Campinas</xMun><UF>SP</UF></transporta></transp>'
        raw = XML.replace(b'</infNFe>', transport + b'</infNFe>')
        doc = parse_file('nota.xml', raw, COMPANY)['documents'][0]
        self.assertEqual(1, len(doc['items']))
        self.assertEqual(['5102'], doc['source_cfops'])
        self.assertEqual('', doc['cfop'])
        carrier = doc['transport']['carrier']
        self.assertEqual('11222333000181', carrier['tax_id'])
        self.assertEqual('Rua Teste 42', carrier['address'])
        self.assertEqual('00123', carrier['ie'])
        self.assertNotIn('number', carrier)
        self.assertNotIn('transport', parse_file('nota.xml', XML, COMPANY)['documents'][0])

    def test_declared_barcode_preserved_but_sem_gtin_is_not_identifier(self):
        for value in ('07891234567895', 'SEM GTIN', ''):
            with self.subTest(value=value):
                raw = XML.replace(b'</prod>', f'<cEAN>{value}</cEAN></prod>'.encode())
                result = parse_file('nota.xml', raw, COMPANY)
                self.assertTrue(result['can_confirm'], result['issues'])
                item = result['documents'][0]['items'][0]
                self.assertEqual(value, item['declared_product_fields']['cEAN'])
                if value and value != 'SEM GTIN':
                    self.assertEqual(value, item['barcode'])
                else:
                    self.assertNotIn('barcode', item)


if __name__ == '__main__':
    unittest.main()
