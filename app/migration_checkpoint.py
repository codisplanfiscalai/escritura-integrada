"""Checkpoint administrativo de migração; não muda o banco ativo do aplicativo.

Captura o SQLite pela API de backup (incluindo WAL), restaura uma cópia de prova
e inventaria todas as linhas com tipos, IDs, vínculos, totais e reservas de IDs.
"""
from contextlib import closing
import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time

from .maintenance import SCHEMA_VERSION, integrity

FORMAT = "escritura-migration-checkpoint-1"
DATABASE_FILE = "snapshot.sqlite3"


class CheckpointError(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def identifier(value):
    return '"' + value.replace('"', '""') + '"'


def readonly(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def encode_cell(value):
    # Texto também usa base64: JSONB não aceita U+0000, presente em alguns dados SQLite.
    if value is None:
        return ["null"]
    if isinstance(value, int):
        return ["integer", str(value)]
    if isinstance(value, float):
        return ["real", value.hex()]
    if isinstance(value, str):
        return ["text", base64.b64encode(value.encode("utf-8")).decode("ascii")]
    if isinstance(value, bytes):
        return ["blob", base64.b64encode(value).decode("ascii")]
    raise CheckpointError("Tipo SQLite não suportado; checkpoint recusado.")


def decode_cell(cell):
    if cell == ["null"]:
        return None
    kind, value = cell
    if kind == "integer":
        return int(value)
    if kind == "real":
        return float.fromhex(value)
    if kind == "text":
        return base64.b64decode(value, validate=True).decode("utf-8")
    if kind == "blob":
        return base64.b64decode(value, validate=True)
    raise CheckpointError("Tipo do checkpoint inválido.")


def table_rows(conn, table):
    names = [column["name"] for column in table["columns"]]
    if table["rowid_alias"]:
        locator = identifier(table["rowid_alias"])
        query = f"SELECT {locator},* FROM {identifier(table['name'])} ORDER BY {locator}"
    else:
        keys = [c["name"] for c in sorted(table["columns"], key=lambda c: c["pk"]) if c["pk"]]
        query = f"SELECT * FROM {identifier(table['name'])} ORDER BY " + ",".join(map(identifier, keys))
    for row in conn.execute(query):
        values = tuple(row)
        if table["rowid_alias"]:
            rowid, values = values[0], values[1:]
        else:
            rowid = None
        if len(values) != len(names):
            raise CheckpointError("Colunas do snapshot divergentes.")
        yield {"source_rowid": rowid, "cells": [encode_cell(value) for value in values]}


def company_key(table, payload):
    columns = [column["name"] for column in table["columns"]]
    scope_column = "id" if table["name"] == "companies" else next(
        (column for column in ("company_id", "source_company_id") if column in columns), None)
    if scope_column is None:
        return "global"
    value = decode_cell(payload["cells"][columns.index(scope_column)])
    return "global" if value is None else str(value)


def summarize(table, rows):
    h, count, groups, maximum = hashlib.sha256(), 0, {}, 0
    columns = [column["name"] for column in table["columns"]]
    cents = [index for index, name in enumerate(columns) if name.endswith("_cents")]
    for payload in rows:
        if len(payload["cells"]) != len(columns):
            raise CheckpointError("Quantidade de colunas divergente.")
        encoded = canonical(payload)
        h.update(len(encoded).to_bytes(8, "big")); h.update(encoded)
        count += 1
        key = company_key(table, payload)
        group = groups.setdefault(key, {"count": 0, "cents": {columns[i]: 0 for i in cents}})
        group["count"] += 1
        for index in cents:
            value = decode_cell(payload["cells"][index])
            if value is not None:
                if type(value) is not int:
                    raise CheckpointError("Valor monetário fora de centavos inteiros; revisão necessária.")
                group["cents"][columns[index]] += value
        if "id" in columns:
            value = decode_cell(payload["cells"][columns.index("id")])
            if type(value) is int:
                maximum = max(maximum, value)
    # Strings decimais preservam somas acima de int64 e precisão em consumidores JSON.
    for group in groups.values():
        group["cents"] = {key: str(value) for key, value in group["cents"].items()}
    return {"count": count, "sha256": h.hexdigest(), "companies": groups, "max_id": str(maximum)}


def inventory(path):
    status = integrity(path)
    if status["schema_version"] != SCHEMA_VERSION:
        raise CheckpointError("Atualize e valide o schema SQLite antes deste ensaio de migração.")
    with closing(readonly(path)) as conn:
        conn.execute("BEGIN")
        objects = [dict(row) for row in conn.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name")]
        tables = []
        for row in sorted(conn.execute("PRAGMA table_list"), key=lambda row: row["name"]):
            name = row["name"]
            if name.startswith("sqlite_"):
                continue
            if row["type"] == "view":
                continue
            if row["type"] != "table":
                raise CheckpointError("Tabela virtual/shadow requer plano explícito de migração.")
            columns = [dict(column) for column in conn.execute(f"PRAGMA table_xinfo({identifier(name)})")]
            names = [column["name"] for column in columns]
            alias = None if row["wr"] else next((a for a in ("_rowid_", "rowid", "oid") if a not in names), None)
            if not row["wr"] and alias is None:
                raise CheckpointError("Rowid oculto não acessível; revisão necessária.")
            table = {"name": name, "columns": columns, "rowid_alias": alias,
                     "foreign_keys": [dict(fk) for fk in conn.execute(f"PRAGMA foreign_key_list({identifier(name)})")]}
            table["summary"] = summarize(table, table_rows(conn, table))
            tables.append(table)
        sequence_values = {}
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
            for row in conn.execute("SELECT * FROM sqlite_sequence"):
                if row["name"] in sequence_values or type(row["seq"]) is not int or row["seq"] < 0:
                    raise CheckpointError("Metadados de sequência SQLite inválidos; revisão necessária.")
                sequence_values[row["name"]] = row["seq"]
        reservations = {}
        for table in tables:
            maximum = max(int(table["summary"]["max_id"]), sequence_values.get(table["name"], 0))
            if table["name"] in {"documents", "journals"} and any(t["name"] == "bulk_deleted_movements" for t in tables):
                removed = conn.execute("SELECT COALESCE(MAX(record_id),0) FROM bulk_deleted_movements WHERE kind=?", (table["name"],)).fetchone()[0]
                maximum = max(maximum, removed)
            primary = [column for column in table["columns"] if column["pk"]]
            if len(primary) == 1 and primary[0]["name"] == "id" and primary[0]["type"].upper() == "INTEGER":
                reservations[table["name"]] = {"high_water": str(maximum), "next_minimum": str(maximum + 1),
                                               "int64_exhausted": maximum >= 9_223_372_036_854_775_807}
        return {"schema_version": status["schema_version"], "objects": objects, "tables": tables,
                "sqlite_sequence": sequence_values, "id_reservations": reservations,
                "integrity": "ok", "foreign_key_violations": 0, "scope": "all-companies-all-years"}


def copy_consistent(source, destination, timeout_seconds=60):
    if type(timeout_seconds) is not int or timeout_seconds < 1:
        raise CheckpointError("Informe prazo positivo para o snapshot.")
    deadline = time.monotonic() + timeout_seconds

    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise CheckpointError("Tempo limite do snapshot; a origem foi preservada.")

    with closing(readonly(source)) as src, closing(sqlite3.connect(destination)) as dst:
        src.backup(dst, pages=256, progress=progress, sleep=0.01)
        # Somente a cópia é consolidada; nunca faz checkpoint ou altera journal_mode da origem.
        dst.execute("PRAGMA journal_mode=DELETE")
    Path(destination).chmod(0o600)


def create_checkpoint(source, destination, timeout_seconds=60):
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    snapshot = destination / DATABASE_FILE
    copy_consistent(source, snapshot, timeout_seconds)
    data = inventory(snapshot)
    with tempfile.TemporaryDirectory(prefix=".restore-proof-", dir=destination) as directory:
        restored = Path(directory) / DATABASE_FILE
        copy_consistent(snapshot, restored, timeout_seconds)
        if inventory(restored) != data:
            raise CheckpointError("A prova de restauração divergiu do snapshot.")
    result = {"format": FORMAT, "snapshot_sha256": file_hash(snapshot), "inventory": data,
              "restore_verified": True, "cutover_performed": False}
    # Publicado por último: falhas deixam diretório incompleto, sem substituir origem/destino.
    with (destination / "manifest.json").open("xb") as stream:
        stream.write(canonical(result))
    (destination / "manifest.json").chmod(0o600)
    return result


def verify_checkpoint(directory):
    directory = Path(directory)
    snapshot, metadata = directory / DATABASE_FILE, directory / "manifest.json"
    if any(path.is_symlink() or not path.is_file() for path in (snapshot, metadata)):
        raise CheckpointError("Checkpoint incompleto ou com links simbólicos.")
    if any((directory / (DATABASE_FILE + suffix)).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise CheckpointError("Checkpoint não é um snapshot SQLite autossuficiente.")
    expected = json.loads(metadata.read_text(encoding="ascii"))
    if expected.get("format") != FORMAT or expected.get("restore_verified") is not True or expected.get("cutover_performed") is not False:
        raise CheckpointError("Formato ou prova de restauração inválidos.")
    if expected.get("snapshot_sha256") != file_hash(snapshot) or expected.get("inventory") != inventory(snapshot):
        raise CheckpointError("Checkpoint divergente: dados, contagens, totais, IDs ou vínculos.")
    return expected


def restore_checkpoint(directory, destination):
    expected = verify_checkpoint(directory)
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    target = destination / "escritura.sqlite3"
    copy_consistent(Path(directory) / DATABASE_FILE, target)
    if inventory(target) != expected["inventory"]:
        raise CheckpointError("Restauração divergente; não ative esta cópia.")
    return expected


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "verify", "restore"))
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", nargs="?", type=Path)
    args = parser.parse_args()
    if args.action != "verify" and args.destination is None:
        parser.error("Informe um destino novo.")
    result = (verify_checkpoint(args.source) if args.action == "verify" else
              create_checkpoint(args.source, args.destination) if args.action == "create" else
              restore_checkpoint(args.source, args.destination))
    print(json.dumps({"format": result["format"], "snapshot_sha256": result["snapshot_sha256"],
                      "restore_verified": True, "cutover_performed": False}))


if __name__ == "__main__":
    main()
