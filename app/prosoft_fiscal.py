"""Intercâmbio parcial de notas Prosoft; não gera EFD nem altera a escrituração."""
from calendar import monthrange
from decimal import Decimal, InvalidOperation
from io import BytesIO
import re
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from .core import DomainError, audit, company_row, digest, money, now, pack, period
from .fiscal_analytics import fiscal_posting_lines
from .prosoft import ascii_field, numeric, put
from .prosoft_profiles import selected_types

LAYOUT = 'PROSOFT-FISCAL-NOTAS-20261029-v1'
WIDTHS = {'incoming': 2340, 'outgoing': 2611}
FILES = {'incoming': 'ENTRADAS.TXT', 'outgoing': 'SAIDAS.TXT'}
# Source: layoutimportdos_29102026.pdf pp. 1–7, 11–18. Positions are one-based.
POSITIONS = {
    'incoming': {'date': 19, 'issue': 25, 'number': 869, 'species': 858,
                 'series': 864, 'split': 43, 'account': 44, 'cfop': 624,
                 'total': 211, 'base': 66, 'icms': 80, 'other': 108,
                 'ipi': 155, 'key': 973, 'party': 5, 'state': 517, 'ie': 499},
    'outgoing': {'date': 20, 'issue': 728, 'number': 989, 'species': 978,
                 'series': 984, 'split': 19, 'account': 26, 'cfop': 734,
                 'total': 34, 'base': 62, 'icms': 76, 'other': 104,
                 'ipi': 132, 'key': 1377, 'party': 254, 'state': 273, 'ie': 1037},
}
LIMITATIONS = [
    'Intercâmbio parcial de notas modelos 55/65. Não é EFD oficial, apuração ou transmissão.',
    'Itens, faturas, meios de pagamento, cadastros, ST/FCP/DIFAL, PIS/COFINS, IBS/CBS e ajustes não exportados.',
    'Campos sem origem inequívoca ficam em branco; a instalação de destino pode interpretar brancos como zero.',
    'Plano e empresa precisam ser selecionados no destino; os arquivos fiscais não contêm esses parâmetros.',
    'Repetir o download não duplica o lote local; reimportar no Prosoft pode duplicar movimentos.',
]


def decimal_field(value, width=14):
    cents = money(value, 'Valor fiscal')
    out = f'{cents // 100:0{width - 3}d}.{cents % 100:02d}'
    if len(out) != width:
        raise DomainError('Valor excede o campo fiscal Prosoft; sem truncamento.')
    return out


def date_field(value):
    from .core import iso_date
    value = iso_date(value)
    if not '2000' <= value[:4] <= '2099':
        raise DomainError('Leiaute fiscal DDMMAA deste perfil cobre 2000 a 2099.')
    return value[8:10] + value[5:7] + value[2:4]


def object_map(value, label):
    if not isinstance(value, dict) or any(not isinstance(v, dict) for v in value.values()):
        raise DomainError(f'{label}: informe um objeto de mapeamentos.')
    return value


