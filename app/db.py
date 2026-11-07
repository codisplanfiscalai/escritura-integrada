"""Persistência local: conexões curtas, WAL e transações serializadas de escrita."""
from __future__ import annotations

import os
import sys
import sqlite3
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

request_context = ContextVar("escritura_request_context", default=None)


class ContextConflict(Exception):
    """Authentication/context changed before obtaining the transaction lock."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password_hash TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 csrf_token TEXT NOT NULL, active_company_id INTEGER REFERENCES companies(id),
 period TEXT NOT NULL, expires_at REAL NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS login_attempts (
 attempt_key TEXT PRIMARY KEY, failures INTEGER NOT NULL, locked_until REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS companies (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE COLLATE NOCASE,
 name TEXT NOT NULL, trade_name TEXT NOT NULL DEFAULT '', tax_id TEXT NOT NULL UNIQUE,
 regime TEXT NOT NULL, state TEXT NOT NULL DEFAULT '', city TEXT NOT NULL DEFAULT '',
 address TEXT NOT NULL DEFAULT '', number TEXT NOT NULL DEFAULT '',
 district TEXT NOT NULL DEFAULT '', postal_code TEXT NOT NULL DEFAULT '',
 ibge TEXT NOT NULL DEFAULT '', ie TEXT NOT NULL DEFAULT '', im TEXT NOT NULL DEFAULT '',
 cnae TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
 prosoft_code TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 access_code TEXT NOT NULL, classifier TEXT NOT NULL, name TEXT NOT NULL,
 nature TEXT NOT NULL CHECK(nature IN ('debit','credit')),
 analytical INTEGER NOT NULL CHECK(analytical IN (0,1)),
 requires_cost_center INTEGER NOT NULL CHECK(requires_cost_center IN (0,1)),
 active INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1,
 UNIQUE(company_id,access_code), UNIQUE(company_id,classifier), UNIQUE(company_id,id)
);
CREATE TABLE IF NOT EXISTS cost_centers (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 code TEXT NOT NULL, name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 version INTEGER NOT NULL DEFAULT 1, UNIQUE(company_id,code), UNIQUE(company_id,id)
);
CREATE TABLE IF NOT EXISTS period_locks (
 company_id INTEGER NOT NULL REFERENCES companies(id), period TEXT NOT NULL,
 module TEXT NOT NULL CHECK(module IN ('fiscal','accounting')),
 closed INTEGER NOT NULL, reason TEXT NOT NULL, actor TEXT NOT NULL,
 changed_at TEXT NOT NULL, version INTEGER NOT NULL,
 PRIMARY KEY(company_id,period,module)
);
CREATE TABLE IF NOT EXISTS journals (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 number INTEGER NOT NULL, date TEXT NOT NULL, period TEXT NOT NULL,
 document TEXT NOT NULL, history TEXT NOT NULL, total_cents INTEGER NOT NULL CHECK(total_cents>0),
 idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL,
 reversal_of INTEGER REFERENCES journals(id), reversed_by INTEGER REFERENCES journals(id),
 created_at TEXT NOT NULL, created_by TEXT NOT NULL,
 UNIQUE(company_id,number), UNIQUE(company_id,idempotency_key), UNIQUE(company_id,id),
 UNIQUE(reversal_of)
);
CREATE TABLE IF NOT EXISTS journal_lines (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, journal_id INTEGER NOT NULL,
 position INTEGER NOT NULL, account_id INTEGER NOT NULL,
 debit_cents INTEGER NOT NULL CHECK(debit_cents>=0), credit_cents INTEGER NOT NULL CHECK(credit_cents>=0),
 cost_center_id INTEGER,
 CHECK ((debit_cents>0 AND credit_cents=0) OR (credit_cents>0 AND debit_cents=0)),
 FOREIGN KEY(company_id,journal_id) REFERENCES journals(company_id,id),
 FOREIGN KEY(company_id,account_id) REFERENCES accounts(company_id,id),
 FOREIGN KEY(company_id,cost_center_id) REFERENCES cost_centers(company_id,id),
 UNIQUE(journal_id,position)
);
CREATE TABLE IF NOT EXISTS documents (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 direction TEXT NOT NULL CHECK(direction IN ('incoming','outgoing')),
 number TEXT NOT NULL, series TEXT NOT NULL, model TEXT NOT NULL,
 issue_date TEXT NOT NULL, posting_date TEXT NOT NULL, period TEXT NOT NULL,
 partner_name TEXT NOT NULL, partner_tax_id TEXT NOT NULL, key TEXT NOT NULL,
 cfop TEXT NOT NULL, total_cents INTEGER NOT NULL CHECK(total_cents>=0),
 taxes_json TEXT NOT NULL, items_json TEXT NOT NULL, source_json TEXT NOT NULL,
 extra_json TEXT NOT NULL DEFAULT '{}',
 source_hash TEXT NOT NULL, business_key TEXT NOT NULL, payload_hash TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','reviewed','booked')),
 version INTEGER NOT NULL DEFAULT 1, journal_id INTEGER REFERENCES journals(id),
 reviewed_by TEXT, review_reason TEXT, booked_by TEXT, book_reason TEXT,
 created_at TEXT NOT NULL, UNIQUE(company_id,business_key), UNIQUE(company_id,id)
);
CREATE TABLE IF NOT EXISTS document_sources (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, document_id INTEGER NOT NULL,
 source_hash TEXT NOT NULL, source_json TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(company_id,document_id) REFERENCES documents(company_id,id),
 UNIQUE(document_id,source_hash,source_json)
);
CREATE TABLE IF NOT EXISTS titles (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 kind TEXT NOT NULL CHECK(kind IN ('payable','receivable')),
 description TEXT NOT NULL, partner_name TEXT NOT NULL, document TEXT NOT NULL,
 issue_date TEXT NOT NULL, due_date TEXT NOT NULL,
 amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
 paid_cents INTEGER NOT NULL DEFAULT 0 CHECK(paid_cents>=0 AND paid_cents<=amount_cents),
 document_id INTEGER, version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
 FOREIGN KEY(company_id,document_id) REFERENCES documents(company_id,id), UNIQUE(company_id,id)
);
CREATE TABLE IF NOT EXISTS settlements (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, title_id INTEGER NOT NULL,
 date TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
 reason TEXT NOT NULL, journal_id INTEGER REFERENCES journals(id),
 idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(company_id,title_id) REFERENCES titles(company_id,id),
 UNIQUE(company_id,idempotency_key)
);
CREATE TABLE IF NOT EXISTS bank_transactions (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 bank_account TEXT NOT NULL, date TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents<>0),
 description TEXT NOT NULL, reference TEXT NOT NULL, external_id TEXT NOT NULL,
 source_json TEXT NOT NULL, source_hash TEXT NOT NULL, fingerprint TEXT NOT NULL,
 payload_hash TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(company_id,bank_account,fingerprint), UNIQUE(company_id,id)
);
CREATE TABLE IF NOT EXISTS reconciliations (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL,
 transaction_id INTEGER NOT NULL UNIQUE, title_id INTEGER NOT NULL UNIQUE,
 reason TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL,
 FOREIGN KEY(company_id,transaction_id) REFERENCES bank_transactions(company_id,id),
 FOREIGN KEY(company_id,title_id) REFERENCES titles(company_id,id)
);
CREATE TABLE IF NOT EXISTS catalogs (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 kind TEXT NOT NULL, code TEXT NOT NULL, description TEXT NOT NULL, direction TEXT NOT NULL,
 valid_from TEXT NOT NULL, valid_to TEXT NOT NULL, source TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1,
 UNIQUE(company_id,kind,code,direction)
);
CREATE TABLE IF NOT EXISTS rules (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id), family_id TEXT NOT NULL,
 version INTEGER NOT NULL, name TEXT NOT NULL, tax TEXT NOT NULL, rate TEXT,
 direction TEXT NOT NULL, cfop TEXT NOT NULL, ncm TEXT NOT NULL,
 valid_from TEXT NOT NULL, valid_to TEXT NOT NULL, source TEXT NOT NULL,
 responsible TEXT NOT NULL, status TEXT NOT NULL, active INTEGER NOT NULL,
 superseded_by INTEGER REFERENCES rules(id), created_at TEXT NOT NULL, created_by TEXT NOT NULL,
 UNIQUE(company_id,family_id,version)
);
CREATE TABLE IF NOT EXISTS templates (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
 source_company_id INTEGER NOT NULL REFERENCES companies(id), rules_json TEXT NOT NULL,
 created_at TEXT NOT NULL, created_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calculations (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 rule_id INTEGER NOT NULL REFERENCES rules(id), payload_json TEXT NOT NULL,
 created_at TEXT NOT NULL, created_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS imports (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id), filename TEXT NOT NULL,
 sha256 TEXT NOT NULL, identity_hash TEXT NOT NULL, preview_hash TEXT NOT NULL,
 period TEXT NOT NULL, company_tax_id TEXT NOT NULL, options_json TEXT NOT NULL,
 original BLOB NOT NULL, parsed_json TEXT NOT NULL, status TEXT NOT NULL,
 bank_account TEXT NOT NULL, confirmation_json TEXT, created_at TEXT NOT NULL,
 created_by TEXT NOT NULL, UNIQUE(company_id,identity_hash), UNIQUE(company_id,id)
);
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY, company_id INTEGER REFERENCES companies(id), actor TEXT NOT NULL,
 action TEXT NOT NULL, entity TEXT NOT NULL, entity_id TEXT NOT NULL,
 details_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_journals_period ON journals(company_id,period,date);
CREATE INDEX IF NOT EXISTS idx_lines_account ON journal_lines(company_id,account_id,journal_id);
CREATE INDEX IF NOT EXISTS idx_documents_period ON documents(company_id,period,status);
CREATE INDEX IF NOT EXISTS idx_titles_due ON titles(company_id,due_date);
CREATE INDEX IF NOT EXISTS idx_bank_date ON bank_transactions(company_id,date);
CREATE INDEX IF NOT EXISTS idx_audit_company ON audit(company_id,id);
"""


