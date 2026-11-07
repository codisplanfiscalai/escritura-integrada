"""Casos sintéticos de leitura, limites e isolamento; não são homologação fiscal."""
import hashlib
import io
import stat
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.importers import parse_file

FIXTURES = Path(__file__).parent / "fixtures"
ALFA = {"tax_id": "12345678000195"}
BETA = {"tax_id": "87654321000198"}
GAMA = {"tax_id": "11222333000181"}


def fixture(name):
    return (FIXTURES / name).read_bytes()


def codes(result):
    return {x["code"] for x in result["issues"]}


def zipped(files, compression=zipfile.ZIP_DEFLATED):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for name, content in files:
            archive.writestr(name, content)
    return buffer.getvalue()


class FiscalReaderTests(unittest.TestCase):
    def test_nfe_preserves_source_and_does_not_convert_supplier_cfop(self):
        data = fixture("nfe_ficticia.xml")
        result = parse_file("nfe.xml", data, ALFA)
        self.assertTrue(result["can_confirm"])
        doc = result["documents"][0]
        self.assertEqual((doc["direction"], doc["number"], doc["total"]), ("incoming", "42", "100.00"))
        self.assertEqual(doc["partner_tax_id"], BETA["tax_id"])
        self.assertEqual(doc["cfop"], "")
        self.assertEqual(doc["items"][0]["source_cfop"], "5102")
        self.assertEqual(doc["items"][0]["cfop"], "")
        self.assertEqual(doc["source_hash"], hashlib.sha256(data).hexdigest())
        self.assertFalse(doc["signature_verified"])
        self.assertFalse(doc["tax_rules_applied"])
        self.assertTrue(doc["posting_date_proposed"])
        self.assertEqual(doc["taxes"]["ICMSTot/vICMS"], "18.00")
        self.assertEqual(doc["invoices"][0]["due_date"], "2026-12-05")
        self.assertFalse(doc["invoices"][0]["financial_posting_created"])

    def test_nfe_issuer_outgoing_and_self_issued_incoming(self):
        data = fixture("nfe_ficticia.xml")
        out = parse_file("nfe.xml", data, BETA)["documents"][0]
        self.assertEqual((out["direction"], out["cfop"]), ("outgoing", "5102"))
        entry = parse_file("nfe.xml", data.replace(b"<tpNF>1</tpNF>", b"<tpNF>0</tpNF>"), BETA)
        self.assertEqual(entry["documents"][0]["direction"], "incoming")

    def test_xml_company_context_is_required_and_enforced(self):
        data = fixture("nfe_ficticia.xml")
        for company, code in ((GAMA, "COMPANY_MISMATCH"), ({}, "COMPANY_TAX_ID_REQUIRED")):
            result = parse_file("nfe.xml", data, company)
            self.assertFalse(result["can_confirm"])
            self.assertEqual(result["documents"], [])
            self.assertIn(code, codes(result))

    def test_nfce_without_recipient_can_be_read_for_issuer(self):
        data = fixture("nfe_ficticia.xml").replace(b"<mod>55</mod>", b"<mod>65</mod>")
        start, end = data.index(b"<dest>"), data.index(b"</dest>") + len(b"</dest>")
        result = parse_file("nfce.xml", data[:start] + data[end:], BETA)
        self.assertTrue(result["can_confirm"])
        self.assertEqual(result["documents"][0]["partner_name"], "Consumidor não identificado")

    def test_cte_uses_taker_and_service_total_not_cargo_or_receivable(self):
        data = fixture("cte_ficticio.xml")
        result = parse_file("cte.xml", data, ALFA)
        self.assertTrue(result["can_confirm"])
        doc = result["documents"][0]
        self.assertEqual((doc["direction"], doc["document_type"], doc["total"]), ("incoming", "transport", "125.50"))
        self.assertEqual(doc["transport"]["taker_group"], "rem")
        self.assertEqual(doc["transport"]["declared_receivable"], "115.50")
        recipient = parse_file("cte.xml", data, GAMA)
        self.assertIn("CTE_COMPANY_NOT_TAKER", codes(recipient))
        self.assertFalse(recipient["can_confirm"])

    def test_cte_toma4_has_own_party(self):
        data = fixture("cte_ficticio.xml").replace(b"<toma3><toma>0</toma></toma3>", b"<toma4><toma>4</toma><CNPJ>11222333000181</CNPJ><xNome>TOMADOR FICTICIO GAMA</xNome></toma4>")
        self.assertTrue(parse_file("cte.xml", data, GAMA)["can_confirm"])
        self.assertIn("CTE_COMPANY_NOT_TAKER", codes(parse_file("cte.xml", data, ALFA)))

    def test_xml_protocol_and_namespace_are_not_trusted_blindly(self):
        data = fixture("nfe_ficticia.xml")
        mismatch = data.replace(b"<chNFe>35261187654321000198550010000000421000000420", b"<chNFe>35261187654321000198550010000000421000000421")
        self.assertIn("XML_PROTOCOL_KEY_MISMATCH", codes(parse_file("nfe.xml", mismatch, ALFA)))
        wrong_ns = data.replace(b"http://www.portalfiscal.inf.br/nfe", b"urn:unknown")
        self.assertIn("XML_NAMESPACE", codes(parse_file("nfe.xml", wrong_ns, ALFA)))

    def test_xml_external_and_internal_entities_blocked_in_utf8_and_utf16(self):
        payloads = [
            '<!DOCTYPE NFe [<!ENTITY x SYSTEM "file:///etc/passwd">]><NFe>&x;</NFe>',
            '<!DOCTYPE NFe [<!ENTITY x "x"><!ENTITY y "&x;&x;&x;">]><NFe>&y;</NFe>',
        ]
        for payload in payloads:
            for encoding in ("utf-8", "utf-16", "utf-32"):
                result = parse_file("evil.xml", payload.encode(encoding), ALFA)
                self.assertIn("XML_DTD_FORBIDDEN", codes(result))
                self.assertFalse(result["can_confirm"])

    def test_unknown_xml_layout_version_and_deep_tree(self):
        data = fixture("nfe_ficticia.xml").replace(b'versao="4.00"', b'versao="9.99"')
        self.assertIn("XML_VERSION_UNSUPPORTED", codes(parse_file("unknown.xml", data, ALFA)))
        self.assertIn("XML_LAYOUT_UNSUPPORTED", codes(parse_file("event.xml", b"<evento/>", ALFA)))
        self.assertIn("XML_LIMIT", codes(parse_file("deep.xml", b"<x>" * 110 + b"</x>" * 110, ALFA)))

    def test_sped_exact_fields_participant_item_analytic_and_installments(self):
        result = parse_file("efd.txt", fixture("sped_ficticio_020.txt"), ALFA)
        self.assertTrue(result["can_confirm"])
        self.assertTrue(result["partial"])
        doc = result["documents"][0]
        self.assertEqual((doc["direction"], doc["model"], doc["total"], doc["cfop"]), ("incoming", "01", "100.00", "1102"))
        self.assertEqual(doc["posting_date"], "2026-11-06")
        self.assertEqual(doc["partner_name"], "FORNECEDOR FICTICIO BETA")
        self.assertEqual(len(doc["items"]), 1)
        self.assertEqual(len(doc["analytics"]), 1)
        self.assertEqual(doc["items"][0]["ncm"], "99999999")
        self.assertEqual(doc["items"][0]["taxes"]["VL_COFINS"], "7.60")
        self.assertEqual(doc["items"][0]["raw_fields"]["COD_CTA"], "CONTA-FICTICIA")
        self.assertEqual(doc["analytics"][0]["rate"], "18.00")
        invoice = doc["invoices"][0]
        self.assertEqual(invoice["number"], "FICT-42")
        self.assertEqual([x["amount"] for x in invoice["installments"]], ["60.00", "40.00"])
        self.assertEqual(invoice["installments"][1]["due_date"], "2027-01-05")
        self.assertFalse(invoice["financial_posting_created"])
        self.assertEqual(result["transactions"], [])
        self.assertEqual(doc["source"]["line"], 8)

    def test_sped_company_layout_missing_parent_and_field_count(self):
        data = fixture("sped_ficticio_020.txt")
        self.assertIn("COMPANY_MISMATCH", codes(parse_file("efd.txt", data, BETA)))
        self.assertIn("SPED_LAYOUT_UNSUPPORTED", codes(parse_file("efd.txt", data.replace(b"|020|", b"|999|", 1), ALFA)))
        short = data.replace(b"|C141|02|05012027|40,00|", b"|C141|02|05012027|")
        self.assertIn("SPED_FIELD_COUNT", codes(parse_file("efd.txt", short, ALFA)))
        orphan = b"\n".join(line for line in data.splitlines() if not line.startswith(b"|C140|"))
        self.assertIn("SPED_ORPHAN_INSTALLMENT", codes(parse_file("efd.txt", orphan, ALFA)))

    def test_sped_unhandled_records_and_divergences_remain_visible(self):
        data = fixture("sped_ficticio_020.txt")
        data = data.replace(b"|C990|", b"|C197|AJUSTE-TESTE|0|0|0|\n|C990|")
        result = parse_file("efd.txt", data, ALFA)
        self.assertIn("SPED_UNPROCESSED_RECORDS", codes(result))
        self.assertEqual(result["unprocessed_records"]["C197"], 1)
        self.assertEqual(result["documents"][0]["unprocessed_records"][0]["record"], "C197")
        bad_count = fixture("sped_ficticio_020.txt").replace(b"|FICT-42|2|", b"|FICT-42|3|")
        self.assertIn("SPED_INSTALLMENT_COUNT", codes(parse_file("efd.txt", bad_count, ALFA)))


