from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from .product_reconciliation import build_product_reconciliation, item_identity
from .xml_parser import finding


def apply_cross_document_rules(documents: list[dict]) -> list[dict]:
    findings = []
    entries_by_key = _entries_by_identity(documents)
    findings.extend(_duplicate_findings(entries_by_key))

    for row in build_product_reconciliation(documents):
        if row["status"] == "missing_input" and row["confidence"] == "exact":
            findings.append(finding(
                "RECONCILIATION-MISSING-INPUT-001",
                "medium",
                "data_quality",
                "Entrada anterior não localizada",
                f"Não foi localizado, na amostra, documento de entrada anterior para {row['identifier']}.",
                row["output_document_ref"],
                row["output_item_number"],
                _economic_evidence(row, sample_limitation=True),
                "Impede conciliar custo e margem do item individualizado.",
                "Confirmar estoque inicial, período da amostra e importar o XML de entrada quando disponível.",
            ))
            continue

        if row["status"] not in {"negative_margin", "zero_margin"}:
            continue

        negative = row["status"] == "negative_margin"
        findings.append(finding(
            "NEGATIVE-MARGIN-001" if negative else "ZERO-MARGIN-001",
            "high" if negative else "medium",
            "economic",
            "Venda abaixo do custo documental" if negative else "Margem documental zerada",
            (
                "As saídas apresentam valor inferior ao custo documental conciliado para o produto."
                if negative else
                "As entradas e saídas conciliadas apresentam margem documental estimada igual a zero."
            ),
            row["output_document_ref"],
            row["output_item_number"],
            _economic_evidence(row),
            (
                "Pode indicar prejuízo, custo incompleto ou correspondência de produto incorreta."
                if negative else
                "Pode sinalizar operação sem margem ou custo/receita incompletos na amostra."
            ),
            "Validar identidade do produto, estoque inicial, devoluções, descontos, despesas e composição do custo.",
        ))

    return findings


def _entries_by_identity(documents: list[dict]):
    grouped = defaultdict(list)
    for document in documents:
        if document.get("status") == "cancelled":
            continue
        for item in document.get("items", []):
            identity = item_identity(item)
            if identity:
                grouped[identity["key"]].append((document, item, identity))
    return grouped


def _duplicate_findings(entries_by_key) -> list[dict]:
    findings = []
    for rows in entries_by_key.values():
        identity = rows[0][2]
        if identity.get("confidence") != "exact":
            continue
        outputs = sorted(
            (entry for entry in rows if entry[0].get("direction") == "saida"),
            key=lambda entry: entry[0].get("issued_at") or "",
        )
        for first, second in zip(outputs, outputs[1:]):
            first_doc, first_item, _ = first
            second_doc, second_item, _ = second
            try:
                minutes = abs((
                    datetime.fromisoformat(second_doc["issued_at"])
                    - datetime.fromisoformat(first_doc["issued_at"])
                ).total_seconds()) / 60
            except (TypeError, ValueError):
                minutes = Decimal("Infinity")
            same_party = first_doc.get("recipient_tax_id") == second_doc.get("recipient_tax_id")
            values_equal = abs(
                Decimal(str(first_item.get("product_value") or "0"))
                - Decimal(str(second_item.get("product_value") or "0"))
            ) <= Decimal("0.01")
            if same_party and values_equal and minutes <= 60:
                evidence = {
                    "layer": "economic",
                    "identity": identity,
                    "documents": [first_doc.get("number"), second_doc.get("number")],
                    "minutes": round(float(minutes), 2),
                    "item_values": [first_item.get("product_value"), second_item.get("product_value")],
                    "recipient_tax_id": first_doc.get("recipient_tax_id"),
                }
                findings.append(finding(
                    "DUPLICATE-ECONOMIC-001",
                    "critical",
                    "duplicate",
                    "Possível duplicidade econômica",
                    f"As NF {first_doc.get('number')} e {second_doc.get('number')} repetem {identity['label']}, contraparte, valor do item e emissão próxima.",
                    first_doc["document_ref"],
                    first_item.get("item_number"),
                    evidence,
                    "Pode superestimar faturamento, estoque, bases e débitos.",
                    "Consultar os eventos oficiais e confirmar se as duas operações são distintas.",
                    Decimal("0.90"),
                ))
    return findings


def _economic_evidence(row: dict, sample_limitation: bool = False) -> dict:
    return {
        "layer": "economic",
        "identity": {
            "key": row["key"],
            "label": row["identifier"],
            "type": row["identity_type"],
            "confidence": row["confidence"],
            "basis": row.get("basis"),
        },
        "ncm": row.get("ncm"),
        "input_quantity": row["input_quantity"],
        "output_quantity": row["output_quantity"],
        "input_value": row["input_value"],
        "output_value": row["output_value"],
        "estimated_unit_cost": row["estimated_unit_cost"],
        "estimated_cost": row["estimated_cost"],
        "estimated_margin": row["margin"],
        "sample_limitation": sample_limitation or row["confidence"] != "exact",
    }


def _used_vehicle_margin_finding(row: dict, entries: list[tuple[dict, dict, dict]]):
    outputs = [entry for entry in entries if entry[0].get("direction") == "saida"]
    if not outputs or row.get("margin") is None:
        return None
    output_doc, output_item, _ = max(outputs, key=lambda entry: entry[0].get("issued_at") or "")
    pis_cofins = Decimal(str(output_item.get("pis_cofins") or "0"))
    explicit_base = Decimal(str(output_item.get("pis_cofins_base") or "0"))
    pis_cofins_base = explicit_base if explicit_base else (
        (pis_cofins / Decimal("0.0365")).quantize(Decimal("0.01")) if pis_cofins else Decimal("0")
    )
    margin = Decimal(str(row["margin"]))
    if not pis_cofins or abs(pis_cofins_base - margin) <= Decimal("1.00"):
        return None
    return finding(
        "USED-VEHICLE-MARGIN-001",
        "high",
        "margin",
        "Margem PIS/COFINS divergente em veículo usado",
        "A base de PIS/COFINS não coincide com a margem documental do veículo usado individualizado.",
        output_doc["document_ref"],
        output_item.get("item_number"),
        {
            "chassis": row["chassis"],
            "input_nf": row.get("input_document"),
            "output_nf": row.get("output_document"),
            "document_margin": str(margin),
            "pis_cofins_base": str(pis_cofins_base),
            "difference": str(pis_cofins_base - margin),
        },
        "Pode alterar PIS/COFINS e, por consequência, a base IBS/CBS.",
        "Reprocessar o custo do veículo e verificar ajustes documentais aplicáveis.",
    )
