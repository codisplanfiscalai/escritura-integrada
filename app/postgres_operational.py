"""Operational PostgreSQL: native versioned DDL and bound qmark parameters.

No SQLite SQL translation, fallback, DDL inference, or production auto-import.
All application writers share a transaction advisory lock, matching SQLite's
single-writer contract (number allocation, idempotency and session revalidation).
"""
from contextlib import contextmanager
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from .postgres_backend import PostgresDatabase, PostgresSettings, Migration, MigrationHistoryError

DATA = Path(__file__).parent / 'data' / 'postgres'
MODEL = json.loads((DATA / 'source.json').read_text())


def qmark(statement):
    """Lex placeholders only; quoted strings/identifiers/comments stay byte-for-byte.

    Use the driver's $n RawCursor binding so literal percent signs are untouched.
    Reject dollar quotes in application queries (native DDL uses the raw driver).
    """
    out=[]; i=0; count=0
    while i < len(statement):
        ch=statement[i]
        if ch in "'\"":
            quote=ch; start=i; i+=1
            while i < len(statement):
                if statement[i]==quote:
                    i+=1
                    if i < len(statement) and statement[i]==quote: i+=1; continue
                    break
                i+=1
            else: raise ValueError('Unterminated SQL literal')
            out.append(statement[start:i]); continue
        if statement.startswith('--',i):
            end=statement.find('\n',i); end=len(statement) if end<0 else end
            out.append(statement[i:end]); i=end; continue
        if statement.startswith('/*',i) or ch=='$' or ch=='\\':
            raise ValueError('Unsupported application SQL token; use native backend statement')
        if ch=='?': count+=1; out.append('$'+str(count))
        else: out.append(ch)
        i+=1
    return ''.join(out)


class Row(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key,int) else super().__getitem__(key)


def row_factory(cursor):
    names=[c.name for c in (cursor.description or ())]
    def build(values):
        # PostgreSQL SUM(bigint) is numeric; the domain uses integer cents.
        return Row(zip(names,(int(v) if isinstance(v,Decimal) and v==v.to_integral_value() else v for v in values)))
    return build


class Connection:
    backend='postgresql'
    def __init__(self, raw): self.raw=raw
    def execute(self, statement, parameters=()):
        try:
            return psycopg.RawCursor(self.raw,row_factory=row_factory).execute(qmark(statement),tuple(int(v) if isinstance(v,bool) else v for v in parameters))
        except psycopg.IntegrityError as exc:
            raise sqlite3.IntegrityError('PostgreSQL constraint violation') from exc
        except psycopg.OperationalError as exc:
            raise sqlite3.OperationalError('PostgreSQL unavailable') from exc

    def executemany(self, statement, rows):
        try:
            cursor=psycopg.RawCursor(self.raw,row_factory=row_factory)
            cursor.executemany(qmark(statement),(tuple(int(v) if isinstance(v,bool) else v for v in row) for row in rows))
            return cursor
        except psycopg.IntegrityError as exc:
            raise sqlite3.IntegrityError('PostgreSQL constraint violation') from exc
        except psycopg.OperationalError as exc:
            raise sqlite3.OperationalError('PostgreSQL unavailable') from exc


def migrations():
    # Single multi-statement native script is trusted versioned application code.
    return (Migration(1,'operational_schema',((DATA/'001.sql').read_text(), (DATA/'002_triggers.sql').read_text())),)


def reset_sequences(conn, reservations=None):
    reservations=reservations or {}
    for table, model in MODEL['tables'].items():
        column=model['identity']
        if not column: continue
        maximum=conn.execute(sql.SQL('SELECT COALESCE(MAX({}),0) AS n FROM {}').format(sql.Identifier(column),sql.Identifier(table))).fetchone()['n']
        maximum=max(maximum,int(reservations.get(table,0)))
        if maximum >= 9223372036854775807: raise ValueError('Identity exhausted')
        # ALTER SEQUENCE is transactional; setval is not and is deliberately avoided.
        sequence=conn.execute('SELECT pg_get_serial_sequence(%s,%s) AS name',(table,column)).fetchone()['name']
        parts=sequence.split('.')
        conn.execute(sql.SQL('ALTER SEQUENCE {} RESTART WITH {}').format(sql.Identifier(*(p.strip('"') for p in parts)),sql.Literal(maximum+1)))


