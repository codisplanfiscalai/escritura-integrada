"""Upgrade the actual schema 2 emitted by commit 51537872, not current DDL.

The checked-in SQL fixture was produced with that commit's archived SCHEMA and
migrate() on an empty database. Source hashes and provenance are in its header.
"""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.db import Database
from app.maintenance import SCHEMA_VERSION

FIXTURE=Path(__file__).parent/'fixtures/schema-v2-51537872.sql'


class LegacySchemaTwoUpgradeTests(unittest.TestCase):
    def seed(self,directory):
        path=Path(directory)/'escritura.sqlite3'
        with closing(sqlite3.connect(path,isolation_level=None)) as conn:
            conn.row_factory=sqlite3.Row;conn.executescript(FIXTURE.read_text())
            self.assertEqual('2',conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
            self.assertNotIn('shared_entry_id',{r['name'] for r in conn.execute('PRAGMA table_info(accounts)')})
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute("ALTER TABLE accounts ADD COLUMN legacy_extension TEXT NOT NULL DEFAULT 'retained-515'")
            for cid in (1,2):
                conn.execute('INSERT INTO companies(id,code,name,tax_id,regime,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(cid,str(cid),'Synthetic legacy company',f'SYNTHETIC-{cid}','outros','date','date'))
            for aid,cid,code,classifier,nature in [(41,1,'10041','1.1.01','debit'),(42,1,'10042','2.1.01','credit'),(43,2,'10043','1.1.01','debit')]:
                conn.execute('''INSERT INTO accounts(id,company_id,access_code,classifier,name,nature,analytical,requires_cost_center,report_group,prosoft_code)
                    VALUES(?,?,?,?,?,?,1,0,?,?)''',(aid,cid,code,classifier,'Synthetic '+code,nature,'asset' if nature=='debit' else 'liability',code))
            conn.execute("INSERT INTO cost_centers(id,company_id,code,name) VALUES(71,1,'C1','Synthetic center')")
            conn.execute('''INSERT INTO journals(id,company_id,number,date,period,document,history,total_cents,idempotency_key,request_hash,created_at,created_by)
                VALUES(51,1,1,'2026-11-01','2026-11','LEGACY','Synthetic legacy journal',1700,'legacy-key','legacy-hash','date','synthetic')''')
            conn.execute('INSERT INTO journal_lines(id,company_id,journal_id,position,account_id,debit_cents,credit_cents,cost_center_id) VALUES(61,1,51,1,41,1700,0,71)')
            conn.execute('INSERT INTO journal_lines(id,company_id,journal_id,position,account_id,debit_cents,credit_cents,cost_center_id) VALUES(62,1,51,2,42,0,1700,71)')
            conn.execute('CREATE INDEX legacy_account_name_idx ON accounts(name,legacy_extension)')
            conn.execute("CREATE TRIGGER legacy_account_name_trigger AFTER UPDATE OF name ON accounts BEGIN INSERT OR REPLACE INTO meta(key,value) VALUES('legacy-trigger-515',NEW.name); END")
            self.assertEqual([],list(conn.execute('PRAGMA foreign_key_check')))
            before=[dict(r) for r in conn.execute('SELECT * FROM accounts ORDER BY id')]
        return path,before

    def assert_preserved(self,path,before):
        with closing(sqlite3.connect(path)) as conn:
            conn.row_factory=sqlite3.Row
            after=[dict(r) for r in conn.execute('SELECT * FROM accounts ORDER BY id')]
            self.assertEqual(before,[{key:row[key] for key in old} for old,row in zip(before,after)])
            self.assertEqual(3,len(after))
            self.assertEqual([(61,41,71,1700,0),(62,42,71,0,1700)],[tuple(r) for r in conn.execute('SELECT id,account_id,cost_center_id,debit_cents,credit_cents FROM journal_lines ORDER BY id')])
            self.assertEqual([],list(conn.execute('PRAGMA foreign_key_check')))
            self.assertEqual('ok',conn.execute('PRAGMA integrity_check').fetchone()[0])
            for name in ('legacy_account_name_idx','legacy_account_name_trigger'):
                self.assertIsNotNone(conn.execute('SELECT 1 FROM sqlite_master WHERE name=?',(name,)).fetchone())

    def test_full_database_upgrade_preserves_real_schema2_columns_ids_fks_and_objects(self):
        with tempfile.TemporaryDirectory(prefix='real-schema2-upgrade-') as directory:
            path,before=self.seed(directory)
            upgraded=Database(directory);self.assertTrue(upgraded.upgrade_backup)
            with closing(sqlite3.connect(upgraded.upgrade_backup)) as backup:
                self.assertEqual('2',backup.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
                self.assertEqual(3,backup.execute('SELECT COUNT(*) FROM accounts').fetchone()[0])
            self.assert_preserved(path,before)
            resumed=Database(directory);self.assertIsNone(resumed.upgrade_backup)
            self.assert_preserved(path,before)
            with resumed.transaction() as conn:
                self.assertEqual(str(SCHEMA_VERSION),conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
                self.assertIn('shared_entry_id',{r['name'] for r in conn.execute('PRAGMA table_info(accounts)')})
                conn.execute("UPDATE accounts SET name='Trigger survives upgrade' WHERE id=41")
                self.assertEqual('Trigger survives upgrade',conn.execute("SELECT value FROM meta WHERE key='legacy-trigger-515'").fetchone()[0])
                # Classification is now a grouping, while access and ownership
                # constraints must remain intact.
                conn.execute("INSERT INTO accounts(company_id,access_code,classifier,name,nature,analytical,requires_cost_center) VALUES(1,'10044','1.1.01','Distinct subaccount','debit',1,0)")
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute("INSERT INTO accounts(company_id,access_code,classifier,name,nature,analytical,requires_cost_center) VALUES(1,'10041','9','Duplicate access','debit',1,0)")
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute('INSERT INTO journal_lines(company_id,journal_id,position,account_id,debit_cents,credit_cents) VALUES(1,51,3,43,1,0)')

    def test_failure_after_rebuild_rolls_back_accounts_and_full_database_retry_succeeds(self):
        with tempfile.TemporaryDirectory(prefix='real-schema2-rollback-') as directory:
            path,before=self.seed(directory)
            original_connect=Database.connect
            def interrupted(instance):
                conn=original_connect(instance)
                def authorizer(action,name,*unused):
                    if action==sqlite3.SQLITE_CREATE_TABLE and name=='global_account_plans':return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK
                conn.set_authorizer(authorizer)
                return conn
            with patch.object(Database,'connect',interrupted):
                with self.assertRaises(sqlite3.DatabaseError):Database(directory)
            self.assert_preserved(path,before)
            with closing(sqlite3.connect(path)) as conn:
                self.assertEqual('5',conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
                self.assertNotIn('shared_entry_id',{r[1] for r in conn.execute('PRAGMA table_info(accounts)')})
                self.assertIsNone(conn.execute("SELECT 1 FROM sqlite_master WHERE name='accounts_global_migration'").fetchone())
            resumed=Database(directory);self.assertTrue(resumed.upgrade_backup)
            self.assert_preserved(path,before)
            with resumed.read() as conn:
                self.assertEqual(str(SCHEMA_VERSION),conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
                self.assertEqual([],list(conn.execute('PRAGMA foreign_key_check')))


if __name__=='__main__':unittest.main()
