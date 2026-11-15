"""Optional native consolidation port from consolidation-export.ts.

Produces the same operational C100/C190/C191/C195 representation. The first
member's key identifies that member; trace lists the whole group separately.
"""
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256

from ..core import DomainError, period
from ..fiscal_series import canonical_series
from .consolidation import _tax_id

REGULAR = {'00', '01', '06', '07', '08'}
BOUNDARIES = {'C100', 'C300', 'C350', 'C400', 'C460', 'C500', 'C590',
              'C600', 'C700', 'C790', 'C800', 'C860', 'C890', 'C990'}
SUM_FIELDS = (10, 12, 13, 14, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28)
OBS_DESCRIPTION = 'CONSOLIDACAO DIARIA NFC-E MODELO 65 POR DATA SERIE SEGMENTO E CFOP'


def _record(code, fields):
    return '|' + '|'.join([code, *map(str, fields)]) + '|'


def _fields(line):
    if not line.startswith('|') or not line.endswith('|'):
        raise DomainError('Linha EFD sem delimitadores; o original não foi alterado.')
    return line[1:-1].split('|')


def _decimal(value):
    try:
        raw = value.strip()
        number = Decimal((raw.replace('.', '').replace(',', '.') if ',' in raw else raw) or '0')
        if not number.is_finite():
            raise InvalidOperation
        return number
    except InvalidOperation:
        raise DomainError('Valor EFD inválido para consolidação; nenhum valor foi substituído.') from None


def _money(value):
    return format(value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP), '.2f').replace('.', ',')


def _date(value):
    try:
        return datetime.strptime(value, '%d%m%Y').date().isoformat()
    except ValueError:
        raise DomainError('NFC-e regular sem data válida para consolidação.') from None


