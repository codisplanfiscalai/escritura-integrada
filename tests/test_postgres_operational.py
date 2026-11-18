"""Real-server regression; no driver/database mocks. CI requires the DSN."""
import os
from pathlib import Path
import tempfile
import unittest
import uuid

from tests.test_core import CoreApiTests as _CoreApiTests

DSN=os.environ.get('ESCRITURA_POSTGRES_TEST_DSN')


class PostgresFixture:
    def setUp(self):
        import psycopg
        from psycopg import sql
        from app.postgres_operational import OperationalDatabase,PostgresSettings
        self.schema='test_operational_'+uuid.uuid4().hex
        with psycopg.connect(DSN,autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        self.pg_env={k:os.environ.get(k) for k in ('ESCRITURA_DATABASE_BACKEND','ESCRITURA_DATABASE_URL','ESCRITURA_DATABASE_SCHEMA')}
        self.addCleanup(self.restore_env)
        os.environ.update(ESCRITURA_DATABASE_BACKEND='postgresql',ESCRITURA_DATABASE_URL=DSN,ESCRITURA_DATABASE_SCHEMA=self.schema)
        with tempfile.TemporaryDirectory() as data:
            OperationalDatabase(PostgresSettings(DSN,schema=self.schema),data,initialize=True)
        super().setUp()

    def restore_env(self):
        for k,v in self.pg_env.items():
            if v is None:os.environ.pop(k,None)
            else:os.environ[k]=v

    def drop_schema(self):
        import psycopg
        from psycopg import sql
        with psycopg.connect(DSN,autocommit=True) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))


