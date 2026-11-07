"""Importadores CSV versionados, independentes do módulo fiscal."""
import base64
import csv
import io
import json
from .core import DomainError, audit, company_row, digest, integer, iso_date, now, pack, select_one
from .permissions import effect
from .file_store import store_file
from .import_scope import eligibility, selected_rows

LAYOUTS={
 'journals-v1':{'module':'accounting','name':'Lançamentos com múltiplas partidas','fields':['id','date','document','history','account','debit','credit','cost_center'],'routine':'accounting.journals'},
 'openings-v1':{'module':'accounting','name':'Saldos iniciais balanceados','fields':['id','date','document','history','account','debit','credit','cost_center'],'routine':'accounting.journals'},
 'accounts-v1':{'module':'accounting','name':'Plano de contas (inclusão)','fields':['access_code','classifier','name','nature','analytical','requires_cost_center','report_group','prosoft_code'],'routine':'accounting.accounts'},
 'titles-v1':{'module':'financial','name':'Títulos e parcelas','fields':['id','kind','description','partner_name','document','issue_date','due_date','amount','installment'],'routine':'financial.titles'},
}

def parse_csv(raw,layout):
    try:
        source=raw.decode('utf-8-sig')
    except UnicodeDecodeError:raise DomainError('O CSV deve estar em UTF-8.')
    reader=csv.DictReader(io.StringIO(source),delimiter=';',strict=True)
    if reader.fieldnames!=LAYOUTS[layout]['fields']:
        raise DomainError('Cabeçalho esperado: '+';'.join(LAYOUTS[layout]['fields']))
    rows=[]
    try:
        for n,row in enumerate(reader,2):
            if n>10001:raise DomainError('Limite de 10.000 linhas por lote.')
            if None in row or any(v is None for v in row.values()):raise DomainError(f'Linha {n}: quantidade incorreta de colunas.')
            rows.append({k:v.strip() for k,v in row.items()})
    except csv.Error:raise DomainError('Estrutura CSV inválida.')
    if not rows:raise DomainError('Arquivo sem registros.')
    return rows

