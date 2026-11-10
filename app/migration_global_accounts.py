"""Account identity is company + access, never a classification bucket.

SQLite cannot drop a table UNIQUE constraint. Rebuild only accounts, retaining
every column, id, index, trigger and dependent FK target. The connection is
exclusive to startup; foreign keys are disabled only around this transaction,
and checked before commit. A pre-schema backup is made by Database.
"""
import re
import json


def migrate_global_accounts(conn):
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='accounts'").fetchone()[0]
    unique = r',\s*UNIQUE\s*\(\s*company_id\s*,\s*classifier\s*\)'
    nullable={'classifier','name','nature','analytical','requires_cost_center','active','report_group','prosoft_code'}
    needs_rebuild = 'account_definition_or_reference' not in sql or bool(re.search(unique, sql, re.I)) or 'shared_entry_id' not in sql or any(r['name'] in nullable and r['notnull'] for r in conn.execute('PRAGMA table_info(accounts)'))
    conn.execute('PRAGMA foreign_keys=OFF')
    try:
        conn.execute('BEGIN IMMEDIATE')
        if needs_rebuild:
            conn.execute('DROP VIEW IF EXISTS effective_accounts')
            objects = [r['sql'] for r in conn.execute("SELECT sql FROM sqlite_master WHERE tbl_name='accounts' AND type IN ('index','trigger') AND sql IS NOT NULL")]
            replacement = re.sub(unique, '', sql, flags=re.I)
            # Local attributes stay intact; new shared references leave them NULL.
            for column,kind in [('classifier','TEXT'),('name','TEXT'),('nature','TEXT'),('analytical','INTEGER'),('requires_cost_center','INTEGER'),('active','INTEGER'),('report_group','TEXT'),('prosoft_code','TEXT')]:
                replacement=re.sub(rf'({column}\s+{kind})\s+NOT NULL',r'\1',replacement,flags=re.I)
            if 'shared_entry_id' not in replacement:
                replacement=replacement.rstrip().removesuffix(')')+', shared_entry_id INTEGER REFERENCES global_account_entries(id))'
            if 'account_definition_or_reference' not in replacement:
                replacement=replacement.rstrip().removesuffix(')')+", CONSTRAINT account_definition_or_reference CHECK(shared_entry_id IS NOT NULL OR (classifier IS NOT NULL AND name IS NOT NULL AND nature IS NOT NULL AND analytical IS NOT NULL AND requires_cost_center IS NOT NULL AND active IS NOT NULL)))"
            replacement, renamed = re.subn(r'CREATE TABLE(?: IF NOT EXISTS)?\s+(?:"accounts"|`accounts`|\[accounts\]|accounts)', 'CREATE TABLE accounts_global_migration', replacement, count=1, flags=re.I)
            if renamed != 1:
                raise RuntimeError('Estrutura de contas não reconhecida; migração cancelada sem alterar contas.')
            conn.execute(replacement)
            columns = ','.join('"'+r['name'].replace('"','""')+'"' for r in conn.execute('PRAGMA table_info(accounts)'))
            conn.execute(f'INSERT INTO accounts_global_migration({columns}) SELECT {columns} FROM accounts')
            conn.execute('DROP TABLE accounts')
            conn.execute('ALTER TABLE accounts_global_migration RENAME TO accounts')
            for statement in objects:
                conn.execute(statement)
        conn.execute('CREATE INDEX IF NOT EXISTS account_classifier_group ON accounts(company_id,classifier,access_code)')
        conn.execute('''CREATE TABLE IF NOT EXISTS global_account_plans (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
            source_company_id INTEGER NOT NULL REFERENCES companies(id), source_batch_id INTEGER NOT NULL,
            parent_id INTEGER REFERENCES global_account_plans(id), plan_json TEXT NOT NULL,
            filename TEXT NOT NULL, format TEXT NOT NULL, original BLOB NOT NULL, sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL, created_by TEXT NOT NULL,
            FOREIGN KEY(source_company_id,source_batch_id) REFERENCES account_plan_batches(company_id,id))''')
        conn.execute('''CREATE TABLE IF NOT EXISTS company_account_plan_bindings (
            company_id INTEGER PRIMARY KEY REFERENCES companies(id),
            global_plan_id INTEGER NOT NULL REFERENCES global_account_plans(id),
            mode TEXT NOT NULL CHECK(mode IN ('shared','own')), version INTEGER NOT NULL DEFAULT 1,
            attached_at TEXT NOT NULL, attached_by TEXT NOT NULL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS global_account_plan_links (
            company_id INTEGER NOT NULL, account_id INTEGER NOT NULL, global_plan_id INTEGER NOT NULL,
            access_code TEXT NOT NULL, PRIMARY KEY(company_id,account_id),
            FOREIGN KEY(company_id,account_id) REFERENCES accounts(company_id,id),
            FOREIGN KEY(global_plan_id) REFERENCES global_account_plans(id))''')
        conn.execute('''CREATE TABLE IF NOT EXISTS global_account_plan_previews (
            id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
            global_plan_id INTEGER NOT NULL REFERENCES global_account_plans(id), mode TEXT NOT NULL,
            state_hash TEXT NOT NULL, preview_hash TEXT NOT NULL, result_json TEXT,
            created_at TEXT NOT NULL, created_by TEXT NOT NULL)''')
        for table in ('company_account_plan_bindings','global_account_plan_previews'):
            if 'copy_scope' not in {r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN copy_scope TEXT NOT NULL DEFAULT 'all' CHECK(copy_scope IN ('all','used'))")
        conn.execute('''CREATE TABLE IF NOT EXISTS global_account_entries (
            id INTEGER PRIMARY KEY, global_plan_id INTEGER NOT NULL REFERENCES global_account_plans(id),
            access_code TEXT NOT NULL, classifier TEXT NOT NULL, name TEXT NOT NULL,
            nature TEXT NOT NULL CHECK(nature IN ('debit','credit')),
            analytical INTEGER NOT NULL CHECK(analytical IN (0,1)), requires_cost_center INTEGER NOT NULL CHECK(requires_cost_center IN (0,1)),
            active INTEGER NOT NULL, report_group TEXT NOT NULL, prosoft_code TEXT NOT NULL,
            prosoft_json TEXT NOT NULL, extras_json TEXT NOT NULL,
            UNIQUE(global_plan_id,access_code))''')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS company_global_account_identity ON accounts(company_id,shared_entry_id) WHERE shared_entry_id IS NOT NULL')
        conn.execute('''CREATE TABLE IF NOT EXISTS company_account_aliases (
            company_id INTEGER NOT NULL, global_entry_id INTEGER NOT NULL REFERENCES global_account_entries(id),
            account_id INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 1 CHECK(used IN (0,1)),
            PRIMARY KEY(company_id,global_entry_id),
            FOREIGN KEY(company_id,account_id) REFERENCES accounts(company_id,id))''')
        # Upgrade unshipped prototype/shared definitions without dropping any originals.
        from .account_plans import FIELDS,account_values
        from .core import pack
        for plan in conn.execute('SELECT id,plan_json FROM global_account_plans'):
            incoming=json.loads(plan['plan_json'])['accounts']
            if conn.execute('SELECT COUNT(*) FROM global_account_entries WHERE global_plan_id=?',(plan['id'],)).fetchone()[0]==len(incoming):continue
            for raw in incoming:
                a=account_values(raw)
                extras={k:v for k,v in a.items() if k not in {*FIELDS,'prosoft'}}
                conn.execute(f"INSERT INTO global_account_entries(global_plan_id,{','.join(FIELDS)},prosoft_json,extras_json) VALUES({','.join('?' for _ in range(len(FIELDS)+3))}) ON CONFLICT(global_plan_id,access_code) DO NOTHING",(plan['id'],*(a[k] for k in FIELDS),pack(a['prosoft']),pack(extras)))
        conn.execute('DROP VIEW IF EXISTS effective_accounts')
        conn.execute('''CREATE VIEW effective_accounts AS
            SELECT a.id,a.company_id,a.access_code,
                COALESCE(a.classifier,g.classifier) AS classifier, COALESCE(a.name,g.name) AS name,
                COALESCE(a.nature,g.nature) AS nature,COALESCE(a.analytical,g.analytical) AS analytical,
                COALESCE(a.requires_cost_center,g.requires_cost_center) AS requires_cost_center,
                COALESCE(a.active,g.active) AS active,a.version,
                COALESCE(a.report_group,g.report_group) AS report_group,COALESCE(a.prosoft_code,g.prosoft_code) AS prosoft_code,
                a.shared_entry_id
            FROM accounts a LEFT JOIN global_account_entries g ON g.id=a.shared_entry_id
            UNION ALL
            SELECT -g.id,b.company_id,g.access_code,g.classifier,g.name,g.nature,g.analytical,g.requires_cost_center,g.active,1,g.report_group,g.prosoft_code,g.id
            FROM company_account_plan_bindings b JOIN global_account_entries g ON g.global_plan_id=b.global_plan_id
            WHERE b.mode='shared' AND NOT EXISTS(SELECT 1 FROM accounts a WHERE a.company_id=b.company_id AND a.access_code=g.access_code)''')
        if conn.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise RuntimeError('Vínculos inválidos após migração do plano; atualização revertida.')
        conn.execute("UPDATE meta SET value='6' WHERE key='schema_version'")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.execute('PRAGMA foreign_keys=ON')
