"""Read-only observed balances for Prosoft preparation, never an SLD codec.

Grouping projects existing accounting evidence, without establishing opening
balances, destination mappings or completeness. Participant IDs belong to lines.
"""
import time
from collections import defaultdict

from fastapi import Request
from fastapi.responses import Response

from .core import DomainError, digest, pack
from .db import request_context
from .permissions import require
from .sped_generator.ecd_snapshot import _snapshot, amount, bounds, months

MAX_SOURCE_ROWS = 10000
MAX_IMPORT_JSON_CHARS = 2_000_000
MAX_RESPONSE_BYTES = 16_000_000
MAX_PROJECTED_BALANCE_ROWS = 20_000
MAX_SOURCE_TEXT_BYTES = 1_000_000
REQUIRED_READS = ('accounting.prosoft', 'accounting.journals',
                  'accounting.accounts', 'accounting.cost_centers')


def _authorize(conn, cid, start):
    ctx = request_context.get() or {}
    if not ctx.get('user_id') or not ctx.get('token_hash'):
        raise DomainError('Sessão autenticada obrigatória.', 401, 'unauthenticated')
    session = conn.execute('SELECT * FROM sessions WHERE token_hash=?', (ctx['token_hash'],)).fetchone()
    if not session or session['expires_at'] <= time.time() or session['user_id'] != ctx['user_id']:
        raise DomainError('Sessão encerrada.', 401, 'unauthenticated')
    for routine in REQUIRED_READS:
        require(conn, ctx['user_id'], cid, routine, 'read')
    if session['active_company_id'] != cid or session['module'] != 'accounting' or session['period'][:4] != start[:4]:
        raise DomainError('Reabra a consulta na empresa, exercício e módulo Contábil ativos.', 409, 'stale_context')


def _limit_sources(conn, cid, end):
    # Bound every collection read by the shared reader before materialization.
    queries = [
        ('SELECT id FROM journals WHERE company_id=? AND date<=?', (cid, end)),
        ('SELECT l.id FROM journal_lines l JOIN journals j ON j.company_id=l.company_id AND j.id=l.journal_id WHERE j.company_id=? AND j.date<=?', (cid, end)),
    ]
    queries.extend((f'SELECT 1 FROM {table} WHERE company_id=?', (cid,)) for table in (
        'effective_accounts', 'company_account_aliases', 'cost_centers', 'documents',
        'settlements', 'audit', 'module_imports'))
    for sql, args in queries:
        if len(conn.execute(sql + ' LIMIT ?', (*args, MAX_SOURCE_ROWS + 1)).fetchall()) > MAX_SOURCE_ROWS:
            raise DomainError('Volume de evidências excede o limite da consulta preparatória.', 413, 'preparation_volume_limit')
    row = conn.execute("SELECT COALESCE(SUM(LENGTH(result_json)),0) AS size FROM module_imports WHERE company_id=? AND module='accounting'", (cid,)).fetchone()
    if row['size'] > MAX_IMPORT_JSON_CHARS:
        raise DomainError('Volume de origens importadas excede o limite preparatório.', 413, 'preparation_volume_limit')

    _limit_source_text(conn, cid, end)


def _limit_source_text(conn, cid, end):
    # Explicit inventory of textual columns materialized by the shared reader,
    # including company_row's profile JSON and definition/binding joins. Keep in
    # sync with its SELECTs. Only numeric aggregates cross the DB boundary here.
    sources = [
        ('companies', 'id=?', (cid,),
         'code name trade_name tax_id regime state city address number district postal_code ibge ie im cnae email phone prosoft_code created_at updated_at profile_json'),
        ('effective_accounts a LEFT JOIN global_account_entries g ON g.id=a.shared_entry_id LEFT JOIN global_account_plans p ON p.id=g.global_plan_id',
         'a.company_id=?', (cid,), 'a.access_code a.classifier a.name a.nature a.report_group a.prosoft_code p.sha256'),
        ('company_account_plan_bindings b JOIN global_account_plans p ON p.id=b.global_plan_id',
         'b.company_id=?', (cid,), 'b.mode b.attached_at b.attached_by b.copy_scope p.name p.sha256'),
        ('cost_centers', 'company_id=?', (cid,), 'code name prosoft_code'),
        ('journals', 'company_id=? AND date<=?', (cid, end), 'date period document history created_at created_by'),
        ('audit', "company_id=? AND entity='journal'", (cid,), 'entity_id action created_at'),
        ('module_imports', "company_id=? AND module='accounting' AND result_json IS NOT NULL", (cid,),
         'layout fingerprint result_json'),
    ]
    total = 0
    for table, where, args, columns in sources:
        # BLOB length counts encoded bytes, including embedded NUL; LENGTH(text)
        # would stop at NUL. Application SQLite databases use UTF-8 encoding.
        lengths = '+'.join(f"LENGTH(CAST(COALESCE({column},'') AS BLOB))" for column in columns.split())
        total += conn.execute(f'SELECT COALESCE(SUM({lengths}),0) AS size FROM {table} WHERE {where}', args).fetchone()['size']
        if total > MAX_SOURCE_TEXT_BYTES:
            raise DomainError('Volume textual das evidências excede o limite preparatório.',
                              413, 'preparation_volume_limit')
    return total


