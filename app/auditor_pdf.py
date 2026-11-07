"""Modelo analítico/sintético do Auditor 1.2.2 adaptado ao retrato do Escritura.

Preserva a organização editorial original e acrescenta tratamento, cobertura,
comparação escriturada e integridade. Não usa valores não recalculados como zero.
"""
import json
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, Table, TableStyle, PageBreak, KeepTogether
import reportlab
from .auditor_reports import amount, day, LABELS, STATUS, evidence_rows, calculation_scope
from .auditor_results import analytics
from .auditor_presentation import eligible, counterpart, SEVERITY_ORDER

NAVY='#12324A'; TEAL='#225F57'; LIGHT='#EDF3F6'; MINT='#E3F1EB'; WARN='#FFF1D1'; DANGER='#FBE7E5'; GRID='#C9D6DE'
WIDTH=770


def build_pdf(job):
    output=BytesIO();snapshot=job['snapshot'];result=job['result'];docs=result['documents'];findings=job['findings']
    stats=analytics(docs,findings);overview=stats['overview'];catalog=snapshot.get('catalog') or {}
    if 'EscrituraSans' not in pdfmetrics.getRegisteredFontNames():
        fonts=Path(reportlab.__file__).parent/'fonts'
        pdfmetrics.registerFont(TTFont('EscrituraSans',str(fonts/'Vera.ttf')))
        pdfmetrics.registerFont(TTFont('EscrituraSans-Bold',str(fonts/'VeraBd.ttf')))
        pdfmetrics.registerFontFamily('EscrituraSans',normal='EscrituraSans',bold='EscrituraSans-Bold')
    styles=getSampleStyleSheet()
    body=ParagraphStyle('audit-body',fontName='EscrituraSans',fontSize=8,leading=11,textColor=colors.HexColor(NAVY),spaceAfter=3)
    small=ParagraphStyle('audit-small',parent=body,fontSize=7,leading=9,spaceAfter=0)
    heading=ParagraphStyle('audit-heading',parent=body,fontName='EscrituraSans-Bold',fontSize=17,leading=21,spaceAfter=12,keepWithNext=True)
    sub=ParagraphStyle('audit-sub',parent=heading,fontSize=11,leading=15,spaceBefore=12,spaceAfter=6)
    white=ParagraphStyle('audit-white',parent=body,textColor=colors.white)
    story=[]
    def p(text,style=body):return Paragraph(escape(str('—' if text is None else text)).replace('\n','<br/>'),style)
    def table(headers,rows,widths=None,numeric=()):
        widths=widths or [WIDTH/len(headers)]*len(headers)
        data=[[p(h,ParagraphStyle('th',parent=small,fontName='EscrituraSans-Bold',textColor=colors.white)) for h in headers]]
        data += [[p(v,ParagraphStyle('num',parent=small,alignment=2) if c in numeric else small) for c,v in enumerate(row)] for row in rows]
        if not rows:data.append([p('Sem registros para esta seção.')]+['']*(len(headers)-1))
        t=LongTable(data,colWidths=widths,repeatRows=1,splitInRow=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor(TEAL)),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor(LIGHT)]),('GRID',(0,0),(-1,-1),.25,colors.HexColor(GRID)),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3)]))
        return t
    def chapter(title,description=None):
        story.extend([PageBreak(),p(title,heading)])
        if description:story.extend([p(description),Spacer(1,8)])
    title=ParagraphStyle('cover-title',parent=heading,fontSize=22,leading=26,textColor=colors.white)
    header=Table([[p('AUDITOR FISCAL · ESCRITURA INTEGRADA',white)],[p('Relatório Analítico e Sintético',title)],[p('Conferência de documentos, tributos e IBS/CBS',white)],[p(f"{snapshot['company']['name']} · CNPJ {snapshot['company']['tax_id']}\n{day(job['start'])} a {day(job['end'])} · {STATUS.get(job['mode'],job['mode'])} · Auditoria #{job['id']}",white)]],colWidths=[WIDTH])
    header.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor(NAVY)),('LEFTPADDING',(0,0),(-1,-1),18),('RIGHTPADDING',(0,0),(-1,-1),18),('TOPPADDING',(0,0),(-1,0),15),('BOTTOMPADDING',(0,-1),(-1,-1),14)]))
    story.extend([header,Spacer(1,14),p('Resumo executivo',sub)])
    kpis=[('Documentos elegíveis',overview['documents']),('Valor dos documentos','R$ '+amount(overview['total_value'])),('Base IBS/CBS informada','R$ '+amount(overview['ibs_cbs_base'])),('IBS + CBS informados','R$ '+amount(Decimal(overview['ibs_value'])+Decimal(overview['cbs_value']))),('Entradas',f"{overview['input_count']} · R$ {amount(overview['input_value'])}"),('Saídas',f"{overview['output_count']} · R$ {amount(overview['output_value'])}"),('Itens / classificação OK',f"{overview['items']} / {stats['classification_ok']}"),('Achados abertos / em revisão',stats['open_findings'])]
    cells=[]
    for index,(label,value) in enumerate(kpis):
        card=Table([[p(label,small)],[p(value,ParagraphStyle('kpi',parent=body,fontName='EscrituraSans-Bold',fontSize=14,leading=18))]],colWidths=[WIDTH/4-8])
        card.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor(DANGER if index==7 else MINT if index in {1,3} else LIGHT)),('BOX',(0,0),(-1,-1),.4,colors.HexColor(GRID)),('LEFTPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),6)]));cells.append(card)
    story.extend([Table([cells[:4],cells[4:]],colWidths=[WIDTH/4]*4,hAlign='LEFT'),Spacer(1,12)])
    conclusion=f"{overview['documents']} documentos elegíveis e {overview['items']} itens. {stats['comparable_items']} itens com recálculo comparável e {stats['not_recalculated_items']} sem recálculo. {stats['excluded_documents']} documentos cancelados ou fora do período estão separados dos totais."
    priorities='\n'.join(f"{n}. {f['title']}: {f.get('recommended_action') or f['description']}" for n,f in enumerate(stats['priorities'][:4],1)) or 'Nenhum achado aberto ou em revisão.'
    story.extend([table(['CONCLUSÃO CENTRAL','AÇÕES PRIORITÁRIAS'],[[conclusion,priorities]],[WIDTH*.45,WIDTH*.55]),Spacer(1,10),p(f"Situação: {STATUS.get(job['status'],job['status'])} · Catálogo: {catalog.get('name') or 'Sem catálogo publicado'}",small)])
    if job.get('error'):story.append(p('Falha do processamento: '+job['error']))
    if job.get('stale_document_ids'):story.append(p('A origem mudou após a auditoria. Reprocessar documentos: '+', '.join(map(str,job['stale_document_ids']))))
    chapter('1. Como a base de IBS/CBS foi formada','Comparativo restrito aos mesmos itens efetivamente recalculados. Diferença = XML menos recálculo; não representa, por si só, tributo a recuperar ou recolher.')
    story.append(table(['Fórmula recuperada UB16-10 — conferência assistida'],[['BC = vProd + vServ + vFrete + vSeg + vOutro + vII - vDesc - vPIS - vCOFINS - vICMS - vICMSUFDest - vFCP - vFCPUFDest - vICMSMono - vISSQN + vIS.']]))
    nonzero=[r for r in stats['components'] if Decimal(r['value'])]
    story.extend([Spacer(1,12),table(['Componente da base','Sinal','Valor (R$)'],[[LABELS.get(r['code'],r['code'])+' ('+r['code']+')',r['sign'],amount(r['value'])] for r in nonzero],[490,80,200],(2,)),Spacer(1,12),table(['Tributo / base','XML (R$)','Recálculo (R$)','Diferença (R$)','Itens comparáveis'],[[r['label'],*[amount(r[k]) if r['items'] else 'Não recalculado' for k in ('original','recalculated','difference')],r['items']] for r in stats['tax_comparison']],[190,150,150,150,130],(1,2,3)),p(f"{stats['not_recalculated_items']} itens fora do recálculo. Cenários especiais, ausência do grupo IBS/CBS e documentos sem XML não são apresentados como diferença zero.",small)])
    for number,direction,label in [(2,'saida','saídas'),(3,'entrada','entradas')]:
        selected=[d for d in docs if eligible(d) and d['direction']==direction]
        chapter(f'{number}. Relatório analítico das {label}',f"{len(selected)} documentos elegíveis · R$ {amount(sum((Decimal(d['total_value']) for d in selected),Decimal(0)))}. Contraparte: {'destinatário' if direction=='saida' else 'emitente'}.")
        rows=[[d.get('number'),day(d.get('issued_at')),counterpart(d),*[amount(d.get(k)) for k in ('total_value','ibs_cbs_base','ibs_value','cbs_value')],len(d.get('items',[])),STATUS.get(d['status'],d['status'])] for d in selected]
        if rows:rows.append(['TOTAL','',f'{len(selected)} documentos',*[amount(sum((Decimal(str(d.get(k) or 0)) for d in selected),Decimal(0))) for k in ('total_value','ibs_cbs_base','ibs_value','cbs_value')],sum(len(d.get('items',[])) for d in selected),''])
        story.append(table(['NF / nº','Emissão','Participante','Valor NF','Base IBS/CBS','IBS','CBS','Itens','Situação'],rows,[50,65,195,85,90,65,65,35,120],(3,4,5,6,7)))
    chapter('4. Inconsistências e pontos de revisão','Achados ordenados por severidade. O tratamento é uma decisão registrada; não altera automaticamente documentos, títulos ou lançamentos.')
    byref={d['document_ref']:d for d in docs}
    ordered=sorted(findings,key=lambda f:SEVERITY_ORDER.get(f['severity'],9))
    story.append(table(['Severidade','NF / item','Regra / achado','Impacto','Ação recomendada','Tratamento'],[[STATUS.get(f['severity'],f['severity']),str(byref.get(f.get('document_ref'),{}).get('number') or 'Lote')+' / '+str(f.get('item_number') or '—'),f['rule_code']+'\n'+f['title']+'\n'+f['description'],f.get('impact'),f.get('recommended_action'),STATUS.get(f['status'],f['status'])+'\n'+(f.get('responsible') or '')+'\n'+(f.get('treatment') or '')] for f in ordered],[65,60,225,120,170,130]))
    story.append(p('Achados, evidências e tratamento',sub))
    grouped={}
    for f in ordered:
        key=(f['rule_code'],json.dumps(f.get('evidence',{}),sort_keys=True,ensure_ascii=False))
        group=grouped.setdefault(key,{'finding':f,'origins':[]})
        group['origins'].append(str(byref.get(f.get('document_ref'),{}).get('number') or 'Lote')+'/'+str(f.get('item_number') or '—'))
    for group in grouped.values():
        f=group['finding']
        story.append(p(f"{f['rule_code']} · mesma evidência em NF/item: {', '.join(group['origins'])}",sub))
        pairs=list(evidence_rows(f.get('evidence',{})))
        story.append(table(['Evidência / origem','Conteúdo'],pairs,[220,550]))
    chapter('5. Auditoria NCM × ClassTrib','Classificações encontradas versus parametrização do retrato. Ausência de catálogo, ambiguidade e divergência permanecem explícitas.')
    story.append(table(['NF / item','Produto','NCM / EX','CST / cClass encontrada','CST / cClass esperada','Situação'],[[str(d.get('number'))+' / '+str(i['item_number']),i.get('description'),(i.get('ncm') or '—')+' / '+(i.get('ex_code') or '—'),(i.get('actual_cst') or '—')+' / '+(i.get('actual_cclass_trib') or '—'),(i.get('expected_cst') or '—')+' / '+(i.get('expected_cclass_trib') or '—'),i.get('classification_status')] for d in docs if eligible(d) for i in d.get('items',[])],[65,225,90,115,115,160]))
    chapter('6. Conciliação econômica de produtos','Identidade por chassi, IMEI, série, lote, GTIN ou correspondência indicativa por NCM, descrição e unidade. Custos e margens são estimativas limitadas à amostra; entradas ausentes não comprovam irregularidade.')
    story.append(table(['Produto / identificador','Tipo / confiança','Qtd. entrada / saída','Custo estimado','Venda','Margem estimada','Situação'],[[r['identifier'],r['identity_type']+' / '+r['confidence'],str(r['input_quantity'])+' / '+str(r['output_quantity']),amount(r['estimated_cost']),amount(r['output_value']),amount(r['margin']),STATUS.get(r['status'],r['status'])] for r in result['reconciliation']],[185,115,85,90,85,90,120],(3,4,5)))
    chapter('7. Memória de cálculo por item','Valores originais, escriturados e recalculados são identificados separadamente. Arredondamento: Decimal ROUND_HALF_UP por componente, para centavos.')
    booked={b['id']:b for b in snapshot['bookkeeping']}
    if booked:
        story.append(table(['Documento','Original XML (R$)','Escriturado (R$)','Versão da origem'],[[d.get('number'),amount(d['total_value']) if d.get('origin')!='bookkeeping' else 'Indisponível',amount(Decimal(booked[d['bookkeeping_id']]['total_cents'])/100),booked[d['bookkeeping_id']]['version']] for d in docs if d.get('bookkeeping_id') in booked]))
    memory_rows=[];legacy_rows=[]
    for d in docs:
        for i in d.get('items',[]):
            valid=calculation_scope(job,d,i) in {'regular','legacy'}
            composition='; '.join(k+' '+amount(v) for k,v in i.get('tax_components',{}).items() if Decimal(str(v or 0))) or 'Sem componentes XML'
            memory_rows.append([str(d.get('number'))+'/'+str(i['item_number']),composition,amount(i.get('ibs_cbs_base_xml')),amount(i.get('ibs_cbs_base_recalculated')) if valid else 'Não recalculado',amount(Decimal(str(i.get('ibs_cbs_base_xml') or 0))-Decimal(str(i.get('ibs_cbs_base_recalculated') or 0))) if valid else 'Não comparável',amount(i.get('ibs_xml'))+' / '+(amount(i.get('ibs_recalculated')) if valid else '—'),amount(i.get('cbs_xml'))+' / '+(amount(i.get('cbs_recalculated')) if valid else '—')])
            for tax,m in i.get('details',{}).get('calculation_memory',{}).items():
                if isinstance(m,dict):legacy_rows.append([str(d.get('number'))+'/'+str(i['item_number']),tax,amount(m.get('base')),m.get('rate'),amount(m.get('original')),amount(m.get('recalculated')) if m.get('scope')=='ad_valorem' else 'Não recalculado',m.get('scope')])
    story.append(table(['NF / item','Componentes da base (R$)','Base XML','Base recálculo','Diferença','IBS XML / recálculo','CBS XML / recálculo'],memory_rows,[65,245,80,85,75,110,110]))
    if legacy_rows:
        story.append(p('Conferência aritmética de PIS e Cofins',sub))
        story.append(table(['NF / item','Tributo','Base','Alíquota (%)','XML','Recálculo','Cobertura'],legacy_rows,[80,90,120,110,120,120,130]))
    chapter('8. Fontes, método, qualidade e histórico')
    story.append(table(['Referência','Versão / uso'],[['Empresa',snapshot['company']['name']],['Motor / catálogo',result['engine']+' / '+(catalog.get('name') or 'Sem catálogo')],['Retrato SHA-256',result['snapshot_sha256']],['Catálogo SHA-256',result.get('catalog_sha256') or 'Não informado'],['Fonte primária','XML preservado; PDF auxiliar não participa dos cálculos.'],['Limitações','; '.join(snapshot['coverage']['limitations'])]],[190,580]))
    story.append(p('Arquivos, recusados e duplicidades',sub))
    story.append(table(['Arquivo / SHA-256','Situação','Diagnóstico'],[[o['name']+'\n'+o['sha256'],STATUS.get(o['status'],o['status']),o.get('error') or '—'] for o in result.get('file_outcomes',[])],[350,120,300]))
    excluded=[d for d in docs if not eligible(d)]
    if excluded:story.append(table(['Documentos excluídos dos totais','Situação','Valor original'],[[d.get('number'),STATUS.get(d['status'],d['status']),amount(d['total_value'])] for d in excluded]))
    from .auditor_catalogs import diagnostics
    issues=diagnostics(catalog.get('entries',[]),catalog.get('reference',{}))
    if issues:
        story.extend([p('Qualidade da parametrização',sub),table(['Linha / NCM','Diagnóstico'],[[str(r.get('source_row'))+' / '+str(r.get('ncm')),r['message']] for r in issues],[160,610])])
    else:
        story.append(p('Qualidade da parametrização: nenhum diagnóstico estrutural no retrato; não equivale a homologação fiscal.',small))
    if result.get('events'):story.extend([p('Eventos preservados',sub),table(['Campo','Valor'],list(evidence_rows(result['events'])),[230,540])])
    if job.get('attachments'):story.extend([p('PDFs vinculados por revisão',sub),table(['Documento','Arquivo','Revisor / justificativa'],[[a['document_ref'],a['file_id'],a['created_by']+' / '+a['reason']] for a in job['attachments']],[300,70,400])])
    story.extend([p('Histórico do processamento',sub),table(['Data / hora','Nível','Evento'],[[day(l['created_at'])+' '+l['created_at'][11:19],l['level'],l['message']] for l in job['logs']],[130,70,570])])
    def footer(canvas,doc):
        canvas.saveState();canvas.setStrokeColor(colors.HexColor(GRID));canvas.line(36,30,806,30)
        canvas.setFont('EscrituraSans',7);canvas.setFillColor(colors.HexColor(NAVY))
        name=snapshot['company']['name'][:65]
        canvas.drawString(36,19,f"{name} · Auditoria #{job['id']} · {day(job['start'])} a {day(job['end'])}")
        canvas.drawRightString(806,19,f'Página {doc.page}');canvas.restoreState()
    SimpleDocTemplate(output,pagesize=landscape(A4),leftMargin=36,rightMargin=36,topMargin=28,bottomMargin=43,title='Relatório Analítico e Sintético - Auditor Fiscal',author='Escritura Integrada').build(story,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()