@unittest.skipUnless(DSN,'Requires disposable PostgreSQL 17')
class PostgresCoreTests(PostgresFixture,_CoreApiTests):
    def test_transaction_rechecks_session_after_context_change(self):
        from app.db import request_context,ContextConflict
        from app.core import digest
        token=self.client.cookies['escritura_session']
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE sessions SET active_company_id=? WHERE token_hash=?',(self.b['id'],digest(token.encode())))
        guard=request_context.set({'token_hash':digest(token.encode()),'company_id':self.a['id'],'period':'2026-11'})
        try:
            with self.assertRaises(ContextConflict):self.core.create_journal(self.a['id'],self.journal(),'teste')
        finally:request_context.reset(guard)
        self.assertEqual([],self.core.journals(self.a['id'],'2026-11'))

    def test_default_is_empty_and_explicit_demo_is_fictional(self):
        # PG identity is the configured database/schema, never the filesystem directory.
        from app.api import create_app
        with tempfile.TemporaryDirectory() as folder:
            restart=create_app(folder)
            self.assertEqual(2,len(restart.state.core.companies()))
            self.assertFalse((Path(folder)/'escritura.sqlite3').exists())

    def test_restart_backup_and_restore(self):
        from app.api import create_app
        from app.postgres_transfer import capture,restore_new
        self.assertEqual(201,self.client.post(self.scope('/journals'),json=self.journal()).status_code)
        restart=create_app(self.tmp.name)
        self.assertEqual('postgresql',restart.state.db.backend)
        self.assertEqual(2,len(restart.state.core.companies()))
        path=Path(self.tmp.name)/'backup.zip'
        manifest=capture(self.core.db,path)
        self.assertEqual(1,manifest['tables']['journals']['count'])
        self.assertEqual('verified',restore_new(self.core.db,path,verify_only=True)['status'])
        with self.core.db.read() as conn:
            self.assertEqual(1,conn.execute('SELECT COUNT(*) FROM journals').fetchone()[0])

    def test_sqlite_wal_migration_rejects_nonempty_and_preserves_source(self):
        import psycopg
        from psycopg import sql
        from app.db import Database
        from app.business import BusinessCore
        from app.integrations import Integrations
        from app.postgres_operational import OperationalDatabase,PostgresSettings
        from app.postgres_transfer import migrate_sqlite,capture,restore_new
        schema='test_import_'+uuid.uuid4().hex
        with psycopg.connect(DSN,autocommit=True) as conn:conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        settings=PostgresSettings(DSN,schema=schema)
        try:
            with tempfile.TemporaryDirectory() as data:
                source=Database(data);BusinessCore(source,True);Integrations(source)
                with source.transaction() as conn:
                    cid=conn.execute('SELECT MIN(id) FROM companies').fetchone()[0]
                    conn.execute("INSERT INTO bulk_deleted_movements VALUES('documents',900000,?,'deleted-key','2026-11-18')",(cid,))
                    conn.execute("DELETE FROM sqlite_sequence WHERE name='integration_events'")
                    conn.execute("INSERT INTO sqlite_sequence(name,seq) VALUES('integration_events',800000)")
                with source.read() as held:
                    held.execute("INSERT INTO meta VALUES('wal-fixture','committed in WAL')")
                    before=list(held.execute('SELECT * FROM meta ORDER BY key'))
                    result=migrate_sqlite(settings,source.path)
                    self.assertTrue(result['source_preserved'])
                    self.assertEqual([tuple(r) for r in before],[tuple(r) for r in held.execute('SELECT * FROM meta ORDER BY key')])
                with self.assertRaises(ValueError):migrate_sqlite(settings,source.path)
                target=OperationalDatabase(settings,data)
                with target.transaction() as conn:
                    self.assertEqual('committed in WAL',conn.execute("SELECT value FROM meta WHERE key='wal-fixture'").fetchone()[0])
                    self.assertEqual(2,conn.execute('SELECT COUNT(*) FROM companies').fetchone()[0])
                    self.assertGreater(conn.execute("SELECT nextval(pg_get_serial_sequence('documents','id'))").fetchone()[0],900000)
                    self.assertGreater(conn.execute("SELECT nextval(pg_get_serial_sequence('integration_events','seq'))").fetchone()[0],800000)
                backup=Path(data)/"migrated.zip"
                manifest=capture(target,backup)
                self.assertEqual(1,len(manifest["sqlite_import"]))
                self.assertEqual("verified",restore_new(target,backup,verify_only=True)["status"])
        finally:
            with psycopg.connect(DSN,autocommit=True) as conn:conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))

    def test_bulk_delete_tombstone_and_rollback(self):
        from app.bulk_operations import BulkOperations
        service=BulkOperations(self.core)
        doc=self.core.create_document(self.a['id'],self.document(),'teste')
        uid=self.client.get('/api/session').json()['user']['id']
        preview=service.preview(self.a['id'],{'kind':'documents','action':'delete','period':'2026-11','ids':[doc['id']]},uid,'teste')
        self.assertTrue(preview['can_confirm'],preview)
        result=service.confirm(self.a['id'],{'preview_id':preview['id'],'preview_hash':preview['preview_hash'],'reason':'Teste sintético','confirmation_phrase':preview['confirmation_phrase'],'irreversible_acknowledged':True},uid,'teste')
        self.assertTrue(result['completed'])
        with self.core.db.read() as conn:
            self.assertIsNotNone(conn.execute("SELECT 1 FROM bulk_deleted_movements WHERE kind='documents' AND record_id=?",(doc['id'],)).fetchone())
        with self.assertRaises(RuntimeError):
            with self.core.db.transaction() as conn:
                conn.execute("INSERT INTO meta VALUES('rollback-test','discard')")
                raise RuntimeError('synthetic partial operation')
        with self.core.db.read() as conn:
            self.assertIsNone(conn.execute("SELECT 1 FROM meta WHERE key='rollback-test'").fetchone())

    def test_failed_restore_leaves_no_schema_and_original_unchanged(self):
        import json
        from zipfile import ZipFile,ZIP_DEFLATED
        from app.postgres_transfer import capture,restore_new
        path=Path(self.tmp.name)/'good.zip';bad=Path(self.tmp.name)/'bad.zip'
        capture(self.core.db,path)
        with ZipFile(path) as src,ZipFile(bad,'w',ZIP_DEFLATED) as dst:
            for name in src.namelist():
                data=src.read(name)
                if name=='manifest.json':
                    manifest=json.loads(data);manifest['tables']['users']['digest']='0'*64
                    data=json.dumps(manifest).encode()
                dst.writestr(name,data)
        def schemas():
            with self.core.db.read() as conn:
                return {r[0] for r in conn.execute("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'restore_%'")}
        before=schemas()
        with self.assertRaisesRegex(ValueError,'divergente'):restore_new(self.core.db,bad)
        self.assertEqual(before,schemas())
        self.assertEqual(2,len(self.core.companies()))

    def test_partial_migration_error_rolls_back_schema(self):
        import psycopg
        from psycopg import sql
        from app.db import Database
        from app.integrations import Integrations
        from app.postgres_operational import PostgresSettings
        from app.postgres_transfer import migrate_sqlite
        schema='test_failed_import_'+uuid.uuid4().hex
        with psycopg.connect(DSN,autocommit=True) as conn:conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            with tempfile.TemporaryDirectory() as data:
                source=Database(data);Integrations(source)
                # SQLite permits a text value in this integer column. PostgreSQL
                # rejects it after earlier tables have already been copied.
                with source.transaction() as conn:
                    conn.execute("UPDATE global_fiscal_catalogs SET active='invalid-integer' WHERE id=1")
                with self.assertRaises(psycopg.Error):
                    migrate_sqlite(PostgresSettings(DSN,schema=schema),source.path)
                with psycopg.connect(DSN) as conn:
                    self.assertEqual(0,conn.execute('SELECT count(*) FROM information_schema.tables WHERE table_schema=%s',(schema,)).fetchone()[0])
                with source.read() as conn:
                    self.assertEqual('invalid-integer',conn.execute('SELECT active FROM global_fiscal_catalogs WHERE id=1').fetchone()[0])
        finally:
            with psycopg.connect(DSN,autocommit=True) as conn:conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))

    def test_encrypted_backend_capture_verify_restore_new_schema(self):
        import psycopg
        from psycopg import sql
        from app.backup_backends import select_backend
        from app.backup_crypto import Secret
        adapter=select_backend(self.core.db)
        work=Path(self.tmp.name);archive=work/'backup.eibk'
        secret=Secret('raw',os.urandom(32))
        checksum=adapter.capture(archive,'synthetic-key',secret,lambda:False,work)
        records=[];adapter.verify(archive,checksum,secret,lambda:False,work,records.append)
        self.assertEqual('verified',records[0]['status'])
        result=adapter.restore(archive,work/'restore-receipt',checksum,lambda _:secret,work)
        self.assertFalse(result['activated']);self.assertTrue(result['schema'].startswith('restore_'))
        try:
            from dataclasses import replace
            from app.postgres_operational import OperationalDatabase
            restored=OperationalDatabase(replace(self.core.db.settings,schema=result['schema']),work/'restored')
            with restored.read() as conn:
                self.assertEqual(2,conn.execute('SELECT COUNT(*) FROM companies').fetchone()[0])
                self.assertEqual(0,conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0])
        finally:
            with psycopg.connect(DSN,autocommit=True) as conn:conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(result['schema'])))
        self.assertEqual(2,len(self.core.companies()))

    def test_account_search_unicode_literals_pagination_and_company_scope(self):
        with self.core.db.transaction() as conn:
            account=conn.execute('SELECT id FROM accounts WHERE company_id=? ORDER BY id LIMIT 1',(self.a['id'],)).fetchone()[0]
            conn.execute('UPDATE accounts SET name=? WHERE id=?',('Árvore 100%_ Straẞe',account))
        for query in ('arvore','100%_','strasse'):
            result=self.core.accounts(self.a['id'],page=1,per_page=1,search=query)
            self.assertEqual(1,result['total']);self.assertEqual(account,result['items'][0]['id'])
            self.assertEqual([],self.core.accounts(self.a['id'],page=2,per_page=1,search=query)['items'])
            self.assertEqual(0,self.core.accounts(self.b['id'],page=1,search=query)['total'])

    def test_parameter_lexer_keeps_literals_and_percent(self):
        with self.core.db.read() as conn:
            self.assertEqual("? % O'Reilly",conn.execute("SELECT '? % O''Reilly' AS value WHERE ?=?",(1,1)).fetchone()[0])