def _project(source):
    prior = source['opening_history']['journals']
    selected = source['journals']
    rolling = defaultdict(int)
    prior_ids = defaultdict(list)
    key_of = lambda line: (line['account_id'], line.get('participant_id'), line['cost_center_id'])
    order = lambda key: tuple((value is not None, value or 0) for value in key)
    identity = lambda key: dict(zip(('account_id', 'participant_id', 'cost_center_id'), key))
    for journal in prior:
        for line in journal['lines']:
            key = key_of(line)
            rolling[key] += int(line['debit']['cents']) - int(line['credit']['cents'])
            prior_ids[key].append(line['id'])
    history = [identity(key) | {'observed_net': amount(rolling[key]), 'line_ids': prior_ids[key]}
               for key in sorted(rolling, key=order)]
    monthly = []
    projected_rows = 0
    for first, last in months(source['scope']['start'], source['scope']['end']):
        entries = [j for j in selected if j['date'][:7] == first[:7]]
        keys = rolling.keys() | {key_of(line) for journal in entries for line in journal['lines']}
        # Charge the entire month before allocating its movements or balance rows.
        # Carried groups count again, including months without recorded journals.
        if projected_rows + len(keys) > MAX_PROJECTED_BALANCE_ROWS:
            raise DomainError('Quantidade de saldos mensais projetados excede o limite preparatório.',
                              413, 'preparation_volume_limit')
        projected_rows += len(keys)
        movements = defaultdict(lambda: [0, 0, []])
        for journal in entries:
            for line in journal['lines']:
                totals = movements[key_of(line)]
                totals[0] += int(line['debit']['cents'])
                totals[1] += int(line['credit']['cents'])
                totals[2].append(line['id'])
        rows = []
        for key in sorted(keys, key=order):
            debits, credits, ids = movements.get(key, (0, 0, []))
            before = rolling[key]
            rolling[key] += debits - credits
            rows.append(identity(key) | {'observed_net_before': amount(before),
                'observed_debits': amount(debits), 'observed_credits': amount(credits),
                'observed_net_after': amount(rolling[key]), 'movement_line_ids': ids,
                'official_opening_balance': None})
        monthly.append({'start': first, 'end': last, 'journal_ids': [j['id'] for j in entries],
            'evidence': 'recorded_journals' if entries else 'no_recorded_journals',
            'completeness': 'unknown', 'balances': rows})
    # Retain origin and reversal links; do not resolve private party catalog data,
    # copy history text, or present ECD candidates as Prosoft mappings.
    evidence = []
    for journal in prior + selected:
        evidence.append({k: journal[k] for k in ('id', 'date', 'period', 'reversal_of',
            'reversed_by', 'source_references', 'audit_events', 'source_record_sha256')} | {
            'scope': 'prior_history' if journal['date'] < source['scope']['start'] else 'selected',
            'lines': [{k: line[k] for k in ('id', 'account_id', 'participant_id',
                      'cost_center_id', 'debit', 'credit')} for line in journal['lines']]})
    return {'schema_version': 1, 'artifact_type': 'prosoft_observed_balances',
        'scope': source['scope'], 'basis': 'stored_accounting_lines_only_debit_minus_credit',
        'sld_generation': 'blocked', 'official_opening_balances': None,
        'destination_mappings': None, 'historical_integrity': 'unknown',
        'opening_attestation': 'unknown', 'safe_reapplication': 'unknown',
        'prior_history_balances': history, 'monthly_balances': monthly,
        'journal_evidence': evidence,
        'source_snapshot_sha256': digest(source),
        'source_anomalies': [w for w in source['warnings'] if w['code'] in {
            'MISSING_ACCOUNT_OR_CENTER', 'JOURNAL_TOTAL_MISMATCH', 'JOURNAL_PERIOD_MISMATCH'}],
        'limitations': ['Preparação somente; SLD é formato Prosoft, não SPED.',
            'Acumulados observados não atestam abertura oficial nem integridade histórica.',
            'Meses sem partidas não comprovam inatividade ou completude.',
            'Aberturas explícitas permanecem partidas; estornos não eliminam as originais.',
            'IDs locais não comprovam códigos ou mapeamentos no destino.']}


def observed_balances(core, cid, start, end):
    start, end = bounds(start, end)
    with core.db.read(snapshot=True) as conn:
        _authorize(conn, cid, start)
        _limit_sources(conn, cid, end)
        result = _project(_snapshot(conn, cid, start, end, include_balances=False))
    response = pack({'snapshot': result, 'snapshot_sha256': digest(result)}) + '\n'
    if len(response.encode('utf-8')) > MAX_RESPONSE_BYTES:
        raise DomainError('Resposta excede o limite preparatório.', 413, 'preparation_volume_limit')
    return response


def register_prosoft_balance_routes(app, core, check_period):
    @app.get('/api/companies/{cid}/prosoft/observed-balances')
    def query(cid: int, request: Request, start: str, end: str):
        start, end = bounds(start, end)
        check_period(request, start[:7])
        for header, expected in [('x-company-id', str(cid)), ('x-year', start[:4]), ('x-module', 'accounting')]:
            if request.headers.get(header) and request.headers[header] != expected:
                raise DomainError('Contexto da consulta mudou.', 409, 'stale_context')
        return Response(observed_balances(core, cid, start, end), media_type='application/json',
                        headers={'Cache-Control': 'no-store'})
