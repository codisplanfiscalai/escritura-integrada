"""First bookkeeping-to-EFD increment: individual NFC-e, partial Block C only.

Verified against Guia Pratico EFD ICMS/IPI 3.2.4, section I.9, C100 exception 9,
C190 and C990. This is not a complete EFD or a PVA validation service.
"""
import calendar
import re
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256

from ..core import DomainError, period
from ..fiscal_analytics import fiscal_posting_lines
from .consolidation import _tax_id

GUIDE_URL = 'https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-icms-ipi/manuais-e-documentos-tecnicos/guia-pratico-efd-versao-3-2-4.pdf/@@download/file'
HEADER = 'COD_VER COD_FIN DT_INI DT_FIN NOME CNPJ CPF UF IE COD_MUN IM SUFRAMA IND_PERFIL IND_ATIV'.split()
C100 = 'IND_OPER IND_EMIT COD_PART COD_MOD COD_SIT SER NUM_DOC CHV_NFE DT_DOC DT_E_S VL_DOC IND_PGTO VL_DESC VL_ABAT_NT VL_MERC IND_FRT VL_FRT VL_SEG VL_OUT_DA VL_BC_ICMS VL_ICMS VL_BC_ICMS_ST VL_ICMS_ST VL_IPI VL_PIS VL_COFINS VL_PIS_ST VL_COFINS_ST'.split()
C190 = 'CST_ICMS CFOP ALIQ_ICMS VL_OPR VL_BC_ICMS VL_ICMS VL_BC_ICMS_ST VL_ICMS_ST VL_RED_BC VL_IPI COD_OBS'.split()
AMOUNTS = C190[3:10]
WARNING_MESSAGES = {
    'PARTIAL_EFD_NOT_PVA_VALIDATED': 'Arquivo parcial do Bloco C; não constitui EFD integral nem foi validado no PVA.',
    'PVA_BLOCK_IMPORT_REPLACES_EXISTING_BLOCK': 'Importar um bloco no PVA substitui todas as informações desse bloco. O 0000 deve coincidir com a EFD aberta.',
    'OTHER_MODELS_ADJUSTMENTS_FCP_AND_ASSESSMENTS_NOT_COVERED': 'Cobertura inicial: NFC-e próprias escrituradas. Outros modelos, ajustes, FCP e apuração não estão cobertos.',
    'DOCUMENTS_NOT_EXPORTED': 'Os documentos listados em skipped não foram incluídos neste arquivo parcial.',
    'HEADER_VALUE_MISSING': 'Há campo obrigatório do cabeçalho não informado; a exportação permanece disponível.',
    'BOOK_VALUE_MISSING': 'Valor da escrituração não informado: campo mantido em branco, sem presumir zero ou crédito.',
    'BOOK_VALUE_INVALID': 'Valor não representável neste campo: mantido em branco, sem alterar a escrituração.',
    'FIELD_NOT_REPRESENTABLE': 'Campo com caractere não representável foi deixado em branco; o valor original permanece no cadastro/documento.',
    'LAYOUT_PERIOD_NOT_VERIFIED': 'O leiaute deste período ainda não foi verificado neste incremento; confira no PVA.',
}


def _leaf(snapshot, path):
    nodes = [snapshot or {}]
    for tag in path.split('/'):
        nodes = [child for node in nodes for child in node.get('children', []) if child.get('tag') == tag]
    values = [node.get('text', '') for node in nodes]
    return values[0] if len(values) == 1 else None


