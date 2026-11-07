"""PDF e Excel gerados no servidor com os mesmos filtros/valores da consulta."""
from decimal import Decimal
from io import BytesIO
import json
from xml.sax.saxutils import escape
from .core import DomainError,decimal_text

LABELS={'date':'Data','document':'Documento','document_id':'Origem fiscal','journal_id':'Lançamento','title_id':'Título','item':'Item',
'document_version':'Versão do documento','rule_version':'Versão da regra','rule_id':'Regra','item_indices':'Itens selecionados','ledger_id':'Apuração','assessment_id':'Memória','period':'Competência','tax':'Tributo','partner_name':'Participante','partner_tax_id':'CPF/CNPJ',
'direction':'Operação','description':'Descrição','status':'Situação','model':'Modelo','series':'Série','cfop':'CFOP','ncm':'NCM','quantity':'Quantidade','unit':'Unidade',
'total_cents':'Total (R$)','item_total_cents':'Total itens (R$)','documents':'Documentos','items':'Itens','occurrences':'Ocorrências',
'code':'Código','message':'Diagnóstico','source':'Fonte','reason':'Fundamento','responsible':'Responsável','document_ids':'Documentos de origem',
'opening_credit_cents':'Crédito anterior (R$)','debit_cents':'Débitos (R$)','credit_cents':'Créditos (R$)','payable_cents':'A recolher (R$)',
'carry_credit_cents':'Crédito a transportar (R$)','base_cents':'Base (R$)','result_cents':'Resultado (R$)','rate':'Alíquota (%)',
'effect':'Natureza','rounding':'Arredondamento','formula':'Fórmula','account_name':'Conta','access_code':'Acesso','classifier':'Classificador',
'cost_center_name':'Centro de custo','history':'Histórico','amount_cents':'Valor (R$)','paid_cents':'Principal baixado (R$)',
'balance_cents':'Saldo (R$)','cash_cents':'Caixa (R$)','due_date':'Vencimento','issue_date':'Emissão','kind':'Tipo','opening_cents':'Saldo inicial (R$)','closing_cents':'Saldo final (R$)'}
for tax in ['icms','ipi','iss','pis','cofins','ibs','cbs']:
    LABELS[tax+'_cents']=tax.upper()+' declarado (R$)';LABELS[tax+'_base_cents']='Base '+tax.upper()+' (R$)';LABELS[tax+'_informed_documents']='Documentos com '+tax.upper()
VALUES={'incoming':'Entrada','outgoing':'Saída','payable':'A pagar','receivable':'A receber','pending':'Pendente','reviewed':'Conferido','booked':'Escriturado','debit':'Débito','credit':'Crédito','open':'Aberto','partial':'Parcial','settled':'Baixado','cancelled':'Cancelado'}

def display(key,value):
    if value is None:return ''
    if key.endswith('_cents'):return decimal_text(value).replace('.',',')
    if isinstance(value,(list,dict)):return json.dumps(value,ensure_ascii=False)
    if isinstance(value,bool):return 'Sim' if value else 'Não'
    return VALUES.get(str(value),str(value))

REPORT_TITLES={'diary':'Diário Geral','consolidated-diary':'Diário Consolidado',
    'ledger':'Razão','trial-balance':'Balancete','cost-centers':'Movimentos por centro de custo',
    'balance-sheet':'Balanço patrimonial','income-statement':'Demonstração do resultado',
    'fiscal-book':'Livro auxiliar fiscal','financial':'Títulos por vencimento',
    'cash-flow':'Caixa realizado','partners':'Conciliação de clientes e fornecedores'}


