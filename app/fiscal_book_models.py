"""Quadros de livros fiscais baseados nos exemplares P1/A e P2/A fornecidos.

Somente apresentação: não calcula incidência, não modifica partições e não
preenche códigos contábeis, isenções ou cadastros ausentes. O quadro principal
é de ICMS; os anexos auxiliares continuam disponíveis separadamente.
"""
from collections import OrderedDict
from decimal import Decimal
from io import BytesIO
import re

from .core import DomainError

BOOK_MODELS = {'reference-entries-p1a-v1': 'fiscal-entries',
               'reference-outputs-p2a-v1': 'fiscal-outputs'}
WIDTH, HEIGHT = 842, 595


def _money(value):
    if value is None:
        return ''
    return f'{Decimal(value) / 100:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def _date(value):
    parts = str(value or '').split('-')
    return '/'.join(reversed(parts)) if len(parts) == 3 else str(value or '')


def _tax_id(value):
    value = str(value or '')
    return re.sub(r'^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$', r'\1.\2.\3/\4-\5', value)


def _book_values(row):
    """Only reviewed book amounts, never the XML tax as an implicit credit."""
    treatment = row.get('treatment')
    mode = treatment.get('book_mode') if isinstance(treatment, dict) else None
    cancelled = row.get('document_state') == 'cancelled'
    code = '3' if mode == 'other_excluding_ipi' else '1' if mode == 'declared_icms' else ''
    operation = row.get('book_other_cents') if code == '3' else row.get('book_base_cents') if code == '1' else None
    rate = '0,0000' if code == '3' else ''
    if code == '1' and row.get('rate') is not None:
        rate = format(Decimal(str(row['rate'])), '.4f').replace('.', ',')
    return {'value': row.get('total_cents'), 'base': row.get('book_base_cents'),
            'tax': row.get('book_icms_cents'), 'other': row.get('book_other_cents'),
            'exempt': None, 'code': code, 'operation': operation,
            'rate': '' if cancelled else rate}