class _Writer:
    def __init__(self):
        self.warnings = []
        self.seen = set()
        self.current_document = None
        self.buckets = {}

    def warn(self, code, *, document_id=None, record='', field=''):
        if document_id != self.current_document:
            self.seen.clear()
            self.current_document = document_id
        key = (code, record, field)
        if key not in self.seen:
            if key not in self.buckets:
                self.buckets[key] = dict(code=code, severity='warning', message=WARNING_MESSAGES.get(code, 'Confira o registro e campo indicados na escrituração; a exportação permanece disponível.'), record=record, field=field,
                                        count=0, document_ids=[])
                self.warnings.append(self.buckets[key])
            warning = self.buckets[key]
            warning['count'] += 1
            if document_id is not None:
                warning['document_ids'].append(document_id)
            self.seen.add(key)

    def record(self, code, fields, values, did=None):
        output = []
        for field in fields:
            value = str(values.get(field) if values.get(field) is not None else '')
            if value != value.strip():
                self.warn('FIELD_WHITESPACE', document_id=did, record=code, field=field)
                value = value.strip()
            if '|' in value or any(ord(c) < 32 or ord(c) == 127 or ord(c) > 255 for c in value):
                self.warn('FIELD_NOT_REPRESENTABLE', document_id=did, record=code, field=field)
                value = ''
            output.append(value)
        return '|' + '|'.join([code, *output]) + '|'

    def amount(self, value, did, field, required=True, record='C190'):
        if value in (None, ''):
            if required:
                self.warn('BOOK_VALUE_MISSING', document_id=did, record=record, field=field)
            return None
        try:
            if isinstance(value, bool) or isinstance(value, float):
                raise InvalidOperation
            number = Decimal(str(value))
            if not number.is_finite() or number < 0 or number != number.quantize(Decimal('.01')):
                raise InvalidOperation
            return number
        except (InvalidOperation, ValueError):
            self.warn('BOOK_VALUE_INVALID', document_id=did, record=record, field=field)
            return None


def _money(value):
    return format(value, '.2f').replace('.', ',') if value is not None else ''


def _sum_known(values):
    return sum(values, Decimal(0)) if values and all(v is not None for v in values) else None


def _sped_date(value, writer, did, field):
    if not value:
        return ''
    try:
        return date.fromisoformat(value).strftime('%d%m%Y')
    except (ValueError, TypeError):
        writer.warn('DATE_INVALID', document_id=did, record='C100', field=field)
        return ''


def _header(company, competence, options, writer):
    supplied = options.get('header_0000')
    if supplied is not None:
        if not isinstance(supplied, str) or not supplied.startswith('|0000|') or not supplied.endswith('|') or any(c in supplied for c in '\r\n'):
            raise DomainError('header_0000 deve conter somente uma linha 0000 delimitada.')
        values = supplied[1:-1].split('|')
        if len(values) != 15:
            raise DomainError('header_0000 deve ter os 15 campos do registro 0000.')
        result = dict(zip(HEADER, values[1:]))
        if _tax_id(result['CNPJ']) != _tax_id(company['tax_id']):
            raise DomainError('Empresa do cabeçalho difere da empresa selecionada.', 409, 'company_mismatch')
        try:
            dates = [date(int(result[k][4:]), int(result[k][2:4]), int(result[k][:2])) for k in ('DT_INI', 'DT_FIN')]
            if not all(d.isoformat()[:7] == competence for d in dates) or dates[0] > dates[1]:
                raise ValueError
        except ValueError:
            raise DomainError('Período do cabeçalho difere da competência selecionada.', 409, 'period_mismatch') from None
    else:
        year, month = map(int, competence.split('-'))
        result = dict(COD_VER='020' if year == 2026 else '', COD_FIN=options.get('purpose', ''),
                      DT_INI=f'01{month:02d}{year:04d}', DT_FIN=f'{calendar.monthrange(year, month)[1]:02d}{month:02d}{year:04d}',
                      NOME=company['name'], CNPJ=company['tax_id'], CPF='', UF=company.get('state', ''),
                      IE=company.get('ie', ''), COD_MUN=company.get('ibge', ''), IM=company.get('im', ''),
                      SUFRAMA='', IND_PERFIL=options.get('profile', ''), IND_ATIV=options.get('activity', ''))
    for field in ('COD_FIN', 'NOME', 'UF', 'IE', 'COD_MUN', 'IND_PERFIL', 'IND_ATIV'):
        if not result.get(field):
            writer.warn('HEADER_VALUE_MISSING', record='0000', field=field)
    if competence[:4] != '2026' or result.get('COD_VER') != '020':
        writer.warn('LAYOUT_PERIOD_NOT_VERIFIED', record='0000', field='COD_VER')
    if result.get('IND_PERFIL') not in ('A', 'B', 'C') or result.get('IND_ATIV') not in ('0', '1') or result.get('COD_FIN') not in ('0', '1'):
        writer.warn('HEADER_CLASSIFICATION_REVIEW', record='0000')
    if not re.fullmatch('[0-9]{14}', result['CNPJ']):
        writer.warn('CNPJ_020_REVIEW', record='0000', field='CNPJ')
    return writer.record('0000', HEADER, result)


