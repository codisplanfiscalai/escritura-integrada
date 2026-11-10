"""PDFs fiscais auxiliares, sem homologação visual Prosoft.

Referências de campos: inventário LFSLIVROS/LFSLIVROSAPUR em
``docs/referencias/formularios-identificados.csv`` e livros históricos P1/A,
P2/A e P9 fornecidos pelo usuário. Eles não comprovam fabricante ou paridade.
Este módulo apresenta exclusivamente o resultado já apurado pelo serviço.
"""
from decimal import Decimal
from html import escape
from io import BytesIO

from .core import DomainError
from .fiscal_reports import FISCAL_REPORTS, TAXES

FISCAL_MODEL_IDS = {kind: 'internal-' + kind for kind in FISCAL_REPORTS}
FISCAL_MODEL_STATUS = 'reference_not_homologated'

LABELS = {
    'document_id': 'ID doc.', 'document_ids': 'IDs documentos',
    'date': 'Data escrit.', 'issue_date': 'Emissão', 'document': 'Documento', 'model': 'Modelo',
    'series': 'Série', 'partner_name': 'Participante', 'partner_tax_id': 'CPF/CNPJ',
    'direction': 'Mov.', 'cfop': 'CFOP', 'ncm': 'NCM', 'status': 'Situação',
    'total_cents': 'Valor documental (R$)', 'item': 'Item', 'description': 'Descrição',
    'quantity': 'Qtd.', 'unit': 'Un.', 'item_total_cents': 'Valor dos itens (R$)',
    'items': 'Itens', 'items_without_value': 'Itens sem valor informado',
    'documents': 'Documentos', 'code': 'Código', 'message': 'Pendência para revisão',
    'ledger_id': 'ID livro', 'period': 'Competência', 'tax': 'Tributo',
    'assessment_id': 'ID memória', 'opening_credit_cents': 'Crédito anterior (R$)',
    'debit_cents': 'Débitos (R$)', 'credit_cents': 'Créditos (R$)',
    'payable_cents': 'A recolher (R$)', 'carry_credit_cents': 'Crédito a transportar (R$)',
    'responsible': 'Responsável', 'reason': 'Justificativa',
    'finalized_assessments': 'Apurações finalizadas', 'occurrences': 'Ocorrências',
}
VALUES = {'incoming': 'Entrada', 'outgoing': 'Saída', 'booked': 'Escriturado',
          'draft': 'Rascunho', 'pending': 'Pendente', 'cancelled': 'Cancelado',
          'canceled': 'Cancelado', 'reversed': 'Estornado'}
# Separate document identity from item and tax detail: readable columns at A4.
DOCUMENT_COLUMNS = [('document_id', 45), ('date', 62), ('issue_date', 62), ('document', 65),
                    ('model', 40), ('series', 34), ('partner_name', 157),
                    ('partner_tax_id', 90), ('direction', 53), ('cfop', 39),
                    ('status', 65), ('total_cents', 96)]
ITEM_COLUMNS = [('document_id', 43), ('date', 58), ('document', 55), ('item', 27),
                ('description', 143), ('partner_name', 100), ('cfop', 35), ('ncm', 48),
                ('quantity', 51), ('unit', 33), ('item_total_cents', 73),
                ('direction', 48), ('status', 64)]


def _display(key, value):
    if value is None or value == '':
        return 'Não informado'
    if key.endswith('_cents'):
        return f'{Decimal(value) / 100:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    if isinstance(value, (list, tuple)):
        return ', '.join(str(v) for v in value) or 'Não informado'
    if key in {'date', 'issue_date'} and len(str(value)) == 10:
        return '/'.join(str(value).split('-')[::-1])
    if key in {'direction', 'status'}:
        return VALUES.get(str(value), str(value))
    return str(value)


