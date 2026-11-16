"""Read-only accounting evidence for ECD preparation; never an ECD serializer.

Use the same effective account view and journal/line records as Core.journals,
but read all inputs under one snapshot. No reference allocation, posting,
normalization, fiscal classification or assumption of complete opening balances.
"""
import calendar
import json
from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta

from fastapi import Request
from fastapi.responses import Response
from ..core import DomainError, company_row, digest, iso_date, pack
from ..permissions import effect

REFERENCE = {
    'layout_family': '9', 'I010_COD_VER_LC_reference': '9.00',
    'checked_on': '2026-11-15', 'calendar_year_reviewed': 2025, 'manual_revision': 'janeiro/2026; ADE Cofis 1/2026',
    'url': 'https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/ecd/manuais-e-documentos-tecnicos/manual_de_orientacao_da_ecd_leiaute_9_janeiro_2026.pdf/@@display-file/file',
    'sha256': '7ddf47755f616ecd76671b8be9c8b61e30adbb0e8408634e45af95f616119b2e',
    'pages_reviewed': [102, 103, 117, 118, 130, 131, 133, 134, 135, 142, 143, 147, 148, 149],
    'later_revision_reviewed': False,
}


def amount(cents):
    """Both cents and decimal are strings, including above JS's safe integer."""
    sign = '-' if cents < 0 else ''
    value = abs(cents)
    return {'cents': str(cents), 'decimal': f'{sign}{value // 100}.{value % 100:02d}'}


def bounds(start, end):
    start, end = iso_date(start, 'Data inicial'), iso_date(end, 'Data final')
    if start > end:
        raise DomainError('Data inicial posterior à final.')
    if start[:4] != end[:4]:
        raise DomainError('O snapshot deve abranger um único exercício; solicite os exercícios separadamente.')
    return start, end


def months(start, end):
    day, last = date.fromisoformat(start), date.fromisoformat(end)
    while day <= last:
        finish = min(last, date(day.year, day.month, calendar.monthrange(day.year, day.month)[1]))
        yield day.isoformat(), finish.isoformat()
        if finish == last:
            break
        day = finish + timedelta(days=1)


def balance_row(key, value, debits=0, credits=0, line_ids=()):
    closing = value + debits - credits
    return {'account_id': key[0], 'cost_center_id': key[1],
            'recorded_opening': amount(value), 'recorded_debits': amount(debits),
            'recorded_credits': amount(credits), 'recorded_closing': amount(closing),
            'recorded_opening_dc': 'D' if value > 0 else 'C' if value < 0 else None,
            'recorded_closing_dc': 'D' if closing > 0 else 'C' if closing < 0 else None,
            'ecd_opening_balance': None, 'ecd_closing_balance': None,
            'movement_line_ids': list(line_ids)}