from tests import test_bank_movement_report as _bank
from tests import test_trial_balance_report as _trial
from tests import test_fiscal_sales_accounting as _sales
from tests import test_global_account_plans as _plans
from tests import test_integration_domains as _integrations
from tests import test_reception_vault as _vault

@unittest.skipUnless(DSN,'Requires disposable PostgreSQL 17')
class PostgresBankTests(PostgresFixture,_bank.BankReportTests): pass

@unittest.skipUnless(DSN,'Requires disposable PostgreSQL 17')
class PostgresTrialTests(PostgresFixture,_trial.TrialBalanceTests): pass

@unittest.skipUnless(DSN,'Requires disposable PostgreSQL 17')
class PostgresSalesTests(PostgresFixture,_sales.FiscalSalesAccountingTests):
    def snapshot(self):
        from app.postgres_transfer import data_digest,pg_rows
        from app.postgres_operational import MODEL
        from app.postgres_backend import PostgresDatabase
        with PostgresDatabase(self.core.db.settings).read(snapshot=True) as conn:
            return {table:data_digest(pg_rows(conn,table)) for table in MODEL['tables']}

@unittest.skipUnless(DSN,'Requires disposable PostgreSQL 17')
class PostgresPlanTests(PostgresFixture,_plans.GlobalAccountPlanTests): pass

@unittest.skipUnless(DSN,'Requires disposable PostgreSQL 17')
class PostgresIntegrationTests(PostgresFixture,_integrations.DomainIntegrationTests):
    def test_webhook_listing_uses_portable_order(self):
        self.credential=self.issue(['documents:webhooks'])
        hook=self.hook('documents')
        response=self.client.get(self.internal('webhooks'))
        self.assertEqual(200,response.status_code,response.text)
        self.assertEqual([hook['id']],[r['id'] for r in response.json()])

@unittest.skipUnless(DSN,'Requires disposable PostgreSQL 17')
class PostgresVaultTests(PostgresFixture,_vault.VaultTests): pass

# Avoid discovery of the imported SQLite superclass under a second name.
del _CoreApiTests

if __name__=='__main__':unittest.main()
