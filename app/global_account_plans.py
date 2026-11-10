"""Versioned shared definitions with company-owned operational account IDs.

Shared versions never change underneath a journal. Shared definitions are not
copied into companies: only used accounts allocate minimal FK targets. Own
forks explicitly copy the definition, preserving every previously used ID.
"""
import json
from collections import Counter

from .account_plans import FIELDS, account_values
from .core import DomainError, audit, check_version, company_row, digest, integer, now, pack, select_one, text
from .permissions import effect


def admin(conn, actor):
    user = conn.execute('SELECT role,active FROM users WHERE username=?', (actor,)).fetchone()
    if not user or not user['active'] or user['role'] != 'admin':
        raise DomainError('Publicação global reservada ao administrador.', 403, 'forbidden')


def global_plan(conn, item_id):
    row = conn.execute('SELECT * FROM global_account_plans WHERE id=?', (item_id,)).fetchone()
    if not row:
        raise DomainError('Plano global não encontrado.', 404, 'not_found')
    return dict(row)


def summary(row):
    plan = json.loads(row['plan_json'])
    codes = Counter(a['classifier'] for a in plan['accounts'])
    return {k: row[k] for k in ('id', 'name', 'description', 'parent_id', 'filename', 'format', 'sha256', 'created_at', 'created_by')} | {
        'record_count': len(plan['accounts']), 'classifier_count': len(codes),
        'repeated_classifier_records': sum(v-1 for v in codes.values()),
        'properties': plan['properties'], 'immutable': True}


def assert_own_plan(conn, cid):
    row = conn.execute('SELECT mode FROM company_account_plan_bindings WHERE company_id=?', (cid,)).fetchone()
    if row and row['mode'] == 'shared':
        raise DomainError('Esta empresa usa uma versão global compartilhada. Duplique para plano próprio antes de adaptar contas.', 409, 'shared_account_plan')


def copy_scope(payload):
    scope=payload.get('copy_scope','all')
    if not isinstance(scope,str) or scope not in {'all','used'}:raise DomainError('Escolha cópia integral ou somente contas usadas.')
    return scope


def selected_global_accounts(conn,cid,row,scope):
    accounts=json.loads(row['plan_json'])['accounts']
    if scope=='all':return accounts,{'used_accounts':None,'parents_included':0,'missing_parent_classifiers':[]}
    used={r[0] for r in conn.execute('SELECT DISTINCT account_id FROM journal_lines WHERE company_id=?',(cid,))}
    used.update(r[0] for r in conn.execute('SELECT account_id FROM company_account_aliases WHERE company_id=? AND used=1',(cid,)))
    used.update(r[0] for r in conn.execute('SELECT id FROM accounts WHERE company_id=? AND shared_entry_id IS NOT NULL AND name IS NULL',(cid,)))
    for master in conn.execute("SELECT data_json FROM masters WHERE company_id=? AND kind='accounting_model'",(cid,)):
        data=json.loads(master['data_json'])
        used.update(data.get(k) for k in ('debit_account_id','credit_account_id') if isinstance(data.get(k),int))
    used_codes={r['access_code'] for r in conn.execute('SELECT id,access_code FROM accounts WHERE company_id=?',(cid,)) if r['id'] in used}
    # Aliases retain source identity even if a private adaptation renamed access.
    source_codes={r['access_code'] for r in conn.execute('''SELECT g.access_code,x.account_id FROM company_account_aliases x
        JOIN global_account_entries g ON g.id=x.global_entry_id WHERE x.company_id=? AND g.global_plan_id=? AND x.used=1''',(cid,row['id'])) if r['account_id'] in used}
    selected=[a for a in accounts if a['access_code'] in used_codes|source_codes]
    classifiers={a['classifier'] for a in selected}
    prefixes=set()
    for classifier in classifiers:
        parts=classifier.split('.')
        prefixes.update('.'.join(parts[:i]) for i in range(1,len(parts)))
    chosen_codes={a['access_code'] for a in selected}
    parents=[a for a in accounts if not a['analytical'] and a['classifier'] in prefixes|classifiers and a['access_code'] not in chosen_codes]
    existing_parents={a['classifier'] for a in accounts if not a['analytical']}
    selected_codes={a['access_code'] for a in selected+parents}
    return [a for a in accounts if a['access_code'] in selected_codes],{'used_accounts':len(selected),'parents_included':len(parents),'missing_parent_classifiers':sorted(prefixes-existing_parents)}


