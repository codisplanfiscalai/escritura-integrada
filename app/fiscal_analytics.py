"""Pure, cent-exact fiscal book rows. XML disclosure is not a tax-credit decision.

``fiscal_treatment`` on an item (or its document as fallback) is explicit
configuration, never inferred from CFOP, issuer CRT or the taxpayer's regime.
Supported book_mode values: other_excluding_ipi, declared_icms. The latter
explicitly authorizes using declared ICMS amounts in the book; it does not
validate their legal eligibility. Missing/unknown decisions leave book cells null.
"""
from decimal import Decimal, ROUND_HALF_UP
import json
from datetime import date

ZERO = Decimal('0')
CENT = Decimal('.01')


def validate_fiscal_treatment(value, posting_date=None):
    """Validate a traceable, dated user decision; no inferred tax entitlement."""
    from .core import DomainError
    allowed = {'code', 'book_mode', 'source', 'responsible', 'valid_from', 'valid_to'}
    if not isinstance(value, dict) or set(value) - allowed:
        raise DomainError('Tratamento fiscal: informe somente os campos do perfil permitido.')
    out = {}
    for key in ('code', 'source', 'responsible'):
        if not isinstance(value.get(key), str) or not value[key].strip() or len(value[key]) > 1000:
            raise DomainError('Tratamento fiscal: código, fonte e responsável são obrigatórios.')
        out[key] = value[key].strip()
    if value.get('book_mode') not in {'other_excluding_ipi', 'declared_icms'}:
        raise DomainError('Tratamento fiscal inválido. Valores explícitos globais não podem ser repetidos por linha.')
    out['book_mode'] = value['book_mode']
    for key in ('valid_from', 'valid_to'):
        raw = value.get(key, '')
        try:
            if not isinstance(raw, str) or (key == 'valid_from' and not raw): raise ValueError()
            if raw and (len(raw) != 10 or date.fromisoformat(raw).isoformat() != raw): raise ValueError()
        except ValueError:
            raise DomainError('Tratamento fiscal: informe vigência em AAAA-MM-DD.') from None
        out[key] = raw
    if out['valid_to'] and out['valid_to'] < out['valid_from']:
        raise DomainError('Tratamento fiscal: vigência final anterior à inicial.')
    if posting_date and (posting_date < out['valid_from'] or (out['valid_to'] and posting_date > out['valid_to'])):
        raise DomainError('Tratamento fiscal fora da vigência para a escrituração.')
    return out


def validate_posting_group_review(value, document):
    """Validate an explicit item partition; never reconstruct one from amounts."""
    from .core import DomainError
    allowed = {'source', 'responsible', 'reason', 'mode', 'item_groups'}
    if not isinstance(value, dict) or set(value) != allowed:
        raise DomainError('Grupos de escrituração: informe fonte, responsável, motivo, modo e todos os itens.')
    out = {}
    for key in ('source', 'responsible', 'reason'):
        raw = value.get(key)
        if not isinstance(raw, str) or not raw.strip() or len(raw) > 1000:
            raise DomainError('Grupos de escrituração: fonte, responsável e motivo são obrigatórios.')
        out[key] = raw.strip()
    if value.get('mode') not in {'split', 'consolidate'}:
        raise DomainError('Grupos de escrituração: modo deve ser split ou consolidate.')
    out['mode'] = value['mode']
    doc = _unpack(document)
    items = doc.get('items') or []
    if doc.get('analytics') or not items:
        raise DomainError('Grupos de escrituração exigem itens e não podem substituir os registros C190 existentes.')
    numbers = [str(row.get('number', '')) for row in items]
    mapping = value.get('item_groups')
    if not all(numbers) or len(set(numbers)) != len(numbers) or not isinstance(mapping, dict) or set(mapping) != set(numbers):
        raise DomainError('Grupos de escrituração devem identificar cada item existente exatamente uma vez.')
    out['item_groups'] = {}
    for number, label in mapping.items():
        if not isinstance(label, str) or not label.strip() or len(label) > 100:
            raise DomainError('Grupo de escrituração: use um rótulo não vazio de até 100 caracteres.')
        out['item_groups'][number] = label.strip()
    group_signatures = {}
    for row in items:
        line = _base(doc, row, 'items')
        treatment = line['treatment']
        if out['mode'] == 'consolidate':
            treatment = validate_fiscal_treatment(treatment, doc.get('posting_date'))
            if treatment['book_mode'] != 'other_excluding_ipi':
                raise DomainError('Consolidação exige decisão explícita e vigente de Outras sem crédito de ICMS/IPI.')
        if not line['cfop']:
            raise DomainError('Revise o CFOP de cada item antes de configurar grupos de escrituração.')
        signature = (line['cfop'], json.dumps(treatment, sort_keys=True))
        label = out['item_groups'][str(row['number'])]
        if label in group_signatures and group_signatures[label] != signature:
            raise DomainError('Um grupo de escrituração não pode misturar CFOPs ou tratamentos fiscais diferentes.')
        group_signatures[label] = signature
    return out


