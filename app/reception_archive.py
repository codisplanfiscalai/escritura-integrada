"""Read-only document/version projection over immutable reception receipts.

No new fiscal authority is inferred from keys, bytes or events. A second byte
version is held for review; originals and bookkeeping are never replaced.
"""
from .core import DomainError,digest


def order(item):
    return (item['received_at'],item['receipt_key'],int(item['nsu']))


def project(cid,provider,environment,occurrences):
    records={};seen={}
    for item in occurrences:
        reference=(item['receipt_key'],item['nsu'])
        if reference in seen:
            if seen[reference]!=item.get('sha256'):raise DomainError('Ocorrência local contraditória. Confira o original.',409,'file_integrity')
            continue
        seen[reference]=item.get('sha256')
        kind=item.get('document_type') or item.get('kind','unsupported')
        key=item.get('xml_access_key') or item.get('access_key')
        # Different events on the same invoice are not versions of the invoice.
        event=kind=='EVENTO' or item.get('kind')=='event'
        trusted_bytes=item.get('content_verified') and item.get('sha256')
        if not event and isinstance(key,str) and key:
            identity=('declared_key',key)
        elif trusted_bytes:
            identity=('content_hash',item['sha256'])
        else:
            identity=('receipt',*reference)
        rid=digest([cid,provider,environment,item.get('target_tax_id'),kind,*identity])
        group=records.setdefault(rid,{'record_id':rid,'identity_evidence':identity[0],'occurrences':[],'versions':{}})
        group['occurrences'].append(item)
        # Missing originals/hashes are never treated as proven duplicate XML.
        version=item['sha256'] if trusted_bytes else digest(['unverified',*reference])
        group['versions'].setdefault(version,[]).append(item)
    for group in records.values():
        group['occurrences'].sort(key=order)
        for sources in group['versions'].values():sources.sort(key=order)
    return sorted(records.values(),key=lambda g:order(g['occurrences'][-1]),reverse=True)


def matches(item,year,query='',direction='',competence=''):
    if str(item['reference_period'])[:4]!=str(year):return False
    if direction and item.get('direction')!=direction and not (direction in {'issued','received'} and item.get('direction')=='both'):return False
    if competence and not str(item.get('declared_competence','')).startswith(competence):return False
    term=query.casefold().strip()
    searchable=('nsu','schema','kind','document_type','access_key','generation_time','direction','company_roles','issuer_name','issuer_tax_id','issue_date','declared_competence','number','xml_access_key','sha256','receipt_key')
    return not term or term in ' '.join(str(item.get(k,'')) for k in searchable).casefold()


def select(group,year,query='',direction='',competence=''):
    candidates=[i for i in group['occurrences'] if matches(i,year,query,direction,competence)]
    if not candidates:return None
    return decorate(group,candidates[0],len(candidates))


def decorate(group,item,matching=1):
    return item|{'record_id':group['record_id'],'identity_evidence':group['identity_evidence'],
        'version_count':len(group['versions']),'occurrence_count':len(group['occurrences']),
        'matching_occurrences':matching,'versions_pending_review':len(group['versions'])>1,
        'first_sha256':group['occurrences'][0].get('sha256'),
        'first_received_at':group['occurrences'][0]['received_at'],'last_received_at':group['occurrences'][-1]['received_at']}


def detail(group,offset):
    variants=sorted(group['versions'].values(),key=lambda sources:order(sources[0]))
    items=[]
    for sources in variants[offset:offset+20]:
        item=next((i for i in sources if i.get('available')),sources[0])
        items.append(item|{'occurrence_count':len(sources),'first_received_at':sources[0]['received_at'],
            'last_received_at':sources[-1]['received_at']})
    return {'record_id':group['record_id'],'identity_evidence':group['identity_evidence'],
        'version_count':len(variants),'occurrence_count':len(group['occurrences']),
        'versions_pending_review':len(variants)>1,'first_sha256':group['occurrences'][0].get('sha256'),
        'versions':items,'offset':offset,'has_more':len(variants)>offset+20}
