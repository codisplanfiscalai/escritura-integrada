"""Pré-apuração explícita: decisões fiscais revisadas, memória imutável e detecção de alteração."""
import json
from decimal import Decimal, ROUND_HALF_UP
from .core import (DomainError, audit, digest, ensure_open, integer, money, now, pack, period, select_one, text, company_row)

class TaxAssessmentMixin:
    def _assessment_snapshot(self,conn,cid,payload):
        competence=period(payload.get('period'));tax=text(payload.get('tax'),'Tributo',True,20).lower()
        if tax not in {'icms','ipi','iss','pis','cofins','ibs','cbs'}:raise DomainError('Tributo não suportado.')
        entries=payload.get('entries',[])
        if not isinstance(entries,list) or len(entries)>1000 or (not entries and payload.get('no_movement_confirmed') is not True):raise DomainError('Inclua bases conferidas ou confirme expressamente a ausência de bases no cenário.')
        company=company_row(conn,cid)
        output=[];seen=set();covered={}
        for entry in entries:
            if not isinstance(entry,dict):raise DomainError('Base fiscal inválida.')
            did=integer(entry.get('document_id'),'Documento');rid=integer(entry.get('rule_id'),'Regra')
            doc=self._document(conn,cid,did);rule=select_one(conn,'rules',cid,rid)
            effect=entry.get('effect')
            if effect not in {'debit','credit'}:raise DomainError('Classifique como débito ou crédito após análise fiscal.')
            indices=entry.get('item_indices',[])
            if not isinstance(indices,list) or any(type(i) is not int or i<0 or i>=len(doc['items']) for i in indices) or len(indices)!=len(set(indices)):
                raise DomainError('Seleção de itens inválida.')
            selected=[doc['items'][i] for i in indices] if indices else doc['items']
            marks=set(indices) if indices else set(range(len(doc['items']))) or {-1}
            prior=covered.setdefault((did,effect),set())
            if prior.intersection(marks):raise DomainError('Documento ou item repetido no mesmo efeito tributário; revise as bases.')
            prior.update(marks)
            if doc['status']!='booked' or doc['period']!=competence:raise DomainError('Use documentos escriturados da competência.')
            if rule['tax'].lower()!=tax or rule['status']!='validated' or not rule['active'] or rule['superseded_by']:
                raise DomainError('Selecione regra vigente, ativa e conferida do tributo.')
            if not rule['valid_from']<=doc['posting_date'] or (rule['valid_to'] and doc['posting_date']>rule['valid_to']):
                raise DomainError('Documento fora da vigência da regra.')
            if rule['direction'] not in {'both',doc['direction']}:raise DomainError('Regra incompatível com o sentido do documento.')
            if rule['cfop'] and (any((i.get('cfop') or doc['cfop'])!=rule['cfop'] for i in selected) if indices else rule['cfop']!=doc['cfop']):raise DomainError('CFOP da base não corresponde à regra.')
            if rule['ncm'] and (not selected or any(x.get('ncm')!=rule['ncm'] for x in selected)):
                raise DomainError('Selecione somente os itens enquadrados no NCM da regra.')
            for field,target in [('regime','regime'),('state','state'),('municipality','ibge')]:
                if rule[field] and rule[field]!=company[target]:raise DomainError('Regra incompatível com regime, UF ou município da empresa.')
            base=money(entry.get('base'),'Base conferida')
            justification=text(entry.get('reason'),'Fundamento da base/crédito',True,1000)
            result=int((Decimal(base)*Decimal(rule['rate'])/100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
            output.append({'document_id':did,'document_number':doc['number'],'document_version':doc['version'],'item_indices':indices,'rule_id':rid,
                'rule_version':rule['version'],'regime':rule['regime'],'state':rule['state'],'municipality':rule['municipality'],'source':rule['source'],'responsible':rule['responsible'],
                'valid_from':rule['valid_from'],'valid_to':rule['valid_to'],'base_cents':base,'rate':rule['rate'],
                'result_cents':result,'effect':effect,'reason':justification,'rounding':'ROUND_HALF_UP','formula':'base_cents * rate / 100'})
        adjustments=[dict(r) for r in conn.execute('SELECT * FROM tax_adjustments WHERE company_id=? AND period=? AND tax=? AND reversed_at IS NULL ORDER BY id',(cid,competence,tax))]
        debit=sum(x['result_cents'] for x in output if x['effect']=='debit')+sum(x['amount_cents'] for x in adjustments if x['kind']=='debit')
        credit=sum(x['result_cents'] for x in output if x['effect']=='credit')+sum(x['amount_cents'] for x in adjustments if x['kind']=='credit')
        opening=money(payload.get('opening_credit','0.00'),'Saldo credor anterior')
        opening_source={'type':'manual','reason':payload.get('opening_reason','')}
        if payload.get('opening_mode')=='previous':
            from .tax_ledger import previous_period
            previous=conn.execute('SELECT * FROM tax_ledgers WHERE company_id=? AND period=? AND tax=? AND reversed_at IS NULL',(cid,previous_period(competence),tax)).fetchone()
            if previous and self._ledger_stale(conn,cid,previous):raise DomainError('Apuração anterior com origem alterada; revise antes de transportar o crédito.',409,'stale_previous_assessment')
            opening=previous['carry_credit_cents'] if previous else 0
            opening_source={'type':'previous','ledger_id':previous['id'] if previous else None,'period':previous_period(competence)}
        elif opening and not payload.get('opening_reason'):
            # O contrato anterior registrava a fundamentação geral; preserve-o como fonte do saldo.
            opening_source['reason']=text(payload.get('source'),'Fundamento do saldo anterior',True,1500)
        net=debit-credit-opening
        return {'period':competence,'tax':tax,'entries':output,'adjustments':adjustments,'opening_credit_cents':opening,'opening_source':opening_source,
            'debit_cents':debit,'credit_cents':credit,'payable_cents':max(0,net),'carry_credit_cents':max(0,-net),
            'legal_validation':False,'scope_note':'Pré-apuração parametrizada pelo escritório. Incidência, base e admissibilidade de créditos exigem revisão fiscal; não transmite obrigação e não compensa tributos distintos.'}

    def assess_tax(self,cid,payload,actor):
        source=text(payload.get('source'),'Fundamentação do cenário',True,1500)
        responsible=text(payload.get('responsible'),'Responsável pela conferência',True,200)
        with self.db.transaction() as conn:
            key,hashed,previous=self._operation(conn,cid,'tax-assessment',payload)
            if previous:return previous
            ensure_open(conn,cid,period(payload.get('period')),'fiscal')
            from .tax_ledger import ensure_unfinalized
            ensure_unfinalized(conn,cid,period(payload.get('period')),payload.get('tax','').lower())
            snapshot=self._assessment_snapshot(conn,cid,payload)
            fingerprint=digest(snapshot)
            item_id=conn.execute('INSERT INTO tax_assessments(company_id,period,tax,source,responsible,snapshot_json,fingerprint,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?)',
                (cid,snapshot['period'],snapshot['tax'],source,responsible,pack({'result':snapshot,'request':payload}),fingerprint,now(),actor)).lastrowid
            result={'id':item_id,'snapshot':snapshot,'fingerprint':fingerprint,'source':source,'responsible':responsible}
            audit(conn,cid,actor,'assess','tax_assessment',item_id,{'fingerprint':fingerprint,'tax':snapshot['tax'],'period':snapshot['period']})
            self._record_operation(conn,cid,'tax-assessment',key,hashed,result)
            return result

    def assessments(self,cid,competence):
        with self.db.read() as conn:
            output=[]
            for r in conn.execute('SELECT * FROM tax_assessments WHERE company_id=? AND period=? ORDER BY id DESC',(cid,period(competence))):
                item=dict(r);saved=json.loads(item.pop('snapshot_json'));item['snapshot']=saved['result']
                try:item['stale']=digest(self._assessment_snapshot(conn,cid,saved['request']))!=item['fingerprint']
                except DomainError:item['stale']=True
                output.append(item)
            return output

    def save_tax_adjustment(self,cid,payload,actor):
        with self.db.transaction() as conn:
            key,hashed,previous=self._operation(conn,cid,'tax-adjustment',payload)
            if previous:return previous
            p=period(payload.get('period'));ensure_open(conn,cid,p,'fiscal')
            tax=text(payload.get('tax'),'Tributo',True,20).lower();kind=payload.get('kind')
            if tax not in {'icms','ipi','iss','pis','cofins','ibs','cbs'} or kind not in {'debit','credit'}:raise DomainError('Tributo ou natureza inválidos.')
            from .tax_ledger import ensure_unfinalized
            ensure_unfinalized(conn,cid,p,tax)
            category=payload.get('category','other')
            if category not in {'other','debit','credit','reverse_debit','reverse_credit'}:raise DomainError('Categoria de ajuste inválida.')
            if category!='other' and kind!=('debit' if category in {'debit','reverse_credit'} else 'credit'):raise DomainError('Natureza incompatível com a categoria de ajuste.')
            amount=money(payload.get('amount'),positive=True);source=text(payload.get('source'),'Fonte normativa',True,1500);reason=text(payload.get('reason'),'Motivo',True,1000)
            did=payload.get('document_id')
            if did:select_one(conn,'documents',cid,integer(did))
            item_id=conn.execute('INSERT INTO tax_adjustments(company_id,period,tax,kind,amount_cents,source,reason,document_id,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?,?)',(cid,p,tax,kind,amount,source,reason,did,now(),actor)).lastrowid
            conn.execute('UPDATE tax_adjustments SET category=? WHERE id=?',(category,item_id))
            audit(conn,cid,actor,'create','tax_adjustment',item_id,payload)
            result={'id':item_id};self._record_operation(conn,cid,'tax-adjustment',key,hashed,result);return result

    def tax_adjustments(self,cid,competence):
        with self.db.read() as conn:
            return [dict(r) for r in conn.execute('SELECT * FROM tax_adjustments WHERE company_id=? AND period=? ORDER BY id',(cid,period(competence)))]

    def reverse_tax_adjustment(self,cid,item_id,payload,actor):
        reason=text(payload.get('reason'),'Justificativa',True,1000)
        with self.db.transaction() as conn:
            r=select_one(conn,'tax_adjustments',cid,item_id)
            if r['period']!=period(payload.get('period')):raise DomainError('Ajuste de outra competência.',409)
            ensure_open(conn,cid,r['period'],'fiscal')
            from .tax_ledger import ensure_unfinalized
            ensure_unfinalized(conn,cid,r['period'],r['tax'])
            if r['reversed_at']:raise DomainError('Ajuste já estornado.',409)
            conn.execute('UPDATE tax_adjustments SET reversed_at=? WHERE id=?',(now(),item_id))
            audit(conn,cid,actor,'reverse','tax_adjustment',item_id,{'reason':reason})
            return {'id':item_id,'reversed':True}
