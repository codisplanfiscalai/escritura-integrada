#!/usr/bin/env python3
"""Gera dois pacotes de implantação sem fontes, builds ou segredos predefinidos."""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from image_tools import ROOT, OPTIONAL_NAMES, read_json, sha256_file, validate_manifest, write_json


def deployment_env(manifest, environment):
    if environment not in {"production", "develop"}:
        raise ValueError("Ambiente de deploy inválido.")
    port = "8000" if environment == "production" else "8001"
    rows = ["# Gerado da publicação verificada. Não contém usuários/senhas predefinidos.",
            "# Tags imutáveis permitem docker load + --pull never; digests estão em images.json.",
            "COMPOSE_PROJECT_NAME=escritura-" + environment,
            "ESCRITURA_BIND=127.0.0.1", "ESCRITURA_PORT=" + port,
            "ESCRITURA_IMAGE=" + manifest["images"]["app"]["reference"], "ESCRITURA_COOKIE_SECURE=0", "",
            "# Serviços opcionais internos; o aplicativo permanece em SQLite."]
    for name in OPTIONAL_NAMES:
        rows.append(name.upper() + "_IMAGE=" + manifest["images"][name]["reference"])
    rows += ["", "# Preencha somente quando ativar o perfil correspondente; mínimo 16 caracteres por senha.",
             "REDIS_PASSWORD=", "POSTGRES_DB=escritura", "POSTGRES_USER=escritura", "POSTGRES_PASSWORD=",
             "MYSQL_DATABASE=escritura", "MYSQL_USER=escritura", "MYSQL_PASSWORD=", "MYSQL_ROOT_PASSWORD=",
             "MINIO_ROOT_USER=", "MINIO_ROOT_PASSWORD=", ""]
    return "\n".join(rows)


def readme(manifest, environment):
    port = "8000" if environment == "production" else "8001"
    version = manifest["version"]
    return f"""ESCRITURA INTEGRADA {version} — {environment}

Requisitos: Docker Engine/Desktop com containers Linux e Docker Compose v2.
Plataforma publicada: linux/amd64. Nenhum build ou código da aplicação no host.

INICIAR
1. Extraia este pacote em um diretório próprio.
2. Execute: docker compose up -d
3. Confira: docker compose ps
4. Abra http://127.0.0.1:{port} e crie o administrador no primeiro acesso.

Apenas a porta da aplicação é publicada, com bind loopback por padrão.
O .env já contém as tags da publicação. Não há senha padrão de administrador.
Não use volumes de produção em desenvolvimento.

GHCR E VISIBILIDADE
Pacotes GHCR novos podem ser privados. Se o pull exigir autenticação, faça
docker login ghcr.io com uma conta autorizada e token com read:packages.
A publicação não torna automaticamente as imagens públicas.
O manifesto images.json registra o resultado da sonda anônima, quando feita.

SEM ACESSO AO REGISTRO (IMAGENS OFFLINE)
Baixe também EscrituraIntegrada-{version}-linux-amd64-images.tar.gz e os hashes.
Confira o SHA-256 antes de carregar. Docker já deve estar instalado.
docker load -i /caminho/EscrituraIntegrada-{version}-linux-amd64-images.tar.gz
docker compose up -d --pull never

O bundle contém app, base Python, Redis, PostgreSQL, MySQL e MinIO.
São usadas tags imutáveis; images.json guarda digests e IDs para conferência.
Não depende de RepoDigests serem preservados por docker save/load.

PERFIS OPCIONAIS
O backend desta versão usa SQLite. Estes serviços ainda NÃO estão integrados:
redis, postgres, mysql, minio. Ativá-los não migra nem muda a base da aplicação.
Preencha no .env as variáveis do perfil desejado; senhas com ao menos 16 caracteres.
Redis: REDIS_PASSWORD.
PostgreSQL: POSTGRES_PASSWORD (usuário/banco configuráveis).
MySQL: MYSQL_ROOT_PASSWORD e MYSQL_PASSWORD (usuário/banco configuráveis).
MinIO: MINIO_ROOT_USER (mínimo 3) e MINIO_ROOT_PASSWORD.
Exemplo: docker compose --profile redis up -d
Offline: docker compose --profile redis up -d --pull never
As próprias imagens rejeitam credenciais ausentes com mensagem explícita.
Nenhuma porta de banco, S3 ou console MinIO é publicada no host.

DADOS E ATUALIZAÇÕES
O volume app-data é o SQLite persistente, com prefixo do projeto Compose.
Faça backup consistente e testado antes de atualizar. Nunca use down -v em dados
que deseja manter. Um rollback da imagem não desfaz migrações de banco.
Execute docker compose down para parar/remover containers preservando volumes.
As instruções completas estão em DEPLOY.md e THIRD-PARTY.md neste pacote.
"""


def package(manifest, output_dir, root=ROOT):
    validate_manifest(manifest)
    root, output_dir = Path(root), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for environment in ("production", "develop"):
        stem = "EscrituraIntegrada-" + manifest["version"] + "-" + environment + "-deploy"
        files = {
            "compose.yaml": (root / "deploy" / environment / "compose.yaml").read_bytes(),
            ".env": deployment_env(manifest, environment).encode(),
            ".env.example": deployment_env(manifest, environment).encode(),
            "images.json": (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(),
            "LEIA-ME.txt": readme(manifest, environment).encode(),
            "DEPLOY.md": (root / "docs/DEPLOY.md").read_bytes(),
            "THIRD-PARTY.md": (root / "docker/THIRD-PARTY.md").read_bytes(),
        }
        # Allowlist fechada: não inclui app/, banco, `.env` local, logs ou material recuperado.
        archive = output_dir / (stem + ".zip")
        temp = archive.with_suffix(".zip.part")
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for name, data in files.items():
                info = zipfile.ZipInfo(stem + "/" + name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100600 << 16 if name == ".env" else 0o100644 << 16
                bundle.writestr(info, data)
        temp.replace(archive)
        digest = sha256_file(archive)
        archive.with_suffix(".zip.sha256").write_text(digest + "  " + archive.name + "\n")
        outputs.append({"environment": environment, "file": archive.name, "sha256": digest, "bytes": archive.stat().st_size})
    summary = {"version": manifest["version"], "channel": manifest["channel"], "source_sha": manifest["source_sha"],
               "packages": outputs, "contains_source": False, "contains_fixed_credentials": False}
    write_json(output_dir / ("EscrituraIntegrada-" + manifest["version"] + "-deploy-manifest.json"), summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", choices=["production", "develop"], required=True)
    parser.add_argument("--images-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = read_json(args.images_manifest)
    if manifest["version"] != args.version or manifest["channel"] != args.channel:
        raise ValueError("Versão/canal não correspondem ao manifesto publicado.")
    summary = package(manifest, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as exc:
        print("ERRO: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
