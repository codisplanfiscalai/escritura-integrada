"""Exportação CTBLCTOS LC1/LC2 conforme o PDF fornecido, sem escrita no destino."""
import base64
import json
import re
import unicodedata
from .core import DomainError, audit, digest, now, pack, period, text

LAYOUT='CTBLCTOS-LC1-LC2-448-342'

def ascii_field(value,label,width,changes):
    value=str(value or '')
    transformed=unicodedata.normalize('NFKD',value).encode('ascii','ignore').decode('ascii')
    if any(ord(c)<32 or ord(c)>126 for c in transformed):raise DomainError(f'{label}: caracteres de controle não permitidos.')
    if transformed!=value:changes.append({'field':label,'original':value,'exported':transformed})
    if len(transformed)>width:raise DomainError(f'{label}: excede {width} posições. Revise sem truncamento automático.')
    return transformed.ljust(width)


def numeric(value,width,label,zero=False):
    value=str(value)
    if not re.fullmatch(r'\d{1,'+str(width)+'}',value) or (not zero and int(value)==0):
        raise DomainError(f'{label}: informe de 1 a {width} dígitos'+(' maiores que zero.' if not zero else '.'))
    return value.zfill(width)


def monetary(cents):
    if not 0<cents<=999999999999999:raise DomainError('Valor excede o leiaute CTBLCTOS.')
    return f'{cents//100:013d}.{cents%100:02d}'


def put(out,start,width,value):
    if len(value)!=width:raise ValueError('Comprimento inválido no exportador')
    out[start-1:start-1+width]=value


def encode_journals(journals,mappings,centers,batch,allow_ascii=False,participants=None):
    participants = participants or {}
    if not isinstance(participants,dict) or any(not isinstance(v,dict) for v in participants.values()):raise DomainError('Mapeamento de terceiros inválido.')
    if not isinstance(mappings,dict) or not isinstance(centers,dict) or any(not isinstance(v,dict) for v in [*mappings.values(),*centers.values()]):raise DomainError('Mapeamentos devem ser objetos de contas e centros.')
    records=[];trace=[];changes=[]
    if not journals or len(journals)>99999:raise DomainError('Selecione de 1 a 99999 lançamentos.')
    for order,j in enumerate(journals,1):
        if not 2<=len(j['lines'])<=200:raise DomainError(f'Lançamento {j["number"]}: CTBLCTOS permite até 200 partidas.')
        resolved=[]
        for line in j['lines']:
            m=mappings.get(str(line['account_id']),{})
            if m.get('confirmed') is not True:raise DomainError(f'Confirme o mapeamento da conta {line["access_code"]} no destino.')
            account=numeric(m.get('code',''),5,'Acesso contábil')
            third=str(m.get('third','')).strip()
            mode=m.get('third_mode','none')
            if mode not in {'none','optional','required'}:raise DomainError('Política de terceiros inválida.')
            third_type=m.get('third_type')
            if line.get('participant_id') and mode!='none':
                pm=participants.get(str(line['participant_id']),{})
                if pm.get('confirmed') is not True:raise DomainError('Confirme o código do terceiro da partida no destino.')
                third=str(pm.get('code','')).strip()
                if not third:raise DomainError('Informe o código do terceiro da partida no destino.')
                third_type=pm.get('third_type')
            if mode=='none' and third:raise DomainError('Conta sem referência a terceiro deve ter campo vazio.')
            if mode=='required' and not third:raise DomainError('Terceiro obrigatório não informado.')
            if third and not re.fullmatch(r'[A-Z0-9]{1,14}',third):raise DomainError('Código de terceiro inválido.')
            if third_type=='free' and len(third)==6:third+='L'
            cc='00000'
            if line.get('cost_center_id'):
                cm=centers.get(str(line['cost_center_id']),{})
                if cm.get('confirmed') is not True:raise DomainError('Confirme o centro de custo no destino.')
                cc=numeric(cm.get('code',''),5,'Centro de custo')
            resolved.append({'account':account,'third':third.ljust(14),'center':cc,
                'nature':'D' if line['debit_cents'] else 'C','value':line['debit_cents'] or line['credit_cents']})
        if sum(x['value']*(1 if x['nature']=='D' else -1) for x in resolved):raise DomainError('Lançamento desequilibrado.')
        header=list(' '*448)
        put(header,1,3,'LC1');put(header,4,5,numeric(order,5,'Ordem'))
        put(header,12,1,'1' if len(resolved)==2 else '2');put(header,13,8,''.join(reversed(j['date'].split('-'))))
        put(header,21,10,ascii_field(j['document'],'Documento '+str(j['number']),10,changes));put(header,31,5,numeric(batch,5,'Lote',True))
        put(header,36,30,'ESCRITURA INTEGRADA'.ljust(30))
        history=ascii_field(j['history'],'Histórico '+str(j['number']),240,changes)
        if len(resolved)==2:
            d=next(x for x in resolved if x['nature']=='D');c=next(x for x in resolved if x['nature']=='C')
            if (d['account'],d['third'],d['center'])==(c['account'],c['third'],c['center']):raise DomainError('Débito e crédito possuem a mesma identificação no destino.')
            for pos,val in [(69,d['account']),(74,d['third']),(88,d['center']),(93,c['account']),(98,c['third']),(112,c['center'])]:put(header,pos,len(val),val)
            put(header,117,16,monetary(d['value']));put(header,133,240,history)
            records.append(''.join(header))
        else:
            put(header,66,3,numeric(len(resolved),3,'Quantidade de contas'));records.append(''.join(header))
            for index,line in enumerate(resolved,1):
                detail=list(' '*342)
                for pos,width,value in [(1,3,'LC2'),(4,5,numeric(order,5,'Ordem')),(9,3,numeric(index,3,'Partida')),
                    (12,1,line['nature']),(13,5,line['account']),(18,14,line['third']),(32,5,line['center']),
                    (37,16,monetary(line['value'])),(53,240,history)]:put(detail,pos,width,value)
                records.append(''.join(detail))
        trace.append({'order':order,'journal_id':j['id'],'journal_number':j['number'],'line_count':len(resolved),'total_cents':j['total_cents']})
    raw=('\r\n'.join(records)+'\r\n').encode('ascii')
    return raw,{'layout':LAYOUT,'records':len(records),'journals':len(journals),'trace':trace,'text_changes':changes,
        'debit_cents':sum(j['total_cents'] for j in journals),'credit_cents':sum(j['total_cents'] for j in journals),
        'needs_ascii_review':bool(changes) and not allow_ascii,'homologated_in_destination':False}

