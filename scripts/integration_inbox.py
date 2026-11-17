"""Reference receiver transaction. Caller provides HTTPS server and business handler.

Never bind this example directly to an Internet-facing socket. Persist the SQLite
inbox with the consumer's business state, and configure expected_company_id.
"""
import hashlib
import json
import re

from app.integrations import verify_signature


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS integration_inbox (
        event_id TEXT PRIMARY KEY, body_hash TEXT NOT NULL)''')
    conn.commit()


def accept(conn, secret, timestamp, supplied_signature, body, expected_company_id, apply):
    """Return True once, False for a duplicate; apply(conn,event) commits atomically.

    Any exception rolls back inbox and business changes together. Return HTTP 2xx
    only after this function returns. On exceptions, return a generic error.
    """
    if len(body) > 8192 or not supplied_signature.startswith('v1='):
        raise ValueError('invalid_envelope')
    if not verify_signature(secret,timestamp,body,supplied_signature[3:]):
        raise ValueError('invalid_signature')
    event = json.loads(body)
    if (not isinstance(event,dict) or event.get('specversion') != '1.0'
            or event.get('type') != 'cost-center.changed.v1'
            or event.get('company_id') != expected_company_id
            or not isinstance(event.get('id'),str)
            or not re.fullmatch('[a-f0-9]{32}',event['id'])):
        raise ValueError('invalid_envelope')
    body_hash = hashlib.sha256(body).hexdigest()
    conn.execute('BEGIN IMMEDIATE')
    try:
        previous = conn.execute('SELECT body_hash FROM integration_inbox WHERE event_id=?',(event['id'],)).fetchone()
        if previous:
            if previous[0] != body_hash:
                raise ValueError('conflicting_event')
            conn.commit()
            return False
        conn.execute('INSERT INTO integration_inbox VALUES(?,?)',(event['id'],body_hash))
        apply(conn,event)
        conn.commit()
        return True
    except BaseException:
        conn.rollback()
        raise
