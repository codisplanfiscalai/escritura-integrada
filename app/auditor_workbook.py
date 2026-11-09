"""Planilhas operacionais equivalentes às seções do Auditor original, com células numéricas."""
from decimal import Decimal
import json
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
    table('Itens - Analítico',['NF','Item','Código','Produto','GTIN','NCM','EX','CFOP','Quantidade','Unidade','CST','cClassTrib','CST esperada','cClass esperada','Valor produto','Situação'],[[d['number'],i['item_number'],i.get('product_code'),i.get('description'),(i.get('details',{}).get('ean_taxable') or i.get('details',{}).get('ean')),i.get('ncm'),i.get('ex_code'),i.get('cfop'),number(i.get('details',{}).get('quantity')),i.get('details',{}).get('unit'),i.get('actual_cst'),i.get('actual_cclass_trib'),i.get('expected_cst'),i.get('expected_cclass_trib'),number(i.get('product_value')),i.get('classification_status')] for d,i in pairs])
    table('Tributos',['NF','Item','NCM','CST ICMS','ICMS','PIS','COFINS','FCP','II','ISSQN'],[[d['number'],i['item_number'],i.get('ncm'),i.get('details',{}).get('icms_cst'),*[number(i.get('tax_components',{}).get(k)) for k in ('vICMS','vPIS','vCOFINS','vFCP','vII','vISSQN')]] for d,i in pairs])
    table('IBS e CBS',['NF','Item','NCM','CST','cClassTrib','Base XML','Base assistida','IBS XML','IBS recálculo','CBS XML','CBS recálculo','Cobertura'],[[d['number'],i['item_number'],i.get('ncm'),i.get('actual_cst'),i.get('actual_cclass_trib'),number(i.get('ibs_cbs_base_xml')),calc(i,'ibs_cbs_base_recalculated'),number(i.get('ibs_xml')),calc(i,'ibs_recalculated'),number(i.get('cbs_xml')),calc(i,'cbs_recalculated'),i.get('calculation_scope','legacy')] for d,i in pairs])
    table('Memória de Cálculo',['NF','Item',*components,'Base XML','Base assistida UB16-10','Arredondamento','Cobertura'],[[d['number'],i['item_number'],*[number(i.get('tax_components',{}).get(k)) for k in components],number(i.get('ibs_cbs_base_xml')),calc(i,'ibs_cbs_base_recalculated'),'ROUND_HALF_UP por componente; 2 casas',i.get('calculation_scope','legacy')] for d,i in pairs])
    memory=[]
    for d,i in pairs:
        for tax,m in i.get('details',{}).get('calculation_memory',{}).items():
            if isinstance(m,dict):memory.append([d['number'],i['item_number'],tax,number(m.get('base')),number(m.get('rate')),number(m.get('original')),number(m.get('recalculated')) if m.get('scope')=='ad_valorem' else None,m.get('scope')])
    table('Memória PIS Cofins',['NF','Item','Tributo','Base','Alíquota (%)','Valor XML','Recálculo','Cobertura'],memory)
    table('Entradas x Saídas',['Produto / identificador','Tipo','Confiança','NCM','Unidade','Qtd. entrada','Qtd. saída','Valor entrada','Valor saída','Custo estimado','Margem estimada','Situação'],[[r['identifier'],r['identity_type'],r['confidence'],r.get('ncm'),r.get('unit'),*[number(r.get(k)) for k in ('input_quantity','output_quantity','input_value','output_value','estimated_cost','margin')],r['status']] for r in job['result']['reconciliation']])
    byref={d['document_ref']:d for d in docs};bykey={d.get('access_key'):d for d in docs if d.get('access_key')}
    evidence=lambda value:json.dumps(value,ensure_ascii=False,sort_keys=True,default=str)
    table('Inconsistências',['Documento','Item','Severidade','Categoria','Regra','Título','Descrição','Impacto','Ação recomendada','Situação','Responsável','Tratamento','NF','Chave','Evidência'],[[f.get(k) for k in ('document_ref','item_number','severity','category','rule_code','title','description','impact','recommended_action','status','responsible','treatment')]+[byref.get(f.get('document_ref'),{}).get('number','Lote'),byref.get(f.get('document_ref'),{}).get('access_key'),evidence(f.get('evidence',{}))] for f in findings])
    occurrences=[[f.get('document_ref'),f['rule_code'],f['severity'],f['description'],'Possível duplicidade',byref.get(f.get('document_ref'),{}).get('number','Lote'),byref.get(f.get('document_ref'),{}).get('access_key'),evidence(f.get('evidence',{}))] for f in findings if f['category']=='duplicate']
    occurrences += [[e.get('access_key'),e.get('event_type'),e.get('status_code'),e.get('description'),'Evento',bykey.get(e.get('access_key'),{}).get('number'),e.get('access_key'),e.get('registered_at') or e.get('event_date') or evidence(e)] for e in job['result']['events']]
    table('Duplicidades e Eventos',['Origem','Tipo','Situação','Descrição','Categoria da ocorrência','NF','Chave','Data/Evidência'],occurrences)
    table('Auditoria NCM-ClassTrib',['NF','Item','Produto','NCM','EX','CST encontrada','cClass encontrada','CST esperada','cClass esperada','Situação','Estratégia','Linha origem'],[[d['number'],i['item_number'],i.get('description'),i.get('ncm'),i.get('ex_code'),i.get('actual_cst'),i.get('actual_cclass_trib'),i.get('expected_cst'),i.get('expected_cclass_trib'),i.get('classification_status'),i.get('catalog_match',{}).get('strategy'),i.get('catalog_match',{}).get('parameter_source_row')] for d,i in pairs])
    from .auditor_catalogs import diagnostics
    issues=diagnostics(catalog.get('entries',[]),catalog.get('reference',{}))
    entries=catalog.get('entries',[])
    table('Qualidade Parametrização',['Severidade','Código','NCM','EX','Linha','Diagnóstico','Aba','Contexto'],[[r.get(k) for k in ('severity','code','ncm','ex_code','source_row','message')]+[entries[r['index']].get('source_sheet'),evidence(entries[r['index']])] for r in issues])
    used_parameters=list(dict.fromkeys((i.get('ncm'),i.get('ex_code'),i.get('expected_cst'),i.get('expected_cclass_trib'),i.get('catalog_match',{}).get('parameter_source_row'),catalog.get('name'),catalog.get('sha256')) for d,i in pairs))
    table('Parametrização Utilizada',['NCM','EX','CST esperada','cClass esperada','Linha','Versão','SHA-256'],used_parameters)
    table('Arquivos processados',['Nome','SHA-256','Situação','Diagnóstico'],[[o.get(k) for k in ('name','sha256','status','error')] for o in job['result'].get('file_outcomes',[])])
    table('Fontes e Método',['Campo','Descrição'],[['Empresa',snapshot['company']['name']],['CNPJ',snapshot['company']['tax_id']],['Período',job['start']+' a '+job['end']],['Motor',snapshot['engine']],['Catálogo',catalog.get('name')],['Fonte',catalog.get('source')],['SHA-256',catalog.get('sha256')],['Arredondamento','Decimal ROUND_HALF_UP; centavos por componente'],['Cobertura','; '.join(snapshot['coverage']['limitations'])],['Efeitos','Auditoria e tratamento de achados não alteram a escrituração.']])


