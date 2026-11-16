"""Pinned ECF reference metadata, not a table importer or tax assessment engine.

Selection requires an explicit immutable revision id. Publication, layout scope
and each row's effectivity are separate; no current/latest fallback is allowed.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from ..core import DomainError, digest, iso_date, pack

CATALOG_PATH = Path(__file__).resolve().parents[1] / 'data' / 'ecf-reference-catalog.json'
API_PATH = '/api/sped/ecf-references'


def load_catalog():
    return json.loads(CATALOG_PATH.read_text(encoding='utf-8'))


def official_url(value):
    if not isinstance(value, str):
        return False
    try:
        url = urlsplit(value)
        return (url.scheme == 'https' and not url.username and not url.password
                and url.port in (None, 443)
                and ((url.hostname == 'www.gov.br' and url.path.startswith('/sped/'))
                     or (url.hostname == 'sped.rfb.gov.br' and url.path.startswith(('/item/', '/arquivo/', '/estatico/')))))
    except ValueError:
        return False


def valid_digest(value):
    return isinstance(value, str) and bool(re.fullmatch('[0-9a-f]{64}', value))


def verify_artifact_bytes(content, reference):
    """Compare actual supplied bytes with a pinned descriptor, without any I/O.

    A digest match is integrity evidence, not a detached publisher signature.
    This helper neither downloads a URL nor imports/executes workbook content.
    """
    reference = reference if isinstance(reference, dict) else {}
    is_bytes = isinstance(content, (bytes, bytearray))
    actual = hashlib.sha256(content).hexdigest() if is_bytes else None
    source_ok = official_url(reference.get('download_url'))
    hash_ok = valid_digest(reference.get('sha256')) and actual == reference['sha256']
    size_ok = type(reference.get('bytes')) is int and is_bytes and len(content) == reference['bytes']
    return {'sha256': actual, 'source_url_official': source_ok, 'hash_matches': hash_ok,
            'size_matches': size_ok, 'matches_pinned_reference': source_ok and hash_ok and size_ok,
            'publisher_signature_verified': False}


def select_reference(request, catalog=None):
    catalog = deepcopy(load_catalog() if catalog is None else catalog)
    warnings = []
    result = {'status': 'unresolved', 'selected_reference': None, 'selection_sha256': None,
              'can_export_catalog': True, 'rows_selected': False, 'client_plan_materialized': False,
              'generates_ecf': False, 'official_program_validated': False, 'warnings': warnings}
    def warn(code, message):
        warnings.append({'code': code, 'message': message, 'blocking_export': False})
    if not isinstance(request, dict):
        warn('INVALID_REQUEST', 'Informe os campos explícitos da consulta de referências.')
        return result
    if not isinstance(catalog, dict) or not isinstance(catalog.get('revisions'), list) or not isinstance(catalog.get('scope_rules'), list):
        warn('INVALID_CATALOG_METADATA', 'Estrutura do catálogo não verificável; nenhuma referência foi selecionada.')
        return result
    allowed = {'start', 'end', 'situation', 'event_date', 'revision_id', 'sheet'}
    if set(request) - allowed:
        warn('UNKNOWN_SELECTION_FIELDS', 'Há campos não reconhecidos; regime/empresa não são inferidos.')
        return result
    normalized = {key: request.get(key) for key in sorted(allowed)}
    if any(isinstance(value, list) and len(value) > 1 for value in normalized.values()):
        warn('AMBIGUOUS_SELECTION_VALUE', 'Há valores repetidos para o mesmo campo; nenhuma escolha automática foi feita.')
        return result
    if any(value is not None and not isinstance(value, str) for value in normalized.values()):
        warn('INVALID_FIELD_TYPE', 'Datas, código de situação e revisão devem ser textos explícitos.')
        return result
    try:
        start, end = iso_date(request.get('start'), 'Início'), iso_date(request.get('end'), 'Fim')
        if start > end or start[:4] != end[:4]:
            raise DomainError('Intervalo invertido ou entre exercícios não coberto pelo catálogo.')
    except DomainError:
        warn('INVALID_OR_UNCOVERED_INTERVAL', 'Use datas ISO válidas e intervalo ordenado de um exercício; nenhuma data é presumida.')
        return result
    normalized.update(start=start, end=end)
    situation = request.get('situation')
    if situation not in tuple(str(value) for value in range(10)):
        warn('SITUATION_REQUIRED_OR_UNKNOWN', 'Informe explicitamente 0000.SIT_ESPECIAL de 0 a 9.')
        return result
    event_date = request.get('event_date')
    if situation == '0':
        if event_date is not None:
            warn('NORMAL_WITH_EVENT_DATE', 'A seleção normal e a data de evento fornecida exigem revisão explícita.')
            return result
    else:
        try:
            event_date = iso_date(event_date, 'Evento')
            if not start <= event_date <= end:
                raise DomainError('Evento fora do intervalo consultado.')
        except DomainError:
            warn('EVENT_DATE_REQUIRED_OR_OUTSIDE_SCOPE', 'Informe a data do evento dentro do recorte consultado; ela não é inferida do fim do período.')
            return result
        normalized['event_date'] = event_date
    revision_id = request.get('revision_id')
    if not revision_id:
        warn('EXPLICIT_REVISION_REQUIRED', 'Escolha uma revisão por ID; a versão mais recente nunca é aplicada automaticamente.')
        return result
    matches = [item for item in catalog['revisions'] if isinstance(item, dict) and item.get('id') == revision_id]
    if not matches:
        warn('UNKNOWN_REVISION', 'Revisão não catalogada; não houve substituição por outra versão.')
        return result
    if len(matches) != 1:
        warn('AMBIGUOUS_REVISION', 'Há mais de uma definição para a revisão; nenhuma foi escolhida.')
        return result
    reference = matches[0]
    if not isinstance(reference.get('layout'), str):
        warn('INVALID_REFERENCE_METADATA', 'Leiaute da revisão não foi declarado; nenhum foi presumido.')
        return result
    eligible = any(isinstance(rule, dict) and rule.get('layout') == reference['layout']
                   and rule.get('calendar_year') == int(start[:4])
                   and isinstance(rule.get('situation_codes'), list) and situation in rule['situation_codes']
                   for rule in catalog['scope_rules'])
    if not eligible:
        warn('LAYOUT_SCOPE_NOT_CATALOGUED', 'O leiaute da revisão não tem cobertura registrada para esse ano/situação; datas internas de linhas não ampliam o leiaute.')
        return result
    if reference.get('verified_payload') is not True:
        warn('HISTORICAL_BYTES_NOT_VERIFIED', 'A revisão é conhecida pelo comunicado, mas seu arquivo/hash histórico não foi recuperado. Não se usa o arquivo atual em seu lugar.')
        return result
    if (not official_url(reference.get('source_page')) or not official_url(reference.get('download_url'))
            or not valid_digest(reference.get('sha256')) or type(reference.get('bytes')) is not int
            or reference['bytes'] <= 0):
        warn('UNTRUSTED_OR_INCOMPLETE_PROVENANCE', 'A procedência HTTPS oficial, tamanho ou hash da referência não são verificáveis.')
        return result
    if reference.get('kind') != 'dynamic_tables_and_reference_charts':
        warn('REFERENCE_KIND_NOT_SUPPORTED', 'A referência não é o pacote de tabelas/planos deste contrato.')
        return result
    sheets = reference.get('sheets')
    if not isinstance(sheets, dict):
        warn('SHEET_INVENTORY_UNAVAILABLE', 'Inventário do arquivo não foi conferido; nenhuma aba é presumida.')
        return result
    sheet = request.get('sheet')
    selected_sheet = None
    if sheet is None:
        warn('SHEET_NOT_SELECTED', 'Selecionado somente o manifesto do pacote; escolha uma aba explicitamente para a próxima etapa.')
    elif sheet not in sheets:
        warn('UNKNOWN_SHEET', 'Aba não encontrada nessa revisão; não se procura automaticamente em outra revisão.')
        return result
    elif sheet == 'INDICE':
        warn('INDEX_IS_NOT_REFERENCE_TABLE', 'A aba de índice não representa seleção de linhas ou plano referencial.')
        return result
    elif not isinstance(sheets[sheet], dict) or type(sheets[sheet].get('has_validity_columns')) is not bool:
        warn('INVALID_SHEET_METADATA', 'Estrutura da aba não verificável; vigências não foram presumidas.')
        return result
    else:
        selected_sheet = {'name': sheet, **sheets[sheet]}
        if not sheets[sheet]['has_validity_columns']:
            warn('NO_ROW_DATE_COLUMNS', 'A aba não apresenta DT_INI/DT_FIM no cabeçalho conferido; vigência por linha não foi inventada.')
    selected = {key: deepcopy(value) for key, value in reference.items() if key != 'sheets'}
    selected['selected_sheet'] = selected_sheet
    selected['selection_scope'] = 'pinned_artifact_manifest_only'
    selected['row_effectivity_validated'] = False
    warn('ROW_EFFECTIVITY_NOT_SELECTED', 'Datas DT_INI/DT_FIM devem ser avaliadas por linha; este incremento não importa linhas nem executa fórmulas.')
    warn('ARCHIVE_NOT_BUNDLED', 'O binário não integra a aplicação; o URL pode mudar. Download futuro precisa conferir o hash fixado, sem aceitar silenciosamente conteúdo novo.')
    result.update(status='selected_manifest', selected_reference=selected,
                  selection_sha256=digest({'request': normalized, 'reference': selected}))
    return result


def reference_response(request):
    catalog = load_catalog()
    return {'schema_version': 1, 'catalog': catalog, 'catalog_sha256': digest(catalog),
            'selection': select_reference(request, catalog), 'read_only': True}


def register_ecf_reference_routes(app):
    from fastapi import Request
    from fastapi.responses import Response
    @app.get(API_PATH)
    def ecf_references(request: Request):
        # Retain repeated/unknown keys for diagnostics instead of taking a last value.
        query = {key: request.query_params.getlist(key) if len(request.query_params.getlist(key)) > 1
                 else request.query_params[key] for key in request.query_params}
        result = reference_response(query)
        return Response(pack(result) + '\n', media_type='application/json', headers={
            'Cache-Control': 'no-store', 'Content-Disposition': 'attachment; filename="ecf-referencias.json"'})
