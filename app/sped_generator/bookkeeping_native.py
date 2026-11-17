"""Optional operational grouping of the current partial bookkeeping export.

No import/posting setting is changed. Unknown values stay unknown; the complete
native exporter retains its original bytes and empty-to-zero behavior.
"""
from collections import defaultdict
from decimal import InvalidOperation
from hashlib import sha256

from ..core import DomainError
from .native_export import _consolidate_native_sped


def _warning(message, code='BOOKKEEPING_NATIVE_OPERATIONAL_FORMAT'):
    return dict(code=code, severity='warning', message=message, record='', field='',
                count=1, document_ids=[])


def consolidate_generated_block_c(result, *, company_tax_id, competence, segment_on_gap=True):
    original = result['payload']

    def fallback(message):
        return dict(result, consolidation_requested=True, consolidated=False,
                    consolidation_trace=[], individual_result_sha256=sha256(original).hexdigest(),
                    warnings=[*result['warnings'], _warning(message, 'BOOKKEEPING_CONSOLIDATION_NOT_APPLIED')])

    try:
        native = _consolidate_native_sped(original, company_tax_id=company_tax_id,
            competence=competence, enabled=True, segment_on_gap=segment_on_gap, partial_block_c=True)
    except (DomainError, InvalidOperation, UnicodeError) as exc:
        if isinstance(exc, DomainError) and exc.code in {'company_mismatch', 'period_mismatch'}:
            raise
        detail = exc.detail if isinstance(exc, DomainError) else 'Valor não agregável com segurança.'
        return fallback(f'Consolidação solicitada não aplicada: {detail} Arquivo individual preservado.')
    if not native['consolidated']:
        return fallback('Não há NFC-e elegível à consolidação; arquivo individual preservado.')
    source = {item['c100_line']: item for item in result['trace']}
    output_lines = native['payload'].decode('latin-1').splitlines()
    keys = defaultdict(list)
    for number, line in enumerate(output_lines, 1):
        if line.startswith('|C100|'):
            keys[line[1:-1].split('|')[8]].append(number)
    groups, member_outputs = [], {}
    for group in native['trace']:
        first_key = group['members'][0]['key']
        if len(keys[first_key]) != 1:
            return fallback('Vínculo de saída ambíguo; arquivo individual e rastreabilidade preservados.')
        line = keys[first_key][0]
        members = []
        for member in group['members']:
            prior = source.get(member['source_line'])
            if prior is None or prior['key'] != member['key']:
                return fallback('Vínculo de origem não reconciliado; arquivo individual preservado.')
            members.append(dict(prior, **member, source_c100_line=prior['c100_line'], c100_line=line))
            member_outputs[prior['c100_line']] = line
        groups.append(dict(group, members=members, output_c100_line=line))
    trace = []
    for item in result['trace']:
        line = member_outputs.get(item['c100_line'])
        if line is None:
            if len(keys[item['key']]) != 1:
                return fallback('Vínculo individual ambíguo; arquivo individual preservado.')
            line = keys[item['key']][0]
        trace.append(dict(item, source_c100_line=item['c100_line'], c100_line=line))
    counts = {code: sum(line.startswith('|' + code + '|') for line in output_lines)
              for code in ('C100', 'C190')}
    return dict(result, payload=native['payload'], kind='NATIVE_NFCE_OPERATIONAL_PARTIAL_BLOCK_C',
        representation='native_operational_nfce_groups', official_pva_replacement=False,
        consolidation_requested=True, consolidated=True, consolidation_trace=groups, trace=trace,
        result_sha256=sha256(native['payload']).hexdigest(), individual_result_sha256=sha256(original).hexdigest(),
        summary=dict(result['summary'], individual_c190_records=result['summary']['c190_records'],
                     c190_records=counts['C190'], output_c100_records=counts['C100'], consolidated_groups=len(groups)),
        warnings=[*result['warnings'], *map(_warning, native['warnings']),
                  _warning('Representação operacional parcial: valores desconhecidos continuam em branco; não constitui bloco oficial para importação no PVA.')],
        rules=dict(result['rules'], representation_layout='native_c100_29_data_fields',
                   missing_values='blank_if_any_member_unknown'))