class ModuleImportsMixin:
    def module_imports(self,cid,module,year):
        with self.db.read() as conn:
            return [dict(r) for r in conn.execute('SELECT b.id,b.module,b.year,b.layout,b.created_at,f.filename,b.result_json IS NOT NULL AS confirmed FROM module_imports b JOIN stored_files f ON f.id=b.file_id WHERE b.company_id=? AND b.module=? AND b.year=? ORDER BY b.id DESC',(cid,module,year))]

    def _module_preview(self,conn,cid,batch):
        result=json.loads(batch['preview_json'])
        for r in result['records']:
            if r.get('validation_error'):
                r['_eligibility']={'status':'blocked','reason':r['validation_error'],'period':''}
            elif batch['layout']=='accounts-v1':r['_eligibility']={'status':'eligible','reason':'Cadastro permanente','period':''}
            else:r['_eligibility']=eligibility(conn,cid,batch['module'],r['payload'].get('date') or r['payload'].get('issue_date'),batch['year'])
        return result|{k:batch[k] for k in ('id','module','year','layout','fingerprint','file_id')}|{'result':json.loads(batch['result_json']) if batch['result_json'] else None}

    def module_import_detail(self,cid,iid,module):
        with self.db.read() as conn:
            batch=select_one(conn,'module_imports',cid,iid)
            if batch['module']!=module:raise DomainError('Importação pertence a outro módulo.',403,'forbidden')
            return self._module_preview(conn,cid,batch)

    def preview_module_import(self,cid,payload,actor):
        layout=payload.get('layout');module=payload.get('module');year=integer(payload.get('year'),'Exercício',1900)
        if layout not in LAYOUTS or LAYOUTS[layout]['module']!=module or year>2199:raise DomainError('Leiaute ou exercício inválido.')
        encoded=payload.get('content_base64','')
        if not isinstance(encoded,str) or len(encoded)>28_000_000:raise DomainError('Arquivo maior que 20 MiB.')
        try:raw=base64.b64decode(encoded,validate=True)
        except ValueError:raise DomainError('Arquivo base64 inválido.')
        records=parse_csv(raw,layout)
        with self.db.transaction() as conn:
            company_row(conn,cid);effect(conn,cid,module+'.imports','import')
            fingerprint=digest(raw)
            old=conn.execute('SELECT * FROM module_imports WHERE company_id=? AND module=? AND year=? AND layout=? AND fingerprint=?',(cid,module,year,layout,fingerprint)).fetchone()
            if old:return self._module_preview(conn,cid,old)
            grouped={};result=[]
            for n,row in enumerate(records,2):
                key=row.get('id') or row.get('access_code')
                if layout in {'journals-v1','openings-v1'}:
                    group=grouped.setdefault(key,{'rows':[],'source_rows':[]});group['rows'].append(row);group['source_rows'].append(n)
                else:grouped[str(n)]={'rows':[row],'source_rows':[n]}
            for index,(key,group) in enumerate(grouped.items()):
                row=group['rows'][0];error=None;data={}
                conn.execute('SAVEPOINT validate_import')
                try:
                    if layout in {'journals-v1','openings-v1'}:
                        if not key:raise DomainError('Informe o ID estável de cada lançamento.')
                        if any(any(r[k]!=row[k] for k in ('date','document','history')) for r in group['rows']):raise DomainError('Partidas do mesmo ID têm cabeçalhos diferentes.')
                        lines=[]
                        for r in group['rows']:
                            account=conn.execute('SELECT id FROM accounts WHERE company_id=? AND access_code=?',(cid,r['account'])).fetchone()
                            if not account:raise DomainError('Conta não localizada: '+r['account'])
                            cc=conn.execute('SELECT id FROM cost_centers WHERE company_id=? AND code=?',(cid,r['cost_center'])).fetchone() if r['cost_center'] else None
                            if r['cost_center'] and not cc:raise DomainError('Centro de custo não localizado: '+r['cost_center'])
                            lines.append({'account_id':account['id'],'debit':r['debit'] or '0','credit':r['credit'] or '0','cost_center_id':cc['id'] if cc else None})
                        data={'date':iso_date(row['date']),'document':row['document'],'history':('Saldos iniciais: ' if layout=='openings-v1' else '')+row['history'],'lines':lines,'idempotency_key':layout+':'+key}
                        self._normalize_lines(conn,cid,lines)
                        if not row['history']:raise DomainError('Informe o histórico.')
                    elif layout=='accounts-v1':
                        data=dict(row)
                        for flag in ('analytical','requires_cost_center'):
                            if row[flag] not in {'0','1'}:raise DomainError(flag+': use 0 ou 1.')
                            data[flag]=row[flag]=='1'
                        self._import_account(conn,cid,data,actor)
                    else:
                        if not row['id']:raise DomainError('Informe o ID estável do título/parcela.')
                        if not row['installment'].isdigit():raise DomainError('Parcela deve ser um número inteiro positivo.')
                        data={k:v for k,v in row.items() if k!='id'}|{'source_key':'titles-v1:'+row['id'],'installment':int(row['installment'])}
                        self._create_title(conn,cid,data,actor)
                except DomainError as exc:error=None if exc.code in {'period_closed','exercise_missing'} else exc.detail
                except Exception as exc:
                    import sqlite3
                    if isinstance(exc,sqlite3.IntegrityError):error='Identidade duplicada ou vínculo inválido no cadastro.'
                    else:raise
                finally:
                    conn.execute('ROLLBACK TO validate_import');conn.execute('RELEASE validate_import')
                result.append({'_selection':str(index),'source_rows':group['source_rows'],'payload':data,'validation_error':error})
            fid=store_file(self.db,conn,cid,year,'originals',payload.get('filename','importacao.csv'),raw,actor)
            iid=conn.execute('INSERT INTO module_imports(company_id,module,year,layout,file_id,fingerprint,preview_json,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?)',(cid,module,year,layout,fid,fingerprint,pack({'records':result}),now(),actor)).lastrowid
            audit(conn,cid,actor,'preview','module_import',iid,{'layout':layout,'year':year,'sha256':fingerprint})
            return self._module_preview(conn,cid,select_one(conn,'module_imports',cid,iid))

    def _import_account(self,conn,cid,data,actor):
        effect(conn,cid,'accounting.accounts','create')
        existing=conn.execute('SELECT * FROM accounts WHERE company_id=? AND access_code=?',(cid,data['access_code'])).fetchone()
        if existing:
            if any(existing[k]!=v for k,v in data.items()):raise DomainError('Conta existente com conteúdo diferente. Edite pelo cadastro.',409,'account_conflict')
            return {'id':existing['id'],'duplicate':True}
        return self._save_account(conn,cid,data,actor)

    def confirm_module_import(self,cid,iid,payload,actor):
        with self.db.transaction() as conn:
            batch=select_one(conn,'module_imports',cid,iid)
            if batch['module']!=payload.get('module'):raise DomainError('Módulo de destino divergente.',403,'forbidden')
            effect(conn,cid,batch['module']+'.imports','import')
            if payload.get('fingerprint')!=batch['fingerprint']:raise DomainError('Prévia alterada.',409,'stale_preview')
            result=self._module_preview(conn,cid,batch)
            if batch['result_json']:
                previous=json.loads(batch['result_json'])
                if sorted(payload.get('selected',[]))!=previous['selected']:raise DomainError('Lote já confirmado com outra seleção.',409,'idempotency_conflict')
                return previous|{'duplicate':True}
            selected=selected_rows(result,payload);written=[]
            effect(conn,cid,LAYOUTS[batch['layout']]['routine'],'create')
            for r in result['records']:
                if r['_selection'] not in selected:continue
                data=r['payload']
                if batch['layout']=='accounts-v1':item=self._import_account(conn,cid,data,actor)
                elif batch['layout']=='titles-v1':item=self._create_title(conn,cid,data,actor)
                else:item=self._create_journal(conn,cid,data,actor)
                written.append({'selection':r['_selection'],'id':item['id'],'duplicate':item.get('duplicate',False)})
            final={'selected':sorted(selected),'written':written,'refused':[r for r in result['records'] if r['_selection'] not in selected]}
            conn.execute('UPDATE module_imports SET result_json=? WHERE id=?',(pack(final),iid))
            audit(conn,cid,actor,'confirm','module_import',iid,final)
            return final