def seed(conn):
    for table,rows in MODEL['seeds'].items():
        for row in rows:
            columns=list(row)
            conn.execute(sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,columns)),sql.SQL(',').join(sql.Placeholder() for _ in columns)),tuple(row.values()))
    reset_sequences(conn)


class OperationalDatabase(PostgresDatabase):
    def __init__(self, settings, data_dir, *, initialize=False):
        super().__init__(settings)
        self.data_dir=Path(data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True,exist_ok=True)
        self.upgrade_backup=None
        with super().transaction() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(1163084626,hashtext(current_schema()))')
            exists=conn.execute("SELECT to_regclass('_escritura_migrations') AS name").fetchone()['name']
            if not exists:
                objects=conn.execute('SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s LIMIT 1',(settings.schema,)).fetchone()
                if objects or not initialize:
                    raise MigrationHistoryError('Destino não inicializado ou incompatível. Use inicialização explícita em schema vazio.')
                conn.execute('''CREATE TABLE _escritura_migrations(version integer PRIMARY KEY,name text NOT NULL,checksum text NOT NULL,applied_at timestamptz NOT NULL DEFAULT now())''')
                for m in migrations():
                    for statement in m.statements: conn.execute(statement)
                    conn.execute('INSERT INTO _escritura_migrations(version,name,checksum) VALUES(%s,%s,%s)',(m.version,m.name,m.checksum))
                seed(conn)
            history=conn.execute('SELECT version,name,checksum FROM _escritura_migrations ORDER BY version').fetchall()
            available=migrations()
            if history != [dict(version=m.version,name=m.name,checksum=m.checksum) for m in available[:len(history)]]:
                raise MigrationHistoryError('Histórico operacional incompatível; atualização recusada.')
            for m in available[len(history):]:
                for statement in m.statements:conn.execute(statement)
                conn.execute('INSERT INTO _escritura_migrations(version,name,checksum) VALUES(%s,%s,%s)',(m.version,m.name,m.checksum))
            expected=set(MODEL['tables'])
            actual={r['table_name'] for r in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_type='BASE TABLE'")}
            if actual-{'_escritura_migrations','_escritura_import'} != expected:
                raise MigrationHistoryError('Tabelas operacionais divergentes; banco incompatível.')
            for table,model in MODEL['tables'].items():
                columns={r['column_name'] for r in conn.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s',(table,))}
                if columns!=set(model['columns']):raise MigrationHistoryError('Colunas operacionais incompatíveis.')


    @contextmanager
    def read(self,snapshot=False):
        with super().read(snapshot=snapshot) as raw:
            yield Connection(raw)

    @contextmanager
    def transaction(self):
        with super().transaction() as raw:
            raw.execute('SELECT pg_advisory_xact_lock(1163084626,hashtext(current_schema()))')
            conn=Connection(raw)
            from .db import validate_context
            validate_context(conn)
            yield conn


def settings_from_env():
    # Separate Compose fields avoid URI escaping of special password characters.
    dsn=os.environ.get('ESCRITURA_DATABASE_URL')
    if not dsn:
        password=os.environ.get('POSTGRES_PASSWORD','')
        if not password: raise ValueError('Configure POSTGRES_PASSWORD para PostgreSQL.')
        dsn=make_conninfo(host=os.environ.get('POSTGRES_HOST','postgres'),port=os.environ.get('POSTGRES_PORT','5432'),dbname=os.environ.get('POSTGRES_DB','escritura'),user=os.environ.get('POSTGRES_USER','escritura'),password=password)
    return PostgresSettings(dsn,schema=os.environ.get('ESCRITURA_DATABASE_SCHEMA','public'))