def encode_fiscal(documents, payload):
    """Pure snapshot encoder. Incomplete fiscal decisions are warnings, never zeros."""
    record_types = selected_types('fiscal', payload.get('record_types'))
    species = object_map(payload.get('species', {}), 'Espécies por modelo')
    accounts = object_map(payload.get('cfop_accounts', {}), 'Contas por CFOP')
    records = {k: [] for k in WIDTHS}
    trace, skipped, warnings, changes = [], [], [], []
    totals = {k: {'documents': 0, 'records': 0, 'total_cents': 0} for k in WIDTHS}
    for doc in documents:
        did = doc['id']
        reason = ('layout_not_selected' if ('incoming_notes' if doc['direction']=='incoming' else 'outgoing_notes') not in record_types else
                  'not_booked' if doc['status'] != 'booked' else
                  'cancellation_not_supported' if doc.get('book_cancellation') else
                  'model_not_supported' if doc['model'] not in {'55', '65'} else '')
        if reason:
            skipped.append({'document_id': did, 'reason': reason, 'total_cents': doc['total_cents']})
            continue
        direction = doc['direction']
        p = POSITIONS[direction]
        config = species.get(doc['model'], {})
        code = config.get('code', '')
        if not isinstance(code, str) or not re.fullmatch('[A-Z0-9]{1,5}', code) or config.get('confirmed') is not True:
            skipped.append({'document_id': did, 'reason': 'species_mapping_required', 'total_cents': doc['total_cents']})
            continue
        try:
            lines = fiscal_posting_lines(doc)
        except (InvalidOperation, ValueError, TypeError):
            raise DomainError('Campos numéricos da escrituração não são representáveis no leiaute fiscal.') from None
        if not lines or len(lines) > 35:
            raise DomainError('O perfil suporta de 1 a 35 desdobramentos por nota; sem descarte de linhas.')
        if sum(money(line['document_total'], 'Valor contábil') for line in lines) != doc['total_cents']:
            raise DomainError('Linhas fiscais não reconciliam com o total da nota.', 409, 'fiscal_total_mismatch')
        number = numeric(doc['number'], 10, 'Número da nota')
        series = str(doc.get('series') or '')
        if series and not re.fullmatch('[A-Z0-9]{1,3}', series):
            raise DomainError('Série fiscal excede o perfil de três posições ou contém caracteres inválidos.')
        key = str(doc.get('key') or '')
        if key and not re.fullmatch('[0-9]{44}', key):
            raise DomainError('Chave fiscal deve ter 44 dígitos ASCII.')
        party = doc.get('issuer', {}) if direction == 'incoming' else doc.get('recipient', {})
        party = party if isinstance(party, dict) else {}
        partner_id = str(doc.get('partner_tax_id') or '')
        # The header layout names a CNPJ field. CPF/alpha CNPJ require a separate profile.
        partner_supported = bool(re.fullmatch('[0-9]{14}', partner_id))
        for index, line in enumerate(lines):
            out = list(' ' * WIDTHS[direction])
            pending = list(line.get('pending', []))
            def field(name, width, value):
                put(out, p[name], width, value)
            field('date', 6, date_field(doc['posting_date']))
            field('issue', 6, date_field(doc['issue_date']))
            field('number', 10, number)
            if direction == 'outgoing': put(out, 999, 10, number)
            field('species', 5, code.ljust(5))
            field('series', 3, series.ljust(3))
            field('split', 1, '123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'[index])
            field('total', 14, decimal_field(line['document_total']))
            field('key', 44, key.ljust(44))
            if not key: pending.append('KEY_NOT_INFORMED')
            cfop = line.get('cfop', '')
            if cfop:
                if not re.fullmatch('[0-9]{4}', cfop): raise DomainError('CFOP inválido para o leiaute fiscal.')
                field('cfop', 4, cfop)
            account = accounts.get(cfop, {})
            if account.get('confirmed') is True:
                field('account', 5, numeric(account.get('code', ''), 5, 'Conta fiscal no destino'))
            else: pending.append('DESTINATION_ACCOUNT_NOT_INFORMED')
            for source, target in [('book_base', 'base'), ('book_icms', 'icms'), ('book_other', 'other'), ('book_ipi', 'ipi')]:
                if line.get(source) is not None: field(target, 14, decimal_field(line[source]))
                else: pending.append(source.upper() + '_NOT_INFORMED')
            if line.get('rate') is not None:
                rate = line['rate']
                # Never silently round a rate exceeding the legacy field's precision.
                amount = Decimal(rate)
                if amount.is_finite() and amount >= 0 and amount < 100 and amount == amount.quantize(Decimal('.01')):
                    put(out, 136 if direction == 'incoming' else 188, 5, decimal_field(format(amount, '.2f'), 5))
                else: pending.append('RATE_NOT_REPRESENTABLE')
            if partner_supported: field('party', 14, partner_id)
            else: pending.append('PARTNER_CNPJ_NOT_REPRESENTABLE')
            state = party.get('state', '')
            if isinstance(state, str) and re.fullmatch('[A-Z]{2}', state): field('state', 2, state)
            else: pending.append('PARTNER_STATE_NOT_INFORMED')
            field('ie', 18, ascii_field(party.get('ie', ''), f'Inscrição estadual nota {did}', 18, changes))
            if line.get('ipi') not in {None, '0.00'}: pending.append('DECLARED_IPI_COMPONENT_NOT_EXPORTED')
            records[direction].append(''.join(out))
            trace.append({'document_id': did, 'source_hash': doc.get('source_hash', ''),
                          'source': doc.get('source', {}), 'sources': doc.get('sources', []), 'source_snapshot_sha256': digest(doc),
                          'number': doc['number'], 'series': series, 'model': doc['model'], 'direction': direction,
                          'file': FILES[direction], 'record': len(records[direction]), 'line': index + 1,
                          'posting_date': doc['posting_date'], 'issue_date': doc['issue_date'],
                          'key': key, 'item_numbers': line.get('item_numbers', []),
                          'classification': {k: line.get(k) for k in ('cfop', 'cst_icms', 'csosn', 'origin', 'rate', 'declared_classifications')},
                          'treatment': line.get('treatment'), 'total_cents': money(line['document_total'], 'Valor contábil')})
            for source in ('book_base', 'book_icms', 'book_other', 'book_ipi'):
                total_key, count_key = source + '_cents', source + '_informed_lines'
                totals[direction].setdefault(total_key, None)
                totals[direction].setdefault(count_key, 0)
                if line.get(source) is not None:
                    totals[direction][total_key] = (totals[direction][total_key] or 0) + money(line[source], source)
                    totals[direction][count_key] += 1
            if pending: warnings.append({'document_id': did, 'line': index + 1, 'codes': list(dict.fromkeys(pending))})
        totals[direction]['documents'] += 1
        totals[direction]['records'] += len(lines)
        totals[direction]['total_cents'] += doc['total_cents']
    files = {FILES[k]: ('\r\n'.join(v) + '\r\n').encode('ascii') for k, v in records.items() if v}
    manifest = {'layout': LAYOUT, 'record_widths': {FILES[k]: v for k, v in WIDTHS.items()},
                'trace': trace, 'skipped': skipped, 'warnings': warnings, 'limitations': LIMITATIONS,
                'totals': totals, 'text_changes': changes, 'needs_ascii_review': bool(changes),
                'homologated_in_destination': False, 'official_efd': False, 'transmitted': False,
                'files': {name: {'sha256': digest(raw), 'size_bytes': len(raw)} for name, raw in files.items()}}
    if 'record_types' in payload: manifest['selected_record_types'] = record_types
    return files, manifest