def _scope(document, company, competence):
    if document.get('company_id') != company['id'] or document.get('period') != competence:
        raise DomainError('Documento fora da empresa ou competência selecionada.', 409, 'stale_context')
    if document.get('status') != 'booked':
        return 'NOT_BOOKED'
    if document.get('model') != '65' or document.get('direction') != 'outgoing':
        return 'MODEL_OR_DIRECTION_NOT_COVERED'
    if document.get('book_cancellation') or document.get('document_state') == 'cancelled':
        return 'CANCELLATION_NOT_COVERED'
    record = (document.get('source') or {}).get('record')
    if record == 'C100' and (document.get('raw_fields') or {}).get('COD_SIT') in ('02', '03', '04', '05'):
        return 'NON_ACTIVE_SITUATION_NOT_COVERED'
    if record == 'C100' and (document.get('raw_fields') or {}).get('IND_EMIT') == '0':
        return None
    if record == 'infNFe' and _tax_id((document.get('issuer') or {}).get('tax_id')) == _tax_id(company['tax_id']):
        return None
    return 'OWN_ISSUANCE_NOT_ESTABLISHED'


def _analytics(document, lines, writer):
    groups = {}
    did = document['id']
    source_rows = document.get('analytics') or []
    for index, line in enumerate(lines):
        cst = line.get('cst_icms') or ''
        if len(cst) == 2 and re.fullmatch('[0-8]', line.get('origin') or ''):
            cst = line['origin'] + cst
        cfop = line.get('cfop') or ''
        rate = writer.amount(line.get('rate'), did, 'ALIQ_ICMS', required=False)
        key = (cst, cfop, rate)
        if not re.fullmatch('[0-9]{3}', cst):
            writer.warn('CST_REVIEW', document_id=did, record='C190', field='CST_ICMS')
        if not re.fullmatch('5[0-9]{3}', cfop):
            writer.warn('NFCE_CFOP_REVIEW', document_id=did, record='C190', field='CFOP')
        for reason in line.get('pending', []):
            writer.warn('POSTING_' + reason, document_id=did, record='C190')
        declared = line.get('declared_taxes') or {}
        row = dict(zip(AMOUNTS, [line.get('document_total'), line.get('book_base'), line.get('book_icms'),
            declared.get('VL_BC_ICMS_ST'), declared.get('VL_ICMS_ST'), declared.get('VL_RED_BC'),
            declared.get('VL_IPI') if line.get('source_kind') == 'sped_c190' else line.get('book_ipi')]))
        values = {field: writer.amount(value, did, field) for field, value in row.items()}
        obs = (source_rows[index].get('raw_fields') or {}).get('COD_OBS', '') if index < len(source_rows) else ''
        if obs:
            writer.warn('OBSERVATION_REFERENCE_REQUIRED', document_id=did, record='C190', field='COD_OBS')
        if key not in groups:
            groups[key] = (values, obs)
        else:
            existing, previous_obs = groups[key]
            groups[key] = ({field: _sum_known([existing[field], values[field]]) for field in AMOUNTS}, obs if obs == previous_obs else '')
            if obs != previous_obs:
                writer.warn('MIXED_OBSERVATIONS', document_id=did, record='C190', field='COD_OBS')
    return groups