def _consolidate_native_sped(payload, *, company_tax_id, competence, enabled=False, segment_on_gap=True):
    """Return derived bytes and individual source-line trace; never writes state.

    Disabled means byte-for-byte original. Enabled uses the reference's native
    aggregation, restricted to outgoing, own-issued model 65 as requested.
    """
    competence = period(competence)
    if type(enabled) is not bool or type(segment_on_gap) is not bool:
        raise DomainError('Opções de consolidação devem ser booleanas.')
    if not enabled:
        return {'payload': payload, 'consolidated': False, 'trace': [], 'warnings': []}
    try:
        text = payload.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = payload.decode('cp1252')
    lines = [line for line in text.splitlines() if line.strip()]
    records = [_fields(line) for line in lines]
    headers = [r for r in records if r[0] == '0000']
    if len(headers) != 1 or len(headers[0]) < 7:
        raise DomainError('Cabeçalho EFD único com empresa e competência é obrigatório.')
    header = headers[0]
    if _tax_id(header[6]) != _tax_id(company_tax_id):
        raise DomainError('Empresa do EFD difere da empresa selecionada.', 409, 'company_mismatch')
    if _date(header[3])[:7] != competence or _date(header[4])[:7] != competence:
        raise DomainError('Competência do EFD difere da consulta.', 409, 'period_mismatch')
    if any(sum(r[0] == code for r in records) != 1 for code in ('0990', 'C990')):
        raise DomainError('EFD deve conter um 0990 e um C990 para reconstrução dos contadores.')
    blocks, targets = {}, []
    index = 0
    while index < len(records):
        if records[index][0] != 'C100':
            index += 1
            continue
        end = index + 1
        while end < len(records) and records[end][0].startswith('C') and records[end][0] not in BOUNDARIES:
            end += 1
        fields = records[index][1:]
        blocks[index] = end
        if len(fields) >= 11 and fields[:2] == ['1', '0'] and fields[3] == '65' and fields[4] in REGULAR:
            if not fields[5].isascii() or not fields[5].isdigit() or not fields[6].isascii() or not fields[6].isdigit():
                raise DomainError('Série/número da NFC-e inválidos para segmentação.')
            if len(fields[7]) != 44 or not fields[7].isascii() or not fields[7].isalnum():
                raise DomainError('NFC-e regular sem chave de 44 caracteres.')
            children = records[index + 1:end]
            if any(r[0] not in {'C190', 'C191'} for r in children):
                raise DomainError('NFC-e possui filhos ainda não agregados com segurança; original preservado.')
            targets.append({'start': index, 'fields': fields, 'children': children,
                            'date': _date(fields[8]), 'series': canonical_series(fields[5]),
                            'number': int(fields[6]), 'key': fields[7]})
        index = end
    identities = Counter((d['series'], d['number']) for d in targets)
    keys = Counter(d['key'] for d in targets)
    if any(n > 1 for n in identities.values()) or any(n > 1 for n in keys.values()):
        raise DomainError('NFC-e duplicada por série/número ou chave; revise a origem antes de consolidar.')
    if not targets:
        return {'payload': payload, 'consolidated': False, 'trace': [], 'warnings': []}
    existing = {r[1]: r[2] for r in records if r[0] == '0460' and len(r) >= 3}
    obs = next((c for c in ('NF65C', 'NF65C1', 'NF65C2', 'NF65C3', 'NF65C4', 'NF65C5')
                if c not in existing or existing[c] == OBS_DESCRIPTION), None)
    if obs is None:
        raise DomainError('Sem código 0460 disponível para a consolidação.')
    grouped = []
    for document in sorted(targets, key=lambda d: (d['date'], d['series'], d['number'])):
        bucket = (document['date'], document['series'])
        previous = grouped[-1][-1] if grouped else None
        if previous is None or (previous['date'], previous['series']) != bucket or (
                segment_on_gap and document['number'] != previous['number'] + 1):
            grouped.append([])
        grouped[-1].append(document)
    rebuilt, trace = [], []
    segments = defaultdict(int)
    for group in grouped:
        first = group[0]
        bucket = (first['date'], first['series'])
        segments[bucket] += 1
        fields = first['fields'] + [''] * max(0, 29 - len(first['fields']))
        fields[4], fields[6], fields[9] = '00', str(first['number']), fields[8]
        for position, fallback in ((2, ''), (11, '0'), (15, '9')):
            values = {d['fields'][position].strip() for d in group
                      if len(d['fields']) > position and d['fields'][position].strip()}
            fields[position] = next(iter(values)) if len(values) == 1 else fallback
        for position in SUM_FIELDS:
            fields[position] = _money(sum((_decimal(d['fields'][position]).quantize(Decimal('.01'), rounding=ROUND_HALF_UP) if len(d['fields']) > position
                                           else Decimal(0) for d in group), Decimal(0)))
        rebuilt.append(_record('C100', fields))
        analytics = {}
        for document in group:
            current = None
            for row in document['children']:
                values = row[1:]
                if row[0] == 'C190':
                    if len(values) != 11:
                        raise DomainError('C190 incompleto para consolidação.')
                    key = (values[0], values[1], _decimal(values[2]), values[10])
                    current = analytics.setdefault(key, [Decimal(0)] * 10)
                    for i, value in enumerate(values[3:10]):
                        current[i] += _decimal(value).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
                elif current is None or len(values) != 3:
                    raise DomainError('C191 sem C190 válido; original preservado.')
                else:
                    for i, value in enumerate(values):
                        current[7 + i] += _decimal(value).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        for (cst, cfop, rate, cod_obs), values in sorted(analytics.items(), key=lambda p: (p[0][1], p[0][0], p[0][2], p[0][3])):
            rebuilt.append(_record('C190', [cst, cfop, _money(rate), *map(_money, values[:7]), cod_obs]))
            if any(values[7:]):
                rebuilt.append(_record('C191', map(_money, values[7:])))
        rebuilt.append(_record('C195', [obs,
            f"NFCE {first['number']} A {group[-1]['number']}; QTD {len(group)}; DATA {first['fields'][8]}; SERIE {first['fields'][5]}; SEGMENTO {segments[bucket]}"]))
        trace.append({'issue_date': first['date'], 'series': first['fields'][5], 'segment': segments[bucket],
                      'total_cents': int(_decimal(fields[10]) * 100),
                      'members': [{'source_line': d['start'] + 1, 'number': d['fields'][6], 'key': d['key'],
                                   'source_c100_sha256': sha256(lines[d['start']].encode()).hexdigest()} for d in group]})
    target_starts = {d['start'] for d in targets}
    output, index = [], 0
    while index < len(lines):
        code = records[index][0]
        if index in target_starts:
            index = blocks[index]
            continue
        if code == 'C990':
            output.extend(rebuilt)
        if not code.startswith('9'):
            output.append(lines[index])
        index += 1
    if obs not in existing:
        at = next(i for i, line in enumerate(output) if _fields(line)[0] == '0990')
        output.insert(at, _record('0460', [obs, OBS_DESCRIPTION]))
    for prefix, closer in (('0', '0990'), ('C', 'C990')):
        count = sum(_fields(line)[0].startswith(prefix) for line in output)
        at = next(i for i, line in enumerate(output) if _fields(line)[0] == closer)
        output[at] = _record(closer, [count])
    counts = Counter(_fields(line)[0] for line in output)
    codes = sorted(set(counts) | {'9001', '9900', '9990', '9999'})
    counts.update({'9001': 1, '9900': len(codes), '9990': 1, '9999': 1})
    block9 = [_record('9001', ['0']), *(_record('9900', [c, counts[c]]) for c in codes)]
    block9.append(_record('9990', [len(block9) + 1]))
    block9.append(_record('9999', [len(output) + len(block9) + 1]))
    return {'payload': ('\r\n'.join(output + block9) + '\r\n').encode(),
            'consolidated': True, 'official_pva_replacement': False, 'trace': trace,
            'warnings': [
                'Consolidação nativa opcional: cada C100 agregado reutiliza número/chave da primeira NFC-e; representa um grupo operacional.',
                'O C100 nativo mantém 29 campos de dados; o leitor 020 atual do Escritura aceita 28 e ainda precisa de adaptação para reimportar esta saída.',
                'As demais chaves e linhas de origem constam na rastreabilidade; este resultado não declara conformidade para entrega no PVA.',
            ]}

def consolidate_native_sped(payload, *, company_tax_id, competence, enabled=False, segment_on_gap=True):
    """Export remains available when an aggregation cannot preserve all evidence.

    Context/permission errors and malformed options remain errors. A limitation
    of the transformation returns original bytes and a visible warning.
    """
    competence = period(competence)
    if type(enabled) is not bool or type(segment_on_gap) is not bool:
        raise DomainError('Opções de consolidação devem ser booleanas.')
    try:
        return _consolidate_native_sped(payload, company_tax_id=company_tax_id,
            competence=competence, enabled=enabled, segment_on_gap=segment_on_gap)
    except (DomainError, InvalidOperation, UnicodeError) as exc:
        if isinstance(exc, DomainError) and exc.code in {'company_mismatch', 'period_mismatch'}:
            raise
        detail = exc.detail if isinstance(exc, DomainError) else 'Valor ou codificação não pôde ser agregado com segurança.'
        return {'payload': payload, 'consolidated': False, 'trace': [],
                'warnings': [f'Consolidação solicitada não aplicada: {detail} Exportação do original preservada.']}
