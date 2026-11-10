"""Excel export of the complete, server-filtered movement search."""
import calendar
import json
import re
import unicodedata
from fastapi import Request
from fastapi.responses import Response
from .core import DomainError, company_row
from .permissions import require
from .report_exports import export_report


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFD', str(value or ''))
                   if not unicodedata.combining(c)).lower()


def search_text(row, kind):
    if kind == 'documents':
        return ' '.join('null' if row.get(k) is None else str(row[k])
                        for k in ('number', 'partner_name', 'key', 'cfop'))
    return json.dumps(row, ensure_ascii=False, separators=(',', ':'))


def register_movement_export_routes(app, core):
    @app.get('/api/companies/{cid}/movement-exports/{kind}.xlsx')
    def movement_export(cid: int, kind: str, request: Request, year: int,
                        month: str = '', query: str = '', direction: str = '', status: str = ''):
        if kind not in ('documents', 'journals'):
            raise DomainError('Tipo de movimento inválido.')
        if not 1900 <= year <= 2199 or (month and not re.fullmatch(r'0[1-9]|1[0-2]', month)):
            raise DomainError('Exercício ou mês inválido.')
        if direction not in ('', 'incoming', 'outgoing') or status not in ('', 'pending', 'reviewed', 'booked', 'cancelled'):
            raise DomainError('Filtro inválido.')
        if kind == 'journals' and (direction or status):
            raise DomainError('Filtro não aplicável a lançamentos contábeis.')
        if len(query) > 4000:
            raise DomainError('Pesquisa excede 4000 caracteres.')
        module = 'fiscal' if kind == 'documents' else 'accounting'
        routine = f'{module}.{kind}'
        session = request.state.session
        if session['active_company_id'] != cid or session.get('module', 'fiscal') != module or session['period'][:4] != str(year):
            raise DomainError('O contexto mudou. Ative a empresa, módulo e exercício da consulta.', 409, 'stale_context')
        with core.db.read() as conn:
            require(conn, session['user']['id'], cid, routine, 'read')
            require(conn, session['user']['id'], cid, routine, 'export')
            company = dict(company_row(conn, cid))
        records = core.documents(cid, year=year) if kind == 'documents' else core.journals(cid)
        records = [r for r in records if r['period'][:4] == str(year)
                   and (not month or r['period'][5:] == month)
                   and (not direction or r['direction'] == direction)
                   and (not status or r['status'] == status or status == 'cancelled' and r.get('book_cancellation'))
                   and normalized(query) in normalized(search_text(r, kind))]
        if len(records) > 1_048_575:
            raise DomainError('A pesquisa excede a capacidade de uma planilha Excel. Refine os filtros para exportar sem truncamento.')
        keys = (('id', 'period', 'direction', 'number', 'model', 'series', 'issue_date', 'posting_date', 'partner_name', 'partner_tax_id', 'key', 'cfop', 'total_cents', 'status', 'document_state', 'book_cancellation')
                if kind == 'documents' else ('id', 'period', 'number', 'date', 'document', 'history', 'total_cents', 'status'))
        data = [{k: r.get(k) for k in keys} for r in records]
        result = {'kind': kind, 'title': 'Documentos fiscais pesquisados' if kind == 'documents' else 'Lançamentos contábeis pesquisados',
                  'company_name': company['name'], 'start': f'{year}-{month or "01"}-01', 'end': f'{year}-{month or "12"}-{calendar.monthrange(year, int(month or 12))[1]}',
                  'scope_note': 'Resultado completo da pesquisa, sem limitação à página ou seleção. Valores em reais e centavos em abas separadas.',
                  'filters': {'year': year, 'month': month, 'query': query, 'direction': direction, 'status': status},
                  'totals': {'Registros': len(data), 'total_cents': sum(r.get('total_cents') or 0 for r in data)}, 'rows': data}
        content, media_type = export_report(result, 'xlsx')
        return Response(content, media_type=media_type, headers={'Content-Disposition': f'attachment; filename="{kind}-{cid}-{year}.xlsx"'})