def fiscal_book_pdf(result, model_id, first_page=1):
    from .accounting_report_models import validate_first_page
    validate_first_page(first_page)
    if BOOK_MODELS.get(model_id) != result.get('kind'):
        raise DomainError('Modelo de livro incompatível com o relatório.')
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase.pdfmetrics import stringWidth
    incoming = result['kind'] == 'fiscal-entries'
    left, right = (54, 804) if incoming else (72, 796)
    edges = ([54, 97, 121, 140, 175, 209, 358, 402, 436, 471, 494, 503, 552, 574, 620, 804]
             if incoming else [72, 99, 130, 205, 218, 231, 275, 300, 318, 400, 426, 471, 514, 555, 796])
    out = BytesIO(); c = canvas.Canvas(out, pagesize=(WIDTH, HEIGHT))
    c.setTitle('Registro de entradas P1/A' if incoming else 'Registro de saídas P2/A')
    c.setAuthor('Escritura Integrada')
    page = first_page
    def text(x, top, value, size=6, bold=False, align='left'):
        value = str(value if value is not None else '')
        c.setFont('Times-Bold' if bold else 'Times-Roman', size)
        fn = c.drawRightString if align == 'right' else c.drawCentredString if align == 'center' else c.drawString
        fn(x, HEIGHT-top-size*.8, value)
    def line(x0, top, x1, bottom=None):
        c.setLineWidth(.35);c.line(x0, HEIGHT-top, x1, HEIGHT-(top if bottom is None else bottom))
    def wrapped(value, width, size=6):
        # Split overlong words as well; preserve all visible source text.
        lines = []; current = ''
        for word in str(value or '').split():
            parts = [''];
            for char in word:
                if stringWidth(parts[-1]+char, 'Times-Roman', size) > width and parts[-1]:parts.append('')
                parts[-1] += char
            for part in parts:
                trial = (current+' '+part).strip()
                if current and stringWidth(trial, 'Times-Roman', size) > width:
                    lines.append(current); current = part
                else:current = trial
        if current:lines.append(current)
        return lines or ['']
    def cell(a,b,top,value,size=6,bold=False,align='center'):
        x = a+2 if align == 'left' else b-2 if align == 'right' else (a+b)/2
        if align == 'right' and re.fullmatch(r'-?[\d.,]+', str(value or '')):
            font='Times-Bold' if bold else 'Times-Roman'
            while size>4 and stringWidth(str(value),font,size)>b-a-4:size=round(size-.25,2)
            if stringWidth(str(value),font,size)>b-a-4:raise DomainError('Valor excede a coluna do livro; consulte o modelo auxiliar sem truncamento.')
            text(x,top,value,size,bold,align)
            return
        for n,part in enumerate(wrapped(value,b-a-4,size)):
            text(x,top+n*7.2,part,size,bold,align)
    filters = result.get('filters', {})
    def header(summary=False):
        if page > 99999:raise DomainError('Numeração das folhas excede o limite de 99999.')
        label = 'REGISTRO DE ENTRADAS' if incoming else 'REGISTRO DE SAÍDAS'
        line(left,37,right)
        text(right,27,'MODELO P1/A' if incoming else 'MODELO P2/A',7,align='right')
        title=' '.join(label)
        title_left,title_width,title_rule = (247.08,296.88,55.2) if incoming else (270.96,264.72,56.52)
        c.saveState()
        t=c.beginText(title_left,HEIGHT-44-12*.8);t.setFont('Times-Bold',12)
        t.setCharSpace((title_width-stringWidth(title,'Times-Bold',12))/(len(title)-1))
        t.textOut(title);c.drawText(t);c.restoreState()
        line(title_left,title_rule,title_left+title_width)
        text(right-60,46,'Folha:',6);text(right-4,45,f'{page:06d}',7,align='right')
        text(left+13,72,'Contribuinte:',8)
        name = f"{result.get('company_code') or ''} - {result.get('company_name') or ''}"
        name_size=8
        while name_size>6 and len(wrapped(name,365,name_size))>2:name_size-=1
        name_lines=wrapped(name,365,name_size)
        if len(name_lines)>2:raise DomainError('Nome da empresa excede o cabeçalho do livro; consulte o modelo auxiliar sem truncamento.')
        for i,part in enumerate(name_lines):text(left+61,69+i*8,part,name_size,True)
        text(502 if incoming else 495,72,'CNPJ: '+_tax_id(result.get('company_tax_id')),8)
        text(left+2,89,'Inscrição Estadual: '+str(result.get('company_ie') or ''),8)
        text(448,89,'Período: '+_date(result['start'])+' a '+_date(result['end']),8)
        text(left,553,'EM HOMOLOGAÇÃO - Quadro ICMS. Campos em branco: não informados. Agrupamentos preservados.',6)
        active = ', '.join(f'{k}={v}' for k,v in filters.items() if v and k not in {'direction','status'})
        selection=wrapped('Seleção: '+active,right-left,6) if active else []
        if len(selection)>1:raise DomainError('Filtros excedem o rodapé do livro; consulte o modelo auxiliar sem truncamento.')
        if selection:text(left,562,selection[0],6)
        text(left,571,'Anexos IPI/UF/observações não reproduzidos. Dados detalhados no modelo auxiliar. Não comprova aceite Prosoft.',6)
        if not summary:table_header()
    def table_header():
        line(left,101,right);line(left,156,right)
        for x in edges:
            start = (101 if x in {54,97,358,402,471,620,804} else 122) if incoming else (101 if x in {72,231,275,318,555,796} else 121 if x in {99,130,205,218,300} else 125)
            line(x,start,x,535)
        if incoming:
            for a,b,label,top in [(97,358,'Documentos Fiscais',106),(402,471,'Codificação',106),(471,620,'Valores Fiscais',106)]:
                cell(a,b,top,label,8,True);line(a,122,b)
            for a,b,label,top in [(54,97,'Data de\nEntrada',119),(97,121,'Espécie',137),(121,140,'Série',131),(140,175,'Número',136),(175,209,'Data do\nDocto',129),(209,358,'CNPJ Emitente / UF / IE\nNome do Emitente',127),(358,402,'Valor\nContábil',117),(402,436,'Contábil',137),(436,471,'Fiscal',137),(471,494,'ICMS\nIPI',127),(494,503,'',126),(503,552,'Base de Cálculo /\nValor Operação',127),(552,574,'Alíquota\n%',127),(574,620,'Imposto\nCreditado',127),(620,804,'Observações',132)]:
                y=top;size=4.5 if b-a<18 else 5 if b-a<35 else 6
                for part in label.split('\n'):
                    cell(a,b,y,part,size,True)
                    y+=max(8,len(wrapped(part,b-a-4,size))*7.2)
            for i,part in enumerate(('C','ó','d','(a)')):text(498.5,124+i*7,part,5,True,'center')
        else:
            for a,b,label in [(72,231,'Documentos Fiscais'),(275,318,'Codificação'),(318,555,'Valores Fiscais')]:cell(a,b,105,label,8,True)
            line(72,121,231);line(318,113,555)
            cell(318,471,117,'Operações c/Débito do Imposto',6,True);cell(471,555,117,'Oper.s/Débito do Imposto',6,True);line(318,125,555)
            for a,b,label,top in [(72,99,'Espécie',137),(99,130,'Série-SSer.',137),(130,205,'N. Inicial / N. Final',137),(205,218,'Dia',137),(218,231,'UF\nDest',130),(231,275,'Valor\nContábil',117),(275,300,'Contábil',130),(300,318,'Fiscal',130),(318,400,'Base de Cálculo',138),(400,426,'Alíquota\n%',130),(426,471,'Imposto\nDebitado',130),(471,514,'Isentas ou\nNão Tributadas',130),(514,555,'Outras',137),(555,796,'Observações',127)]:
                y=top;size=4.5 if b-a<18 else 5 if b-a<35 else 6
                for part in label.split('\n'):
                    cell(a,b,y,part,size,True)
                    y+=max(8,len(wrapped(part,b-a-4,size))*7.2)
    keys = ('value','base','tax','exempt','other')
    totals = {k:[0,0,0] for k in keys} # cents, known, missing
    def accumulate(target,values):
        for k in keys:
            v=values[k];target[k][2 if v is None else 1]+=1
            if v is not None:target[k][0]+=v
    def known(target,k):return target[k][0] if target[k][1] and not target[k][2] else None
    def total_row(top,label):
        line(left,top-3,right)
        if incoming:
            cell(209,358,top,label,6,True)
            cell(358,402,top,_money(known(totals,'value')),6,True,'right')
            # Operation is not a sum of base + other across different codes.
            cell(503,552,top,_money(known(totals,'other')) if all_other else _money(known(totals,'base')) if all_credit else '',6,True,'right')
            cell(574,620,top,_money(known(totals,'tax')),6,True,'right')
        else:
            cell(72,231,top,label,6,True)
            for a,b,k in [(231,275,'value'),(318,400,'base'),(426,471,'tax'),(471,514,'exempt'),(514,555,'other')]:cell(a,b,top,_money(known(totals,k)),6,True,'right')
    def order(value):
        value=str(value or '')
        return (0,int(value)) if value.isascii() and value.isdigit() else (1,value.casefold())
    # The supplied books order dates and numeric document identities. Stable
    # sorting keeps each document's analytical lines in their original order.
    rows=sorted(result.get('rows',[]),key=lambda r:(r.get('date',''),order(r.get('document')),order(r.get('series'))));all_other=all(_book_values(r)['code']=='3' for r in rows);all_credit=all(_book_values(r)['code']=='1' for r in rows)
    header();top=159;groups=OrderedDict()
    if not rows:text(left+5,170,'Sem registros para a seleção efetiva.',8)
    for row in rows:
        values=_book_values(row)
        name_lines=wrapped(row.get('partner_name',''),145) if incoming else ['']
        identity=' '.join(v for v in (_tax_id(row.get('partner_tax_id')),row.get('partner_state',''),row.get('partner_ie','')) if v)
        identity_lines=wrapped(identity,145) if incoming else ['']
        number=str(row.get('document') or '')
        number=number.zfill(10) if number.isascii() and number.isdigit() else number
        scalar_cells=[(15,row.get('series','')),(31,number),(30,_date(row.get('issue_date'))),(39,_date(row.get('date')))] if incoming else [(27,row.get('series','')),(33,number),(9,row.get('partner_state',''))]
        scalar_height=max(len(wrapped(v,w))*7.2 for w,v in scalar_cells)
        cancelled=row.get('document_state')=='cancelled'
        observations='***CANCELADA***' if cancelled else ''
        if row.get('pending'):observations += (' ' if observations else '')+'Pendências: '+', '.join(row['pending'])
        obs_lines=wrapped(observations,180 if incoming else 237)
        row_height=max((len(name_lines)+len(identity_lines))*7.2 if incoming else 7.2,len(obs_lines)*7.2,scalar_height)
        if row_height > 350:raise DomainError('Texto do registro excede o quadro do livro; consulte o modelo auxiliar sem truncamento.')
        if top+row_height > 516:
            total_row(523,'A Transportar');c.showPage();page+=1;header();total_row(160,'De Transporte');top=174
        species={'55':'NF-E','65':'NFC-e','57':'CT-e'}.get(str(row.get('model')),str(row.get('model') or ''))
        number=str(row.get('document') or '');number=number.zfill(10) if number.isascii() and number.isdigit() else number
        if incoming:
            for a,b,value in [(54,97,_date(row.get('date'))),(97,121,species),(121,140,row.get('series')),(140,175,number),(175,209,_date(row.get('issue_date')))]:cell(a,b,top,value)
            cell(209,358,top,identity,6,align='left')
            for i,part in enumerate(name_lines):text(211,top+7.2*(i+len(identity_lines)),part)
            for a,b,value,align in [(358,402,_money(values['value']),'right'),(402,436,row.get('accounting_code',''),'center'),(436,471,row.get('cfop'),'center'),(471,494,'ICMS','center'),(494,503,values['code'],'center'),(503,552,_money(values['operation']),'right'),(552,574,values['rate'],'right'),(574,620,_money(values['tax']),'right')]:cell(a,b,top,value,6,align=align)
            cell(620,804,top,observations,6,align='left')
        else:
            series=str(row.get('series') or '');series=series.zfill(3) if series.isascii() and series.isdigit() else series
            cell(72,99,top,species);cell(99,130,top,series)
            cell(130,168,top,number);cell(168,205,top,number)
            cell(205,218,top,str(row.get('date') or '')[-2:]);cell(218,231,top,row.get('partner_state',''))
            for a,b,value,align in [(231,275,_money(values['value']),'right'),(275,300,row.get('accounting_code',''),'center'),(300,318,row.get('cfop'),'center'),(318,400,_money(values['base']),'right'),(400,426,values['rate'],'right'),(426,471,_money(values['tax']),'right'),(471,514,_money(values['exempt']),'right'),(514,555,_money(values['other']),'right')]:cell(a,b,top,value,6,align=align)
            cell(555,796,top,observations,6,align='left')
        accumulate(totals,values)
        group=groups.setdefault(row.get('cfop') or '',{k:[0,0,0] for k in keys});accumulate(group,values)
        top+=row_height
    total_row(min(top+7,523),'TOTAL GERAL')
    # A distinct summary does not change the book's analytical partitions.
    if rows:
        c.showPage();page+=1;header(summary=True)
        text((left+right)/2,114,'RESUMO POR CFOP - VALORES DO LIVRO',10,True,'center')
        text(left,130,'Somente seleção efetiva. Totais em branco quando houver valores não informados.',7)
        columns=[left,left+60,left+195,left+320,left+420,left+550,right]
        def summary_columns(continuation=False):
            if continuation:
                text((left+right)/2,114,'RESUMO POR CFOP - CONTINUAÇÃO',10,True,'center')
            for i,label in enumerate(['CFOP','Valor Contábil','Base de Cálculo','Imposto','Isentas / Não Tributadas','Outras']):cell(columns[i],columns[i+1],150,label,7,True)
            line(left,163,right)
        summary_columns();y=170
        for cfop,group in groups.items():
            if y>516:
                c.showPage();page+=1;header(summary=True);summary_columns(continuation=True);y=170
            cell(columns[0],columns[1],y,cfop,7)
            for i,k in enumerate(keys,1):cell(columns[i],columns[i+1],y,_money(known(group,k)),7,align='right')
            y+=14
        line(left,y,right);cell(columns[0],columns[1],y+5,'TOTAL GERAL',7,True)
        for i,k in enumerate(keys,1):cell(columns[i],columns[i+1],y+5,_money(known(totals,k)),7,True,'right')
    c.save();return out.getvalue(),'application/pdf'
