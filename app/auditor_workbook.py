"""Planilhas operacionais equivalentes às seções do Auditor original, com células numéricas."""
from decimal import Decimal
from .auditor_results import analytics


def enrich_workbook(wb,job):
    docs=job['result']['documents'];findings=job['findings'];snapshot=job['snapshot'];catalog=snapshot.get('catalog') or {}
    def number(v):return float(Decimal(str(v))) if v is not None and v!='' else None
    def calc(item,field):return number(item.get(field)) if item.get('calculation_scope','legacy') in {'regular','legacy'} else None
    def table(name,headers,rows):
        ws=wb.create_sheet(name);ws.append(headers)
        for row in rows:ws.append(row)
        ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
        ws.sheet_view.showGridLines=False;ws.print_title_rows='1:1';ws.sheet_properties.pageSetUpPr.fitToPage=True
        ws.page_setup.orientation='landscape';ws.page_setup.paperSize=ws.PAPERSIZE_A4;ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=0
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value,(float,int)):cell.number_format='#,##0.00'
        return ws
    a=analytics(docs,findings)
    table('Resumo Executivo',['Indicador','Valor'],[[k,number(v) if isinstance(v,(str,int,float)) else v] for k,v in a['overview'].items()]+[['Recusados',job['result'].get('outcome',{}).get('rejected',0)],['Duplicidades',job['result'].get('outcome',{}).get('duplicates',0)]])
    table('Notas - Sintético',['NF','Chave','Modelo','Emissão','Escrituração','Direção','Emitente','Destinatário','Valor NF','Base IBS/CBS','IBS','CBS','Itens','Situação','Origem'],[[d.get('number'),d.get('access_key'),d.get('model'),d.get('issued_at'),d.get('posting_date'),d['direction'],d.get('issuer_tax_id'),d.get('recipient_tax_id'),*[number(d.get(k)) for k in ('total_value','ibs_cbs_base','ibs_value','cbs_value')],len(d['items']),d['status'],d.get('origin','xml')] for d in docs])
    pairs=[(d,i) for d in docs for i in d['items']]
    components=['vProd','vServ','vFrete','vSeg','vOutro','vII','vDesc','vPIS','vCOFINS','vICMS','vICMSUFDest','vFCP','vFCPUFDest','vICMSMono','vISSQN','vIS']
    table('Itens - Analítico',['NF','Item','Código','Produto','GTIN','NCM','EX','CFOP','Quantidade','Unidade','CST','cClassTrib','CST esperada','cClass esperada','Valor produto','Situação'],[[d['number'],i['item_number'],i.get('product_code'),i.get('description'),i.get('details',{}).get('ean'),i.get('ncm'),i.get('ex_code'),i.get('cfop'),number(i.get('details',{}).get('quantity')),i.get('details',{}).get('unit'),i.get('actual_cst'),i.get('actual_cclass_trib'),i.get('expected_cst'),i.get('expected_cclass_trib'),number(i.get('product_value')),i.get('classification_status')] for d,i in pairs])
    table('Tributos',['NF','Item','NCM','CST ICMS','ICMS','PIS','COFINS','FCP','II','ISSQN'],[[d['number'],i['item_number'],i.get('ncm'),i.get('details',{}).get('icms_cst'),*[number(i.get('tax_components',{}).get(k)) for k in ('vICMS','vPIS','vCOFINS','vFCP','vII','vISSQN')]] for d,i in pairs])
    table('IBS e CBS',['NF','Item','NCM','CST','cClassTrib','Base XML','Base assistida','IBS XML','IBS recálculo','CBS XML','CBS recálculo','Cobertura'],[[d['number'],i['item_number'],i.get('ncm'),i.get('actual_cst'),i.get('actual_cclass_trib'),number(i.get('ibs_cbs_base_xml')),calc(i,'ibs_cbs_base_recalculated'),number(i.get('ibs_xml')),calc(i,'ibs_recalculated'),number(i.get('cbs_xml')),calc(i,'cbs_recalculated'),i.get('calculation_scope','legacy')] for d,i in pairs])
    table('Memória de Cálculo',['NF','Item',*components,'Base XML','Base assistida UB16-10','Arredondamento','Cobertura'],[[d['number'],i['item_number'],*[number(i.get('tax_components',{}).get(k)) for k in components],number(i.get('ibs_cbs_base_xml')),calc(i,'ibs_cbs_base_recalculated'),'ROUND_HALF_UP por componente; 2 casas',i.get('calculation_scope','legacy')] for d,i in pairs])
    memory=[]
    for d,i in pairs:
        for tax,m in i.get('details',{}).get('calculation_memory',{}).items():
            if isinstance(m,dict):memory.append([d['number'],i['item_number'],tax,number(m.get('base')),number(m.get('rate')),number(m.get('original')),number(m.get('recalculated')) if m.get('scope')=='ad_valorem' else None,m.get('scope')])
    table('Memória PIS Cofins',['NF','Item','Tributo','Base','Alíquota (%)','Valor XML','Recálculo','Cobertura'],memory)
    table('Entradas x Saídas',['Produto / identificador','Tipo','Confiança','NCM','Unidade','Qtd. entrada','Qtd. saída','Valor entrada','Valor saída','Custo estimado','Margem estimada','Situação'],[[r['identifier'],r['identity_type'],r['confidence'],r.get('ncm'),r.get('unit'),*[number(r.get(k)) for k in ('input_quantity','output_quantity','input_value','output_value','estimated_cost','margin')],r['status']] for r in job['result']['reconciliation']])
    table('Inconsistências',['Documento','Item','Severidade','Categoria','Regra','Título','Descrição','Impacto','Ação recomendada','Situação','Responsável','Tratamento'],[[f.get(k) for k in ('document_ref','item_number','severity','category','rule_code','title','description','impact','recommended_action','status','responsible','treatment')] for f in findings])
    table('Duplicidades e Eventos',['Origem','Tipo','Situação','Descrição'],[[f.get('document_ref'),f['rule_code'],f['severity'],f['description']] for f in findings if f['category']=='duplicate']+[[e.get('access_key'),e.get('event_type'),e.get('status_code'),e.get('description')] for e in job['result']['events']])
    table('Auditoria NCM-ClassTrib',['NF','Item','Produto','NCM','EX','CST encontrada','cClass encontrada','CST esperada','cClass esperada','Situação','Estratégia','Linha origem'],[[d['number'],i['item_number'],i.get('description'),i.get('ncm'),i.get('ex_code'),i.get('actual_cst'),i.get('actual_cclass_trib'),i.get('expected_cst'),i.get('expected_cclass_trib'),i.get('classification_status'),i.get('catalog_match',{}).get('strategy'),i.get('catalog_match',{}).get('parameter_source_row')] for d,i in pairs])
    from .auditor_catalogs import diagnostics
    issues=diagnostics(catalog.get('entries',[]),catalog.get('reference',{}))
    table('Qualidade Parametrização',['Severidade','Código','NCM','EX','Linha','Diagnóstico'],[[r.get(k) for k in ('severity','code','ncm','ex_code','source_row','message')] for r in issues])
    table('Parametrização Utilizada',['NCM','EX','CST esperada','cClass esperada','Linha','Versão','SHA-256'],[[i.get('ncm'),i.get('ex_code'),i.get('expected_cst'),i.get('expected_cclass_trib'),i.get('catalog_match',{}).get('parameter_source_row'),catalog.get('name'),catalog.get('sha256')] for d,i in pairs])
    table('Arquivos processados',['Nome','SHA-256','Situação','Diagnóstico'],[[o.get(k) for k in ('name','sha256','status','error')] for o in job['result'].get('file_outcomes',[])])
    table('Fontes e Método',['Campo','Descrição'],[['Empresa',snapshot['company']['name']],['CNPJ',snapshot['company']['tax_id']],['Período',job['start']+' a '+job['end']],['Motor',snapshot['engine']],['Catálogo',catalog.get('name')],['Fonte',catalog.get('source')],['SHA-256',catalog.get('sha256')],['Arredondamento','Decimal ROUND_HALF_UP; centavos por componente'],['Cobertura','; '.join(snapshot['coverage']['limitations'])],['Efeitos','Auditoria e tratamento de achados não alteram a escrituração.']])
