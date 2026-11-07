"""Relatórios do Auditor com evidências, memória, versões e tratamento atual."""
from decimal import Decimal, InvalidOperation
from io import BytesIO
import json
from xml.sax.saxutils import escape
from .core import DomainError

LABELS={'document_ref':'Documento / chave','document_id':'Documento escriturado','item_number':'Item','description':'Descrição','impact':'Impacto','recommended_action':'Orientação','responsible':'Responsável','status':'Situação','treatment':'Tratamento','source':'Fonte','source_row':'Linha de origem','ncm':'NCM','ex_code':'EX','actual_cst':'CST no XML','actual_cclass_trib':'cClassTrib no XML','expected_cst':'CST no catálogo','expected_cclass_trib':'cClassTrib no catálogo','strategy':'Critério de correspondência','parameter_source_row':'Linha da parametrização','catalog_version_id':'Versão do catálogo','base_xml':'Base no XML','base_recalculated':'Base recalculada','difference':'Diferença','ibs_xml':'IBS no XML','ibs_recalculated':'IBS recalculado','cbs_xml':'CBS no XML','cbs_recalculated':'CBS recalculada','ibs_rate':'Alíquota IBS','cbs_rate':'Alíquota CBS','components':'Componentes','original':'Original','booked_cents':'Escriturado (centavos)','file_id':'Arquivo original','sha256':'SHA-256','version':'Versão','vProd':'Produtos','vServ':'Serviços','vFrete':'Frete','vSeg':'Seguro','vOutro':'Outras despesas','vII':'II','vDesc':'Desconto','vPIS':'PIS','vCOFINS':'Cofins','vICMS':'ICMS','vICMSUFDest':'ICMS UF destino','vFCP':'FCP','vFCPUFDest':'FCP UF destino','vICMSMono':'ICMS monofásico','vISSQN':'ISSQN','vIS':'Imposto Seletivo'}
LABELS.update({'estimated_cost': 'Custo estimado', 'estimated_margin': 'Margem estimada', 'estimated_unit_cost': 'Custo unitário estimado', 'identity': 'Identidade do produto', 'basis': 'Critério', 'confidence': 'Confiança', 'key': 'Chave', 'label': 'Identificador', 'type': 'Tipo', 'input_quantity': 'Quantidade de entradas', 'output_quantity': 'Quantidade de saídas', 'input_value': 'Valor de entradas', 'output_value': 'Valor de saídas', 'layer': 'Área da análise', 'sample_limitation': 'Limitado à amostra'})
STATUS={'completed':'Concluída','failed':'Falhou','running':'Em processamento','cancelled':'Cancelado','rejected':'Recusado','duplicate':'Duplicado','auxiliary':'PDF auxiliar','event':'Evento','internal':'Escrituração','standalone':'Avulsa','critical':'Crítica','high':'Alta','medium':'Média','low':'Baixa','open':'Aberto','reviewing':'Em revisão','resolved':'Tratado','dismissed':'Justificado','authorized':'Autorizado no XML','parsed':'Lido','cancelled':'Cancelado','outside_period':'Fora do período','missing_input':'Entrada ausente na amostra','insufficient_quantity_data':'Quantidades incompletas','insufficient_input_quantity':'Entradas insuficientes','review_identity':'Revisar identidade','negative_margin':'Margem negativa','zero_margin':'Margem zero','reconciled':'Correspondência exata','reconciled_estimate':'Correspondência estimada','in_stock':'Sem saída na amostra'}

def amount(value):
    if value is None:return '—'
    try:return f'{Decimal(str(value)):,.2f}'.replace(',','X').replace('.',',').replace('X','.')
    except InvalidOperation:return str(value)

def day(value):return '/'.join(str(value)[:10].split('-')[::-1]) if value else '—'

def evidence_rows(value,prefix=''):
    if isinstance(value,dict):
        for key,item in value.items():yield from evidence_rows(item,(prefix+' / ' if prefix else '')+LABELS.get(key,key.replace('_',' ')))
    elif isinstance(value,list):
        for n,item in enumerate(value,1):yield from evidence_rows(item,f'{prefix} / {n}')
    else:yield [prefix,'—' if value is None else 'Sim' if value is True else 'Não' if value is False else str(value)]