def _document_records(document, company, competence, writer):
    did = document['id']
    lines = fiscal_posting_lines(document)
    groups = _analytics(document, lines, writer)
    raw = document.get('raw_fields') or {}
    snapshot = document.get('declared_document_fields') or {}
    xml_totals = document.get('taxes') or {}
    status = raw.get('COD_SIT') if document.get('source', {}).get('record') == 'C100' else (
        '00' if document.get('authorization', {}).get('status') in ('100', '150') else '')
    if status not in ('00', '01', '06', '07', '08'):
        writer.warn('DOCUMENT_SITUATION_REVIEW', document_id=did, record='C100', field='COD_SIT')
    if document.get('environment') not in (None, '', '1'):
        writer.warn('XML_ENVIRONMENT_REVIEW', document_id=did, record='C100')
    if document['issue_date'][:7] != competence:
        writer.warn('ISSUE_OUTSIDE_POSTING_PERIOD', document_id=did, record='C100', field='DT_DOC')
    if document.get('declared_new_total'):
        writer.warn('RTC_TOTAL_REVIEW', document_id=did, record='C100', field='VL_DOC')
    if document.get('import_posting', {}).get('review_pending') or not document.get('reviewed_by'):
        writer.warn('DOCUMENT_REVIEW_PENDING', document_id=did, record='C100')
    key = document.get('key', '')
    if re.fullmatch('[0-9]{44}', key):
        total = sum(int(c) * (2 + i % 8) for i, c in enumerate(reversed(key[:43])))
        dv = 11 - total % 11
        if int(key[-1]) != (0 if dv >= 10 else dv):
            writer.warn('KEY_CHECK_DIGIT_REVIEW', document_id=did, record='C100', field='CHV_NFE')
        if key[20:22] != '65' or _tax_id(key[6:20]) != _tax_id(company['tax_id']) or key[22:25].lstrip('0') != document.get('series', '').lstrip('0') or key[25:34].lstrip('0') != document.get('number', '').lstrip('0'):
            writer.warn('KEY_IDENTITY_REVIEW', document_id=did, record='C100', field='CHV_NFE')
    else:
        writer.warn('KEY_STRUCTURE_REVIEW', document_id=did, record='C100', field='CHV_NFE')
    base = _sum_known([v[0]['VL_BC_ICMS'] for v in groups.values()])
    icms = _sum_known([v[0]['VL_ICMS'] for v in groups.values()])
    values = dict(IND_OPER='1', IND_EMIT='0', COD_MOD='65', COD_SIT=status,
        SER=document.get('series', ''), NUM_DOC=document.get('number', ''), CHV_NFE=key,
        DT_DOC=_sped_date(document.get('issue_date'), writer, did, 'DT_DOC'),
        DT_E_S=_sped_date(document.get('movement_date'), writer, did, 'DT_E_S') if document.get('movement_date') else raw.get('DT_E_S', ''),
        VL_DOC=_money(Decimal(document['total_cents']) / 100), IND_PGTO=raw.get('IND_PGTO') or _leaf(snapshot, 'pag/detPag/indPag') or _leaf(snapshot, 'ide/indPag') or '',
        IND_FRT=raw.get('IND_FRT') or _leaf(snapshot, 'transp/modFrete') or '',
        VL_BC_ICMS=_money(base), VL_ICMS=_money(icms))
    for field, xml_tag in [('VL_ABAT_NT', None), ('VL_DESC', 'vDesc'), ('VL_MERC', 'vProd'), ('VL_FRT', 'vFrete'), ('VL_SEG', 'vSeg'), ('VL_OUT_DA', 'vOutro')]:
        source = raw.get(field)
        # Raw EFD monetary strings use a comma; normalized XML values use a dot.
        amount = writer.amount(source.replace(',', '.') if source not in (None, '') else xml_totals.get('ICMSTot/' + xml_tag) if xml_tag else None, did, field, required=False, record='C100')
        values[field] = _money(amount)
    for field in ('IND_PGTO', 'IND_FRT', 'VL_BC_ICMS', 'VL_ICMS'):
        if values[field] == '':
            writer.warn('DOCUMENT_VALUE_MISSING', document_id=did, record='C100', field=field)
    if values['IND_PGTO'] not in ('0', '1', '2'):
        writer.warn('PAYMENT_INDICATOR_REVIEW', document_id=did, record='C100', field='IND_PGTO')
    if values['IND_FRT'] not in ('0', '1', '2', '3', '4', '9'):
        writer.warn('FREIGHT_INDICATOR_REVIEW', document_id=did, record='C100', field='IND_FRT')
    if not re.fullmatch('[0-9]{3}', values['SER']):
        writer.warn('SERIES_REVIEW', document_id=did, record='C100', field='SER')
    if not groups:
        writer.warn('ANALYTICS_MISSING', document_id=did, record='C190')
    records = [writer.record('C100', C100, values, did)]
    for (cst, cfop, rate), (amounts, obs) in sorted(groups.items(), key=lambda x: (x[0][0], x[0][1], str(x[0][2]))):
        fields = dict(CST_ICMS=cst, CFOP=cfop, ALIQ_ICMS=_money(rate), COD_OBS=obs)
        fields.update({field: _money(value) for field, value in amounts.items()})
        records.append(writer.record('C190', C190, fields, did))
    # C100 NFC-e fields prohibited by exception 9 are absent from values and serialize blank.
    return records, len(lines)


