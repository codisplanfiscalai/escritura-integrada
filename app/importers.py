"""Leitores de conferência, sem persistência e sem inferência de regras tributárias.

Contrato público: parse_file(filename, data, company) -> preview JSON serializável.
Opções explícitas em company['import_options']; ver IMPORTER_SCOPE abaixo.
Valores monetários são strings Decimal. Nenhum XML realiza acesso à rede.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import stat
import unicodedata
import zipfile
import zlib
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_EXPANDED_BYTES = 80 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 1000
MAX_ARCHIVE_DEPTH = 2  # raiz ZIP + um ZIP interno; um terceiro contêiner é recusado
MAX_COMPRESSION_RATIO = 200
MAX_RECORDS = 100000
MAX_LINE_CHARS = 65536
MAX_XML_NODES = 200000
MAX_XML_DEPTH = 100
MAX_ISSUES = 250

IMPORTER_SCOPE = {
    "xml": "NF-e/NFC-e 4.00 (55/65) e CT-e 4.00 (57); extração para conferência, sem validação XSD, assinatura, consulta SEFAZ ou motor fiscal.",
    "sped": "EFD ICMS/IPI leiaute 020/2026: 0000, 0150, 0200, C100, C170, C190, C140 e C141. Outros registros ficam identificados como não processados. Não importa ECD, ECF ou EFD-Contribuições.",
    "csv_txt": "Cabeçalho canônico data;valor;historico;documento ou bank_columns explícito. Separador decimal e formato de data configuráveis. TXT posicional exige bank_layout=fixed e posições explícitas.",
    "ofx": "Extratos bancários/cartão OFX XML e SGML: STMTTRN, DTPOSTED, TRNAMT, FITID, CHECKNUM, NAME/MEMO. Investimentos, pendentes e correções não são tratados como novos movimentos.",
    "ofc": "OFC 1.0.6: ACCTSTMT/ACCTFROM, TRNTYPE numérico, CHKNUM, data YYYYMMDD, valor com sinal. Leitor separado do OFX; sujeito a homologação por banco.",
    "qif": "Seções Bank/Cash/CCard/Oth A/Oth L, campos D/T/P/M/N e terminador ^. Datas locais exigem formato explícito; contas múltiplas e investimentos são recusados.",
    "zip": "Leitura em memória, limites de tamanho/quantidade/expansão/profundidade, sem extração de caminhos e sem seguir links. PDFs acessórios reconhecidos dentro de compactados são ignorados com aviso e origem rastreável; não geram documentos fiscais nem dispensam limites e integridade.",
    "rar_7z": "7z via py7zr; RAR via rarfile com libarchive (bsdtar no contêiner/macOS ou tar.exe no Windows) para entradas comprimidas. Sem leitor compatível, retorna diagnóstico e orienta ZIP/7z. Pacotes com senha, multipartes e codecs não suportados são recusados; limites e proteção de caminhos aplicados.",
}

SOURCE_DOCUMENTATION = [
    {"id": "efd", "title": "Guia Prático EFD ICMS/IPI 3.2.4", "url": "https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-icms-ipi/manuais-e-documentos-tecnicos/guia-pratico-efd-versao-3-2-4.pdf/@@display-file/file", "sections": "0000, 0150, 0200, C100, C140, C141, C170, C190; pp. 28–38, 65–68, 77–81, 106–107"},
    {"id": "efd020", "title": "NT 2025.001 v1.0 — leiaute 020, 2026", "url": "https://www.confaz.fazenda.gov.br/legislacao/arquivo-manuais/06___anexo_2.pdf/@@download/file/06___ANEXO_2.pdf"},
    {"id": "nfe", "title": "MOC NF-e 7.0 — Anexo I", "url": "https://www.nfe.fazenda.gov.br/portal/exibirArquivo.aspx?conteudo=J+I+v4eN00E%3D", "sections": "infNFe/ide, emit, dest, det/prod, imposto, total, cobr"},
    {"id": "cte", "title": "MOC CT-e 4.00 — Anexo I", "url": "https://www.cte.fazenda.gov.br/portal/exibirArquivo.aspx?conteudo=6aFNuknaWsc%3D", "sections": "ide/toma3/toma4, emit, rem, exped, receb, dest, vPrest/vTPrest"},
    {"id": "ofx", "title": "Financial Data Exchange — OFX Banking 2.3", "url": "https://financialdataexchange.org/common/Uploaded%20files/OFX%20files/OFX%20Banking%20Specification%20v2.3.pdf", "sections": "3.2, 11.4.4; compatibilidade de sintaxe SGML limitada aos extratos implementados"},
    {"id": "qif", "title": "Documento original Intuit preservado pelo W3C — QIF", "url": "https://www.w3.org/2000/10/swap/pim/qif-doc/QIF-doc.htm"},
    {"id": "ofc", "title": "Especificação Microsoft OFC 1.0.6 preservada por MnyBank", "url": "https://mnybank.sourceforge.net/Specs_Ofc.html", "note": "Cópia histórica da fonte primária; homologação com arquivos reais pendente."},
]


class ImportProblem(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _source(file, record=None, line=None, **extra):
    return {"file": file, "record": record, "line": line, **extra}


def _issue(result, code, message, source, severity="error"):
    # These generic reminders repeat for every XML, but contain no per-document
    # eligibility decision. Keep their complete provenance without consuming
    # the diagnostic budget once per document. Decision-bearing warnings such
    # as XML_NO_PROTOCOL and RTC_TOTAL_REVIEW must remain individual: posting
    # checks match their source.file to the document.
    aggregate_codes = {"DOCUMENT_REVIEW_REQUIRED", "HOMOLOGATION_DOCUMENT", "CFOP_CLASSIFICATION_REQUIRED"}
    if severity == "warning" and code in aggregate_codes:
        existing = next((item for item in result["issues"] if item["code"] == code and item["severity"] == severity), None)
        if existing is not None:
            sources = existing.setdefault("sources", [existing["source"]])
            sources.append(source)
            existing["count"] = len(sources)
            existing["message"] = f"{message} ({len(sources)} ocorrências; origens preservadas na prévia.)"
            return
    if len(result["issues"]) < MAX_ISSUES:
        result["issues"].append({"severity": severity, "code": code, "message": message, "source": source})
    elif not any(x["code"] == "ISSUE_LIMIT" for x in result["issues"]):
        result["issues"].append({"severity": "error", "code": "ISSUE_LIMIT", "message": "Há mais ocorrências que o limite da prévia; divida o arquivo e corrija as inconsistências.", "source": source})


def _empty():
    return {"documents": [], "transactions": [], "issues": [], "sources": [], "format": "unknown", "bank_account_hint": None, "partial": False, "can_confirm": False, "review_required": True}


def _tax_id(value):
    # Preserva letras: não transforma um CNPJ alfanumérico em outro identificador.
    return re.sub(r"[.\-/\s]", "", str(value or "")).upper()


def _company_tax(company):
    value = _tax_id(company.get("tax_id") or company.get("cnpj"))
    if not re.fullmatch(r"(?:[A-Z0-9]{12}\d{2}|\d{11})", value):
        raise ImportProblem("COMPANY_TAX_ID_REQUIRED", "Selecione uma empresa com CNPJ/CPF informado antes de importar documentos fiscais.")
    return value


def _options(company):
    options = company.get("import_options") or {}
    if not isinstance(options, dict):
        raise ImportProblem("INVALID_OPTIONS", "As opções de importação devem ser um objeto.")
    for name in ("encoding", "date_format", "delimiter", "decimal_separator", "thousands_separator", "bank_layout", "posting_date", "currency"):
        if options.get(name) is not None and not isinstance(options[name], str):
            raise ImportProblem("INVALID_OPTIONS", f"A opção {name} deve ser texto.")
    return options


def _decode(data, options, declared=None):
    configured = options.get("encoding")
    encoding = (None if configured in (None, "", "auto") else configured) or declared
    aliases = {"utf8": "utf-8-sig", "utf-8": "utf-8-sig", "utf-8-sig": "utf-8-sig", "cp1252": "cp1252", "windows-1252": "cp1252", "1252": "cp1252", "iso-8859-1": "iso-8859-1", "latin1": "iso-8859-1", "ascii": "ascii", "us-ascii": "ascii", "utf-16": "utf-16"}
    if encoding:
        encoding = aliases.get(str(encoding).lower())
        if not encoding:
            raise ImportProblem("ENCODING_UNSUPPORTED", "Codificação não suportada. Informe UTF-8, Windows-1252, ISO-8859-1, ASCII ou UTF-16 com BOM.")
    elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    else:
        encoding = "utf-8-sig"
    try:
        text = data.decode(encoding, errors="strict")
    except (UnicodeError, LookupError):
        raise ImportProblem("ENCODING_REQUIRED", "Não foi possível ler a codificação sem perda. Selecione a codificação do arquivo; não há conversão automática por tentativa.") from None
    if "\x00" in text:
        raise ImportProblem("BINARY_TEXT", "Arquivo de texto contém bytes nulos ou uma codificação incompatível.")
    return text


def _decimal(value, decimal_separator=".", thousands_separator=None, money=False, allow_negative=True):
    value = str(value).strip()
    if not value:
        raise ImportProblem("NUMBER_REQUIRED", "Valor numérico obrigatório não informado.")
    if len(value) > 48 or decimal_separator not in (".", ","):
        raise ImportProblem("INVALID_NUMBER", "Valor numérico ou separador decimal inválido.")
    if thousands_separator:
        if thousands_separator == decimal_separator or thousands_separator not in (".", ",", " "):
            raise ImportProblem("INVALID_OPTIONS", "Separadores de milhar e decimal precisam ser distintos.")
        group = re.escape(thousands_separator)
        dec = re.escape(decimal_separator)
        pattern = rf"[+-]?(?:\d+|\d{{1,3}}(?:{group}\d{{3}})+)(?:{dec}\d+)?"
        if not re.fullmatch(pattern, value):
            raise ImportProblem("INVALID_NUMBER", f"Valor '{value[:48]}' não corresponde aos separadores configurados.")
        value = value.replace(thousands_separator, "")
    if not re.fullmatch(rf"[+-]?\d{{1,20}}(?:{re.escape(decimal_separator)}\d{{1,15}})?", value):
        raise ImportProblem("INVALID_NUMBER", f"Valor '{value[:48]}' inválido. Expoentes, NaN e separadores não declarados não são aceitos.")
    try:
        number = Decimal(value.replace(decimal_separator, "."))
        if not allow_negative and number < 0:
            raise ImportProblem("NEGATIVE_AMOUNT", "Valor negativo não é aceito neste campo de documento.")
        if money:
            rounded = number.quantize(Decimal("0.01"))
            if rounded != number:
                raise ImportProblem("AMOUNT_PRECISION", "Valor monetário tem mais de duas casas significativas; o leitor não arredonda silenciosamente.")
            return format(rounded, ".2f")
        return format(number, "f")
    except InvalidOperation:
        raise ImportProblem("INVALID_NUMBER", "Valor fora dos limites de precisão do importador.") from None


DATE_FORMATS = {"YMD": "%Y-%m-%d", "DMY": "%d/%m/%Y", "MDY": "%m/%d/%Y", "YYYY-MM-DD": "%Y-%m-%d", "DD/MM/YYYY": "%d/%m/%Y", "MM/DD/YYYY": "%m/%d/%Y", "DDMMYYYY": "%d%m%Y", "YYYYMMDD": "%Y%m%d", "%Y-%m-%d": "%Y-%m-%d", "%d/%m/%Y": "%d/%m/%Y", "%m/%d/%Y": "%m/%d/%Y", "%d%m%Y": "%d%m%Y", "%Y%m%d": "%Y%m%d"}


def _date(value, format_name=None):
    value = str(value).strip()
    if not value:
        raise ImportProblem("DATE_REQUIRED", "Data obrigatória não informada.")
    if not format_name:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            format_name = "YYYY-MM-DD"
        else:
            raise ImportProblem("DATE_FORMAT_REQUIRED", f"Defina o formato de data para '{value[:24]}'. O leitor não presume dia/mês nem século.")
    fmt = DATE_FORMATS.get(format_name)
    if not fmt:
        raise ImportProblem("DATE_FORMAT_UNSUPPORTED", "Formato de data não suportado. Use ano com quatro dígitos e um dos formatos documentados.")
    patterns = {"%Y-%m-%d": r"\d{4}-\d{2}-\d{2}", "%d/%m/%Y": r"\d{1,2}/\d{1,2}/\d{4}", "%m/%d/%Y": r"\d{1,2}/\d{1,2}/\d{4}", "%d%m%Y": r"\d{8}", "%Y%m%d": r"\d{8}"}
    if not re.fullmatch(patterns[fmt], value):
        raise ImportProblem("INVALID_DATE", f"Data '{value[:24]}' não corresponde ao formato configurado.")
    try:
        return datetime.strptime(value, fmt).date().isoformat()
    except ValueError:
        raise ImportProblem("INVALID_DATE", f"Data '{value[:24]}' inválida.") from None


def _xml_date(value):
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return _date(value)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?", value):
        raise ImportProblem("INVALID_DATE", "Data/hora XML inválida; esperado formato ISO do documento.")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        raise ImportProblem("INVALID_DATE", "Data/hora XML fora dos limites válidos.") from None


def _bank_date(value):
    if not re.fullmatch(r"\d{8}(?:\d{6}(?:\.\d{1,6})?)?(?:\[[+-]?\d{1,2}(?:\.\d+)?(?::[^\]\r\n]{1,12})?\])?", value):
        raise ImportProblem("INVALID_BANK_DATE", "Data OFX/OFC deve iniciar em AAAAMMDD; datas locais não são presumidas.")
    if len(value) >= 14 and value[:14].isdigit():
        try:
            datetime.strptime(value[:14], "%Y%m%d%H%M%S")
        except ValueError:
            raise ImportProblem("INVALID_BANK_DATE", "Data/hora OFX/OFC inválida.") from None
    return _date(value[:8], "YYYYMMDD")


def _required(value, name):
    if value is None or str(value).strip() == "":
        raise ImportProblem("FIELD_REQUIRED", f"Campo obrigatório para leitura não informado: {name}.")
    return str(value).strip()


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _namespace(tag):
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _children(element, name):
    if element is None:
        return []
    ns = _namespace(element.tag)
    return [x for x in element if _local(x.tag) == name and _namespace(x.tag) == ns]


def _node(element, path):
    for part in path.split("/"):
        values = _children(element, part)
        if not values:
            return None
        if len(values) > 1:
            raise ImportProblem("XML_DUPLICATE_FIELD", f"Elemento único repetido no XML: {path}.")
        element = values[0]
    return element


def _text(element, path, default=""):
    value = _node(element, path)
    return (value.text or "").strip() if value is not None else default


class _BoundedTreeBuilder(ET.TreeBuilder):
    """Aplica limites durante a construção, antes de materializar uma árvore gigante."""
    def __init__(self):
        super().__init__()
        self.nodes = 0
        self.depth = 0

    def start(self, tag, attrs):
        self.nodes += 1
        self.depth += 1
        if self.nodes > MAX_XML_NODES or self.depth > MAX_XML_DEPTH:
            raise ImportProblem("XML_LIMIT", "XML excede o limite de elementos ou profundidade.")
        return super().start(tag, attrs)

    def end(self, tag):
        self.depth -= 1
        return super().end(tag)

    def doctype(self, name, pubid, system):
        raise ImportProblem("XML_DTD_FORBIDDEN", "DTD não é permitida no XML importado.")


def _xml_tree(data):
    # Também cobre declarações codificadas em UTF-16/UTF-32 antes de entregá-las ao parser.
    probe = data.replace(b"\x00", b"")
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", probe, re.I):
        raise ImportProblem("XML_DTD_FORBIDDEN", "DTD e entidades externas/internas não são permitidas no XML importado.")
    try:
        root = ET.fromstring(data, parser=ET.XMLParser(target=_BoundedTreeBuilder()))
    except ImportProblem:
        raise
    except (ET.ParseError, ValueError, LookupError):
        raise ImportProblem("XML_INVALID", "XML malformado ou codificação XML inválida.") from None
    return root


def _flatten(element, prefix=""):
    """Preserva textos de origem; não soma, calcula alíquotas nem toma crédito."""
    if element is None:
        return {}
    values = {}
    for child in element:
        key = f"{prefix}/{_local(child.tag)}".lstrip("/")
        if len(child):
            for subkey, value in _flatten(child, key).items():
                if subkey in values:
                    raise ImportProblem("XML_DUPLICATE_FIELD", f"Campo tributário duplicado: {subkey}.")
                values[subkey] = value
        else:
            if key in values:
                raise ImportProblem("XML_DUPLICATE_FIELD", f"Campo tributário duplicado: {key}.")
            values[key] = (child.text or "").strip()
    return values


def _party(element):
    party = {"name": _text(element, "xNome"), "tax_id": _tax_id(_text(element, "CNPJ") or _text(element, "CPF")), "foreign_id": _text(element, "idEstrangeiro")}
    if element is None:
        return party
    address_tag = {"emit": "enderEmit", "dest": "enderDest", "rem": "enderReme",
                   "exped": "enderExped", "receb": "enderReceb", "toma4": "enderToma"}.get(_local(element.tag))
    address = _node(element, address_tag) if address_tag else None
    for key, tag in {"trade_name": "xFant", "ie": "IE", "im": "IM", "email": "email", "phone": "fone"}.items():
        value = _text(element, tag)
        if value:
            party[key] = value
    for key, tag in {"address": "xLgr", "number": "nro", "district": "xBairro", "city": "xMun",
                     "state": "UF", "postal_code": "CEP", "ibge": "cMun", "phone": "fone"}.items():
        value = _text(address, tag)
        if value:
            party[key] = value
    # NF-e transporta uses flat address fields instead of an ender* group.
    if _local(element.tag) == "transporta":
        for key, tag in {"address": "xEnder", "city": "xMun", "state": "UF"}.items():
            value = _text(element, tag)
            if value:
                party[key] = value
    return party


def _xml_document(filename, data, company, result, digest):
    root = _xml_tree(data)
    kind = _local(root.tag)
    nfe = kind in ("NFe", "nfeProc")
    cte = kind in ("CTe", "cteProc")
    if not nfe and not cte:
        raise ImportProblem("XML_LAYOUT_UNSUPPORTED", "XML não é NF-e/NFC-e ou CT-e completo suportado. Resumos, eventos, NFS-e e outros modelos precisam de leitor específico.")
    ns = "http://www.portalfiscal.inf.br/nfe" if nfe else "http://www.portalfiscal.inf.br/cte"
    if _namespace(root.tag) != ns:
        raise ImportProblem("XML_NAMESPACE", "Namespace do documento fiscal não corresponde ao leiaute reconhecido.")
    tag = "infNFe" if nfe else "infCte"
    matches = list(root.iter(f"{{{ns}}}{tag}"))
    if len(matches) != 1:
        raise ImportProblem("XML_DOCUMENT_COUNT", "O XML deve conter exatamente um documento fiscal completo.")
    info = matches[0]
    if info.get("versao") != "4.00":
        raise ImportProblem("XML_VERSION_UNSUPPORTED", f"Versão XML '{info.get('versao', '')}' não homologada por este leitor; suportado o núcleo 4.00.")
    source = _source(filename, tag)
    own = _company_tax(company)
    issuer, recipient = _party(_node(info, "emit")), _party(_node(info, "dest"))
    model = _required(_text(info, "ide/mod"), "ide/mod")
    key = info.get("Id", "")
    prefix = "NFe" if nfe else "CTe"
    if not key.startswith(prefix) or not re.fullmatch(r"[A-Z0-9]{44}", key[len(prefix):]):
        raise ImportProblem("DOCUMENT_KEY", "Chave do documento ausente ou com estrutura diferente dos 44 caracteres esperados.")
    key = key[len(prefix):]
    if nfe:
        if model not in ("55", "65"):
            raise ImportProblem("XML_MODEL_UNSUPPORTED", f"Modelo {model} não é NF-e/NFC-e suportado.")
        operation = _required(_text(info, "ide/tpNF"), "ide/tpNF")
        if operation not in ("0", "1"):
            raise ImportProblem("XML_OPERATION", "tpNF deve indicar entrada ou saída no documento de origem.")
        if own == issuer["tax_id"] and own == recipient["tax_id"]:
            raise ImportProblem("COMPANY_ROLE_AMBIGUOUS", "Empresa aparece simultaneamente como emitente e destinatária; confirme a natureza da operação manualmente.")
        if own == issuer["tax_id"]:
            direction, partner = ("outgoing" if operation == "1" else "incoming"), recipient
        elif own == recipient["tax_id"]:
            direction, partner = ("incoming" if operation == "1" else "outgoing"), issuer
            if operation == "0":
                _issue(result, "THIRD_PARTY_ENTRY_REVIEW", "Nota de entrada emitida por terceiro: a direção proposta exige conferência da operação antes da escrituração.", source)
        else:
            raise ImportProblem("COMPANY_MISMATCH", "O CNPJ/CPF da empresa ativa não é emitente nem destinatário deste documento.")
        total = _decimal(_required(_text(info, "total/ICMSTot/vNF"), "total/ICMSTot/vNF"), money=True, allow_negative=False)
        taxes = _flatten(_node(info, "total"))
        number = _required(_text(info, "ide/nNF"), "ide/nNF")
        transport = None
    else:
        if model != "57":
            raise ImportProblem("XML_MODEL_UNSUPPORTED", "Este leitor trata CT-e modelo 57; CT-e OS e outros modelos precisam de leiaute próprio.")
        toma3, toma4 = _node(info, "ide/toma3"), _node(info, "ide/toma4")
        if (toma3 is None) == (toma4 is None):
            raise ImportProblem("CTE_TAKER_AMBIGUOUS", "CT-e deve identificar exatamente um tomador em toma3 ou toma4.")
        if toma3 is not None:
            taker_role = _text(toma3, "toma")
            group = {"0": "rem", "1": "exped", "2": "receb", "3": "dest"}.get(taker_role)
            if not group:
                raise ImportProblem("CTE_TAKER_INVALID", "Indicador toma3 não reconhecido.")
            taker = _party(_node(info, group))
        else:
            taker_role = _text(toma4, "toma")
            if taker_role != "4":
                raise ImportProblem("CTE_TAKER_INVALID", "toma4 deve identificar 'outros' (4).")
            taker, group = _party(toma4), "toma4"
        if not taker["tax_id"]:
            raise ImportProblem("CTE_TAKER_MISSING", "Tomador do transporte não identificado. Remetente e destinatário não substituem automaticamente o tomador.")
        if own == issuer["tax_id"] and own == taker["tax_id"]:
            raise ImportProblem("COMPANY_ROLE_AMBIGUOUS", "Empresa aparece como emitente e tomadora do transporte; confirme a operação.")
        if own == issuer["tax_id"]:
            direction, partner = "outgoing", taker
        elif own == taker["tax_id"]:
            direction, partner = "incoming", issuer
        else:
            raise ImportProblem("CTE_COMPANY_NOT_TAKER", "Empresa ativa não é emitente nem tomadora do transporte. Ser remetente/destinatária, isoladamente, não determina uma entrada de serviço.")
        total = _decimal(_required(_text(info, "vPrest/vTPrest"), "vPrest/vTPrest"), money=True, allow_negative=False)
        taxes = _flatten(_node(info, "imp"))
        number = _required(_text(info, "ide/nCT"), "ide/nCT")
        transport = {"taker_role": taker_role, "taker_group": group, "taker": taker, "issuer": issuer, "sender": _party(_node(info, "rem")), "recipient": recipient, "declared_receivable": _text(info, "vPrest/vRec"), "service_type": _text(info, "ide/tpServ")}
    issue_date = _xml_date(_required(_text(info, "ide/dhEmi"), "ide/dhEmi"))
    options = _options(company)
    posting_date = _date(options["posting_date"]) if options.get("posting_date") else issue_date
    doc = {"direction": direction, "document_type": "goods" if nfe else "transport", "number": number, "series": _text(info, "ide/serie"), "model": model, "issue_date": issue_date, "posting_date": posting_date, "posting_date_proposed": not bool(options.get("posting_date")), "partner_name": partner["name"] or ("Consumidor não identificado" if model == "65" else ""), "partner_tax_id": partner["tax_id"], "key": key, "cfop": "", "total": total, "taxes": taxes, "items": [], "invoices": [], "source": source, "source_hash": digest, "company_tax_id": own, "issuer": issuer, "recipient": recipient, "review_required": True, "environment": _text(info, "ide/tpAmb"), "signature_verified": False, "schema_validated": False, "tax_rules_applied": False}
    _required(doc["partner_name"], "nome do participante")
    # The declared goods movement date is evidence, not an automatic posting
    # rule. Do not fabricate it from issue_date when the XML omits the field.
    movement_date = (_text(info, "ide/dhSaiEnt") or _text(info, "ide/dSaiEnt")) if nfe else ""
    if movement_date:
        doc["movement_date"] = _xml_date(movement_date)
    if transport:
        doc["transport"] = transport
        declared_cfops = [_text(info, "ide/CFOP")]
    else:
        declared_cfops = []
        for index, det in enumerate(_children(info, "det"), 1):
            product = _node(det, "prod")
            if product is None:
                raise ImportProblem("XML_ITEM_MISSING", "Item fiscal sem grupo prod.")
            cfop = _text(product, "CFOP")
            declared_cfops.append(cfop)
            doc["items"].append({"number": det.get("nItem", str(index)), "code": _text(product, "cProd"), "description": _text(product, "xProd"), "ncm": _text(product, "NCM"), "cest": _text(product, "CEST"), "unit": _text(product, "uCom"), "quantity": _decimal(_required(_text(product, "qCom"), "qCom")), "unit_price": _decimal(_required(_text(product, "vUnCom"), "vUnCom")), "total": _decimal(_required(_text(product, "vProd"), "vProd"), money=True, allow_negative=False), "cfop": cfop if own == issuer["tax_id"] else "", "source_cfop": cfop, "taxes": _flatten(_node(det, "imposto")), "declared_product_fields": _flatten(product), "source": _source(filename, f"det[{index}]", item=det.get("nItem", str(index)))})
            barcode = _text(product, "cEAN")
            if barcode and barcode.upper() != "SEM GTIN":
                doc["items"][-1]["barcode"] = barcode
        for index, dup in enumerate(_children(_node(info, "cobr"), "dup"), 1):
            doc["invoices"].append({"number": _text(dup, "nDup") or str(index), "due_date": _date(_required(_text(dup, "dVenc"), "dup/dVenc")), "amount": _decimal(_required(_text(dup, "vDup"), "dup/vDup"), money=True, allow_negative=False), "source": _source(filename, f"cobr/dup[{index}]"), "financial_posting_created": False})
        if not doc["items"]:
            raise ImportProblem("XML_ITEM_MISSING", "NF-e/NFC-e sem itens det; o leitor requer um documento completo.")
    declared_cfops = sorted(set(x for x in declared_cfops if x))
    doc["source_cfops"] = declared_cfops
    doc["cfop_perspective"] = "issuer"
    if own == issuer["tax_id"] and len(declared_cfops) == 1:
        doc["cfop"] = declared_cfops[0]
    elif own != issuer["tax_id"]:
        _issue(result, "CFOP_CLASSIFICATION_REQUIRED", "CFOP do XML representa a operação do emitente. Classifique a operação da empresa ativa; o leitor preservou os códigos originais sem convertê-los.", source, "warning")
    if nfe:
        carrier = _node(info, "transp/transporta")
        if carrier is not None:
            doc["transport"] = {"carrier": _party(carrier)}
    if nfe and _text(info, "total/vNFTot"):
        doc["declared_new_total"] = _text(info, "total/vNFTot")
        _issue(result, "RTC_TOTAL_REVIEW", "XML contém vNFTot. O total extraído de vNF e os novos totalizadores foram preservados; o tratamento da versão RTC precisa de conferência.", source, "warning")
    protocol_tag = "infProt"
    protocols = list(root.iter(f"{{{ns}}}{protocol_tag}"))
    if len(protocols) > 1:
        raise ImportProblem("XML_PROTOCOL_AMBIGUOUS", "XML contém mais de um protocolo; não é possível associá-lo de forma inequívoca.")
    if protocols:
        protocol = protocols[0]
        protocol_key = _text(protocol, "chNFe" if nfe else "chCTe")
        if protocol_key != key:
            raise ImportProblem("XML_PROTOCOL_KEY_MISMATCH", "Chave do protocolo diverge da chave do documento.")
        doc["authorization"] = {"status": _text(protocol, "cStat"), "number": _text(protocol, "nProt"), "reason": _text(protocol, "xMotivo"), "verified_online": False}
        if doc["authorization"]["status"] not in ("100", "150"):
            _issue(result, "XML_AUTHORIZATION_STATUS", "Protocolo não indica um status de autorização reconhecido para esta leitura; confira antes de escriturar.", source)
    else:
        _issue(result, "XML_NO_PROTOCOL", "XML sem protocolo de autorização associado. A leitura não comprova autorização, assinatura ou situação atual.", source, "warning")
    if doc["environment"] == "2":
        _issue(result, "HOMOLOGATION_DOCUMENT", "Documento identificado como ambiente de homologação; não representa operação de produção.", source, "warning")
    _issue(result, "DOCUMENT_REVIEW_REQUIRED", "Valores declarados foram extraídos. Confira classificação e data de escrituração; XSD, assinatura, eventos posteriores e regras fiscais não foram validados.", source, "warning")
    result["documents"].append(doc)
    return "nfe" if nfe else "cte"


# Índices zero-based, incluindo REG na posição 0. Nunca tratar C190 como itens.
SPED_FIELDS = {
    "0000": "REG COD_VER COD_FIN DT_INI DT_FIN NOME CNPJ CPF UF IE COD_MUN IM SUFRAMA IND_PERFIL IND_ATIV".split(),
    "0150": "REG COD_PART NOME COD_PAIS CNPJ CPF IE COD_MUN SUFRAMA END NUM COMPL BAIRRO".split(),
    "0200": "REG COD_ITEM DESCR_ITEM COD_BARRA COD_ANT_ITEM UNID_INV TIPO_ITEM COD_NCM EX_IPI COD_GEN COD_LST ALIQ_ICMS CEST".split(),
    "C100": "REG IND_OPER IND_EMIT COD_PART COD_MOD COD_SIT SER NUM_DOC CHV_NFE DT_DOC DT_E_S VL_DOC IND_PGTO VL_DESC VL_ABAT_NT VL_MERC IND_FRT VL_FRT VL_SEG VL_OUT_DA VL_BC_ICMS VL_ICMS VL_BC_ICMS_ST VL_ICMS_ST VL_IPI VL_PIS VL_COFINS VL_PIS_ST VL_COFINS_ST".split(),
    "C170": "REG NUM_ITEM COD_ITEM DESCR_COMPL QTD UNID VL_ITEM VL_DESC IND_MOV CST_ICMS CFOP COD_NAT VL_BC_ICMS ALIQ_ICMS VL_ICMS VL_BC_ICMS_ST ALIQ_ST VL_ICMS_ST IND_APUR CST_IPI COD_ENQ VL_BC_IPI ALIQ_IPI VL_IPI CST_PIS VL_BC_PIS ALIQ_PIS_PERCENT QUANT_BC_PIS ALIQ_PIS_REAIS VL_PIS CST_COFINS VL_BC_COFINS ALIQ_COFINS_PERCENT QUANT_BC_COFINS ALIQ_COFINS_REAIS VL_COFINS COD_CTA VL_ABAT_NT".split(),
    "C190": "REG CST_ICMS CFOP ALIQ_ICMS VL_OPR VL_BC_ICMS VL_ICMS VL_BC_ICMS_ST VL_ICMS_ST VL_RED_BC VL_IPI COD_OBS".split(),
    "C140": "REG IND_EMIT IND_TIT DESC_TIT NUM_TIT QTD_PARC VL_TIT".split(),
    "C141": "REG NUM_PARC DT_VCTO VL_PARC".split(),
}


def _sped_fields(fields):
    names = SPED_FIELDS[fields[0]]
    if len(fields) != len(names):
        raise ImportProblem("SPED_FIELD_COUNT", f"Registro {fields[0]} possui {len(fields)} campos; esperado {len(names)} no recorte de leiaute suportado.")
    return dict(zip(names, fields))


def _sped(filename, data, company, result, digest):
    own = _company_tax(company)
    text = _decode(data, _options(company))
    records = []
    for line_number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        if len(raw) > MAX_LINE_CHARS or len(records) >= MAX_RECORDS:
            raise ImportProblem("RECORD_LIMIT", "SPED excede limite de registros/tamanho de linha.")
        if not raw.startswith("|") or not raw.endswith("|"):
            raise ImportProblem("SPED_DELIMITERS", f"Linha {line_number} não inicia/termina com o delimitador |.")
        records.append((line_number, raw[1:-1].split("|")))
    headers = [(line, f) for line, f in records if f[0] == "0000"]
    if len(headers) != 1 or records[0][1][0] != "0000":
        raise ImportProblem("SPED_HEADER", "EFD ICMS/IPI deve iniciar com um único registro 0000.")
    header = _sped_fields(headers[0][1])
    if header["COD_VER"] != "020":
        raise ImportProblem("SPED_LAYOUT_UNSUPPORTED", f"Leiaute {header['COD_VER']} não está habilitado: este recorte foi conferido para EFD ICMS/IPI 020/2026. ECD, ECF e EFD-Contribuições têm leitores próprios ainda pendentes.")
    start, end = _date(header["DT_INI"], "DDMMYYYY"), _date(header["DT_FIN"], "DDMMYYYY")
    if start > end or not start.startswith("2026-") or not end.startswith("2026-"):
        raise ImportProblem("SPED_PERIOD_LAYOUT", "Período não corresponde à vigência 2026 do leiaute 020 suportado.")
    if _tax_id(header["CNPJ"] or header["CPF"]) != own:
        raise ImportProblem("COMPANY_MISMATCH", "CNPJ/CPF do registro 0000 não corresponde à empresa ativa.")
    result["sped_header"] = {**header, "start_date": start, "end_date": end}
    participants, products = {}, {}
    for line, fields in records:
        if fields[0] in ("0150", "0200"):
            values = _sped_fields(fields)
            mapping, code = (participants, values.get("COD_PART")) if fields[0] == "0150" else (products, values.get("COD_ITEM"))
            if not code or code in mapping:
                raise ImportProblem("SPED_DUPLICATE_CODE", f"Código de cadastro ausente/repetido em {fields[0]}, linha {line}.")
            mapping[code] = {**values, "source": _source(filename, fields[0], line)}
    result["catalogs"] = {"participants": list(participants.values()), "products": list(products.values())}
    current, invoice = None, None
    unknown = Counter()
    structural = {"0000", "0001", "0005", "0100", "0190", "0400", "0450", "0460", "0500", "0600", "0990", "C001", "C990", "9001", "9900", "9990", "9999"}
    for line, fields in records:
        reg, source = fields[0], _source(filename, fields[0], line)
        if reg not in SPED_FIELDS:
            if reg not in structural:
                unknown[reg] += 1
                if current is not None and reg.startswith("C"):
                    current.setdefault("unprocessed_records", []).append({"record": reg, "line": line, "fields": fields})
            if not reg.startswith("C") or reg in ("C001", "C990") or re.fullmatch(r"C[2-9]00", reg):
                current, invoice = None, None
            continue
        if reg in ("0000", "0150", "0200"):
            continue
        if reg == "C100":
            current, invoice = None, None
        try:
            f = _sped_fields(fields)
            if reg == "C100":
                if f["COD_SIT"] in ("02", "03", "04", "05"):
                    _issue(result, "SPED_NON_MOVEMENT", "Documento cancelado/denegado/inutilizado preservado na origem; não foi convertido em movimento fiscal ativo.", source, "warning")
                    continue
                if f["COD_MOD"] not in ("01", "1B", "04", "55", "65") or f["IND_OPER"] not in ("0", "1"):
                    raise ImportProblem("SPED_DOCUMENT_TYPE", "Modelo ou indicador de operação C100 não suportado.")
                if f["IND_EMIT"] not in ("0", "1"):
                    raise ImportProblem("SPED_ISSUER", "Indicador IND_EMIT do C100 inválido.")
                if f["COD_MOD"] in ("55", "65") and not re.fullmatch(r"[A-Z0-9]{44}", f["CHV_NFE"]):
                    raise ImportProblem("DOCUMENT_KEY", "C100 de NF-e/NFC-e sem chave de 44 caracteres; corrija antes de importar.")
                partner = participants.get(f["COD_PART"], {})
                if f["COD_PART"] and not partner:
                    raise ImportProblem("SPED_PARTICIPANT_MISSING", f"Participante {f['COD_PART']} não encontrado no 0150.")
                partner_name = partner.get("NOME", "") or ("Consumidor não identificado" if f["COD_MOD"] == "65" else "")
                _required(partner_name, "nome do participante/0150")
                issued = _date(f["DT_DOC"], "DDMMYYYY")
                posted = _date(f["DT_E_S"], "DDMMYYYY") if f["DT_E_S"] else issued
                if not f["DT_E_S"]:
                    _issue(result, "POSTING_DATE_REVIEW", "C100 sem DT_E_S. Data de emissão foi proposta para conferência, sem determinar automaticamente a competência fiscal.", source, "warning")
                current = {"direction": "incoming" if f["IND_OPER"] == "0" else "outgoing", "document_type": "goods", "number": _required(f["NUM_DOC"], "NUM_DOC"), "series": f["SER"], "model": f["COD_MOD"], "issue_date": issued, "posting_date": posted, "posting_date_proposed": not bool(f["DT_E_S"]), "partner_name": partner.get("NOME", ""), "partner_tax_id": _tax_id(partner.get("CNPJ") or partner.get("CPF")), "key": f["CHV_NFE"], "cfop": "", "total": _decimal(f["VL_DOC"], ",", money=True, allow_negative=False), "taxes": {k: _decimal(v, ",") for k, v in f.items() if v and k in {"VL_BC_ICMS", "VL_ICMS", "VL_BC_ICMS_ST", "VL_ICMS_ST", "VL_IPI", "VL_PIS", "VL_COFINS", "VL_PIS_ST", "VL_COFINS_ST"}}, "items": [], "analytics": [], "invoices": [], "raw_fields": f, "source": source, "source_hash": digest, "company_tax_id": own, "review_required": True, "tax_rules_applied": False, "cfop_perspective": "declarant"}
                current["partner_name"] = partner_name
                result["documents"].append(current)
            elif current is None:
                raise ImportProblem("SPED_ORPHAN_RECORD", f"{reg} sem C100 válido associado.")
            elif reg == "C170":
                product = products.get(f["COD_ITEM"])
                if not product:
                    raise ImportProblem("SPED_PRODUCT_MISSING", f"Item {f['COD_ITEM']} não encontrado no 0200.")
                if any(x["number"] == f["NUM_ITEM"] for x in current["items"]):
                    raise ImportProblem("SPED_DUPLICATE_ITEM", "Número de item repetido no mesmo C100.")
                current["items"].append({"number": f["NUM_ITEM"], "code": f["COD_ITEM"], "description": product["DESCR_ITEM"], "complement": f["DESCR_COMPL"], "ncm": product["COD_NCM"], "cest": product["CEST"], "quantity": _decimal(f["QTD"], ","), "unit": f["UNID"], "total": _decimal(f["VL_ITEM"], ",", money=True, allow_negative=False), "cfop": f["CFOP"], "cst_icms": f["CST_ICMS"], "taxes": {k: _decimal(v, ",") for k, v in f.items() if v and (k.startswith("VL_") or k.startswith("ALIQ_") or k.startswith("QUANT_BC"))}, "raw_fields": f, "source": source})
            elif reg == "C190":
                key = (f["CST_ICMS"], f["CFOP"], f["ALIQ_ICMS"])
                if any((x["cst_icms"], x["cfop"], x["raw_fields"]["ALIQ_ICMS"]) == key for x in current["analytics"]):
                    raise ImportProblem("SPED_DUPLICATE_ANALYTIC", "Agrupamento CST/CFOP/alíquota repetido no C190.")
                current["analytics"].append({"cst_icms": f["CST_ICMS"], "cfop": f["CFOP"], "rate": _decimal(f["ALIQ_ICMS"], ",") if f["ALIQ_ICMS"] else None, "operation_total": _decimal(f["VL_OPR"], ",", money=True), "taxes": {k: _decimal(v, ",") for k, v in f.items() if v and k.startswith("VL_")}, "raw_fields": f, "source": source})
            elif reg == "C140":
                if invoice is not None:
                    raise ImportProblem("SPED_DUPLICATE_INVOICE", "Mais de um C140 associado ao C100 neste leiaute.")
                if not f["QTD_PARC"].isdigit():
                    raise ImportProblem("SPED_INSTALLMENT_COUNT", "Quantidade de parcelas C140 inválida.")
                invoice = {"number": f["NUM_TIT"], "type": f["IND_TIT"], "description": f["DESC_TIT"], "amount": _decimal(f["VL_TIT"], ",", money=True, allow_negative=False), "declared_installment_count": int(f["QTD_PARC"]), "installments": [], "raw_fields": f, "source": source, "financial_posting_created": False}
                current["invoices"].append(invoice)
            elif reg == "C141":
                if invoice is None:
                    raise ImportProblem("SPED_ORPHAN_INSTALLMENT", "C141 sem C140 associado.")
                if any(x["number"] == f["NUM_PARC"] for x in invoice["installments"]):
                    raise ImportProblem("SPED_DUPLICATE_INSTALLMENT", "Parcela repetida no C141.")
                invoice["installments"].append({"number": f["NUM_PARC"], "due_date": _date(f["DT_VCTO"], "DDMMYYYY"), "amount": _decimal(f["VL_PARC"], ",", money=True, allow_negative=False), "source": source})
        except ImportProblem as problem:
            _issue(result, problem.code, str(problem), source)
    for doc in [x for x in result["documents"] if x["source_hash"] == digest]:
        cfops = sorted({x["cfop"] for x in doc["items"] + doc["analytics"] if x.get("cfop")})
        doc["cfops"] = cfops
        doc["cfop"] = cfops[0] if len(cfops) == 1 else ""
        for invoice in doc["invoices"]:
            if len(invoice["installments"]) != invoice["declared_installment_count"]:
                _issue(result, "SPED_INSTALLMENT_COUNT", "Quantidade de parcelas C141 diverge do C140.", invoice["source"])
        if doc["analytics"]:
            for field in ("VL_BC_ICMS", "VL_ICMS", "VL_BC_ICMS_ST", "VL_ICMS_ST", "VL_IPI"):
                if field in doc["taxes"] and all(field in x["taxes"] for x in doc["analytics"]):
                    declared_sum = sum((Decimal(x["taxes"][field]) for x in doc["analytics"]), Decimal("0"))
                    if declared_sum != Decimal(doc["taxes"][field]):
                        _issue(result, "SPED_DECLARED_TOTAL_MISMATCH", f"Somatório declarado em C190 para {field} diverge do C100; nenhum valor foi corrigido automaticamente.", doc["source"], "warning")
    result["partial"] = True
    result["unprocessed_records"] = dict(unknown)
    _issue(result, "SPED_PARTIAL_READER", "Leitura parcial EFD ICMS/IPI 020: cabeçalhos, itens, analíticos e faturas. Não valida PVA, ajustes, apuração, inventário ou obrigações; não gera títulos nem lançamentos automaticamente.", _source(filename, "0000", headers[0][0]), "warning")
    if unknown:
        _issue(result, "SPED_UNPROCESSED_RECORDS", "Registros preservados apenas no arquivo de origem, sem interpretação: " + ", ".join(f"{k} ({v})" for k, v in sorted(unknown.items()))[:1400], _source(filename), "warning")
    return "sped_efd_icms_ipi_020"


def _normal_header(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value.strip().lower()) if not unicodedata.combining(c))


def _transaction(result, filename, digest, line, record, date_value, amount, description, reference="", external_id="", bank_account_hint=None, **extra):
    if len(result["transactions"]) >= MAX_RECORDS:
        raise ImportProblem("RECORD_LIMIT", "Extrato excede limite de movimentos.")
    _required(description, "histórico do movimento")
    if Decimal(amount) == 0:
        raise ImportProblem("ZERO_BANK_AMOUNT", "Movimento de valor zero não pode ser conciliado neste fluxo; confira a linha do extrato.")
    source = _source(filename, record, line)
    result["transactions"].append({"date": date_value, "amount": amount, "description": description.strip(), "reference": reference.strip(), "external_id": external_id or hashlib.sha256(f"{digest}:{record}:{line}".encode()).hexdigest(), "external_id_origin": "source" if external_id else "file_record_hash", "source": source, "source_hash": digest, "bank_account_hint": bank_account_hint, **extra})


def _bank_table(filename, data, company, result, digest):
    options = _options(company)
    if options.get("currency", "BRL") != "BRL":
        raise ImportProblem("CURRENCY_UNSUPPORTED", "Conversão de moeda não está implementada. Este contexto financeiro admite BRL.")
    text = _decode(data, options)
    if any(len(line) > MAX_LINE_CHARS for line in text.splitlines()):
        raise ImportProblem("LINE_LIMIT", "Linha do extrato excede limite de tamanho.")
    columns = options.get("bank_columns")
    required = ("date", "amount", "description", "reference")
    rows = []
    if options.get("bank_layout") == "fixed":
        if not isinstance(columns, dict) or not all(k in columns for k in required):
            raise ImportProblem("BANK_LAYOUT_REQUIRED", "TXT posicional exige bank_columns para date, amount, description e reference, com start (base zero) e length.")
        for key in required:
            spec = columns[key]
            if not isinstance(spec, dict) or not isinstance(spec.get("start"), int) or not isinstance(spec.get("length"), int) or spec["start"] < 0 or spec["length"] <= 0 or spec["start"] + spec["length"] > MAX_LINE_CHARS:
                raise ImportProblem("BANK_LAYOUT_INVALID", f"Posição/tamanho inválido para {key}.")
        for line_number, line in enumerate(text.splitlines(), 1):
            if line.strip():
                if any(len(line) < columns[k]["start"] + columns[k]["length"] for k in required):
                    raise ImportProblem("BANK_ROW_SHORT", f"Linha {line_number} é menor que o leiaute posicional.")
                rows.append((line_number, {k: line[columns[k]["start"]:columns[k]["start"] + columns[k]["length"]].strip() for k in required}))
                if len(rows) > MAX_RECORDS:
                    raise ImportProblem("RECORD_LIMIT", "Extrato excede limite de linhas.")
    else:
        if columns is None:
            columns = {"date": "data", "amount": "valor", "description": "historico", "reference": "documento"}
        if not isinstance(columns, dict) or not all(isinstance(columns.get(k), str) and columns[k] for k in required):
            raise ImportProblem("BANK_LAYOUT_REQUIRED", "Informe o mapeamento dos campos date, amount, description e reference ou use data,valor,historico,documento no cabeçalho.")
        delimiter = options.get("delimiter")
        delimiter = "\t" if delimiter == "TAB" else delimiter
        if delimiter and delimiter not in (";", ",", "\t", "|"):
            raise ImportProblem("BANK_DELIMITER_INVALID", "Delimitador deve ser ponto e vírgula, vírgula, tabulação ou |.")
        first_line = text.splitlines()[0] if text.splitlines() else ""
        if not delimiter:
            wanted = {_normal_header(x) for x in columns.values()}
            candidates = []
            for candidate in (";", ",", "\t", "|"):
                values = next(csv.reader([first_line], delimiter=candidate, strict=True))
                if wanted.issubset({_normal_header(x) for x in values}):
                    candidates.append(candidate)
            if len(candidates) != 1:
                raise ImportProblem("BANK_LAYOUT_REQUIRED", "Cabeçalho não corresponde a um leiaute explícito. Use data;valor;historico;documento ou configure o mapeamento e delimitador.")
            delimiter = candidates[0]
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
        header = next(reader, None)
        if not header:
            raise ImportProblem("EMPTY_FILE", "Extrato está vazio.")
        normalized = [_normal_header(x) for x in header]
        if len(set(normalized)) != len(normalized):
            raise ImportProblem("BANK_DUPLICATE_HEADER", "Cabeçalho contém colunas duplicadas.")
        try:
            mapping = {k: normalized.index(_normal_header(columns[k])) for k in required}
        except ValueError:
            raise ImportProblem("BANK_LAYOUT_REQUIRED", "Uma coluna exigida pelo leiaute não existe no cabeçalho.") from None
        for values in reader:
            if not any(x.strip() for x in values):
                continue
            if len(values) != len(header):
                raise ImportProblem("BANK_COLUMN_COUNT", f"Linha {reader.line_num} possui quantidade diferente de colunas; confirme delimitador e aspas.")
            rows.append((reader.line_num, {k: values[index] for k, index in mapping.items()}))
            if len(rows) > MAX_RECORDS:
                raise ImportProblem("RECORD_LIMIT", "Extrato excede limite de linhas.")
    for line, row in rows:
        source = _source(filename, "bank_row", line)
        try:
            posted = _date(row["date"], options.get("date_format"))
            amount = _decimal(row["amount"], options.get("decimal_separator", "."), options.get("thousands_separator"), money=True)
            _transaction(result, filename, digest, line, "bank_row", posted, amount, _required(row["description"], "histórico"), row["reference"])
        except ImportProblem as problem:
            _issue(result, problem.code, str(problem), source)
    if not rows:
        raise ImportProblem("NO_TRANSACTIONS", "O extrato não contém linhas de movimentos.")
    return "bank_fixed_txt" if options.get("bank_layout") == "fixed" else "bank_delimited"


def _tag_value(block, tag, required=False):
    matches = re.findall(rf"<{re.escape(tag)}\s*>\s*([^<]*)", block, re.I)
    if len(matches) > 1:
        raise ImportProblem("BANK_DUPLICATE_TAG", f"Campo {tag} repetido no movimento bancário.")
    value = matches[0].strip() if matches else ""
    return _required(value, tag) if required else value


def _bank_blocks(text, tag):
    return list(re.finditer(rf"<{tag}(?:\s[^<>]*)?>(.*?)</{tag}\s*>", text, re.I | re.S))


def _bank_markup(filename, data, company, result, digest, ofc=False):
    probe = data.replace(b"\x00", b"")
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", probe, re.I):
        raise ImportProblem("XML_DTD_FORBIDDEN", "DTD/entidades não são permitidas em OFX/OFC.")
    declared = None
    charset = re.search(br"(?:CHARSET\s*:\s*|<CPAGE>\s*)(1252|UTF-8|65001|8859-1|ISO-8859-1)", data[:4096], re.I)
    if charset:
        declared = {"65001": "utf-8", "8859-1": "iso-8859-1"}.get(charset[1].decode().upper(), charset[1].decode())
    declaration = re.search(br"<\?xml[^>]*encoding\s*=\s*['\"]([^'\"]+)['\"]", data[:256], re.I)
    if declaration:
        declared = declaration[1].decode("ascii")
    text = _decode(data, _options(company), declared)
    root_tag = "OFC" if ofc else "OFX"
    root_match = re.search(rf"<{root_tag}(?:\s[^<>]*)?>", text, re.I)
    if not root_match or not re.search(rf"</{root_tag}\s*>\s*$", text, re.I):
        raise ImportProblem("BANK_ROOT", f"Arquivo não contém raiz {root_tag} completa; formatos OFX e OFC não são intercambiáveis.")
    xml_mode = not ofc and (text.lstrip().startswith("<?xml") or bool(re.search(r"<\?OFX\b", text, re.I)))
    if xml_mode:
        _xml_tree(data)  # valida fechamento/estrutura antes da leitura do subconjunto
    if re.search(r"<(?:INVSTMTRS|STMTTRNP|CORRECTFITID|CORRECTACTION)\b", text, re.I):
        raise ImportProblem("BANK_OPERATION_UNSUPPORTED", "Investimentos, movimentos pendentes e correções de movimentos exigem tratamento próprio; não serão convertidos em novos lançamentos.")
    for status in _bank_blocks(text, "STATUS"):
        code = _tag_value(status.group(1), "CODE")
        if code and code != "0":
            raise ImportProblem("OFX_STATUS_ERROR", f"O arquivo informa status bancário {code}; confira o retorno do banco.")
    statements = _bank_blocks(text, "ACCTSTMT") if ofc else sorted(_bank_blocks(text, "STMTRS") + _bank_blocks(text, "CCSTMTRS"), key=lambda x: x.start())
    if not statements:
        raise ImportProblem("BANK_STATEMENT_REQUIRED", f"{root_tag} sem extrato bancário/cartão reconhecido.")
    seen_ids, hints, transaction_count = set(), set(), 0
    for statement in statements:
        body = statement.group(1)
        currency = _tag_value(body, "CURDEF")
        if currency and currency != "BRL":
            raise ImportProblem("CURRENCY_UNSUPPORTED", f"Extrato em {currency}; não será convertido para BRL nem mesclado sem um módulo de moeda correspondente.")
        account_tag = "ACCTFROM" if ofc else ("BANKACCTFROM" if _bank_blocks(body, "BANKACCTFROM") else "CCACCTFROM")
        accounts = _bank_blocks(body, account_tag)
        if len(accounts) != 1:
            raise ImportProblem("BANK_ACCOUNT_AMBIGUOUS", "Cada extrato deve identificar uma conta de origem sem ambiguidade.")
        account = accounts[0].group(1)
        account_id = _tag_value(account, "ACCTID", required=True)
        hint = "/".join(x for x in (_tag_value(account, "BANKID"), _tag_value(account, "BRANCHID"), account_id) if x)
        hints.add(hint)
        blocks = _bank_blocks(body, "STMTTRN")
        if len(re.findall(r"<STMTTRN\s*>", body, re.I)) != len(blocks):
            raise ImportProblem("BANK_TRANSACTION_TRUNCATED", "Movimento STMTTRN sem fechamento; arquivo foi recusado para evitar perda silenciosa.")
        for match in blocks:
            transaction_count += 1
            block = match.group(1)
            offset = statement.start(1) + match.start()
            line = text.count("\n", 0, offset) + 1
            source = _source(filename, "STMTTRN", line)
            try:
                trntype = _tag_value(block, "TRNTYPE", required=True)
                if ofc and trntype not in {str(i) for i in range(13)}:
                    raise ImportProblem("OFC_TRANSACTION_TYPE", "OFC requer TRNTYPE numérico 0–12, conforme seu próprio leiaute.")
                if not ofc and not re.fullmatch(r"[A-Z]+", trntype):
                    raise ImportProblem("OFX_TRANSACTION_TYPE", "OFX requer tipo textual de movimento; não será aplicado o código numérico do OFC.")
                posted = _bank_date(_tag_value(block, "DTPOSTED", required=True))
                raw_amount = _tag_value(block, "TRNAMT", required=True)
                separator = "," if ofc and "," in raw_amount else "."
                amount = _decimal(raw_amount, separator, money=True)
                fitid = _tag_value(block, "FITID")
                if not ofc and not fitid:
                    raise ImportProblem("OFX_FITID_REQUIRED", "Movimento OFX sem FITID; a identificação bancária é necessária para evitar duplicidade.")
                if fitid and (hint, fitid) in seen_ids:
                    raise ImportProblem("BANK_DUPLICATE_ID", "FITID repetido para a mesma conta dentro do arquivo; revise antes de importar.")
                seen_ids.add((hint, fitid))
                # NAME pode estar no grupo PAYEE; ambos não devem coexistir.
                description = " — ".join(x for x in (_tag_value(block, "NAME"), _tag_value(block, "MEMO")) if x)
                reference = _tag_value(block, "CHKNUM" if ofc else "CHECKNUM") or _tag_value(block, "REFNUM")
                _transaction(result, filename, digest, line, f"STMTTRN[{transaction_count}]", posted, amount, description, reference, fitid, hint, transaction_type=trntype, currency=currency or None)
                if ofc and not fitid:
                    _issue(result, "OFC_NO_FITID", "OFC sem FITID: identidade limitada ao arquivo/registro; confira sobreposição de extratos.", source, "warning")
            except ImportProblem as problem:
                _issue(result, problem.code, str(problem), source)
    if transaction_count != len(re.findall(r"<STMTTRN\s*>", text, re.I)):
        raise ImportProblem("BANK_UNSCOPED_TRANSACTION", "Há movimentos fora dos extratos reconhecidos; arquivo recusado para não perder contexto de conta.")
    if not transaction_count:
        _issue(result, "NO_TRANSACTIONS", "Extrato reconhecido sem movimentos STMTTRN.", _source(filename), "warning")
    result["bank_account_hints"] = sorted(set(result.get("bank_account_hints", [])) | hints)
    result["bank_account_hint"] = next(iter(hints)) if len(hints) == 1 else None
    if len(hints) > 1:
        _issue(result, "MULTIPLE_BANK_ACCOUNTS", "Arquivo contém mais de uma conta. Separe as contas na confirmação; não atribua todos os movimentos a uma conta única.", _source(filename))
    return "ofc" if ofc else ("ofx_xml" if xml_mode else "ofx_sgml")


def _qif(filename, data, company, result, digest):
    options = _options(company)
    if options.get("currency", "BRL") != "BRL":
        raise ImportProblem("CURRENCY_UNSUPPORTED", "Conversão de moeda não está implementada. Este contexto financeiro admite BRL.")
    text = _decode(data, options)
    record, start, kind, count = [], None, None, 0
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if len(line) > MAX_LINE_CHARS:
            raise ImportProblem("LINE_LIMIT", "Linha QIF excede o limite.")
        if line.startswith("!"):
            if record:
                raise ImportProblem("QIF_TERMINATOR", "Registro QIF não foi encerrado com ^ antes do próximo cabeçalho.")
            if line == "!Account":
                raise ImportProblem("QIF_ACCOUNTS_UNSUPPORTED", "QIF com cadastro/múltiplas contas exige separação explícita antes da importação.")
            if not line.startswith("!Type:") or line[6:] not in ("Bank", "Cash", "CCard", "Oth A", "Oth L"):
                raise ImportProblem("QIF_TYPE_UNSUPPORTED", "Tipo QIF não suportado: leia somente extratos Bank, Cash, CCard, Oth A ou Oth L.")
            kind = line[6:]
            continue
        if kind is None:
            raise ImportProblem("QIF_HEADER", "QIF deve declarar uma seção !Type suportada.")
        if line != "^":
            start = start or line_number
            record.append(line)
            continue
        count += 1
        source = _source(filename, f"QIF[{count}]", start or line_number)
        try:
            values = {}
            for item in record:
                code, value = item[0], item[1:]
                if code in "DTPMN" and code in values:
                    raise ImportProblem("QIF_DUPLICATE_FIELD", f"Campo QIF {code} repetido na mesma transação.")
                values[code] = value
            posted = _date(_required(values.get("D"), "D/data"), options.get("date_format"))
            decimal_separator = options.get("decimal_separator", ".")
            thousands = options.get("thousands_separator", "," if decimal_separator == "." else None)
            amount = _decimal(_required(values.get("T"), "T/valor"), decimal_separator, thousands, money=True)
            description = " — ".join(x for x in (values.get("P"), values.get("M")) if x)
            _transaction(result, filename, digest, start or line_number, f"QIF[{count}]", posted, amount, description, values.get("N", ""), qif_type=kind, raw_lines=record[:])
            if any(item[0] in "SE$" for item in record):
                _issue(result, "QIF_SPLITS_REVIEW", "Rateios QIF preservados como informação de origem; apenas o total T foi importado como movimento bancário.", source, "warning")
        except ImportProblem as problem:
            _issue(result, problem.code, str(problem), source)
        record, start = [], None
    if record:
        raise ImportProblem("QIF_TERMINATOR", "Último registro QIF está truncado: falta o terminador ^.")
    if not count:
        raise ImportProblem("NO_TRANSACTIONS", "QIF sem transações terminadas por ^.")
    return "qif"


def _zip(filename, data, company, result, state, depth):
    if depth >= MAX_ARCHIVE_DEPTH:
        raise ImportProblem("ARCHIVE_DEPTH", "ZIP excede dois níveis de contêiner (arquivo principal e um ZIP interno).")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ImportProblem("ZIP_INVALID", "Arquivo ZIP inválido ou incompleto.") from None
    with archive:
        entries = archive.infolist()
        state["members"] += len(entries)
        if state["members"] > MAX_ARCHIVE_MEMBERS:
            raise ImportProblem("ARCHIVE_MEMBERS", "Quantidade total de membros excede o limite do pacote.")
        seen = set()
        for member in entries:
            name = member.filename.replace("\\", "/")
            path = PurePosixPath(name)
            mode = member.external_attr >> 16
            if "\x00" in name or path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", name) or ":" in name or stat.S_ISLNK(mode):
                raise ImportProblem("ARCHIVE_UNSAFE_PATH", "ZIP contém caminho absoluto, relativo inseguro, stream ou link simbólico.")
            if name in seen:
                raise ImportProblem("ARCHIVE_DUPLICATE_NAME", "ZIP contém nomes de arquivo repetidos; a origem seria ambígua.")
            seen.add(name)
            if member.flag_bits & 1:
                raise ImportProblem("ARCHIVE_ENCRYPTED", "ZIP protegido por senha não é suportado.")
            if member.file_size > MAX_FILE_BYTES or (member.file_size > 0 and member.file_size / max(member.compress_size, 1) > MAX_COMPRESSION_RATIO):
                raise ImportProblem("ARCHIVE_EXPANSION", "Membro ZIP excede limite de tamanho ou proporção de descompressão.")
        for member in entries:
            if member.is_dir():
                continue
            if state["expanded"] + member.file_size > MAX_EXPANDED_BYTES:
                raise ImportProblem("ARCHIVE_EXPANSION", "Pacote excede limite total de bytes descompactados.")
            try:
                with archive.open(member) as stream:
                    child = stream.read(MAX_FILE_BYTES + 1)
                    if len(child) > MAX_FILE_BYTES:
                        raise ImportProblem("ARCHIVE_EXPANSION", "Membro ZIP excede limite durante a leitura.")
            except (RuntimeError, NotImplementedError, zipfile.BadZipFile, EOFError, zlib.error):
                raise ImportProblem("ZIP_MEMBER_INVALID", "Membro ZIP corrompido, protegido ou com compressão não suportada.") from None
            state["expanded"] += len(child)
            child_name = f"{filename}!/{member.filename.replace(chr(92), '/')}"
            _parse(child_name, child, company, result, state, depth + 1)
    return "zip"


def _parse(filename, data, company, result, state, depth):
    digest = hashlib.sha256(data).hexdigest()
    source_info = {"file": filename, "sha256": digest, "size": len(data), "format": "unknown"}
    result["sources"].append(source_info)
    if len(data) > MAX_FILE_BYTES:
        raise ImportProblem("FILE_SIZE", "Arquivo excede o limite de 20 MiB; divida o lote.")
    if not data:
        raise ImportProblem("EMPTY_FILE", "Arquivo vazio.")
    suffix = PurePosixPath(filename.lower()).suffix
    try:
        if suffix in (".rar", ".7z") or data.startswith((b"Rar!", b"7z\xbc\xaf\x27\x1c")):
            if depth >= MAX_ARCHIVE_DEPTH:
                raise ImportProblem("ARCHIVE_DEPTH", "Pacote excede dois níveis de contêiner.")
            from .archives import read_archive
            fmt = "7z" if suffix == ".7z" or data.startswith(b"7z") else "rar"
            children=read_archive(fmt,data,state,(MAX_FILE_BYTES,MAX_EXPANDED_BYTES,MAX_ARCHIVE_MEMBERS,MAX_COMPRESSION_RATIO))
            for name,child in children:
                if state["expanded"]+len(child)>MAX_EXPANDED_BYTES:
                    raise ImportProblem("ARCHIVE_EXPANSION", "Lote excede limite total de descompressão.")
                state["expanded"]+=len(child)
                _parse(filename+"!/"+name.replace("\\","/"),child,company,result,state,depth+1)
        elif suffix == ".zip" or data.startswith(b"PK\x03\x04"):
            fmt = _zip(filename, data, company, result, state, depth)
        elif depth > 0 and suffix == ".pdf" and data.startswith(b"%PDF-"):
            # Archive readers have already checked paths, encryption, expansion
            # and integrity. Keep the source/hash but never parse PDF contents.
            # Aggregate the notice later: one warning per PDF would hit
            # MAX_ISSUES and incorrectly block otherwise valid large batches.
            fmt = "pdf"
            source_info["status"] = "ignored"
            source_info["reason"] = "ARCHIVE_PDF_IGNORED"
        elif suffix in (".ofx", ".qfx"):
            fmt = _bank_markup(filename, data, company, result, digest)
        elif suffix == ".ofc":
            fmt = _bank_markup(filename, data, company, result, digest, ofc=True)
        elif suffix == ".qif":
            fmt = _qif(filename, data, company, result, digest)
        elif suffix == ".xml":
            fmt = _xml_document(filename, data, company, result, digest)
        elif suffix in (".txt", ".sped", ".csv", ".efd"):
            preview = _decode(data, _options(company))
            if preview.lstrip().startswith("|0000|"):
                fmt = _sped(filename, data, company, result, digest)
            else:
                fmt = _bank_table(filename, data, company, result, digest)
        else:
            raise ImportProblem("FORMAT_UNSUPPORTED", f"Extensão '{suffix or '(ausente)'}' não suportada. Arquivos executáveis nunca são abertos.")
        source_info["format"] = fmt
        return fmt
    except ImportProblem as problem:
        _issue(result, problem.code, str(problem), _source(filename))
        source_info["status"] = "error"
        return "unsupported" if problem.code.endswith("UNSUPPORTED") else "invalid"


def parse_file(filename: str, data: bytes, company: dict) -> dict:
    """Lê uma fonte para conferência. Erros bloqueiam a confirmação na API.

    A identidade dos movimentos sempre pertence à empresa fornecida pelo backend.
    XML/SPED de outra empresa são recusados. O parser não ativa empresas, grava
    banco, aplica créditos, cria partidas, baixa títulos ou confirma conciliações.
    """
    result = _empty()
    if not isinstance(filename, str) or not filename or len(filename) > 1024:
        _issue(result, "INVALID_FILENAME", "Nome do arquivo inválido.", _source(""))
        return result
    if not isinstance(data, bytes) or not isinstance(company, dict):
        _issue(result, "INVALID_INPUT", "Forneça bytes do arquivo e contexto de empresa válido.", _source(filename))
        return result
    try:
        result["format"] = _parse(filename, data, company, result, {"members": 0, "expanded": 0}, 0)
    except ImportProblem as problem:
        _issue(result, problem.code, str(problem), _source(filename))
    except (csv.Error, ET.ParseError, UnicodeError, zipfile.BadZipFile, OSError, OverflowError, ValueError) as problem:
        _issue(result, "MALFORMED_FILE", f"Arquivo não pôde ser lido integralmente ({type(problem).__name__}). Nenhuma confirmação foi realizada.", _source(filename))
    hints = sorted({x["bank_account_hint"] for x in result["transactions"] if x.get("bank_account_hint")})
    result["bank_account_hints"] = hints
    result["bank_account_hint"] = hints[0] if len(hints) == 1 else None
    if len(hints) > 1 and not any(x["code"] == "MULTIPLE_BANK_ACCOUNTS" for x in result["issues"]):
        _issue(result, "MULTIPLE_BANK_ACCOUNTS", "O lote contém extratos de contas distintas. Separe os arquivos por conta antes de confirmar.", _source(filename))
    ignored_pdfs = sum(source.get("reason") == "ARCHIVE_PDF_IGNORED" for source in result["sources"])
    if ignored_pdfs:
        _issue(result, "ARCHIVE_PDF_IGNORED", f"{ignored_pdfs} PDF(s) acessório(s) ignorado(s) no compactado; não geram documentos fiscais. Consulte as fontes para os nomes e hashes.", _source(filename), "warning")
    result["can_confirm"] = not any(x["severity"] == "error" for x in result["issues"]) and bool(result["documents"] or result["transactions"])
    result["review_required"] = True
    return result
