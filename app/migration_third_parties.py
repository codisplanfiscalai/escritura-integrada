"""Additive identity index. No existing master or document/title FK is rewritten."""


def migrate_third_parties(conn):
    conn.execute('BEGIN IMMEDIATE')
    try:
        for sql in [
            '''CREATE TABLE IF NOT EXISTS third_parties (
                id INTEGER PRIMARY KEY, entity_type TEXT NOT NULL CHECK(entity_type IN ('organization','person')),
                identity_key TEXT NOT NULL, UNIQUE(entity_type,identity_key))''',
            '''CREATE TABLE IF NOT EXISTS third_party_establishments (
                id INTEGER PRIMARY KEY, third_party_id INTEGER NOT NULL REFERENCES third_parties(id),
                tax_id TEXT NOT NULL UNIQUE, UNIQUE(third_party_id,id))''',
            '''CREATE TABLE IF NOT EXISTS third_party_company_links (
                company_id INTEGER NOT NULL, master_id INTEGER NOT NULL, third_party_id INTEGER NOT NULL REFERENCES third_parties(id),
                establishment_id INTEGER, snapshot_json TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(company_id,master_id),
                FOREIGN KEY(company_id,master_id) REFERENCES masters(company_id,id),
                FOREIGN KEY(third_party_id,establishment_id) REFERENCES third_party_establishments(third_party_id,id))''',
            '''CREATE TABLE IF NOT EXISTS third_party_history (
                id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, master_id INTEGER NOT NULL,
                event TEXT NOT NULL, details_json TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY(company_id,master_id) REFERENCES masters(company_id,id))''',
            'CREATE INDEX IF NOT EXISTS third_party_history_scope ON third_party_history(company_id,master_id,id)',
            '''CREATE TABLE IF NOT EXISTS third_party_replacements (
                company_id INTEGER NOT NULL, master_id INTEGER NOT NULL, replacement_master_id INTEGER NOT NULL,
                reason TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY(company_id,master_id), CHECK(master_id<>replacement_master_id),
                FOREIGN KEY(company_id,master_id) REFERENCES masters(company_id,id),
                FOREIGN KEY(company_id,replacement_master_id) REFERENCES masters(company_id,id))''',
        ]:
            conn.execute(sql)
        from .third_parties import sync_third_party
        for row in conn.execute("SELECT id,company_id FROM masters WHERE kind IN ('participant','establishment') ORDER BY id").fetchall():
            sync_third_party(conn, row['company_id'], row['id'], 'migration', 'Vínculo aditivo; cadastro local preservado.')
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('third_parties_schema_version','1')")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