class BankReaderTests(unittest.TestCase):
    def test_csv_iso_decimal_and_stable_record_identity(self):
        data = fixture("extrato_ficticio.csv")
        result = parse_file("extrato.csv", data, ALFA)
        self.assertTrue(result["can_confirm"])
        self.assertEqual([x["amount"] for x in result["transactions"]], ["100.00", "-25.50"])
        self.assertEqual(result["transactions"][0]["date"], "2026-11-05")
        self.assertEqual(result["transactions"], parse_file("extrato.csv", data, ALFA)["transactions"])
        duplicate_rows = b"data;valor;historico;documento\n2026-11-05;100.00;Teste;1\n2026-11-05;100.00;Teste;1\n"
        items = parse_file("extrato.csv", duplicate_rows, ALFA)["transactions"]
        self.assertEqual(len(items), 2)
        self.assertNotEqual(items[0]["external_id"], items[1]["external_id"])

    def test_csv_ambiguous_date_and_decimal_require_options(self):
        data = b"data;valor;historico;documento\n05/11/2026;1.234,56;Teste;1\n"
        result = parse_file("extrato.csv", data, ALFA)
        self.assertIn("DATE_FORMAT_REQUIRED", codes(result))
        explicit = {**ALFA, "import_options": {"date_format": "DD/MM/YYYY", "decimal_separator": ",", "thousands_separator": "."}}
        result = parse_file("extrato.csv", data, explicit)
        self.assertTrue(result["can_confirm"])
        self.assertEqual((result["transactions"][0]["date"], result["transactions"][0]["amount"]), ("2026-11-05", "1234.56"))

    def test_csv_invalid_numbers_never_float_or_silently_round(self):
        for amount in ("NaN", "Infinity", "1e9", "1,23", "12.345", "12.00-", "1_000.00"):
            data = f"data;valor;historico;documento\n2026-11-05;{amount};Teste;1\n".encode()
            result = parse_file("extrato.csv", data, ALFA)
            self.assertFalse(result["can_confirm"], amount)
            self.assertEqual(result["transactions"], [], amount)

    def test_csv_encoding_columns_and_quotes_are_explicit(self):
        data = "data;valor;historico;documento\n2026-11-05;10.00;Serviço;1\n".encode("cp1252")
        self.assertIn("ENCODING_REQUIRED", codes(parse_file("bank.csv", data, ALFA)))
        self.assertTrue(parse_file("bank.csv", data, {**ALFA, "import_options": {"encoding": "windows-1252"}})["can_confirm"])
        duplicate = b"data;valor;historico;documento;valor\n2026-11-05;10.00;X;1;20.00\n"
        self.assertIn("BANK_DUPLICATE_HEADER", codes(parse_file("bank.csv", duplicate, ALFA)))
        malformed = b'data;valor;historico;documento\n2026-11-05;10.00;"unclosed;1\n'
        self.assertFalse(parse_file("bank.csv", malformed, ALFA)["can_confirm"])

    def test_csv_custom_mapping_and_fixed_txt(self):
        data = b"Dia|Montante|Texto|Ref\n2026-11-05|-10.00|Teste|A\n"
        options = {"bank_columns": {"date": "Dia", "amount": "Montante", "description": "Texto", "reference": "Ref"}, "delimiter": "|"}
        self.assertTrue(parse_file("bank.txt", data, {**ALFA, "import_options": options})["can_confirm"])
        options = {"bank_layout": "fixed", "bank_columns": {"date": {"start": 0, "length": 10}, "amount": {"start": 10, "length": 8}, "description": {"start": 18, "length": 8}, "reference": {"start": 26, "length": 3}}}
        fixed = b"2026-11-05  -10.00Teste   A01\n"
        result = parse_file("fixed.txt", fixed, {**ALFA, "import_options": options})
        self.assertTrue(result["can_confirm"], result)
        self.assertEqual(result["transactions"][0]["reference"], "A01")
        self.assertIn("BANK_LAYOUT_REQUIRED", codes(parse_file("fixed.txt", fixed, ALFA)))

    def test_ui_option_aliases_are_supported_without_automatic_guessing(self):
        data = b"data\tvalor\thistorico\tdocumento\n05/11/2026\t100,50\tTeste\tA01\n"
        options = {"date_format": "DMY", "encoding": "auto", "delimiter": "TAB", "decimal_separator": ","}
        result = parse_file("bank.txt", data, {**ALFA, "import_options": options})
        self.assertTrue(result["can_confirm"], result)
        self.assertEqual(result["transactions"][0]["date"], "2026-11-05")
        self.assertEqual(result["transactions"][0]["amount"], "100.50")
        malformed = parse_file("bank.csv", fixture("extrato_ficticio.csv"), {**ALFA, "import_options": {"date_format": {"unexpected": "object"}}})
        self.assertIn("INVALID_OPTIONS", codes(malformed))

    def test_ofx_xml_and_sgml_have_equivalent_transaction_values(self):
        sgml = parse_file("bank.ofx", fixture("extrato_ficticio.ofx"), ALFA)
        xml = parse_file("bank.ofx", fixture("extrato_ficticio_xml.ofx"), ALFA)
        self.assertTrue(sgml["can_confirm"])
        self.assertTrue(xml["can_confirm"])
        self.assertEqual(sgml["format"], "ofx_sgml")
        self.assertEqual(xml["format"], "ofx_xml")
        fields = ("date", "amount", "reference", "external_id", "description", "bank_account_hint")
        self.assertEqual([{k: x[k] for k in fields} for x in sgml["transactions"]], [{k: x[k] for k in fields} for x in xml["transactions"]])
        self.assertEqual(sgml["bank_account_hint"], "000/0001/CONTA-FICTICIA")

    def test_ofc_uses_numeric_type_chknum_and_own_decimal_syntax(self):
        data = fixture("extrato_ficticio.ofc")
        result = parse_file("bank.ofc", data, ALFA)
        self.assertTrue(result["can_confirm"])
        self.assertEqual([x["amount"] for x in result["transactions"]], ["100.00", "-25.50"])
        self.assertEqual(result["transactions"][0]["reference"], "OFC-001")
        self.assertEqual(result["transactions"][1]["transaction_type"], "1")
        wrong = data.replace(b"<TRNTYPE>0", b"<TRNTYPE>CREDIT")
        self.assertIn("OFC_TRANSACTION_TYPE", codes(parse_file("bank.ofc", wrong, ALFA)))
        self.assertIn("BANK_ROOT", codes(parse_file("bank.ofx", data, ALFA)))

    def test_ofx_duplicate_id_missing_id_pending_and_truncated_are_blocked(self):
        data = fixture("extrato_ficticio.ofx")
        cases = [
            (data.replace(b"FICT-OFX-002", b"FICT-OFX-001"), "BANK_DUPLICATE_ID"),
            (data.replace(b"<FITID>FICT-OFX-001", b""), "OFX_FITID_REQUIRED"),
            (data.replace(b"<FITID>FICT-OFX-001", b"<CORRECTFITID>OLD<FITID>FICT-OFX-001"), "BANK_OPERATION_UNSUPPORTED"),
            (data.replace(b"</STMTTRN>", b"", 1), "BANK_TRANSACTION_TRUNCATED"),
            (data.replace(b"<TRNAMT>100.00", b"<TRNAMT>100.00<TRNAMT>999.00"), "BANK_DUPLICATE_TAG"),
        ]
        for payload, code in cases:
            result = parse_file("bank.ofx", payload, ALFA)
            self.assertFalse(result["can_confirm"], code)
            self.assertIn(code, codes(result))

    def test_bank_xml_entities_and_nonzero_status(self):
        data = fixture("extrato_ficticio_xml.ofx")
        payload = data.replace(b"<OFX>", b'<!DOCTYPE OFX [<!ENTITY x SYSTEM "https://example.invalid/x">]><OFX>')
        self.assertIn("XML_DTD_FORBIDDEN", codes(parse_file("bank.ofx", payload, ALFA)))
        self.assertIn("OFX_STATUS_ERROR", codes(parse_file("bank.ofx", data.replace(b"<CODE>0</CODE>", b"<CODE>2000</CODE>"), ALFA)))
        foreign = data.replace(b"<CURDEF>BRL</CURDEF>", b"<CURDEF>USD</CURDEF>")
        self.assertIn("CURRENCY_UNSUPPORTED", codes(parse_file("bank.ofx", foreign, ALFA)))

    def test_qif_date_order_is_not_guessed(self):
        result = parse_file("bank.qif", fixture("extrato_ficticio.qif"), ALFA)
        self.assertTrue(result["can_confirm"])
        self.assertEqual([x["amount"] for x in result["transactions"]], ["100.00", "-25.50"])
        local = b"!Type:Bank\nD05/11/2026\nT-1,234.56\nPTeste\n^\n"
        self.assertIn("DATE_FORMAT_REQUIRED", codes(parse_file("bank.qif", local, ALFA)))
        explicit = {**ALFA, "import_options": {"date_format": "MM/DD/YYYY"}}
        parsed = parse_file("bank.qif", local, explicit)
        self.assertEqual(parsed["transactions"][0]["date"], "2026-05-11")
        self.assertEqual(parsed["transactions"][0]["amount"], "-1234.56")

    def test_qif_splits_are_not_duplicated_and_truncation_not_ignored(self):
        data = b"!Type:Bank\nD2026-11-05\nT-100.00\nPTeste\nSGrupo1\n$-40.00\nSGrupo2\n$-60.00\n^\n"
        result = parse_file("bank.qif", data, ALFA)
        self.assertEqual(len(result["transactions"]), 1)
        self.assertEqual(result["transactions"][0]["amount"], "-100.00")
        self.assertIn("QIF_SPLITS_REVIEW", codes(result))
        self.assertIn("QIF_TERMINATOR", codes(parse_file("bank.qif", data.rstrip(b"^\n"), ALFA)))
        self.assertIn("QIF_TYPE_UNSUPPORTED", codes(parse_file("bank.qif", data.replace(b"!Type:Bank", b"!Type:Invst"), ALFA)))
        self.assertIn("QIF_ACCOUNTS_UNSUPPORTED", codes(parse_file("bank.qif", b"!Account\nNConta\n^\n" + data, ALFA)))


