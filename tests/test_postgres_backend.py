"""Provas de infraestrutura em PostgreSQL real, com schemas descartáveis.

As tabelas probe_* são fixtures, não representam homologação dos serviços fiscais.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import importlib.util
import os
from pathlib import Path
import threading
import unittest
import uuid

HAS_DRIVER = importlib.util.find_spec("psycopg") is not None
TEST_DSN = os.environ.get("ESCRITURA_POSTGRES_TEST_DSN", "")
if HAS_DRIVER:
    import psycopg
    from psycopg import sql
    from app.postgres_backend import (
        Migration, MigrationHistoryError, PostgresConfigurationError,
        PostgresDatabase, PostgresSettings, PostgresUnavailable,
    )


@unittest.skipUnless(HAS_DRIVER, "Instale requirements-postgres.txt para validar o backend opcional.")
class PostgresConfigurationTests(unittest.TestCase):
    def test_requires_explicit_connection_without_sqlite_or_environment_fallback(self):
        for dsn in ("", " ", "sqlite:///tmp/local.db", "dbname=test", "service=escritura", "bad=secret-value"):
            with self.subTest(dsn=dsn), self.assertRaises(PostgresConfigurationError) as caught:
                PostgresSettings(dsn)
            self.assertNotIn("secret-value", str(caught.exception))

    def test_settings_repr_hides_credentials_and_rejects_unsafe_schema_or_timeouts(self):
        valid = PostgresSettings("postgresql://fixture:secret-value@127.0.0.1/test")
        self.assertNotIn("secret-value", repr(valid))
        for changes in ({"schema": 'public; DROP TABLE users'}, {"schema": "x" * 64},
                        {"connect_timeout": 0}, {"statement_timeout_ms": True},
                        {"lock_timeout_ms": -1}):
            with self.subTest(changes=changes), self.assertRaises(PostgresConfigurationError):
                replace(valid, **changes)

    def test_migrations_require_complete_ordered_source(self):
        db = PostgresDatabase(PostgresSettings("host=127.0.0.1 dbname=test user=fixture"))
        for migrations in ((Migration(2, "gap", ("SELECT 1",)),), ("not_a_migration",)):
            with self.assertRaises(ValueError):
                db.apply_migrations(migrations)
        for values in ((True, "invalid", ("SELECT 1",)), (1, "invalid name", ("SELECT 1",)),
                       (1, "invalid", ["SELECT 1"]), (1, "invalid", ("",))):
            with self.assertRaises(ValueError):
                Migration(*values)


@unittest.skipUnless(HAS_DRIVER and TEST_DSN, "Requer ESCRITURA_POSTGRES_TEST_DSN de banco descartável.")
class PostgresBackendTests(unittest.TestCase):
    def setUp(self):
        self.schema = "test_backend_" + uuid.uuid4().hex
        settings = PostgresSettings(TEST_DSN, schema=self.schema)
        # O DSN de teste é exclusivo; não usa a configuração do aplicativo.
        with psycopg.connect(TEST_DSN, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        self.db = PostgresDatabase(settings)

    def drop_schema(self):
        with psycopg.connect(TEST_DSN, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def create_probes(self):
        self.db.apply_migrations((Migration(1, "backend_probes", (
            """CREATE TABLE probe_movements (
                id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                company_id bigint NOT NULL, request_key text NOT NULL,
                cents bigint NOT NULL CHECK(cents >= 0), original bytea NOT NULL,
                UNIQUE(company_id, request_key), UNIQUE(company_id,id))""",
            """CREATE TABLE probe_audit (
                company_id bigint NOT NULL, movement_id bigint NOT NULL, actor text NOT NULL,
                FOREIGN KEY(company_id,movement_id) REFERENCES probe_movements(company_id,id))""",
        )),))

    def counts(self):
        with self.db.read() as conn:
            return tuple(conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(
                sql.Identifier(table))).fetchone()["n"] for table in ("probe_movements", "probe_audit"))

    def test_commit_returning_binary_xml_alphanumeric_cnpj_and_large_cents(self):
        self.create_probes()
        raw = (Path(__file__).parent / "fixtures" / "nfe_ficticia.xml").read_bytes()
        with self.db.transaction() as conn:
            result = conn.execute("""INSERT INTO probe_movements(company_id,request_key,cents,original)
                VALUES(%s,%s,%s,%s) RETURNING id""", (1, "12ABC34501DE35", 99_999_999_999_999, raw)).fetchone()
            conn.execute("INSERT INTO probe_audit VALUES(%s,%s,%s)", (1, result["id"], "fixture-ação"))
            writer = conn
        self.assertTrue(writer.closed)
        with self.db.read() as conn:
            row = conn.execute("SELECT * FROM probe_movements").fetchone()
            self.assertEqual(raw, row["original"])
            self.assertEqual(99_999_999_999_999, row["cents"])
            self.assertEqual("12ABC34501DE35", row["request_key"])
        self.assertTrue(conn.closed)
        self.assertEqual((1, 1), self.counts())

    def test_exception_rolls_back_movement_and_audit_then_retry_succeeds(self):
        self.create_probes()
        with self.assertRaisesRegex(RuntimeError, "interrompida"):
            with self.db.transaction() as conn:
                iid = conn.execute("""INSERT INTO probe_movements(company_id,request_key,cents,original)
                    VALUES(1,'retry',1,%s) RETURNING id""", (b"fixture",)).fetchone()["id"]
                conn.execute("INSERT INTO probe_audit VALUES(1,%s,'fixture')", (iid,))
                raise RuntimeError("operação interrompida")
        self.assertTrue(conn.closed)
        self.assertEqual((0, 0), self.counts())
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO probe_movements(company_id,request_key,cents,original) VALUES(1,'retry',1,%s)", (b"fixture",))
        self.assertEqual((1, 0), self.counts())

    def test_baseexception_rolls_back_and_closes(self):
        self.create_probes()
        with self.assertRaises(KeyboardInterrupt):
            with self.db.transaction() as conn:
                conn.execute("INSERT INTO probe_movements(company_id,request_key,cents,original) VALUES(1,'interrupt',1,%s)", (b"fixture",))
                raise KeyboardInterrupt()
        self.assertTrue(conn.closed)
        self.assertEqual((0, 0), self.counts())

    def test_foreign_key_failure_rolls_back_all_effects(self):
        self.create_probes()
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            with self.db.transaction() as conn:
                iid = conn.execute("""INSERT INTO probe_movements(company_id,request_key,cents,original)
                    VALUES(1,'tenant',1,%s) RETURNING id""", (b"fixture",)).fetchone()["id"]
                conn.execute("INSERT INTO probe_audit VALUES(2,%s,'fixture')", (iid,))
        self.assertEqual((0, 0), self.counts())

    def test_unique_and_check_constraints_are_native(self):
        self.create_probes()
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO probe_movements(company_id,request_key,cents,original) VALUES(1,'unique',1,%s)", (b"fixture",))
        for key, cents, error in (("unique", 1, psycopg.errors.UniqueViolation),
                                   ("negative", -1, psycopg.errors.CheckViolation)):
            with self.assertRaises(error), self.db.transaction() as conn:
                conn.execute("INSERT INTO probe_movements(company_id,request_key,cents,original) VALUES(1,%s,%s,%s)", (key, cents, b"fixture"))
        self.assertEqual((1, 0), self.counts())

    def test_read_rejects_writes_and_closes(self):
        self.create_probes()
        with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
            with self.db.read() as conn:
                conn.execute("DELETE FROM probe_movements")
        self.assertTrue(conn.closed)
        self.assertEqual((0, 0), self.counts())

    def test_snapshot_preserves_view_across_another_connection_commit(self):
        self.create_probes()
        with self.db.read(snapshot=True) as reader:
            self.assertEqual(0, reader.execute("SELECT count(*) AS n FROM probe_movements").fetchone()["n"])
            with self.db.transaction() as writer:
                writer.execute("INSERT INTO probe_movements(company_id,request_key,cents,original) VALUES(1,'snapshot',1,%s)", (b"fixture",))
            self.assertEqual(0, reader.execute("SELECT count(*) AS n FROM probe_movements").fetchone()["n"])
        self.assertEqual((1, 0), self.counts())

    def test_migrations_are_idempotent_and_detect_changed_or_missing_history(self):
        first = Migration(1, "first", ("CREATE TABLE probe_one(id bigint PRIMARY KEY)",))
        second = Migration(2, "second", ("CREATE TABLE probe_two(id bigint PRIMARY KEY)",))
        self.assertEqual((1,), self.db.apply_migrations((first,)))
        self.assertEqual((2,), self.db.apply_migrations((first, second)))
        self.assertEqual((), self.db.apply_migrations((first, second)))
        changed = replace(first, statements=("CREATE TABLE changed(id bigint PRIMARY KEY)",))
        for source in ((changed, second), (first,), ()):
            with self.assertRaises(MigrationHistoryError):
                self.db.apply_migrations(source)
        with self.db.read() as conn:
            self.assertIsNone(conn.execute("SELECT to_regclass('changed') AS name").fetchone()["name"])
            self.assertEqual(2, conn.execute("SELECT count(*) AS n FROM _escritura_migrations").fetchone()["n"])

    def test_failed_migration_rolls_back_ddl_data_and_history_then_retry_works(self):
        first = Migration(1, "first", ("CREATE TABLE probe_one(id bigint PRIMARY KEY)",))
        broken = Migration(2, "broken", ("INSERT INTO probe_one VALUES(1)", "SELECT * FROM missing_probe"))
        with self.assertRaises(psycopg.errors.UndefinedTable):
            self.db.apply_migrations((first, broken))
        with self.db.read() as conn:
            for table in ("probe_one", "_escritura_migrations"):
                self.assertIsNone(conn.execute("SELECT to_regclass(%s) AS name", (table,)).fetchone()["name"])
        self.assertEqual((1,), self.db.apply_migrations((first,)))

    def test_concurrent_bootstraps_apply_exactly_once(self):
        barrier = threading.Barrier(2)
        migration = Migration(1, "concurrent", ("CREATE TABLE probe_once(id bigint PRIMARY KEY)", "INSERT INTO probe_once VALUES(1)"))

        def apply():
            barrier.wait(timeout=5)
            return self.db.apply_migrations((migration,))

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(apply) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        self.assertCountEqual([(), (1,)], results)
        with self.db.read() as conn:
            self.assertEqual([{"id": 1}], conn.execute("SELECT * FROM probe_once").fetchall())

    def test_failed_upgrade_preserves_previous_history_and_data(self):
        first = Migration(1, "first", ("CREATE TABLE probe_existing(id bigint PRIMARY KEY)",
                                       "INSERT INTO probe_existing VALUES(1)"))
        self.db.apply_migrations((first,))
        broken = Migration(2, "broken", ("UPDATE probe_existing SET id=2", "SELECT * FROM missing_probe"))
        with self.assertRaises(psycopg.errors.UndefinedTable):
            self.db.apply_migrations((first, broken))
        with self.db.read() as conn:
            self.assertEqual([{"id": 1}], conn.execute("SELECT * FROM probe_existing").fetchall())
            self.assertEqual([{"version": 1}], conn.execute("SELECT version FROM _escritura_migrations").fetchall())

    def test_explicit_commit_cannot_break_atomic_context(self):
        self.create_probes()
        with self.assertRaises(psycopg.ProgrammingError):
            with self.db.transaction() as conn:
                conn.execute("INSERT INTO probe_movements(company_id,request_key,cents,original) VALUES(1,'commit',1,%s)", (b"fixture",))
                conn.commit()
        self.assertEqual((0, 0), self.counts())

    def test_advisory_lock_timeout_releases_connection_and_allows_retry(self):
        limited = PostgresDatabase(replace(self.db.settings, lock_timeout_ms=100))
        migration = Migration(1, "lock_retry", ("CREATE TABLE probe_lock(id bigint)",))
        with self.db.transaction() as holder:
            holder.execute("SELECT pg_advisory_xact_lock(1163084626, 1)")
            with self.assertRaises(psycopg.errors.LockNotAvailable):
                limited.apply_migrations((migration,))
        self.assertEqual((1,), limited.apply_migrations((migration,)))

    def test_statement_timeout_rolls_back_and_connection_is_closed(self):
        self.create_probes()
        limited = PostgresDatabase(replace(self.db.settings, statement_timeout_ms=100))
        with self.assertRaises(psycopg.errors.QueryCanceled):
            with limited.transaction() as conn:
                conn.execute("INSERT INTO probe_movements(company_id,request_key,cents,original) VALUES(1,'timeout',1,%s)", (b"fixture",))
                conn.execute("SELECT pg_sleep(2)")
        self.assertTrue(conn.closed)
        self.assertEqual((0, 0), self.counts())

    def test_missing_schema_fails_instead_of_writing_to_public(self):
        missing = PostgresDatabase(replace(self.db.settings, schema="missing_" + uuid.uuid4().hex))
        with self.assertRaises(PostgresConfigurationError):
            missing.apply_migrations((Migration(1, "missing", ("SELECT 1",)),))

    def test_connection_failure_is_sanitized(self):
        unavailable = PostgresDatabase(PostgresSettings("host=127.0.0.1 port=1 dbname=fixture user=fixture password=secret-value"))
        with self.assertRaises(PostgresUnavailable) as caught:
            with unavailable.transaction():
                self.fail("Não deve abrir transação")
        self.assertNotIn("secret-value", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)


if __name__ == "__main__":
    # O comando dedicado nunca pode sinalizar homologação real com todos pulados.
    if not HAS_DRIVER or not TEST_DSN:
        raise SystemExit("Instale requirements-postgres.txt e defina ESCRITURA_POSTGRES_TEST_DSN para um banco de teste descartável.")
    unittest.main(verbosity=2)
