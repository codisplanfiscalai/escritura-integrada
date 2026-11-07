"""Auditor integrado: snapshots imutáveis, trabalhos persistidos e efeitos isolados."""
import base64
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import io
import json
from pathlib import PurePosixPath
import re
from zipfile import ZipFile, BadZipFile
from .core import DomainError, audit, check_version, company_row, digest, integer, iso_date, now, pack, select_one, text
from .db import request_context
from .permissions import effect, require
from .file_store import store_file, read_file

ENGINE_VERSION='auditor-1.2.2/escritura-0.7.0.2'
COVERAGE={
 'read':['NF-e 55','NFC-e 65','CT-e 57','CT-e OS 67','MDF-e 58','Evento NF-e','XML','ZIP XML/PDF'],
 'arithmetic':['PIS/Cofins ad valorem com base e alíquota explícitas','IBS/CBS regular sem redução/diferimento/devolução','Conferência assistida UB16-10 recuperada'],
 'classification':'NCM/EX × CST/cClassTrib contra catálogo publicado pelo responsável; não prova enquadramento legal.',
 'auxiliary':'DANFE 55 gerado em Python por BrazilFiscalReport 1.3.1, em XML completo; demais renderizadores pendentes de validação. PDF original preservado. Associação por chave de 44 dígitos no nome; não certifica conteúdo ou assinatura.',
 'limitations':['Sem consulta SEFAZ ou validação de assinatura digital','CT-e/MDF-e: leitura, sem auditoria tributária','Sem escrituração, baixa ou contabilização automática','Custos e margens dependem da amostra; não substituem estoque/custeio','Regras especiais IBS/CBS requerem revisão fiscal','SPED/manual sem XML: comparação limitada aos valores escriturados'],
}

class Cancelled(Exception):pass

def members(filename,raw):
    if not isinstance(filename,str) or not filename.strip():raise DomainError('Informe o nome do arquivo original.')
    suffix=PurePosixPath(filename).suffix.lower()
    if suffix in {'.xml','.pdf'}:return [(filename,raw)]
    if suffix!='.zip':raise DomainError('Auditor: envie XML, PDF auxiliar ou ZIP de XML/PDF.')
    try:
        with ZipFile(io.BytesIO(raw)) as z:
            entries=z.infolist();total=0;seen=set();result=[]
            if len(entries)>1000:raise DomainError('ZIP excede 1.000 membros.')
            for e in entries:
                path=PurePosixPath(e.filename.replace('\\','/'))
                if path.is_absolute() or '..' in path.parts or ':' in e.filename or e.filename in seen or (e.external_attr>>16)&0o170000==0o120000 or e.flag_bits&1:
                    raise DomainError('ZIP contém caminho, link, repetição ou criptografia não permitidos.')
                seen.add(e.filename)
                if e.is_dir():continue
                total+=e.file_size
                if e.file_size>20*1024*1024 or total>100*1024*1024 or e.file_size/max(e.compress_size,1)>500:raise DomainError('ZIP excede o limite de expansão.')
                if path.suffix.lower() not in {'.xml','.pdf'}:raise DomainError('ZIP do Auditor aceita somente XML e PDF; remova: '+path.name)
                result.append((path.name,z.read(e)))
            return result
    except BadZipFile:raise DomainError('ZIP inválido.')

