"""Integração dos serviços, preservando o núcleo e seus contratos anteriores."""
import json
import re
from .core import (Core, DomainError, audit, check_version, decimal_text, ensure_open,
                   integer, iso_date, money, now, pack, period, select_one, text)
from .cadastros import CadastrosMixin
from .finance import FinanceMixin
from .reconciliation import ReconciliationMixin
from .reports import ReportsMixin
from .prosoft import ProsoftMixin
from .access import AccessMixin
from .periods import PeriodMixin
from .tax_assessment import TaxAssessmentMixin
from .tax_ledger import TaxLedgerMixin,ensure_unfinalized
from .fiscal_reports import FiscalReportsMixin

from .auditor import AuditorMixin
from .module_imports import ModuleImportsMixin

class BusinessCore(AuditorMixin, ModuleImportsMixin, TaxLedgerMixin, FiscalReportsMixin, PeriodMixin, AccessMixin, ProsoftMixin, ReportsMixin, TaxAssessmentMixin, ReconciliationMixin, FinanceMixin, CadastrosMixin, Core):
    def _validate_document_links(self,conn,cid,payload):
        for k,kind in [('participant_id','participant'),('establishment_id','establishment')]:
            if payload.get(k):
                m=self._master(conn,cid,integer(payload[k],k),kind,True)
                if kind=='participant' and m['tax_id'] and m['tax_id']!=re.sub(r'[.\-/\s]','',payload.get('partner_tax_id','')).upper():
                    raise DomainError('CPF/CNPJ do documento diverge do participante selecionado.')
        items=payload.get('items',[])
        if not isinstance(items,list):raise DomainError('Itens fiscais devem formar uma lista.')
        for item in items:
            if not isinstance(item,dict):raise DomainError('Item fiscal inválido.')
            if item.get('master_id'):
                m=self._master(conn,cid,integer(item['master_id'],'Produto/serviço'),active=True)
                if m['kind'] not in {'product','service'}:raise DomainError('Item deve referenciar um produto ou serviço.')

    def create_document(self,cid,payload,actor):
        with self.db.transaction() as conn:
            if payload.get('idempotency_key'):
                key,hashed,previous=self._operation(conn,cid,'manual-document',payload)
                if previous:return previous
            result=self._create_document(conn,cid,payload,actor)
            if payload.get('idempotency_key'):self._record_operation(conn,cid,'manual-document',key,hashed,result)
            return result

    def _create_document(self,conn,cid,payload,actor):
        self._validate_document_links(conn,cid,payload)
        return super()._create_document(conn,cid,payload,actor)

    def _book_document(self,conn,cid,item_id,payload,actor):
        doc=self._document(conn,cid,item_id)
        self._validate_document_links(conn,cid,doc)
        scope='book-document:'+str(item_id)
        if payload.get('idempotency_key'):
            key,hashed,previous=self._operation(conn,cid,scope,payload)
            if previous:return previous
        effective=dict(payload)
        model_id=payload.get('model_id')
        if model_id:
            if payload.get('lines'):raise DomainError('Escolha um modelo ou partidas manuais, sem combinar os dois.')
            effective['lines']=self._model_lines(conn,cid,model_id,doc)
        if effective.get('lines'):
            _,total=self._normalize_lines(conn,cid,effective['lines'])
            if total!=doc['total_cents']:
                raise DomainError('O valor contabilizado deve corresponder ao total do documento.')
        parts=None
        if payload.get('generate_titles'):
            requested=payload.get('installments')
            if payload.get('use_document_installments'):
                requested=[p for invoice in doc.get('invoices',[]) for p in invoice.get('installments',[invoice])]
            financed=money(payload.get('financed_amount',decimal_text(doc['total_cents'])),'Valor financiado',positive=True)
            if financed>doc['total_cents']:
                raise DomainError('Valor financiado excede o total do documento.')
            parts=self._installments(requested,financed,doc['issue_date'])
            if conn.execute('SELECT 1 FROM titles WHERE company_id=? AND document_id=? AND cancelled=0',(cid,item_id)).fetchone():
                raise DomainError('Documento já possui títulos. Confira os vínculos antes de gerar parcelas.',409,'titles_exist')
        result=super()._book_document(conn,cid,item_id,effective,actor)
        titles=[]
        for n,p in enumerate(parts or [],1):
            titles.append(self._create_title(conn,cid,{'kind':'payable' if doc['direction']=='incoming' else 'receivable',
                'description':f'Documento {doc["number"]} - parcela {n}','partner_name':doc['partner_name'],
                'participant_id':doc.get('participant_id'),'document':doc['number'],'document_id':item_id,'issue_date':doc['issue_date'],**p,
                'installment':n,'source_key':f'document:{item_id}:revision:{doc["version"]}:installment:{n}'},actor))
        result['titles']=titles
        audit(conn,cid,actor,'integrate','document',item_id,{'title_ids':[t['id'] for t in titles],
            'journal_id':result['journal']['id'] if result['journal'] else None,'model_id':model_id,
            'model_snapshot':self._master(conn,cid,model_id) if model_id else None})
        if payload.get('idempotency_key'):self._record_operation(conn,cid,scope,key,hashed,result)
        return result

    def reverse_document(self,cid,item_id,payload,actor):
        reason=text(payload.get('reason'),'Motivo da reversão da escrituração',True,1000)
        day=iso_date(payload.get('date'))
        with self.db.transaction() as conn:
            scope='reverse-document:'+str(item_id)
            key,hashed,previous=self._operation(conn,cid,scope,payload)
            if previous:return previous
            doc=self._document(conn,cid,item_id);check_version(doc,payload)
            ensure_open(conn,cid,doc['period'],'fiscal');ensure_unfinalized(conn,cid,doc['period'])
            if doc['status']!='booked':raise DomainError('Somente documento escriturado pode ter sua escrituração revertida.',409)
            if day<doc['posting_date']:raise DomainError('Reversão não pode anteceder a escrituração.')
            titles=[self._title(conn,cid,r['id']) for r in conn.execute('SELECT id FROM titles WHERE company_id=? AND document_id=? AND cancelled=0',(cid,item_id))]
            for t in titles:
                from .permissions import effect
                effect(conn,cid,'financial.titles','reverse')
                ensure_open(conn,cid,t['issue_date'][:7],'financial')
                if t['paid_cents'] or t['allocations'] or conn.execute('SELECT 1 FROM reconciliations WHERE title_id=?',(t['id'],)).fetchone():
                    raise DomainError('Há baixa ou conciliação vinculada. Reverta esses efeitos antes da escrituração.',409)
            if conn.execute('SELECT 1 FROM titles WHERE company_id=? AND document_id=? AND renegotiation_id IS NOT NULL',(cid,item_id)).fetchone():
                raise DomainError('Documento possui renegociação; sua cadeia financeira exige revisão antes da reversão.',409)
            journal=self._reverse_linked_journal(conn,cid,doc['journal_id'],day,reason,actor,'document-reversal:'+str(item_id)+':'+str(doc['version'])) if doc['journal_id'] else None
            for t in titles:conn.execute('UPDATE titles SET cancelled=1,version=version+1 WHERE id=?',(t['id'],))
            conn.execute("UPDATE documents SET status='pending',journal_id=NULL,reviewed_by=NULL,review_reason=NULL,booked_by=NULL,book_reason=NULL,version=version+1 WHERE id=? AND company_id=?",(item_id,cid))
            audit(conn,cid,actor,'reverse-booking','document',item_id,{'reason':reason,'date':day,'before':doc,'cancelled_title_ids':[t['id'] for t in titles],'reversal_journal_id':journal['id'] if journal else None})
            result={'document':self._document(conn,cid,item_id),'journal':journal,'cancelled_titles':len(titles)}
            self._record_operation(conn,cid,scope,key,hashed,result)
            return result

    def trace_document(self,cid,item_id):
        with self.db.read() as conn:
            doc=self._document(conn,cid,item_id)
            titles=[self._title(conn,cid,x['id']) for x in conn.execute('SELECT id FROM titles WHERE company_id=? AND document_id=?',(cid,item_id))]
            title_ids={t['id'] for t in titles};agreements=[]
            pending=[dict(a) for a in conn.execute('SELECT * FROM renegotiations WHERE company_id=? ORDER BY id',(cid,))]
            for a in pending:
                originals=json.loads(a['original_ids_json'])
                if title_ids.intersection(originals):
                    related=[self._title(conn,cid,t['id']) for t in conn.execute('SELECT id FROM titles WHERE company_id=? AND source_key LIKE ?',(cid,f"renegotiation:{a['id']}:%"))]
                    titles.extend(t for t in related if t['id'] not in title_ids);title_ids.update(t['id'] for t in related)
                    agreements.append({'id':a['id'],'date':a['date'],'reason':a['reason'],'original_ids':originals,'new_title_ids':[t['id'] for t in related],'reversed_at':a['reversed_at']})
            journal_ids={doc['journal_id']} if doc['journal_id'] else set()
            for t in titles:
                for s in t['settlements']:
                    journal_ids.update(x for x in [s['journal_id'],s['reversal_journal_id']] if x)
            events=[dict(r)|{'details':json.loads(r['details_json'])} for r in conn.execute("SELECT * FROM audit WHERE company_id=? AND entity='document' AND entity_id=? ORDER BY id",(cid,str(item_id)))]
            for e in events:
                e.pop('details_json',None)
                if e['action']=='reverse-booking':
                    journal_ids.update(x for x in [e['details'].get('reversal_journal_id'),e['details'].get('before',{}).get('journal_id')] if x)
            from .permissions import readable
            return {'document':doc,'titles':titles if readable(conn,cid,'financial.titles') else [],
                'journals':[self._journal(conn,cid,i) for i in sorted(journal_ids)] if readable(conn,cid,'accounting.journals') else [],
                'events':events if readable(conn,cid,'system.audit') else [],
                'renegotiations':agreements if readable(conn,cid,'financial.titles') else []}

    def create_opening(self,cid,payload,actor):
        day=iso_date(payload.get('date'))
        reason=text(payload.get('history'),'Fundamento dos saldos iniciais',True,1000)
        with self.db.transaction() as conn:
            result=self._create_journal(conn,cid,dict(payload,history='Saldos iniciais: '+reason,document='ABERTURA',idempotency_key='opening:'+day),actor)
            if not result.get('duplicate'):audit(conn,cid,actor,'opening','journal',result['id'],{'date':day,'reason':reason})
            return result