class ArchiveSafetyTests(unittest.TestCase):
    def test_zip_aggregates_sources_and_one_inner_zip(self):
        inner = zipped([("extrato.csv", fixture("extrato_ficticio.csv"))])
        data = zipped([("fiscal/nfe.xml", fixture("nfe_ficticia.xml")), ("extratos.zip", inner)])
        result = parse_file("lote.zip", data, ALFA)
        self.assertTrue(result["can_confirm"])
        self.assertEqual((len(result["documents"]), len(result["transactions"]), len(result["sources"])), (1, 2, 4))
        self.assertEqual(result["transactions"][0]["source"]["file"], "lote.zip!/extratos.zip!/extrato.csv")

    def test_zip_rejects_third_archive_layer(self):
        inner = zipped([("bank.csv", fixture("extrato_ficticio.csv"))])
        middle = zipped([("inner.zip", inner)])
        result = parse_file("outer.zip", zipped([("middle.zip", middle)]), ALFA)
        self.assertIn("ARCHIVE_DEPTH", codes(result))
        self.assertFalse(result["can_confirm"])

    def test_zip_traversal_absolute_windows_path_and_symlink_are_refused(self):
        for name in ("../escape.xml", "/tmp/escape.xml", "C:\\escape.xml", "folder/../../escape.xml", "file.xml:stream"):
            result = parse_file("unsafe.zip", zipped([(name, fixture("nfe_ficticia.xml"))]), ALFA)
            self.assertIn("ARCHIVE_UNSAFE_PATH", codes(result), name)
        link = zipfile.ZipInfo("link.xml")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.assertIn("ARCHIVE_UNSAFE_PATH", codes(parse_file("unsafe.zip", zipped([(link, b"/etc/passwd")]), ALFA)))

    def test_zip_bomb_limits_count_size_and_crc(self):
        bomb = zipped([("bomb.txt", b"A" * 300000)])
        self.assertIn("ARCHIVE_EXPANSION", codes(parse_file("bomb.zip", bomb, ALFA)))
        small = zipped([("1.csv", fixture("extrato_ficticio.csv")), ("2.csv", fixture("extrato_ficticio.csv"))])
        with patch("app.importers.MAX_ARCHIVE_MEMBERS", 1):
            self.assertIn("ARCHIVE_MEMBERS", codes(parse_file("count.zip", small, ALFA)))
        with patch("app.importers.MAX_EXPANDED_BYTES", 10):
            self.assertIn("ARCHIVE_EXPANSION", codes(parse_file("size.zip", small, ALFA)))
        self.assertIn("ZIP_INVALID", codes(parse_file("broken.zip", b"PK\x03\x04broken", ALFA)))
        stored = bytearray(zipped([("bank.csv", fixture("extrato_ficticio.csv"))], zipfile.ZIP_STORED))
        offset = stored.index(b"data;valor;historico;documento")
        stored[offset] = ord("X")
        self.assertIn("ZIP_MEMBER_INVALID", codes(parse_file("crc.zip", bytes(stored), ALFA)))

    def test_archive_child_error_blocks_whole_confirmation(self):
        data = zipped([("bank.csv", fixture("extrato_ficticio.csv")), ("bad.xml", b'<!DOCTYPE x [<!ENTITY x "boom">]><x/>')])
        result = parse_file("mixed.zip", data, ALFA)
        self.assertEqual(len(result["transactions"]), 2)
        self.assertIn("XML_DTD_FORBIDDEN", codes(result))
        self.assertFalse(result["can_confirm"])

    def test_zip_cannot_merge_different_bank_accounts_into_one_confirmation(self):
        account_one = fixture("extrato_ficticio.ofx")
        account_two = account_one.replace(b"CONTA-FICTICIA", b"OUTRA-CONTA-FICTICIA")
        result = parse_file("two-accounts.zip", zipped([("one.ofx", account_one), ("two.ofx", account_two)]), ALFA)
        self.assertEqual(len(result["bank_account_hints"]), 2)
        self.assertIsNone(result["bank_account_hint"])
        self.assertIn("MULTIPLE_BANK_ACCOUNTS", codes(result))
        self.assertFalse(result["can_confirm"])

    def test_unsupported_archives_and_executables_are_explicit(self):
        for name, data, code in (("legacy.rar", b"Rar!fake", "ARCHIVE_FORMAT_UNSUPPORTED"), ("legacy.7z", b"7z\xbc\xaf\x27\x1cfake", "ARCHIVE_FORMAT_UNSUPPORTED"), ("program.exe", b"MZfake", "FORMAT_UNSUPPORTED")):
            result = parse_file(name, data, ALFA)
            self.assertIn(code, codes(result))
            self.assertFalse(result["can_confirm"])


if __name__ == "__main__":
    unittest.main()
