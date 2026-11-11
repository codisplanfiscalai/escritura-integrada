"""Synthetic mixed archives: ignored PDFs never bypass archive safeguards."""
import hashlib
import io
from pathlib import Path
import stat
import struct
import unittest
from unittest.mock import patch
import zipfile

from app.importers import parse_file

COMPANY = {"tax_id": "12345678000195"}
PDF = b"%PDF-1.4\n% synthetic accessory, never parsed\n%%EOF"
XML = (Path(__file__).parent / "fixtures/nfe_ficticia.xml").read_bytes()


def zipped(files, compression=zipfile.ZIP_STORED):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, content in files:
            archive.writestr(name, content)
    return output.getvalue()


class ArchivePdfAccessoryTests(unittest.TestCase):
    def parse(self, files, **kwargs):
        return parse_file("lote.zip", zipped(files, **kwargs), COMPANY)

    def assert_blocked(self, result, code):
        self.assertFalse(result["can_confirm"], result)
        self.assertIn(code, {issue["code"] for issue in result["issues"]})

    def test_xml_and_pdf_keep_document_and_trace_ignored_source(self):
        result = self.parse([("nota.xml", XML), ("danfe/NOTA.PDF", PDF)])
        self.assertTrue(result["can_confirm"], result["issues"])
        self.assertEqual(1, len(result["documents"]))
        pdf = result["sources"][-1]
        self.assertEqual("lote.zip!/danfe/NOTA.PDF", pdf["file"])
        self.assertEqual(("pdf", "ignored", len(PDF), hashlib.sha256(PDF).hexdigest()),
                         (pdf["format"], pdf["status"], pdf["size"], pdf["sha256"]))
        self.assertEqual(["ARCHIVE_PDF_IGNORED"], [i["code"] for i in result["issues"] if i["severity"] == "warning" and i["code"].startswith("ARCHIVE_")])
        self.assertEqual([], result["transactions"])

    def test_pdf_only_archive_and_standalone_pdf_are_not_confirmable(self):
        result = self.parse([("nota.pdf", PDF)])
        self.assertFalse(result["can_confirm"])
        self.assertEqual([], result["documents"])
        self.assertEqual("warning", result["issues"][0]["severity"])
        self.assert_blocked(parse_file("nota.pdf", PDF, COMPANY), "FORMAT_UNSUPPORTED")

    def test_many_pdf_accessories_do_not_exhaust_issue_limit(self):
        result = self.parse([("nota.xml", XML)] + [(f"danfe/{i}.pdf", PDF) for i in range(300)])
        self.assertTrue(result["can_confirm"], result["issues"])
        self.assertEqual(300, sum(s.get("status") == "ignored" for s in result["sources"]))
        notices = [i for i in result["issues"] if i["code"] == "ARCHIVE_PDF_IGNORED"]
        self.assertEqual(1, len(notices))
        self.assertIn("300 PDF(s)", notices[0]["message"])

    def test_300_xml_and_pdf_pairs_aggregate_only_generic_reminders(self):
        files = [(name, content) for i in range(300)
                 for name, content in ((f"{i}.xml", XML), (f"{i}.pdf", PDF))]
        result = self.parse(files)
        self.assertTrue(result["can_confirm"], result["issues"])
        self.assertEqual(300, len(result["documents"]))
        for code in ("DOCUMENT_REVIEW_REQUIRED", "HOMOLOGATION_DOCUMENT", "CFOP_CLASSIFICATION_REQUIRED"):
            notices = [i for i in result["issues"] if i["code"] == code]
            self.assertEqual(1, len(notices))
            self.assertEqual(300, notices[0]["count"])
            self.assertEqual(300, len({s["file"] for s in notices[0]["sources"]}))
        self.assertNotIn("ISSUE_LIMIT", {i["code"] for i in result["issues"]})
        result = self.parse(files + [("broken.xml", b"<broken")])
        self.assert_blocked(result, "XML_INVALID")
        error = next(i for i in result["issues"] if i["code"] == "XML_INVALID")
        self.assertEqual("lote.zip!/broken.xml", error["source"]["file"])

    def test_decision_warnings_keep_individual_sources_and_late_errors_block(self):
        import re
        without_protocol = re.sub(br"<protNFe.*?</protNFe>", b"", XML, flags=re.S)
        result = self.parse([("one.xml", without_protocol), ("two.xml", without_protocol)])
        notices = [i for i in result["issues"] if i["code"] == "XML_NO_PROTOCOL"]
        self.assertEqual({"lote.zip!/one.xml", "lote.zip!/two.xml"}, {i["source"]["file"] for i in notices})
        from app.importers import _empty, _issue, MAX_ISSUES
        result = _empty()
        for i in range(MAX_ISSUES):
            _issue(result, "XML_NO_PROTOCOL", "Preserve decision warning", {"file": f"{i}.xml"}, "warning")
        _issue(result, "XML_INVALID", "Late error", {"file": "broken.xml"})
        limit = next(i for i in result["issues"] if i["code"] == "ISSUE_LIMIT")
        self.assertEqual("error", limit["severity"])
        self.assertEqual("broken.xml", limit["source"]["file"])

    def test_nested_zip_accessory_is_ignored_but_depth_is_bounded(self):
        inner = zipped([("nota.xml", XML), ("nota.pdf", PDF)])
        self.assertTrue(self.parse([("inner.zip", inner)])["can_confirm"])
        self.assert_blocked(self.parse([("middle.zip", zipped([("inner.zip", inner)]))]), "ARCHIVE_DEPTH")

    def test_pdf_does_not_hide_bad_xml_unknown_files_or_executables(self):
        for name, content, code in [("bad.xml", b"<broken", "XML_INVALID"),
                                    ("run.exe", b"MZfake", "FORMAT_UNSUPPORTED"),
                                    ("fake.pdf", b"MZfake", "FORMAT_UNSUPPORTED"),
                                    ("other.bin", b"unknown", "FORMAT_UNSUPPORTED")]:
            with self.subTest(name=name):
                result = self.parse([("nota.xml", XML), ("nota.pdf", PDF), (name, content)])
                self.assertFalse(result["can_confirm"])
                self.assert_blocked(result, code)

    def test_ignored_pdf_counts_toward_all_resource_limits(self):
        files = [("nota.xml", XML), ("nota.pdf", PDF)]
        with patch("app.importers.MAX_ARCHIVE_MEMBERS", 1):
            self.assert_blocked(self.parse(files), "ARCHIVE_MEMBERS")
        with patch("app.importers.MAX_EXPANDED_BYTES", len(XML) + len(PDF) - 1):
            self.assert_blocked(self.parse(files), "ARCHIVE_EXPANSION")
        with patch("app.operational_settings.MAX_UPLOAD_BYTES", 100):
            self.assert_blocked(self.parse(files), "FILE_SIZE")
        bomb = PDF + b"A" * 300000
        self.assert_blocked(self.parse([("nota.pdf", bomb)], compression=zipfile.ZIP_DEFLATED), "ARCHIVE_EXPANSION")
        # The compressed root fits; the expanded member exceeds the same limit.
        with patch("app.importers.MAX_FILE_BYTES", 1000):
            self.assert_blocked(self.parse([("nota.pdf", PDF * 100)], compression=zipfile.ZIP_DEFLATED), "ARCHIVE_EXPANSION")

    def test_pdf_unsafe_paths_links_and_duplicate_names_stay_blocked(self):
        for name in ("../nota.pdf", "/nota.pdf", "C:/nota.pdf", "x:nota.pdf"):
            with self.subTest(name=name):
                self.assert_blocked(self.parse([(name, PDF)]), "ARCHIVE_UNSAFE_PATH")
        link = zipfile.ZipInfo("nota.pdf")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.assert_blocked(self.parse([(link, PDF)]), "ARCHIVE_UNSAFE_PATH")
        with self.assertWarns(UserWarning):
            result = self.parse([("nota.pdf", PDF), ("nota.pdf", PDF)])
        self.assert_blocked(result, "ARCHIVE_DUPLICATE_NAME")

    def test_pdf_crc_encryption_and_unsupported_compression_stay_blocked(self):
        raw = zipped([("nota.pdf", PDF)])
        corrupt = raw.replace(PDF, PDF.replace(b"synthetic", b"synthetix"))
        self.assert_blocked(parse_file("crc.zip", corrupt, COMPANY), "ZIP_MEMBER_INVALID")
        for field, value, code in ((8, 99, "ZIP_MEMBER_INVALID"), (6, 1, "ARCHIVE_ENCRYPTED")):
            modified = bytearray(raw)
            central = raw.index(b"PK\x01\x02")
            struct.pack_into("<H", modified, field, value)
            struct.pack_into("<H", modified, central + field + 2, value)
            self.assert_blocked(parse_file("bad.zip", bytes(modified), COMPANY), code)

    def test_seven_zip_accessories_use_same_nonblocking_policy(self):
        import py7zr
        output = io.BytesIO()
        with py7zr.SevenZipFile(output, "w") as archive:
            archive.writestr(XML, "nota.xml")
            archive.writestr(PDF, "nota.pdf")
        result = parse_file("lote.7z", output.getvalue(), COMPANY)
        self.assertTrue(result["can_confirm"], result["issues"])
        self.assertEqual("ignored", result["sources"][-1]["status"])


if __name__ == "__main__":
    unittest.main()
