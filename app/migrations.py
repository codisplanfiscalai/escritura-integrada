"""Migrações aditivas; preservam bancos 0.4.x e executam em uma transação."""

def migrate(conn):
    conn.execute('BEGIN IMMEDIATE')
    try:
        additions = {
            'companies': {'profile_json': "TEXT NOT NULL DEFAULT '{}'"},
            'users': {'role': "TEXT NOT NULL DEFAULT 'admin'", 'active': 'INTEGER NOT NULL DEFAULT 1'},
            'accounts': {'report_group': "TEXT NOT NULL DEFAULT ''", 'prosoft_code': "TEXT NOT NULL DEFAULT ''"},
            'journal_lines': {'participant_id': 'INTEGER REFERENCES masters(id)'},
            'cost_centers': {'prosoft_code': "TEXT NOT NULL DEFAULT ''"},
            'titles': {'participant_id': 'INTEGER REFERENCES masters(id)', 'source_key': 'TEXT', 'request_hash': "TEXT NOT NULL DEFAULT ''", 'cancelled': 'INTEGER NOT NULL DEFAULT 0', 'renegotiation_id': 'INTEGER', 'installment': 'INTEGER NOT NULL DEFAULT 1'},
            'settlements': {'interest_cents': 'INTEGER NOT NULL DEFAULT 0', 'fine_cents': 'INTEGER NOT NULL DEFAULT 0', 'discount_cents': 'INTEGER NOT NULL DEFAULT 0', 'cash_cents': 'INTEGER', 'reversed_at': 'TEXT', 'reversal_date': 'TEXT', 'reversal_reason': 'TEXT', 'reversal_journal_id': 'INTEGER REFERENCES journals(id)'},
        }
        for table, fields in additions.items():
            existing = {r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}
            for name, definition in fields.items():
                if name not in existing:
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
        statements = [
            '''CREATE TABLE IF NOT EXISTS account_plan_batches (
                id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
                filename TEXT NOT NULL, format TEXT NOT NULL, sha256 TEXT NOT NULL, original BLOB NOT NULL,
                options_json TEXT NOT NULL, plan_json TEXT NOT NULL, preview_hash TEXT NOT NULL, state_hash TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('preview','confirmed','reference')), confirmation_json TEXT,
                created_at TEXT NOT NULL, created_by TEXT NOT NULL, UNIQUE(company_id,id))''',
            '''CREATE TABLE IF NOT EXISTS account_plan_properties (
                company_id INTEGER PRIMARY KEY REFERENCES companies(id), properties_json TEXT NOT NULL, extras_json TEXT NOT NULL DEFAULT '{}')''',
            '''CREATE TABLE IF NOT EXISTS account_plan_metadata (
                company_id INTEGER NOT NULL, account_id INTEGER NOT NULL, prosoft_json TEXT NOT NULL, extras_json TEXT NOT NULL DEFAULT '{}', batch_id INTEGER NOT NULL,
                PRIMARY KEY(company_id,account_id),
                FOREIGN KEY(company_id,account_id) REFERENCES accounts(company_id,id),
                FOREIGN KEY(company_id,batch_id) REFERENCES account_plan_batches(company_id,id))''',
            '''CREATE TABLE IF NOT EXISTS masters (
                id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
                kind TEXT NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL, tax_id TEXT NOT NULL DEFAULT '',
                data_json TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(company_id,kind,code), UNIQUE(company_id,id))''',
            "CREATE UNIQUE INDEX IF NOT EXISTS master_tax_identity ON masters(company_id,kind,tax_id) WHERE tax_id<>''",
            'CREATE UNIQUE INDEX IF NOT EXISTS title_source_identity ON titles(company_id,source_key) WHERE source_key IS NOT NULL',
            '''CREATE TABLE IF NOT EXISTS operations (
                company_id INTEGER NOT NULL REFERENCES companies(id), scope TEXT NOT NULL, key TEXT NOT NULL,
                request_hash TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY(company_id,scope,key))''',
            '''CREATE TABLE IF NOT EXISTS renegotiations (
                id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
                date TEXT NOT NULL, reason TEXT NOT NULL, original_ids_json TEXT NOT NULL,
                principal_cents INTEGER NOT NULL, interest_cents INTEGER NOT NULL, discount_cents INTEGER NOT NULL,
                created_at TEXT NOT NULL, created_by TEXT NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS bank_allocations (
                id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, transaction_id INTEGER NOT NULL,
                title_id INTEGER NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
                settlement_id INTEGER REFERENCES settlements(id), reason TEXT NOT NULL,
                created_at TEXT NOT NULL, created_by TEXT NOT NULL, reversed_at TEXT,
                FOREIGN KEY(company_id,transaction_id) REFERENCES bank_transactions(company_id,id),
                FOREIGN KEY(company_id,title_id) REFERENCES titles(company_id,id))''',
            '''CREATE TABLE IF NOT EXISTS lookup_cache (
                kind TEXT NOT NULL, query TEXT NOT NULL, provider TEXT NOT NULL,
                data_json TEXT NOT NULL, fetched_at TEXT NOT NULL, expires_at REAL NOT NULL,
                PRIMARY KEY(kind,query,provider))''',
            '''CREATE TABLE IF NOT EXISTS lookup_limits (
                provider TEXT PRIMARY KEY, window_start REAL NOT NULL, count INTEGER NOT NULL,
                blocked_until REAL NOT NULL DEFAULT 0)''',
            '''CREATE TABLE IF NOT EXISTS user_companies (
                user_id INTEGER NOT NULL REFERENCES users(id), company_id INTEGER NOT NULL REFERENCES companies(id),
                PRIMARY KEY(user_id,company_id))''',
            '''CREATE TABLE IF NOT EXISTS tax_adjustments (
                id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id), period TEXT NOT NULL,
                tax TEXT NOT NULL, kind TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
                source TEXT NOT NULL, reason TEXT NOT NULL, document_id INTEGER, created_at TEXT NOT NULL,
                created_by TEXT NOT NULL, reversed_at TEXT,
                FOREIGN KEY(company_id,document_id) REFERENCES documents(company_id,id))''',
            '''CREATE TABLE IF NOT EXISTS tax_assessments (
                id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id), period TEXT NOT NULL,
                tax TEXT NOT NULL, source TEXT NOT NULL, responsible TEXT NOT NULL, snapshot_json TEXT NOT NULL,
                fingerprint TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS export_batches (
                id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id), period TEXT NOT NULL,
                layout TEXT NOT NULL, fingerprint TEXT NOT NULL, filename TEXT NOT NULL, content BLOB NOT NULL,
                manifest_json TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL,
                UNIQUE(company_id,layout,fingerprint))''',
        ]
        for sql in statements:
            conn.execute(sql)
        if 'reversed_at' not in {r['name'] for r in conn.execute('PRAGMA table_info(renegotiations)')}:
            conn.execute('ALTER TABLE renegotiations ADD COLUMN reversed_at TEXT')
        conn.execute("UPDATE settlements SET cash_cents=amount_cents WHERE cash_cents IS NULL")
        from .migration_v3 import migrate_v3
        migrate_v3(conn)
        from .migration_v4 import migrate_v4
        migrate_v4(conn)
        from .migration_v5 import migrate_v5
        migrate_v5(conn)
        from .bulk_operations import initialize_bulk_schema
        initialize_bulk_schema(conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
