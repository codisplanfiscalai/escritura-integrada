"""Relatórios internos com período explícito, saldos e origens conferíveis."""
import calendar
from .core import DomainError, company_row, integer, iso_date, period, select_one

class ReportsMixin:
    def business_report(self,cid,kind,start,end,account_id=None,cost_center_id=None,query='',status='',direction=''):
        start,end=iso_date(start),iso_date(end)
        if start>end:raise DomainError('Período inicial posterior ao final.')
        query=str(query or '').casefold()
        with self.db.read(snapshot=True) as conn:
            company=company_row(conn,cid)
            clauses=['l.company_id=?'];params=[cid]
            for field,value,table in [('account_id',account_id,'accounts'),('cost_center_id',cost_center_id,'cost_centers')]:
                if value is not None:
                    record=select_one(conn,table,cid,value if table=='accounts' else integer(value,field))
                    value=record['id']
                    if table=='accounts':account_id=value
                    clauses.append('l.'+field+'=?');params.append(value)
            where=' AND '.join(clauses)
            openings={r['account_id']:r['balance'] for r in conn.execute('SELECT l.account_id,SUM(l.debit_cents-l.credit_cents) AS balance FROM journal_lines l JOIN journals j ON j.id=l.journal_id WHERE '+where+' AND j.date<? GROUP BY l.account_id',(*params,start))}
            rows=[dict(r) for r in conn.execute('''SELECT j.id AS journal_id,j.number,j.date,j.document,j.history,
                a.id AS account_id,a.access_code,a.classifier,a.name AS account_name,a.nature,a.report_group,
                l.cost_center_id,c.code AS cost_center_code,c.name AS cost_center_name,l.debit_cents,l.credit_cents
                FROM journal_lines l JOIN journals j ON j.id=l.journal_id JOIN effective_accounts a ON a.id=l.account_id
                LEFT JOIN cost_centers c ON c.id=l.cost_center_id WHERE '''+where+' AND j.date BETWEEN ? AND ? ORDER BY j.date,j.id,l.position',(*params,start,end))]
            totals={'debit_cents':sum(r['debit_cents'] for r in rows),'credit_cents':sum(r['credit_cents'] for r in rows)}
            note='Relatório interno, com base nos movimentos cadastrados. Débito positivo; crédito negativo nos saldos.'
            if kind in {'diary','ledger'}:
                if kind=='ledger':
                    rows.sort(key=lambda x:(x['classifier'],x['date'],x['journal_id']))
                    balances=dict(openings)
                    for r in rows:
                        aid=r['account_id'];r['opening_cents']=openings.get(aid,0)
                        balances[aid]=balances.get(aid,0)+r['debit_cents']-r['credit_cents'];r['balance_cents']=balances[aid]
                if query:rows=[r for r in rows if query in f"{r['document']} {r['history']} {r['account_name']}".casefold()]
            elif kind in {'trial-balance','balance-sheet','income-statement'}:
                movements={}
                for r in rows:
                    x=movements.setdefault(r['account_id'],{'debit_cents':0,'credit_cents':0,'journal_ids':set()})
                    x['debit_cents']+=r['debit_cents'];x['credit_cents']+=r['credit_cents'];x['journal_ids'].add(r['journal_id'])
                accounts=[dict(r) for r in conn.execute('SELECT * FROM effective_accounts WHERE company_id=? AND analytical=1 ORDER BY classifier',(cid,))]
                rows=[]
                for a in accounts:
                    if account_id and a['id']!=account_id:continue
                    m=movements.get(a['id'],{'debit_cents':0,'credit_cents':0,'journal_ids':set()})
                    opening=openings.get(a['id'],0);closing=opening+m['debit_cents']-m['credit_cents']
                    rows.append({'account_id':a['id'],'access_code':a['access_code'],'classifier':a['classifier'],'account_name':a['name'],
                        'report_group':a['report_group'],'opening_cents':opening,'debit_cents':m['debit_cents'],'credit_cents':m['credit_cents'],
                        'closing_cents':closing,'journal_ids':sorted(m['journal_ids'])})
                if kind in {'balance-sheet','income-statement'}:
                    missing=[r['account_name'] for r in rows if not r['report_group'] and (r['opening_cents'] or r['debit_cents'] or r['credit_cents'])]
                    if missing:raise DomainError('Classifique o grupo das contas movimentadas antes do demonstrativo: '+', '.join(missing),409,'unmapped_accounts')
                    if kind=='income-statement':
                        rows=[r for r in rows if r['report_group'] in {'revenue','expense'}]
                        for r in rows:r['result_cents']=r['credit_cents']-r['debit_cents']
                        totals={'result_cents':sum(r['result_cents'] for r in rows)}
                        note='Resultado do período por grupos explicitamente classificados. Não inclui encerramento automático.'
                    else:
                        groups={g:sum(r['closing_cents'] for r in rows if r['report_group']==g) for g in ['asset','liability','equity','revenue','expense']}
                        totals={'assets_cents':groups['asset'],'liabilities_cents':-groups['liability'],'equity_cents':-groups['equity'],
                            'unclosed_result_cents':-groups['revenue']-groups['expense'],'difference_cents':sum(groups.values())}
                        note='Posição até a data final. Resultado ainda não encerrado é apresentado separadamente; não duplica patrimônio líquido.'
                else:
                    totals.update(opening_cents=sum(r['opening_cents'] for r in rows),closing_cents=sum(r['closing_cents'] for r in rows))
            elif kind=='cost-centers':
                groups={}
                for r in rows:
                    key=(r['cost_center_id'],r['account_id'])
                    x=groups.setdefault(key,{k:r[k] for k in ['cost_center_id','cost_center_name','account_id','access_code','account_name']}|{'debit_cents':0,'credit_cents':0,'journal_ids':[]})
                    x['debit_cents']+=r['debit_cents'];x['credit_cents']+=r['credit_cents']
                    if r['journal_id'] not in x['journal_ids']:x['journal_ids'].append(r['journal_id'])
                rows=list(groups.values())
                for r in rows:r['balance_cents']=r['debit_cents']-r['credit_cents']
                note='Movimentos agrupados por centro e conta. Sem centro aparece separadamente; débitos e créditos de cada centro podem diferir.'
            elif kind=='consolidated-diary':
                groups={}
                for r in rows:
                    key=(r['date'],r['account_id'],r['cost_center_id'])
                    x=groups.setdefault(key,{k:r[k] for k in ['date','account_id','access_code','account_name','cost_center_name']}|{'debit_cents':0,'credit_cents':0,'journal_ids':[]})
                    x['debit_cents']+=r['debit_cents'];x['credit_cents']+=r['credit_cents']
                    if r['journal_id'] not in x['journal_ids']:x['journal_ids'].append(r['journal_id'])
                rows=list(groups.values());note='Consolidação diária por conta e centro dentro da empresa selecionada. Não consolida pessoas jurídicas nem elimina operações intercompanhias.'
            elif kind=='fiscal-book':
                from .fiscal_series import normalize_series,settings
                digits=settings(conn,cid)['digits']
                rows=[{'document_id':r['id'],'date':r['posting_date'],'document':r['number'],'series':normalize_series(r['series'],digits),'model':r['model'],
                    'partner_name':r['partner_name'],'direction':r['direction'],'cfop':r['cfop'],'total_cents':r['total_cents'],'status':r['status'],'journal_id':r['journal_id']} for r in conn.execute('SELECT * FROM documents WHERE company_id=? AND posting_date BETWEEN ? AND ? ORDER BY posting_date,id',(cid,start,end))]
                rows=[r for r in rows if (not status or r['status']==status) and (not direction or r['direction']==direction) and (not query or query in (r['document']+' '+r['partner_name']).casefold())]
                totals={'total_cents':sum(r['total_cents'] for r in rows),'documents':len(rows)}
                note='Livro auxiliar de documentos declarados. Não substitui livro fiscal legal, PVA ou obrigação transmitida.'
            elif kind in {'financial','cash-flow','partners'}:
                rows=[]
                if kind=='partners':
                    rows=[r for r in self.partner_reconciliation(cid) if start<=r['due_date']<=end]
                elif kind=='financial':
                    rows=[{k:t[k] for k in ['id','kind','description','partner_name','document','document_id','issue_date','due_date','amount_cents','paid_cents','balance_cents','status']} for t in [self._title(conn,cid,x['id']) for x in conn.execute('SELECT id FROM titles WHERE company_id=?',(cid,))] if start<=t['due_date']<=end]
                    for r in rows:r['title_id']=r.pop('id')
                else:
                    for s in conn.execute('''SELECT s.*,t.kind,t.description,t.partner_name,t.document FROM settlements s
                        JOIN titles t ON t.id=s.title_id WHERE s.company_id=?''',(cid,)):
                        sign=1 if s['kind']=='receivable' else -1
                        base={'settlement_id':s['id'],'title_id':s['title_id'],'kind':s['kind'],'partner_name':s['partner_name'],'document':s['document'],'description':s['description']}
                        if start<=s['date']<=end:rows.append(base|{'date':s['date'],'cash_cents':sign*s['cash_cents'],'event':'Baixa'})
                        if s['reversal_date'] and start<=s['reversal_date']<=end:rows.append(base|{'date':s['reversal_date'],'cash_cents':-sign*s['cash_cents'],'event':'Estorno'})
                    rows.sort(key=lambda r:(r['date'],r['settlement_id']))
                rows=[r for r in rows if (not status or r.get('status')==status) and (not direction or r.get('kind')==direction) and (not query or query in str(r).casefold())]
                totals={k:sum(r.get(k,0) for r in rows) for k in ['amount_cents','paid_cents','balance_cents','cash_cents'] if any(k in r for r in rows)}
                note='Vencimentos no período para títulos; caixa realizado pelas datas das baixas e dos estornos. Renegociações preservam os títulos originais encerrados.'
            else:raise DomainError('Relatório não encontrado.',404)
            if kind in {'diary','ledger'}:totals={'debit_cents':sum(r['debit_cents'] for r in rows),'credit_cents':sum(r['credit_cents'] for r in rows)}
            ledger_groups=[]
            if kind=='ledger':
                for r in rows:
                    others=[x['access_code'] for x in conn.execute('SELECT DISTINCT a.access_code FROM journal_lines l JOIN effective_accounts a ON a.id=l.account_id WHERE l.company_id=? AND l.journal_id=? AND l.account_id<>?',(cid,r['journal_id'],r['account_id']))]
                    r['counterpart']=others[0] if len(others)==1 else 'Diversos' if others else ''
                for a in conn.execute('SELECT id,access_code,classifier,name FROM effective_accounts WHERE company_id=? AND analytical=1 ORDER BY classifier',(cid,)):
                    if account_id and a['id']!=account_id:continue
                    movements=[r for r in rows if r['account_id']==a['id']]
                    if movements or openings.get(a['id']):ledger_groups.append({'account_id':a['id'],'access_code':a['access_code'],'classifier':a['classifier'],'account_name':a['name'],'opening_cents':openings.get(a['id'],0),'closing_cents':balances.get(a['id'],openings.get(a['id'],0)),'filtered':bool(query),'rows':movements})
                if query:note+=' Pesquisa restringe os movimentos exibidos; os saldos incluem todos os movimentos da conta no período e centro selecionados.'
            return {'ledger_groups':ledger_groups,'company_code':company['prosoft_code'] or company['code'],'company_tax_id':company['tax_id'],'kind':kind,'company_id':cid,'company_name':company['name'],'start':start,'end':end,'rows':rows,'totals':totals,'scope_note':note,'account_id':account_id,'cost_center_id':cost_center_id,'filters':{'account_id':account_id,'cost_center_id':cost_center_id,'query':query,'status':status,'direction':direction}}
