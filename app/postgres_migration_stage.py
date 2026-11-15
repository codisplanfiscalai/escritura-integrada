"""Ensaio de transporte integral para staging PostgreSQL; não é banco operacional.

Usa exclusivamente schema migration_* vazio ou um ensaio idêntico já verificado.
Nunca limpa, mescla, sobrescreve ou promove empresas/tabelas do aplicativo.
"""
from contextlib import closing
from pathlib import Path

from psycopg.types.json import Jsonb

from .migration_checkpoint import (
    CheckpointError, DATABASE_FILE, company_key, readonly, summarize, table_rows, verify_checkpoint,
)
from .postgres_backend import PostgresDatabase


class StageConflict(CheckpointError):
    pass


def _verify_rows(conn, expected):
    inventory = expected["inventory"]
    tables = {table["name"]: table for table in inventory["tables"]}
    names = {row["table_name"] for row in conn.execute("SELECT DISTINCT table_name FROM migration_rows")}
    if not names <= tables.keys():
        raise StageConflict("Tabela inesperada no ensaio PostgreSQL.")
    for name, table in tables.items():
        def payloads():
            # Cursor de servidor evita carregar uma tabela inteira na memória do cliente.
            with conn.cursor(name="verify_migration_rows") as cursor:
                cursor.execute("""SELECT ordinal,company_key,payload FROM migration_rows
                                  WHERE table_name=%s ORDER BY ordinal""", (name,))
                for ordinal, row in enumerate(cursor, 1):
                    if row["ordinal"] != ordinal or row["company_key"] != company_key(table, row["payload"]):
                        raise StageConflict("Identidade ou segregação de empresa divergente no staging.")
                    yield row["payload"]
        if summarize(table, payloads()) != table["summary"]:
            raise StageConflict("Staging diverge do checkpoint: dados, contagens, totais, IDs ou vínculos.")


def _locked_schema(conn, database):
    if not database.settings.schema.startswith("migration_"):
        raise StageConflict("Use um schema de preparação migration_*, nunca public ou o schema operacional.")
    conn.execute("SELECT pg_advisory_xact_lock(1163084626, 2)")
    existing = {row["relname"] for row in conn.execute("""SELECT c.relname FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=%s AND c.relkind IN ('r','p','v','m','f','S')""", (database.settings.schema,))}
    if existing and existing != {"migration_checkpoint", "migration_rows"}:
        raise StageConflict("Schema não está vazio ou pertence a outro uso; nenhum dado será substituído.")
    return bool(existing)


def stage_checkpoint(database: PostgresDatabase, directory):
    expected = verify_checkpoint(directory)
    with database.transaction() as conn:
        exists = _locked_schema(conn, database)
        if exists:
            stored = conn.execute("SELECT * FROM migration_checkpoint").fetchall()
            if len(stored) != 1 or stored[0]["manifest"] != expected or stored[0]["status"] != "verified":
                raise StageConflict("Outro checkpoint ou ensaio incompleto existe neste schema; use um schema novo.")
            _verify_rows(conn, expected)
            if verify_checkpoint(directory) != expected:
                raise StageConflict("Checkpoint mudou durante a conferência; operação revertida.")
            return {"snapshot_sha256": expected["snapshot_sha256"], "duplicate": True,
                    "status": "verified_staging_only", "cutover_performed": False}
        conn.execute("""CREATE TABLE migration_checkpoint (
            singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
            snapshot_sha256 text NOT NULL CHECK(length(snapshot_sha256)=64), manifest jsonb NOT NULL,
            status text NOT NULL CHECK(status IN ('staging','verified')),
            created_at timestamptz NOT NULL DEFAULT transaction_timestamp())""")
        conn.execute("""CREATE TABLE migration_rows (
            checkpoint boolean NOT NULL DEFAULT true REFERENCES migration_checkpoint(singleton),
            table_name text NOT NULL, ordinal bigint NOT NULL CHECK(ordinal>0),
            company_key text NOT NULL, payload jsonb NOT NULL,
            PRIMARY KEY(table_name,ordinal))""")
        conn.execute("INSERT INTO migration_checkpoint(snapshot_sha256,manifest,status) VALUES(%s,%s,'staging')",
                     (expected["snapshot_sha256"], Jsonb(expected)))
        with closing(readonly(Path(directory) / DATABASE_FILE)) as source:
            source.execute("BEGIN")
            with conn.cursor() as cursor:
                for table in expected["inventory"]["tables"]:
                    # executemany consome o iterador; não acumula o banco inteiro em RAM.
                    cursor.executemany("INSERT INTO migration_rows(table_name,ordinal,company_key,payload) VALUES(%s,%s,%s,%s)",
                        ((table["name"], ordinal, company_key(table, payload), Jsonb(payload))
                         for ordinal, payload in enumerate(table_rows(source, table), 1)))
        _verify_rows(conn, expected)
        if verify_checkpoint(directory) != expected:
            raise StageConflict("Checkpoint mudou durante o transporte; ensaio revertido.")
        conn.execute("UPDATE migration_checkpoint SET status='verified'")
        return {"snapshot_sha256": expected["snapshot_sha256"], "duplicate": False,
                "status": "verified_staging_only", "cutover_performed": False}


def verify_stage(database: PostgresDatabase, directory):
    expected = verify_checkpoint(directory)
    with database.read(snapshot=True) as conn:
        if not database.settings.schema.startswith("migration_"):
            raise StageConflict("O schema não é de preparação migration_*.")
        stored = conn.execute("SELECT * FROM migration_checkpoint").fetchall()
        if len(stored) != 1 or stored[0]["manifest"] != expected or stored[0]["status"] != "verified":
            raise StageConflict("Checkpoint ou estado PostgreSQL divergente.")
        _verify_rows(conn, expected)
    return {"snapshot_sha256": expected["snapshot_sha256"], "status": "verified_staging_only",
            "cutover_performed": False}


def main():
    import argparse
    import json
    import os
    from .postgres_backend import PostgresSettings
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "verify"))
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--schema", required=True, help="schema migration_* já criado e isolado")
    args = parser.parse_args()
    database = PostgresDatabase(PostgresSettings(os.environ.get("ESCRITURA_MIGRATION_DSN", ""), schema=args.schema))
    result = stage_checkpoint(database, args.checkpoint) if args.action == "stage" else verify_stage(database, args.checkpoint)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
