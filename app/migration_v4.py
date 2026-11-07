"""Extensão modular; não altera IDs nem divide vínculos transacionais existentes."""
def migrate_v4(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS stored_files (
      id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id), year INTEGER NOT NULL,
      category TEXT NOT NULL, filename TEXT NOT NULL, sha256 TEXT NOT NULL, content BLOB NOT NULL,
      created_at TEXT NOT NULL, created_by TEXT NOT NULL,
      UNIQUE(company_id,year,category,sha256), UNIQUE(company_id,id))''')
    # Os originais legados continuam intactos em imports. Este índice permite
    # reconstruir os diretórios anuais e inclui o histórico no backup verificável.
    if not conn.execute("SELECT 1 FROM meta WHERE key='files_organized_v4'").fetchone():
        conn.execute('''INSERT OR IGNORE INTO stored_files(company_id,year,category,filename,sha256,content,created_at,created_by)
          SELECT company_id,CAST(substr(period,1,4) AS INTEGER),'originals',filename,sha256,original,created_at,created_by
          FROM imports WHERE length(original)>0''')
        conn.execute("INSERT INTO meta(key,value) VALUES('files_organized_v4','1')")
    conn.execute('''CREATE TABLE IF NOT EXISTS module_imports (
      id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id), module TEXT NOT NULL,
      year INTEGER NOT NULL, layout TEXT NOT NULL, file_id INTEGER NOT NULL,
      fingerprint TEXT NOT NULL, preview_json TEXT NOT NULL, result_json TEXT,
      created_at TEXT NOT NULL, created_by TEXT NOT NULL,
      FOREIGN KEY(company_id,file_id) REFERENCES stored_files(company_id,id),
      UNIQUE(company_id,module,year,layout,fingerprint))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS auditor_catalogs (
      id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id), name TEXT NOT NULL,
      version INTEGER NOT NULL DEFAULT 1, state TEXT NOT NULL DEFAULT 'draft', source TEXT NOT NULL,
      valid_from TEXT NOT NULL, valid_to TEXT NOT NULL, content_json TEXT NOT NULL, sha256 TEXT NOT NULL,
      created_at TEXT NOT NULL, created_by TEXT NOT NULL, published_at TEXT, published_by TEXT,
      review_reason TEXT, source_id INTEGER, UNIQUE(company_id,id))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS auditor_catalog_sources (
      id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id), file_id INTEGER NOT NULL,
      preview_json TEXT NOT NULL, created_at TEXT NOT NULL,
      FOREIGN KEY(company_id,file_id) REFERENCES stored_files(company_id,id), UNIQUE(company_id,id))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS auditor_jobs (
      id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id), year INTEGER NOT NULL,
      mode TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
      version INTEGER NOT NULL DEFAULT 1, request_key TEXT NOT NULL, request_hash TEXT NOT NULL,
      snapshot_json TEXT NOT NULL, result_json TEXT, error TEXT, cancelled INTEGER NOT NULL DEFAULT 0,
      deleted_at TEXT, created_at TEXT NOT NULL, created_by TEXT NOT NULL, user_id INTEGER REFERENCES users(id),
      finished_at TEXT, UNIQUE(company_id,request_key), UNIQUE(company_id,id))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS auditor_findings (
      id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, job_id INTEGER NOT NULL,
      payload_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', responsible TEXT NOT NULL DEFAULT '',
      treatment TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1, updated_at TEXT,
      FOREIGN KEY(company_id,job_id) REFERENCES auditor_jobs(company_id,id), UNIQUE(company_id,id))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS auditor_logs (
      id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, job_id INTEGER NOT NULL,
      level TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL,
      FOREIGN KEY(company_id,job_id) REFERENCES auditor_jobs(company_id,id))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS auditor_auxiliary (
      id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, job_id INTEGER NOT NULL, document_ref TEXT NOT NULL,
      file_id INTEGER NOT NULL, renderer TEXT NOT NULL, source_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
      FOREIGN KEY(company_id,job_id) REFERENCES auditor_jobs(company_id,id),
      FOREIGN KEY(company_id,file_id) REFERENCES stored_files(company_id,id),
      UNIQUE(company_id,job_id,document_ref))''')
    conn.execute("UPDATE meta SET value='4' WHERE key='schema_version'")
