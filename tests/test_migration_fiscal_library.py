"""Atomic migration, including DDL, seed and source versions in autocommit SQLite."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from app.migration_fiscal_library import migrate


class InjectedFailureConnection:
    def __init__(self, conn, target, after=1):
        self.conn=conn; self.target=target; self.after=after; self.hits=0

    def __getattr__(self,name): return getattr(self.conn,name)

    def execute(self,sql,params=()):
        if self.target in sql:
            self.hits+=1
            if self.hits==self.after: raise sqlite3.OperationalError('injected migration failure')
        return self.conn.execute(sql,params)


class FiscalLibraryMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.sqlite3'

    def tearDown(self): self.tmp.cleanup()

    def connect(self):
        conn=sqlite3.connect(self.path,isolation_level=None);conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON');conn.execute('PRAGMA journal_mode=WAL');conn.execute('PRAGMA synchronous=FULL')
        return conn

    def test_single_transaction_covers_ddl_sources_catalogs_versions_and_ends_closed(self):
        with closing(self.connect()) as conn:
            traced=[];conn.set_trace_callback(traced.append);migrate(conn)
            self.assertFalse(conn.in_transaction)
            self.assertEqual(1,sum(s=='BEGIN IMMEDIATE' for s in traced));self.assertEqual(1,sum(s=='COMMIT' for s in traced))
            self.assertEqual(619,conn.execute('SELECT COUNT(*) FROM global_fiscal_catalogs').fetchone()[0])
            self.assertEqual(619,conn.execute('SELECT COUNT(*) FROM fiscal_library_versions').fetchone()[0])
            self.assertEqual(1,conn.execute('SELECT COUNT(*) FROM global_fiscal_sources').fetchone()[0])
            conn.execute('BEGIN IMMEDIATE');conn.rollback()  # Next migration owns its own transaction.

    def test_mid_seed_failure_rolls_back_ddl_and_records_and_allows_retry(self):
        with closing(self.connect()) as conn:
            with self.assertRaisesRegex(sqlite3.OperationalError,'injected'):
                migrate(InjectedFailureConnection(conn,'INSERT OR IGNORE INTO global_fiscal_catalogs',after=13))
            self.assertFalse(conn.in_transaction)
            self.assertEqual([],conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%fiscal%'").fetchall())
            migrate(conn)
            self.assertEqual(619,conn.execute('SELECT COUNT(*) FROM global_fiscal_catalogs').fetchone()[0])
            self.assertFalse(conn.in_transaction)

    def test_failure_on_existing_database_preserves_edits_and_rolls_back_partial_version_seed(self):
        with closing(self.connect()) as conn:
            migrate(conn)
            conn.execute("UPDATE global_fiscal_catalogs SET active=0,version=2 WHERE code='1102'")
            before=[dict(r) for r in conn.execute('SELECT * FROM global_fiscal_catalogs ORDER BY id')]
            with self.assertRaisesRegex(sqlite3.OperationalError,'injected'):
                migrate(InjectedFailureConnection(conn,'INSERT OR IGNORE INTO fiscal_library_versions',after=16))
            self.assertFalse(conn.in_transaction)
            self.assertEqual(before,[dict(r) for r in conn.execute('SELECT * FROM global_fiscal_catalogs ORDER BY id')])
            self.assertEqual(619,conn.execute('SELECT COUNT(*) FROM fiscal_library_versions').fetchone()[0])

    def test_reopen_is_idempotent_and_does_not_overwrite_existing_reference_edits(self):
        with closing(self.connect()) as conn:
            migrate(conn);conn.execute("UPDATE global_fiscal_catalogs SET active=0 WHERE code='1102'")
            before=[dict(r) for r in conn.execute('SELECT * FROM global_fiscal_catalogs ORDER BY id')]
            versions=[dict(r) for r in conn.execute('SELECT * FROM fiscal_library_versions ORDER BY entity_id,version')]
        with closing(self.connect()) as reopened:
            migrate(reopened);migrate(reopened)
            self.assertFalse(reopened.in_transaction)
            self.assertEqual(before,[dict(r) for r in reopened.execute('SELECT * FROM global_fiscal_catalogs ORDER BY id')])
            self.assertEqual(versions,[dict(r) for r in reopened.execute('SELECT * FROM fiscal_library_versions ORDER BY entity_id,version')])

    def test_active_caller_transaction_is_not_committed_or_rolled_back(self):
        with closing(self.connect()) as conn:
            conn.execute('CREATE TABLE caller_work (value TEXT)');conn.execute('BEGIN IMMEDIATE')
            conn.execute("INSERT INTO caller_work VALUES('pending')")
            with self.assertRaisesRegex(RuntimeError,'transação aberta'): migrate(conn)
            self.assertTrue(conn.in_transaction);self.assertEqual(1,conn.execute('SELECT COUNT(*) FROM caller_work').fetchone()[0])
            conn.rollback();self.assertEqual(0,conn.execute('SELECT COUNT(*) FROM caller_work').fetchone()[0])
