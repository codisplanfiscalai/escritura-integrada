"""Resultados de auditoria: consultas, validação e armazenamento de relatórios."""
from collections import Counter
from decimal import Decimal
import json
from .core import DomainError, audit, digest, now, pack
from .file_store import read_file, store_file


def analytics(documents, findings):
    active=[d for d in documents if d.get('status') not in {'cancelled','outside_period'}]
    items=[i for d in active for i in d.get('items',[])]
    def total(rows,key): return str(sum((Decimal(str(r.get(key) or 0)) for r in rows),Decimal(0)))
    return {'overview': {'documents':len(active),'items':len(items),'findings':len(findings),
        'input_count':sum(d['direction']=='entrada' for d in active),'output_count':sum(d['direction']=='saida' for d in active),
        'total_value':total(active,'total_value'),'input_value':total([d for d in active if d['direction']=='entrada'],'total_value'),
        'output_value':total([d for d in active if d['direction']=='saida'],'total_value'),
        **{k:total(active,k) for k in ('ibs_cbs_base','ibs_value','cbs_value')}},
        'severity_counts':dict(Counter(f['severity'] for f in findings)),
        'category_counts':dict(Counter(f['category'] for f in findings)),
        'classification_counts':dict(Counter(i.get('classification_status','NOT_EVALUATED') for i in items)),
        'status_counts':dict(Counter(f.get('status','open') for f in findings))}


def validate_result(result):
    refs=set()
    for d in result['documents']:
        if not d.get('document_ref') or d['document_ref'] in refs: raise DomainError('Resultado com documentos repetidos; publicação bloqueada.',409,'audit_result_invalid')
        refs.add(d['document_ref']);numbers=set()
        for i in d['items']:
            n=i.get('item_number')
            if not isinstance(n,int) or n<1 or n in numbers: raise DomainError('Resultado com itens inválidos ou repetidos.',409,'audit_result_invalid')
            numbers.add(n)
        for key in ('total_value','ibs_cbs_base','ibs_value','cbs_value'):
            if not Decimal(str(d.get(key) or 0)).is_finite(): raise DomainError('Resultado monetário não finito.',409,'audit_result_invalid')


def compare_bookkeeping(document,booked):
    """Compara o retrato original com as células efetivamente escrituradas; não presume correção."""
    from .auditor_engine.xml_parser import finding
    result=[]
    def different(a,b,code=False):
        if a is None or b is None:return False
        if code:return str(a)!=str(b)
        try:return Decimal(str(a))!=Decimal(str(b))
        except Exception:return str(a)!=str(b)
    for i in document['items']:
        b=next((b for b in booked['items'] if str(b.get('number'))==str(i['item_number'])),None)
        if b is None:
            result.append(finding('BOOKED-ITEM-MISSING-001','high','bookkeeping','Item não localizado na escrituração','O item original não consta do retrato escriturado.',document['document_ref'],i['item_number'],{'document_id':booked['id']}));continue
        changes=[]
        for field,original,recorded in [('NCM',i.get('ncm'),b.get('ncm')),('Quantidade',i.get('details',{}).get('quantity'),b.get('quantity'))]:
            if different(original,recorded,field=='NCM'):changes.append({'field':field,'original':original,'booked':recorded})
        original_taxes=i.get('details',{}).get('tax_path_values',{})
        for field,recorded in (b.get('taxes') or {}).items():
            if field in original_taxes and different(original_taxes[field],recorded,not field.rsplit('/',1)[-1].startswith(('v','p','q'))):
                changes.append({'field':field,'original':original_taxes[field],'booked':recorded})
        if changes:result.append(finding('BOOKED-FIELDS-001','high','bookkeeping','Campos escriturados diferem do XML','Confira as alterações de classificação, quantidade e tributos. O apontamento não corrige a origem.',document['document_ref'],i['item_number'],{'document_id':booked['id'],'bookkeeping_version':booked['version'],'differences':changes}))
    return result


def bookkeeping_document(booked):
    """Representa dados escriturados sem fabricar XML nem recálculos tributários."""
    items=[]
    for n,i in enumerate(booked.get('items',[]),1):
        items.append({'item_number':int(i.get('number') or n),'product_code':i.get('code'),
            'description':i.get('description'),'ncm':i.get('ncm'),'cfop':i.get('cfop'),
            'product_value':str(i.get('total') or 0),'calculation_scope':'bookkeeping_only',
            'classification_status':'NOT_EVALUATED','details':{'quantity':i.get('quantity'),'unit':i.get('unit')},
            'tax_components':{},'catalog_match':{},'bookkeeping':i})
    return {'document_ref':'bookkeeping:'+str(booked['id']),'number':booked['number'],'model':booked['model'],
        'series':booked['series'],'access_key':booked.get('key'),'issued_at':booked['issue_date'],
        'posting_date':booked['posting_date'],'direction':'entrada' if booked['direction']=='incoming' else 'saida',
        'status':'cancelled' if booked.get('status')=='cancelled' else 'bookkeeping_only',
        'total_value':str(Decimal(booked['total_cents'])/100),'ibs_cbs_base':'0','ibs_value':'0','cbs_value':'0',
        'items':items,'item_count':len(items),'bookkeeping_id':booked['id'],'bookkeeping_version':booked['version'],
        'original_file_id':None,'normalized':{'origin':'bookkeeping','partner_name':booked.get('partner_name'),'booked_taxes':booked.get('taxes',{})},
        'origin':'bookkeeping','coverage':'Sem XML original: valores escriturados consultáveis; recálculos não executados.'}


def report_revision(job):
    return digest({'snapshot':job['result']['snapshot_sha256'],'result':job['result'],
                   'findings':job['findings'],'stale':job.get('stale_document_ids',[]),'logs':job.get('logs',[]),'attachments':job.get('attachments',[]),'template':'auditor-v2'})


def persist_report(core,conn,cid,job,fmt,content,actor):
    revision=report_revision(job)
    old=conn.execute('SELECT * FROM auditor_reports WHERE company_id=? AND job_id=? AND format=? AND revision=?',(cid,job['id'],fmt,revision)).fetchone()
    if old:return dict(old)
    fid=store_file(core.db,conn,cid,job['year'],'reports',f"auditoria-{job['id']}-{revision[:12]}.{fmt}",content,actor)
    rid=conn.execute('INSERT INTO auditor_reports(company_id,job_id,format,revision,file_id,created_at,created_by) VALUES(?,?,?,?,?,?,?)',(cid,job['id'],fmt,revision,fid,now(),actor)).lastrowid
    audit(conn,cid,actor,'report','auditor_job',job['id'],{'report_id':rid,'format':fmt,'revision':revision,'file_id':fid})
    return {'id':rid,'file_id':fid,'revision':revision,'format':fmt}


def report_bytes(core,cid,job,fmt,actor):
    if fmt not in {'pdf','xlsx'}:raise DomainError('Selecione PDF ou Excel.')
    revision=report_revision(job)
    with core.db.read() as conn:
        old=conn.execute('SELECT * FROM auditor_reports WHERE company_id=? AND job_id=? AND format=? AND revision=?',(cid,job['id'],fmt,revision)).fetchone()
        if old:return read_file(conn,cid,old['file_id'])['content']
    from .auditor_reports import export_audit
    content,_=export_audit(job,fmt)
    with core.db.transaction() as conn:persist_report(core,conn,cid,job,fmt,content,actor)
    return content
