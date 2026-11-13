"""Atomic shared fiscal references; existing company data is never moved."""

DDL = (
    '''CREATE TABLE IF NOT EXISTS global_fiscal_sources (
      bundle_id TEXT PRIMARY KEY, data_json TEXT NOT NULL, sha256 TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS global_fiscal_catalogs (
      id INTEGER PRIMARY KEY, kind TEXT NOT NULL, code TEXT NOT NULL, namespace TEXT NOT NULL DEFAULT '',
      data_json TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
      version INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL, UNIQUE(kind,namespace,code))''',
    '''CREATE TABLE IF NOT EXISTS fiscal_library_versions (
      entity_type TEXT NOT NULL, entity_id INTEGER NOT NULL, version INTEGER NOT NULL,
      data_json TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL,
      PRIMARY KEY(entity_type,entity_id,version))''',
    '''CREATE TABLE IF NOT EXISTS fiscal_patterns (
      id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, data_json TEXT NOT NULL,
      active INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS company_fiscal_pattern_imports (
      id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
      pattern_id INTEGER NOT NULL REFERENCES fiscal_patterns(id), pattern_version INTEGER NOT NULL,
      fingerprint TEXT NOT NULL, snapshot_json TEXT NOT NULL, rule_ids_json TEXT NOT NULL,
      created_at TEXT NOT NULL, created_by TEXT NOT NULL, UNIQUE(company_id,fingerprint))''',
)


def migrate(conn):
    # Never silently commit or take ownership of a caller's transaction.
    if conn.in_transaction:
        raise RuntimeError('A migração da biblioteca fiscal exige conexão sem transação aberta.')
    conn.execute('BEGIN IMMEDIATE')
    try:
        for statement in DDL:
            conn.execute(statement)
        _seed(conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _seed(conn):
    from .cfop import reference, reference_index
    from .cfop_source import default_source_bundle
    from .core import pack, now
    import hashlib
    original=pack(default_source_bundle())
    conn.execute('INSERT OR IGNORE INTO global_fiscal_sources VALUES(?,?,?)',
                 (default_source_bundle()['bundle_id'],original,hashlib.sha256(original.encode()).hexdigest()))
    declared = {r['code']: r for r in default_source_bundle()['records']}
    for code, wordings in reference_index().items():
        row = wordings[-1]; source = declared.get(code, {})
        data = {'description': row['title'], 'direction': row['direction'], 'official_wordings': wordings,
                'source': reference()['source'], 'valid_from': '', 'valid_to': '',
                'rates_declared': source.get('rates_declared', []),
                'source_rates_declared': source.get('rates_declared', []),
                'parameters_declared': source.get('parameters_declared', {}),
                'source_bundle_id': default_source_bundle()['bundle_id'],
                'review_status': 'unreviewed', 'informational_only': True}
        conn.execute('INSERT OR IGNORE INTO global_fiscal_catalogs(kind,code,data_json,updated_at) VALUES(?,?,?,?)',
                     ('cfop', code, pack(data), now()))

    for row in conn.execute("SELECT * FROM global_fiscal_catalogs"):
        conn.execute("INSERT OR IGNORE INTO fiscal_library_versions VALUES(?,?,?,?,?,?)", ('catalog', row['id'], row['version'], pack(dict(row)), now(), 'reference-seed'))
