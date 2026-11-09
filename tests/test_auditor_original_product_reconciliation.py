"""Casos originais Auditor Fiscal 1.2.2 (MIT); caminhos adaptados ao Escritura."""
from app.auditor_engine.product_reconciliation import build_product_reconciliation, item_identity


def item(value, quantity, *, gtin=None, ncm="61091000", description="CAMISETA", unit="UN"):
    return {
        "item_number": 1,
        "description": description,
        "ncm": ncm,
        "product_value": value,
        "details": {"quantity": quantity, "unit": unit, "ean": gtin},
    }


def document(number, direction, fiscal_item):
    return {
        "number": number,
        "document_ref": number,
        "direction": direction,
        "issued_at": f"2026-01-{number.zfill(2)}T10:00:00-03:00",
        "status": "authorized",
        "items": [fiscal_item],
    }


def test_reconciles_generic_retail_product_by_gtin_and_quantity():
    gtin = "7891234567895"
    rows = build_product_reconciliation([
        document("1", "entrada", item("100.00", "10", gtin=gtin)),
        document("2", "saida", item("60.00", "4", gtin=gtin)),
    ])

    assert len(rows) == 1
    assert rows[0]["identity_type"] == "gtin"
    assert rows[0]["confidence"] == "high"
    assert rows[0]["estimated_cost"] == "40.00"
    assert rows[0]["margin"] == "20.00"
    assert rows[0]["status"] == "reconciled_estimate"


def test_marks_description_match_as_indicative_instead_of_conclusive():
    rows = build_product_reconciliation([
        document("1", "entrada", item("100.00", "1")),
        document("2", "saida", item("90.00", "1")),
    ])

    assert rows[0]["confidence"] == "indicative"
    assert rows[0]["status"] == "review_identity"


def test_prioritizes_mobile_imei_as_exact_identity():
    fiscal_item = item("2500.00", "1", description="SMARTPHONE")
    fiscal_item["details"]["identifiers"] = [
        {"type": "imei", "value": "123456789012345", "source": "det/infAdProd"}
    ]

    identity = item_identity(fiscal_item)

    assert identity["key"] == "unique:imei:123456789012345"
    assert identity["confidence"] == "exact"


def test_reconciles_market_lot_without_vehicle_fields():
    input_item = item("300.00", "30", description="IOGURTE", ncm="04031000")
    output_item = item("80.00", "5", description="IOGURTE", ncm="04031000")
    for fiscal_item in [input_item, output_item]:
        fiscal_item["details"]["traceability"] = [{"lot": "LT-2026-08", "expires_at": "2026-09-30"}]

    rows = build_product_reconciliation([
        document("1", "entrada", input_item),
        document("2", "saida", output_item),
    ])

    assert rows[0]["identity_type"] == "lot"
    assert rows[0]["input_quantity"] == "30"
    assert rows[0]["estimated_cost"] == "50.00"
    assert rows[0]["margin"] == "30.00"


def load_tests(loader, tests, pattern):
    import unittest
    return unittest.TestSuite(unittest.FunctionTestCase(fn) for name,fn in globals().items() if name.startswith("test_") and callable(fn))
