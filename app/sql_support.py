"""Explicit backend differences. Values always remain driver parameters."""


def insert_id(conn, statement, parameters=()):
    # Called only with application INSERT statements, not user SQL.
    if getattr(conn, 'backend', 'sqlite') == 'postgresql':
        return conn.execute(statement + ' RETURNING id', parameters).fetchone()[0]
    return conn.execute(statement, parameters).lastrowid


def dialect(conn, sqlite, postgres):
    return postgres if getattr(conn, 'backend', 'sqlite') == 'postgresql' else sqlite


def has_table(conn, name):
    return conn.execute(dialect(conn,
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        "SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=?"), (name,)).fetchone() is not None


def foreign_keys(conn):
    if getattr(conn, 'backend', 'sqlite') == 'postgresql':
        return conn.execute('''SELECT t.relname AS child, a.attname AS "from", r.relname AS "table", b.attname AS "to",
            EXISTS(SELECT 1 FROM pg_attribute x WHERE x.attrelid=t.oid AND x.attname='id') AS has_id
            FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_class r ON r.oid=c.confrelid
            JOIN pg_namespace n ON n.oid=t.relnamespace
            CROSS JOIN LATERAL unnest(c.conkey,c.confkey) AS k(src,dst)
            JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=k.src
            JOIN pg_attribute b ON b.attrelid=r.oid AND b.attnum=k.dst
            WHERE c.contype='f' AND n.nspname=current_schema()''').fetchall()
    result=[]
    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        table=row[0]; quoted='"'+table.replace('"','""')+'"'
        result.extend(dict(fk,child=table,has_id=True) for fk in (dict(r) for r in conn.execute(f'PRAGMA foreign_key_list({quoted})')))
    return result


def check_foreign_keys(conn):
    if getattr(conn, 'backend', 'sqlite') == 'postgresql':
        conn.execute('SET CONSTRAINTS ALL IMMEDIATE')
        return False
    return conn.execute('PRAGMA foreign_key_check').fetchone() is not None
