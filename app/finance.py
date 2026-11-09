"""Títulos, baixas, encargos, estornos e renegociação com efeitos explícitos."""
import json
from .core import (DomainError, audit, check_version, decimal_text, digest, integer,
                   iso_date, money, now, pack, select_one, text, ensure_open)
from .permissions import effect

class FinanceMixin:
    def _operation(self,conn,cid,scope,payload):
        key=text(payload.get('idempotency_key'),'Chave de idempotência',True,200)
        hashed=digest({k:v for k,v in payload.items() if k!='version'})
        old=conn.execute('SELECT * FROM operations WHERE company_id=? AND scope=? AND key=?',(cid,scope,key)).fetchone()
        if old and old['request_hash']!=hashed:
            raise DomainError('Chave já utilizada com conteúdo diferente.',409,'idempotency_conflict')
        if old and json.loads(old['result_json']).get('movement_deleted'):
            raise DomainError('Esta operação possui movimentos excluídos fisicamente. Inicie uma nova intenção com outra chave.',409,'movement_deleted')
        return key,hashed,(json.loads(old['result_json'])|{'duplicate':True}) if old else None

    def _record_operation(self,conn,cid,scope,key,hashed,result):
        conn.execute('INSERT INTO operations VALUES(?,?,?,?,?,?)',(cid,scope,key,hashed,pack(result),now()))

    def _title(self,conn,cid,item_id):
        r=super()._title(conn,cid,item_id)
        r['settlements']=[dict(x) for x in conn.execute('SELECT * FROM settlements WHERE company_id=? AND title_id=? ORDER BY date,id',(cid,item_id))]
        for s in r['settlements']:
            s.pop('request_hash',None)
        r['original_balance_cents']=r['balance_cents']
        if r['cancelled']:
            r['balance_cents']=0
            r['status']='renegotiated' if r['renegotiation_id'] else 'cancelled'
        r['allocations']=[dict(x) for x in conn.execute('SELECT id,transaction_id,amount_cents,settlement_id,reason FROM bank_allocations WHERE company_id=? AND title_id=? AND reversed_at IS NULL',(cid,item_id))]
        return r

    def _create_title(self,conn,cid,payload,actor):
        participant_id=payload.get('participant_id')
        if payload.get('document_id'):
            doc=self._document(conn,cid,integer(payload['document_id'],'Documento'))
            participant_id=participant_id or doc.get('participant_id')
            if participant_id and doc.get('participant_id') and participant_id!=doc['participant_id']:
                raise DomainError('Participante do título diverge do documento.')
        if participant_id:
            participant=self._master(conn,cid,integer(participant_id,'Participante'),'participant',True)
            payload=dict(payload,partner_name=participant['name'],participant_id=participant['id'])
        source=payload.get('source_key')
        if source:
            source=text(source,'Identificação do título',True,200)
            old=conn.execute('SELECT * FROM titles WHERE company_id=? AND source_key=?',(cid,source)).fetchone()
            hashed=digest({k:v for k,v in payload.items() if k!='idempotency_key'})
            if old:
                if old['request_hash']!=hashed:
                    raise DomainError('Identificação do título repetida com outro conteúdo.',409,'title_conflict')
                return self._title(conn,cid,old['id'])|{'duplicate':True}
        r=super()._create_title(conn,cid,payload,actor)
        if r['due_date']<r['issue_date']:
            raise DomainError('Vencimento anterior à emissão.')
        if participant_id:
            conn.execute('UPDATE titles SET participant_id=? WHERE id=?',(participant_id,r['id']))
        if source:
            conn.execute('UPDATE titles SET source_key=?,request_hash=?,installment=? WHERE id=?',(source,hashed,integer(payload.get('installment',1),'Parcela'),r['id']))
        return self._title(conn,cid,r['id'])

    def create_title(self,cid,payload,actor):
        with self.db.transaction() as conn:
            if payload.get('idempotency_key'):
                payload=dict(payload,source_key='manual:'+text(payload['idempotency_key'],'Chave',True,150))
            return self._create_title(conn,cid,payload,actor)

    def _settle(self,conn,cid,item_id,payload,actor):
        amount=money(payload.get('amount'),'Principal da baixa',positive=True)
        day=iso_date(payload.get('date'),'Data da baixa')
        effect(conn,cid,'financial.settlements','settle')
        ensure_open(conn,cid,day[:7],'financial')
        reason=text(payload.get('reason'),'Histórico da baixa',True,1000)
        key=text(payload.get('idempotency_key'),'Chave de idempotência',True,200)
        charges={k:money(payload.get(k,'0.00'),k) for k in ('interest','fine','discount')}
        cash=amount+charges['interest']+charges['fine']-charges['discount']
        if cash<0:
            raise DomainError('Desconto excede principal e encargos.')
        hashed=digest({'title_id':item_id,'amount':amount,'date':day,'reason':reason,'charges':charges,'lines':payload.get('lines',[])})
        title=self._title(conn,cid,item_id)
        existing=conn.execute('SELECT * FROM settlements WHERE company_id=? AND idempotency_key=?',(cid,key)).fetchone()
        if existing:
            legacy=digest({'title_id':item_id,'amount_cents':amount,'date':day,'reason':reason,'lines':payload.get('lines',[])})
            if existing['request_hash']!=hashed and (any(charges.values()) or existing['request_hash']!=legacy):
                raise DomainError('Chave de baixa já utilizada com conteúdo diferente.',409,'idempotency_conflict')
            return {'title':title,'settlement':dict(existing),'journal':self._journal(conn,cid,existing['journal_id']) if existing['journal_id'] else None,'duplicate':True}
        if payload.get('version') is not None:
            check_version(title,payload)
        if day<title['issue_date']:
            raise DomainError('Baixa não pode anteceder a emissão do título.')
        if title['cancelled']:
            raise DomainError('Título cancelado ou renegociado não aceita baixa.',409)
        if amount>title['balance_cents']:
            raise DomainError('A baixa excede o saldo do título.',409,'overpayment')
        journal=None
        if payload.get('lines'):
            _,total=self._normalize_lines(conn,cid,payload['lines'])
            if total!=amount+charges['interest']+charges['fine']:
                raise DomainError('Partidas devem contemplar principal, encargos e desconto: total contábil = principal + juros + multa.')
            journal=self._create_journal(conn,cid,{'date':day,'document':title['document'],'history':reason,'idempotency_key':'settlement:'+key,'lines':payload['lines']},actor)
        sid=conn.execute('''INSERT INTO settlements(company_id,title_id,date,amount_cents,reason,journal_id,idempotency_key,request_hash,created_at,interest_cents,fine_cents,discount_cents,cash_cents)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(cid,item_id,day,amount,reason,journal['id'] if journal else None,key,hashed,now(),charges['interest'],charges['fine'],charges['discount'],cash)).lastrowid
        conn.execute('UPDATE titles SET paid_cents=paid_cents+?,version=version+1 WHERE id=? AND company_id=?',(amount,item_id,cid))
        audit(conn,cid,actor,'settle','title',item_id,{'settlement_id':sid,'principal_cents':amount,'cash_cents':cash,'charges':charges,'journal_id':journal['id'] if journal else None})
        return {'title':self._title(conn,cid,item_id),'settlement':dict(conn.execute('SELECT * FROM settlements WHERE id=?',(sid,)).fetchone()),'journal':journal}

    def settle_title(self,cid,item_id,payload,actor):
        with self.db.transaction() as conn:
            return self._settle(conn,cid,item_id,payload,actor)

    def _reverse_linked_journal(self,conn,cid,jid,day,reason,actor,key):
        original=self._journal(conn,cid,jid)
        ensure_open(conn,cid,original['period'],'accounting')
        if original['reversed_by']:
            raise DomainError('Lançamento de origem já estornado. Confira o vínculo.',409)
        lines=[{'account_id':x['account_id'],'debit':decimal_text(x['credit_cents']),
                'credit':decimal_text(x['debit_cents']),'cost_center_id':x['cost_center_id']} for x in original['lines']]
        return self._create_journal(conn,cid,{'date':day,'document':original['document'],'history':reason,'idempotency_key':key,'lines':lines},actor,reversal_of=jid)

    def reverse_settlement(self,cid,item_id,payload,actor):
        reason=text(payload.get('reason'),'Motivo do estorno',True,1000)
        day=iso_date(payload.get('date'),'Data do estorno')
        with self.db.transaction() as conn:
            key,hashed,previous=self._operation(conn,cid,'reverse-settlement:'+str(item_id),payload)
            if previous:return previous
            s=select_one(conn,'settlements',cid,item_id)
            effect(conn,cid,'financial.settlements','reverse')
            ensure_open(conn,cid,day[:7],'financial')
            ensure_open(conn,cid,s['date'][:7],'financial')
            title=self._title(conn,cid,s['title_id'])
            if s['reversed_at'] or title['cancelled']:
                raise DomainError('Baixa já estornada ou título renegociado.',409)
            if day<s['date']:
                raise DomainError('Estorno não pode anteceder a baixa.')
            if conn.execute('SELECT 1 FROM bank_allocations WHERE settlement_id=? AND reversed_at IS NULL',(item_id,)).fetchone():
                raise DomainError('Desfaça primeiro o vínculo bancário desta baixa.',409,'reconciliation_exists')
            journal=self._reverse_linked_journal(conn,cid,s['journal_id'],day,reason,actor,'settlement-reversal:'+str(item_id)) if s['journal_id'] else None
            conn.execute('UPDATE settlements SET reversed_at=?,reversal_date=?,reversal_reason=?,reversal_journal_id=? WHERE id=?',(now(),day,reason,journal['id'] if journal else None,item_id))
            conn.execute('UPDATE titles SET paid_cents=paid_cents-?,version=version+1 WHERE id=? AND company_id=?',(s['amount_cents'],s['title_id'],cid))
            audit(conn,cid,actor,'reverse-settlement','title',s['title_id'],{'settlement_id':item_id,'reason':reason,'date':day,'journal_id':journal['id'] if journal else None})
            result={'title':self._title(conn,cid,s['title_id']),'journal':journal}
            self._record_operation(conn,cid,'reverse-settlement:'+str(item_id),key,hashed,result)
            return result

    def renegotiate(self,cid,payload,actor):
        ids=payload.get('title_ids',[])
        if not isinstance(ids,list) or not 1<=len(ids)<=100 or any(not isinstance(i,int) or isinstance(i,bool) for i in ids) or len(set(ids))!=len(ids):
            raise DomainError('Selecione de 1 a 100 títulos diferentes.')
        reason=text(payload.get('reason'),'Motivo da renegociação',True,1000)
        day=iso_date(payload.get('date'))
        interest=money(payload.get('interest','0.00'),'Encargos negociados')
        discount=money(payload.get('discount','0.00'),'Desconto negociado')
        with self.db.transaction() as conn:
            effect(conn,cid,'financial.titles','edit')
            ensure_open(conn,cid,day[:7],'financial')
            key,hashed,previous=self._operation(conn,cid,'renegotiate',payload)
            if previous:return previous
            titles=[self._title(conn,cid,integer(i,'Título')) for i in ids]
            if any(t['balance_cents']<=0 for t in titles) or len({(t['kind'],('id',t['participant_id']) if t['participant_id'] else ('name',t['partner_name'])) for t in titles})!=1:
                raise DomainError('Renegocie títulos com saldo, mesmo sentido e mesmo participante.')
            versions=payload.get('versions',{})
            if not isinstance(versions,dict):raise DomainError('Versões dos títulos inválidas.')
            for t in titles:
                ensure_open(conn,cid,t['issue_date'][:7],'financial')
                if str(t['id']) not in versions or versions[str(t['id'])]!=t['version']:
                    raise DomainError('Título alterado. Atualize a seleção para renegociar.',409,'stale_version')
                if day<t['issue_date']:
                    raise DomainError('Renegociação não pode anteceder a emissão.')
                if t['allocations'] or conn.execute('SELECT 1 FROM reconciliations WHERE title_id=?',(t['id'],)).fetchone():
                    raise DomainError('Desfaça a conciliação antes de renegociar.',409)
            principal=sum(t['balance_cents'] for t in titles)
            total=principal+interest-discount
            parts=self._installments(payload.get('installments'),total,day)
            rid=conn.execute('INSERT INTO renegotiations(company_id,date,reason,original_ids_json,principal_cents,interest_cents,discount_cents,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?)',
                (cid,day,reason,pack(ids),principal,interest,discount,now(),actor)).lastrowid
            created=[]
            for n,p in enumerate(parts,1):
                created.append(self._create_title(conn,cid,{'kind':titles[0]['kind'],'description':f'Renegociação {rid} - parcela {n}',
                    'partner_name':titles[0]['partner_name'],'participant_id':titles[0]['participant_id'],'document':f'REN-{rid}','issue_date':day,**p,
                    'installment':n,'source_key':f'renegotiation:{rid}:{n}'},actor))
            for t in titles:
                conn.execute('UPDATE titles SET cancelled=1,renegotiation_id=?,version=version+1 WHERE id=?',(rid,t['id']))
            result={'id':rid,'titles':created,'principal_cents':principal,'total_cents':total,'accounting_created':False}
            audit(conn,cid,actor,'renegotiate','renegotiation',rid,result|{'original_ids':ids,'reason':reason})
            self._record_operation(conn,cid,'renegotiate',key,hashed,result)
            return result

    @staticmethod
    def _installments(parts,total,issue):
        if not isinstance(parts,list) or not 1<=len(parts)<=240:
            raise DomainError('Informe de 1 a 240 parcelas.')
        result=[]
        for p in parts:
            if not isinstance(p,dict):raise DomainError('Parcela inválida.')
            day=iso_date(p.get('due_date'),'Vencimento')
            amount=money(p.get('amount'),'Valor da parcela',positive=True)
            if day<issue:raise DomainError('Vencimento anterior à emissão.')
            result.append({'due_date':day,'amount':decimal_text(amount)})
        if sum(money(x['amount']) for x in result)!=total:
            raise DomainError('A soma das parcelas deve corresponder ao valor financiado.',409,'installment_total')
        return result

    def renegotiations(self,cid):
        with self.db.read(snapshot=True) as conn:
            output=[]
            for r in conn.execute('SELECT * FROM renegotiations WHERE company_id=? ORDER BY id DESC',(cid,)):
                item=dict(r);item['original_ids']=json.loads(item.pop('original_ids_json'))
                item['new_title_ids']=[t['id'] for t in conn.execute('SELECT id FROM titles WHERE company_id=? AND source_key LIKE ?',(cid,f"renegotiation:{item['id']}:%"))]
                output.append(item)
            return output

    def reverse_renegotiation(self,cid,item_id,payload,actor):
        reason=text(payload.get('reason'),'Justificativa',True,1000)
        day=iso_date(payload.get('date'))
        with self.db.transaction() as conn:
            key,hashed,previous=self._operation(conn,cid,'reverse-renegotiation:'+str(item_id),payload)
            if previous:return previous
            agreement=select_one(conn,'renegotiations',cid,item_id)
            ensure_open(conn,cid,day[:7],'financial')
            ensure_open(conn,cid,agreement['date'][:7],'financial')
            if agreement['reversed_at']:raise DomainError('Renegociação já revertida.',409)
            if day<agreement['date']:raise DomainError('Reversão anterior ao acordo.')
            new=[self._title(conn,cid,t['id']) for t in conn.execute('SELECT id FROM titles WHERE company_id=? AND source_key LIKE ?',(cid,f'renegotiation:{item_id}:%'))]
            if any(t['cancelled'] or t['paid_cents'] or t['allocations'] or conn.execute('SELECT 1 FROM reconciliations WHERE title_id=?',(t['id'],)).fetchone() for t in new):
                raise DomainError('Novos títulos possuem movimentos. Reverta as operações dependentes antes do acordo.',409)
            old=[self._title(conn,cid,t) for t in json.loads(agreement['original_ids_json'])]
            if any(t['renegotiation_id']!=item_id for t in old):raise DomainError('Origem do acordo alterada; confira o histórico.',409)
            for t in new:conn.execute('UPDATE titles SET cancelled=1,version=version+1 WHERE id=?',(t['id'],))
            for t in old:conn.execute('UPDATE titles SET cancelled=0,renegotiation_id=NULL,version=version+1 WHERE id=?',(t['id'],))
            conn.execute('UPDATE renegotiations SET reversed_at=? WHERE id=?',(now(),item_id))
            result={'id':item_id,'reactivated_title_ids':[t['id'] for t in old],'cancelled_title_ids':[t['id'] for t in new]}
            audit(conn,cid,actor,'reverse','renegotiation',item_id,{'reason':reason,'date':day,**result})
            self._record_operation(conn,cid,'reverse-renegotiation:'+str(item_id),key,hashed,result)
            return result