def generate_nfce_block_c(documents, *, company, competence, options=None):
    """Return a partial block and trace from current booked values, without writes."""
    competence = period(competence)
    options = options or {}
    writer = _Writer()
    writer.warn('PARTIAL_EFD_NOT_PVA_VALIDATED')
    writer.warn('PVA_BLOCK_IMPORT_REPLACES_EXISTING_BLOCK')
    writer.warn('OTHER_MODELS_ADJUSTMENTS_FCP_AND_ASSESSMENTS_NOT_COVERED')
    header = _header(company, competence, options, writer)
    entries, skipped, input_count = [], [], 0
    for document in documents:
        input_count += 1
        reason = _scope(document, company, competence)
        if reason:
            skipped.append(dict(document_id=document['id'], reason=reason))
            continue
        records, posting_lines = _document_records(document, company, competence, writer)
        reference = {key: document.get(key) for key in ('id', 'version', 'key', 'source_hash', 'posting_date', 'issue_date', 'series', 'number', 'total_cents')}
        entries.append((reference, records, posting_lines))
    entries.sort(key=lambda x: (x[0]['issue_date'], x[0].get('series', ''), x[0].get('number', ''), x[0]['id']))
    identities = Counter((d['series'], d['number']) for d, _, _ in entries)
    keys = Counter(d.get('key', '') for d, _, _ in entries)
    output = [header, '|C001|' + ('0' if entries else '1') + '|']
    trace = []
    for document, records, posting_lines in entries:
        did = document['id']
        if identities[document['series'], document['number']] > 1 or keys[document.get('key', '')] > 1:
            writer.warn('DUPLICATE_IDENTITY_REVIEW', document_id=did, record='C100')
        trace.append(dict(document_id=did, version=document['version'], key=document.get('key', ''),
            source_hash=document.get('source_hash', ''), posting_date=document['posting_date'],
            issue_date=document['issue_date'], c100_line=len(output) + 1, c190_count=len(records) - 1,
            posting_line_count=posting_lines))
        output.extend(records)
    output.append('|C990|' + str(len(output)) + '|')  # len before append includes 0000, excludes C990.
    payload = ('\r\n'.join(output) + '\r\n').encode('latin-1')
    skipped.sort(key=lambda x: x['document_id'])
    for item in skipped:
        writer.warn('DOCUMENTS_NOT_EXPORTED', document_id=item['document_id'])
    for warning in writer.warnings:
        warning['document_ids'].sort()
    writer.warnings.sort(key=lambda x: (x['code'], x['record'], x['field']))
    return dict(payload=payload, kind='EFD_ICMS_IPI_PARTIAL_BLOCK_C', complete_efd=False,
        pva_validated=False, transmitted=False, can_export=True, representation='individual_nfce',
        company_id=company['id'], period=competence, encoding='ISO-8859-1',
        result_sha256=sha256(payload).hexdigest(), trace=trace, skipped=skipped, warnings=writer.warnings,
        summary=dict(input_documents=input_count, exported_documents=len(entries),
            skipped_documents=len(skipped), c190_records=sum(len(r) - 1 for _, r, _ in entries),
            total_cents=sum(d['total_cents'] for d, _, _ in entries)),
        rules=dict(guide='3.2.4', layout='020', supported_year=2026, guide_url=GUIDE_URL))
