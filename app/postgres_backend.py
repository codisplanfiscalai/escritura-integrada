"""Infraestrutura PostgreSQL nativa, ainda não conectada a create_app.

Não traduz SQL SQLite nem oferece fallback. Os serviços existentes precisam ser
portados e homologados antes da troca do banco do aplicativo/contêiner.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Iterable

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row


class PostgresConfigurationError(ValueError):
    """Configuração inválida, sem reproduzir credenciais na mensagem."""


class PostgresUnavailable(RuntimeError):
    """Conexão indisponível; detalhes do driver não cruzam esta fronteira."""


class MigrationHistoryError(RuntimeError):
    """Histórico ausente, divergente ou mais novo que a fonte disponível."""


@dataclass(frozen=True)
class PostgresSettings:
    dsn: str = field(repr=False)
    schema: str = "public"
    connect_timeout: int = 5
    statement_timeout_ms: int = 30_000
    lock_timeout_ms: int = 5_000

    def __post_init__(self):
        if not isinstance(self.dsn, str) or not self.dsn.strip():
            raise PostgresConfigurationError("Informe a conexão PostgreSQL explicitamente.")
        try:
            parameters = conninfo_to_dict(self.dsn)
        except (psycopg.Error, ValueError):
            raise PostgresConfigurationError("Conexão PostgreSQL inválida.") from None
        if parameters.get("service") or not all(parameters.get(k) for k in ("host", "dbname", "user")):
            raise PostgresConfigurationError("A conexão deve declarar host, dbname e user, sem service.")
        if not isinstance(self.schema, str) or not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", self.schema):
            raise PostgresConfigurationError("Nome de schema PostgreSQL inválido.")
        for value in (self.connect_timeout, self.statement_timeout_ms, self.lock_timeout_ms):
            if type(value) is not int or not 1 <= value <= 2_147_483_647:
                raise PostgresConfigurationError("Os limites de conexão e execução devem ser inteiros positivos.")


@dataclass(frozen=True)
class Migration:
    """SQL nativo e confiável, versionado na fonte; nunca SQL de uma requisição."""

    version: int
    name: str
    statements: tuple[str, ...]

    def __post_init__(self):
        if type(self.version) is not int or self.version < 1:
            raise ValueError("Versão de migração inválida.")
        if not isinstance(self.name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,99}", self.name):
            raise ValueError("Nome de migração inválido.")
        if not isinstance(self.statements, tuple) or not self.statements or any(
            not isinstance(statement, str) or not statement.strip() for statement in self.statements
        ):
            raise ValueError("Informe uma tupla não vazia de instruções SQL.")

    @property
    def checksum(self):
        encoded = json.dumps([self.version, self.name, self.statements], ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class PostgresDatabase:
    """Uma conexão por operação; commit único ou rollback de todos os efeitos.

    Parâmetros seguem o driver (%s), linhas são dicionários, IDs usam RETURNING.
    A transação não revalida a sessão/permissões do aplicativo: essa integração
    depende da migração dos serviços e de testes próprios antes de uso na API.
    """

    def __init__(self, settings: PostgresSettings):
        self.settings = settings

    def _connect(self):
        try:
            conn = psycopg.connect(self.settings.dsn, autocommit=True, row_factory=dict_row,
                                   connect_timeout=self.settings.connect_timeout,
                                   application_name="escritura-postgres-foundation")
        except psycopg.Error:
            raise PostgresUnavailable("Não foi possível conectar ao PostgreSQL.") from None
        if conn.info.server_version < 170000:
            conn.close()
            raise PostgresUnavailable("Este backend requer PostgreSQL 17 ou superior.")
        return conn

    @contextmanager
    def _operation(self, *, readonly=False, snapshot=False):
        with self._connect() as conn:
            with conn.transaction():
                if snapshot:
                    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                if readonly:
                    conn.execute("SET TRANSACTION READ ONLY")
                conn.execute("SELECT set_config('statement_timeout', %s, true)",
                             (str(self.settings.statement_timeout_ms),))
                conn.execute("SELECT set_config('lock_timeout', %s, true)",
                             (str(self.settings.lock_timeout_ms),))
                if conn.execute("SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname=%s",
                                (self.settings.schema,)).fetchone() is None:
                    raise PostgresConfigurationError("O schema PostgreSQL configurado não existe.")
                conn.execute(sql.SQL("SET LOCAL search_path TO {}, pg_catalog").format(
                    sql.Identifier(self.settings.schema)))
                conn.execute("SET LOCAL TIME ZONE 'UTC'")
                yield conn

    def transaction(self):
        return self._operation()

    def read(self, snapshot=False):
        return self._operation(readonly=True, snapshot=snapshot)

    def apply_migrations(self, migrations: Iterable[Migration]):
        """Aplica uma sequência completa em transação, com trava entre processos.

        Versões aplicadas devem ser prefixo exato da fonte. Alterar SQL já aplicado,
        omitir versões ou executar uma fonte antiga é erro; nunca há downgrade.
        Nenhuma tabela de domínio é criada implicitamente pelo construtor.
        """
        migrations = tuple(migrations)
        if any(not isinstance(migration, Migration) for migration in migrations):
            raise ValueError("Migrações devem ser instâncias de Migration.")
        if [migration.version for migration in migrations] != list(range(1, len(migrations) + 1)):
            raise ValueError("Migrações devem ser sequenciais a partir da versão 1.")
        with self.transaction() as conn:
            # Chave fixa no banco: inclusive a criação do histórico fica serializada.
            # A trava pertence à transação e é liberada também em falha/timeout.
            conn.execute("SELECT pg_advisory_xact_lock(1163084626, 1)")
            conn.execute("""CREATE TABLE IF NOT EXISTS _escritura_migrations (
                version integer PRIMARY KEY CHECK(version > 0), name text NOT NULL,
                checksum text NOT NULL CHECK(length(checksum) = 64),
                applied_at timestamptz NOT NULL DEFAULT transaction_timestamp())""")
            history = conn.execute("SELECT version,name,checksum FROM _escritura_migrations ORDER BY version").fetchall()
            expected = [{"version": m.version, "name": m.name, "checksum": m.checksum}
                        for m in migrations[:len(history)]]
            if history != expected:
                raise MigrationHistoryError("Histórico PostgreSQL incompatível com as migrações disponíveis.")
            applied = []
            for migration in migrations[len(history):]:
                for statement in migration.statements:
                    conn.execute(statement)
                conn.execute("INSERT INTO _escritura_migrations(version,name,checksum) VALUES(%s,%s,%s)",
                             (migration.version, migration.name, migration.checksum))
                applied.append(migration.version)
            return tuple(applied)
