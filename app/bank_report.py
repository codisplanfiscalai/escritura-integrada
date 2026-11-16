"""Movimentos importados, sem inferir saldos de extrato a partir de histórico parcial."""
from .core import company_row


def bank_report(db, cid, start, end, bank_account=''):
    with db.read(snapshot=True) as conn:
        company = company_row(conn, cid)
        rows = [dict(r) for r in conn.execute("""SELECT id AS bank_id, bank_account, date,
            description, reference, external_id, source_hash, amount_cents
            FROM bank_transactions WHERE company_id=? AND date BETWEEN ? AND ?
            AND (?='' OR bank_account=?) ORDER BY bank_account,date,id""",
            (cid, start, end, bank_account, bank_account))]
        for row in rows:
            row.update(inflow_cents=max(0,row['amount_cents']), outflow_cents=max(0,-row['amount_cents']), balance_cents=None)
        return dict(kind='bank-movements',company_id=cid,company_name=company['name'],
            company_code=company['code'],company_tax_id=company['tax_id'],start=start,end=end,
            filters={'bank_account':bank_account},rows=rows,
            totals=dict(opening_cents=None,inflow_cents=sum(r['inflow_cents'] for r in rows),
                outflow_cents=sum(r['outflow_cents'] for r in rows),
                net_movement_cents=sum(r['amount_cents'] for r in rows),closing_cents=None),
            scope_note='Movimentos bancários importados, por conta e data. Saldo de abertura, saldo corrente e saldo final indisponíveis: o domínio não armazena saldo comprovado de extrato. O movimento líquido não representa saldo bancário. ID, referência, identificador e hash permitem conferir a origem. Não inclui baixas financeiras sem transação bancária importada.')
