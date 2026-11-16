"""Ensaio integral de staging com dados fictícios e PostgreSQL real descartável."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
import threading
import unittest
from unittest.mock import patch
import uuid

from test_migration_checkpoint import CheckpointFixture
from app.migration_checkpoint import decode_cell, inventory, restore_checkpoint, verify_checkpoint

HAS_DRIVER = importlib.util.find_spec("psycopg") is not None
TEST_DSN = os.environ.get("ESCRITURA_POSTGRES_TEST_DSN", "")
if HAS_DRIVER:
    import psycopg
    from psycopg import sql
    from app.postgres_backend import PostgresDatabase, PostgresSettings
    from app.postgres_migration_stage import StageConflict, stage_checkpoint, verify_stage


@unittest.skipUnless(HAS_DRIVER and TEST_DSN, "Requer driver e ESCRITURA_POSTGRES_TEST_DSN descartável.")
class PostgresMigrationStageTests(CheckpointFixture):
    def setUp(self):
        super().setUp()
        self.schema = "migration_test_" + uuid.uuid4().hex
        with psycopg.connect(TEST_DSN, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        self.database = PostgresDatabase(PostgresSettings(TEST_DSN, schema=self.schema))
        self.manifest = self.create()

    def drop_schema(self):
        with psycopg.connect(TEST_DSN, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def tables(self):
        with self.database.read() as conn:
            return {row["tablename"] for row in conn.execute(
                "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname=%s", (self.schema,))}

    def test_full_source_roundtrip_is_verified_with_original_bytes_ids_and_company_totals(self):
        before = inventory(self.source)
        result = stage_checkpoint(self.database, self.checkpoint)
        self.assertEqual("verified_staging_only", result["status"])
        self.assertFalse(result["cutover_performed"])
        self.assertEqual(result["snapshot_sha256"], verify_stage(self.database, self.checkpoint)["snapshot_sha256"])
        with self.database.read() as conn:
            rows = conn.execute("SELECT company_key,payload FROM migration_rows WHERE table_name='migration_probe' ORDER BY ordinal").fetchall()
            self.assertEqual(["1", "2"], [row["company_key"] for row in rows])
            first = [decode_cell(cell) for cell in rows[0]["payload"]["cells"]]
            self.assertEqual([31, 1, 99_999_999_999_999, self.original, "ação\x00fim", 0.1], first)
            self.assertEqual(31, rows[0]["payload"]["source_rowid"])
            total = conn.execute("SELECT count(*) AS n FROM migration_rows").fetchone()["n"]
            self.assertEqual(sum(t["summary"]["count"] for t in before["tables"]), total)
            stored = conn.execute("SELECT manifest FROM migration_checkpoint").fetchone()["manifest"]
            self.assertEqual("201", stored["inventory"]["id_reservations"]["migration_probe"]["next_minimum"])
            self.assertEqual("901", stored["inventory"]["id_reservations"]["documents"]["next_minimum"])
        self.assertEqual(before, inventory(self.source))
        restore_checkpoint(self.checkpoint, self.root / "rollback_copy")
        self.assertEqual(before, inventory(self.root / "rollback_copy/escritura.sqlite3"))

    def test_repeated_stage_is_idempotent_and_revalidates_all_data(self):
        self.assertFalse(stage_checkpoint(self.database, self.checkpoint)["duplicate"])
        self.assertTrue(stage_checkpoint(self.database, self.checkpoint)["duplicate"])
        with self.database.transaction() as conn:
            conn.execute("""UPDATE migration_rows SET payload=jsonb_set(payload,'{cells,2,1}','\"0\"')
                WHERE table_name='migration_probe' AND ordinal=1""")
        with self.assertRaises(StageConflict):
            stage_checkpoint(self.database, self.checkpoint)
        with self.assertRaises(StageConflict):
            verify_stage(self.database, self.checkpoint)
        # A validação não corrige/sobrescreve uma divergência existente.
        with self.database.read() as conn:
            value = conn.execute("SELECT payload FROM migration_rows WHERE table_name='migration_probe' AND ordinal=1").fetchone()["payload"]
            self.assertEqual(0, decode_cell(value["cells"][2]))

    def test_partial_transport_failure_rolls_back_all_ddl_rows_and_state_then_retry_works(self):
        from app.migration_checkpoint import table_rows as original_rows
        before = inventory(self.source)

        def interrupted(conn, table):
            for row in original_rows(conn, table):
                yield row
                if table["name"] == "migration_probe":
                    raise RuntimeError("transporte interrompido após linhas anteriores")

        with patch("app.postgres_migration_stage.table_rows", side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, "interrompido"):
                stage_checkpoint(self.database, self.checkpoint)
        self.assertEqual(set(), self.tables())
        self.assertEqual(before, inventory(self.source))
        self.assertEqual(self.manifest, verify_checkpoint(self.checkpoint))
        self.assertFalse(stage_checkpoint(self.database, self.checkpoint)["duplicate"])

    def test_verification_failure_rolls_back_and_preserves_snapshot_for_retry(self):
        with patch("app.postgres_migration_stage._verify_rows", side_effect=StageConflict("conferência falhou")):
            with self.assertRaises(StageConflict):
                stage_checkpoint(self.database, self.checkpoint)
        self.assertEqual(set(), self.tables())
        self.assertFalse(stage_checkpoint(self.database, self.checkpoint)["duplicate"])

    def test_company_locator_tampering_is_detected_even_with_identical_payload(self):
        stage_checkpoint(self.database, self.checkpoint)
        with self.database.transaction() as conn:
            conn.execute("UPDATE migration_rows SET company_key='2' WHERE table_name='migration_probe' AND ordinal=1")
        with self.assertRaisesRegex(StageConflict, "empresa"):
            verify_stage(self.database, self.checkpoint)

    def test_nonempty_schema_is_preserved_and_public_is_refused(self):
        with self.database.transaction() as conn:
            conn.execute("CREATE TABLE existing_data(id bigint PRIMARY KEY)")
            conn.execute("INSERT INTO existing_data VALUES(42)")
        with self.assertRaises(StageConflict):
            stage_checkpoint(self.database, self.checkpoint)
        self.assertEqual({"existing_data"}, self.tables())
        with self.database.read() as conn:
            self.assertEqual({"id": 42}, conn.execute("SELECT * FROM existing_data").fetchone())
        public = PostgresDatabase(PostgresSettings(TEST_DSN))
        with self.assertRaisesRegex(StageConflict, "migration_"):
            stage_checkpoint(public, self.checkpoint)

    def test_another_checkpoint_is_refused_without_merging_or_replacing_existing_rows(self):
        stage_checkpoint(self.database, self.checkpoint)
        with self.core.db.transaction() as conn:
            conn.execute("UPDATE migration_probe SET amount_cents=7 WHERE id=31")
        from app.migration_checkpoint import create_checkpoint
        other = self.root / "other_checkpoint"
        create_checkpoint(self.source, other)
        with self.assertRaises(StageConflict):
            stage_checkpoint(self.database, other)
        verify_stage(self.database, self.checkpoint)
        restore_checkpoint(self.checkpoint, self.root / "rollback")
        with self.core.db.read() as conn:
            self.assertEqual(7, conn.execute("SELECT amount_cents FROM migration_probe WHERE id=31").fetchone()[0])

    def test_concurrent_retry_creates_one_complete_stage(self):
        barrier = threading.Barrier(2)

        def stage():
            barrier.wait(timeout=5)
            return stage_checkpoint(self.database, self.checkpoint)["duplicate"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(stage) for _ in range(2)]
            self.assertCountEqual([False, True], [f.result(timeout=30) for f in futures])
        verify_stage(self.database, self.checkpoint)

    def registry_checkpoint(self):
        from app.migration_checkpoint import create_checkpoint
        third = self.core.save_registration(1, 'third-party',
            {'name': 'Terceiro staging sintético', 'tax_id': '11144477735', 'data': {}}, 'fixture')
        accountant = self.core.save_registration(1, 'accountant',
            {'name': 'Contador staging sintético', 'tax_id': '52998224725',
             'data': {'crc': '1SP000000', 'crc_state': 'SP', 'category': 'accountant'}}, 'fixture')
        for cid in (1, 2):
            for row, kind in ((third, 'third-party'), (accountant, 'accountant')):
                self.core.link_registration(cid, kind, row['id'],
                    {'company_id': cid, 'version': row['version']}, 'fixture')
        checkpoint = self.root / 'registry_checkpoint'
        create_checkpoint(self.source, checkpoint)
        return checkpoint

    def test_registry_stage_preserves_profiles_links_products_documents_and_restore(self):
        checkpoint = self.registry_checkpoint()
        before = inventory(self.source)
        result = stage_checkpoint(self.database, checkpoint)
        self.assertEqual('verified_staging_only', result['status'])
        self.assertFalse(result['cutover_performed'])
        tables = {t['name']: t for t in before['tables']}
        names = ('shared_registrations', 'shared_registration_links', 'companies',
                 'masters', 'documents', 'titles', 'user_permissions')
        with self.core.db.read() as source, self.database.read() as target:
            for name in names:
                columns = [c['name'] for c in tables[name]['columns']]
                expected = [dict(r) for r in source.execute(f'SELECT * FROM "{name}"')]
                stored = target.execute('SELECT company_key,payload FROM migration_rows WHERE table_name=%s ORDER BY ordinal', (name,)).fetchall()
                actual = [dict(zip(columns, map(decode_cell, r['payload']['cells']))) for r in stored]
                self.assertCountEqual(expected, actual, name)
                if name == 'shared_registration_links':
                    self.assertEqual({'1', '2'}, {r['company_key'] for r in stored})
                    self.assertTrue(any(r['master_id'] is None for r in actual))
                    self.assertTrue(any(r['master_id'] is not None for r in actual))
        self.assertTrue(stage_checkpoint(self.database, checkpoint)['duplicate'])
        verify_stage(self.database, checkpoint)
        self.assertEqual(before, inventory(self.source))
        restore_checkpoint(checkpoint, self.root / 'registry_rollback')
        self.assertEqual(before, inventory(self.root / 'registry_rollback/escritura.sqlite3'))
        import sqlite3
        with sqlite3.connect(self.root / 'registry_rollback/escritura.sqlite3') as restored:
            self.assertEqual([], restored.execute('PRAGMA foreign_key_check').fetchall())

    def test_registry_stage_rejects_missing_link_without_repairing_it(self):
        checkpoint = self.registry_checkpoint()
        stage_checkpoint(self.database, checkpoint)
        with self.database.transaction() as conn:
            count = conn.execute("SELECT count(*) AS n FROM migration_rows WHERE table_name='shared_registration_links'").fetchone()['n']
            conn.execute("DELETE FROM migration_rows WHERE table_name='shared_registration_links' AND ordinal=1")
        with self.assertRaises(StageConflict):
            verify_stage(self.database, checkpoint)
        with self.assertRaises(StageConflict):
            stage_checkpoint(self.database, checkpoint)
        with self.database.read() as conn:
            self.assertEqual(count - 1, conn.execute("SELECT count(*) AS n FROM migration_rows WHERE table_name='shared_registration_links'").fetchone()['n'])
        verify_checkpoint(checkpoint)

    def test_large_signed_totals_beyond_int64_are_preserved_in_manifest(self):
        with self.core.db.transaction() as conn:
            conn.execute("UPDATE migration_probe SET company_id=1,amount_cents=?", (2**63-1,))
        from app.migration_checkpoint import create_checkpoint
        other = self.root / "large_checkpoint"
        create_checkpoint(self.source, other)
        stage_checkpoint(self.database, other)
        with self.database.read() as conn:
            manifest = conn.execute("SELECT manifest FROM migration_checkpoint").fetchone()["manifest"]
            probe = next(t for t in manifest["inventory"]["tables"] if t["name"] == "migration_probe")
            self.assertEqual("18446744073709551614", probe["summary"]["companies"]["1"]["cents"]["amount_cents"])


if __name__ == "__main__":
    if not HAS_DRIVER or not TEST_DSN:
        raise SystemExit("Instale requirements-postgres.txt e configure ESCRITURA_POSTGRES_TEST_DSN de teste descartável.")
    unittest.main(verbosity=2)
