"""Casos originais Auditor Fiscal 1.2.2 (MIT); caminhos adaptados ao Escritura."""
from app.auditor_engine.document_duplicates import document_identity, duplicate_finding


def _document(access_key: str | None, xml_hash: str | None, source: str) -> dict:
    return {
        "document_ref": access_key or xml_hash or source,
        "access_key": access_key,
        "source_file_id": source,
        "normalized": {"xml_sha256": xml_hash},
    }


def test_exact_duplicate_is_a_traceable_medium_finding():
    canonical = _document("1" * 44, "a" * 64, "source-a")
    duplicate = _document("1" * 44, "a" * 64, "source-b")
    identity = document_identity(canonical)

    result = duplicate_finding(canonical, duplicate, identity, 2)

    assert result["rule_code"] == "DOCUMENT-DUPLICATE-EXACT-001"
    assert result["severity"] == "medium"
    assert result["category"] == "duplicate"
    assert result["evidence"]["classification"] == "exact"
    assert result["evidence"]["occurrence"] == 2


def test_conflicting_content_for_the_same_access_key_is_critical():
    canonical = _document("2" * 44, "b" * 64, "source-a")
    duplicate = _document("2" * 44, "c" * 64, "source-b")

    result = duplicate_finding(canonical, duplicate, document_identity(canonical), 2)

    assert result["rule_code"] == "DOCUMENT-DUPLICATE-CONFLICT-001"
    assert result["severity"] == "critical"
    assert result["evidence"]["canonical_xml_sha256"] == "b" * 64
    assert result["evidence"]["duplicate_xml_sha256"] == "c" * 64


def test_xml_hash_is_the_fallback_identity_without_an_access_key():
    document = _document(None, "d" * 64, "source-a")

    assert document_identity(document) == ("xml_sha256", "d" * 64)


def load_tests(loader, tests, pattern):
    import unittest
    return unittest.TestSuite(unittest.FunctionTestCase(fn) for name,fn in globals().items() if name.startswith("test_") and callable(fn))
