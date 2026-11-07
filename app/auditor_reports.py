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
        from .auditor_workbook import style_workbook
        style_workbook(wb,job)
        wb.save(output)
        return output.getvalue(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    if format!='pdf':raise DomainError('Selecione PDF ou Excel.')
    from .auditor_pdf import build_pdf
    return build_pdf(job), 'application/pdf'