class GlobalAccountPlansMixin:
    def global_account_plans(self, cid):
        with self.db.read() as conn:
            company_row(conn, cid)
            effect(conn, cid, 'accounting.accounts', 'read')
            binding = conn.execute('SELECT * FROM company_account_plan_bindings WHERE company_id=?', (cid,)).fetchone()
            return {'binding': dict(binding) if binding else None,
                    'plans': [summary(dict(r)) for r in conn.execute('SELECT * FROM global_account_plans ORDER BY id DESC')]}

    def global_account_plan(self, cid, item_id, search='', page=1):
        page = integer(page, 'Página')
        if page < 1: raise DomainError('Página inválida.')
        query = text(search, 'Pesquisa', False, 200).casefold()
        with self.db.read() as conn:
            company_row(conn, cid); effect(conn, cid, 'accounting.accounts', 'read')
            row = global_plan(conn, item_id); plan = json.loads(row['plan_json'])
            accounts = [a for a in plan['accounts'] if not query or query in (a['access_code']+' '+a['classifier']+' '+a['name']).casefold()]
            return summary(row) | {'accounts': accounts[(page-1)*100:page*100], 'total': len(accounts),
                                   'page': page, 'per_page': 100, 'warnings': plan.get('warnings', [])[:100],
                                   'warning_count': len(plan.get('warnings', []))}

    def publish_global_account_plan(self, cid, batch_id, payload, actor):
        name = text(payload.get('name'), 'Nome global', True, 200)
        description = text(payload.get('description', ''), 'Descrição', False, 1000)
        reason = text(payload.get('reason'), 'Motivo', True, 1000)
        if payload.get('properties_reviewed') is not True or payload.get('global_visibility_reviewed') is not True:
            raise DomainError('Revise as propriedades e confirme a disponibilização integral para todas as empresas desta instalação.')
        with self.db.transaction() as conn:
            admin(conn, actor); effect(conn, cid, 'accounting.accounts', 'read')
            batch = select_one(conn, 'account_plan_batches', cid, batch_id)
            if payload.get('preview_hash') != batch['preview_hash']:
                raise DomainError('A prévia do lote mudou.', 409, 'stale_preview')
            plan = json.loads(batch['plan_json'])
            accesses = set()
            for raw in plan['accounts']:
                account = account_values(raw)
                if account['access_code'] in accesses:
                    raise DomainError('Acesso repetido na origem; não é possível publicar.', 409, 'account_plan_conflict')
                accesses.add(account['access_code'])
            parent = payload.get('parent_id')
            if parent is not None:
                parent = integer(parent, 'Versão de origem'); global_plan(conn, parent)
            # Retry-safe: the same reviewed source/name/parent is one immutable publication.
            previous = conn.execute('SELECT * FROM global_account_plans WHERE source_company_id=? AND source_batch_id=? AND name=? AND description=? AND parent_id IS ?',
                                    (cid, batch_id, name, description, parent)).fetchone()
            if previous: return summary(dict(previous)) | {'duplicate': True}
            item_id = conn.execute('''INSERT INTO global_account_plans(name,description,source_company_id,source_batch_id,parent_id,plan_json,filename,format,original,sha256,created_at,created_by)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''', (name, description, cid, batch_id, parent, batch['plan_json'], batch['filename'], batch['format'], batch['original'], batch['sha256'], now(), actor)).lastrowid
            for raw in plan['accounts']:
                a=account_values(raw);extras={k:v for k,v in a.items() if k not in {*FIELDS,'prosoft'}}
                conn.execute(f"INSERT INTO global_account_entries(global_plan_id,{','.join(FIELDS)},prosoft_json,extras_json) VALUES({','.join('?' for _ in range(len(FIELDS)+3))})",(item_id,*(a[k] for k in FIELDS),pack(a['prosoft']),pack(extras)))
            audit(conn, cid, actor, 'publish-global', 'account_plan', item_id, {'reason': reason, 'batch_id': batch_id, 'sha256': batch['sha256'], 'records': len(accesses)})
            return summary(global_plan(conn, item_id))

    def _global_account_preview(self, conn, cid, row, mode, scope="all"):
        current, properties = self._plan_state(conn, cid)
        binding = conn.execute('SELECT * FROM company_account_plan_bindings WHERE company_id=?', (cid,)).fetchone()
        plan = json.loads(row['plan_json']); selected,selection=selected_global_accounts(conn,cid,row,scope if mode=='own' else 'all'); by_access = {a['access_code']: a for a in current}
        created, preserved, conflicts = [], [], []
        for raw in selected:
            account = account_values(raw); old = by_access.get(account['access_code'])
            if old is None or old['id']<0:
                created.append(account)
            elif {k:v for k,v in old.items() if k not in {'id','version'}} == account:
                preserved.append(old)
            else:
                conflicts.append({'access_code': account['access_code'], 'reason': 'Acesso existente possui características diferentes. Nenhuma conta será substituída.'})
        adapted=conn.execute('''SELECT g.access_code,a.access_code AS local_code FROM company_account_aliases x JOIN global_account_entries g ON g.id=x.global_entry_id JOIN accounts a ON a.id=x.account_id AND a.company_id=x.company_id WHERE x.company_id=? AND g.global_plan_id=? AND a.access_code<>g.access_code''',(cid,row['id'])).fetchall()
        for alias in adapted:
            conflicts.append({'access_code':alias['access_code'],'reason':'Entrada global já vinculada a acesso adaptado nesta empresa; nenhuma identidade será substituída.'})
        if properties is not None and properties != plan['properties']:
            conflicts.append({'access_code': '', 'reason': 'Propriedades e máscara diferem do plano da empresa. Não será feita combinação automática.'})
        state = digest({'accounts': current, 'properties': properties, 'binding': dict(binding) if binding else None,'selection':[a['access_code'] for a in selected]})
        incoming = {a['access_code'] for a in plan['accounts']}
        return {'created': len(created), 'preserved': len(preserved), 'local_accounts_preserved': sum(a['id']>0 and a['access_code'] not in incoming for a in current),
                'can_confirm': not conflicts, 'conflicts': conflicts, 'to_create': created, 'state_hash': state,
                'record_count':len(selected),'global_record_count':len(plan['accounts']),'copy_scope':scope,'mode':mode}|selection

    def preview_global_account_plan(self, cid, item_id, payload, actor):
        mode = payload.get('mode', 'shared')
        if not isinstance(mode,str) or mode not in {'shared', 'own'}: raise DomainError('Escolha plano compartilhado ou próprio.')
        scope=copy_scope(payload) if mode=='own' else 'all'
        with self.db.transaction() as conn:
            effect(conn, cid, 'accounting.accounts', 'read')
            row = global_plan(conn, item_id); result = self._global_account_preview(conn, cid, row, mode, scope)
            fingerprint = digest({'global_plan_id': item_id, 'sha256': row['sha256'], 'state': result['state_hash'], 'mode': mode,'copy_scope':scope})
            pid = conn.execute('''INSERT INTO global_account_plan_previews(company_id,global_plan_id,mode,state_hash,preview_hash,created_at,created_by,copy_scope) VALUES(?,?,?,?,?,?,?,?)''',
                               (cid, item_id, mode, result['state_hash'], fingerprint, now(), actor,scope)).lastrowid
            return {k: v for k,v in result.items() if k not in {'to_create','state_hash','conflicts'}} | {'id': pid, 'preview_hash': fingerprint, 'conflict_count': len(result['conflicts']), 'conflicts': result['conflicts'][:100], 'plan': summary(row)}

    def confirm_global_account_plan(self, cid, preview_id, payload, actor):
        reason = text(payload.get('reason'), 'Motivo', True, 1000)
        if payload.get('properties_reviewed') is not True: raise DomainError('Confirme a revisão da estrutura, características e propriedades do plano.')
        with self.db.transaction() as conn:
            effect(conn, cid, 'accounting.accounts', 'create')
            preview = select_one(conn, 'global_account_plan_previews', cid, preview_id)
            if payload.get('preview_hash') != preview['preview_hash']: raise DomainError('A prévia mudou.', 409, 'stale_preview')
            if preview['result_json']: return json.loads(preview['result_json']) | {'duplicate': True}
            row = global_plan(conn, preview['global_plan_id']); plan = json.loads(row['plan_json'])
            result = self._global_account_preview(conn, cid, row, preview['mode'],preview['copy_scope'])
            if result['state_hash'] != preview['state_hash']: raise DomainError('O plano da empresa mudou. Gere nova prévia.', 409, 'stale_preview')
            if result['conflicts']: raise DomainError('Há conflitos; nenhuma conta foi alterada.', 409, 'account_plan_conflict')
            batch = None
            physical_created = 0
            if preview['mode']=='own':
                batch,physical_created=self._duplicate_global_accounts(conn,cid,row,actor,preview['preview_hash'],result['state_hash'],preview['copy_scope'])
            # Shared adoption writes only this binding/preview/audit, not accounts,
            # metadata, properties, source BLOBs or per-company plan JSON.
            conn.execute('''INSERT INTO company_account_plan_bindings(company_id,global_plan_id,mode,attached_at,attached_by,copy_scope) VALUES(?,?,?,?,?,?)
                ON CONFLICT(company_id) DO UPDATE SET global_plan_id=excluded.global_plan_id,mode=excluded.mode,version=version+1,attached_at=excluded.attached_at,attached_by=excluded.attached_by,copy_scope=excluded.copy_scope''', (cid, row['id'], preview['mode'], now(), actor,preview['copy_scope']))
            confirmed = {k:v for k,v in result.items() if k not in {'to_create','state_hash','conflicts'}} | {'global_plan_id': row['id'], 'batch_id': batch, 'created':physical_created, 'available':result['record_count'], 'references_materialized':0}
            conn.execute('UPDATE global_account_plan_previews SET result_json=? WHERE id=?', (pack(confirmed), preview_id))
            audit(conn, cid, actor, 'attach-global' if preview['mode']=='shared' else 'duplicate-global', 'account_plan', row['id'], confirmed | {'reason': reason})
            return confirmed

    def _duplicate_global_accounts(self,conn,cid,row,actor,fingerprint,state_hash,scope="all"):
        plan=json.loads(row['plan_json']);selected,selection=selected_global_accounts(conn,cid,row,scope)
        source_plan=plan|{'accounts':selected}
        raw=row['original'];sha=row['sha256'];format=row['format'];filename=row['filename']
        if scope=='used':
            raw=pack(source_plan).encode('utf-8');sha=digest(raw);format='native';filename=f'plano-proprio-usadas-{cid}.json'
        batch=conn.execute('''INSERT INTO account_plan_batches(company_id,filename,format,sha256,original,options_json,plan_json,preview_hash,state_hash,status,confirmation_json,created_at,created_by)
            VALUES(?,?,?,?,?,?,?,?,?,'confirmed',?,?,?)''',(cid,filename,format,sha,raw,pack({'identity_mode':'access','copy_scope':scope,'source_global_plan_id':row['id'],'source_global_sha256':row['sha256']}),pack(source_plan),fingerprint,state_hash,pack({'global_plan_id':row['id'],'own_copy':True}),now(),actor)).lastrowid
        created=0;selected_codes={a['access_code'] for a in selected}
        for entry in conn.execute('SELECT * FROM global_account_entries WHERE global_plan_id=? ORDER BY access_code',(row['id'],)):
            if entry['access_code'] not in selected_codes:continue
            old=conn.execute('SELECT id,shared_entry_id FROM accounts WHERE company_id=? AND access_code=?',(cid,entry['access_code'])).fetchone()
            if old is None:
                aid=conn.execute(f"INSERT INTO accounts(company_id,{','.join(FIELDS)},shared_entry_id) VALUES({','.join('?' for _ in range(len(FIELDS)+2))})",(cid,*(entry[k] for k in FIELDS),entry['id'])).lastrowid
                created+=1
            else:
                aid=old['id']
                if old['shared_entry_id'] is not None:
                    conn.execute(f"UPDATE accounts SET {','.join(k+'=?' for k in FIELDS)},version=version+1 WHERE company_id=? AND id=?",(*(entry[k] for k in FIELDS),cid,aid))
            conn.execute('INSERT INTO company_account_aliases(company_id,global_entry_id,account_id,used) VALUES(?,?,?,0) ON CONFLICT(company_id,global_entry_id) DO NOTHING',(cid,entry['id'],aid))
            conn.execute('INSERT INTO account_plan_metadata(company_id,account_id,prosoft_json,extras_json,batch_id) VALUES(?,?,?,?,?) ON CONFLICT(company_id,account_id) DO NOTHING',(cid,aid,entry['prosoft_json'],entry['extras_json'],batch))
            conn.execute('INSERT INTO global_account_plan_links(company_id,account_id,global_plan_id,access_code) VALUES(?,?,?,?) ON CONFLICT(company_id,account_id) DO NOTHING',(cid,aid,row['id'],entry['access_code']))
        extras={k:v for k,v in plan.items() if k not in {'schema','properties','accounts','format','encoding'}}
        conn.execute('INSERT INTO account_plan_properties(company_id,properties_json,extras_json) VALUES(?,?,?) ON CONFLICT(company_id) DO NOTHING',(cid,pack(plan['properties']),pack(extras)))
        return batch,created

    def detach_global_account_plan(self, cid, payload, actor):
        reason = text(payload.get('reason'), 'Motivo da adaptação', True, 1000)
        scope=copy_scope(payload)
        with self.db.transaction() as conn:
            company_row(conn, cid); effect(conn, cid, 'accounting.accounts', 'edit')
            binding = conn.execute('SELECT * FROM company_account_plan_bindings WHERE company_id=?', (cid,)).fetchone()
            if not binding: raise DomainError('Esta empresa não possui vínculo com plano global.', 404, 'not_found')
            check_version(binding, payload)
            details={'duplicate':True}
            if binding['mode'] != 'own':
                row=global_plan(conn,binding['global_plan_id'])
                selected,selection=selected_global_accounts(conn,cid,row,scope)
                batch,created=self._duplicate_global_accounts(conn,cid,row,actor,digest(dict(binding)),digest(self._plan_state(conn,cid)),scope)
                details=selection|{'copied_accounts':len(selected),'created':created,'batch_id':batch}
                conn.execute("UPDATE company_account_plan_bindings SET mode='own',copy_scope=?,version=version+1 WHERE company_id=?", (scope,cid))
                audit(conn, cid, actor, 'detach-global', 'account_plan', binding['global_plan_id'], {'reason': reason, 'ids_preserved': True,'copy_scope':scope})
            return dict(conn.execute('SELECT * FROM company_account_plan_bindings WHERE company_id=?', (cid,)).fetchone())|details
