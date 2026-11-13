"""Catálogos locais versionados; migração dos serviços CatalogController/seed do Auditor 1.2.2."""
import gzip
import json
import re
from pathlib import Path
from .core import DomainError, audit, check_version, digest, iso_date, now, pack, select_one, text
from .permissions import effect


def contents(row):
    return json.loads(row['content_json']), json.loads(row.get('reference_json') or '{}')


def diagnostics(entries, reference):
    csts = {r['cst'] for r in reference.get('cst', [])}
    classes = {r['cclass_trib']: r for r in reference.get('cclass', [])}
    issues = []
    seen = set()
    for n, row in enumerate(entries):
        def issue(code, message, severity='error'):
            issues.append({'index': n, 'source_row': row.get('source_row'), 'ncm': row.get('ncm'), 'ex_code': row.get('ex_code'), 'code': code, 'severity': severity, 'message': message})
        # The audit engine ignores hierarchy headings: they are not tax rules.
        if row.get('ncm_level') == 'hierarchy':
            continue
        key = (row.get('ncm'), row.get('ex_code') or '')
        if key in seen and row.get('ncm_level','item') == 'item': issue('PARAMETER_CONFLICT', 'NCM/EX repetido; revise as ocorrências.')
        seen.add(key)
        cst, cc = row.get('cst'), row.get('cclass_trib')
        if not cst and not cc:
            if row.get('ncm_level') == 'hierarchy': continue
            issue('MISSING_CLASSIFICATION', 'NCM sem classificação; não haverá confirmação de enquadramento.', 'warning')
            continue
        if not re.fullmatch(r'\d{3}', str(cst or '')) or (csts and cst not in csts):
            issue('INVALID_CST', 'CST ausente ou inexistente na referência desta versão.')
        if not re.fullmatch(r'\d{6}', str(cc or '')) or (classes and cc not in classes):
            issue('UNKNOWN_CCLASS', 'cClassTrib ausente ou inexistente na referência desta versão.')
        if cst and cc and (not cc.startswith(cst) or (cc in classes and classes[cc]['cst'] != cst)):
            issue('CST_CCLASS_MISMATCH', 'CST e cClassTrib incompatíveis.')
        reduction = re.search(r'(\d+(?:[.,]\d+)?)\s*%', row.get('reduction_type') or '')
        if reduction and cc in classes:
            from decimal import Decimal
            rates = [Decimal(str(classes[cc].get(k) or 0)) for k in ('ibs_reduction_percent', 'cbs_reduction_percent')]
            if Decimal(reduction[1].replace(',', '.')) not in rates:
                issue('REDUCTION_CONFLICT', 'Redução descrita diverge da referência CST/cClassTrib.')
    return issues


def catalog_detail(core, cid, iid):
    with core.db.read() as conn:
        row = select_one(conn, 'auditor_catalogs', cid, iid)
    entries, reference = contents(row)
    issues = diagnostics(entries, reference)
    return {k: v for k, v in row.items() if k not in {'content_json', 'reference_json'}} | {
        'entry_count': len(entries), 'item_count': sum(r.get('ncm_level', 'item') == 'item' for r in entries),
        'reference': reference, 'issues': issues, 'error_count': sum(i['severity'] == 'error' for i in issues)}


def catalog_entries(core, cid, iid, search='', status='', page=1, per_page=50, kind='parameters'):
    if not 1 <= per_page <= 200 or page < 1: raise DomainError('Paginação inválida.')
    with core.db.read() as conn: row = select_one(conn, 'auditor_catalogs', cid, iid)
    entries, reference = contents(row)
    if kind not in {'parameters', 'cst', 'cclass'}: raise DomainError('Tabela de catálogo inválida.')
    issues = diagnostics(entries, reference)
    errors = {i['index'] for i in issues if i['severity'] == 'error'} if kind == 'parameters' else set()
    warnings = {i['index'] for i in issues if i['severity'] != 'error'} if kind == 'parameters' else set()
    rows = [{**r, '_index': n, '_status': 'error' if n in errors else 'warning' if n in warnings else 'valid'} for n, r in enumerate(entries if kind == 'parameters' else reference.get(kind, []))]
    if search: rows = [r for r in rows if search.casefold() in json.dumps(r, ensure_ascii=False).casefold()]
    if status: rows = [r for r in rows if r['_status'] == status]
    return {'rows': rows[(page-1)*per_page:page*per_page], 'total': len(rows), 'page': page, 'per_page': per_page, 'version': row['version']}


def load_reference():
    root = Path(__file__).with_name('auditor_engine') / 'data'
    manifest = json.loads((root/'manifest.json').read_text())
    def read(name):
        with gzip.open(root/name, 'rt', encoding='utf-8') as f: return [json.loads(line) for line in f]
    entries = [dict(r, cst=r.get('expected_cst'), cclass_trib=r.get('expected_cclass_trib')) for r in read('ncm_class_trib.jsonl.gz')]
    reference = {'manifest': manifest, 'cst': read('cst_catalog.jsonl.gz'), 'cclass': read('cclass_catalog.jsonl.gz'),
                 'historical': True, 'notice': 'Referência histórica do Auditor 1.2.2. Exige revisão dos erros, condições e vigência antes de publicar. Não equivale a tabela atualizada automaticamente.'}
    return entries, reference