def archive(files, manifest):
    """Stable ZIP bytes; no clock, external paths, compression or executable entries."""
    output = BytesIO()
    with ZipFile(output, 'w', compression=ZIP_STORED) as z:
        for name, raw in [*sorted(files.items()), ('manifest.json', pack(manifest).encode('utf-8'))]:
            info = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o600 << 16
            z.writestr(info, raw)
    return output.getvalue()


class ProsoftFiscalMixin:
    def export_prosoft_fiscal(self, cid, payload, actor, confirm=False):
        competence = period(payload.get('period'))
        company_code = numeric(payload.get('company_code', ''), 4, 'Empresa Prosoft')
        plan_code = numeric(payload.get('plan_code', '050'), 4, 'Plano no destino')
        ids = payload.get('document_ids')
        if ids is not None and (not isinstance(ids, list) or not ids or
                                any(type(v) is not int or v <= 0 for v in ids) or len(set(ids)) != len(ids)):
            raise DomainError('Seleção de documentos inválida.')
        with self.db.transaction() as conn:
            from .prosoft_settings import assert_settings_version
            assert_settings_version(conn,cid,'fiscal',payload)
            company_row(conn, cid)
            from .fiscal_series import settings
            digits = settings(conn, cid)['digits']
            year, month = map(int, competence.split('-'))
            start, end = competence + '-01', competence + f'-{monthrange(year, month)[1]:02d}'
            docs = [self._document_values(r, digits) for r in conn.execute(
                'SELECT * FROM documents WHERE company_id=? AND posting_date BETWEEN ? AND ? ORDER BY posting_date,id', (cid, start, end))]
            if ids is not None:
                if not set(ids) <= {d['id'] for d in docs}:
                    raise DomainError('Seleção contém documento de outra empresa ou competência.')
                docs = [d for d in docs if d['id'] in ids]
            by_id = {d['id']: d for d in docs}
            for doc in docs: doc['sources'] = []
            import json
            for row in conn.execute('SELECT s.* FROM document_sources s JOIN documents d ON d.id=s.document_id AND d.company_id=s.company_id WHERE s.company_id=? AND d.posting_date BETWEEN ? AND ? ORDER BY s.id', (cid, start, end)):
                if row['document_id'] in by_id:
                    by_id[row['document_id']]['sources'].append({'source_hash':row['source_hash'], 'source':json.loads(row['source_json'])})
            files, manifest = encode_fiscal(docs, payload)
            manifest.update(company_id=cid, company_code=company_code, period=competence, plan_code=plan_code,
                            selection_count=len(docs), selected_total_cents=sum(d['total_cents'] for d in docs))
            raw = archive(files, manifest)
            fingerprint = digest({'content_sha256': digest(raw), 'configuration': {
                k: payload.get(k, {}) for k in ('species', 'cfop_accounts')}, 'source_snapshot': docs})
            result = {'preview_hash': fingerprint, 'filename': f'PROSOFT_FISCAL_{company_code}_{competence.replace("-", "")}.zip',
                      'sha256': digest(raw), 'manifest': manifest, 'sample': {name: data.decode('ascii').splitlines()[:2] for name, data in files.items()}}
            if not confirm: return result
            if payload.get('preview_hash') != fingerprint:
                raise DomainError('Dados ou mapeamentos alterados. Gere nova prévia.', 409, 'stale_preview')
            if not files: raise DomainError('Nenhuma nota coberta neste lote. Consulte os documentos não exportados na prévia.')
            if manifest['needs_ascii_review'] and payload.get('allow_ascii') is not True: raise DomainError('Revise e aceite a conversão dos textos para ASCII.')
            if payload.get('destination_reviewed') is not True:
                raise DomainError('Confira empresa, plano e mapeamentos no destino antes de gerar o lote.')
            existing = conn.execute('SELECT id FROM export_batches WHERE company_id=? AND layout=? AND fingerprint=?', (cid, LAYOUT, fingerprint)).fetchone()
            if existing: return result | {'id': existing['id'], 'duplicate': True}
            item_id = conn.execute('INSERT INTO export_batches(company_id,period,layout,fingerprint,filename,content,manifest_json,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?)',
                                   (cid, competence, LAYOUT, fingerprint, result['filename'], raw, pack(manifest), now(), actor)).lastrowid
            audit(conn, cid, actor, 'export', 'prosoft-fiscal', item_id, {'fingerprint': fingerprint, 'sha256': digest(raw), 'layout': LAYOUT})
            return result | {'id': item_id}
