from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
import unicodedata


ZERO = Decimal("0")
CENT = Decimal("0.01")


def decimal_value(value, default: Decimal = ZERO) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.000001"))
    except (InvalidOperation, TypeError, ValueError):
        return default


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _normalized(value: str | None) -> str:
    raw = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = "".join(character for character in raw if not unicodedata.combining(character))
    return re.sub(r"[^A-Z0-9]+", " ", ascii_value.upper()).strip()


def _valid_gtin(value: str | None) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits if len(digits) in {8, 12, 13, 14} else None


def item_identity(item: dict) -> dict | None:
    details = item.get("details") or {}
    configured = details.get("reconciliation_identity") or {}
    if configured.get("key") and configured.get("label"):
        return configured

    if item.get("chassis"):
        chassis = _normalized(item["chassis"]).replace(" ", "")
        return {
            "key": f"unique:chassis:{chassis}",
            "label": f"Chassi {item['chassis']}",
            "type": "chassis",
            "confidence": "exact",
            "basis": "det/infAdProd",
        }

    identifiers = details.get("identifiers") or []
    priorities = {"chassis": 0, "imei": 1, "serial": 2, "aggregation_code": 3}
    unique = sorted(
        (identifier for identifier in identifiers if identifier.get("type") in priorities and identifier.get("value")),
        key=lambda identifier: priorities[identifier["type"]],
    )
    if unique:
        identifier = unique[0]
        kind = identifier["type"]
        value = _normalized(identifier["value"]).replace(" ", "")
        labels = {"chassis": "Chassi", "imei": "IMEI", "serial": "Série", "aggregation_code": "Agregação"}
        return {
            "key": f"unique:{kind}:{value}",
            "label": f"{labels[kind]} {identifier['value']}",
            "type": kind,
            "confidence": "exact",
            "basis": identifier.get("source"),
        }

    traceability = details.get("traceability") or []
    lot = next((entry for entry in traceability if entry.get("lot")), None)
    if lot:
        qualifier = _valid_gtin(details.get("ean_taxable") or details.get("ean")) or item.get("ncm") or "SEM-CODIGO"
        return {
            "key": f"lot:{qualifier}:{_normalized(lot['lot']).replace(' ', '')}",
            "label": f"Lote {lot['lot']} · {item.get('description') or qualifier}",
            "type": "lot",
            "confidence": "high",
            "basis": "prod/rastro/nLote",
        }

    gtin = _valid_gtin(details.get("ean_taxable") or details.get("ean"))
    if gtin:
        return {
            "key": f"gtin:{gtin}",
            "label": f"GTIN {gtin} · {item.get('description') or ''}".rstrip(" ·"),
            "type": "gtin",
            "confidence": "high",
            "basis": "prod/cEAN|cEANTrib",
        }

    description = _normalized(item.get("description"))
    ncm = re.sub(r"\D", "", str(item.get("ncm") or ""))
    unit = _normalized(details.get("unit") or details.get("taxable_unit"))
    if ncm and description:
        return {
            "key": f"indicative:{ncm}:{description}:{unit}",
            "label": item.get("description") or ncm,
            "type": "ncm_description",
            "confidence": "indicative",
            "basis": "prod/NCM+xProd+uCom",
        }

    return None


def build_product_reconciliation(documents: list[dict]) -> list[dict]:
    grouped: dict[str, list[tuple[dict, dict, dict]]] = defaultdict(list)
    for document in documents:
        if document.get("status") == "cancelled":
            continue
        for item in document.get("items", []):
            identity = item_identity(item)
            if identity:
                grouped[identity["key"]].append((document, item, identity))

    rows = []
    for key, entries in grouped.items():
        identity = entries[0][2]
        inputs = [entry for entry in entries if entry[0].get("direction") == "entrada"]
        outputs = [entry for entry in entries if entry[0].get("direction") == "saida"]
        input_quantity = sum((_quantity(item, identity) for _, item, _ in inputs), ZERO)
        output_quantity = sum((_quantity(item, identity) for _, item, _ in outputs), ZERO)
        input_value = money(sum((decimal_value(item.get("product_value")) for _, item, _ in inputs), ZERO))
        output_value = money(sum((decimal_value(item.get("product_value")) for _, item, _ in outputs), ZERO))
        quantity_complete = all(_has_quantity(item, identity) for _, item, _ in inputs + outputs)
        unit_cost = money(input_value / input_quantity) if input_quantity > ZERO else None
        enough_stock = input_quantity >= output_quantity > ZERO
        estimated_cost = money(unit_cost * output_quantity) if unit_cost is not None and quantity_complete and enough_stock else None
        margin = money(output_value - estimated_cost) if estimated_cost is not None else None

        if not outputs:
            status = "in_stock"
        elif not inputs:
            status = "missing_input"
        elif not quantity_complete:
            status = "insufficient_quantity_data"
        elif not enough_stock:
            status = "insufficient_input_quantity"
        elif identity["confidence"] == "indicative":
            status = "review_identity"
        elif margin is not None and margin < ZERO:
            status = "negative_margin"
        elif margin == ZERO:
            status = "zero_margin"
        else:
            status = "reconciled" if identity["confidence"] == "exact" else "reconciled_estimate"

        latest_input = max(inputs, key=lambda entry: entry[0].get("issued_at") or "", default=None)
        latest_output = max(outputs, key=lambda entry: entry[0].get("issued_at") or "", default=None)
        rows.append({
            "key": key,
            "identifier": identity["label"],
            "identity_type": identity["type"],
            "confidence": identity["confidence"],
            "basis": identity.get("basis"),
            "description": next((item.get("description") for _, item, _ in entries if item.get("description")), None),
            "ncm": next((item.get("ncm") for _, item, _ in entries if item.get("ncm")), None),
            "unit": next(((item.get("details") or {}).get("unit") for _, item, _ in entries if (item.get("details") or {}).get("unit")), None),
            "input_quantity": decimal_text(input_quantity),
            "output_quantity": decimal_text(output_quantity),
            "input_value": str(input_value),
            "output_value": str(output_value),
            "estimated_unit_cost": str(unit_cost) if unit_cost is not None else None,
            "estimated_cost": str(estimated_cost) if estimated_cost is not None else None,
            "margin": str(margin) if margin is not None else None,
            "status": status,
            "input_document": latest_input[0].get("number") if latest_input else None,
            "output_document": latest_output[0].get("number") if latest_output else None,
            "output_document_ref": latest_output[0].get("document_ref") if latest_output else None,
            "output_item_number": latest_output[1].get("item_number") if latest_output else None,
            "used_movable_good": any(bool(item.get("used_movable_good")) for _, item, _ in entries),
            "chassis": next((item.get("chassis") for _, item, _ in entries if item.get("chassis")), None),
        })

    confidence_order = {"exact": 0, "high": 1, "indicative": 2}
    return sorted(rows, key=lambda row: (confidence_order.get(row["confidence"], 9), row["identifier"]))


def _has_quantity(item: dict, identity: dict) -> bool:
    if identity.get("confidence") == "exact":
        return True
    details = item.get("details") or {}
    return decimal_value(details.get("quantity")) > ZERO


def _quantity(item: dict, identity: dict) -> Decimal:
    if identity.get("confidence") == "exact":
        return Decimal("1")
    details = item.get("details") or {}
    return decimal_value(details.get("quantity"))
