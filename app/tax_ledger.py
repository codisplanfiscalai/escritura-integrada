"""Finalização revisável e transporte por empresa/tributo, sem compensação cruzada."""
import json
from .core import DomainError,audit,digest,ensure_open,integer,now,pack,period,select_one,text


def previous_period(value):
    y,m=map(int,value.split('-'));return f'{y-1:04d}-12' if m==1 else f'{y:04d}-{m-1:02d}'


def ensure_unfinalized(conn,cid,competence,tax=None):
    sql='SELECT id,tax FROM tax_ledgers WHERE company_id=? AND period=? AND reversed_at IS NULL'
    args=[cid,competence]
    if tax:sql+=' AND tax=?';args.append(tax)
    row=conn.execute(sql,args).fetchone()
    if row:raise DomainError(f"Há apuração {row['tax'].upper()} finalizada (# {row['id']}). Reverta sua finalização antes de modificar as bases desta competência.",409,'assessment_finalized')

class TaxLedgerMixin:
    def _ledger_stale(self,conn,cid,row):
        assessment=select_one(conn,'tax_assessments',cid,row['assessment_id']);saved=json.loads(assessment['snapshot_json'])
        try:return digest(self._assessment_snapshot(conn,cid,saved['request']))!=row['fingerprint']
        except DomainError:return True

    def tax_ledgers(self,cid,competence):
        with self.db.read(snapshot=True) as conn:
            return [dict(r)|{'snapshot':json.loads(r['snapshot_json']),'stale':self._ledger_stale(conn,cid,r)} for r in conn.execute('SELECT * FROM tax_ledgers WHERE company_id=? AND period=? ORDER BY id DESC',(cid,period(competence)))]

    def previous_credit(self,cid,competence,tax):
        with self.db.read(snapshot=True) as conn:
            row=conn.execute('SELECT * FROM tax_ledgers WHERE company_id=? AND period=? AND tax=? AND reversed_at IS NULL',(cid,previous_period(period(competence)),tax)).fetchone()
            return {'period':previous_period(competence),'tax':tax,'ledger_id':row['id'] if row else None,'carry_credit_cents':row['carry_credit_cents'] if row else 0,'stale':self._ledger_stale(conn,cid,row) if row else False}

    def finalize_assessment(self,cid,item_id,payload,actor):
        reason=text(payload.get('reason'),'Justificativa da finalização',True,1000)
        if payload.get('coverage_reviewed') is not True:raise DomainError('Confirme a revisão das bases, documentos não tributados, ajustes e saldos deste tributo.')
        with self.db.transaction() as conn:
            key,hashed,old=self._operation(conn,cid,'finalize-assessment',payload|{'assessment_id':item_id})
            if old:return old
            assessment=select_one(conn,'tax_assessments',cid,item_id);p=assessment['period'];tax=assessment['tax']
            if payload.get('period')!=p:raise DomainError('Memória pertence a outra competência.',409)
            ensure_open(conn,cid,p,'fiscal');ensure_unfinalized(conn,cid,p,tax)
            if conn.execute('SELECT 1 FROM tax_ledgers WHERE company_id=? AND tax=? AND period>? AND reversed_at IS NULL',(cid,tax,p)).fetchone():
                raise DomainError('Existem apurações posteriores finalizadas. Reverta-as na ordem inversa antes de finalizar este período.',409,'dependent_assessment')
            saved=json.loads(assessment['snapshot_json']);snapshot=self._assessment_snapshot(conn,cid,saved['request'])
            if digest(snapshot)!=assessment['fingerprint']:raise DomainError('A origem mudou. Gere e revise uma nova memória antes de finalizar.',409,'stale_assessment')
            previous=snapshot.get('opening_source',{}).get('ledger_id')
            lid=conn.execute('''INSERT INTO tax_ledgers(company_id,period,tax,assessment_id,previous_id,opening_credit_cents,carry_credit_cents,payable_cents,snapshot_json,fingerprint,reason,created_at,created_by)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(cid,p,tax,item_id,previous,snapshot['opening_credit_cents'],snapshot['carry_credit_cents'],snapshot['payable_cents'],pack(snapshot),assessment['fingerprint'],reason,now(),actor)).lastrowid
            result={'id':lid,'assessment_id':item_id,'period':p,'tax':tax,'snapshot':snapshot}
            audit(conn,cid,actor,'finalize','tax_ledger',lid,{'reason':reason,'assessment_id':item_id,'previous_id':previous,'period':p,'tax':tax,'fingerprint':assessment['fingerprint']})
            self._record_operation(conn,cid,'finalize-assessment',key,hashed,result);return result

    def reverse_ledger(self,cid,item_id,payload,actor):
        reason=text(payload.get('reason'),'Justificativa da reversão',True,1000)
        with self.db.transaction() as conn:
            row=select_one(conn,'tax_ledgers',cid,item_id)
            if payload.get('period')!=row['period']:raise DomainError('Apuração pertence a outra competência.',409)
            ensure_open(conn,cid,row['period'],'fiscal')
            if row['reversed_at']:raise DomainError('Finalização já revertida.',409)
            if conn.execute('SELECT 1 FROM tax_ledgers WHERE company_id=? AND tax=? AND period>? AND reversed_at IS NULL',(cid,row['tax'],row['period'])).fetchone():
                raise DomainError('Reverta primeiro as apurações posteriores deste mesmo tributo.',409,'dependent_assessment')
            conn.execute('UPDATE tax_ledgers SET reversed_at=?,reversed_by=?,reversal_reason=? WHERE id=?',(now(),actor,reason,item_id))
            audit(conn,cid,actor,'reverse','tax_ledger',item_id,{'reason':reason,'period':row['period'],'tax':row['tax']})
            return {'id':item_id,'reversed':True}

    def ledger_report(self,cid,item_id):
        with self.db.read(snapshot=True) as conn:
            ledger=select_one(conn,'tax_ledgers',cid,item_id);snapshot=json.loads(ledger['snapshot_json']);company=conn.execute('SELECT name FROM companies WHERE id=?',(cid,)).fetchone()
            rows=[dict(row) for row in snapshot['entries']]
            for a in snapshot['adjustments']:rows.append({'description':'Ajuste '+a.get('category','other'),'effect':a['kind'],'result_cents':a['amount_cents'],'source':a['source'],'reason':a['reason']})
            return {'ledger_id':item_id,'kind':'assessment-memory','title':f"Memória {ledger['tax'].upper()} · apuração #{item_id}",'company_id':cid,'company_name':company['name'],'start':ledger['period'],'end':ledger['period'],
               'rows':rows,'totals':{k:snapshot[k] for k in ['opening_credit_cents','debit_cents','credit_cents','payable_cents','carry_credit_cents']},
               'scope_note':snapshot['scope_note']+(' Finalização revertida.' if ledger['reversed_at'] else '')+(' Origens alteradas: exige revisão.' if self._ledger_stale(conn,cid,ledger) else ''),
               'filters':{'assessment_id':ledger['assessment_id'],'previous_id':ledger['previous_id'],'fingerprint':ledger['fingerprint'],'responsible':ledger['created_by'],'reason':ledger['reason']}}
