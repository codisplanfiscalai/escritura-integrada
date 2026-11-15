"""Snapshots/rollback sintéticos; não acessa empresas ou perfis reais."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.business import BusinessCore
from app.db import Database
from app.migration_checkpoint import (
    CheckpointError, DATABASE_FILE, canonical, create_checkpoint, decode_cell, encode_cell,
    file_hash, inventory, restore_checkpoint, verify_checkpoint,
)


class CheckpointFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.core = BusinessCore(Database(self.root / "source"), demo=True)
        self.session_token = self.core.setup({"username": "migration-fixture", "password": "Fixture-pass-20261115"})
        self.core.save_group({"name": "Grupo sintético preservado", "company_ids": [1],
                              "permissions": [{"company_id": 1, "routine": "fiscal.*", "action": "read", "effect": "allow"}]}, "fixture")
        self.source = self.core.db.path
        self.checkpoint = self.root / "checkpoint"
        # Dados heterogêneos e originais ficam em uma tabela sintética adicional.
        self.original = (Path(__file__).parent / "fixtures/nfe_ficticia.xml").read_bytes()
        with self.core.db.transaction() as conn:
            conn.execute("UPDATE documents SET journal_id=(SELECT MIN(id) FROM journals WHERE company_id=1) WHERE company_id=1")
            conn.execute("UPDATE titles SET document_id=(SELECT MIN(id) FROM documents WHERE company_id=1) WHERE company_id=1")
            conn.execute("""CREATE TABLE migration_probe (
                id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER NOT NULL REFERENCES companies(id),
                amount_cents INTEGER NOT NULL, original BLOB NOT NULL, label TEXT, value REAL)""")
            conn.execute("INSERT INTO migration_probe VALUES(?,?,?, ?,?,?)",
                         (31, 1, 99_999_999_999_999, self.original, "ação\x00fim", 0.1))
            conn.execute("INSERT INTO migration_probe VALUES(?,?,?, ?,?,?)",
                         (32, 2, -7, b"\x00\xff", None, None))
            # AUTOINCREMENT pode exceder o máximo vivo; deve ser reservado, não reciclado.
            conn.execute("INSERT INTO migration_probe VALUES(200,1,1,X'00','retido',0)")
            conn.execute("DELETE FROM migration_probe WHERE id=200")
            conn.execute("INSERT INTO bulk_deleted_movements VALUES('documents',900,1,'retido','2026-11-15')")
            conn.execute("CREATE TABLE migration_composite (a TEXT, b INTEGER, PRIMARY KEY(a,b)) WITHOUT ROWID")
            conn.execute("INSERT INTO migration_composite VALUES('A',7)")

    def create(self):
        return create_checkpoint(self.source, self.checkpoint)


class MigrationCheckpointTests(CheckpointFixture):
    def test_all_tables_types_ids_company_totals_and_reservations_survive_restore(self):
        before = inventory(self.source)
        manifest = self.create()
        self.assertEqual(before, manifest["inventory"])
        self.assertEqual(manifest, verify_checkpoint(self.checkpoint))
        restore_checkpoint(self.checkpoint, self.root / "restored")
        self.assertEqual(before, inventory(self.root / "restored/escritura.sqlite3"))
        tables = {table["name"]: table for table in before["tables"]}
        totals = tables["migration_probe"]["summary"]["companies"]
        self.assertEqual({"count": 1, "cents": {"amount_cents": "99999999999999"}}, totals["1"])
        self.assertEqual({"count": 1, "cents": {"amount_cents": "-7"}}, totals["2"])
        self.assertEqual("201", before["id_reservations"]["migration_probe"]["next_minimum"])
        self.assertEqual("901", before["id_reservations"]["documents"]["next_minimum"])
        self.assertNotIn("bulk_previews", before["id_reservations"])
        with closing(sqlite3.connect(self.root / "restored/escritura.sqlite3")) as conn:
            self.assertEqual((31, self.original, "ação\x00fim", 0.1), conn.execute(
                "SELECT id,original,label,value FROM migration_probe WHERE company_id=1").fetchone())
        self.assertFalse(manifest["cutover_performed"])
        restored_core = BusinessCore(Database(self.root / "restored"))
        session = restored_core.session(self.session_token)
        self.assertTrue(session["authenticated"])
        self.assertEqual("migration-fixture", session["user"]["username"])
        self.assertEqual("Grupo sintético preservado", restored_core.groups()[0]["name"])

    def test_sequence_exhaustion_is_reported_without_resetting_or_recycling_ids(self):
        with self.core.db.transaction() as conn:
            conn.execute("UPDATE sqlite_sequence SET seq=? WHERE name='migration_probe'", (2**63-1,))
        manifest = self.create()
        reserve = manifest["inventory"]["id_reservations"]["migration_probe"]
        self.assertTrue(reserve["int64_exhausted"])
        self.assertEqual(str(2**63-1), reserve["high_water"])
        self.assertEqual(str(2**63), reserve["next_minimum"])

    def test_wal_commits_are_captured_uncommitted_writes_are_excluded_and_source_is_unchanged(self):
        with closing(sqlite3.connect(self.source, isolation_level=None)) as keeper:
            keeper.execute("PRAGMA journal_mode=WAL")
            keeper.execute("PRAGMA wal_autocheckpoint=0")
            before_file = file_hash(self.source)
            keeper.execute("UPDATE migration_probe SET label='commit apenas WAL' WHERE id=31")
            self.assertTrue(Path(str(self.source) + "-wal").stat().st_size > 0)
            self.assertEqual(before_file, file_hash(self.source), "O commit deve estar somente no WAL")
            keeper.execute("BEGIN IMMEDIATE")
            keeper.execute("UPDATE migration_probe SET amount_cents=123 WHERE id=31")
            manifest = self.create()
            self.assertEqual(before_file, file_hash(self.source), "A captura não faz checkpoint da origem")
            self.assertEqual("wal", keeper.execute("PRAGMA journal_mode").fetchone()[0])
            keeper.rollback()
        with closing(sqlite3.connect(self.checkpoint / DATABASE_FILE)) as conn:
            self.assertEqual(("commit apenas WAL", 99_999_999_999_999), conn.execute(
                "SELECT label,amount_cents FROM migration_probe WHERE id=31").fetchone())
        self.assertTrue(manifest["restore_verified"])

    def test_destination_never_overwrites_source_or_existing_checkpoint_or_restore(self):
        original = inventory(self.source)
        self.create()
        for destination in (self.checkpoint, self.source.parent):
            with self.assertRaises(FileExistsError):
                create_checkpoint(self.source, destination)
        restore_checkpoint(self.checkpoint, self.root / "restored")
        with self.assertRaises(FileExistsError):
            restore_checkpoint(self.checkpoint, self.root / "restored")
        self.assertEqual(original, inventory(self.source))

    def test_tampering_counts_and_data_is_detected(self):
        self.create()
        with closing(sqlite3.connect(self.checkpoint / DATABASE_FILE)) as conn, conn:
            conn.execute("UPDATE migration_probe SET amount_cents=0 WHERE id=31")
        with self.assertRaises(CheckpointError):
            verify_checkpoint(self.checkpoint)
        self.assertFalse((self.root / "restored").exists())
        with self.assertRaises(CheckpointError):
            restore_checkpoint(self.checkpoint, self.root / "restored")

    def test_forged_byte_hash_does_not_bypass_semantic_verification(self):
        self.create()
        with closing(sqlite3.connect(self.checkpoint / DATABASE_FILE)) as conn, conn:
            conn.execute("UPDATE migration_probe SET company_id=2 WHERE id=31")
        metadata = self.checkpoint / "manifest.json"
        manifest = json.loads(metadata.read_text())
        manifest["snapshot_sha256"] = file_hash(self.checkpoint / DATABASE_FILE)
        metadata.write_bytes(canonical(manifest))
        with self.assertRaises(CheckpointError):
            verify_checkpoint(self.checkpoint)

    def test_broken_links_newer_schema_and_noninteger_cents_fail_closed(self):
        with self.core.db.read() as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("UPDATE migration_probe SET company_id=999 WHERE id=31")
        with self.assertRaisesRegex(RuntimeError, "referências"):
            self.create()
        self.assertFalse((self.checkpoint / "manifest.json").exists())
        with self.core.db.read() as conn:
            conn.execute("UPDATE migration_probe SET company_id=1 WHERE id=31")
            conn.execute("UPDATE meta SET value='999' WHERE key='schema_version'")
        with self.assertRaises(CheckpointError):
            inventory(self.source)
        with self.core.db.read() as conn:
            conn.execute("UPDATE meta SET value='6' WHERE key='schema_version'")
            conn.execute("UPDATE migration_probe SET amount_cents=1.5 WHERE id=31")
        with self.assertRaisesRegex(CheckpointError, "centavos"):
            inventory(self.source)

    def test_restore_proof_failure_never_publishes_manifest_or_changes_source(self):
        before = inventory(self.source)
        with patch("app.migration_checkpoint.inventory", side_effect=[before, {"different": True}]):
            with self.assertRaisesRegex(CheckpointError, "restauração"):
                self.create()
        self.assertFalse((self.checkpoint / "manifest.json").exists())
        self.assertEqual(before, inventory(self.source))

    def test_failed_snapshot_is_not_a_valid_checkpoint(self):
        with patch("app.migration_checkpoint.time.monotonic", side_effect=[0, 100]):
            with self.assertRaisesRegex(CheckpointError, "limite"):
                self.create()
        with self.assertRaises(CheckpointError):
            verify_checkpoint(self.checkpoint)

    def test_cells_round_trip_without_loss_including_nul_and_blob(self):
        for value in (None, 2**63 - 1, -(2**63), 0.1, float("inf"), "a\x00ação", b"\x00\xff"):
            with self.subTest(value=value):
                self.assertEqual(value, decode_cell(encode_cell(value)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
