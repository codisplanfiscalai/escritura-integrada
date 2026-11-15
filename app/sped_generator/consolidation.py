"""Read-only operational NFC-e grouping; groups never represent fiscal documents."""
import re
from collections import Counter

from ..core import DomainError, iso_date, period
from ..fiscal_series import canonical_series


def _tax_id(value):
    return re.sub(r'[.\-/\s]', '', str(value or '')).upper()


def _exclusion(document, company_id, company_tax_id, competence):
    if document.get('company_id') != company_id:
        return 'OTHER_COMPANY'
    if document.get('period') != competence:
        return 'OTHER_POSTING_PERIOD'
    if document.get('model') != '65':
        return 'OTHER_MODEL'
    if document.get('direction') != 'outgoing':
        return 'NOT_OUTGOING'
    if document.get('book_cancellation') or document.get('document_state') == 'cancelled':
        return 'CANCELLED'
    if not document.get('source_hash'):
        return 'SOURCE_REQUIRED'
    record = (document.get('source') or {}).get('record')
    if record == 'infNFe':
        if _tax_id((document.get('issuer') or {}).get('tax_id')) != _tax_id(company_tax_id):
            return 'NOT_OWN_ISSUANCE'
        if document.get('environment') != '1':
            return 'NON_PRODUCTION_XML'
        if (document.get('authorization') or {}).get('status') not in {'100', '150'}:
            return 'REGULAR_AUTHORIZATION_REQUIRED'
    elif record == 'C100':
        raw = document.get('raw_fields') or {}
        if raw.get('IND_EMIT') != '0':
            return 'NOT_OWN_ISSUANCE'
        if raw.get('COD_SIT') not in {'00', '01', '06', '07', '08'}:
            return 'NON_REGULAR_SPED'
    else:
        return 'ISSUANCE_EVIDENCE_REQUIRED'
    if not re.fullmatch(r'[A-Z0-9]{44}', document.get('key', '')):
        return 'DOCUMENT_KEY_REQUIRED'
    if not re.fullmatch(r'[0-9]{1,9}', document.get('number', '')) or int(document['number']) < 1:
        return 'DOCUMENT_NUMBER_REQUIRED'
    if not re.fullmatch(r'[0-9]{1,3}', canonical_series(document.get('series', ''))):
        return 'NUMERIC_SERIES_REQUIRED'
    try:
        iso_date(document.get('issue_date'))
        if iso_date(document.get('posting_date'))[:7] != competence:
            return 'OTHER_POSTING_PERIOD'
    except DomainError:
        return 'DOCUMENT_DATE_REQUIRED'
    if type(document.get('total_cents')) is not int or document['total_cents'] < 0:
        return 'INVALID_DOCUMENT_TOTAL'
    return None


def preview_nfce_groups(documents, *, company_id, company_tax_id, competence):
    """Consume the entire selected period; keep only compact member references.

    Own issuance is declared source evidence, not online/cryptographic validation.
    Pending review stays visible and does not become a posting/export decision.
    """
    competence = period(competence)
    candidates, excluded = [], []
    input_count = 0
    for document in documents:
        input_count += 1
        reason = _exclusion(document, company_id, company_tax_id, competence)
        if reason:
            excluded.append({'document_id': document.get('id'), 'reason': reason})
            continue
        candidates.append({
            'document_id': document['id'], 'version': document['version'],
            'number': document['number'], 'series': document['series'],
            'declared_series': document.get('declared_series', document['series']),
            'key': document['key'], 'issue_date': document['issue_date'],
            'posting_date': document['posting_date'], 'total_cents': document['total_cents'],
            'source_hash': document['source_hash'], 'source': dict(document['source']),
            'status': document['status'],
            'review_pending': document['status'] == 'pending'
                or bool((document.get('import_posting') or {}).get('review_pending')),
        })
    identities = Counter((canonical_series(d['series']), int(d['number'])) for d in candidates)
    keys = Counter(d['key'] for d in candidates)
    members = []
    for member in candidates:
        identity = (canonical_series(member['series']), int(member['number']))
        if identities[identity] > 1 or keys[member['key']] > 1:
            excluded.append({'document_id': member['document_id'], 'reason': 'DUPLICATE_IDENTITY_OR_KEY'})
        else:
            members.append(member)
    members.sort(key=lambda d: (d['issue_date'], canonical_series(d['series']), int(d['number']), d['document_id']))
    groups = []
    previous_bucket, previous_number, segment = None, None, 0
    for member in members:
        bucket = (member['issue_date'], canonical_series(member['series']))
        number = int(member['number'])
        if bucket != previous_bucket or number != previous_number + 1:
            segment = segment + 1 if bucket == previous_bucket else 1
            groups.append({'issue_date': bucket[0], 'series': bucket[1], 'segment': segment,
                           'document_count': 0, 'total_cents': 0, 'members': []})
        group = groups[-1]
        group['members'].append(member)
        group['document_count'] += 1
        group['total_cents'] += member['total_cents']
        previous_bucket, previous_number = bucket, number
    excluded.sort(key=lambda d: (d['document_id'], d['reason']))
    return {
        'mode': 'preview_only', 'company_id': company_id, 'period': competence,
        'grouping': 'issue_date_series_contiguous_number',
        'summary': {'input_documents': input_count, 'included_documents': len(members),
                    'excluded_documents': len(excluded), 'groups': len(groups),
                    'total_cents': sum(d['total_cents'] for d in members),
                    'review_pending_documents': sum(d['review_pending'] for d in members)},
        'groups': groups, 'excluded': excluded,
        'limitations': [
            'Grupos operacionais; cada membro mantém sua identidade fiscal individual.',
            'Prévia sem escrituração, alteração de documentos ou geração de SPED.',
            'Sem consolidação de CFOP/tributos ou validação de assinatura e situação na SEFAZ.',
            'Lacunas segmentam a amostra; não comprovam notas ausentes, cancelamento ou inutilização.',
        ],
    }
