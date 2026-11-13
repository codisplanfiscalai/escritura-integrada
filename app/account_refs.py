"""Company-scoped account references, resolved without copying shared definitions.

Positive IDs are historical company rows. Negative IDs are immutable global
entry aliases, visible only through a company's current binding. First use
creates a minimal company FK target, not a copy of attributes or source bytes.
"""
from .core import DomainError, audit


def account_ref(value):
    if isinstance(value, bool) or not isinstance(value, int) or value == 0 or not -(2**63-1) <= value <= 2**63-1:
        raise DomainError('Referência contábil inválida.')
    return value


def canonical_payload_accounts(conn,cid,payload):
    """Stable idempotency identity across virtual/allocated aliases, read-only."""
    if not isinstance(payload.get('lines'),list):return payload
    lines=[]
    for line in payload['lines']:
        if not isinstance(line,dict) or 'account_id' not in line:
            lines.append(line);continue
        account=resolve_account(conn,cid,line['account_id'])
        canonical=-account['shared_entry_id'] if account['shared_entry_id'] else account['id']
        lines.append(dict(line,account_id=canonical))
    return dict(payload,lines=lines)


def resolve_account(conn, cid, value, materialize=False, actor=None):
    value = account_ref(value)
    if value > 0:
        row = conn.execute('SELECT * FROM effective_accounts WHERE company_id=? AND id=?', (cid,value)).fetchone()
    else:
        entry_id = -value
        # Already used aliases stay valid for retries and old open forms. The
        # company-owned FK target is authoritative, even after an own fork.
        row = conn.execute('''SELECT a.* FROM company_account_aliases x JOIN effective_accounts a ON a.company_id=x.company_id AND a.id=x.account_id
            WHERE x.company_id=? AND x.global_entry_id=?''',(cid,entry_id)).fetchone()
        if row is None:
            row = conn.execute('SELECT * FROM effective_accounts WHERE company_id=? AND shared_entry_id=? AND id>0', (cid,entry_id)).fetchone()
        if row is None:
            entry = conn.execute('''SELECT g.* FROM global_account_entries g
                JOIN company_account_plan_bindings b ON b.global_plan_id=g.global_plan_id
                WHERE b.company_id=? AND b.mode='shared' AND g.id=?''', (cid,entry_id)).fetchone()
            if entry:
                # An identical pre-existing local account can retain its ID.
                row = conn.execute('SELECT * FROM effective_accounts WHERE company_id=? AND access_code=?', (cid,entry['access_code'])).fetchone()
    if row is None:
        raise DomainError('Conta não disponível no plano vinculado a esta empresa.',404,'account_reference_unavailable')
    result = dict(row)
    if materialize and result['id'] < 0:
        # Technical FK allocation is part of the authorized accounting action;
        # it does not grant permission to edit any local/global account.
        aid = conn.execute('''INSERT INTO accounts(company_id,access_code,classifier,name,nature,analytical,requires_cost_center,active,report_group,prosoft_code,shared_entry_id)
            VALUES(?,?,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,?)''',(cid,result['access_code'],result['shared_entry_id'])).lastrowid
        conn.execute('INSERT INTO global_account_plan_links(company_id,account_id,global_plan_id,access_code) SELECT ?,?,global_plan_id,access_code FROM global_account_entries WHERE id=?', (cid,aid,result['shared_entry_id']))
        if actor is None:
            from .db import request_context
            context = request_context.get() or {}
            user = conn.execute('SELECT username FROM users WHERE id=?',(context.get('user_id'),)).fetchone()
            actor = user['username'] if user else 'system'
        audit(conn,cid,actor,'materialize-reference','account',aid,{'global_entry_id':result['shared_entry_id'],'access_code':result['access_code']})
        result = dict(conn.execute('SELECT * FROM effective_accounts WHERE company_id=? AND id=?',(cid,aid)).fetchone())
    if materialize:
        entries=set()
        if value<0:entries.add(-value)
        if result['shared_entry_id']:entries.add(result['shared_entry_id'])
        current=conn.execute('''SELECT g.id FROM global_account_entries g JOIN company_account_plan_bindings b ON b.global_plan_id=g.global_plan_id
            WHERE b.company_id=? AND b.mode='shared' AND g.access_code=?''',(cid,result['access_code'])).fetchone()
        if current:entries.add(current['id'])
        for entry_id in entries:
            conn.execute('INSERT INTO company_account_aliases(company_id,global_entry_id,account_id,used) VALUES(?,?,?,1) ON CONFLICT(company_id,global_entry_id) DO UPDATE SET used=1',(cid,entry_id,result['id']))
        conn.execute('UPDATE company_account_aliases SET used=1 WHERE company_id=? AND account_id=?',(cid,result['id']))
    return result
