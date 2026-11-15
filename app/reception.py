"""Read-only fiscal reception protocols. No network, certificate or fiscal event API.

Requests are plans for a future authenticated transport. Response NSUs are evidence;
this module never persists or advances a cursor, even after successful decoding.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
import zlib
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

from .importers import (ImportProblem, MAX_ARCHIVE_MEMBERS, MAX_EXPANDED_BYTES, MAX_FILE_BYTES,
                        _xml_tree)

NFE_NS = 'http://www.portalfiscal.inf.br/nfe'
SOAP_NS = 'http://www.w3.org/2003/05/soap-envelope'
WSDL_NS = NFE_NS + '/wsdl/NFeDistribuicaoDFe'
NFE_ENDPOINTS = {
    'production': 'https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx',
    'homologation': 'https://hom.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx',
}
ADN_ENDPOINTS = {
    'production': 'https://adn.nfse.gov.br/contribuintes',
    'restricted_production': 'https://adn.producaorestrita.nfse.gov.br/contribuintes',
}


def nsu(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,15}', value):
        raise ImportProblem('RECEPTION_NSU', 'NSU deve conter de 1 a 15 dígitos ASCII.')
    return value.zfill(15)


def _tax_id(value):
    # No silent removal of letters from the application's alphanumeric CNPJ.
    if not isinstance(value, str) or not re.fullmatch(r'(?:[0-9]{11}|[0-9]{14})', value):
        raise ImportProblem('RECEPTION_TAX_ID', 'Este contrato remoto aceita CPF/CNPJ numérico sem pontuação; CNPJ alfanumérico ainda depende de homologação própria.')
    return value


def nfe_request(tax_id, uf_code, environment, last_nsu):
    """Build only distNSU. Never builds manifestation, issuance or cancellation."""
    tax_id = _tax_id(tax_id)
    if environment not in NFE_ENDPOINTS:
        raise ImportProblem('RECEPTION_ENVIRONMENT', 'Escolha produção ou homologação para NF-e.')
    if uf_code not in {'11','12','13','14','15','16','17','21','22','23','24','25','26','27','28','29','31','32','33','35','41','42','43','50','51','52','53'}:
        raise ImportProblem('RECEPTION_UF', 'Código IBGE da UF inválido.')
    envelope = ET.Element(f'{{{SOAP_NS}}}Envelope')
    body = ET.SubElement(envelope, f'{{{SOAP_NS}}}Body')
    operation = ET.SubElement(body, f'{{{WSDL_NS}}}nfeDistDFeInteresse')
    message = ET.SubElement(operation, f'{{{WSDL_NS}}}nfeDadosMsg')
    request = ET.SubElement(message, f'{{{NFE_NS}}}distDFeInt', versao='1.01')
    for name, value in [('tpAmb', '1' if environment == 'production' else '2'),
                        ('cUFAutor', uf_code), ('CNPJ' if len(tax_id) == 14 else 'CPF', tax_id)]:
        ET.SubElement(request, f'{{{NFE_NS}}}{name}').text = value
    ET.SubElement(ET.SubElement(request, f'{{{NFE_NS}}}distNSU'), f'{{{NFE_NS}}}ultNSU').text = nsu(last_nsu)
    return {'method': 'POST', 'url': NFE_ENDPOINTS[environment],
            'content_type': 'application/soap+xml; charset=utf-8',
            'body': ET.tostring(envelope, encoding='utf-8', xml_declaration=True),
            'network_executed': False}


def adn_request(tax_id, environment, last_nsu, *, certificate_tax_id=None, allow_procuration=False):
    """Always target the selected company, including same-base/procuration queries."""
    tax_id = _tax_id(tax_id)
    if environment not in ADN_ENDPOINTS:
        raise ImportProblem('RECEPTION_ENVIRONMENT', 'Escolha produção ou produção restrita para NFS-e ADN.')
    mode = None
    if certificate_tax_id is not None:
        from .reception_credentials import adn_access_mode
        mode = adn_access_mode(tax_id, certificate_tax_id, allow_procuration)
    query = '' if mode == 'InscricaoCertificado' else urlencode({'cnpjConsulta' if len(tax_id) == 14 else 'cpfConsulta': tax_id})
    return {'method': 'GET', 'url': ADN_ENDPOINTS[environment] + '/DFe/' + nsu(last_nsu) + ('?' + query if query else ''),
            'expected_authorization_mode': mode,
            'network_executed': False, 'authorization_verified': False}


def adn_rejection(payload, last_nsu):
    """Normalize documented rejections only. Do not guess the success JSON schema."""
    cursor = nsu(last_nsu)
    if not isinstance(payload, dict) or not isinstance(payload.get('Erros'), list) or not payload['Erros']:
        raise ImportProblem('ADN_RESPONSE_UNSUPPORTED', 'Resposta de sucesso ADN ainda não integrada; preserve a origem e o cursor.')
    codes = []
    for error in payload['Erros']:
        if not isinstance(error, dict) or not isinstance(error.get('Codigo'), str) or not re.fullmatch(r'E[0-9]{3,4}', error['Codigo']):
            raise ImportProblem('ADN_RESPONSE_INVALID', 'Código de rejeição ADN inválido; cursor preservado.')
        codes.append(error['Codigo'])
    return {'provider': 'nfse_adn', 'state': 'authorization_pending' if 'E2245' in codes else 'rejected',
            'error_codes': codes, 'last_nsu': cursor, 'cursor_advance_allowed': False,
            'authorization_verified': False}


def is_nfe_distribution(root):
    if root.tag == f'{{{NFE_NS}}}retDistDFeInt':
        return True
    return root.tag == f'{{{SOAP_NS}}}Envelope' and bool(list(root.iter(f'{{{NFE_NS}}}retDistDFeInt')))


def _one_text(root, name):
    matches = root.findall(f'{{{NFE_NS}}}{name}')
    if len(matches) != 1 or not matches[0].text:
        raise ImportProblem('RECEPTION_RESPONSE_INVALID', 'Retorno de distribuição sem campo único: ' + name + '.')
    return matches[0].text.strip()


def _inflate(encoded, state):
    if not isinstance(encoded, str) or len(encoded) > 28_000_000:
        raise ImportProblem('RECEPTION_SIZE', 'docZip excede limite técnico.')
    try:
        compressed = base64.b64decode(''.join(encoded.split()), validate=True)
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        maximum = min(MAX_FILE_BYTES, MAX_EXPANDED_BYTES - state['expanded'])
        if maximum <= 0:
            raise ImportProblem('RECEPTION_EXPANSION', 'Distribuição excede limite total de descompressão.')
        raw = decoder.decompress(compressed, maximum + 1)
        if len(raw) > maximum or decoder.unconsumed_tail:
            raise ImportProblem('RECEPTION_EXPANSION', 'Distribuição excede limite total de descompressão.')
        if not decoder.eof or decoder.unused_data or not raw:
            raise ImportProblem('RECEPTION_GZIP', 'docZip deve conter um GZip completo, sem dados extras.')
    except (binascii.Error, zlib.error, ValueError) as exc:
        if isinstance(exc, ImportProblem):
            raise
        raise ImportProblem('RECEPTION_GZIP', 'docZip não contém base64/GZip válido.') from None
    state['expanded'] += len(raw)
    return raw


def read_nfe_distribution(data, state=None):
    if len(data) > MAX_FILE_BYTES:
        raise ImportProblem('RECEPTION_SIZE', 'Resposta de distribuição excede 20 MiB.')
    root = _xml_tree(data)
    if not is_nfe_distribution(root):
        raise ImportProblem('RECEPTION_LAYOUT', 'Retorno não é distribuição NF-e no namespace oficial.')
    returns = list(root.iter(f'{{{NFE_NS}}}retDistDFeInt'))
    if len(returns) != 1 or returns[0].get('versao') != '1.01':
        raise ImportProblem('RECEPTION_RESPONSE_INVALID', 'Esperado um retorno de distribuição NF-e 1.01.')
    response = returns[0]
    environment, status = _one_text(response, 'tpAmb'), _one_text(response, 'cStat')
    if environment not in {'1', '2'} or not re.fullmatch(r'[0-9]{3}', status):
        raise ImportProblem('RECEPTION_RESPONSE_INVALID', 'Ambiente ou status inválido na distribuição.')
    last = nsu(_one_text(response, 'ultNSU')) if status in {'137','138'} else None
    maximum = nsu(_one_text(response, 'maxNSU')) if status in {'137','138'} else None
    if last is not None and last > maximum:
        raise ImportProblem('RECEPTION_NSU', 'Último NSU excede o máximo declarado.')
    packets = list(response.iter(f'{{{NFE_NS}}}docZip'))
    if len(packets) > 50 or (status == '138') != bool(packets):
        raise ImportProblem('RECEPTION_RESPONSE_INVALID', 'Quantidade de documentos incompatível com o retorno.')
    state = state if state is not None else {'members': 0, 'expanded': 0}
    state['members'] += len(packets)
    if state['members'] > MAX_ARCHIVE_MEMBERS:
        raise ImportProblem('RECEPTION_MEMBERS', 'Lote excede limite total de documentos compactados.')
    seen, entries = set(), []
    for packet in packets:
        current = nsu(packet.get('NSU'))
        if current in seen or current == '000000000000000' or current > last:
            raise ImportProblem('RECEPTION_NSU', 'NSU repetido ou fora do intervalo declarado.')
        seen.add(current)
        raw = _inflate(packet.text, state)
        xml = _xml_tree(raw)
        schema = packet.get('schema', '')
        kind, reason = 'unsupported', 'Documento distribuído sem leitor homologado; original preservado.'
        if xml.tag == f'{{{NFE_NS}}}nfeProc' and schema == 'procNFe_v4.00.xsd':
            infos = list(xml.iter(f'{{{NFE_NS}}}infNFe'))
            if len(infos) != 1 or infos[0].findtext(f'{{{NFE_NS}}}ide/{{{NFE_NS}}}tpAmb') != environment:
                raise ImportProblem('RECEPTION_ENVIRONMENT', 'Ambiente do XML difere do retorno de distribuição.')
            if infos[0].findtext(f'{{{NFE_NS}}}ide/{{{NFE_NS}}}mod') == '55':
                kind, reason = 'full_xml', ''
        elif xml.tag == f'{{{NFE_NS}}}resNFe' and schema == 'resNFe_v1.01.xsd':
            kind, reason = 'summary', 'Resumo sem XML íntegro; aguarda obtenção por meio autorizado. Nenhuma manifestação é executada.'
        elif xml.tag in {f'{{{NFE_NS}}}procEventoNFe', f'{{{NFE_NS}}}resEvento'}:
            kind, reason = 'event', 'Evento recebido como evidência; sem alteração automática de documento ou estado fiscal.'
        entries.append({'nsu': current, 'schema': schema, 'kind': kind, 'reason': reason,
                        'sha256': hashlib.sha256(raw).hexdigest(), 'xml': raw})
    return {'provider': 'nfe_distribution', 'environment': environment, 'status_code': status,
            'reported_last_nsu': last, 'reported_max_nsu': maximum,
            'cooldown_seconds': 3600 if status in {'137','656'} or (last is not None and last == maximum) else 0,
            'cursor_advance_allowed': False, 'network_executed': False,
            'entries': entries}


def ensure_reception_open(conn, company_id, posting_date):
    """New reception writes require reopening even if legacy lock checks are optional."""
    from .core import DomainError, ensure_open, iso_date
    competence = iso_date(posting_date, 'Escrituração')[:7]
    ensure_open(conn, company_id, competence, 'fiscal')
    lock = conn.execute('SELECT closed FROM period_locks WHERE company_id=? AND period=? AND module=?',
                        (company_id, competence, 'fiscal')).fetchone()
    if lock and lock['closed']:
        raise DomainError('Reabra a competência ' + competence + ' antes de importar a recepção.', 409, 'period_closed')
