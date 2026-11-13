"""Livros auxiliares e análises fiscais, preservando valores declarados e lacunas."""
import json
from collections import defaultdict
from .core import DomainError,company_row,iso_date,money,decimal_text
from .fiscal_analytics import fiscal_posting_lines

FISCAL_REPORTS={'fiscal-documents':'Documentos fiscais','fiscal-entries':'Registro de entradas',
'fiscal-outputs':'Registro de saídas','fiscal-items':'Itens escriturados','fiscal-operations':'Operações por CFOP',
'fiscal-participants':'Operações por participante','fiscal-classifications':'Itens por NCM e CFOP',
'fiscal-taxes':'Bases e tributos declarados','fiscal-inconsistencies':'Pendências de conferência',
'fiscal-assessments':'Livro auxiliar de apuração'}
TAXES={'icms':['icms','vICMS','VL_ICMS'],'ipi':['ipi','vIPI','VL_IPI'],'iss':['iss','vISS','vISSQN'],
       'pis':['pis','vPIS','VL_PIS'],'cofins':['cofins','vCOFINS','VL_COFINS'],'ibs':['ibs','vIBS'],'cbs':['cbs','vCBS']}

def declared(taxes,tax,base=False):
    """Não soma pais e filhos nem toma campo ausente como valor zero."""
    aliases=(['base_'+tax,tax+'_base','VL_BC_'+tax.upper()] if base else TAXES[tax])
    candidates=[]
    for key,value in taxes.items():
        if not isinstance(value,(str,int,float)):continue
        leaf=key.split('.')[-1]
        matches=leaf in aliases
        if base and leaf in {'vBC','vBCISS','vBCIBSCBS'}:
            matches=(tax=='icms' and key.startswith(('ICMS.','ICMSTot.'))) or (tax=='iss' and (key.startswith('ISSQN') or leaf=='vBCISS')) or (tax in {'ibs','cbs'} and leaf=='vBCIBSCBS') or key.startswith(tax.upper()+'.')
        if matches:
            try:candidates.append(money(str(value),key))
            except DomainError:return None
    return candidates[0] if len(candidates)==1 else None

