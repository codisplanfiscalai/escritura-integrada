"""Inspect explicit ECD preparation declarations; never classify or attest data.

The optional native-plan namespace is additive to existing preserved extras.
Only these four declared I050 fields are read. No Prosoft field, classifier,
report group, D/C nature, opening journal or arithmetic zero is a substitute.
"""
import json
from collections import Counter
from copy import deepcopy
from ..core import DomainError, digest, iso_date

NAMESPACE = 'ecd_preparation_v1'
FIELDS = ('DT_ALT', 'COD_NAT', 'NIVEL', 'COD_CTA_SUP')
NATURE_CODES = frozenset(('01', '02', '03', '04', '05', '09'))


def _invalid_json_constant(value):
    raise ValueError('Constante JSON não finita: ' + value)


def declared_metadata(conn, cid):
    """Same local-before-shared metadata precedence as AccountPlansMixin._plan_state."""
    result = {}
    for row in conn.execute('''SELECT a.id,COALESCE(m.extras_json,g.extras_json,'{}') AS extras,
        m.batch_id,g.global_plan_id,g.id AS shared_entry_id FROM effective_accounts a
        LEFT JOIN account_plan_metadata m ON m.account_id=a.id AND m.company_id=a.company_id
        LEFT JOIN global_account_entries g ON g.id=a.shared_entry_id
        WHERE a.company_id=? ORDER BY a.id''', (cid,)):
        source = {'batch_id': row['batch_id'], 'global_plan_id': row['global_plan_id'],
                  'shared_entry_id': row['shared_entry_id'],
                  'kind': 'local_account_metadata' if row['batch_id'] is not None else
                          'shared_entry_metadata' if row['shared_entry_id'] is not None else 'absent'}
        try:
            extra = json.loads(row['extras'], parse_constant=_invalid_json_constant)
            namespace_hash = digest(extra[NAMESPACE]) if isinstance(extra, dict) and NAMESPACE in extra else None
        except (ValueError, TypeError, UnicodeError):
            extra, namespace_hash = None, None
        if not isinstance(extra, dict):
            result[row['id']] = {'present': False, 'malformed_metadata': True,
                'source': source, 'metadata_sha256': digest(row['extras'])}
        else:
            result[row['id']] = {'present': NAMESPACE in extra, 'value': extra.get(NAMESPACE),
                'source': source, 'metadata_sha256': namespace_hash}
    return result


def _cycles(edges):
    """Functional-graph walk, iterative and linear even with a very deep plan."""
    done, found = set(), []
    for start in sorted(edges):
        path, positions, current = [], {}, start
        while current in edges and current not in done and current not in positions:
            positions[current] = len(path)
            path.append(current)
            current = edges[current]
        if current in positions:
            found.append(sorted(path[positions[current]:]))
        done.update(path)
    return sorted(found)


