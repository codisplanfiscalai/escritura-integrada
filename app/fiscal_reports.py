"""Livros auxiliares e análises fiscais, preservando valores declarados e lacunas."""
import json
from collections import defaultdict
from .core import DomainError,company_row,iso_date,money,decimal_text

FISCAL_REPORTS={'fiscal-documents':'Documentos fiscais','fiscal-entries':'Livro auxiliar de entradas',
'fiscal-outputs':'Livro auxiliar de saídas','fiscal-items':'Itens escriturados','fiscal-operations':'Operações por CFOP',
'fiscal-participants':'Operações por participante','fiscal-classifications':'Itens por NCM e CFOP',
'fiscal-taxes':'Bases e tributos declarados','fiscal-inconsistencies':'Pendências de conferência',
'fiscal-assessments':'Livro auxiliar de apuração'}
TAXES={'icms':['icms','vICMS','VL_ICMS'],'ipi':['ipi','vIPI','VL_IPI'],'iss':['iss','vISS','vISSQN'],
       'pis':['pis','vPIS','VL_PIS'],'cofins':['cofins','vCOFINS','VL_COFINS'],'ibs':['ibs','vIBS'],'cbs':['cbs','vCBS']}

def declared(taxes,tax,base=False):
    """Não soma pais e filhos nem toma campo ausente como valor zero."""
    aliases=(['base_'+tax,'VL_BC_'+tax.upper()] if base else TAXES[tax])
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
        if kind in {'fiscal-entries','fiscal-outputs'}:direction='incoming' if kind=='fiscal-entries' else 'outgoing';status='booked'
        with self.db.read(snapshot=True) as conn:
            company=company_row(conn,cid);docs=[self._document(conn,cid,r[0]) for r in conn.execute('SELECT id FROM documents WHERE company_id=? AND posting_date BETWEEN ? AND ? ORDER BY posting_date,id',(cid,start,end))]
            query=query.casefold().strip()
            docs=[d for d in docs if (not status or d['status']==status) and (not direction or d['direction']==direction) and (not query or query in f"{d['number']} {d['partner_name']} {d['partner_tax_id']} {d['key']}".casefold())]
            docs=[d for d in docs if (not cfop or d['cfop']==cfop or any(i.get('cfop')==cfop for i in d['items'])) and (not ncm or any(i.get('ncm')==ncm for i in d['items']))]
            def document(d):return {'document_id':d['id'],'date':d['posting_date'],'document':d['number'],'model':d['model'],'series':d['series'],
                'partner_name':d['partner_name'],'partner_tax_id':d['partner_tax_id'],'direction':d['direction'],'cfop':d['cfop'],
                'total_cents':d['total_cents'],'status':d['status']}
            rows=[];totals={};note='Relatório auxiliar interno. Valores declarados; campos ausentes permanecem em branco. Não substitui obrigação legal, PVA ou validação da incidência/crédito.'
            if kind in {'fiscal-documents','fiscal-entries','fiscal-outputs','fiscal-taxes'}:
                rows=[document(d) for d in docs]
                if kind=='fiscal-taxes':
                    for r,d in zip(rows,docs):
                        for tax in TAXES:
                            r[tax+'_base_cents']=declared(d['taxes'],tax,True);r[tax+'_cents']=declared(d['taxes'],tax)
                    for tax in TAXES:
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
                        try:
                            item_total=sum(money(i.get('total'),'Total do item') for i in d['items'])
                            if item_total!=d['total_cents']:issues.append(('ITEM_HEADER_DIFFERENCE','Itens e total documental diferem; confira frete, descontos e demais componentes. Não indica erro por si só.'))
                        except DomainError:issues.append(('ITEM_VALUE','Há item sem total numérico válido.'))
                    for code,message in issues:rows.append({'document_id':d['id'],'date':d['posting_date'],'document':d['number'],'partner_name':d['partner_name'],'status':d['status'],'code':code,'message':message})
                totals={'documents':len(docs),'occurrences':len(rows)};note+=' Diagnósticos operacionais para revisão; não constituem conclusão tributária.'
            else:
                for r in conn.execute('SELECT * FROM tax_ledgers WHERE company_id=? AND period BETWEEN ? AND ? AND reversed_at IS NULL ORDER BY period,tax',(cid,start[:7],end[:7])):
                    saved=json.loads(r['snapshot_json']);rows.append({'ledger_id':r['id'],'period':r['period'],'tax':r['tax'].upper(),'assessment_id':r['assessment_id'],
                        'opening_credit_cents':r['opening_credit_cents'],'debit_cents':saved['debit_cents'],'credit_cents':saved['credit_cents'],
                        'payable_cents':r['payable_cents'],'carry_credit_cents':r['carry_credit_cents'],'responsible':r['created_by'],'reason':r['reason']})
                totals={'finalized_assessments':len(rows)};note='Livro auxiliar de memórias conferidas e finalizadas por tributo. Saldos de tributos diferentes não são somados nem compensados. Cada linha permite consultar a memória de origem.'
            return {'kind':kind,'title':FISCAL_REPORTS[kind],'company_id':cid,'company_name':company['name'],'start':start,'end':end,'rows':rows,'totals':totals,'scope_note':note,'filters':{'query':query,'status':status,'direction':direction,'cfop':cfop,'ncm':ncm}}
