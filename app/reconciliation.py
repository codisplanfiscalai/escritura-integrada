"""Conciliação bancária por alocações, com baixa apenas quando solicitada."""
from datetime import date
from .core import DomainError, audit, decimal_text, integer, money, now, select_one, text

class ReconciliationMixin:
    def _bank(self,conn,cid,item_id):
        bank=super()._bank(conn,cid,item_id)
        allocations=[dict(x) for x in conn.execute('''SELECT a.*,t.description AS title_description
            FROM bank_allocations a JOIN titles t ON t.id=a.title_id
            WHERE a.company_id=? AND a.transaction_id=? AND a.reversed_at IS NULL ORDER BY a.id''',(cid,item_id))]
        bank['allocations']=allocations
        bank['allocated_cents']=abs(bank['amount_cents']) if bank['reconciliation'] else sum(x['amount_cents'] for x in allocations)
        bank['remaining_cents']=abs(bank['amount_cents'])-bank['allocated_cents']
        bank['reconciled']=bank['remaining_cents']==0
        return bank

    def bank_suggestions(self,cid,item_id):
        with self.db.read() as conn:
            bank=self._bank(conn,cid,item_id)
            if bank['reconciled']:return []
            kind='receivable' if bank['amount_cents']>0 else 'payable'
            result=[]
            for r in conn.execute('SELECT id FROM titles WHERE company_id=? AND kind=? AND cancelled=0 ORDER BY due_date',(cid,kind)):
                t=self._title(conn,cid,r['id'])
                allocated=sum(x['amount_cents'] for x in t['allocations'])
                if conn.execute('SELECT 1 FROM reconciliations WHERE title_id=?',(t['id'],)).fetchone():continue
                available=t['amount_cents']-allocated
                delta=abs((date.fromisoformat(t['due_date'])-date.fromisoformat(bank['date'])).days)
                if available>0 and delta<=30:
                    exact=available==bank['remaining_cents']
                    result.append({'title_id':t['id'],'description':t['description'],'amount_cents':available,
                        'balance_cents':t['balance_cents'],'date':t['due_date'],'difference_days':delta,
                        'score':(100 if exact else 30)+(20 if t['document'] and t['document']==bank['reference'] else 0)-min(delta,30),
                        'reason':('Mesmo valor disponível' if exact else 'Possível parcela ou agrupamento')+'; confirme documento e participante.'})
            return sorted(result,key=lambda x:(-x['score'],x['title_id']))[:30]

    def allocate_bank(self,cid,item_id,payload,actor):
        reason=text(payload.get('reason'),'Conferência da conciliação',True,1000)
        entries=payload.get('allocations',[])
        if not isinstance(entries,list) or not 1<=len(entries)<=100:
            raise DomainError('Informe de 1 a 100 alocações.')
        with self.db.transaction() as conn:
            scope='bank-allocate:'+str(item_id)
            key,hashed,previous=self._operation(conn,cid,scope,payload)
            if previous:return previous
            bank=self._bank(conn,cid,item_id)
            if bank['reconciled']:raise DomainError('Movimento já conciliado.',409)
            if any(not isinstance(e,dict) for e in entries):raise DomainError('Alocação inválida.')
            if len({e.get('title_id') for e in entries})!=len(entries):raise DomainError('Título repetido no rateio.')
            total=sum(money(e.get('amount'),'Valor da alocação',positive=True) for e in entries)
            if total>bank['remaining_cents']:raise DomainError('Rateio excede o saldo bancário disponível.')
            ids=[]
            for index,e in enumerate(entries):
                tid=integer(e.get('title_id'),'Título');t=self._title(conn,cid,tid)
                amount=money(e.get('amount'),positive=True)
                if t['cancelled'] or t['kind']!=('receivable' if bank['amount_cents']>0 else 'payable'):
                    raise DomainError('Título incompatível com o sentido do movimento.')
                if conn.execute('SELECT 1 FROM reconciliations WHERE title_id=?',(tid,)).fetchone():
                    raise DomainError('Título já possui conciliação individual.',409)
                available=t['amount_cents']-sum(x['amount_cents'] for x in t['allocations'])
                if amount>available:raise DomainError('Rateio excede o valor do título ainda não conciliado.',409)
                settlement=None
                if payload.get('settle') is True:
                    settlement=self._settle(conn,cid,tid,{'amount':decimal_text(amount),'date':bank['date'],
                        'reason':reason,'version':e.get('version'),'idempotency_key':f'bank:{item_id}:{key}:{index}',
                        'lines':e.get('lines',[])},actor)['settlement']
                aid=conn.execute('INSERT INTO bank_allocations(company_id,transaction_id,title_id,amount_cents,settlement_id,reason,created_at,created_by) VALUES(?,?,?,?,?,?,?,?)',
                    (cid,item_id,tid,amount,settlement['id'] if settlement else None,reason,now(),actor)).lastrowid
                ids.append(aid)
            result={'bank':self._bank(conn,cid,item_id),'allocation_ids':ids,'settlements_created':len(ids) if payload.get('settle') is True else 0}
            audit(conn,cid,actor,'allocate','bank_transaction',item_id,{'reason':reason,'ids':ids,'settle':payload.get('settle') is True})
            self._record_operation(conn,cid,scope,key,hashed,result)
            return result

    def reverse_allocation(self,cid,item_id,payload,actor):
        reason=text(payload.get('reason'),'Motivo para desfazer o vínculo',True,1000)
        with self.db.transaction() as conn:
            a=select_one(conn,'bank_allocations',cid,item_id)
            if a['reversed_at']:raise DomainError('Vínculo já desfeito.',409)
            conn.execute('UPDATE bank_allocations SET reversed_at=? WHERE id=?',(now(),item_id))
            audit(conn,cid,actor,'unallocate','bank_transaction',a['transaction_id'],{'allocation_id':item_id,'reason':reason,'settlement_preserved':a['settlement_id']})
            return {'bank':self._bank(conn,cid,a['transaction_id']),'settlement_preserved':a['settlement_id']}

    def partner_reconciliation(self,cid):
        # Origin/settlement comparison is independent of bank reconciliation.
        result=[]
        for t in self.titles(cid):
            settled=sum(s['amount_cents'] for s in t['settlements'] if not s['reversed_at'])
            result.append({'title_id':t['id'],'partner_name':t['partner_name'],'kind':t['kind'],
                'document':t['document'],'document_id':t['document_id'],'due_date':t['due_date'],
                'amount_cents':t['amount_cents'],'paid_cents':settled,'balance_cents':t['balance_cents'],
                'status':t['status'],'consistent':settled==t['paid_cents'],
                'settlement_ids':[s['id'] for s in t['settlements']],'bank_ids':[a['transaction_id'] for a in t['allocations']]})
        return result