def revise_catalog(core, cid, payload, actor, iid=None):
    with core.db.transaction() as conn:
        effect(conn, cid, 'auditor.catalogs', 'create')
        if iid:
            previous = select_one(conn, 'auditor_catalogs', cid, iid)
            entries, reference = contents(previous)
            source = previous['source']; source_id = previous['source_id']
        else:
            effect(conn, cid, 'auditor.catalogs', 'import')
            entries, reference = load_reference()
            source = 'Auditor Fiscal 1.2.2 / ' + reference['manifest']['version']; source_id = None
        if payload.get('apply_verified_errata') is True:
            from .auditor_catalog_corrections import corrected_reference
            entries, reference = corrected_reference(entries, reference)
        start = iso_date(payload.get('valid_from')); end = iso_date(payload.get('valid_to'))
        if start > end: raise DomainError('Vigência final anterior à inicial.')
        name = text(payload.get('name'), 'Nome da versão', True, 150)
        hashed = digest({'entries': entries, 'reference': reference, 'source': source, 'valid_from': start, 'valid_to': end})
        new = conn.execute('''INSERT INTO auditor_catalogs(company_id,name,source,valid_from,valid_to,content_json,reference_json,sha256,created_at,created_by,parent_id,source_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''', (cid,name,source,start,end,pack(entries),pack(reference),hashed,now(),actor,iid,source_id)).lastrowid
        audit(conn,cid,actor,'revision' if iid else 'import_reference','auditor_catalog',new,{'parent_id':iid,'sha256':hashed,'historical':reference.get('historical')})
    return catalog_detail(core,cid,new)


def edit_entry(core,cid,iid,payload,actor,index=None,delete=False):
    with core.db.transaction() as conn:
        row = select_one(conn,'auditor_catalogs',cid,iid);check_version(row,payload)
        if row['state'] != 'draft': raise DomainError('Versão publicada é imutável. Crie uma revisão.',409)
        entries, reference = contents(row)
        if index is not None and not 0 <= index < len(entries): raise DomainError('Linha não encontrada.',404)
        if delete:
            old = entries.pop(index)
        else:
            entry = dict(payload.get('entry') or {})
            hierarchy = entry.get('ncm_level') == 'hierarchy'
            for field, pattern in [('ncm',r'[0-9]{2,7}' if hierarchy else r'[0-9]{8}'),('cst',r'[0-9]{3}'),('cclass_trib',r'[0-9]{6}')]:
                if hierarchy and field in ('cst','cclass_trib') and not entry.get(field): continue
                if not isinstance(entry.get(field),str) or not re.fullmatch(pattern,entry[field]): raise DomainError('Confira NCM (8 dígitos; 2 a 7 em agrupamentos), CST (3) e cClassTrib (6 dígitos).')
            ex = entry.get('ex_code') or ''
            if not isinstance(ex,str) or (ex and not re.fullmatch(r'[0-9]{1,3}',ex)): raise DomainError('EX inválido.')
            entry.update(ex_code=ex.zfill(2) if ex else '',ncm_level='hierarchy' if hierarchy else 'item',status='valid',validation_issues=[])
            for field in ('valid_from','valid_to'):
                entry[field]=iso_date(entry[field]) if entry.get(field) else None
            if entry.get('valid_from') and entry.get('valid_to') and entry['valid_from']>entry['valid_to']:
                raise DomainError('Vigência final da regra anterior à inicial.')
            if entry.get('conditions') is not None and not isinstance(entry['conditions'],(dict,list)):
                raise DomainError('Condições devem ser uma lista ou objeto JSON.')
            if entry.get('reference_rate') not in (None,''):
                from decimal import Decimal,InvalidOperation
                try:rate=Decimal(str(entry['reference_rate']).replace(',','.'))
                except InvalidOperation:raise DomainError('Alíquota de referência inválida.')
                if not rate.is_finite() or rate<0:raise DomainError('Alíquota de referência inválida.')
                entry['reference_rate']=str(rate)
            entry={k:v for k,v in entry.items() if not k.startswith('_')}
            entry['description'] = text(entry.get('description'),'Descrição',True,2000)
            old = entries[index] if index is not None else None
            if old: entry = {**old,**entry}
            if index is None:
                if len(entries)>=25000: raise DomainError('Limite de 25.000 regras.')
                entry.update(source_sheet='MANUAL',source_row=None);entries.append(entry)
            else: entries[index] = entry
        hashed = digest({'entries':entries,'reference':reference,'source':row['source'],'valid_from':row['valid_from'],'valid_to':row['valid_to']})
        conn.execute('UPDATE auditor_catalogs SET content_json=?,sha256=?,version=version+1 WHERE id=?',(pack(entries),hashed,iid))
        audit(conn,cid,actor,'delete_entry' if delete else 'edit_entry','auditor_catalog',iid,{'index':index,'before':old,'after':None if delete else entry,'sha256':hashed})
    return catalog_detail(core,cid,iid)


def compare_catalogs(core,cid,left,right):
    with core.db.read() as conn:
        a,_ = contents(select_one(conn,'auditor_catalogs',cid,left));b,_ = contents(select_one(conn,'auditor_catalogs',cid,right))
    def keyed(rows): return {(r['ncm'],r.get('ex_code') or ''):r for r in rows if r.get('ncm')}
    a,b=keyed(a),keyed(b);changes=[]
    fields=('ncm_level','cst','cclass_trib','description','reference_rate','reduction_type','legal_reference_raw','conditions','valid_from','valid_to')
    for key in sorted(set(a)|set(b)):
        old,new=a.get(key),b.get(key)
        if old is None or new is None or any(old.get(f)!=new.get(f) for f in fields):
            changes.append({'ncm':key[0],'ex_code':key[1],'change':'added' if old is None else 'removed' if new is None else 'changed','before':old,'after':new})
    return {'from':left,'to':right,'total':len(changes),'changes':changes}
