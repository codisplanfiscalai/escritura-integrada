"""Cross-engine fixture proved on SQLite; PostgreSQL proof joins the existing gate."""
import itertools
import sqlite3
import unittest
from nfce_identity_fixture import COLUMNS,TABLE_COLUMNS,fixture,index_ddl,parameters,queries,raw_digest,unchanged_guard_ids


class NfceIdentityContractTests(unittest.TestCase):
    def test_actual_candidate_query_keeps_all_guard_identities_and_original_values(self):
        source=fixture();conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
        try:
            conn.execute('CREATE TABLE documents('+TABLE_COLUMNS+')')
            conn.executemany('INSERT INTO documents('+','.join(COLUMNS)+') VALUES('+','.join('?' for _ in COLUMNS)+')',[tuple(row[name] for name in COLUMNS) for row in source['rows']])
            before=raw_digest(conn.execute('SELECT * FROM documents ORDER BY id').fetchall())
            conn.execute(index_ddl());old,new=queries()
            for case in source['cases']:
                with self.subTest(case=case['name']):
                    previous=conn.execute(old,parameters(case)).fetchall();current=conn.execute(new,parameters(case,True)).fetchall()
                    self.assertEqual(case['expected_guard_ids'],unchanged_guard_ids(previous,case))
                    self.assertEqual(case['expected_guard_ids'],unchanged_guard_ids(current,case))
                    self.assertLessEqual(len(current),len(previous))
            self.assertEqual(before,raw_digest(conn.execute('SELECT * FROM documents ORDER BY id').fetchall()))
            self.assertEqual('ok',conn.execute('PRAGMA quick_check').fetchone()[0])
        finally:conn.close()

    def test_canonical_identity_implies_same_sql_candidate_key_for_small_alphabet(self):
        conn=sqlite3.connect(':memory:');groups={}
        try:
            strings=[''.join(chars) for length in range(1,5) for chars in itertools.product('01A٠',repeat=length)]
            strings+=['0'*300+'9','0009']
            for value in strings:
                canonical=str(int(value)) if value.isascii() and value.isdigit() else value
                key=conn.execute("SELECT ltrim(?,'0')",(value,)).fetchone()[0]
                self.assertEqual(groups.setdefault(canonical,key),key)
        finally:conn.close()

    def test_native_query_escapes_like_percent_and_uses_driver_parameters(self):
        old,new=queries(table='probe_documents',postgres=True)
        self.assertEqual(4,old.count('%s'));self.assertEqual(5,new.count('%s'))
        self.assertIn("LIKE '%%",new);self.assertNotIn('?',new)