class FiscalReportsMixin:
    def fiscal_report(self,cid,kind,start,end,query='',status='',direction='',cfop='',ncm=''):
        if kind not in FISCAL_REPORTS:raise DomainError('Relatório fiscal não encontrado.',404)
        start,end=iso_date(start),iso_date(end)
        if start>end:raise DomainError('Período inicial posterior ao final.')
        if status not in {'','pending','reviewed','booked','cancelled'}:raise DomainError('Situação fiscal inválida.')
        if direction not in {'','incoming','outgoing'}:raise DomainError('Operação fiscal inválida.')
        cfop=str(cfop or '').strip();ncm=str(ncm or '').strip()
        if cfop and (len(cfop)!=4 or not cfop.isascii() or not cfop.isdigit()):raise DomainError('CFOP deve conter quatro dígitos.')
        if ncm and (len(ncm)!=8 or not ncm.isascii() or not ncm.isdigit()):raise DomainError('NCM deve conter oito dígitos.')
        if kind=='fiscal-assessments' and any([query,status,direction,cfop,ncm]):raise DomainError('Apurações são filtradas pelo intervalo de competências, sem filtros documentais.')
        cancelled_only = status == 'cancelled'
        if kind in {'fiscal-entries','fiscal-outputs'}:direction='incoming' if kind=='fiscal-entries' else 'outgoing';status='booked'
        with self.db.read(snapshot=True) as conn:
            from .fiscal_series import settings
            digits=settings(conn,cid)["digits"]
            company=company_row(conn,cid);docs=[self._document_values(r,digits) for r in conn.execute('SELECT * FROM documents WHERE company_id=? AND posting_date BETWEEN ? AND ? ORDER BY posting_date,id',(cid,start,end))]
            query=query.casefold().strip()
            docs=[d for d in docs if (not status or d['status']==status or status=='cancelled' and d.get('book_cancellation')) and (not cancelled_only or d.get('book_cancellation')) and (not direction or d['direction']==direction) and (not query or query in f"{d['number']} {d['partner_name']} {d['partner_tax_id']} {d['key']}".casefold())]
            analytical_book=kind in {'fiscal-entries','fiscal-outputs'}
            docs=[d for d in docs if analytical_book or (not cfop or d['cfop']==cfop or any(i.get('cfop')==cfop for i in d['items'])) and (not ncm or any(i.get('ncm')==ncm for i in d['items']))]
            def document(d):
                party = d.get('issuer', {}) if d['direction'] == 'incoming' else d.get('recipient', {})
                party = party if isinstance(party, dict) else {}
                return {'partner_state':party.get('state','') if isinstance(party.get('state',''),str) else '', 'partner_ie':party.get('ie','') if isinstance(party.get('ie',''),str) else '','document_id':d['id'],'date':d['posting_date'],'issue_date':d['issue_date'],'document':d['number'],'model':d['model'],'series':d['series'],
                'partner_name':d['partner_name'],'partner_tax_id':d['partner_tax_id'],'direction':d['direction'],'cfop':d['cfop'],
                'total_cents':d['total_cents'],'status':d['status'], 'document_state':d.get('document_state',''), 'cancellation_source':d.get('book_cancellation',{}).get('source',''), 'cancellation_responsible':d.get('book_cancellation',{}).get('responsible',''), 'cancellation_reason':d.get('book_cancellation',{}).get('reason','')}
            rows=[];totals={};note='Relatório auxiliar interno. Valores declarados; campos ausentes permanecem em branco. Não substitui obrigação legal, PVA ou validação da incidência/crédito.'
            if any(d.get('book_cancellation') for d in docs):
                note+=' Canceladas conforme livro validado: datas e classificação atribuídas ao livro; valores zerados, sem efeitos econômicos ou comprovação eletrônica/SEFAZ.'
            document_headers=[]
            if analytical_book:
                for d in docs:
                    selected=[]
                    for index,line in enumerate(fiscal_posting_lines(d),1):
                        if (cfop and line['cfop']!=cfop) or (ncm and ncm not in line.get('ncms',[])):continue
                        r=document(d)
                        r.update(line=index,cfop=line['cfop'],cst_icms=line.get('cst_icms',''),
                            csosn=line.get('csosn',''),origin=line.get('origin',''),rate=line.get('rate'),
                            item_numbers=line.get('item_numbers',[]),ncms=line.get('ncms',[]),
                            treatment=line.get('treatment',''),pending=line.get('pending',[]),
                            source_kind=line.get('source_kind',''),declared_taxes=line.get('declared_taxes',{}),
                            posting_group=line.get('posting_group',''),posting_group_review=d.get('posting_group_review'),grouping_mode=line.get('grouping_mode','automatic'),
                            declared_classifications=line.get('declared_classifications',[]),
                            declared_tax_coverage=line.get('declared_tax_coverage',{}),
                            declared_tax_partial_totals=line.get('declared_tax_partial_totals',{}))
                        for source,target in [('document_total','total_cents'),('ipi','ipi_allocated_cents'),
                            ('book_base','book_base_cents'),('book_icms','book_icms_cents'),
                            ('book_other','book_other_cents'),('book_ipi','book_ipi_cents')]:
                            value=line.get(source)
                            r[target]=money(value,source,signed=True) if value is not None else None
                        r['declared_ipi_cents']=r['ipi_allocated_cents'] if line.get('ipi_informed') else None
                        for tax in ['icms','ipi']:
                            r['declared_'+tax+'_base_cents']=declared(r['declared_taxes'],tax,True)
                            if tax!='ipi':r['declared_'+tax+'_cents']=declared(r['declared_taxes'],tax)
                        selected.append(r)
                    if selected:
                        document_headers.append(document(d))
                        rows.extend(selected)
                totals={'documents':len(document_headers),'lines':len(rows),
                    'document_total_cents':sum(d['total_cents'] for d in document_headers)}
                for key in ['total_cents','ipi_allocated_cents','declared_ipi_cents','declared_icms_cents',
                    'declared_icms_base_cents','declared_ipi_base_cents','book_base_cents',
                    'book_icms_cents','book_other_cents','book_ipi_cents']:
                    known=[r[key] for r in rows if r[key] is not None]
                    totals[key]=sum(known) if known or key=='total_cents' else None
                    totals[key.removesuffix('_cents')+'_informed_lines']=len(known)
                totals['lines_with_pending']=sum(bool(r['pending']) for r in rows)
                note+=' Livro analítico: agrupamento automático por CFOP, CST/CSOSN, origem, alíquota e tratamento, salvo grupo revisado explícito. Consolidação heterogênea preserva todas as classificações declaradas e deixa campos comuns mistos não informados. Valor contábil é a parcela da linha, nunca repetição do total da nota. Cabeçalhos preservam o total documental integral uma única vez. Tributos declarados e valores de livro são separados; sem tratamento explícito, bases, créditos e Outras do livro permanecem não informados. Rateios e lacunas são identificados na origem e nas pendências de cada linha.'
                if cfop:note+=' O filtro CFOP seleciona e soma somente as linhas correspondentes; o total documental de referência não é o total das linhas filtradas.'
                if ncm:note+=' O filtro NCM seleciona linhas que contêm esse NCM; cada linha fiscal permanece integral e pode reunir outros NCMs. Não há rateio adicional por NCM.'
            elif kind in {'fiscal-documents','fiscal-taxes'}:
                rows=[document(d) for d in docs]
                if kind in {'fiscal-taxes','fiscal-entries','fiscal-outputs'}:
                    reported_taxes=TAXES if kind=='fiscal-taxes' else ['icms','ipi']
                    for r,d in zip(rows,docs):
                        for tax in reported_taxes:
                            r[tax+'_base_cents']=declared(d['taxes'],tax,True);r[tax+'_cents']=declared(d['taxes'],tax)
                    for tax in reported_taxes:
                        for suffix in ['_base_cents','_cents']:totals[tax+suffix]=sum(r[tax+suffix] or 0 for r in rows)
                        totals[tax+'_informed_documents']=sum(r[tax+'_cents'] is not None for r in rows)
                    note+=' Totais tributários abrangem somente valores conhecidos; a quantidade informada indica a cobertura por tributo.'
                totals.update(documents=len(docs),total_cents=sum(d['total_cents'] for d in docs))
            elif kind in {'fiscal-items','fiscal-classifications','fiscal-operations'}:
                for d in docs:
                    items=d['items']
                    if kind=='fiscal-operations' and not items:
                        items=[{'description':'Documento sem detalhamento de itens','cfop':d['cfop'],'total':decimal_text(d['total_cents'])}]
                    for index,item in enumerate(items,1):
                        code=item.get('cfop') or d['cfop'];classification=item.get('ncm','')
                        if (cfop and code!=cfop) or (ncm and classification!=ncm):continue
                        try:value=money(item.get('total'),'Total do item')
                        except DomainError:value=None
                        rows.append({'document_id':d['id'],'date':d['posting_date'],'document':d['number'],'item':index,
                            'description':item.get('description',''),'partner_name':d['partner_name'],'cfop':code,'ncm':classification,
                            'quantity':item.get('quantity',''),'unit':item.get('unit',''),'item_total_cents':value,'direction':d['direction'],'status':d['status']})
                totals={'items':len(rows),'item_total_cents':sum(r['item_total_cents'] or 0 for r in rows),'items_without_value':sum(r['item_total_cents'] is None for r in rows)}
                if kind in {'fiscal-classifications','fiscal-operations'}:
                    groups={}
                    for r in rows:
                        keys=['direction','cfop']+(['ncm'] if kind=='fiscal-classifications' else [])
                        group=groups.setdefault(tuple(r[k] for k in keys),{k:r[k] for k in keys}|{'items':0,'item_total_cents':0,'items_without_value':0,'document_ids':[]})
                        group['items']+=1;group['item_total_cents']+=r['item_total_cents'] or 0;group['items_without_value']+=r['item_total_cents'] is None
                        if r['document_id'] not in group['document_ids']:group['document_ids'].append(r['document_id'])
                    rows=list(groups.values())
                note+=' Totais por itens não incluem frete, descontos ou outras parcelas do cabeçalho automaticamente. Sem itens, operações por CFOP usam o total documental uma única vez.'
            elif kind=='fiscal-participants':
                groups={}
                for d in docs:
                    key=(d['partner_tax_id'],d['partner_name'],d['direction'])
                    group=groups.setdefault(key,{'partner_tax_id':key[0],'partner_name':key[1],'direction':key[2],'documents':0,'total_cents':0,'document_ids':[]})
                    group['documents']+=1;group['total_cents']+=d['total_cents'];group['document_ids'].append(d['id'])
                rows=list(groups.values());totals={'documents':len(docs),'total_cents':sum(d['total_cents'] for d in docs)}
            elif kind=='fiscal-inconsistencies':
                for d in docs:
                    issues=[]
                    if d['status']!='booked':issues.append(('NOT_BOOKED','Documento ainda não escriturado.'))
                    if not d['cfop'] and d['model']!='NFSE':issues.append(('CFOP_REVIEW','Confira a classificação da operação no cabeçalho e nos itens.'))
                    if not d['partner_tax_id']:issues.append(('PARTNER_ID','Participante sem CPF/CNPJ; confira se a ausência é permitida neste documento.'))
                    if d['items']:
                        from .document_totals import document_total_issue
                        issue=document_total_issue(d)
                        if issue:issues.append(issue)
                    for code,message in issues:rows.append({'document_id':d['id'],'date':d['posting_date'],'document':d['number'],'partner_name':d['partner_name'],'status':d['status'],'code':code,'message':message,'line_numbers':[],'next_step':'Confira o documento de origem e os componentes da operação.'})
                    # Escrituração concluída não significa tratamento tributário
                    # completo. Reúna a mesma crítica por documento e código,
                    # conservando quais linhas do livro precisam de revisão.
                    from .fiscal_review_messages import fiscal_review
                    grouped = {}
                    for index,line in enumerate(fiscal_posting_lines(d),1):
                        if (cfop and line['cfop']!=cfop) or (ncm and ncm not in line.get('ncms',[])):continue
                        for code in dict.fromkeys(line.get('pending', [])):
                            grouped.setdefault(code, []).append(index)
                    for code,line_numbers in grouped.items():
                        rows.append({'document_id':d['id'],'date':d['posting_date'],'document':d['number'],
                            'partner_name':d['partner_name'],'status':d['status'],
                            **fiscal_review(code),'line_numbers':line_numbers})
                totals={'documents':len(docs),'documents_with_findings':len({r['document_id'] for r in rows}),
                    'occurrences':len(rows)}
                note+=' Diagnósticos operacionais para revisão; não constituem conclusão tributária. Uma ocorrência reúne a mesma crítica de um documento e identifica as linhas afetadas. Documento escriturado pode ainda exigir revisão do tratamento fiscal; isso não altera seu estado de escrituração nem presume imposto devido ou crédito.'
            else:
                for r in conn.execute('SELECT * FROM tax_ledgers WHERE company_id=? AND period BETWEEN ? AND ? AND reversed_at IS NULL ORDER BY period,tax',(cid,start[:7],end[:7])):
                    saved=json.loads(r['snapshot_json']);rows.append({'ledger_id':r['id'],'period':r['period'],'tax':r['tax'].upper(),'assessment_id':r['assessment_id'],
                        'opening_credit_cents':r['opening_credit_cents'],'debit_cents':saved['debit_cents'],'credit_cents':saved['credit_cents'],
                        'payable_cents':r['payable_cents'],'carry_credit_cents':r['carry_credit_cents'],'responsible':r['created_by'],'reason':r['reason']})
                totals={'finalized_assessments':len(rows)};note='Livro auxiliar de memórias conferidas e finalizadas por tributo. O intervalo considera as competências mensais das datas inicial e final, inclusive. Saldos de tributos diferentes não são somados nem compensados. Cada linha permite consultar a memória de origem.'
            if (cfop or ncm) and kind not in {'fiscal-items','fiscal-classifications','fiscal-operations','fiscal-entries','fiscal-outputs'}:note+=' CFOP/NCM selecionam documentos que contenham a classificação; os valores documentais permanecem integrais, sem rateio pelos itens selecionados.'
            return {'series_digits':digits,'kind':kind,'title':FISCAL_REPORTS[kind],'company_id':cid,'company_name':company['name'],'company_code':company['prosoft_code'] or company['code'],'company_tax_id':company['tax_id'],'company_ie':company['ie'],'start':start,'end':end,'rows':rows,**({'document_headers':document_headers,'row_scope':'analytical_posting_lines','analytical_version':1} if analytical_book else {}),'totals':totals,'scope_note':note,'filters':{'query':query,'status':'cancelled' if cancelled_only else status,'direction':direction,'cfop':cfop,'ncm':ncm}}
