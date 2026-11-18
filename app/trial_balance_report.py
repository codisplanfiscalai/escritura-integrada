"""Read-only hierarchical trial balance; totals never sum synthetic rows."""
from .core import DomainError, company_row
from .account_refs import resolve_account

AMOUNTS = ('opening_cents', 'debit_cents', 'credit_cents', 'closing_cents')


def classifier_path(value):
    text = str(value or '').strip()
    if '.' in text:
        parts = text.split('.')
        while parts and parts[-1] and set(parts[-1]) == {'0'}:
            parts.pop()
        return tuple(parts)
    # Legacy unformatted classifiers use trailing zero padding.
    return tuple(text.rstrip('0'))


def trial_balance(core, cid, start, end, account_id=None, cost_center_id=None, activity='active'):
    if activity not in {'active', 'all'}:
        raise DomainError('Selecione contas com movimento ou saldo, ou todas as contas.')
    with core.db.read(snapshot=True) as conn:
        company = company_row(conn, cid)
        accounts = [dict(a) for a in conn.execute('SELECT * FROM effective_accounts WHERE company_id=?', (cid,))]
        paths = {a['id']: classifier_path(a['classifier']) for a in accounts}
        selected = resolve_account(conn, cid, account_id) if account_id is not None else None
        if cost_center_id is not None:
            from .core import select_one, integer
            cost_center_id = select_one(conn, 'cost_centers', cid, integer(cost_center_id, 'Centro'))['id']
        selected_path = classifier_path(selected['classifier']) if selected else None
        def in_selection(a):
            if not selected: return True
            if selected['analytical']: return a['id'] == selected['id']
            path = paths[a['id']]
            return bool(selected_path) and path[:len(selected_path)] == selected_path
        clauses = ['l.company_id=?', 'j.date<=?']; params = [cid, end]
        if cost_center_id is not None:
            clauses.append('l.cost_center_id=?'); params.append(cost_center_id)
        sql = '''SELECT l.account_id,
            SUM(CASE WHEN j.date<? THEN l.debit_cents-l.credit_cents ELSE 0 END) opening,
            SUM(CASE WHEN j.date>=? THEN l.debit_cents ELSE 0 END) debit,
            SUM(CASE WHEN j.date>=? THEN l.credit_cents ELSE 0 END) credit
            FROM journal_lines l JOIN journals j ON j.id=l.journal_id WHERE ''' + ' AND '.join(clauses) + ' GROUP BY l.account_id'
        movements = {r['account_id']:r for r in conn.execute(sql, [start,start,start,*params])}
        sources = {}
        for r in conn.execute('SELECT DISTINCT l.account_id,j.id FROM journal_lines l JOIN journals j ON j.id=l.journal_id WHERE '+' AND '.join(clauses)+' AND j.date>=? ORDER BY j.id', [*params,start]):
            sources.setdefault(r['account_id'], []).append(r['id'])
        analytic = []
        for a in accounts:
            if not a['analytical'] or not in_selection(a): continue
            m = movements.get(a['id'])
            opening, debit, credit = (m['opening'],m['debit'],m['credit']) if m else (0,0,0)
            row = {'account_id':a['id'],'access_code':a['access_code'],'classifier':a['classifier'],
                   'account_name':a['name'],'report_group':a['report_group'],'analytical':True,
                   'journal_ids':sources.get(a['id'],[]),'opening_cents':opening,'debit_cents':debit,'credit_cents':credit,'closing_cents':opening+debit-credit}
            if activity == 'all' or any(row[k] for k in AMOUNTS): analytic.append(row)
        totals = {k:sum(r[k] for r in analytic) for k in AMOUNTS}
        # Build only actual synthetic ancestors; never invent account names/codes.
        synthetics = [a for a in accounts if not a['analytical'] and paths[a['id']]]
        index = {}
        for a in synthetics: index.setdefault(paths[a['id']], []).append(a)
        aggregated = {}
        for row in analytic:
            path = paths[row['account_id']]
            for length in range(1,len(path)+1):
                for a in index.get(path[:length],[]):
                    aid=a['id']
                    subtotal=aggregated.setdefault(aid,{k:0 for k in AMOUNTS})
                    for k in AMOUNTS: subtotal[k]+=row[k]
        rows = list(analytic)
        for a in synthetics:
            if a['id'] not in aggregated:
                if activity != 'all' or not in_selection(a): continue
                aggregated[a['id']]={k:0 for k in AMOUNTS}
            rows.append({'account_id':a['id'],'access_code':a['access_code'],'classifier':a['classifier'],
                         'account_name':a['name'],'report_group':a['report_group'],'analytical':False,**aggregated[a['id']]})
        for row in rows:
            path=paths[row['account_id']]
            row['depth']=sum(1 for n in range(1,len(path)+1) if path[:n] in index and (n<len(path) or row['analytical']))
        rows.sort(key=lambda r:(paths[r['account_id']], bool(r['analytical']), str(r['access_code']), r['account_id']))
        return {'kind':'trial-balance','company_id':cid,'company_name':company['name'],
                'company_code':company['prosoft_code'] or company['code'],'company_tax_id':company['tax_id'],
                'start':start,'end':end,'rows':rows,'totals':totals,'account_id':account_id,'cost_center_id':cost_center_id,
                'filters':{'account_id':account_id,'cost_center_id':cost_center_id,'activity':activity},
                'scope_note':'Com movimento ou saldo inclui saldo anterior, débitos, créditos ou saldo final diferentes de zero. Contas sintéticas são subtotais; os totais consideram apenas contas analíticas, sem duplicação. Saldos devedores positivos e credores negativos. Não altera lançamentos.'}
