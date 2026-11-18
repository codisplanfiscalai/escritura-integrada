"""Versioned company service-book policy; immutable snapshots on booked notes."""
import json
import re
from .core import DomainError, audit, company_row, decimal_text, digest, now, pack, text
from .permissions import require

SCOPE = 'service-bookkeeping-profile-v1'
FIELDS = ('base', 'iss', 'iss_withheld')


def settings(conn, cid):
    company_row(conn,cid)
    row = conn.execute('SELECT result_json FROM operations WHERE company_id=? AND scope=? AND key=?',(cid,SCOPE,'default')).fetchone()
    return json.loads(row['result_json']) if row else {'version':0,'base':False,'iss':False,'iss_withheld':False,'source':'','responsible':''}


def save(db,cid,uid,actor,payload):
    if not isinstance(payload,dict) or set(payload)!={'version',*FIELDS,'source','responsible'}:
        raise DomainError('Informe versão, campos de escrituração, fonte e responsável.')
    if any(type(payload[k]) is not bool for k in FIELDS): raise DomainError('Seleções do perfil devem ser booleanas.')
    source=text(payload['source'],'Fonte do perfil',True,1000)
    responsible=text(payload['responsible'],'Responsável',True,200)
    with db.transaction() as conn:
        require(conn,uid,cid,'fiscal.parameters','edit')
        old=settings(conn,cid)
        if type(payload['version']) is not int or payload['version']!=old['version']: raise DomainError('Perfil alterado; recarregue.',409,'stale_version')
        result={k:payload[k] for k in FIELDS}|{'version':old['version']+1,'source':source,'responsible':responsible}
        conn.execute('''INSERT INTO operations(company_id,scope,key,request_hash,result_json,created_at) VALUES(?,?,?,?,?,?)
          ON CONFLICT(company_id,scope,key) DO UPDATE SET request_hash=excluded.request_hash,result_json=excluded.result_json''',(cid,SCOPE,'default',digest(result),pack(result),now()))
        audit(conn,cid,actor,'configure','service-bookkeeping',cid,result)
        return result


def apply(document,profile):
    if not profile['version']: raise DomainError('Cadastre o perfil de escrituração de serviços desta empresa.',409,'service_profile_required')
    taxes=document['taxes']; values={'accounting':document.get('total') or decimal_text(document['total_cents'])}
    for field,key in [('base','ISS.vBC'),('iss','ISS.vISSQN'),('iss_withheld','ISS.vISSRetido')]:
        if profile[field] and taxes.get(key) in (None,''):
            label={'base':'base de cálculo','iss':'ISSQN','iss_withheld':'ISSQN retido'}[field]
            raise DomainError('XML sem valor declarado para '+label+'; revise a nota antes de escriturar.',409,'service_amount_missing')
        if profile[field]:
            from .importers import _decimal
            try: values[field]=_decimal(str(taxes[key]),money=True,allow_negative=False)
            except ValueError: raise DomainError('Valor declarado inválido no perfil de serviços; confira a origem.',409,'service_amount_invalid') from None
        else: values[field]=None
    document['service_bookkeeping']={**document.get('service_bookkeeping',{}),'profile':dict(profile),'values':values}
    return document


def event_keys(conn,cid,environment=None):
    """An archived related event requires situation review, never auto-cancels."""
    from .file_store import read_file
    from .importers import _xml_tree
    from .nfse_import import NS
    keys=set()
    for row in conn.execute('SELECT result_json FROM operations WHERE company_id=? AND scope=?',(cid,'fiscal-reception-run-v1')):
        receipt=json.loads(row['result_json'])
        if receipt.get('provider')!='nfse_adn' or environment and receipt.get('environment')!=environment: continue
        for entry in receipt.get('entries',[]):
            if entry.get('document_type')!='EVENTO': continue
            key=entry.get('access_key')
            if isinstance(key,str) and re.fullmatch('[0-9A-Z]{50}',key): keys.add(key)
            elif entry.get('file_id'):
                file=read_file(conn,cid,entry['file_id'])
                if file['sha256']!=entry.get('sha256'): raise DomainError('Evento fiscal com integridade divergente.',409,'file_integrity')
                root=_xml_tree(file['content'])
                if root.tag!='{'+NS+'}evento': continue
                values=root.findall('{'+NS+'}infEvento/{'+NS+'}chNFSe')+root.findall('/'.join('{'+NS+'}'+p for p in ('infEvento','pedRegEvento','infPedReg','chNFSe')))
                if len(values)==1 and values[0].text: keys.add(values[0].text)
    return keys


def report(core,cid,competence):
    """Only stored book-policy snapshots, independent of today's settings."""
    from .core import period
    with core.db.read(snapshot=True) as conn:
        company=company_row(conn,cid)
        rows=[]
        for row in conn.execute("SELECT * FROM documents WHERE company_id=? AND period=? AND model='NFSE' AND status='booked' ORDER BY posting_date,id",(cid,period(competence))):
            d=core._document_values(row)
            if d.get('book_cancellation'): continue
            snapshot=d.get('service_bookkeeping',{})
            rows.append({'id':d['id'],'number':d['number'],'direction':d['direction'],'partner':d['partner_name'],
                'issue_date':d['issue_date'],'posting_date':d['posting_date'],'declared_competence':d.get('declared_competence',''),
                **snapshot.get('values',{}),'profile_version':snapshot.get('profile',{}).get('version')})
        return {'company_id':cid,'period':competence,'rows':rows}