class AuditorMixin:
    def auditor_jobs(self,cid,year):
        with self.db.read() as conn:
            return [dict(r) for r in conn.execute('SELECT id,year,mode,start,end,status,version,deleted_at,created_at,created_by,error FROM auditor_jobs WHERE company_id=? AND year=? ORDER BY id DESC',(cid,year))]

    def auditor_job(self,cid,jid):
        with self.db.read(snapshot=True) as conn:
            row=select_one(conn,'auditor_jobs',cid,jid);snap=json.loads(row.pop('snapshot_json'))
            result=json.loads(row.pop('result_json')) if row['result_json'] else None
            row['snapshot']=snap;row['result']=result;row['coverage']=snap['coverage']
            row['auxiliary']=[dict(r) for r in conn.execute('SELECT * FROM auditor_auxiliary WHERE company_id=? AND job_id=?',(cid,jid))]
            row['findings']=[{**json.loads(r['payload_json']),**{k:r[k] for k in ('id','status','responsible','treatment','version','updated_at')}} for r in conn.execute('SELECT * FROM auditor_findings WHERE company_id=? AND job_id=? ORDER BY id',(cid,jid))]
            row['logs']=[dict(r) for r in conn.execute('SELECT level,message,created_at FROM auditor_logs WHERE company_id=? AND job_id=? ORDER BY id',(cid,jid))]
            changed=[]
            for doc in snap['bookkeeping']:
                current=conn.execute('SELECT version FROM documents WHERE company_id=? AND id=?',(cid,doc['id'])).fetchone()
                if not current or current['version']!=doc['version']:changed.append(doc['id'])
            row['stale_document_ids']=changed
            row.pop('request_hash',None)
            return row

    def create_auditor_job(self,cid,payload,actor):
        mode=payload.get('mode');start=iso_date(payload.get('start'));end=iso_date(payload.get('end'));key=text(payload.get('idempotency_key'),'Chave de envio',True,200)
        if mode not in {'internal','standalone'} or start>end or start[:4]!=end[:4]:raise DomainError('Selecione origem e período dentro de um exercício.')
        files=payload.get('files',[])
        if not isinstance(files,list) or len(files)>10 or any(not isinstance(f,dict) for f in files):raise DomainError('Selecione até dez arquivos válidos.')
        if mode=='standalone' and not files:raise DomainError('Selecione arquivos para auditoria avulsa.')
        if mode=='internal' and files:raise DomainError('Auditoria interna utiliza os documentos já armazenados.')
        with self.db.transaction() as conn:
            effect(conn,cid,'auditor.analyses','create')
            if mode=='standalone':effect(conn,cid,'auditor.analyses','import')
            hashed=digest(payload);old=conn.execute('SELECT * FROM auditor_jobs WHERE company_id=? AND request_key=?',(cid,key)).fetchone()
            if old:
                if old['request_hash']!=hashed:raise DomainError('Chave de envio reutilizada com conteúdo diferente.',409,'idempotency_conflict')
                return {'id':old['id'],'status':old['status'],'duplicate':True}
            company=company_row(conn,cid);catalog=None
            if payload.get('catalog_id'):
                c=select_one(conn,'auditor_catalogs',cid,integer(payload['catalog_id'],'Catálogo'))
                if c['state']!='published':raise DomainError('Publique o catálogo após revisão antes de auditar.')
                catalog={'id':c['id'],'name':c['name'],'sha256':c['sha256'],'source':c['source'],'valid_from':c['valid_from'],'valid_to':c['valid_to'],'entries':json.loads(c['content_json'])}
            snap={'engine':ENGINE_VERSION,'coverage':COVERAGE,'company':company,'catalog':catalog,'files':[],'bookkeeping':[],'input':{'mode':mode,'start':start,'end':end,'catalog_id':payload.get('catalog_id')}}
            total_bytes=0
            for f in files:
                encoded=f.get('content_base64','')
                if not isinstance(encoded,str) or len(encoded)>28_000_000:raise DomainError('Arquivo excede 20 MiB.')
                try:raw=base64.b64decode(encoded,validate=True)
                except ValueError:raise DomainError('Arquivo base64 inválido.')
                total_bytes+=len(raw)
                if total_bytes>20*1024*1024:raise DomainError('Lote excede 20 MiB.')
                expanded=members(f.get('filename',''),raw)
                # Guarda pacote original e membros, todos sob o mesmo escopo.
                fid=store_file(self.db,conn,cid,int(start[:4]),'audit',f['filename'],raw,actor)
                for name,content in expanded:
                    child=store_file(self.db,conn,cid,int(start[:4]),'auxiliary' if name.lower().endswith('.pdf') else 'audit',name,content,actor)
                    snap['files'].append({'id':child,'name':name,'sha256':digest(content),'package_id':fid})
            if mode=='internal':
                ids=payload.get('document_ids')
                rows=[self._document(conn,cid,r['id']) for r in conn.execute('SELECT id FROM documents WHERE company_id=? AND posting_date BETWEEN ? AND ? ORDER BY id',(cid,start,end))]
                if ids is not None:
                    if not isinstance(ids,list) or not ids or any(i not in {r['id'] for r in rows} for i in ids):raise DomainError('Documento fora da empresa ou período selecionado.')
                    rows=[r for r in rows if r['id'] in ids]
                if not rows:raise DomainError('Não há documentos no período selecionado.')
                if len(rows)>2000:raise DomainError('Limite de 2.000 documentos por auditoria; reduza o intervalo.')
                snap['bookkeeping']=rows;snap['input']['document_ids']=[r['id'] for r in rows]
                hashes={s['source_hash'] for d in rows for s in d['sources'] if s['source_hash']}
                # Usa os XMLs exatos das fontes, nunca recria XML a partir do cadastro.
                for batch in conn.execute('SELECT filename,original FROM imports WHERE company_id=?',(cid,)):
                    try:parts=members(batch['filename'],batch['original'])
                    except DomainError:continue
                    for name,raw in parts:
                        sha=digest(raw)
                        if sha not in hashes or not name.lower().endswith('.xml'):continue
                        if any(f['sha256']==sha for f in snap['files']):continue
                        fid=store_file(self.db,conn,cid,int(start[:4]),'audit',name,raw,actor)
                        snap['files'].append({'id':fid,'name':name,'sha256':sha})
            ctx=request_context.get() or {}
            jid=conn.execute('INSERT INTO auditor_jobs(company_id,year,mode,start,end,request_key,request_hash,snapshot_json,created_at,created_by,user_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(cid,int(start[:4]),mode,start,end,key,hashed,pack(snap),now(),actor,ctx.get('user_id'))).lastrowid
            audit(conn,cid,actor,'create','auditor_job',jid,{'snapshot_sha256':digest(snap),'engine':ENGINE_VERSION,'mode':mode})
            return {'id':jid,'status':'queued'}

    def auditor_action(self,cid,jid,action,payload,actor):
        reason=text(payload.get('reason'),'Justificativa',True,1000)
        with self.db.transaction() as conn:
            row=select_one(conn,'auditor_jobs',cid,jid);check_version(row,payload)
            if action=='cancel':
                if row['status'] not in {'queued','running'}:raise DomainError('Auditoria já encerrada.',409)
                conn.execute("UPDATE auditor_jobs SET cancelled=1,version=version+1 WHERE id=?",(jid,))
            elif action in {'delete','restore'}:
                if row['status'] in {'queued','running'}:raise DomainError('Cancele e aguarde o processamento antes de excluir.',409)
                conn.execute('UPDATE auditor_jobs SET deleted_at=?,version=version+1 WHERE id=?',(now() if action=='delete' else None,jid))
            else:raise DomainError('Ação inválida.')
            audit(conn,cid,actor,action,'auditor_job',jid,{'reason':reason})
        return self.auditor_job(cid,jid)

    def treat_finding(self,cid,fid,payload,actor):
        with self.db.transaction() as conn:
            row=select_one(conn,'auditor_findings',cid,fid);check_version(row,payload)
            status=payload.get('status')
            if status not in {'open','reviewing','resolved','dismissed'}:raise DomainError('Situação inválida.')
            reason=text(payload.get('treatment'),'Tratamento/justificativa',True,2000);responsible=text(payload.get('responsible'),'Responsável',True,150)
            conn.execute('UPDATE auditor_findings SET status=?,responsible=?,treatment=?,version=version+1,updated_at=? WHERE id=?',(status,responsible,reason,now(),fid))
            audit(conn,cid,actor,'treatment','auditor_finding',fid,{'before':dict(row),'after':payload,'source_corrected':False})
        return {'ok':True,'source_corrected':False}

    def auditor_catalogs(self,cid):
        with self.db.read() as conn:
            return [dict(r)|{'entries':json.loads(r['content_json'])} for r in conn.execute('SELECT * FROM auditor_catalogs WHERE company_id=? ORDER BY id DESC',(cid,))]

    def save_auditor_catalog(self,cid,payload,actor,iid=None):
        name=text(payload.get('name'),'Nome',True,150);source=text(payload.get('source'),'Fonte e versão normativa',True,1000)
        start=iso_date(payload.get('valid_from'));end=iso_date(payload.get('valid_to'));entries=payload.get('entries')
        if start>end or not isinstance(entries,list) or not 1<=len(entries)<=25000:raise DomainError('Vigência ou quantidade de linhas inválida (1 a 25.000).')
        seen=set()
        for r in entries:
            if not isinstance(r,dict) or any(not isinstance(r.get(k),str) or not re.fullmatch(pattern,r[k]) for k,pattern in [('ncm',r'[0-9]{8}'),('cst',r'[0-9]{3}'),('cclass_trib',r'[0-9]{6}')]) or not r['cclass_trib'].startswith(r['cst']):raise DomainError('Cada linha exige NCM com 8 dígitos, CST com 3 e cClassTrib com 6, prefixado pelo CST. Informe os códigos como texto para preservar zeros iniciais.')
            ex='' if r.get('ex_code') is None else r['ex_code']
            if not isinstance(ex,str) or (ex and not re.fullmatch(r'[0-9]{1,3}',ex)):raise DomainError('EX deve ser texto com até três dígitos ou vazio.')
            key=(r['ncm'],ex)
            if key in seen:raise DomainError('NCM/EX ambíguo no catálogo.')
            seen.add(key)
        hashed=digest({'source':source,'valid_from':start,'valid_to':end,'entries':entries})
        with self.db.transaction() as conn:
            source_id=payload.get('source_id')
            if source_id:
                source_row=select_one(conn,'auditor_catalog_sources',cid,integer(source_id,'Origem do catálogo'))
                if json.loads(source_row['preview_json'])['issues'] and payload.get('acknowledge_issues') is not True:
                    raise DomainError('Revise e reconheça os diagnósticos e exclusões da planilha antes de salvar o rascunho.')
            if iid:
                old=select_one(conn,'auditor_catalogs',cid,iid);check_version(old,payload)
                if old['state']!='draft':raise DomainError('Catálogo publicado é imutável. Crie uma nova versão.',409,'immutable_catalog')
                conn.execute('UPDATE auditor_catalogs SET name=?,source=?,valid_from=?,valid_to=?,content_json=?,sha256=?,version=version+1 WHERE id=?',(name,source,start,end,pack(entries),hashed,iid))
            else:iid=conn.execute('INSERT INTO auditor_catalogs(company_id,name,source,valid_from,valid_to,content_json,sha256,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?)',(cid,name,source,start,end,pack(entries),hashed,now(),actor)).lastrowid
            if source_id:conn.execute('UPDATE auditor_catalogs SET source_id=? WHERE id=?',(source_id,iid))
            audit(conn,cid,actor,'draft','auditor_catalog',iid,{'sha256':hashed,'source_id':source_id,'diagnostics_reviewed':payload.get('acknowledge_issues') is True})
        return next(r for r in self.auditor_catalogs(cid) if r['id']==iid)

    def publish_auditor_catalog(self,cid,iid,payload,actor):
        reason=text(payload.get('reason'),'Conclusão da revisão',True,2000)
        with self.db.transaction() as conn:
            old=select_one(conn,'auditor_catalogs',cid,iid);check_version(old,payload)
            if old['state']!='draft':raise DomainError('Catálogo já publicado.',409)
            conn.execute("UPDATE auditor_catalogs SET state='published',review_reason=?,published_at=?,published_by=?,version=version+1 WHERE id=?",(reason,now(),actor,iid))
            audit(conn,cid,actor,'publish','auditor_catalog',iid,{'sha256':old['sha256'],'reason':reason})
        return {'id':iid,'state':'published'}

class AuditorWorker:
    def __init__(self,core):
        self.core=core;self.db=core.db;self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='auditor')
        self.pending=set()
        from threading import Lock
        self.lock=Lock()

    def recover(self):
        with self.db.transaction() as conn:
            # Trabalho interrompido nunca é declarado concluído.
            conn.execute("UPDATE auditor_jobs SET status='queued',error='Retomado após interrupção do aplicativo.' WHERE status='running'")
            rows=[(r['company_id'],r['id']) for r in conn.execute("SELECT company_id,id FROM auditor_jobs WHERE status='queued' AND deleted_at IS NULL")]
        for cid,jid in rows:self.submit(cid,jid)

    def submit(self,cid,jid):
        with self.lock:
            if jid in self.pending:return
            self.pending.add(jid)
        self.pool.submit(self.run,cid,jid)

    def close(self):self.pool.shutdown(wait=True,cancel_futures=False)

    def checkpoint(self,cid,jid):
        with self.db.read() as conn:
            row=select_one(conn,'auditor_jobs',cid,jid)
            if row['cancelled'] or row['deleted_at']:raise Cancelled()
            if row['user_id']:
                require(conn,row['user_id'],cid,'auditor.analyses','create')
                if row['mode']=='standalone':require(conn,row['user_id'],cid,'auditor.analyses','import')

    def log(self,cid,jid,message,level='info'):
        with self.db.transaction() as conn:conn.execute('INSERT INTO auditor_logs(company_id,job_id,level,message,created_at) VALUES(?,?,?,?,?)',(cid,jid,level,message,now()))

    def run(self,cid,jid):
        token=request_context.set(None)
        try:
            from .auditor_engine.catalog import CatalogSnapshot
            from .auditor_engine.xml_parser import parse_invoice,parse_event,finding
            from .auditor_engine.document_duplicates import document_identity,duplicate_finding
            from .auditor_engine.cross_rules import apply_cross_document_rules
            from .auditor_engine.product_reconciliation import build_product_reconciliation
            with self.db.transaction() as conn:
                job=select_one(conn,'auditor_jobs',cid,jid)
                if job['status']!='queued':return
                conn.execute("UPDATE auditor_jobs SET status='running',version=version+1 WHERE id=?",(jid,))
                snap=json.loads(job['snapshot_json'])
            self.checkpoint(cid,jid);self.log(cid,jid,'Leitura iniciada; escrituração preservada.')
            catalog=CatalogSnapshot(snap['catalog']);documents=[];findings=[];events=[];seen={};pdfs=[]
            for source in snap['files']:
                self.checkpoint(cid,jid)
                with self.db.read() as conn:f=read_file(conn,cid,source['id'])
                if source['name'].lower().endswith('.pdf'):
                    if not f['content'].startswith(b'%PDF-'):raise DomainError('Documento auxiliar não é PDF válido.')
                    pdfs.append(source);continue
                try:
                    event=parse_event(f['content'])
                    if event:events.append(event);continue
                    doc,found=parse_invoice(f['content'],str(f['id']),str(f['id']),catalog,snap['company']['tax_id'])
                    issued=(doc.get('issued_at') or '')[:10]
                    if snap['input']['mode']=='standalone' and not job['start']<=issued<=job['end']:
                        findings.append(finding('PERIOD-001','high','scope','Documento fora do período','Arquivo preservado, mas excluído dos totais da amostra.',doc['document_ref'],evidence={'issued_at':issued,'start':job['start'],'end':job['end']}))
                        doc['status']='outside_period'
                    identity=document_identity(doc)
                    if identity in seen:
                        findings.append(duplicate_finding(seen[identity],doc,identity,2));continue
                    if identity:seen[identity]=doc
                    doc['original_file_id']=f['id'];documents.append(doc);findings.extend(found)
                except (ValueError,TypeError,ArithmeticError) as exc:
                    findings.append(finding('XML-PARSE-001','critical','document','XML não auditado',str(exc)[:300],source['sha256'],evidence={'file_id':f['id'],'sha256':source['sha256']}))
                except Exception as exc:
                    from .auditor_engine.input_validation import FiscalInputError
                    from lxml.etree import XMLSyntaxError
                    if isinstance(exc,(FiscalInputError,XMLSyntaxError)):
                        findings.append(finding('XML-PARSE-001','critical','document','XML não auditado',getattr(exc,'detail','XML inválido ou empresa divergente.'),source['sha256'],evidence={'file_id':f['id'],'sha256':source['sha256']}))
                    else:raise
            for doc in documents:
                for event in events:
                    # 136 = evento não vinculado: não cancela documento automaticamente.
                    if event.get('access_key')==doc.get('access_key') and event.get('event_type')=='110111' and event.get('status_code') in {'135','155'}:
                        doc['status']='cancelled';doc['cancellation_event']=event
                matches=[f for f in pdfs if doc.get('access_key') and doc['access_key'] in re.findall(r'(?<!\d)\d{44}(?!\d)',f['name'])]
                doc['auxiliary_file_ids']=[f['id'] for f in matches]
                booked=next((b for b in snap['bookkeeping'] if (doc.get('access_key') and b['key']==doc['access_key']) or any(s['source_hash']==doc['normalized'].get('xml_sha256') for s in b['sources'])),None)
                if booked:
                    doc['bookkeeping_id']=booked['id'];doc['bookkeeping_version']=booked['version']
                    if Decimal(doc['total_value'])*100!=booked['total_cents']:
                        findings.append(finding('BOOKED-TOTAL-001','high','bookkeeping','Original e escrituração divergentes','O total escriturado difere do XML preservado.',doc['document_ref'],evidence={'document_id':booked['id'],'original':doc['total_value'],'booked_cents':booked['total_cents'],'version':booked['version']}))
                    xml_items={int(i['item_number']):i for i in doc['items']}
                    for b in booked['items']:
                        original=xml_items.get(int(b.get('number',0))) if str(b.get('number','')).isdigit() else None
                        if original and b.get('total') is not None and Decimal(str(b['total']))!=Decimal(str(original['product_value'])):
                            findings.append(finding('BOOKED-ITEM-001','high','bookkeeping','Item escriturado divergente','Valor do item difere do original.',doc['document_ref'],original['item_number'],{'document_id':booked['id'],'item':b.get('number'),'original':original['product_value'],'booked':b['total']}))
            for b in snap['bookkeeping']:
                if not any(d.get('bookkeeping_id')==b['id'] for d in documents):
                    findings.append(finding('ORIGINAL-MISSING-001','medium','coverage','XML original indisponível','Registro preservado no retrato; recálculo de XML não executado.',b['key'] or str(b['id']),evidence={'document_id':b['id'],'version':b['version'],'booked_total_cents':b['total_cents']}))
            self.checkpoint(cid,jid)
            active=[d for d in documents if d['status'] not in {'cancelled','outside_period'}]
            findings.extend(apply_cross_document_rules(active))
            result={'engine':ENGINE_VERSION,'documents':documents,'events':events,'reconciliation':build_product_reconciliation(active),'totals':{'documents':len(active),'total_cents':int(sum((Decimal(d['total_value'])*100 for d in active),Decimal(0))),'findings':len(findings)},'snapshot_sha256':digest(snap),'catalog_sha256':snap['catalog']['sha256'] if snap['catalog'] else None}
            self.checkpoint(cid,jid)
            with self.db.transaction() as conn:
                current=select_one(conn,'auditor_jobs',cid,jid)
                if current['cancelled']:raise Cancelled()
                if current['user_id']:require(conn,current['user_id'],cid,'auditor.analyses','create')
                if current['user_id'] and current['mode']=='standalone':require(conn,current['user_id'],cid,'auditor.analyses','import')
                conn.execute('DELETE FROM auditor_findings WHERE company_id=? AND job_id=?',(cid,jid))
                for f in findings:
                    # Decimal da confiança é serializado sem ponto flutuante.
                    if isinstance(f.get('confidence'),Decimal):f['confidence']=str(f['confidence'])
                    conn.execute('INSERT INTO auditor_findings(company_id,job_id,payload_json) VALUES(?,?,?)',(cid,jid,pack(f)))
                conn.execute("UPDATE auditor_jobs SET status='completed',result_json=?,finished_at=?,error=NULL,version=version+1 WHERE id=?",(pack(result),now(),jid))
                audit(conn,cid,job['created_by'],'complete','auditor_job',jid,{'totals':result['totals'],'snapshot_sha256':result['snapshot_sha256'],'bookkeeping_changed':False})
            self.log(cid,jid,'Concluído. Marcar achados como tratados não corrige a origem.')
        except Cancelled:
            with self.db.transaction() as conn:conn.execute("UPDATE auditor_jobs SET status='cancelled',finished_at=?,version=version+1 WHERE id=? AND company_id=?",(now(),jid,cid))
            self.log(cid,jid,'Cancelado; nenhum resultado parcial foi publicado.','warning')
        except Exception as exc:
            message=exc.detail if isinstance(exc,DomainError) else 'Falha no processamento. Os originais e o retrato foram preservados; consulte os logs do aplicativo.'
            import logging
            logging.getLogger(__name__).exception('Auditoria %s/%s falhou',cid,jid)
            with self.db.transaction() as conn:conn.execute("UPDATE auditor_jobs SET status='failed',error=?,finished_at=?,version=version+1 WHERE id=? AND company_id=?",(message,now(),jid,cid))
            self.log(cid,jid,message,'error')
        finally:
            request_context.reset(token)
            with self.lock:self.pending.discard(jid)
