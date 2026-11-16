"""PDF e Excel gerados no servidor com os mesmos filtros/valores da consulta."""
from decimal import Decimal
from io import BytesIO
import json
from .core import DomainError,decimal_text

LABELS={'partner_state':'UF do participante','partner_ie':'Inscrição estadual do participante','company_ie':'Inscrição estadual','date':'Data','document':'Documento','document_id':'Origem fiscal','journal_id':'Lançamento','title_id':'Título','item':'Item',
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

REPORT_TITLES={'bank-movements':'Movimentação bancária','diary':'Diário Geral','consolidated-diary':'Diário Consolidado',
    'ledger':'Razão','trial-balance':'Balancete','cost-centers':'Movimentos por centro de custo',
    'balance-sheet':'Balanço patrimonial','income-statement':'Demonstração do resultado',
    'fiscal-book':'Livro auxiliar fiscal','financial':'Títulos por vencimento',
    'cash-flow':'Caixa realizado','partners':'Conciliação de clientes e fornecedores'}


def export_report(result,kind):
    rows=result['rows'];keys=list(dict.fromkeys(k for r in rows for k in r))
    labels=dict(LABELS)
    if kind=='pdf':
        from .report_models import resolve_model_id,report_model_pdf
        model=resolve_model_id(result['kind'])
        if model:return report_model_pdf(result,model)
        from .accounting_report_models import accounting_pdf
        return accounting_pdf(result)
    if result.get('row_scope')=='analytical_posting_lines':
        from .fiscal_report_models import ANALYTICAL_LABELS
        labels.update(ANALYTICAL_LABELS)
        labels['total_cents']='Valor contábil da linha (R$)'
    title=result.get('title') or REPORT_TITLES.get(result['kind'],result['kind']);output=BytesIO()
    if kind=='xlsx':
        from openpyxl import Workbook
        from openpyxl.styles import Font,PatternFill,Alignment
        from openpyxl.utils import get_column_letter
        wb=Workbook();meta=wb.active;meta.title='Conferência';sheet=wb.create_sheet('Dados');raw=wb.create_sheet('Valores em centavos')
        for pair in [('Relatório',title),('Empresa',result['company_name']),('Início',result['start']),('Fim',result['end']),('Escopo',result['scope_note']),('Filtros',json.dumps(result.get('filters',{}),ensure_ascii=False))]:meta.append(pair)
        meta.append(['Totais conferíveis',''])
        for k,v in result['totals'].items():meta.append([labels.get(k,k),display(k,v)])
        for ws in [sheet,raw]:ws.append([labels.get(k,k) if ws is sheet else k for k in keys])
        for row in rows:
            for ws in [sheet,raw]:
                values=[]
                for k in keys:
                    v=row.get(k)
                    if k.endswith('_cents') and v is not None:values.append(Decimal(v)/100 if ws is sheet else v)
                    elif isinstance(v,(int,float)) and not isinstance(v,bool):values.append(v)
                    else:
                        rendered=display(k,v)
                        if k=='declared_classifications' and result.get('row_scope')=='analytical_posting_lines' and len(rendered)>32000:
                            rendered='Classificações completas na aba Classificações declaradas (excede o limite de uma célula Excel). '
                        values.append(rendered)
                ws.append(values)
                for cell in ws[ws.max_row]:
                    if isinstance(cell.value,str):cell.data_type='s'  # texto do usuário nunca vira fórmula
                    cell.alignment=Alignment(vertical='top',wrap_text=True)
                    if ws is sheet and keys[cell.column-1].endswith('_cents'):cell.number_format='#,##0.00;[Red]-#,##0.00'
        if result.get('row_scope')=='analytical_posting_lines':
            headers=result.get('document_headers') or []
            header_keys=list(dict.fromkeys(k for r in headers for k in r))
            header_sheet=wb.create_sheet('Cabeçalhos documentos')
            header_sheet.append([LABELS.get(k,k) for k in header_keys])
            for row in headers:
                header_sheet.append([Decimal(row[k])/100 if k.endswith('_cents') and row.get(k) is not None else display(k,row.get(k)) for k in header_keys])
                for cell in header_sheet[header_sheet.max_row]:
                    if isinstance(cell.value,str):cell.data_type='s'
                    if header_keys[cell.column-1].endswith('_cents'):cell.number_format='#,##0.00;[Red]-#,##0.00'
            classes_sheet=wb.create_sheet('Classificações declaradas')
            class_keys=['document_id','document','line','posting_group','cfop','cst_icms','csosn','origin','rate']
            classes_sheet.append([labels.get(k,k) for k in class_keys])
            for row in rows:
                for classification in row.get('declared_classifications',[]):
                    record={k:row.get(k) for k in ['document_id','document','line','posting_group']} | classification
                    classes_sheet.append([display(k,record.get(k)) for k in class_keys])
                    for cell in classes_sheet[classes_sheet.max_row]:
                        if isinstance(cell.value,str):cell.data_type='s'
        for ws in wb:
            ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions if ws is not meta else 'A1:B1'
            for cell in ws[1]:cell.font=Font(bold=True,color='000000');cell.fill=PatternFill('solid',fgColor='E8E8E8')
            for col in range(1,ws.max_column+1):ws.column_dimensions[get_column_letter(col)].width=24 if col>1 else 20
        meta.column_dimensions['B'].width=100
        for row in meta:
            for cell in row:
                if isinstance(cell.value,str):cell.data_type='s'
                cell.alignment=Alignment(wrap_text=True,vertical='top')
        wb.save(output);return output.getvalue(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    raise DomainError('Formato deve ser PDF ou Excel.')

LABELS.update(document_state='Estado documental', cancellation_source='Fonte do cancelamento', cancellation_responsible='Responsável pelo cancelamento', cancellation_reason='Motivo do cancelamento', book_cancellation='Cancelamento conforme livro validado')

LABELS.update(bank_account='Conta bancária', bank_id='Movimento de origem', reference='Referência', source_hash='Hash da origem', external_id='Identificador bancário', inflow_cents='Entradas (R$)', outflow_cents='Saídas (R$)', net_movement_cents='Movimento líquido (R$)')
