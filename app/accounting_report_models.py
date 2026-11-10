"""Impressões contábeis baseadas nos campos recuperados, sem paridade visual certificada.

Fontes: docs/referencias/formularios-identificados.csv (CTB020600, CTB020800,
CTB021400, CTB030200, CTB020700/021500/021700). Os formulários comprovam
campos/variantes, não a geometria da saída impressa. Nenhuma assinatura ou
qualificação profissional é inventada por estes modelos.
"""
from collections import OrderedDict
from decimal import Decimal
from io import BytesIO
import json
from xml.sax.saxutils import escape

from .core import DomainError
from .report_exports import LABELS, REPORT_TITLES, display

NOTICE = 'Baseada nos campos, layout não homologado. Não certifica identidade visual Prosoft.'
GROUPS = {'asset': 'Ativo', 'liability': 'Passivo', 'equity': 'Patrimônio líquido',
          'revenue': 'Receitas', 'expense': 'Despesas'}
LABELS = dict(LABELS, number='Lcto.', journal_ids='Lançamentos de origem',
              account_id='ID da conta', nature='Natureza', report_group='Grupo contábil',
              cost_center_id='ID do centro', cost_center_code='Código do centro',
              assets_cents='Ativo', liabilities_cents='Passivo', equity_cents='Patrimônio líquido',
              unclosed_result_cents='Resultado não encerrado', difference_cents='Diferença',
              account_id_filter='Filtro de conta', cost_center_id_filter='Filtro de centro')
# Frações de largura, em vez de colunas genéricas igualmente espaçadas.
COLUMNS = {
 'diary': [('date', .10), ('number', .06), ('document', .09), ('classifier', .11),
           ('account_name', .16), ('history', .20), ('debit_cents', .09), ('credit_cents', .09), ('cost_center_name', .10)],
 'consolidated-diary': [('date', .10), ('access_code', .08), ('account_name', .28),
                        ('cost_center_name', .20), ('debit_cents', .12), ('credit_cents', .12), ('journal_ids', .10)],
 'trial-balance': [('access_code', .06), ('classifier', .13), ('account_name', .27),
                   ('opening_cents', .14), ('debit_cents', .13), ('credit_cents', .13), ('closing_cents', .14)],
 'balance-sheet': [('classifier', .16), ('account_name', .32), ('opening_cents', .13),
                   ('debit_cents', .13), ('credit_cents', .13), ('closing_cents', .13)],
 'income-statement': [('classifier', .14), ('account_name', .41), ('debit_cents', .15),
                      ('credit_cents', .15), ('result_cents', .15)],
 'cost-centers': [('access_code', .10), ('account_name', .42), ('debit_cents', .16),
                  ('credit_cents', .16), ('balance_cents', .16)],
}


def validate_first_page(first_page):
    if isinstance(first_page, bool) or not isinstance(first_page, int) or not 1 <= first_page <= 99999:
        raise DomainError('Folha inicial deve ser um inteiro entre 1 e 99999.')