class Database:
    def __init__(self, data_dir=None):
        if data_dir is None:
            data_dir = os.environ.get("ESCRITURA_DATA_DIR")
        if not data_dir:
            if os.name == "nt":
                data_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "EscrituraIntegrada"
            elif sys.platform == "darwin":
                data_dir = Path.home() / "Library/Application Support/Codisplan/Escritura Integrada/data"
            else:
                data_dir = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "escritura-integrada"
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "escritura.sqlite3"
        from .maintenance import backup_before_schema
        self.upgrade_backup = backup_before_schema(self.path)
        with self.read() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            conn.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('schema_version','1')")
            from .migrations import migrate
            migrate(conn)
        if os.name != "nt":
            self.path.chmod(0o600)

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    @contextmanager
    def read(self, snapshot=False):
        conn = self.connect()
        try:
            if snapshot:
                conn.execute("BEGIN")
            yield conn
        finally:
            conn.rollback()
            conn.close()

    @contextmanager
    def transaction(self):
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            expected = request_context.get()
            if expected:
                session = conn.execute("SELECT active_company_id,period,module,expires_at FROM sessions WHERE token_hash=?", (expected["token_hash"],)).fetchone()
                if not session or session["expires_at"] <= time.time():
                    raise ContextConflict("A sessão foi encerrada. Entre novamente antes de salvar.")
                if expected.get("user_id"):
                    from .permissions import require
                    require(conn, expected["user_id"], expected.get("permission_company_id"),
                            expected.get("routine"), expected.get("action", "read"), expected.get("admin", False))
                if expected.get("company_id") is not None and (session["active_company_id"] != expected["company_id"] or session["period"][:4] != expected["period"][:4] or (expected.get("module") and session["module"] != expected["module"])):
                    raise ContextConflict("A empresa ou competência ativa mudou. Reabra o lançamento no contexto correto.")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
