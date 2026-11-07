"""Relatórios do Auditor com evidências, memória, versões e tratamento atual."""
from io import BytesIO
import json
from xml.sax.saxutils import escape
from .core import DomainError


def export_audit(job,format):
    snap=job['snapshot'];result=job['result'];output=BytesIO()
    sections=[('Documentos',[{k:d.get(k) for k in ('document_ref','number','model','issued_at','direction','status','total_value','bookkeeping_id','bookkeeping_version','original_file_id')} for d in result['documents']]),
              ('Itens e memória',[{'document_ref':d['document_ref'],**i} for d in result['documents'] for i in d.get('items',[])]),
              ('Achados',job['findings']),('Conciliação e margens',result['reconciliation']),('Eventos',result['events']),
              ('Escrituração original',snap['bookkeeping']),('Catálogo',(snap['catalog'] or {}).get('entries',[])),('Logs',job['logs'])]
    metadata={'Empresa':snap['company']['name'],'CNPJ':snap['company']['tax_id'],'Período':job['start']+' a '+job['end'],'Origem':job['mode'],'Motor':result['engine'],'Snapshot SHA-256':result['snapshot_sha256'],'Catálogo SHA-256':result['catalog_sha256'] or 'Sem catálogo publicado','Documentos alterados depois da auditoria':job['stale_document_ids'],'Total da amostra (centavos)':result['totals']['total_cents'],'Limitações':snap['coverage']['limitations']}
    if format=='xlsx':
        from openpyxl import Workbook
        from openpyxl.styles import Font,PatternFill,Alignment
        from openpyxl.utils import get_column_letter
        wb=Workbook();ws=wb.active;ws.title='Resumo';ws.append(['Campo','Valor'])
        for k,v in metadata.items():ws.append([k,str(v)])
        for name,rows in sections:
            sheet=wb.create_sheet(name[:31]);keys=list(dict.fromkeys(k for r in rows for k in r));sheet.append(keys or ['Sem registros'])
            for r in rows:sheet.append([json.dumps(r.get(k),ensure_ascii=False,default=str) if isinstance(r.get(k),(list,dict)) else r.get(k) for k in keys])
            sheet.auto_filter.ref=sheet.dimensions
        for sheet in wb:
            sheet.freeze_panes='A2'
            for col in range(1,sheet.max_column+1):sheet.column_dimensions[get_column_letter(col)].width=30
            for row in sheet:
                for c in row:
                    if isinstance(c.value,str):c.data_type='s'
                    c.alignment=Alignment(wrap_text=True,vertical='top')
            for c in sheet[1]:c.font=Font(color='FFFFFF',bold=True);c.fill=PatternFill('solid',fgColor='225F57')
        wb.save(output)
        return output.getvalue(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    if format!='pdf':raise DomainError('Selecione PDF ou Excel.')
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib.pagesizes import A4,landscape
    from reportlab.lib import colors
    styles=getSampleStyleSheet();body=ParagraphStyle('auditbody',parent=styles['BodyText'],fontSize=8,leading=11,wordWrap='CJK')
    def p(v):return Paragraph(escape(str(v if v is not None else '')),body)
    story=[Paragraph('Escritura Integrada · Auditor Fiscal',styles['Title'])]
    for k,v in metadata.items():story.append(p(f'{k}: {v}'))
    story += [Spacer(1,14),p('Auditoria não altera a origem. Resolver um achado registra seu tratamento; correções exigem os fluxos próprios e suas permissões. Valores monetários em reais, salvo indicação de centavos. Fórmula recuperada e cenários especiais exigem revisão de vigência.')]
    def table(headers,rows,widths):
        if not rows:return [p('Sem registros nesta seção.')]
        t=LongTable([[p(c) for c in headers]]+[[p(c) for c in r] for r in rows],colWidths=widths,repeatRows=1,splitInRow=1)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dcebe7')),('GRID',(0,0),(-1,-1),.3,colors.HexColor('#b8c5c2')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5)]));return [t]
    story += [PageBreak(),Paragraph('Documentos e origens',styles['Heading1'])]
    story += table(['Documento / chave','Emissão / situação','Valor XML','Escrituração / original'],[[str(d.get('number'))+'\n'+d['document_ref'],str(d.get('issued_at'))+' / '+d['status'],d['total_value'],str(d.get('bookkeeping_id','Avulso'))+' / arquivo '+str(d['original_file_id'])] for d in result['documents']],[280,190,90,200])
    story += [PageBreak(),Paragraph('Achados, evidências e tratamento',styles['Heading1'])]
    for f in job['findings']:
        story.append(Paragraph(escape(f"{f['severity']} · {f['rule_code']} · {f['title']}"),styles['Heading3']))
        for k in ('document_ref','item_number','description','impact','recommended_action','responsible','status','treatment','evidence'):
            if f.get(k) is not None:story.append(p(f'{k}: '+json.dumps(f[k],ensure_ascii=False,default=str)))
        story.append(Spacer(1,8))
    story += [PageBreak(),Paragraph('Memória de cálculo por item',styles['Heading1'])]
    for d in result['documents']:
        for i in d.get('items',[]):
            story.append(Paragraph(escape(f"Documento {d.get('number')} · item {i.get('item_number')} · {i.get('description')}"),styles['Heading3']))
            for k in ('tax_components','ibs_cbs_base_xml','ibs_cbs_base_recalculated','base_difference','ibs_xml','ibs_recalculated','cbs_xml','cbs_recalculated','classification_status','classification_evidence'):
                if k in i:story.append(p(k+': '+json.dumps(i[k],ensure_ascii=False,default=str)))
            story.append(p('Arredondamento monetário: Decimal ROUND_HALF_UP; grupos especiais indicados na cobertura não foram recalculados.'))
    story += [PageBreak(),Paragraph('Conciliação, custos e margens da amostra',styles['Heading1'])]
    for r in result['reconciliation']:story.append(p(json.dumps(r,ensure_ascii=False,default=str)))
    def footer(canvas,doc):
        canvas.setFont('Helvetica',7);canvas.drawString(36,20,f"Auditoria {job['id']} · {result['engine']}");canvas.drawRightString(806,20,f'Página {doc.page}')
    SimpleDocTemplate(output,pagesize=landscape(A4),leftMargin=36,rightMargin=36,topMargin=32,bottomMargin=35,title='Auditor Fiscal',author='Escritura Integrada').build(story,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue(),'application/pdf'