def _unpack(document):
    doc = dict(document)
    for name in ('items', 'taxes', 'source'):
        if name not in doc and name + '_json' in doc:
            doc[name] = json.loads(doc[name + '_json'])
    if 'extra_json' in doc:
        doc = json.loads(doc['extra_json']) | doc
    return doc


def _d(value):
    return Decimal(str(value or '0'))


def _money(value):
    return format(_d(value).quantize(CENT, rounding=ROUND_HALF_UP), '.2f')


def _field(values, leaf, prefix=None):
    matches = [v for k, v in values.items() if k.replace('.', '/').split('/')[-1] == leaf and (prefix is None or k.replace('.', '/').startswith(prefix))]
    return matches[0] if len(matches) == 1 else None


def _allocate(amount, weights):
    """Largest remainder, stable input-order ties, exact cents including negatives."""
    cents = int(_d(amount).quantize(CENT, rounding=ROUND_HALF_UP) * 100)
    weights = [max(ZERO, w) for w in weights]
    if not sum(weights):
        return [Decimal(cents) / 100] + [ZERO] * (len(weights) - 1)
    exact = [Decimal(abs(cents)) * w / sum(weights) for w in weights]
    parts = [int(x) for x in exact]
    for i in sorted(range(len(parts)), key=lambda i: (-(exact[i] - parts[i]), i))[:abs(cents) - sum(parts)]:
        parts[i] += 1
    return [Decimal(x if cents >= 0 else -x) / 100 for x in parts]


def _base(doc, row, kind):
    taxes = row.get('taxes', {})
    raw = row.get('raw_fields', {})
    cst = row.get('cst_icms') or _field(taxes, 'CST', 'ICMS/') or ''
    csosn = row.get('csosn') or _field(taxes, 'CSOSN', 'ICMS/') or ''
    rate = row.get('rate')
    if rate is None:
        rate = raw.get('ALIQ_ICMS') or taxes.get('ALIQ_ICMS') or _field(taxes, 'pICMS', 'ICMS/')
    treatment = row.get('fiscal_treatment', doc.get('fiscal_treatment', {})) or {}
    return {'cfop': row.get('cfop') or doc.get('cfop', ''), 'cst_icms': cst,
            'csosn': csosn, 'origin': _field(taxes, 'orig', 'ICMS/') or '',
            'rate': format(_d(str(rate).replace(',', '.')), 'f') if rate is not None else None,
            'posting_date': doc.get('posting_date', ''), 'item_numbers': [], 'ncms': [],
            'document_total': '0.00', 'ipi': '0.00', 'ipi_informed': False, 'book_base': None,
            'book_icms': None, 'book_other': None, 'book_ipi': None,
            'posting_group': None, 'grouping_mode': 'automatic', 'declared_classifications': [],
            'declared_taxes': {}, 'declared_tax_coverage': {}, 'declared_tax_partial_totals': {}, 'declared_tax_records': [], 'treatment': treatment, 'pending': [], 'source_kind': kind}


