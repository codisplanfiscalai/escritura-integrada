"""Read explicit, company-owned preparation declarations; never apply tax rules."""
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from ..core import DomainError, digest, iso_date, period as validate_period
from ..permissions import readable

NAMESPACE = 'contributions_preparation_v1'
CATALOG_PATH = Path(__file__).resolve().parents[1] / 'data/contributions-reference-catalog.json'
COMPANY_FIELDS = ('COD_INC_TRIB', 'IND_APRO_CRED', 'COD_TIPO_CONT', 'IND_REG_CUM')
ITEM_FIELDS = ('CST_PIS', 'CST_COFINS')


def load_catalog():
    return json.loads(CATALOG_PATH.read_text(encoding='utf-8'))


def select_reference(competence, revision_id, catalog):
    result = {'status': 'unresolved', 'reference': None, 'reference_sha256': None,
              'diagnostics': [], 'official_applicability_validated': False}
    def problem(code):
        result['diagnostics'].append({'code': code, 'blocking_export': False})
        return result
    try:
        if validate_period(competence) != competence:
            raise DomainError('Competência não canônica.')
    except DomainError:
        return problem('INVALID_REFERENCE_PERIOD')
    if not isinstance(revision_id, str) or not revision_id:
        return problem('EXPLICIT_REFERENCE_REQUIRED')
    revisions = [r for r in catalog.get('revisions', []) if isinstance(r, dict) and r.get('id') == revision_id]
    if len(revisions) != 1:
        return problem('UNKNOWN_REFERENCE' if not revisions else 'AMBIGUOUS_REFERENCE')
    revision = revisions[0]
    if not revision['reviewed_period_start'] <= competence <= revision['reviewed_period_end']:
        return problem('PERIOD_NOT_REVIEWED_FOR_REFERENCE')
    sources = []
    for source_id in revision['source_ids']:
        matches = [source for source in catalog['sources'] if source['id'] == source_id]
        if len(matches) != 1:
            return problem('REFERENCE_SOURCE_NOT_UNIQUE')
        source = matches[0]
        url = urlsplit(source.get('url', ''))
        if (url.scheme != 'https' or url.hostname != 'www.gov.br' or not url.path.startswith('/sped/')
                or url.username or url.password or source.get('verified_payload') is not True
                or type(source.get('bytes')) is not int or source['bytes'] <= 0
                or not isinstance(source.get('sha256'), str)
                or not re.fullmatch('[0-9a-f]{64}', source['sha256'])):
            return problem('UNVERIFIED_REFERENCE_PROVENANCE')
        sources.append(deepcopy(source))
    pinned = {'revision': deepcopy(revision), 'sources': sources}
    result.update(status='pinned_for_preparation', reference=pinned, reference_sha256=digest(pinned))
    return result


def _unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Chave JSON duplicada.')
        value[key] = item
    return value


def _invalid_constant(value):
    raise ValueError('Constante JSON não finita.')


def review_declaration(declaration, source, cid, competence, catalog):
    row = {'source': deepcopy(source), 'declaration': deepcopy(declaration),
           'declaration_sha256': digest(declaration), 'diagnostics': [],
           'declared_fields': {}, 'missing_fields': [], 'reference_selection': None,
           'classification_applied': False, 'operation_applicability_validated': False,
           'eligible_for_preparation_review': False}
    def problem(code):
        row['diagnostics'].append({'code': code, 'blocking_export': False})
    if not isinstance(declaration, dict):
        problem('DECLARATION_NOT_OBJECT')
        return row
    d = declaration
    allowed = {'id', 'revision', 'company_id', 'scope', 'direction', 'valid_from', 'valid_to',
               'reference_id', 'source', 'source_sha256', 'responsible', 'declared_on', 'fields'}
    if set(d) - allowed:
        problem('UNSUPPORTED_DECLARATION_FIELDS')
    for name in ('id', 'revision', 'source', 'responsible'):
        if not isinstance(d.get(name), str) or not d[name].strip() or d[name] != d[name].strip():
            problem('MISSING_OR_NONCANONICAL_' + name.upper())
    if not isinstance(d.get('source_sha256'), str) or not re.fullmatch('[0-9a-f]{64}', d['source_sha256']):
        problem('DECLARATION_SOURCE_HASH_REQUIRED')
    try:
        if iso_date(d.get('declared_on')) != d['declared_on']:
            raise DomainError('Data não canônica.')
    except DomainError:
        problem('DECLARATION_DATE_REQUIRED')
    if type(d.get('company_id')) is not int or d['company_id'] != cid:
        problem('DECLARATION_COMPANY_MISMATCH')
    expected_scope = 'company' if source['kind'] == 'establishment' else 'item'
    if d.get('scope') != expected_scope:
        problem('DECLARATION_SCOPE_MISMATCH')
    if expected_scope == 'item' and d.get('direction') not in ('incoming', 'outgoing'):
        problem('EXPLICIT_DIRECTION_REQUIRED')
    if expected_scope == 'company' and d.get('direction') is not None:
        problem('COMPANY_DECLARATION_WITH_ITEM_DIRECTION')
    covers = False
    try:
        start, end = validate_period(d.get('valid_from')), validate_period(d.get('valid_to'))
        if start != d['valid_from'] or end != d['valid_to'] or start > end:
            raise DomainError('Intervalo inválido.')
        covers = start <= competence <= end
        if not covers:
            problem('OUTSIDE_DECLARED_PERIOD')
    except DomainError:
        problem('EXPLICIT_DECLARATION_PERIOD_REQUIRED')
    if not source['active']:
        problem('INACTIVE_DECLARATION_MASTER')
    selection = select_reference(competence, d.get('reference_id'), catalog)
    row['reference_selection'] = selection
    if selection['reference'] is None:
        problem('REFERENCE_NOT_RESOLVED')
    fields = d.get('fields')
    expected = COMPANY_FIELDS if expected_scope == 'company' else ITEM_FIELDS
    if not isinstance(fields, dict):
        problem('DECLARED_FIELDS_NOT_OBJECT')
        fields = {}
    if set(fields) - set(expected):
        problem('UNSUPPORTED_CLASSIFICATION_FIELDS')
    row['declared_fields'] = {key: deepcopy(fields[key]) for key in expected if key in fields}
    row['missing_fields'] = [key for key in expected if fields.get(key) in (None, '')]
    # Conditional legal requiredness is deliberately not inferred from the regime.
    # Unknown optional fields stay absent; do not manufacture a regime-dependent default.
    required = ('COD_INC_TRIB',) if expected_scope == 'company' else ()
    if (any(key in row['missing_fields'] for key in required)
            or not any(fields.get(key) not in (None, '') for key in expected)):
        problem('FIELDS_MISSING_FOR_REVIEW')
    row['conditional_requiredness_evaluated'] = False
    if selection['reference'] is not None:
        reference = selection['reference']; revision = reference['revision']
        by_id = {source['id']: source for source in reference['sources']}
        for key, value in row['declared_fields'].items():
            if value in (None, ''):
                continue
            codes = (revision['regime_0110_codes'][key] if expected_scope == 'company'
                     else by_id[revision['cst_source_ids'][key]]['codes'])
            if not isinstance(value, str) or value not in codes:
                problem('CODE_NOT_LISTED_IN_PINNED_REFERENCE_' + key)
    row['eligible_for_preparation_review'] = covers and not row['diagnostics']
    return row