def style_workbook(wb,job):
    """Restitui o painel e as colunas do modelo original sem remover abas legadas."""
    from openpyxl.styles import Font,PatternFill,Alignment,Border,Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table,TableStyleInfo
    from openpyxl.formatting.rule import CellIsRule
    from .auditor_presentation import COMPONENTS,eligible,SEVERITY_ORDER
    from .auditor_reports import STATUS
    from .auditor_results import analytics
    from decimal import Decimal
    docs=job['result']['documents'];pairs=[(d,i) for d in docs for i in d.get('items',[])]
    def num(v):return float(Decimal(str(v))) if v not in (None,'') else None
    def calculated(i,k):return num(i.get(k)) if i.get('calculation_scope','legacy') in {'regular','legacy'} else None
    def difference(i,a,b):return num(Decimal(str(i.get(a) or 0))-Decimal(str(i.get(b) or 0))) if calculated(i,b) is not None else None
    def append_columns(name,headers,rows):
        ws=wb[name];start=ws.max_column+1
        for c,h in enumerate(headers,start):ws.cell(1,c,h)
        for r,values in enumerate(rows,2):
            for c,v in enumerate(values,start):ws.cell(r,c,v)
    append_columns('Itens - Analítico',COMPONENTS+['Base XML','Base recalculada','Diferença base','IBS XML','IBS recálculo','CBS XML','CBS recálculo','Cobertura','Elegível nos totais'],[[*[num(i.get('tax_components',{}).get(k,0)) for k in COMPONENTS],num(i.get('ibs_cbs_base_xml')),calculated(i,'ibs_cbs_base_recalculated'),difference(i,'ibs_cbs_base_xml','ibs_cbs_base_recalculated'),num(i.get('ibs_xml')),calculated(i,'ibs_recalculated'),num(i.get('cbs_xml')),calculated(i,'cbs_recalculated'),i.get('calculation_scope','legacy'),'Sim' if eligible(d) else 'Não'] for d,i in pairs])
    append_columns('Tributos',['CST PIS','CST COFINS'],[[i.get('details',{}).get('pis_cst'),i.get('details',{}).get('cofins_cst')] for d,i in pairs])
    append_columns('IBS e CBS',['Diferença base','Diferença IBS','Diferença CBS','Situação'],[[difference(i,a,b) for a,b in [('ibs_cbs_base_xml','ibs_cbs_base_recalculated'),('ibs_xml','ibs_recalculated'),('cbs_xml','cbs_recalculated')]]+[i.get('classification_status')] for d,i in pairs])
    append_columns('Memória de Cálculo',['Diferença base'],[[difference(i,'ibs_cbs_base_xml','ibs_cbs_base_recalculated')] for d,i in pairs])
    append_columns('Notas - Sintético',['Elegível nos totais'],[['Sim' if eligible(d) else 'Não'] for d in docs])
    operational=['Resumo Executivo','Notas - Sintético','Itens - Analítico','Tributos','IBS e CBS','Memória de Cálculo','Memória PIS Cofins','Entradas x Saídas','Inconsistências','Auditoria NCM-ClassTrib','Duplicidades e Eventos','Qualidade Parametrização','Parametrização Utilizada','Arquivos processados','Fontes e Método']
    for name in reversed(operational):wb.move_sheet(wb[name],offset=-wb.index(wb[name]))
    navy='12324A';teal='225F57';light='EDF3F6';grid=Side(style='thin',color='D8E1E7')
    for index,ws in enumerate(wb):
        if ws.title not in operational:
            # Formato técnico anterior permanece disponível para compatibilidade.
            ws.sheet_state='hidden'
            continue
        if ws.title=='Resumo Executivo':continue
        ws.sheet_properties.tabColor=teal;ws.sheet_view.showGridLines=False
        ws.freeze_panes='D2' if ws.max_column>10 else 'A2'
        ws.sheet_properties.pageSetUpPr.fitToPage=True;ws.page_setup.orientation='landscape';ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=0
        ws.print_title_rows='1:1';ws.print_options.horizontalCentered=True
        ws.oddFooter.center.text=f"Auditoria #{job['id']} · Página &P de &N"
        ws.oddHeader.center.text=job['snapshot']['company']['name'].replace('&','&&')
        headers=[str(c.value or '') for c in ws[1]]
        ws.row_dimensions[1].height=32
        for col,h in enumerate(headers,1):
            ws.column_dimensions[get_column_letter(col)].width=55 if h in {'Descrição','Evidência','Ação recomendada','Tratamento','Diagnóstico','Mensagem','Contexto','Data/Evidência'} else 46 if 'Chave' in h or 'SHA-256' in h else 38 if h in {'Produto','Produto / identificador','Nome'} else 19 if any(x in h for x in ['Valor','Base','recálculo','Diferença','Emissão','Situação']) else 15
        for row in ws:
            for cell in row:
                cell.border=Border(bottom=grid);cell.alignment=Alignment(vertical='top',wrap_text=True)
                cell.font=Font(name='Calibri',size=10,color=navy)
                if cell.row==1:cell.fill=PatternFill('solid',fgColor=teal);cell.font=Font(name='Calibri',size=10,bold=True,color='FFFFFF')
                elif cell.row%2==0:cell.fill=PatternFill('solid',fgColor=light)
                if isinstance(cell.value,str):cell.data_type='s'
                if isinstance(cell.value,(float,int)):
                    h=headers[cell.column-1]
                    cell.number_format='0' if h in {'Item','Itens','Linha','Linha origem'} else '#,##0.000000' if 'Qtd.' in h or h=='Quantidade' else '#,##0.00'
                    cell.alignment=Alignment(vertical='top',horizontal='right')
                if cell.row>1 and cell.value in ('critical','high','negative_margin'):
                    cell.fill=PatternFill('solid',fgColor='FBE7E5');cell.font=Font(color='9B1C13',bold=True)
        if ws.max_row>1 and len(set(headers))==len(headers):
            t=Table(displayName=f'Auditor{index}',ref=ws.dimensions);t.tableStyleInfo=TableStyleInfo(name='TableStyleMedium2',showRowStripes=True);ws.add_table(t)
        for c,h in enumerate(headers,1):
            if 'Diferença' in h:
                ws.conditional_formatting.add(f'{get_column_letter(c)}2:{get_column_letter(c)}{max(2,ws.max_row)}',CellIsRule(operator='notEqual',formula=['0'],fill=PatternFill('solid',fgColor='FFF1D1')))
    ws=wb['Resumo Executivo'];ws.delete_rows(1,ws.max_row);ws.auto_filter.ref=None;ws.freeze_panes='A11'
    ws.sheet_view.showGridLines=False
    for c in 'ABCDEFGH':ws.column_dimensions[c].width=21
    def merged(r,c,end,value,bg=light,size=11,color=navy,bold=False):
        ws.merge_cells(start_row=r,start_column=c,end_row=r,end_column=end)
        cell=ws.cell(r,c,value);cell.fill=PatternFill('solid',fgColor=bg);cell.font=Font(name='Calibri',size=size,color=color,bold=bold);cell.alignment=Alignment(vertical='center',wrap_text=True)
        if isinstance(value,str):cell.data_type='s'
        return cell
    merged(1,1,8,'Relatório Analítico e Sintético · Auditor Fiscal',navy,21,'FFFFFF',True);ws.row_dimensions[1].height=42
    merged(2,1,8,f"{job['snapshot']['company']['name']} · {job['start']} a {job['end']} · Auditoria #{job['id']}",navy,11,'FFFFFF');ws.row_dimensions[2].height=30
    stats=analytics(docs,job['findings']);a=stats['overview']
    kpis=[('Documentos elegíveis',a['documents']),('Valor dos documentos',num(a['total_value'])),('Base IBS/CBS informada',num(a['ibs_cbs_base'])),('IBS + CBS informados',num(Decimal(a['ibs_value'])+Decimal(a['cbs_value']))),('Entradas',a['input_count']),('Saídas',a['output_count']),('Itens / classificação OK',f"{a['items']} / {stats['classification_ok']}"),('Achados abertos / em revisão',stats['open_findings'])]
    for index,(label,value) in enumerate(kpis):
        r=4+(index//4)*3;c=(index%4)*2+1
        label_cell=merged(r,c,c+1,label,bold=True);ws.row_dimensions[r].height=28
        v=merged(r+1,c,c+1,value,'FBE7E5' if index==7 else light,20,bold=True);ws.row_dimensions[r+1].height=38
        for cell in (label_cell,v):cell.alignment=Alignment(horizontal='center',vertical='center',wrap_text=True)
        if index in {1,2,3}:v.number_format='"R$" #,##0.00'
    merged(11,1,8,'AÇÕES PRIORITÁRIAS',teal,12,'FFFFFF',True);ws.row_dimensions[11].height=28
    priorities=stats['priorities']
    for r,f in enumerate(priorities or [{'severity':'info','title':'Nenhum achado aberto ou em revisão','recommended_action':''}],12):
        merged(r,1,2,STATUS.get(f['severity'],f['severity']),'FBE7E5' if f['severity'] in {'critical','high'} else 'FFF1D1',bold=True)
        action=f['title']+' · '+(f.get('recommended_action') or f.get('description') or '')
        merged(r,3,8,action);ws.row_dimensions[r].height=max(28,((len(action)+109)//110)*15+8)
    r=13+max(1,len(priorities));merged(r,1,8,'COBERTURA E LEITURA DO RELATÓRIO',teal,12,'FFFFFF',True)
    notes=[f"{stats['comparable_items']} itens com recálculo comparável; {stats['not_recalculated_items']} sem recálculo. Diferenças não comprovam créditos ou débitos tributários.",f"{stats['excluded_documents']} documentos cancelados ou fora do período excluídos dos indicadores. Nas planilhas, consulte a coluna Elegível nos totais.",'Auditar ou tratar um achado não altera a escrituração. Abas técnicas do formato anterior foram preservadas, ocultas.']
    for n,note in enumerate(notes,r+1):merged(n,1,8,note);ws.row_dimensions[n].height=32
    r+=5;merged(r,1,8,'NAVEGAR PELAS PLANILHAS',teal,12,'FFFFFF',True)
    for n,name in enumerate(operational[1:],r+1):
        cell=merged(n,1,8,name);cell.hyperlink=f"#'{name}'!A1";cell.font=Font(name='Calibri',color=teal,underline='single');ws.row_dimensions[n].height=23
    ws.print_options.horizontalCentered=True;ws.sheet_properties.pageSetUpPr.fitToPage=True;ws.page_setup.orientation='landscape';ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=0
    wb.active=0