def _book(line):
    treatment = line['treatment']
    mode = None
    if treatment:
        from .core import DomainError
        try:
            treatment = validate_fiscal_treatment(treatment, line['posting_date'])
            line['treatment'] = treatment
            mode = treatment['book_mode']
        except DomainError:
            line['pending'].append('INVALID_FISCAL_TREATMENT')
    if mode == 'other_excluding_ipi':
        line.update(book_base='0.00', book_icms='0.00', book_ipi='0.00',
                    book_other=_money(_d(line['document_total']) - _d(line['ipi'])))
    elif mode == 'declared_icms':
        line.update(book_base=line['declared_taxes'].get('icms_base'),
                    book_icms=line['declared_taxes'].get('icms'))
        if line['book_base'] is None or line['book_icms'] is None:
            line['book_base'] = line['book_icms'] = None
            line['pending'].append('DECLARED_ICMS_MISSING')
        # This authorization alone does not establish Outras or an IPI credit.
        line['pending'].append('OTHER_IPI_TREATMENT_REQUIRED')
    else:
        line['pending'].append('FISCAL_TREATMENT_REQUIRED')
    if not line['cfop']:
        line['pending'].append('CFOP_REQUIRED')


def fiscal_posting_lines(document):
    """Return JSON-ready lines without mutating document or external state.

    document_total is each line's allocated accounting amount, not a repeated
    header total. Book fields are null while treatment is undecided. Existing
    SPED C190 is authoritative and never combined with C170 or C100 amounts.
    """
    doc = _unpack(document)
    review = None
    review_invalid = False
    if doc.get('posting_group_review') is not None:
        from .core import DomainError
        try:
            review = validate_posting_group_review(doc['posting_group_review'], doc)
        except DomainError:
            review_invalid = True
    total = _d(doc.get('total')) if 'total' in doc else _d(doc.get('total_cents')) / 100
    if doc.get('analytics'):
        lines = []
        for row in doc['analytics']:
            line = _base(doc, row, 'sped_c190')
            taxes = row.get('taxes', {})
            line.update(document_total=_money(row.get('operation_total', taxes.get('VL_OPR'))),
                        ipi=_money(taxes.get('VL_IPI')), ipi_informed='VL_IPI' in taxes, book_base=_money(taxes['VL_BC_ICMS']) if 'VL_BC_ICMS' in taxes else None,
                        book_icms=_money(taxes['VL_ICMS']) if 'VL_ICMS' in taxes else None,
                        book_ipi=None,
                        declared_taxes=dict(taxes))
            line['pending'].append('OTHER_IPI_TREATMENT_REQUIRED')
            if review_invalid: line['pending'].append('INVALID_POSTING_GROUP_REVIEW')
            if not line['cfop']: line['pending'].append('CFOP_REQUIRED')
            lines.append(line)
        if sum(_d(x['document_total']) for x in lines) != total:
            for line in lines: line['pending'].append('C190_TOTAL_MISMATCH')
        return lines

    items = doc.get('items') or [doc]
    header_only = not doc.get('items')
    weights = [max(ZERO, _d(i.get('total', total))) if i.get('declared_product_fields', {}).get('indTot', '1') != '0' else ZERO for i in items]
    contributing = [i for i, row in enumerate(items) if row.get('declared_product_fields', {}).get('indTot', '1') != '0']
    # Excluded products must never receive a residual amount.
    if not sum(weights) and contributing: weights[contributing[0]] = Decimal(1)
    amounts = [ZERO for _ in items]
    pending = ['INVALID_POSTING_GROUP_REVIEW'] if review_invalid else []
    header = doc.get('taxes', {})
    components = [('product', 'vProd', 1), ('discount', 'vDesc', -1), ('freight', 'vFrete', 1),
                  ('insurance', 'vSeg', 1), ('other', 'vOutro', 1), ('ipi', 'vIPI', 1),
                  ('st', 'vST', 1), ('fcp_st', 'vFCPST', 1), ('import_duty', 'vII', 1),
                  ('ipi_return', 'vIPIDevol', 1)]
    component_values = {}
    for name, tag, sign in components:
        vals = []
        for row in items:
            product = row.get('declared_product_fields', {})
            taxes = row.get('taxes', {})
            value = product.get(tag) if name in {'product', 'discount', 'freight', 'insurance', 'other'} else _field(taxes, 'vICMSST' if tag == 'vST' else tag)
            if name == 'product' and value is None: value = row.get('total', total if header_only else 0)
            vals.append(_d(value) if product.get('indTot', '1') != '0' else ZERO)
        declared = _field(header, tag, 'ICMSTot/')
        if declared is not None:
            delta = _d(declared) - sum(vals)
            if delta:
                shares = _allocate(delta, weights)
                vals = [v + s for v, s in zip(vals, shares)]
                pending.append('HEADER_COMPONENT_ALLOCATED')
        component_values[name] = vals
        amounts = [a + sign * v for a, v in zip(amounts, vals)]
    residual = total - sum(amounts)
    if residual:
        amounts = [a + b for a, b in zip(amounts, _allocate(residual, weights))]
        pending.append('TOTAL_ALLOCATION_REVIEW')
    if not contributing: pending.append('NO_CONTRIBUTING_ITEMS')
    groups = {}
    for idx, item in enumerate(items):
        line = _base(doc, item, 'document' if header_only else 'items')
        key = (line['cfop'], line['cst_icms'], line['csosn'], line['origin'],
               _d(line['rate']) if line['rate'] is not None else None,
               json.dumps(line['treatment'], sort_keys=True))
        classification = {k: line[k] for k in ('cfop', 'cst_icms', 'csosn', 'origin', 'rate')}
        if classification['rate'] is not None:
            classification['rate'] = format(_d(classification['rate']).normalize(), 'f')
        if review:
            label = review['item_groups'][str(item['number'])]
            line['posting_group'] = label
            line['grouping_mode'] = review['mode']
            key = (label,) if review['mode'] == 'consolidate' else (label,) + key
        group = groups.setdefault(key, line)
        if classification not in group['declared_classifications']:
            group['declared_classifications'].append(classification)
        if review and review['mode'] == 'consolidate':
            for field in ('cst_icms', 'csosn', 'origin', 'rate'):
                values = {x[field] for x in group['declared_classifications']}
                group[field] = next(iter(values)) if len(values) == 1 else None
        if not header_only: group['item_numbers'].append(str(item.get('number', idx + 1)))
        if item.get('ncm') and item['ncm'] not in group['ncms']: group['ncms'].append(item['ncm'])
        group['document_total'] = _money(_d(group['document_total']) + amounts[idx])
        group['ipi'] = _money(_d(group['ipi']) + component_values['ipi'][idx])
        group['ipi_informed'] = group['ipi_informed'] or _field(item.get('taxes', {}), 'vIPI') is not None or _field(header, 'vIPI', 'ICMSTot/') is not None
        taxes = item.get('taxes', {})
        group['declared_tax_records'].append({'item_number': str(item.get('number', '')), 'taxes': dict(taxes)})
        for name, leaf, prefix in [('icms_base', 'vBC', 'ICMS/'), ('icms', 'vICMS', 'ICMS/'),
                                   ('ipi_base', 'vBC', 'IPI/'), ('ipi', 'vIPI', 'IPI/')]:
            val = _field(taxes, leaf, prefix)
            source = 'items'
            if header_only and name in {'icms_base', 'icms', 'ipi'}:
                val = val if val is not None else _field(taxes, leaf, 'ICMSTot/')
                source = 'document'
            if name == 'ipi' and _field(header, 'vIPI', 'ICMSTot/') is not None:
                val = component_values['ipi'][idx]
                source = 'header_allocated'
            coverage = group['declared_tax_coverage'].setdefault(name, {'known': 0, 'expected': 0, 'complete': False, 'sources': []})
            coverage['expected'] += 1
            if val is not None and val != '':
                coverage['known'] += 1
                if source not in coverage['sources']: coverage['sources'].append(source)
                group['declared_tax_partial_totals'][name] = _money(_d(group['declared_tax_partial_totals'].get(name)) + _d(val))
    lines = list(groups.values())
    for line in lines:
        line['pending'] = list(dict.fromkeys(pending))
        for name, coverage in line['declared_tax_coverage'].items():
            coverage['complete'] = coverage['known'] == coverage['expected']
            line['declared_taxes'][name] = line['declared_tax_partial_totals'].get(name) if coverage['complete'] else None
            if 0 < coverage['known'] < coverage['expected']:
                line['pending'].append('DECLARED_' + name.upper() + '_INCOMPLETE')
        line['ipi_informed'] = line['declared_tax_coverage']['ipi']['complete']
        _book(line)
        if _d(line['document_total']) < 0: line['pending'].append('NEGATIVE_ALLOCATION_REVIEW')
    return lines