def _snapshot(conn, cid, start, end):
    company = company_row(conn, cid)
    warnings = [
        {'code': 'PREPARATION_ONLY', 'message': 'JSON preparatório, sem arquivo ECD, assinatura, transmissão ou validação oficial.'},
        {'code': 'OPENING_AND_COMPLETENESS_UNATTESTED', 'message': 'Saldos observados somam somente partidas armazenadas; abertura, integridade histórica e encerramento ECD não foram atestados. Valores ECD permanecem nulos.'},
        {'code': 'MANUAL_REVISION_FROZEN', 'message': 'Base conferida: janeiro/2026. Revisão maio/2026 publicada; download retornou HTTP 503 e confronto integral permanece pendente.'},
        {'code': 'ECD_CLASSIFICATIONS_MISSING', 'message': 'Faltam datas de alteração/natureza/hierarquia ECD das contas, plano referencial, tipo de lançamento/livro, responsáveis e demonstrações. Não inferidos dos códigos ou do histórico.'},
        {'code': 'CURRENT_DEFINITIONS', 'message': 'Contas e centros refletem definições atuais resolvidas pelo domínio, com versões/fontes. Vigência histórica campo a campo não atestada.'},
    ]
    if start[8:] != '01' or int(end[8:]) != calendar.monthrange(int(end[:4]), int(end[5:7]))[1]:
        warnings.append({'code': 'PARTIAL_MONTH_SCOPE', 'message': 'Recorte de consulta contém fração de mês; não comprova situação especial ou período oficial de livro.'})
    if start[:4] != str(REFERENCE['calendar_year_reviewed']):
        warnings.append({'code': 'REFERENCE_YEAR_NOT_REVIEWED', 'message': 'Dados exportados; o exercício solicitado não é o ano-calendário 2025 da matriz conferida.'})
    accounts = [dict(r) for r in conn.execute('''SELECT a.*,g.global_plan_id AS definition_plan_id,
        p.sha256 AS definition_plan_sha256 FROM effective_accounts a
        LEFT JOIN global_account_entries g ON g.id=a.shared_entry_id
        LEFT JOIN global_account_plans p ON p.id=g.global_plan_id
        WHERE a.company_id=? ORDER BY a.access_code,a.id''', (cid,))]
    aliases = defaultdict(list)
    for row in conn.execute('SELECT account_id,global_entry_id FROM company_account_aliases WHERE company_id=? ORDER BY global_entry_id', (cid,)):
        aliases[row['account_id']].append(row['global_entry_id'])
    for account in accounts:
        account['global_alias_entry_ids'] = aliases[account['id']]
        account['ecd_candidates'] = {'COD_CTA': account['access_code'], 'CTA': account['name'],
            'IND_CTA': 'A' if account['analytical'] else 'S', 'DT_ALT': None,
            'COD_NAT': None, 'NIVEL': None, 'COD_CTA_SUP': None}
    by_account = {a['id']: a for a in accounts}
    binding = conn.execute('''SELECT b.*,p.name,p.sha256,p.parent_id FROM company_account_plan_bindings b
        JOIN global_account_plans p ON p.id=b.global_plan_id WHERE b.company_id=?''', (cid,)).fetchone()
    centers = {r['id']: dict(r) for r in conn.execute('SELECT * FROM cost_centers WHERE company_id=? ORDER BY code,id', (cid,))}
    journals = []
    for row in conn.execute('''SELECT id,number,date,period,document,history,total_cents,reversal_of,
        reversed_by,created_at,created_by FROM journals WHERE company_id=? AND date<=? ORDER BY date,id''', (cid, end)):
        journal = dict(row)
        journal['status'] = 'reversed' if journal['reversed_by'] else 'posted'
        journal['lines'], journal['source_references'], journal['audit_events'] = [], [], []
        journal['ecd_candidates'] = {'NUM_LCTO': str(journal['number']), 'DT_LCTO': journal['date'],
            'VL_LCTO': amount(journal.pop('total_cents')),
            'IND_LCTO': None, 'DT_LCTO_EXT': None, 'VL_LCTO_MF': None}
        journals.append(journal)
    by_journal = {j['id']: j for j in journals}
    for row in conn.execute('''SELECT l.* FROM journal_lines l JOIN journals j
        ON j.company_id=l.company_id AND j.id=l.journal_id
        WHERE j.company_id=? AND j.date<=? ORDER BY j.date,j.id,l.position,l.id''', (cid, end)):
        line = dict(row)
        journal = by_journal[line['journal_id']]
        account, center = by_account.get(line['account_id']), centers.get(line['cost_center_id'])
        debit, credit = line.pop('debit_cents'), line.pop('credit_cents')
        line['debit'], line['credit'] = amount(debit), amount(credit)
        line['ecd_candidates'] = {'COD_CTA': account['access_code'] if account else None,
            'COD_CCUS': center['code'] if center else None,
            'VL_DC': amount(debit + credit), 'IND_DC': 'D' if debit else 'C',
            'NUM_ARQ': None, 'COD_HIST_PAD': None, 'HIST': journal['history'], 'COD_PART': None,
            'VL_DC_MF': None, 'IND_DC_MF': None}
        line['history_source'] = 'journal_header'
        if account is None or line['cost_center_id'] is not None and center is None:
            warnings.append({'code': 'MISSING_ACCOUNT_OR_CENTER', 'journal_id': journal['id'], 'line_id': line['id']})
        journal['lines'].append(line)
    # Only identifiers/relationships are exposed, never fiscal/financial payloads or files.
    for table, columns in [('documents', ('journal_id',)), ('settlements', ('journal_id', 'reversal_journal_id'))]:
        for column in columns:
            for row in conn.execute(f'SELECT id,{column} AS jid FROM {table} WHERE company_id=? AND {column} IS NOT NULL ORDER BY id', (cid,)):
                if row['jid'] in by_journal:
                    by_journal[row['jid']]['source_references'].append({'entity': table, 'id': row['id'], 'relationship': column})
    for row in conn.execute("SELECT id,entity_id,action,created_at FROM audit WHERE company_id=? AND entity='journal' ORDER BY id", (cid,)):
        if row['entity_id'].isdigit() and int(row['entity_id']) in by_journal:
            by_journal[int(row['entity_id'])]['audit_events'].append({k: row[k] for k in ('id', 'action', 'created_at')})
    for row in conn.execute("SELECT id,file_id,layout,fingerprint,result_json FROM module_imports WHERE company_id=? AND module='accounting' AND result_json IS NOT NULL ORDER BY id", (cid,)):
        if not row['layout'].startswith(('journals-', 'openings-')):
            continue
        for written in json.loads(row['result_json']).get('written', []):
            if written['id'] in by_journal:
                by_journal[written['id']]['source_references'].append({
                    'entity': 'module_imports', 'id': row['id'], 'file_id': row['file_id'],
                    'fingerprint': row['fingerprint'], 'selection': written['selection']})
    before, selected = [], []
    prior = defaultdict(int)
    prior_lines = defaultdict(list)
    for journal in journals:
        debits = sum(int(line['debit']['cents']) for line in journal['lines'])
        credits = sum(int(line['credit']['cents']) for line in journal['lines'])
        journal['reconciliation'] = {'debits': amount(debits), 'credits': amount(credits),
            'matches_stored_total': bool(journal['lines']) and debits == credits == int(journal['ecd_candidates']['VL_LCTO']['cents'])}
        if not journal['reconciliation']['matches_stored_total']:
            warnings.append({'code': 'JOURNAL_TOTAL_MISMATCH', 'journal_id': journal['id']})
        if any(event['action'] == 'opening' for event in journal['audit_events']):
            warnings.append({'code': 'OPENING_ENTRY_REQUIRES_ECD_TREATMENT', 'journal_id': journal['id'],
                'message': 'Abertura explícita preservada como lançamento; não convertida automaticamente em saldo inicial ECD.'})
        if journal['period'] != journal['date'][:7]:
            warnings.append({'code': 'JOURNAL_PERIOD_MISMATCH', 'journal_id': journal['id'],
                             'message': 'Competência armazenada difere da data; agrupamento usa a data real preservada.'})
        journal['source_record_sha256'] = digest(journal)
        (before if journal['date'] < start else selected).append(journal)
        if journal['date'] < start:
            for line in journal['lines']:
                key = (line['account_id'], line['cost_center_id'])
                prior[key] += int(line['debit']['cents']) - int(line['credit']['cents'])
                prior_lines[key].append(line['id'])
    order = lambda key: (key[0], key[1] is not None, key[1] or 0)
    initial = [{'account_id': key[0], 'cost_center_id': key[1], 'recorded_balance': amount(prior[key]),
                'line_ids': prior_lines[key], 'ecd_opening_balance': None} for key in sorted(prior, key=order)]
    period_journals = defaultdict(list)
    for journal in selected:
        period_journals[journal['date'][:7]].append(journal)
    monthly = []
    rolling = dict(prior)
    for first, last in months(start, end):
        movements = defaultdict(lambda: [0, 0, []])
        entries = period_journals[first[:7]]
        for journal in entries:
            for line in journal['lines']:
                key = (line['account_id'], line['cost_center_id'])
                movements[key][0] += int(line['debit']['cents'])
                movements[key][1] += int(line['credit']['cents'])
                movements[key][2].append(line['id'])
        rows = [balance_row(key, rolling.get(key, 0), *movements.get(key, (0, 0, [])))
                for key in sorted(rolling.keys() | movements.keys(), key=order)]
        rolling = {(r['account_id'], r['cost_center_id']): int(r['recorded_closing']['cents']) for r in rows}
        monthly.append({'start': first, 'end': last, 'journal_ids': [j['id'] for j in entries], 'balances': rows})
    if not selected:
        warnings.append({'code': 'NO_RECORDED_JOURNALS_IN_RANGE', 'message': 'Ausência de lançamentos no intervalo não atesta inatividade ou saldo zero ECD.'})
    used_centers = sorted({line['cost_center_id'] for j in journals for line in j['lines'] if line['cost_center_id'] in centers})
    selected_debits = sum(int(j['reconciliation']['debits']['cents']) for j in selected)
    selected_credits = sum(int(j['reconciliation']['credits']['cents']) for j in selected)
    return {'schema_version': 1, 'artifact_type': 'ecd_preparation_snapshot_json',
        'complete_ecd': False, 'validated_in_official_program': False, 'transmitted': False,
        'warnings_block_export': False, 'reference': deepcopy(REFERENCE),
        'scope': {'company_id': cid, 'calendar_year': int(start[:4]), 'start': start, 'end': end,
                  'opening_history_includes_prior_years': True},
        'company': {key: company[key] for key in ('id', 'code', 'name', 'tax_id', 'version')},
        'plan_binding': dict(binding) if binding else None, 'accounts': accounts,
        'cost_centers': [centers[key] | {'ecd_DT_ALT': None} for key in used_centers],
        'opening_history': {'basis': 'recorded_lines_only_not_certified_ecd_opening',
                            'journals': before, 'recorded_balances': initial},
        'journals': selected, 'monthly_balances': monthly,
        'reconciliation': {'recorded_debits': amount(selected_debits), 'recorded_credits': amount(selected_credits),
                           'balanced': selected_debits == selected_credits, 'has_recorded_journals': bool(selected),
                           'meaning': 'arithmetic_of_recorded_rows_only',
                           'journal_totals_match': all(j['reconciliation']['matches_stored_total'] for j in journals)},
        'coverage': {'book_kind': None, 'referential_plan': None, 'source_links': 'current_links_and_journal_audit_and_accounting_import_refs_only',
                     'historical_definitions_attested': False, 'opening_balances_attested': False,
                     'signers': None, 'financial_statements': None, 'functional_currency': None,
                     'candidates_are_serialized_ecd_records': False, 'history_per_line': 'journal_header_only'}, 'warnings': warnings}