def accounting_pdf(result, first_page=1, show_numbers=False):
    """Renderiza os valores do resultado, sem recalcular ou remover filtros/linhas.

    Campos fora da grade principal ficam no anexo numerado por registro original.
    show_numbers é aceito por compatibilidade; lançamentos são sempre identificados.
    """
    validate_first_page(first_page)
    kind = result['kind']
    if kind not in COLUMNS:
        raise DomainError('Modelo contábil indisponível para este relatório.')
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle, PageBreak

    # Embed the bundled Unicode font: PDF viewers need not substitute base fonts.
    from pathlib import Path
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    fonts = Path(reportlab.__file__).parent / 'fonts'
    if 'AccountingSans' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('AccountingSans', str(fonts / 'Vera.ttf')))
        pdfmetrics.registerFont(TTFont('AccountingSans-Bold', str(fonts / 'VeraBd.ttf')))
    title = REPORT_TITLES[kind]
    out = BytesIO()
    pagesize = landscape(A4)
    width = pagesize[0] - 64
    doc = SimpleDocTemplate(out, pagesize=pagesize, leftMargin=32, rightMargin=32,
                           topMargin=72, bottomMargin=42, title=title, author='Escritura Integrada')
    normal = ParagraphStyle('accounting', fontName='AccountingSans', fontSize=8, leading=11, splitLongWords=True)
    heading = ParagraphStyle('section', parent=normal, fontName='AccountingSans-Bold', fontSize=10,
                             leading=14, spaceBefore=10, spaceAfter=6, keepWithNext=True)
    numeric = ParagraphStyle('amount', parent=normal, alignment=2)
    def p(value, style=normal):
        return Paragraph(escape(str(value if value is not None else '')).replace('\n', '<br/>'), style)
    def val(key, value):
        if value is None:
            return ''
        if key.endswith('_cents'):
            amount = Decimal(value) / 100
            text = f'{abs(amount):,.2f}'.replace(',', '@').replace('.', ',').replace('@', '.')
            if key in {'opening_cents', 'closing_cents', 'balance_cents'}:
                return text + (' C' if amount < 0 else ' D')
            return ('-' if amount < 0 else '') + text
        if key == 'report_group':
            return GROUPS.get(value, value)
        if key == 'date':
            return '/'.join(str(value).split('-')[::-1])
        return display(key, value)
    def table(data, widths, header=True):
        t = LongTable(data, colWidths=widths, repeatRows=1 if header else 0,
                      hAlign='LEFT', splitByRow=1, splitInRow=1)
        commands = [('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LINEBELOW', (0, 0), (-1, 0), .6, colors.black),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 5), ('TOPPADDING', (0, 0), (-1, -1), 5),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f4f4f4')])]
        if header:
            commands.append(('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8e8e8')))
        t.setStyle(TableStyle(commands))
        return t

    filters = dict(result.get('filters') or {})
    for key in ('account_id', 'cost_center_id'):
        if result.get(key) is not None:
            filters.setdefault(key, result[key])
    story = [p(result.get('company_name', ''), heading),
             p('Empresa: ' + str(result.get('company_code', '')) + ' | CNPJ: ' + str(result.get('company_tax_id', ''))),
             p('Período: ' + val('date', result['start']) + ' a ' + val('date', result['end'])),
             p(NOTICE), p(result.get('scope_note', '')),
             p('Filtros: ' + (json.dumps(filters, ensure_ascii=False, sort_keys=True) if filters else 'Sem filtros adicionais.')),
             p('Valores em reais. Saldos: D = devedor; C = credor. Resultado positivo = lucro; negativo = prejuízo.'), Spacer(1, 8)]
    rows = result.get('rows', [])
    sections = OrderedDict()
    for index, row in enumerate(rows, 1):
        if kind in {'balance-sheet', 'income-statement'}:
            key = row.get('report_group') or 'Sem classificação'
            name = GROUPS.get(key, key)
        elif kind == 'cost-centers':
            # Homônimos não devem fundir centros distintos.
            key = (row.get('cost_center_id'), row.get('cost_center_code'), row.get('cost_center_name'))
            name = 'Centro de custo: ' + str(row.get('cost_center_name') or 'Sem centro')
            if row.get('cost_center_id') is not None:
                name += ' | ID ' + str(row['cost_center_id'])
        else:
            key, name = '', ''
        sections.setdefault(key, (name, []))[1].append((index, row))
    columns = COLUMNS[kind]
    keys = [key for key, _ in columns]
    # Registro original estável permite conferir anexo mesmo com agrupamento.
    widths = [width * .04] + [width * .96 * weight / sum(w for _, w in columns) for _, weight in columns]
    for name, records in sections.values():
        if name:
            story.append(p(name, heading))
        data = [[p('Reg.')] + [p(LABELS.get(key, key)) for key in keys]]
        for index, row in records:
            data.append([p(index)] + [p(val(key, row.get(key)), numeric if key.endswith('_cents') else normal) for key in keys])
        story.append(table(data, widths))
    if not rows:
        story.append(p('Nenhum registro nos filtros selecionados.'))
    story.append(p('Totais do escopo consultado', heading))
    totals = result.get('totals', {})
    if totals:
        story.append(table([[p('Descrição'), p('Valor')]] + [[p(LABELS.get(key, key)), p(val(key, value), numeric)]
                           for key, value in totals.items()], [width * .72, width * .28]))
    else:
        story.append(p('Sem totalizadores fornecidos.'))

    extras = [(index, [(key, value) for key, value in row.items() if key not in keys]) for index, row in enumerate(rows, 1)]
    extras = [(index, values) for index, values in extras if values]
    if extras:
        story += [PageBreak(), p('Anexo de conferência - campos complementares', heading),
                  p('Reg. corresponde ao registro da grade principal; nenhum campo do resultado foi omitido.')]
        data = [[p('Reg.'), p('Campo'), p('Valor')]]
        for index, fields in extras:
            for key, value in fields:
                data.append([p(index), p(LABELS.get(key, key)), p(val(key, value))])
        story.append(table(data, [width * .06, width * .25, width * .69]))

    def header_footer(canvas, document):
        page = first_page + document.page - 1
        if page > 99999:
            raise DomainError('Paginação excede a folha 99999. Reduza a folha inicial ou o escopo.')
        canvas.saveState()
        canvas.setFont('AccountingSans-Bold', 12)
        canvas.drawString(32, pagesize[1] - 32, title.upper())
        canvas.setFont('AccountingSans', 8)
        canvas.drawRightString(pagesize[0] - 32, pagesize[1] - 32, f'Folha: {page:05d}')
        canvas.drawString(32, pagesize[1] - 49, 'Continuação' if document.page > 1 else 'Escritura Integrada - impressão contábil')
        canvas.line(32, pagesize[1] - 57, pagesize[0] - 32, pagesize[1] - 57)
        canvas.setFont('AccountingSans', 7)
        canvas.drawString(32, 24, 'Baseada nos campos, layout não homologado | ' + val('date', result['start']) + ' a ' + val('date', result['end']))
        canvas.drawRightString(pagesize[0] - 32, 24, f'Página {document.page}')
        canvas.restoreState()
    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    return out.getvalue(), 'application/pdf'
