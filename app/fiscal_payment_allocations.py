"""Read declared NF-e payments and build explicitly mapped accounting debits.

No settlement, card fee, receivable, account default or inferred cash change.
"""
import re
from decimal import Decimal
from .core import DomainError, decimal_text
from .account_refs import resolve_account


def children(node, tag):
    nodes = node.get('children', []) if isinstance(node, dict) else []
    if not isinstance(nodes, list):
        raise DomainError('Evidência de pagamentos inválida.')
    return [n for n in nodes if isinstance(n, dict) and n.get('tag') == tag]


def leaf(node, tag, *, optional=False):
    found = children(node, tag)
    if not found and optional:
        return None
    if len(found) != 1 or not isinstance(found[0].get('text'), str):
        raise DomainError(f'Confira o campo {tag} dos pagamentos declarados.')
    return found[0]['text']


def cents(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,13}(?:\.[0-9]{1,2})?', value):
        raise DomainError('Pagamento deve declarar valor não negativo com até dois decimais.')
    return int(Decimal(value) * 100)


def payment_evidence(doc, *, retained=None):
    if doc['direction'] != 'outgoing' or doc['model'] not in {'55', '65'}:
        raise DomainError('Rateio por pagamento aceita somente saídas NF-e/NFC-e com pagamentos declarados.')
    fields = doc.get('declared_document_fields')
    recovered = fields is None and retained is not None
    if recovered:
        fields = retained.snapshot(doc)
    groups = children(fields, 'pag')
    if len(groups) != 1:
        raise DomainError('Nota sem grupo único de pagamentos declarado. Use contas diretas ou confira a origem.')
    rows = children(groups[0], 'detPag')
    if not 1 <= len(rows) <= 100:
        raise DomainError('Confira os pagamentos declarados da nota (1 a 100 detalhes).')
    payments = []
    for index, row in enumerate(rows):
        method, amount = leaf(row, 'tPag'), cents(leaf(row, 'vPag'))
        if not re.fullmatch(r'[0-9]{2}', method) or method in {'90', '91'} or amount <= 0:
            raise DomainError('O rateio exige meio de pagamento identificado e valor maior que zero.')
        payments.append(dict(index=index, method=method, amount_cents=amount,
                             description=leaf(row, 'xPag', optional=True)))
    declared_change = leaf(groups[0], 'vTroco', optional=True)
    change = cents('0.00' if declared_change is None else declared_change)
    if sum(p['amount_cents'] for p in payments) - change != doc['total_cents']:
        raise DomainError('Pagamentos menos troco divergem do total escriturado. Confira a nota antes do rateio.')
    return dict(payments=payments, change_cents=change, total_cents=doc['total_cents']) | (
        {'evidence_origin': 'retained_xml', 'source_hash': doc['source_hash']} if recovered else {})


def payment_lines(conn, cid, doc, entry, *, retained=None):
    evidence = payment_evidence(doc, retained=retained)
    mappings = entry['payment_accounts']
    if not isinstance(mappings, list) or not 1 <= len(mappings) <= 100:
        raise DomainError('Informe as contas explícitas por meio de pagamento.')
    accounts, dimensions = {}, []
    for mapping in mappings:
        if not isinstance(mapping, dict) or set(mapping) != {'method', 'account_id'}:
            raise DomainError('Mapeamento de pagamento inválido.')
        method = mapping['method']
        if not isinstance(method, str) or not re.fullmatch(r'[0-9]{2}', method) or method in accounts:
            raise DomainError('Informe cada meio de pagamento uma única vez.')
        account = resolve_account(conn, cid, mapping['account_id'])
        if not account['active'] or not account['analytical']:
            raise DomainError('Selecione conta analítica ativa para cada meio de pagamento.')
        accounts[method] = mapping['account_id']
        canonical = -account['shared_entry_id'] if account['shared_entry_id'] else account['id']
        dimensions.append((method, canonical))
    changes = entry.get('change_allocations', [])
    if not isinstance(changes, list) or len(changes) > len(evidence['payments']):
        raise DomainError('Distribuição do troco inválida.')
    change_by_index = {}
    for change in changes:
        if not isinstance(change, dict) or set(change) != {'payment_index', 'amount_cents'}:
            raise DomainError('Distribuição do troco inválida.')
        index, amount = change['payment_index'], change['amount_cents']
        if type(index) is not int or not 0 <= index < len(evidence['payments']) or index in change_by_index or type(amount) is not int or amount < 0:
            raise DomainError('Informe detalhes únicos e centavos não negativos para o troco.')
        change_by_index[index] = amount
    if sum(change_by_index.values()) != evidence['change_cents']:
        raise DomainError('Distribua explicitamente todo o troco entre os pagamentos da nota.')
    center = entry.get('cost_center_id')
    lines, snapshot = [], []
    for payment in evidence['payments']:
        method, index = payment['method'], payment['index']
        if method not in accounts:
            raise DomainError(f'Informe a conta do meio de pagamento {method}.')
        change = change_by_index.get(index, 0)
        net = payment['amount_cents'] - change
        if net < 0:
            raise DomainError('Troco distribuído excede o valor do pagamento.')
        snapshot.append(payment | dict(change_cents=change, net_cents=net, account_ref=accounts[method]))
        if net:
            lines.append(dict(account_id=accounts[method], debit=decimal_text(net), credit='0.00', cost_center_id=center))
    lines.append(dict(account_id=entry.get('credit_account_id'), debit='0.00', credit=decimal_text(doc['total_cents']), cost_center_id=center))
    return lines, evidence | {'payments': snapshot}, sorted(dimensions)