class ProsoftMixin:
    def export_prosoft(self,cid,payload,actor,confirm=False):
        competence=period(payload.get('period'));code=numeric(payload.get('company_code',''),4,'Empresa Prosoft')
        ids=payload.get('journal_ids')
        with self.db.transaction() as conn:
            query='SELECT id FROM journals WHERE company_id=? AND period=? ORDER BY date,id'
            journals=[self._journal(conn,cid,r['id']) for r in conn.execute(query,(cid,competence))]
            if ids is not None:
                if not isinstance(ids,list) or not ids or len(set(ids))!=len(ids):raise DomainError('Seleção de lançamentos inválida.')
                if not set(ids)<={j['id'] for j in journals}:raise DomainError('Há lançamentos de outra empresa ou competência na seleção.')
                journals=[j for j in journals if j['id'] in ids]
            mappings=payload.get('accounts',{})
            if not isinstance(mappings,dict):raise DomainError('Mapeamentos de contas devem ser um objeto.')
            required={line['account_id'] for j in journals for line in j['lines']}
            aliases={-r['shared_entry_id']:r['id'] for r in conn.execute('SELECT id,shared_entry_id FROM accounts WHERE company_id=? AND shared_entry_id IS NOT NULL',(cid,))}
            aliases.update({-r['global_entry_id']:r['account_id'] for r in conn.execute('SELECT global_entry_id,account_id FROM company_account_aliases WHERE company_id=?',(cid,))})
            canonical={}
            for key,value in mappings.items():
                try:reference=int(key)
                except (TypeError,ValueError):continue
                resolved=aliases.get(reference,reference)
                if resolved not in required:continue
                if str(resolved) in canonical and canonical[str(resolved)]!=value:
                    raise DomainError('O alias global e a conta local possuem mapeamentos Prosoft divergentes.',409,'account_mapping_conflict')
                canonical[str(resolved)]=value
            from .journal_participants import participant_policy
            from .account_refs import resolve_account
            for journal in journals:
                for line in journal['lines']:
                    if participant_policy(conn,cid,resolve_account(conn,cid,line['account_id']))=='required':
                        if not line.get('participant_id'):raise DomainError('Partida histórica sem terceiro obrigatório. Revise antes de exportar.')
                        if canonical.get(str(line['account_id']),{}).get('third_mode')!='required':raise DomainError('Conta com terceiro obrigatório exige esse modo no destino.')
            raw,manifest=encode_journals(journals,canonical,payload.get('centers',{}),payload.get('batch','1'),payload.get('allow_ascii') is True,participants=payload.get('participants',{}))
            fingerprint=digest({'content_sha256':digest(raw),'configuration':canonical,
                'participants':payload.get('participants',{}),'centers':payload.get('centers'),'company_code':code,'period':competence,'journals':journals})
            filename=f'CTBLCTOS{code}_{competence.replace("-","")}.TXT'
            result={'preview_hash':fingerprint,'filename':filename,'manifest':manifest,'sha256':digest(raw),'sample':raw.decode('ascii').splitlines()[:5]}
            if not confirm:return result
            if payload.get('preview_hash')!=fingerprint:raise DomainError('Dados ou mapeamentos alterados. Gere uma nova prévia.',409,'stale_preview')
            if manifest['needs_ascii_review']:raise DomainError('Revise e aceite a conversão dos textos para ASCII antes de exportar.')
            if payload.get('destination_reviewed') is not True:raise DomainError('Confirme a empresa, as contas, terceiros e centros no destino.')
            existing=conn.execute('SELECT id FROM export_batches WHERE company_id=? AND layout=? AND fingerprint=?',(cid,LAYOUT,fingerprint)).fetchone()
            if existing:return result|{'id':existing['id'],'duplicate':True}
            item_id=conn.execute('INSERT INTO export_batches(company_id,period,layout,fingerprint,filename,content,manifest_json,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?)',
                (cid,competence,LAYOUT,fingerprint,filename,raw,pack(manifest),now(),actor)).lastrowid
            audit(conn,cid,actor,'export','prosoft',item_id,{'fingerprint':fingerprint,'sha256':digest(raw),'layout':LAYOUT,'journals':[j['id'] for j in journals]})
            return result|{'id':item_id}