def calculation_scope(job,document,item):
    if item.get('calculation_scope'):return item['calculation_scope']
    if any(f['rule_code']=='COVERAGE-IBSCBS-001' and f['document_ref']==document['document_ref'] and f.get('item_number')==item['item_number'] for f in job['findings']):return 'unsupported_special'
    return 'legacy'

def export_audit(job,format):
    snap=job['snapshot'];result=job['result'];output=BytesIO()
    sections=[('Documentos',[{k:d.get(k) for k in ('document_ref','number','model','issued_at','direction','status','total_value','bookkeeping_id','bookkeeping_version','original_file_id')} for d in result['documents']]),
              ('Itens e memória',[{'document_ref':d['document_ref'],**i} for d in result['documents'] for i in d.get('items',[])]),
              ('Achados',job['findings']),('Conciliação e margens',result['reconciliation']),('Eventos',result['events']),
              ('Escrituração original',snap['bookkeeping']),('Catálogo',(snap['catalog'] or {}).get('entries',[])),('PDFs vinculados',job.get('attachments',[])),('Logs',job['logs'])]
    comparison=[]
    for d in result['documents']:
        for i in d.get('items',[]):
            scope=calculation_scope(job,d,i)
            comparison.append({'Documento':d.get('number'),'Item':i['item_number'],'Descrição':i.get('description'),'NCM':i.get('ncm'),'CST XML':i.get('actual_cst'),'cClassTrib XML':i.get('actual_cclass_trib'),'Cobertura':{'regular':'Aritmética regular','absent':'Sem grupo IBS/CBS','unsupported_special':'Não recalculado: cenário especial','legacy':'Conferência assistida'}.get(scope,scope),
                **{label:i.get(field) if not recalc or scope in {'regular','legacy'} else None for label,field,recalc in [('Base XML','ibs_cbs_base_xml',False),('Base recalculada','ibs_cbs_base_recalculated',True),('IBS XML','ibs_xml',False),('IBS recalculado','ibs_recalculated',True),('CBS XML','cbs_xml',False),('CBS recalculada','cbs_recalculated',True)]}})
    sections.insert(2,('Comparativo tributos',comparison))
    metadata={'Situação da auditoria':STATUS.get(job['status'],job['status']),'Empresa':snap['company']['name'],'CNPJ':snap['company']['tax_id'],'Período':day(job['start'])+' a '+day(job['end']),'Origem':STATUS.get(job['mode'],job['mode']),'Motor':result['engine'],'Retrato SHA-256':result['snapshot_sha256'],'Catálogo SHA-256':result['catalog_sha256'] or 'Sem catálogo publicado','Documentos alterados depois da auditoria':', '.join(map(str,job['stale_document_ids'])) or 'Nenhum','Total da amostra (R$)':amount(Decimal(result['totals']['total_cents'])/100),'Limitações':'; '.join(snap['coverage']['limitations'])}
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
        from .auditor_workbook import enrich_workbook
        enrich_workbook(wb,job)
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
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from pathlib import Path
    import reportlab
    if 'EscrituraSans' not in pdfmetrics.getRegisteredFontNames():
        fonts=Path(reportlab.__file__).parent/'fonts'
        pdfmetrics.registerFont(TTFont('EscrituraSans',str(fonts/'Vera.ttf')))
        pdfmetrics.registerFont(TTFont('EscrituraSans-Bold',str(fonts/'VeraBd.ttf')))
        pdfmetrics.registerFontFamily('EscrituraSans',normal='EscrituraSans',bold='EscrituraSans-Bold')
    styles=getSampleStyleSheet()
    for style in styles.byName.values():style.fontName='EscrituraSans-Bold' if 'Heading' in style.name or style.name=='Title' else 'EscrituraSans'
    for name in ('Heading1','Heading2','Heading3'):styles[name].keepWithNext=True
    body=ParagraphStyle('auditbody',parent=styles['BodyText'],fontSize=8,leading=11,wordWrap='CJK')
    def p(v):return Paragraph(escape(str(v if v is not None else '')),body)
    story=[Paragraph('Escritura Integrada · Auditor Fiscal',styles['Title'])]
    for k,v in metadata.items():story.append(p(f'{k}: {v}'))
    story += [Spacer(1,14),p('Auditoria não altera a origem. Resolver um achado registra seu tratamento; correções exigem os fluxos próprios e suas permissões. Valores monetários em reais, salvo indicação de centavos. Fórmula recuperada e cenários especiais exigem revisão de vigência.')]
    def table(headers,rows,widths):
        if not rows:return [p('Sem registros nesta seção.')]
        t=LongTable([[p(c) for c in headers]]+[[p(c) for c in r] for r in rows],colWidths=widths,repeatRows=1,splitInRow=1)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dcebe7')),('GRID',(0,0),(-1,-1),.3,colors.HexColor('#b8c5c2')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5)]));return [t]
    from .auditor_results import analytics
    stats=analytics(result['documents'],job['findings'])
    story += [Spacer(1,14),Paragraph('Resumo executivo',styles['Heading1'])]
    overview=stats['overview']
    story += table(['Indicador','Quantidade','Valor (R$)'],[
        ['Documentos elegíveis',overview['documents'],amount(overview['total_value'])],
        ['Entradas',overview['input_count'],amount(overview['input_value'])],
        ['Saídas',overview['output_count'],amount(overview['output_value'])],
        ['Itens',overview['items'],''],['Achados',overview['findings'],''],
        ['Arquivos recusados',result.get('outcome',{}).get('rejected',0),'']], [380,180,200])
    story += table(['Severidade','Achados'],[[STATUS.get(k,k),v] for k,v in stats['severity_counts'].items()],[380,380])
    story += [Spacer(1,12),Paragraph('Arquivos, recusas e duplicidades',styles['Heading2'])]
    story += table(['Origem / hash','Resultado','Diagnóstico'],[[o['name']+' / '+o['sha256'],STATUS.get(o['status'],o['status']),o.get('error','')] for o in result.get('file_outcomes',[])],[360,140,260])
    story += [PageBreak(),Paragraph('Documentos e origens',styles['Heading1'])]
    story += table(['Documento / chave','Emissão / situação','Valor XML (R$)','Escrituração / original'],[[str(d.get('number'))+' / '+d['document_ref'],day(d.get('issued_at'))+' / '+STATUS.get(d['status'],d['status']),amount(d['total_value']),str(d.get('bookkeeping_id','Avulso'))+' / arquivo '+str(d['original_file_id'])] for d in result['documents']],[280,190,90,200])
    if snap['bookkeeping']:
        booked={r['id']:r for r in snap['bookkeeping']}
        story += [Spacer(1,12),Paragraph('Original e escriturado',styles['Heading2'])]
        story += table(['Documento','Original XML (R$)','Escriturado (R$)','Diferença (R$)','Versão da origem'],[
            [d.get('number'),amount(d['total_value']) if d.get('origin')=='xml' else 'XML indisponível',
             amount(Decimal(booked[d['bookkeeping_id']]['total_cents'])/100),
             amount(Decimal(booked[d['bookkeeping_id']]['total_cents'])/100-Decimal(d['total_value'])) if d.get('origin')=='xml' else 'Não comparável',
             d.get('bookkeeping_version')]
            for d in result['documents'] if d.get('bookkeeping_id') in booked],[180,145,145,145,145])
    story += [Spacer(1,12),Paragraph('Classificação NCM / EX / CST / cClassTrib',styles['Heading2'])]
    story += table(['Documento / item','Produto / NCM / EX','XML: CST / cClassTrib','Catálogo: CST / cClassTrib','Situação'],[[str(d.get('number'))+' / '+str(i['item_number']),str(i.get('description') or '')+' / '+str(i.get('ncm') or '')+' / '+str(i.get('ex_code') or ''),str(i.get('actual_cst') or '')+' / '+str(i.get('actual_cclass_trib') or ''),str(i.get('expected_cst') or '')+' / '+str(i.get('expected_cclass_trib') or ''),i.get('classification_status','')] for d in result['documents'] for i in d['items']],[90,250,130,130,160])
    story += [PageBreak(),Paragraph('Achados, evidências e tratamento',styles['Heading1'])]
    for f in job['findings']:
        story.append(Paragraph(escape(f"{STATUS.get(f['severity'],f['severity'])} · {f['rule_code']} · {f['title']}"),styles['Heading3']))
        rows=[[LABELS[k],STATUS.get(str(f[k]),f[k])] for k in ('document_ref','item_number','description','impact','recommended_action','responsible','status','treatment') if f.get(k) is not None]
        rows+=list(evidence_rows(f.get('evidence',{}),'Evidência'))
        story+=table(['Informação','Conteúdo'],rows,[180,580]);story.append(Spacer(1,10))
    story += [PageBreak(),Paragraph('Memória de cálculo por item',styles['Heading1'])]
    for d in result['documents']:
        for i in d.get('items',[]):
            story.append(Paragraph(escape(f"Documento {d.get('number')} · item {i.get('item_number')} · {i.get('description')}"),styles['Heading3']))
            scope=calculation_scope(job,d,i);valid=scope in {'regular','legacy'}
            note='Não recalculado: cenário especial' if scope=='unsupported_special' else 'Sem grupo IBS/CBS'
            rows=[[label,amount(i.get(original)),amount(i.get(recalc)) if valid else note] for label,original,recalc in [('Base IBS/CBS','ibs_cbs_base_xml','ibs_cbs_base_recalculated'),('IBS','ibs_xml','ibs_recalculated'),('CBS','cbs_xml','cbs_recalculated')]]
            story+=table(['Tributo / base (R$)','XML original','Conferência recalculada'],rows,[240,240,280])
            for tax,m in i.get('details',{}).get('calculation_memory',{}).items():
                if isinstance(m,dict):story+=table([tax+' · base','Alíquota (%)','XML (R$)','Recálculo (R$)'],[[amount(m.get('base')),str(m.get('rate')),amount(m.get('original')),amount(m.get('recalculated')) if m.get('scope')=='ad_valorem' else 'Não recalculado']],[190,190,190,190])
            story+=table(['Componente da base','Valor'],[[LABELS.get(k,k),amount(v)] for k,v in i.get('tax_components',{}).items()],[240,520])
            story+=table(['Parametrização','Evidência'],list(evidence_rows(i.get('catalog_match',{}))),[240,520])
            story.append(p('Arredondamento: Decimal ROUND_HALF_UP, por componente para centavos. Base assistida: fórmula recuperada UB16-10, sujeita a confirmação de vigência e cenário. Grupos especiais indicados na cobertura não foram recalculados.'))
            story.append(Spacer(1,12))
    story += [PageBreak(),Paragraph('Conciliação, custos e margens da amostra',styles['Heading1'])]
    story.append(p('Estimativas restritas aos documentos analisados; não substituem controle de estoque ou custeio. Ausência de quantidade ou de entradas impede estimar custo e margem.'))
    story+=table(['Identificador / produto','Entrada / saída (qtd.)','Entradas / saídas (R$)','Custo / margem estimados (R$)','Situação'],[[r['identifier']+' / '+str(r.get('description') or ''),str(r['input_quantity'])+' / '+str(r['output_quantity']),amount(r['input_value'])+' / '+amount(r['output_value']),amount(r['estimated_cost'])+' / '+amount(r['margin']),STATUS.get(r['status'],r['status'])] for r in result['reconciliation']],[200,110,140,150,160])
    story += [Spacer(1,12),Paragraph('Eventos preservados',styles['Heading2'])]
    for event in result['events']:story+=table(['Campo','Valor'],list(evidence_rows(event)),[180,580])
    if not result['events']:story.append(p('Nenhum evento nesta auditoria.'))
    story += [Spacer(1,12),Paragraph('PDFs associados por revisão',styles['Heading2'])]
    story += table(['Documento','Arquivo','Revisor / justificativa'],[[a['document_ref'],a['file_id'],a['created_by']+' / '+a['reason']] for a in job.get('attachments',[])],[280,100,380])
    story += [PageBreak(),Paragraph('Fontes, qualidade do catálogo e histórico',styles['Heading1'])]
    catalog=snap.get('catalog') or {}
    from .auditor_catalogs import diagnostics
    issues=diagnostics(catalog.get('entries',[]),catalog.get('reference',{}))
    story += table(['Linha / NCM','Diagnóstico'],[[str(i.get('source_row'))+' / '+str(i.get('ncm')),i['message']] for i in issues],[200,560])
    story += table(['Data','Nível','Log'],[[day(l['created_at'])+' '+l['created_at'][11:19],l['level'],l['message']] for l in job['logs']],[160,80,520])
    def footer(canvas,doc):
        canvas.setFont('EscrituraSans',7);canvas.drawString(36,20,f"Auditoria {job['id']} · {result['engine']}");canvas.drawRightString(806,20,f'Página {doc.page}')
    SimpleDocTemplate(output,pagesize=landscape(A4),leftMargin=36,rightMargin=36,topMargin=32,bottomMargin=35,title='Auditor Fiscal',author='Escritura Integrada').build(story,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue(),'application/pdf'
