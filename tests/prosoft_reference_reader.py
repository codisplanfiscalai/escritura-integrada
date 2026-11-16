"""Read-only test oracle transcribed from vendor PDFs, never exporter constants.

Sources/positions and deliberate coverage limits: docs/VALIDACAO_INTERCAMBIO_PROSOFT.md.
No production decoder, automatic repair, tax inference or destination validation.
"""
from datetime import datetime
from decimal import Decimal
import re


def field(row, start, width):
    return row[start - 1:start - 1 + width].decode('ascii')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def numeric(value):
    require(bool(re.fullmatch(r'[0-9]+', value)), 'invalid numeric field')
    return int(value)


def amount(row, start, width, optional=False):
    value = field(row, start, width)
    if optional and value == ' ' * width:
        return None
    require(bool(re.fullmatch(r'[0-9]{' + str(width - 3) + r'}\.[0-9]{2}', value)), 'invalid decimal field')
    return int(Decimal(value) * 100)


def records(raw):
    require(raw.endswith(b'\r\n'), 'missing final CRLF')
    rows = raw[:-2].split(b'\r\n')
    require(all(row and all(32 <= b <= 126 for b in row) for row in rows), 'non printable ASCII or invalid separator')
    return rows


def date(row, start, width):
    value = field(row, start, width)
    numeric(value)
    # Application fiscal profile explicitly covers 2000..2099, unlike strptime %y pivot.
    if width == 6:
        value = value[:4] + '20' + value[4:]
    return datetime.strptime(value, '%d%m%Y').date().isoformat()


def fiscal(raw, direction):
    # Fiscal PDF pp.1-3,7 (incoming), 11-14,17 (outgoing). One-based positions.
    if direction == 'incoming':
        width, posting, issue, number, species, series, split, account, cfop = 2340,19,25,869,858,864,43,44,624
        total, base, icms, other, ipi, cancelled, key = 211,66,80,108,155,809,973
    else:
        require(direction == 'outgoing', 'unknown fiscal direction')
        width, posting, issue, number, species, series, split, account, cfop = 2611,20,728,989,978,984,19,26,734
        total, base, icms, other, ipi, cancelled, key = 34,62,76,104,132,930,1377
    result = []
    for row in records(raw):
        require(len(row) == width, 'invalid fiscal width')
        flag = field(row,cancelled,1)
        require(flag in ('0','1'), 'invalid cancellation flag')
        identity = field(row,number,10)
        numeric(identity)
        if direction == 'outgoing':
            require(identity == field(row,999,10), 'different initial/final note')
        result.append({'number':identity,'species':field(row,species,5).rstrip(),
            'series':field(row,series,3).rstrip(),'split':field(row,split,1),
            'account':numeric(field(row,account,5)) if field(row,account,5).strip() else None,
            'cfop':field(row,cfop,4),'posting_date':date(row,posting,6),'issue_date':date(row,issue,6),
            'key':field(row,key,44).rstrip(),'cancelled':flag=='1',
            'total_cents':amount(row,total,14),'book_base_cents':amount(row,base,14,True),
            'book_icms_cents':amount(row,icms,14,True),'book_other_cents':amount(row,other,14,True),
            'book_ipi_cents':amount(row,ipi,14,True)})
    return result


def accounting(raw):
    # CTBLCTOS PDF p.2 CTA, pp.4-5 LC1/LC2 and mode/sequence rules.
    registrations, journals = [], []
    current = None
    for row in records(raw):
        kind = field(row,1,3)
        require(kind in ('CTA','LC1','LC2'), 'unsupported record')
        require(len(row) == {'CTA':208,'LC1':448,'LC2':342}[kind], 'invalid accounting width')
        order = numeric(field(row,4,5))
        if kind == 'CTA':
            require(not journals, 'CTA after journals')
            require(order == len(registrations)+1, 'invalid CTA sequence')
            require(field(row,9,3) == ' '*3 and field(row,165,44) == ' '*44, 'invalid CTA filler')
            registrations.append({'order':order,'account':numeric(field(row,12,5)),
                'classifier':field(row,17,15),'name':field(row,32,30).rstrip(),
                'third_mode':field(row,62,1),'center_mode':field(row,63,1)})
        elif kind == 'LC1':
            if current:
                require(len(current['lines']) == current['count'], 'incomplete detailed journal')
            require(order == len(journals)+1, 'invalid LC1 sequence')
            require(field(row,9,3) == ' '*3 and field(row,375,74) == ' '*74, 'invalid LC1 filler')
            mode = field(row,12,1)
            require(mode in ('1','2'), 'invalid journal mode')
            current = {'order':order,'date':date(row,13,8),'document':field(row,21,10).rstrip(),
                'batch':numeric(field(row,31,5)),'origin':field(row,36,30).rstrip(),
                'mode':mode,'count':2 if mode=='1' else numeric(field(row,66,3)),'lines':[]}
            if mode == '1':
                require(field(row,66,3) == ' '*3, 'mode 1 count must be blank')
                value = amount(row,117,16)
                for nature,access,third,center in [('D',69,74,88),('C',93,98,112)]:
                    current['lines'].append({'nature':nature,'account':numeric(field(row,access,5)),
                        'third':field(row,third,14).rstrip(),'center':numeric(field(row,center,5)),
                        'cents':value,'history':field(row,133,240).rstrip()})
            else:
                require(2 <= current['count'] <= 200, 'invalid detailed count')
                require(field(row,69,304) == ' '*304, 'mode 2 simple fields must be blank')
            journals.append(current)
        else:
            require(current is not None and current['mode']=='2', 'LC2 without detailed LC1')
            require(order == current['order'], 'LC2 parent order mismatch')
            require(numeric(field(row,9,3)) == len(current['lines'])+1, 'invalid LC2 sequence')
            require(field(row,294,49) == ' '*49, 'invalid LC2 filler')
            nature=field(row,12,1)
            require(nature in ('D','C'), 'invalid nature')
            current['lines'].append({'nature':nature,'account':numeric(field(row,13,5)),
                'third':field(row,18,14).rstrip(),'center':numeric(field(row,32,5)),
                'cents':amount(row,37,16),'history':field(row,53,240).rstrip()})
    require(bool(journals), 'no journals')
    for journal in journals:
        require(len(journal['lines']) == journal['count'], 'incomplete detailed journal')
        debit=sum(x['cents'] for x in journal['lines'] if x['nature']=='D')
        credit=sum(x['cents'] for x in journal['lines'] if x['nature']=='C')
        require(debit == credit, 'unbalanced journal')
        journal['total_cents']=debit
    return registrations,journals
