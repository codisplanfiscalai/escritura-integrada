"""Startup remains recoverable until all global migrations have succeeded."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.db import Database


class GlobalMigrationSequenceTests(unittest.TestCase):
    def test_schema_six_is_not_marked_before_shared_modules_finish(self):
        with tempfile.TemporaryDirectory(prefix='global-migration-sequence-') as directory:
            def interrupted(conn):
                self.assertFalse(conn.in_transaction)
                self.assertEqual('5', conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertTrue({'third_parties', 'third_party_history', 'global_fiscal_catalogs', 'fiscal_patterns'} <= tables)
                self.assertEqual(619, conn.execute('SELECT COUNT(*) FROM global_fiscal_catalogs').fetchone()[0])
                raise RuntimeError('Synthetic interrupted account migration')

            with patch('app.migration_global_accounts.migrate_global_accounts', side_effect=interrupted):
                with self.assertRaisesRegex(RuntimeError, 'Synthetic interrupted'):
                    Database(directory)
            path = Path(directory) / 'escritura.sqlite3'
            with closing(sqlite3.connect(path)) as conn:
                self.assertEqual('5', conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])

            resumed = Database(directory)
            self.assertTrue(resumed.upgrade_backup)
            self.assertTrue(Path(resumed.upgrade_backup).exists())
            with resumed.read() as conn:
                self.assertEqual('6', conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
                self.assertEqual([], conn.execute('PRAGMA foreign_key_check').fetchall())
                self.assertEqual(619, conn.execute('SELECT COUNT(*) FROM global_fiscal_catalogs').fetchone()[0])
