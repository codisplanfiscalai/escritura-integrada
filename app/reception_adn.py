"""ADN JSON distribution profile recovered from the user's captured OpenAPI.

See docs/RECEPCAO_DFE_NFSE.md for provenance/hash and external validation limits.
This reads transport packets, not fiscal amounts, signatures or bookkeeping.
"""
import hashlib
import json
import re
from datetime import datetime

from .importers import ImportProblem, MAX_ARCHIVE_MEMBERS, MAX_FILE_BYTES, _xml_tree
from .reception import _inflate, adn_nsu

PROFILE = 'adn-contribuintes-json-v1-recovered-271e9577'
NFSE_NS = 'http://www.sped.fazenda.gov.br/nfse'
TOP_FIELDS = {'TipoConsulta','StatusProcessamento','LoteDFe','Alertas','Erros','TipoAmbiente','VersaoAplicativo','DataHoraProcessamento'}
PACKET_FIELDS = {'NSU','ChaveAcesso','TipoDocumento','TipoEvento','ArquivoXml','DataHoraGeracao'}
KINDS = {'NFSE','EVENTO','DPS','PEDIDO_REGISTRO_EVENTO','CNC'}


def _invalid(code='ADN_RESPONSE_INVALID'):
    raise ImportProblem(code, 'Resposta ADN pendente de revisão; original e cursor devem ser preservados.')


def _pairs(items):
    result = {}
    for name, value in items:
        if name in result:
            _invalid('ADN_JSON_DUPLICATE')
        result[name] = value
    return result


def load_adn_json(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_FILE_BYTES:
        _invalid('ADN_RESPONSE_SIZE')
    try:
        return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_pairs,
                          parse_constant=lambda _: _invalid('ADN_JSON_INVALID'))
    except (UnicodeError, ValueError, RecursionError) as error:
        if isinstance(error, ImportProblem):
            raise
        _invalid('ADN_JSON_INVALID')


def _date(value, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value,str) or len(value)>64:
        _invalid()
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is None:
            _invalid()
    except ValueError:
        _invalid()
    return value  # Declared processing/generation time; never posting date.


def _optional_text(value):
    if value is not None and (not isinstance(value,str) or len(value)>256 or any(ord(c)<32 for c in value)):
        _invalid()
    return value


def read_adn_distribution(payload, cursor, environment, expected_mode):
    """Decode an entire known success page or hold it entirely, never partially.

    Cursor candidate is max returned NSU (exclusive GET contract), and only the
    service may commit it after storing both envelope and every decoded original.
    """
    if not isinstance(payload,dict) or set(payload)-TOP_FIELDS:
        _invalid('ADN_RESPONSE_UNSUPPORTED')
    if payload.get('StatusProcessamento') != 'DOCUMENTOS_LOCALIZADOS':
        _invalid('ADN_RESPONSE_UNSUPPORTED')
    if expected_mode not in {'InscricaoCertificado','CnpjBase','Procuracao'} or payload.get('TipoConsulta') != expected_mode:
        _invalid('ADN_AUTHORIZATION_MISMATCH')
    if payload.get('TipoAmbiente') != {'production':'PRODUCAO','restricted_production':'HOMOLOGACAO'}.get(environment):
        _invalid('ADN_ENVIRONMENT_MISMATCH')
    if payload.get('Erros') not in (None,[]):
        _invalid('ADN_ERRORS_PRESENT')
    # Alert semantics are not inferred; retain page for review without advancing.
    if payload.get('Alertas') not in (None,[]):
        _invalid('ADN_ALERT_REVIEW')
    processed=_date(payload.get('DataHoraProcessamento'))
    _optional_text(payload.get('VersaoAplicativo'))
    packets=payload.get('LoteDFe')
    if not isinstance(packets,list) or not 1 <= len(packets) <= MAX_ARCHIVE_MEMBERS:
        _invalid('ADN_LOT_INVALID')
    old=int(adn_nsu(cursor))
    seen,entries=set(),[]
    budget={'expanded':0}
    for packet in packets:
        if not isinstance(packet,dict) or set(packet)-PACKET_FIELDS:
            _invalid('ADN_RESPONSE_UNSUPPORTED')
        current=packet.get('NSU')
        if type(current) is not int or current <= old or current in seen:
            _invalid('ADN_NSU')
        number=adn_nsu(current)
        seen.add(current)
        kind=packet.get('TipoDocumento')
        if not isinstance(kind,str) or kind not in KINDS:
            _invalid('ADN_DOCUMENT_TYPE')
        key=_optional_text(packet.get('ChaveAcesso'))
        event=_optional_text(packet.get('TipoEvento'))
        generated=_date(packet.get('DataHoraGeracao'),nullable=True)
        if not packet.get('ArquivoXml'):
            _invalid('ADN_XML_MISSING')
        raw=_inflate(packet['ArquivoXml'],budget)
        try:
            text=raw.decode('utf-8-sig')
        except UnicodeError:
            _invalid('ADN_XML_ENCODING')
        declaration=re.match(r'\s*<\?xml\b[^?]*\?>',text)
        if declaration and re.search(r'encoding\s*=\s*[\'"](?!utf-8[\'"])[^\'"]+',declaration[0],re.I):
            _invalid('ADN_XML_ENCODING')
        root=_xml_tree(raw)
        if kind=='NFSE' and (root.tag != '{'+NFSE_NS+'}NFSe' or len(root.findall('{'+NFSE_NS+'}infNFSe')) != 1):
            _invalid('ADN_XML_LAYOUT')
        entries.append({'nsu':number,'document_type':kind,'access_key':key,'event_type':event,
                        'generation_time':generated,'xml_root':root.tag,'sha256':hashlib.sha256(raw).hexdigest(),
                        'bytes':len(raw),'xml':raw,'review_pending':True,
                        'reason':'nfse_bookkeeping_reader_pending' if kind=='NFSE' else 'received_xml_without_fiscal_effect'})
    return {'contract_profile':PROFILE,'authorization_mode':expected_mode,'authorization_verified':True,
            'processing_time':processed,'entries':entries,'reported_last_nsu':adn_nsu(max(seen)),
            'review_pending':True}