def declaration_review(conn, cid, competence, catalog=None):
    catalog = deepcopy(load_catalog() if catalog is None else catalog)
    result = {'namespace': NAMESPACE, 'catalog': catalog, 'catalog_sha256': digest(catalog),
              'records': [], 'groups': [], 'classification_applied': False,
              'resolved_company_fields': None, 'operation_applicability_validated': False}
    if not readable(conn, cid, 'fiscal.masters'):
        result.update(status='not_authorized', records=None,
                      diagnostics=[{'code': 'MASTERS_READ_PERMISSION_REQUIRED', 'blocking_export': False}])
        return result
    for master in conn.execute("SELECT id,kind,code,version,active,data_json FROM masters WHERE company_id=? AND kind IN ('establishment','product','service') ORDER BY kind,code,id", (cid,)):
        source = {key: master[key] for key in ('id', 'kind', 'code', 'version', 'active')}
        source['active'] = bool(source['active'])
        try:
            data = json.loads(master['data_json'], object_pairs_hook=_unique_pairs, parse_constant=_invalid_constant)
            if not isinstance(data, dict):
                raise ValueError('Dados cadastrais não são objeto.')
        except (ValueError, TypeError):
            result['records'].append({'source': source, 'metadata_sha256': digest(master['data_json']),
                'diagnostics': [{'code': 'UNREADABLE_OR_AMBIGUOUS_MASTER_METADATA', 'blocking_export': False}],
                'eligible_for_preparation_review': False})
            continue
        if NAMESPACE not in data:
            continue
        declarations = data[NAMESPACE]
        if not isinstance(declarations, list):
            result['records'].append({'source': source, 'declaration': deepcopy(declarations),
                'declaration_sha256': digest(declarations), 'eligible_for_preparation_review': False,
                'diagnostics': [{'code': 'DECLARATIONS_NOT_LIST', 'blocking_export': False}]})
            continue
        for position, declaration in enumerate(declarations):
            result['records'].append(review_declaration(declaration, source | {'declaration_position': position}, cid, competence, catalog))
    duplicates = Counter((r['declaration']['id'], r['declaration']['revision']) for r in result['records']
        if isinstance(r.get('declaration'), dict) and isinstance(r['declaration'].get('id'), str)
        and isinstance(r['declaration'].get('revision'), str))
    groups = defaultdict(list)
    for index, row in enumerate(result['records']):
        declaration = row.get('declaration')
        if (isinstance(declaration, dict) and isinstance(declaration.get('id'), str)
                and isinstance(declaration.get('revision'), str)
                and duplicates.get((declaration['id'], declaration['revision']), 0) > 1):
            row['eligible_for_preparation_review'] = False
            row['diagnostics'].append({'code': 'DUPLICATE_DECLARATION_REVISION', 'blocking_export': False})
        if row['eligible_for_preparation_review']:
            key = ('company', None) if declaration['scope'] == 'company' else (str(row['source']['id']), declaration['direction'])
            groups[key].append(index)
    for (target, direction), indexes in sorted(groups.items(), key=lambda pair: str(pair[0])):
        result['groups'].append({'target': target, 'direction': direction, 'record_indexes': indexes,
                                 'status': 'ambiguous' if len(indexes) > 1 else 'declared_for_review'})
        if len(indexes) > 1:
            for index in indexes:
                result['records'][index]['diagnostics'].append({'code': 'OVERLAPPING_DECLARATIONS', 'blocking_export': False})
                result['records'][index]['eligible_for_preparation_review'] = False
    result['status'] = 'absent' if not result['records'] else 'declarations_observed'
    return result
