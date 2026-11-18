"""Resolve a bounded union of company account selections, without materializing."""
from .core import DomainError
from .account_refs import resolve_account

ACCOUNT_REPORTS={'diary','ledger','consolidated-diary','trial-balance','balance-sheet','income-statement','cost-centers'}


def plan_mask(conn,cid):
    import json,re
    row=conn.execute('SELECT properties_json FROM account_plan_properties WHERE company_id=?',(cid,)).fetchone()
    if row:properties=json.loads(row['properties_json'])
    else:
        row=conn.execute('SELECT g.plan_json FROM company_account_plan_bindings b JOIN global_account_plans g ON g.id=b.global_plan_id WHERE b.company_id=?',(cid,)).fetchone()
        properties=json.loads(row['plan_json']).get('properties',{}) if row else {}
    mask=properties.get('mask','')
    return mask if isinstance(mask,str) and re.fullmatch(r'#(?:\.#+)+',mask) else None


def selected_accounts(conn,cid,account_id=None,account_ids=None):
    raw=list(account_ids or [])
    if account_id is not None:raw.append(account_id)
    if len(raw)>500:raise DomainError('Selecione até 500 contas ou use Todas as contas.')
    if not raw:return [],None
    selected={}
    for value in raw:
        row=resolve_account(conn,cid,value)
        selected[row['id']]=row
    from .trial_balance_report import classifier_path
    mask=plan_mask(conn,cid)
    paths=[classifier_path(r['classifier'],mask) for r in selected.values() if not r['analytical']]
    analytical={r['id'] for r in selected.values() if r['analytical']}
    if paths:
        for a in conn.execute('SELECT id,classifier FROM effective_accounts WHERE company_id=? AND analytical=1',(cid,)):
            path=classifier_path(a['classifier'],mask)
            if any(p and path[:len(p)]==p for p in paths):analytical.add(a['id'])
    return list(selected.values()),analytical
