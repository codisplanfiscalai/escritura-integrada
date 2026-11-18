"""Explicit all-or-nothing migration and bounded native PostgreSQL backups.

Imports require an empty schema. Restores create an unpredictable NEW schema;
never overwrite an existing database/schema or activate restored data.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid
from zipfile import ZipFile, ZIP_DEFLATED

from psycopg import sql
from .postgres_backend import PostgresDatabase, PostgresSettings
from .postgres_operational import MODEL, migrations, reset_sequences
from .migration_checkpoint import copy_consistent, readonly, encode_cell, decode_cell, canonical

FORMAT='escritura-postgresql-operational-1'
MAX_BYTES=512*1024*1024


def native_schema(conn):
    conn.execute('SELECT pg_advisory_xact_lock(1163084626,hashtext(current_schema()))')
    if conn.execute('SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() LIMIT 1').fetchone():
        raise ValueError('Destino não vazio. Nenhum dado existente será substituído.')
    conn.execute('CREATE TABLE _escritura_migrations(version integer PRIMARY KEY,name text NOT NULL,checksum text NOT NULL,applied_at timestamptz NOT NULL DEFAULT now())')
    for m in migrations():
        for statement in m.statements: conn.execute(statement)
        conn.execute('INSERT INTO _escritura_migrations(version,name,checksum) VALUES(%s,%s,%s)',(m.version,m.name,m.checksum))


def columns_sql(table):
    return sql.SQL(',').join(map(sql.Identifier,MODEL['tables'][table]['columns']))


def insert_rows(conn,table,rows):
    columns=MODEL['tables'][table]['columns']
    statement=sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(sql.Identifier(table),columns_sql(table),sql.SQL(',').join(sql.Placeholder() for _ in columns))
    with conn.cursor() as cursor:
        cursor.executemany(statement,rows)


def data_digest(rows):
    """Order independent multiset digest, preserving types, duplicates and blobs."""
    total=0; count=0
    for row in rows:
        cells=[encode_cell(v) for v in row]
        total=(total+int.from_bytes(hashlib.sha256(canonical(cells)).digest(),'big')) % (1<<256)
        count+=1
    return {'count':count,'digest':f'{total:064x}'}


def pg_rows(conn,table):
    with conn.cursor(name='transfer_rows') as cursor:
        cursor.execute(sql.SQL('SELECT {} FROM {}').format(columns_sql(table),sql.Identifier(table)))
        for row in cursor: yield tuple(row.values())


def suppress_events(conn, enabled):
    # Only integration triggers owned by this application; never disable FK checks.
    for table in {o['tbl_name'] for o in MODEL['objects'] if o['type']=='trigger'}:
        conn.execute(sql.SQL('ALTER TABLE {} {} TRIGGER USER').format(sql.Identifier(table),sql.SQL('ENABLE' if enabled else 'DISABLE')))


def migrate_sqlite(settings, source):
    source=Path(source).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='.escritura-sqlite-import-',dir=os.environ.get('ESCRITURA_DATA_DIR',source.parent)) as work:
        snapshot=Path(work)/'escritura.sqlite3'
        copy_consistent(source,snapshot)
        # Upgrade ONLY a private copy; no checkpoint, schema write or vacuum on source.
        from .db import Database
        from .integrations import Integrations
        copy=Database(work); Integrations(copy)
        with closing(readonly(snapshot)) as src:
            if src.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or src.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('Origem inconsistente; importação recusada.')
            known={(o['type'],o['name']) for o in MODEL['objects']}
            objects={(r['type'],r['name']) for r in src.execute("SELECT type,name FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")}
            if objects-known:
                raise ValueError('Objetos SQLite adicionais exigem revisão explícita; não serão descartados.')
            actual={r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if actual != set(MODEL['tables']):raise ValueError('Tabelas SQLite incompatíveis; nenhuma tabela pode ser ignorada.')
            for table,model in MODEL['tables'].items():
                names={r['name'] for r in src.execute(f'PRAGMA table_info("{table}")')}
                if names != set(model['columns']):raise ValueError('Colunas SQLite incompatíveis: '+table)
            def rows(table):
                names=','.join('"'+n+'"' for n in MODEL['tables'][table]['columns'])
                for row in src.execute(f'SELECT {names} FROM "{table}"'):
                    values=list(row)
                    if table=='integration_events':
                        index=MODEL['tables'][table]['columns'].index('resource_id'); values[index]=str(values[index])
                    yield tuple(values)
            reserves={r['name']:r['seq'] for r in src.execute('SELECT name,seq FROM sqlite_sequence')}
            for kind in ('documents','journals'):
                reserves[kind]=max(reserves.get(kind,0),src.execute('SELECT COALESCE(MAX(record_id),0) FROM bulk_deleted_movements WHERE kind=?',(kind,)).fetchone()[0])
            expected={table:data_digest(rows(table)) for table in MODEL['tables']}
            db=PostgresDatabase(settings)
            with db.transaction() as conn:
                native_schema(conn); conn.execute('SET CONSTRAINTS ALL DEFERRED'); suppress_events(conn,False)
                for table in MODEL['tables']:insert_rows(conn,table,rows(table))
                for table in MODEL['tables']:
                    if data_digest(pg_rows(conn,table))!=expected[table]:raise ValueError('Divergência após cópia: '+table)
                reset_sequences(conn,reserves); conn.execute('SET CONSTRAINTS ALL IMMEDIATE'); suppress_events(conn,True)
                conn.execute('CREATE TABLE _escritura_import(source_sha256 text NOT NULL, imported_at timestamptz NOT NULL DEFAULT now())')
                with snapshot.open('rb') as file:
                    digest=hashlib.file_digest(file,'sha256').hexdigest()
                conn.execute('INSERT INTO _escritura_import(source_sha256) VALUES(%s)',(digest,))
    return {'status':'imported','tables':expected,'source_preserved':True,'activated':False}


def capture(database,output,cancelled=lambda:False):
    output=Path(output)
    written=0
    def bounded(data):
        nonlocal written
        written+=len(data)
        if written>MAX_BYTES or cancelled():raise ValueError('Backup excede limite ou foi cancelado.')
        return data
    # Lock all app writers before establishing the repeatable read snapshot. Lock
    # outside the read transaction avoids snapshots predating a waiting writer.
    with database._connect() as raw:
        raw.execute("SELECT set_config('statement_timeout',%s,false)",(str(database.settings.statement_timeout_ms),))
        raw.execute('SELECT pg_advisory_lock(1163084626,hashtext(%s))',(database.settings.schema,))
        try:
            with PostgresDatabase(database.settings).read(snapshot=True) as conn:
                tables={};sequences={}
                imported=[]
                if conn.execute("SELECT to_regclass('_escritura_import') AS name").fetchone()['name']:
                    imported=conn.execute('SELECT source_sha256,imported_at::text FROM _escritura_import').fetchall()
                with output.open('xb') as file:
                    output.chmod(0o600)
                    with ZipFile(file,'w',ZIP_DEFLATED) as archive:
                        for table,model in MODEL['tables'].items():
                            with archive.open(table+'.jsonl','w') as dst:
                                def rows():
                                    for row in pg_rows(conn,table):
                                        dst.write(bounded(canonical([encode_cell(v) for v in row])+b'\n'))
                                        yield row
                                tables[table]=data_digest(rows())
                            if model['identity']:
                                seq=conn.execute('SELECT pg_get_serial_sequence(%s,%s) AS name',(table,model['identity'])).fetchone()['name']
                                parts=[p.strip('"') for p in seq.split('.')]
                                r=conn.execute(sql.SQL('SELECT last_value,is_called FROM {}').format(sql.Identifier(*parts))).fetchone()
                                sequences[table]=int(r['last_value']) if r['is_called'] else int(r['last_value'])-1
                        manifest={'format':FORMAT,'tables':tables,'sequences':sequences,'migration_checksums':[m.checksum for m in migrations()],'sqlite_import':imported}
                        archive.writestr('manifest.json',bounded(canonical(manifest)))
                return manifest
        finally:
            raw.execute('SELECT pg_advisory_unlock(1163084626,hashtext(%s))',(database.settings.schema,))


def restore_new(database,archive_path, *, verify_only=False):
    schema='restore_'+uuid.uuid4().hex
    with ZipFile(archive_path) as archive:
        expected_names={t+'.jsonl' for t in MODEL['tables']}|{'manifest.json'}
        infos=archive.infolist()
        if {i.filename for i in infos}!=expected_names or len(infos)!=len(expected_names) or sum(i.file_size for i in infos)>MAX_BYTES:
            raise ValueError('Conteúdo/tamanho de backup inválido.')
        manifest=json.loads(archive.read('manifest.json'))
        if manifest.get('format')!=FORMAT or manifest.get('migration_checksums')!=[m.checksum for m in migrations()] or set(manifest.get('tables',{}))!=set(MODEL['tables']):
            raise ValueError('Backup/schema incompatível.')
        # CREATE SCHEMA and all contents commit atomically. Random destination is
        # never accepted from an HTTP payload; a collision fails without overwrite.
        with PostgresDatabase(database.settings).transaction() as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            conn.execute(sql.SQL('SET LOCAL search_path TO {}, pg_catalog').format(sql.Identifier(schema)))
            native_schema(conn);conn.execute('SET CONSTRAINTS ALL DEFERRED');suppress_events(conn,False)
            for table in MODEL['tables']:
                def rows():
                    with archive.open(table+'.jsonl') as stream:
                        for line in stream:
                            values=[decode_cell(v) for v in json.loads(line)]
                            if len(values)!=len(MODEL['tables'][table]['columns']):raise ValueError('Colunas divergentes')
                            yield values
                insert_rows(conn,table,rows())
                if data_digest(pg_rows(conn,table))!=manifest['tables'][table]:raise ValueError('Restauração divergente: '+table)
            reset_sequences(conn,manifest['sequences']);conn.execute('SET CONSTRAINTS ALL IMMEDIATE');suppress_events(conn,True)
            imported=manifest.get('sqlite_import',[])
            if imported:
                if len(imported)!=1 or not isinstance(imported[0].get('source_sha256'),str) or len(imported[0]['source_sha256'])!=64:
                    raise ValueError('Marcador de migração inválido.')
                conn.execute('CREATE TABLE _escritura_import(source_sha256 text NOT NULL,imported_at timestamptz NOT NULL DEFAULT now())')
                conn.execute('INSERT INTO _escritura_import VALUES(%s,%s)',(imported[0]['source_sha256'],imported[0]['imported_at']))
            # Authentication sessions are invalidated only after exact reconciliation.
            for table in ('session_contexts','sessions','login_attempts'):
                conn.execute(sql.SQL('DELETE FROM {}').format(sql.Identifier(table)))
            if verify_only:conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    return {'backend':'postgresql','schema':None if verify_only else schema,'status':'verified' if verify_only else 'restored','activated':False}


def main():
    import argparse
    from .postgres_operational import OperationalDatabase,settings_from_env
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('initialize','migrate-sqlite','backup','restore'))
    parser.add_argument('--source',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--acknowledge-stopped-sqlite',action='store_true')
    args=parser.parse_args();settings=settings_from_env();data=os.environ.get('ESCRITURA_DATA_DIR','/data')
    if args.action=='initialize':
        if (Path(data)/'escritura.sqlite3').exists():raise ValueError('SQLite existente: use migrate-sqlite explicitamente.')
        OperationalDatabase(settings,data,initialize=True);result={'status':'initialized'}
    elif args.action=='migrate-sqlite':
        if not args.acknowledge_stopped_sqlite or not args.source:raise ValueError('Pare os escritores SQLite e confirme --acknowledge-stopped-sqlite e --source.')
        result=migrate_sqlite(settings,args.source)
    else:
        db=OperationalDatabase(settings,data)
        if args.action=='backup':
            if not args.output:raise ValueError('--output obrigatório')
            result=capture(db,args.output)
        else:
            if not args.source:raise ValueError('--source obrigatório')
            result=restore_new(db,args.source)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