def accounting_snapshot(core, cid, start, end):
    start, end = bounds(start, end)
    with core.db.read(snapshot=True) as conn:
        for routine, action in [('accounting.journals', 'read'), ('accounting.journals', 'export'), ('accounting.accounts', 'read')]:
            effect(conn, cid, routine, action)
        snapshot = _snapshot(conn, cid, start, end)
        from .ecd_contracts import declared_metadata, preparation_review
        snapshot['schema_version'] = 2
        snapshot['preparation_review'] = preparation_review(snapshot, declared_metadata(conn, cid))
        return {'snapshot': snapshot, 'snapshot_sha256': digest(snapshot)}


def register_ecd_snapshot_routes(app, core, check_period):
    @app.get('/api/companies/{cid}/sped-generator/accounting-snapshot')
    def ecd_snapshot(cid: int, request: Request, start: str, end: str):
        start, end = bounds(start, end)
        check_period(request, start[:7])
        session = request.state.session
        if session['active_company_id'] != cid or session.get('module', 'fiscal') != 'accounting':
            raise DomainError('Ative a empresa e o módulo Contábil do snapshot.', 409, 'stale_context')
        for header, expected in [('x-company-id', str(cid)), ('x-year', start[:4]), ('x-module', 'accounting')]:
            if request.headers.get(header) and request.headers[header] != expected:
                raise DomainError('O contexto mudou. Reabra o snapshot na empresa, exercício e módulo selecionados.', 409, 'stale_context')
        result = accounting_snapshot(core, cid, start, end)
        return Response(pack(result) + '\n', media_type='application/json', headers={
            'Content-Disposition': f'attachment; filename="ecd-preparacao-{cid}-{start}-{end}.json"',
            'Cache-Control': 'no-store', 'X-Snapshot-SHA256': result['snapshot_sha256']})
