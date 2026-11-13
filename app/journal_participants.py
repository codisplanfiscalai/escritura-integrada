"""Account third-party policy from explicit imported plan metadata, never names."""
import json


def participant_policy(conn, cid, account):
    row = conn.execute("SELECT prosoft_json FROM account_plan_metadata WHERE company_id=? AND account_id=?", (cid, account['id'])).fetchone()
    if row is None and account.get('shared_entry_id'):
        row = conn.execute("SELECT prosoft_json FROM global_account_entries WHERE id=?", (account['shared_entry_id'],)).fetchone()
    value = str(json.loads(row['prosoft_json'] or '{}').get('entries', '')).strip() if row else ''
    return {'1': 'none', '2': 'optional', '3': 'required'}.get(value, 'optional')