def export_report(result,kind):
    rows=result['rows'];keys=list(dict.fromkeys(k for r in rows for k in r))
    title=result.get('title') or REPORT_TITLES.get(result['kind'],result['kind']);output=BytesIO()
    if kind=='xlsx':
        from openpyxl import Workbook
        from openpyxl.styles import Font,PatternFill,Alignment
        from openpyxl.utils import get_column_letter
        wb=Workbook();meta=wb.active;meta.title='Conferência';sheet=wb.create_sheet('Dados');raw=wb.create_sheet('Valores em centavos')
        for pair in [('Relatório',title),('Empresa',result['company_name']),('Início',result['start']),('Fim',result['end']),('Escopo',result['scope_note']),('Filtros',json.dumps(result.get('filters',{}),ensure_ascii=False))]:meta.append(pair)
        meta.append(['Totais conferíveis',''])
        for k,v in result['totals'].items():meta.append([LABELS.get(k,k),display(k,v)])
        for ws in [sheet,raw]:ws.append([LABELS.get(k,k) if ws is sheet else k for k in keys])
        for row in rows:
            for ws in [sheet,raw]:
                values=[]
                for k in keys:
                    v=row.get(k)
                    if k.endswith('_cents') and v is not None:values.append(Decimal(v)/100 if ws is sheet else v)
                    elif isinstance(v,(int,float)) and not isinstance(v,bool):values.append(v)
                    else:values.append(display(k,v))
                ws.append(values)
                for cell in ws[ws.max_row]:
                    if isinstance(cell.value,str):cell.data_type='s'  # texto do usuário nunca vira fórmula
                    cell.alignment=Alignment(vertical='top',wrap_text=True)
                    if ws is sheet and keys[cell.column-1].endswith('_cents'):cell.number_format='#,##0.00;[Red]-#,##0.00'
        for ws in wb:
            ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions if ws is not meta else 'A1:B1'
            for cell in ws[1]:cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='225F57')
            for col in range(1,ws.max_column+1):ws.column_dimensions[get_column_letter(col)].width=24 if col>1 else 20
        meta.column_dimensions['B'].width=100
        for row in meta:
            for cell in row:
                if isinstance(cell.value,str):cell.data_type='s'
                cell.alignment=Alignment(wrap_text=True,vertical='top')
        wb.save(output);return output.getvalue(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    if kind!='pdf':raise DomainError('Formato deve ser PDF ou Excel.')
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,LongTable,TableStyle,PageBreak
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib.pagesizes import A4,landscape
    from reportlab.lib import colors
    from pathlib import Path
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import reportlab
    fonts=Path(reportlab.__file__).parent/'fonts'
    if 'EscrituraSans' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('EscrituraSans',str(fonts/'Vera.ttf')))
        pdfmetrics.registerFont(TTFont('EscrituraSans-Bold',str(fonts/'VeraBd.ttf')))
        pdfmetrics.registerFontFamily('EscrituraSans',normal='EscrituraSans',bold='EscrituraSans-Bold')
    styles=getSampleStyleSheet()
    for style in styles.byName.values():style.fontName='EscrituraSans-Bold' if 'Heading' in style.name else 'EscrituraSans'
    small=ParagraphStyle('ReportCell',fontName='EscrituraSans',fontSize=7.5,leading=10)
    body=ParagraphStyle('ReportBody',parent=styles['BodyText'],fontSize=9,leading=12)
    def para(value,style=small):return Paragraph(escape(str(value)),style)
    pagesize=landscape(A4);width=pagesize[0]-60
    doc=SimpleDocTemplate(output,pagesize=pagesize,leftMargin=30,rightMargin=30,topMargin=35,bottomMargin=30,title=title,author='Escritura Integrada')
    story=[para(title,styles['Heading1']),para(result['company_name'],styles['Heading2']),para(f"Período: {result['start']} a {result['end']}",body),Spacer(1,8),para(result['scope_note'],body),Spacer(1,10)]
    if result.get('filters'):story+=[para('Filtros: '+json.dumps(result['filters'],ensure_ascii=False),body),Spacer(1,8)]
    totals=[[para(LABELS.get(k,k)),para(display(k,v))] for k,v in result['totals'].items()]
    if totals:
        table=LongTable(totals,colWidths=[width*.7,width*.3]);table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#eef5f3')),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),5)]));story.extend([table,Spacer(1,16)])
    anchors=[k for k in ['document','date','account_name','partner_name','tax'] if k in keys][:2]
    rest=[k for k in keys if k not in anchors];blocks=[anchors+rest[i:i+5] for i in range(0,len(rest),5)] or [anchors]
    for index,columns in enumerate(blocks):
        if not columns:continue
        if index:story+=[PageBreak(),para(title+' · continuação',styles['Heading2']),para(result['company_name'],body),Spacer(1,10)]
        content=[[para(LABELS.get(k,k)) for k in columns]]+[[para(display(k,r.get(k))) for k in columns] for r in rows]
        table=LongTable(content,colWidths=[width/len(columns)]*len(columns),repeatRows=1,hAlign='LEFT',splitByRow=1,splitInRow=1)
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dceee7')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f5f7f8')]),('GRID',(0,0),(-1,-1),.25,colors.HexColor('#d5dfe2')),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]));story.append(table)
    if not rows:story.append(para('Nenhum registro nos filtros selecionados.',body))
    def footer(canvas,document):
        canvas.setFont('EscrituraSans',8);canvas.drawString(30,15,'Escritura Integrada · relatório auxiliar');canvas.drawRightString(pagesize[0]-30,15,f'Página {document.page}')
    doc.build(story,onFirstPage=footer,onLaterPages=footer);return output.getvalue(),'application/pdf'