def account_review(accounts, metadata, end):
    by_code = {}
    for account in accounts:
        by_code.setdefault(account['access_code'], []).append(account)
    rows, edges = {}, {}
    for account in sorted(accounts, key=lambda a: (a['access_code'], a['id'])):
        aid = account['id']
        data = metadata.get(aid, {'present': False})
        value = data.get('value')
        declared = {k: deepcopy(value[k]) for k in FIELDS if k in value} if isinstance(value, dict) else {}
        row = {'account_id': aid, 'access_code': account['access_code'], 'declared_fields': declared,
               'source': deepcopy(data.get('source')), 'declaration_sha256': data.get('metadata_sha256'),
               'missing_fields': [], 'diagnostics': [], 'resolved_parent_account_id': None}
        rows[aid] = row
        def diagnostic(code, field, category='inconsistent'):
            row['diagnostics'].append({'code': code, 'field': field, 'category': category, 'blocking': False})
        if data.get('malformed_metadata'):
            diagnostic('ACCOUNT_METADATA_NOT_OBJECT', NAMESPACE)
        if data.get('present') and not isinstance(value, dict):
            diagnostic('DECLARATION_NOT_OBJECT', NAMESPACE)
        if isinstance(value, dict) and set(value) - set(FIELDS):
            row['ignored_fields'] = sorted(set(value) - set(FIELDS))
            diagnostic('UNSUPPORTED_DECLARATION_FIELDS', NAMESPACE, 'review')
        if len(by_code[account['access_code']]) > 1:
            diagnostic('DUPLICATE_ACCOUNT_CODE', 'COD_CTA')
        nature = declared.get('COD_NAT')
        if nature in (None, ''):
            row['missing_fields'].append('COD_NAT')
        elif not isinstance(nature, str) or nature not in NATURE_CODES:
            diagnostic('UNKNOWN_NATURE_CODE', 'COD_NAT')
        level = declared.get('NIVEL')
        valid_level = type(level) is int and level >= 1
        if level is None:
            row['missing_fields'].append('NIVEL')
        elif not valid_level:
            diagnostic('INVALID_LEVEL', 'NIVEL')
        changed = declared.get('DT_ALT')
        if changed in (None, ''):
            row['missing_fields'].append('DT_ALT')
        else:
            try:
                normalized = iso_date(changed, 'DT_ALT')
                if normalized != changed:
                    raise DomainError('Data não canônica.')
                # January's rule compares years, not dates within the same year.
                if changed[:4] > end[:4]:
                    diagnostic('ALTERATION_YEAR_AFTER_SCOPE', 'DT_ALT', 'review')
            except DomainError:
                diagnostic('INVALID_ALTERATION_DATE', 'DT_ALT')
        parent = declared.get('COD_CTA_SUP')
        has_parent = isinstance(parent, str) and bool(parent.strip())
        if parent not in (None, '') and (not isinstance(parent, str) or parent != parent.strip()):
            diagnostic('INVALID_PARENT_CODE', 'COD_CTA_SUP')
            has_parent = False
        if valid_level and level == 1 and has_parent:
            diagnostic('ROOT_HAS_PARENT', 'COD_CTA_SUP')
        if (not valid_level or level > 1) and not has_parent:
            row['missing_fields'].append('COD_CTA_SUP')
        if has_parent:
            parents = by_code.get(parent, [])
            if len(parents) != 1:
                diagnostic('PARENT_NOT_UNIQUE_IN_COMPANY_PLAN', 'COD_CTA_SUP')
            else:
                target = parents[0]
                row['resolved_parent_account_id'] = target['id']
                edges[aid] = target['id']
                if target['analytical']:
                    diagnostic('PARENT_IS_ANALYTICAL', 'COD_CTA_SUP')
        row['missing_fields'].sort()
    cycles = _cycles(edges)
    cycle_by_id = {aid: index for index, cycle in enumerate(cycles) for aid in cycle}
    for aid, row in rows.items():
        parent_id = row['resolved_parent_account_id']
        if aid in cycle_by_id:
            row['diagnostics'].append({'code': 'CYCLIC_PARENT_RELATION', 'field': 'COD_CTA_SUP',
                                      'cycle_index': cycle_by_id[aid], 'category': 'inconsistent', 'blocking': False})
        if parent_id is not None:
            child, parent = row['declared_fields'], rows[parent_id]['declared_fields']
            level, parent_level = child.get('NIVEL'), parent.get('NIVEL')
            if type(level) is int and type(parent_level) is int and level >= 1 and parent_level >= 1:
                if level <= parent_level:
                    row['diagnostics'].append({'code': 'CHILD_LEVEL_NOT_GREATER_THAN_PARENT', 'field': 'NIVEL', 'category': 'inconsistent', 'blocking': False})
                if level > 2 and isinstance(child.get('COD_NAT'), str) and child['COD_NAT'] in NATURE_CODES:
                    if not isinstance(parent.get('COD_NAT'), str) or parent['COD_NAT'] not in NATURE_CODES:
                        row['diagnostics'].append({'code': 'PARENT_NATURE_NOT_REVIEWABLE', 'field': 'COD_NAT', 'category': 'review', 'blocking': False})
                    elif child['COD_NAT'] != parent['COD_NAT']:
                        row['diagnostics'].append({'code': 'NATURE_DIFFERS_FROM_PARENT_ABOVE_LEVEL_TWO', 'field': 'COD_NAT', 'category': 'inconsistent', 'blocking': False})
            else:
                row['diagnostics'].append({'code': 'PARENT_LEVEL_NOT_REVIEWABLE', 'field': 'NIVEL', 'category': 'review', 'blocking': False})
        row['status'] = ('inconsistent' if any(d['category'] == 'inconsistent' for d in row['diagnostics'])
                         else 'missing' if not row['declared_fields']
                         else 'declared_needs_review' if row['missing_fields'] or row['diagnostics']
                         else 'consistent_for_preparation')
    counts = Counter(row['status'] for row in rows.values())
    return {'namespace': NAMESPACE, 'accounts': list(rows.values()), 'cycles': cycles,
            'summary': dict(sorted(counts.items())), 'classification_applied': False,
            'book_dependent_rules_evaluated': False,
            'pending': ['I010.IND_ESC para regra condicional de nível mínimo',
                        'Vigência histórica e plano referencial', 'Revisão maio/2026 e programa oficial']}


def opening_review(snapshot):
    evidence = []
    for section, entries in [('opening_history', snapshot['opening_history']['journals']),
                             ('journals', snapshot['journals'])]:
        for journal in entries:
            if any(event['action'] == 'opening' for event in journal['audit_events']):
                evidence.append({'journal_id': journal['id'], 'date': journal['date'],
                    'section': section, 'reversed_by': journal['reversed_by'],
                    'source_record_sha256': journal['source_record_sha256']})
    dates = sorted({row['date'] for row in evidence})
    return {'cutoff': snapshot['scope']['start'], 'company_id': snapshot['scope']['company_id'],
        'observed_basis': 'stored_preperiod_lines_only',
        'observed_balances': deepcopy(snapshot['opening_history']['recorded_balances']),
        'explicit_opening_postings': evidence, 'opening_dates': dates,
        'attestation_status': 'not_available_in_current_domain', 'attested_opening_balances': None,
        'observed_is_attested': False, 'classification_applied': False,
        'diagnostics': [{'code': 'OBSERVED_BALANCE_IS_NOT_ATTESTATION', 'blocking': False}] +
                       ([{'code': 'OPENING_POSTINGS_REQUIRE_EXPLICIT_TREATMENT', 'blocking': False}] if evidence else []) +
                       ([{'code': 'MULTIPLE_OPENING_DATES', 'blocking': False}] if len(dates) > 1 else []),
        'attestation_contract_pending': ['Empresa, exercício e data de corte explícitos',
            'Completude histórica, identificação das contas/centros e evidência de origem',
            'Responsável e revisão próprios; não deduzidos de extras do plano ou totais balanceados']}


def preparation_review(snapshot, metadata):
    return {'schema_version': 1, 'complete_ecd': False, 'warnings_block_export': False,
        'reference': {'revision': 'janeiro/2026; ADE Cofis 1/2026', 'calendar_year_reviewed': 2025,
                      'sha256': snapshot['reference']['sha256'], 'pages': [117, 118, 119, 120, 133, 134, 135],
                      'may_2026_recovered': False},
        'account_contracts': account_review(snapshot['accounts'], metadata, snapshot['scope']['end']),
        'opening_contract': opening_review(snapshot)}
