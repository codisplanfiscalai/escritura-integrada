"""Compact portrait trial balance inspired by the supplied accounting reference."""
from io import BytesIO
from decimal import Decimal
from xml.sax.saxutils import escape
from .core import DomainError


def trial_balance_pdf(result, first_page=1):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, LongTable, TableStyle, Paragraph, Spacer
    from .accounting_report_models import validate_first_page
    validate_first_page(first_page)
    out=BytesIO(); width,height=A4; margin=20; usable=width-2*margin
    doc=SimpleDocTemplate(out,pagesize=A4,leftMargin=margin,rightMargin=margin,topMargin=126,bottomMargin=40,title='Balancete',author='Escritura Integrada')
    normal=ParagraphStyle('trial',fontName='Courier',fontSize=7,leading=9)
    bold=ParagraphStyle('trial-bold',parent=normal,fontName='Courier-Bold')
    def p(value,style=normal): return Paragraph(escape(str(value or '')),style)
    def amount(value):
        n=Decimal(value or 0)/100
        return f'{abs(n):,.2f}'.replace(',','@').replace('.',',').replace('@','.')+(' C' if n<0 else ' D' if n>0 else '')
    def movement(value): return f'{Decimal(value or 0)/100:,.2f}'.replace(',','@').replace('.',',').replace('@','.')
    fields=['access_code','classifier','account_name','opening_cents','debit_cents','credit_cents','closing_cents']
    headers=['Acesso','Classificador','Nome da conta','Saldo inicial','Mov. débito','Mov. crédito','Saldo final']
    widths=[32,77,164,70,70,70,72]; factor=usable/sum(widths);widths=[w*factor for w in widths]
    data=[[p(x,bold) for x in headers]];commands=[('VALIGN',(0,0),(-1,-1),'TOP'),('LINEABOVE',(0,0),(-1,0),.5,'black'),('LINEBELOW',(0,0),(-1,0),.5,'black'),('LEFTPADDING',(0,0),(-1,-1),2),('RIGHTPADDING',(0,0),(-1,-1),2),('TOPPADDING',(0,0),(-1,-1),2),('BOTTOMPADDING',(0,0),(-1,-1),2),('ALIGN',(3,1),(-1,-1),'RIGHT'),('FONTNAME',(0,0),(-1,-1),'Courier'),('FONTSIZE',(0,0),(-1,-1),7)]
    for index,row in enumerate(result['rows'],1):
        synthetic=row.get('analytical') is False
        style=ParagraphStyle('row'+str(index),parent=bold if synthetic else normal,leftIndent=min(row.get('depth',0),8)*4)
        data.append([p(row.get('access_code')),p(row.get('classifier')),p(row.get('account_name'),style),amount(row.get('opening_cents')),movement(row.get('debit_cents')),movement(row.get('credit_cents')),amount(row.get('closing_cents'))])
        if synthetic:
            commands.extend([('FONTNAME',(0,index),(-1,index),'Courier-Bold'),('TOPPADDING',(0,index),(-1,index),5)])
            if index<len(result['rows']): commands.append(('NOSPLIT',(0,index),(-1,index+1)))
    story=[]
    if result['rows']:
        # Bound ReportLab table layout cost, including the optional full plan.
        offset=1
        while offset<len(data):
            end=min(offset+200,len(data))
            while end<len(data) and end>offset+1 and result['rows'][end-2].get('analytical') is False:
                end-=1
            chunk=[data[0]]+data[offset:end]
            local=[('ALIGN',(3,1),(-1,-1),'RIGHT')]
            for command in commands:
                if command[1][1] <= 0:
                    local.append(command)
                elif offset<=command[1][1]<end:
                    last=min(command[2][1],end-1) if command[2][1]>=0 else command[2][1]
                    local.append((command[0],(command[1][0],command[1][1]-offset+1),(command[2][0],last-offset+1 if last>=0 else last),*command[3:]))
            table=LongTable(chunk,colWidths=widths,repeatRows=1,hAlign='LEFT',splitByRow=1,splitInRow=1)
            table.setStyle(TableStyle(local));story.append(table)
            offset=end
    else: story.append(p('Nenhum registro nos filtros selecionados.'))
    totals=result.get('totals',{})
    story.extend([Spacer(1,10),p('Totais do escopo consultado - somente contas analíticas',bold)])
    total_data=[[p(k,bold) for k in headers[3:]], [amount(totals.get('opening_cents')),movement(totals.get('debit_cents')),movement(totals.get('credit_cents')),amount(totals.get('closing_cents'))]]
    table=LongTable(total_data,colWidths=[usable/4]*4);table.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),'Courier-Bold'),('FONTSIZE',(0,0),(-1,-1),7),('ALIGN',(0,1),(-1,1),'RIGHT'),('LINEABOVE',(0,0),(-1,0),.5,'black')]));story.append(table)
    story.extend([Spacer(1,8),p(result.get('scope_note',''))])
    # Unknown extension fields remain auditable without printing technical IDs per account.
    internal=set(fields)|{'account_id','report_group','analytical','depth','journal_ids'}
    extras=[(i,k,v) for i,r in enumerate(result['rows'],1) for k,v in r.items() if k not in internal]
    if extras:
        story.extend([Spacer(1,8),p('Campos complementares',bold)])
        for i,k,v in extras:story.append(p(f'{i} / {k}: {v}'))
    def frame(canvas, document):
        page=first_page+document.page-1
        if page>99999:raise DomainError('Paginação excede a folha 99999.')
        canvas.saveState();canvas.setFont('Courier-Bold',9)
        canvas.drawString(margin,height-29,'Balancete Analítico (Valores em Reais)')
        canvas.setFont('Courier',7);canvas.drawRightString(width-margin,height-29,f'Folha: {page:05d}')
        canvas.line(margin,height-36,width-margin,height-36)
        canvas.drawString(margin,height-49,str(result.get('company_name',''))[:95]+' ('+str(result.get('company_code',''))+')')
        canvas.drawString(margin,height-64,'CNPJ/CPF: '+str(result.get('company_tax_id','')))
        dates=['/'.join(str(result[k]).split('-')[::-1]) for k in ('start','end')]
        canvas.drawString(margin,height-79,'Período: '+dates[0]+' a '+dates[1])
        filters=result.get('filters',{});mode='Todas as contas' if filters.get('activity')=='all' else 'Com movimento (inclui contas com saldo)'
        canvas.drawString(margin,height-94,mode+' | Conta: '+str(filters.get('account_id') or 'Todas')+' | Centro: '+str(filters.get('cost_center_id') or 'Todos'))
        if filters.get('query'):canvas.drawString(margin,height-106,'Pesquisa: '+str(filters['query'])[:90])
        canvas.setFont('Courier',6)
        canvas.drawString(margin,23,'Escritura Integrada | layout não homologado | D: devedor; C: credor | Totais sem duplicar sintéticas')
        canvas.drawRightString(width-margin,14,f'Página {document.page}');canvas.restoreState()
    doc.build(story,onFirstPage=frame,onLaterPages=frame)
    return out.getvalue(),'application/pdf'
