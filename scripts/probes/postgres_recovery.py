"""Real PostgreSQL recovery rehearsal; creates/drops only UUID-named fixture databases.

Requires an explicitly supplied disposable server and its local Docker container.
No production connection settings, pg_restore --clean, or activation are accepted.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo, conninfo_to_dict

from app.db import Database
from app.business import BusinessCore
from app.integrations import Integrations
from app.postgres_operational import OperationalDatabase, PostgresSettings, MODEL
from app.postgres_transfer import migrate_sqlite, capture, restore_new, data_digest


def main():
    dsn=os.environ.get('ESCRITURA_POSTGRES_TEST_DSN')
    container=os.environ.get('ESCRITURA_POSTGRES_TEST_CONTAINER')
    if not dsn or not container:
        raise SystemExit('Required: disposable ESCRITURA_POSTGRES_TEST_DSN and ESCRITURA_POSTGRES_TEST_CONTAINER; no skip.')
    user=conninfo_to_dict(dsn)['user']
    source_name='recovery_source_'+uuid.uuid4().hex
    target_name='recovery_target_'+uuid.uuid4().hex
    created=[]
    def docker(*args,**kwargs):
        return subprocess.run(['docker','exec','-i',container,*args],check=True,timeout=300,**kwargs)
    try:
        with psycopg.connect(dsn,autocommit=True) as admin:
            for name in (source_name,target_name):
                admin.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
                created.append(name)
        source_dsn=make_conninfo(dsn,dbname=source_name)
        target_dsn=make_conninfo(dsn,dbname=target_name)
        with tempfile.TemporaryDirectory(prefix='escritura-native-recovery-') as work:
            folder=Path(work);os.environ['ESCRITURA_DATA_DIR']=str(folder)
            origin=Database(folder/'sqlite');BusinessCore(origin,True);Integrations(origin)
            settings=PostgresSettings(source_dsn)
            migrate_sqlite(settings,origin.path)
            db=OperationalDatabase(settings,folder/'pg')
            core=BusinessCore(db,False)
            with origin.read() as conn:before=conn.execute('SELECT COUNT(*) FROM journals').fetchone()[0]
            with db.read() as conn:
                cid=conn.execute('SELECT MIN(id) FROM companies').fetchone()[0]
                accounts=conn.execute('SELECT id FROM effective_accounts WHERE company_id=? AND analytical=1 ORDER BY id LIMIT 2',(cid,)).fetchall()
            journal=core.create_journal(cid,{'date':'2026-11-06','document':'RECOVERY-SYNTHETIC','history':'Post-cutover recovery fixture','idempotency_key':'post-cutover-fixture',
                'lines':[{'account_id':accounts[0]['id'],'debit':'123.45','credit':'0.00'},{'account_id':accounts[1]['id'],'debit':'0.00','credit':'123.45'}]},'synthetic')
            with origin.read() as conn:
                assert conn.execute('SELECT COUNT(*) FROM journals').fetchone()[0]==before
                assert conn.execute("SELECT COUNT(*) FROM journals WHERE idempotency_key='post-cutover-fixture'").fetchone()[0]==0
            # 513 MiB of genuine bytea content, intentionally compressible. This
            # tests logical capacity, not random-data compression or performance.
            with db.transaction() as conn:
                for n in range(513):
                    content=n.to_bytes(4,'big')+b'x'*(1024*1024-4)
                    conn.execute('INSERT INTO stored_files(company_id,year,category,filename,sha256,content,created_at,created_by) VALUES(?,?,?,?,?,?,?,?)',
                        (cid,2026,'originals',f'synthetic-{n}.bin',hashlib.sha256(content).hexdigest(),content,'2026-11-18T00:00:00Z','synthetic'))
            partial=folder/'bounded.zip'
            try:capture(db,partial)
            except ValueError as error:assert 'limite' in str(error)
            else:raise AssertionError('512 MiB logical limit was not enforced')
            try:restore_new(db,partial)
            except (ValueError,KeyError):pass
            else:raise AssertionError('Incomplete backup was accepted')
            archive=folder/'native.dump'
            with archive.open('xb') as output:
                archive.chmod(0o600)
                docker('pg_dump','--username',user,'--dbname',source_name,'--format=custom',stdout=output)
            # The target was created above; its existence is never adopted after
            # CREATE DATABASE failure. Do not use --create or --clean on restore.
            with archive.open('rb') as stream:
                docker('pg_restore','--username',user,'--dbname',target_name,'--single-transaction','--exit-on-error','--no-owner',stdin=stream)
            restored=OperationalDatabase(PostgresSettings(target_dsn),folder/'restored')
            with db.read(snapshot=True) as left,restored.read(snapshot=True) as right:
                for table in MODEL['tables']:
                    columns=','.join("encode(sha256(content),'hex') AS content_digest" if table=='stored_files' and name=='content' else '"'+name+'"' for name in MODEL['tables'][table]['columns'])
                    query='SELECT '+columns+' FROM "'+table+'"'
                    assert data_digest(tuple(r.values()) for r in left.execute(query))==data_digest(tuple(r.values()) for r in right.execute(query)),table
                seq='SELECT sequencename,last_value FROM pg_sequences WHERE schemaname=current_schema() ORDER BY sequencename'
                assert left.execute(seq).fetchall()==right.execute(seq).fetchall()
                assert right.execute("SELECT total_cents FROM journals WHERE idempotency_key='post-cutover-fixture'").fetchone()[0]==12345
                assert right.execute('SELECT SUM(octet_length(content)) FROM stored_files').fetchone()[0]>=513*1024*1024
                assert right.execute("SELECT COUNT(*) FROM stored_files WHERE encode(sha256(content),'hex')<>sha256").fetchone()[0]==0
                assert right.execute('SELECT COUNT(*) FROM _escritura_import').fetchone()[0]==1
                assert right.execute('SELECT COUNT(*) FROM companies').fetchone()[0]==2
            print(json.dumps({'status':'passed','synthetic_only':True,'post_cutover_journal_id':journal['id'],
                'sqlite_return_blocked':True,'native_restore_preserves_post_cutover':True,'blob_bytes':513*1024*1024,
                'logical_limit_refused':True,'tables_reconciled':len(MODEL['tables']),'archive_bytes':archive.stat().st_size,
                'activated':False}))
    finally:
        with psycopg.connect(dsn,autocommit=True) as admin:
            for name in reversed(created):admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


if __name__=='__main__':main()
