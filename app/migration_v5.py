"""Auditor: progresso, catálogos completos e artefatos verificáveis, sem alterar a escrituração."""
def migrate_v5(conn):
    additions = {
        'auditor_jobs': [('name', "TEXT NOT NULL DEFAULT ''"), ('stage', "TEXT NOT NULL DEFAULT 'queued'"),
                         ('progress', 'INTEGER NOT NULL DEFAULT 0'), ('processed_files', 'INTEGER NOT NULL DEFAULT 0'),
                         ('total_files', 'INTEGER NOT NULL DEFAULT 0'), ('parent_id', 'INTEGER'),
                         ('started_at', 'TEXT')],
        'auditor_catalogs': [('reference_json', "TEXT NOT NULL DEFAULT '{}'"), ('parent_id', 'INTEGER')],
    }
    for table, fields in additions.items():
        existing = {r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}
        for name, definition in fields:
            if name not in existing:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
    conn.execute('''CREATE TABLE IF NOT EXISTS auditor_reports (
        id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, job_id INTEGER NOT NULL,
        format TEXT NOT NULL, revision TEXT NOT NULL, file_id INTEGER NOT NULL,
        created_at TEXT NOT NULL, created_by TEXT NOT NULL,
        FOREIGN KEY(company_id,job_id) REFERENCES auditor_jobs(company_id,id),
        FOREIGN KEY(company_id,file_id) REFERENCES stored_files(company_id,id),
        UNIQUE(company_id,job_id,format,revision))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS auditor_attachments (
        id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, job_id INTEGER NOT NULL,
        document_ref TEXT NOT NULL, file_id INTEGER NOT NULL, reason TEXT NOT NULL,
        created_at TEXT NOT NULL, created_by TEXT NOT NULL,
        FOREIGN KEY(company_id,job_id) REFERENCES auditor_jobs(company_id,id),
        FOREIGN KEY(company_id,file_id) REFERENCES stored_files(company_id,id),
        UNIQUE(company_id,job_id,document_ref,file_id))''')
    conn.execute('CREATE INDEX IF NOT EXISTS auditor_job_scope ON auditor_jobs(company_id,year,id)')
    conn.execute('CREATE INDEX IF NOT EXISTS auditor_findings_scope ON auditor_findings(company_id,job_id,id)')
    conn.execute("UPDATE meta SET value='5' WHERE key='schema_version'")
