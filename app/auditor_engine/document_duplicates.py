from __future__ import annotations

import re
from typing import Any

SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def document_identity(document: dict[str, Any]) -> tuple[str, str] | None:
    access_key = str(document.get("access_key") or "").strip()
    if access_key:
        return "access_key", access_key
    xml_hash = xml_sha256(document)
    if xml_hash:
        return "xml_sha256", xml_hash
    return None


def xml_sha256(document: dict[str, Any]) -> str | None:
    normalized = document.get("normalized") or {}
    value = str(normalized.get("xml_sha256") or "").strip().lower()
    return value if SHA256_PATTERN.fullmatch(value) else None


def duplicate_classification(canonical: dict[str, Any], duplicate: dict[str, Any], identity_type: str) -> str:
    canonical_hash = xml_sha256(canonical)
    duplicate_hash = xml_sha256(duplicate)
    if canonical_hash and duplicate_hash and canonical_hash == duplicate_hash:
        return "exact"
    if identity_type == "access_key" and canonical_hash and duplicate_hash:
        return "conflicting_content"
    return "unverified"


def duplicate_finding(
    canonical: dict[str, Any],
    duplicate: dict[str, Any],
    identity: tuple[str, str],
    occurrence: int,
) -> dict[str, Any]:
    identity_type, identity_value = identity
    classification = duplicate_classification(canonical, duplicate, identity_type)
    variants = {
        "exact": (
            "DOCUMENT-DUPLICATE-EXACT-001",
            "medium",
            "Documento fiscal repetido no lote",
            "Uma ocorrência com a mesma identidade e o mesmo conteúdo XML foi consolidada no documento canônico.",
            "Sem a consolidação, valores, itens e tributos seriam contabilizados mais de uma vez.",
            "Confirmar a origem da repetição e manter apenas uma cópia do XML no próximo envio.",
            "1.0000",
        ),
        "conflicting_content": (
            "DOCUMENT-DUPLICATE-CONFLICT-001",
            "critical",
            "Chave de acesso repetida com conteúdo divergente",
            "Foram recebidos XMLs com a mesma chave de acesso, mas hashes de conteúdo diferentes. A primeira ocorrência foi preservada como canônica.",
            "Pode indicar alteração indevida, arquivo corrompido ou versões incompatíveis do mesmo documento fiscal.",
            "Comparar os XMLs com a autorização oficial da SEFAZ antes de usar o documento na apuração.",
            "0.9500",
        ),
        "unverified": (
            "DOCUMENT-DUPLICATE-UNVERIFIED-001",
            "high",
            "Identidade fiscal repetida sem hash verificável",
            "Mais de uma ocorrência compartilha a mesma identidade fiscal, mas não há hashes válidos suficientes para provar igualdade de conteúdo.",
            "Os totalizadores poderiam ser duplicados e o conteúdo divergente não pôde ser descartado.",
            "Validar os arquivos de origem e confrontar o documento com a autorização oficial da SEFAZ.",
            "0.9500",
        ),
    }
    rule, severity, title, description, impact, action, confidence = variants[classification]
    evidence = {
        "detection_layer": "document",
        "classification": classification,
        "identity_type": identity_type,
        "identity_value": identity_value,
        "canonical_document_ref": canonical.get("document_ref"),
        "duplicate_document_ref": duplicate.get("document_ref"),
        "canonical_source_file_id": canonical.get("source_file_id"),
        "duplicate_source_file_id": duplicate.get("source_file_id"),
        "canonical_xml_sha256": xml_sha256(canonical),
        "duplicate_xml_sha256": xml_sha256(duplicate),
        "occurrence": occurrence,
    }
    return {
        "document_ref": canonical.get("document_ref"),
        "item_number": None,
        "rule_code": rule,
        "rule_version": "1.0.0",
        "severity": severity,
        "category": "duplicate",
        "title": title,
        "description": description,
        "impact": impact,
        "recommended_action": action,
        "status": "open",
        "confidence": confidence,
        "evidence": evidence,
    }