def fiscal_pdf(result, first_page=1, show_numbers=False):
    """Render all ten fiscal results as (PDF bytes, MIME type).

    ``show_numbers`` adds a presentation sequence, never suppressing source IDs.
    Absent source amounts are explicit; no taxable incidence is calculated here.
    """
    if isinstance(first_page, bool) or not isinstance(first_page, int) or not 1 <= first_page <= 99999:
        raise DomainError('Folha inicial deve estar entre 1 e 99999.')
    kind = result.get('kind')
    if kind not in FISCAL_REPORTS:
        raise DomainError('Modelo fiscal não encontrado.', 404)
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle

    out = BytesIO()
    page_size = landscape(A4)
    width, height = page_size
    margin = 30
    usable = width - 2 * margin - 12
    styles = {
        'cell': ParagraphStyle('fiscal-cell', fontName='Helvetica', fontSize=8, leading=10,
                               splitLongWords=True, spaceAfter=0),
        'head': ParagraphStyle('fiscal-head', fontName='Helvetica-Bold', fontSize=8, leading=10),
        'text': ParagraphStyle('fiscal-text', fontName='Helvetica', fontSize=9, leading=12,
                               spaceAfter=6, splitLongWords=True),
        'section': ParagraphStyle('fiscal-section', fontName='Helvetica-Bold', fontSize=11,
                                  leading=14, spaceBefore=10, spaceAfter=6, keepWithNext=True),
    }
    def p(value, style='cell'):
        return Paragraph(escape(str(value)).replace('\n', '<br/>'), styles[style])

    title = FISCAL_REPORTS[kind]
    company_header = p('Empresa: ' + str(result.get('company_name') or 'Não informada'), 'text')
    _, company_height = company_header.wrap(usable, height)
    def header(canvas, doc):
        if first_page + doc.page - 1 > 99999:
            raise DomainError('Numeração das folhas excede o limite de 99999.')
        canvas.saveState()
        canvas.setFont('Helvetica-Bold', 12)
        canvas.drawString(margin, height - 27, title)
        canvas.setFont('Helvetica', 8)
        canvas.drawString(margin, height - 41, 'Período: ' + _display('date', result.get('start')) +
                          ' a ' + _display('date', result.get('end')))
        canvas.drawRightString(width - margin, height - 41, f'Folha: {first_page + doc.page - 1:05d}')
        canvas.setLineWidth(.5)
        canvas.line(margin, height - 48, width - margin, height - 48)
        company_header.drawOn(canvas, margin, height - 54 - company_height)
        canvas.setFont('Helvetica', 7)
        canvas.drawString(margin, 18, 'Escritura Integrada | Relatório auxiliar | Layout de referência não homologado Prosoft')
        canvas.drawRightString(width - margin, 18, FISCAL_MODEL_IDS[kind])
        canvas.restoreState()

    doc = SimpleDocTemplate(out, pagesize=page_size, leftMargin=margin, rightMargin=margin,
                            topMargin=64 + company_height, bottomMargin=34, title=title, author='Escritura Integrada')
    story = [p('ID empresa: ' + str(result.get('company_id', 'Não informado')), 'text')]
    for key, label in [('company_code', 'Código'), ('company_tax_id', 'CNPJ')]:
        if result.get(key):
            story.append(p(label + ': ' + str(result[key]), 'text'))
    filters = result.get('filters') or {}
    if kind == 'fiscal-assessments':
        story.append(p('Seleção efetiva: memórias finalizadas e não estornadas; competências de ' +
                       str(result.get('start', ''))[:7] + ' a ' + str(result.get('end', ''))[:7] +
                       '. Busca, situação documental, movimento, CFOP e NCM não se aplicam a este livro.', 'text'))
    else:
        labels = {'query': 'Busca', 'status': 'Situação', 'direction': 'Movimento', 'cfop': 'CFOP', 'ncm': 'NCM'}
        selection = '; '.join(label + ': ' + (_display(key, filters[key]) if filters.get(key) else 'Todos')
                              for key, label in labels.items())
        story.append(p('Filtros efetivos: ' + selection, 'text'))
    story.append(p(result.get('scope_note') or 'Relatório auxiliar de valores declarados; não substitui obrigação legal.', 'text'))
    story.append(p('Campos ausentes: Não informado. Totais monetários abrangem apenas valores conhecidos; '
                   'não representam necessariamente o total integral da operação. Não há validação da incidência ou do crédito tributário.', 'text'))

    rows = result.get('rows') or []
    def section(name, columns, data, numbered=False):
        story.append(p(name, 'section'))
        if not data:
            story.append(p('Sem registros para a seleção efetiva.', 'text'))
            return
        cols = list(columns)
        if numbered and show_numbers:
            cols.insert(0, ('sequence', 30))
        header_row = [p(LABELS.get(key, key), 'head') for key, _ in cols]
        if numbered and show_numbers:
            header_row[0] = p('Seq.', 'head')
        body = [header_row]
        for index, row in enumerate(data, 1):
            body.append([p(_display(key, index if key == 'sequence' else row.get(key))) for key, _ in cols])
        table = LongTable(body, colWidths=[size * usable / sum(v for _, v in cols) for _, size in cols],
                          repeatRows=1, splitByRow=1, splitInRow=1, hAlign='LEFT')
        table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e9edf2')),
            ('LINEBELOW', (0, 0), (-1, 0), .6, colors.HexColor('#475569')),
            ('LINEBELOW', (0, 1), (-1, -1), .25, colors.HexColor('#d1d5db')),
            ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        story.extend([table, Spacer(1, 6)])

    if kind in {'fiscal-documents', 'fiscal-entries', 'fiscal-outputs', 'fiscal-taxes'}:
        heading = {'fiscal-documents': 'Registro de documentos', 'fiscal-entries': 'Entradas escrituradas',
                   'fiscal-outputs': 'Saídas escrituradas', 'fiscal-taxes': 'Documentos de origem'}[kind]
        section(heading, DOCUMENT_COLUMNS, rows, True)
        if kind in {'fiscal-taxes', 'fiscal-entries', 'fiscal-outputs'}:
            taxes = TAXES if kind == 'fiscal-taxes' else ('icms', 'ipi')
            tax_rows = []
            for row in rows:
                for tax in taxes:
                    tax_rows.append({key: row.get(key) for key in ('document_id', 'date', 'document')} |
                                    {'tax': tax.upper(), 'base_cents': row.get(tax + '_base_cents'),
                                     'tax_cents': row.get(tax + '_cents')})
            tax_columns = [('document_id', 65), ('date', 80), ('document', 110), ('tax', 75),
                           ('base_cents', 170), ('tax_cents', 170)]
            section('Bases e valores declarados por documento e tributo', tax_columns, tax_rows)
            coverage = []
            for tax in taxes:
                bases = [r[tax + '_base_cents'] for r in rows if r.get(tax + '_base_cents') is not None]
                amounts = [r[tax + '_cents'] for r in rows if r.get(tax + '_cents') is not None]
                coverage.append({'tax': tax.upper(), 'base_cents': sum(bases) if bases else None,
                                 'tax_cents': sum(amounts) if amounts else None,
                                 'base_coverage': f'{len(bases)} / {len(rows)}',
                                 'tax_coverage': f'{len(amounts)} / {len(rows)}'})
            section('Totais conhecidos e cobertura por tributo', [('tax', 70), ('base_cents', 140),
                    ('tax_cents', 140), ('base_coverage', 140), ('tax_coverage', 140)], coverage)
    elif kind == 'fiscal-items':
        section('Detalhamento dos itens escriturados', ITEM_COLUMNS, rows, True)
    elif kind in {'fiscal-operations', 'fiscal-classifications'}:
        columns = [('direction', 65), ('cfop', 50)]
        if kind == 'fiscal-classifications':
            columns.append(('ncm', 65))
        columns += [('items', 45), ('item_total_cents', 110), ('items_without_value', 110), ('document_ids', 250)]
        # A group with no known item values must not display the service's empty sum as zero.
        data = [dict(row, item_total_cents=None) if row.get('items') == row.get('items_without_value')
                else row for row in rows]
        section('Resumo por NCM e CFOP' if kind == 'fiscal-classifications' else 'Resumo por CFOP', columns, data, True)
    elif kind == 'fiscal-participants':
        section('Movimentação por participante', [('partner_tax_id', 100), ('partner_name', 220),
                ('direction', 65), ('documents', 65), ('total_cents', 105), ('document_ids', 170)], rows, True)
    elif kind == 'fiscal-inconsistencies':
        section('Ocorrências para conferência', [('document_id', 50), ('date', 65), ('document', 65),
                ('partner_name', 140), ('status', 65), ('code', 130), ('message', 270)], rows, True)
    else:
        section('Saldos das memórias finalizadas', [('ledger_id', 50), ('period', 65), ('tax', 50),
                ('assessment_id', 55), ('opening_credit_cents', 110), ('debit_cents', 100),
                ('credit_cents', 100), ('payable_cents', 100), ('carry_credit_cents', 110)], rows, True)
        section('Rastreabilidade das memórias', [('ledger_id', 60), ('assessment_id', 80),
                ('period', 70), ('tax', 55), ('responsible', 180), ('reason', 300)], rows)
        story.append(p('Saldos de tributos diferentes não são somados nem compensados.', 'text'))

    totals = dict(result.get('totals') or {})
    if kind in {'fiscal-taxes', 'fiscal-entries', 'fiscal-outputs'}:
        totals = {key: value for key, value in totals.items()
                  if not any(key.startswith(tax + '_') for tax in TAXES)}
    if 'item_total_cents' in totals and totals.get('items') == totals.get('items_without_value'):
        totals['item_total_cents'] = None
    section('Totalizadores da seleção', [('metric', 350), ('value', 350)],
            [{'metric': LABELS.get(key, key), 'value': _display(key, value)} for key, value in totals.items()])
    doc.build(story, onFirstPage=header, onLaterPages=header)
    return out.getvalue(), 'application/pdf'


LABELS.update({'base_cents': 'Base declarada (R$)', 'tax_cents': 'Tributo declarado (R$)',
               'base_coverage': 'Documentos com base / selecionados',
               'tax_coverage': 'Documentos com valor / selecionados',
               'metric': 'Indicador', 'value': 'Valor informado'})
