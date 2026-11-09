"""Exercícios, permissões e encerramento de apurações, sem apagar movimentos."""
from datetime import date, datetime, timezone


def migrate_v3(conn):
    current = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if current and int(current[0]) >= 3:
        return
    for table, column, definition in (
        ('users', 'version', 'INTEGER NOT NULL DEFAULT 1'),
        ('sessions', 'module', "TEXT NOT NULL DEFAULT 'fiscal'"),
        ('rules', 'regime', "TEXT NOT NULL DEFAULT ''"),
        ('rules', 'state', "TEXT NOT NULL DEFAULT ''"),
        ('rules', 'municipality', "TEXT NOT NULL DEFAULT ''"),
        ('tax_adjustments', 'category', "TEXT NOT NULL DEFAULT 'other'"),
    ):
        if column not in {r['name'] for r in conn.execute('PRAGMA table_info(' + table + ')')}:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
    # O CHECK anterior impedia Financeiro e Social. Não há referências a esta tabela.
    conn.execute('ALTER TABLE period_locks RENAME TO period_locks_v2')
    conn.execute('''CREATE TABLE period_locks (
        company_id INTEGER NOT NULL REFERENCES companies(id),period TEXT NOT NULL,
        module TEXT NOT NULL CHECK(module IN ('fiscal','accounting','financial','social')),
        closed INTEGER NOT NULL,reason TEXT NOT NULL,actor TEXT NOT NULL,changed_at TEXT NOT NULL,version INTEGER NOT NULL,
        PRIMARY KEY(company_id,period,module))''')
    conn.execute('INSERT INTO period_locks SELECT * FROM period_locks_v2')
    conn.execute('DROP TABLE period_locks_v2')
    definitions = [
        '''CREATE TABLE exercises(company_id INTEGER NOT NULL REFERENCES companies(id),module TEXT NOT NULL,
            year INTEGER NOT NULL CHECK(year BETWEEN 1900 AND 2199),created_at TEXT NOT NULL,created_by TEXT NOT NULL,
            PRIMARY KEY(company_id,module,year))''',
        '''CREATE TABLE session_contexts(token_hash TEXT NOT NULL REFERENCES sessions(token_hash) ON DELETE CASCADE,
            company_id INTEGER NOT NULL REFERENCES companies(id),module TEXT NOT NULL,period TEXT NOT NULL,
            PRIMARY KEY(token_hash,company_id,module))''',
        '''CREATE TABLE access_groups(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            description TEXT NOT NULL DEFAULT '',active INTEGER NOT NULL DEFAULT 1,version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''',
        '''CREATE TABLE group_users(group_id INTEGER NOT NULL REFERENCES access_groups(id),user_id INTEGER NOT NULL REFERENCES users(id),
            PRIMARY KEY(group_id,user_id))''',
        '''CREATE TABLE group_companies(group_id INTEGER NOT NULL REFERENCES access_groups(id),company_id INTEGER NOT NULL REFERENCES companies(id),
            PRIMARY KEY(group_id,company_id))''',
        '''CREATE TABLE user_company_access(user_id INTEGER NOT NULL REFERENCES users(id),company_id INTEGER NOT NULL REFERENCES companies(id),
            effect TEXT NOT NULL CHECK(effect IN ('allow','deny')),PRIMARY KEY(user_id,company_id))''',
        '''CREATE TABLE group_permissions(group_id INTEGER NOT NULL REFERENCES access_groups(id),company_id INTEGER NOT NULL REFERENCES companies(id),
            routine TEXT NOT NULL,action TEXT NOT NULL,effect TEXT NOT NULL CHECK(effect IN ('allow','deny')),
            PRIMARY KEY(group_id,company_id,routine,action))''',
        '''CREATE TABLE user_permissions(user_id INTEGER NOT NULL REFERENCES users(id),company_id INTEGER NOT NULL REFERENCES companies(id),
            routine TEXT NOT NULL,action TEXT NOT NULL,effect TEXT NOT NULL CHECK(effect IN ('allow','deny')),
            PRIMARY KEY(user_id,company_id,routine,action))''',
        '''CREATE TABLE tax_ledgers(id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL REFERENCES companies(id),
            period TEXT NOT NULL,tax TEXT NOT NULL,assessment_id INTEGER NOT NULL REFERENCES tax_assessments(id),
            previous_id INTEGER REFERENCES tax_ledgers(id),opening_credit_cents INTEGER NOT NULL,carry_credit_cents INTEGER NOT NULL,
            payable_cents INTEGER NOT NULL,snapshot_json TEXT NOT NULL,fingerprint TEXT NOT NULL,reason TEXT NOT NULL,
            created_at TEXT NOT NULL,created_by TEXT NOT NULL,reversed_at TEXT,reversed_by TEXT,reversal_reason TEXT)''',
        'CREATE UNIQUE INDEX tax_ledger_active ON tax_ledgers(company_id,period,tax) WHERE reversed_at IS NULL',
    ]
    for sql in definitions:
        conn.execute(sql)
    stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    for company in conn.execute('SELECT id FROM companies').fetchall():
        cid = company['id']; years = {date.today().year}
        for table, field in [('documents','period'),('journals','period'),('imports','period'),('period_locks','period'),('titles','issue_date'),('bank_transactions','date')]:
            years.update(int(r[0]) for r in conn.execute(f'SELECT DISTINCT substr({field},1,4) FROM {table} WHERE company_id=?', (cid,)) if r[0] and str(r[0]).isdigit())
        for module in ('fiscal','accounting','financial','social'):
            for year in years:
                conn.execute('INSERT INTO exercises VALUES(?,?,?,?,?)', (cid,module,year,stamp,'migração 0.6'))
    # Materializa o acesso anterior para não ampliar nem revogar permissões silenciosamente.
    from .permissions import ROUTINES
    for row in conn.execute('SELECT uc.*,u.role FROM user_companies uc JOIN users u ON u.id=uc.user_id').fetchall():
        if row['role'] == 'admin': continue
        for routine, (_, actions) in ROUTINES.items():
            for action in actions.split():
                if row['role'] == 'viewer' and action not in {'read','export','print'}: continue
                conn.execute('INSERT INTO user_permissions VALUES(?,?,?,?,?)', (row['user_id'],row['company_id'],routine,action,'allow'))
    conn.execute("UPDATE meta SET value='3' WHERE key='schema_version'")
